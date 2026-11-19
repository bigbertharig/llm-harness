#!/usr/bin/env python3
"""Explicit host command tools for trusted local dashboard models."""
import argparse
import ipaddress
import json
import os
import subprocess
import sys
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("HOST_CONTROL_CONFIG_PATH") or
                   (Path.home() / ".config/llm-harness/host-control.json"))


def load_config(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"local_targets", "private_cidr", "ssh_user"}:
        raise ValueError("invalid host-control config")
    targets = data["local_targets"]
    if not isinstance(targets, dict) or not targets or "pi" not in targets or targets["pi"] is not None:
        raise ValueError("host-control config requires local pi target")
    if any(not isinstance(name, str) or not name or
           (host is not None and (not isinstance(host, str) or not host))
           for name, host in targets.items()):
        raise ValueError("invalid host-control target")
    for name, host in targets.items():
        if name != "pi" and host is None:
            raise ValueError("remote target requires an address")
    network = ipaddress.ip_network(data["private_cidr"], strict=True)
    if not isinstance(network, ipaddress.IPv4Network) or network.is_global or network.prefixlen < 16:
        raise ValueError("private control requires a bounded private IPv4 network")
    user = data["ssh_user"]
    if not isinstance(user, str) or not user or not all(ch.isalnum() or ch in "_-" for ch in user):
        raise ValueError("invalid SSH user")
    return {"local_targets": targets, "private_network": network, "ssh_user": user}


LOCAL_TOOL = {"name": "run_local_command",
    "description": "Run a command on the Pi, GPU rig, or a named CPU worker. This is broad trusted local control; sudo is available. Use only when the user asks for an action or investigation.",
    "inputSchema": {"type": "object", "properties": {
        "target": {"type": "string"},
        "command": {"type": "string", "minLength": 1, "maxLength": 4000},
        "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120}},
        "required": ["target", "command"], "additionalProperties": False}}
FULL_TOOL = {"name": "run_private_command",
    "description": "Run a command over SSH on a device in the configured private network with an already trusted host key. Requires Full private-network access.",
    "inputSchema": {"type": "object", "properties": {
        "host": {"type": "string", "description": "IPv4 address in the configured private network"},
        "command": {"type": "string", "minLength": 1, "maxLength": 4000},
        "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120}},
        "required": ["host", "command"], "additionalProperties": False}}

def run(name, args, scope, config):
    if not isinstance(args, dict) or set(args) - {"target", "host", "command", "timeout_seconds"}:
        raise ValueError("invalid command arguments")
    command = args.get("command")
    timeout = args.get("timeout_seconds", 60)
    if not isinstance(command, str) or not 1 <= len(command) <= 4000 or type(timeout) is not int or not 1 <= timeout <= 120:
        raise ValueError("invalid command or timeout")
    if name == "run_local_command" and scope == "local":
        if set(args) - {"target", "command", "timeout_seconds"} or args.get("target") not in config["local_targets"]:
            raise ValueError("choose a configured local target")
        target = args["target"]
        argv = ["/bin/bash", "-lc", command] if target == "pi" else [
            "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=8", f"{config['ssh_user']}@{config['local_targets'][target]}", command]
    elif name == "run_private_command" and scope == "full":
        if set(args) - {"host", "command", "timeout_seconds"}:
            raise ValueError("invalid private command arguments")
        try: host = ipaddress.IPv4Address(args.get("host"))
        except (ipaddress.AddressValueError, TypeError): raise ValueError("invalid private host")
        if host not in config["private_network"] or host in (
                config["private_network"].network_address,
                config["private_network"].broadcast_address):
            raise ValueError("host must be a device in the configured private network")
        target = str(host)
        argv = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                "-o", "ConnectTimeout=8", f"{config['ssh_user']}@{target}", command]
    else:
        raise ValueError("tool is unavailable in this access mode")
    try:
        result = subprocess.run(argv, text=True, capture_output=True, timeout=timeout, errors="replace")
    except subprocess.TimeoutExpired:
        raise ValueError("command timed out")
    return {"target": target, "exit_code": result.returncode,
            "stdout": result.stdout[:20000], "stderr": result.stderr[:10000],
            "truncated": len(result.stdout) > 20000 or len(result.stderr) > 10000}

def respond(identifier, result):
    print(json.dumps({"jsonrpc": "2.0", "id": identifier, "result": result}), flush=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", choices=("local", "full"), required=True)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    options = parser.parse_args()
    scope = options.scope
    config = load_config(options.config)
    local_tool = {**LOCAL_TOOL, "inputSchema": {**LOCAL_TOOL["inputSchema"],
                  "properties": {**LOCAL_TOOL["inputSchema"]["properties"],
                                 "target": {"type": "string", "enum": list(config["local_targets"])}}}}
    tools = [local_tool] if scope == "local" else [FULL_TOOL]
    for line in sys.stdin:
        try:
            packet = json.loads(line)
            identifier = packet.get("id")
            if identifier is None: continue
            method = packet.get("method")
            if method == "initialize":
                respond(identifier, {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                                     "serverInfo": {"name": "host-control", "version": "0.1.0"}})
            elif method == "ping": respond(identifier, {})
            elif method == "tools/list": respond(identifier, {"tools": tools})
            elif method == "tools/call":
                params = packet.get("params") or {}
                try:
                    if not isinstance(params, dict): raise ValueError("invalid tool call")
                    result = run(params.get("name"), params.get("arguments"), scope, config)
                    respond(identifier, {"content": [{"type": "text", "text": json.dumps(result)}]})
                except ValueError as exc:
                    respond(identifier, {"isError": True, "content": [{"type": "text", "text": str(exc)}]})
            else: respond(identifier, {})
        except (ValueError, TypeError, AttributeError) as exc:
            if 'identifier' in locals() and identifier is not None:
                respond(identifier, {"isError": True, "content": [{"type": "text", "text": str(exc)}]})

if __name__ == "__main__": main()
