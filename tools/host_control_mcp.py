#!/usr/bin/env python3
"""Explicit host command tools for trusted local dashboard models."""
import argparse
import ipaddress
import json
import subprocess
import sys

WORKERS = {f"worker-{n}": f"10.0.0.{n}" for n in range(11, 18)}
LOCAL = {"pi": None, "rig": "10.0.0.3", **WORKERS}
LOCAL_TOOL = {"name": "run_local_command",
    "description": "Run a command on the Pi, GPU rig, or a named CPU worker. This is broad trusted local control; sudo is available. Use only when the user asks for an action or investigation.",
    "inputSchema": {"type": "object", "properties": {
        "target": {"type": "string", "enum": list(LOCAL)},
        "command": {"type": "string", "minLength": 1, "maxLength": 4000},
        "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120}},
        "required": ["target", "command"], "additionalProperties": False}}
FULL_TOOL = {"name": "run_private_command",
    "description": "Run a command over SSH on another 10.0.0.0/24 device with an already trusted host key. Requires Full private-network access.",
    "inputSchema": {"type": "object", "properties": {
        "host": {"type": "string", "description": "IPv4 address in 10.0.0.0/24"},
        "command": {"type": "string", "minLength": 1, "maxLength": 4000},
        "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120}},
        "required": ["host", "command"], "additionalProperties": False}}

def run(name, args, scope):
    if not isinstance(args, dict) or set(args) - {"target", "host", "command", "timeout_seconds"}:
        raise ValueError("invalid command arguments")
    command = args.get("command")
    timeout = args.get("timeout_seconds", 60)
    if not isinstance(command, str) or not 1 <= len(command) <= 4000 or type(timeout) is not int or not 1 <= timeout <= 120:
        raise ValueError("invalid command or timeout")
    if name == "run_local_command" and scope == "local":
        if set(args) - {"target", "command", "timeout_seconds"} or args.get("target") not in LOCAL:
            raise ValueError("choose pi, rig, or a named CPU worker")
        target = args["target"]
        argv = ["/bin/bash", "-lc", command] if target == "pi" else [
            "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=8", f"bryan@{LOCAL[target]}", command]
    elif name == "run_private_command" and scope == "full":
        if set(args) - {"host", "command", "timeout_seconds"}:
            raise ValueError("invalid private command arguments")
        try: host = ipaddress.IPv4Address(args.get("host"))
        except (ipaddress.AddressValueError, TypeError): raise ValueError("invalid private host")
        if host not in ipaddress.IPv4Network("10.0.0.0/24") or int(host) & 255 in (0, 255):
            raise ValueError("host must be a device in 10.0.0.0/24")
        target = str(host)
        argv = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                "-o", "ConnectTimeout=8", f"bryan@{target}", command]
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
    scope = parser.parse_args().scope
    tools = [LOCAL_TOOL] if scope == "local" else [FULL_TOOL]
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
                    result = run(params.get("name"), params.get("arguments"), scope)
                    respond(identifier, {"content": [{"type": "text", "text": json.dumps(result)}]})
                except ValueError as exc:
                    respond(identifier, {"isError": True, "content": [{"type": "text", "text": str(exc)}]})
            else: respond(identifier, {})
        except (ValueError, TypeError, AttributeError) as exc:
            if 'identifier' in locals() and identifier is not None:
                respond(identifier, {"isError": True, "content": [{"type": "text", "text": str(exc)}]})

if __name__ == "__main__": main()
