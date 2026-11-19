#!/usr/bin/env python3
"""Narrow MCP tool that restarts the dashboard gateway and resumes one saved Codex chat."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from urllib.request import Request, urlopen
from uuid import uuid4


def atomic_json(path: Path, value: dict) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def turn_state(database: Path, conversation_id: str) -> str | None:
    with sqlite3.connect(database) as db:
        row = db.execute(
            "SELECT state FROM turns WHERE conversation_id=? "
            "ORDER BY created_at DESC,rowid DESC LIMIT 1", (conversation_id,)).fetchone()
    return row[0] if row else None


def worker(args) -> int:
    request_path = Path(args.request_path).resolve()
    request_doc = json.loads(request_path.read_text(encoding="utf-8"))
    database = Path(args.data_root).resolve() / "conversations.sqlite3"
    deadline = time.monotonic() + args.wait_seconds
    while time.monotonic() < deadline and turn_state(database, args.conversation_id) == "running":
        time.sleep(1)
    request_doc.update(state="restarting", restarted_at=time.time())
    atomic_json(request_path, request_doc)
    result = subprocess.run(["sudo", "-n", "systemctl", "restart", "pi-gateway.service"],
                            text=True, capture_output=True)
    if result.returncode:
        request_doc.update(state="failed", error=(result.stderr or result.stdout).strip()[-500:])
        atomic_json(request_path, request_doc)
        return 1
    health_deadline = time.monotonic() + 60
    while time.monotonic() < health_deadline:
        try:
            with urlopen("http://127.0.0.1:8080/health", timeout=2) as response:
                if response.status == 200:
                    break
        except OSError:
            pass
        time.sleep(1)
    else:
        request_doc.update(state="failed", error="gateway did not become healthy within 60 seconds")
        atomic_json(request_path, request_doc)
        return 1
    prompt = ("The requested gateway restart completed. Resume the work that was in progress before "
              "the restart. Inspect the saved thread and current workspace state first; do not repeat "
              "completed edits.\n\nRecovery note: " + request_doc["recovery_note"])
    payload = json.dumps({"model": "Codex", "message": prompt}).encode()
    try:
        with urlopen(Request(
                "http://127.0.0.1:8080/dashboard/api/chat/conversations/" +
                args.conversation_id + "/turn", data=payload,
                headers={"Content-Type": "application/json"}, method="POST"), timeout=15) as response:
            accepted = json.load(response)
    except Exception as exc:
        request_doc.update(state="failed", error=f"resume request failed: {type(exc).__name__}: {exc}")
        atomic_json(request_path, request_doc)
        return 1
    request_doc.update(state="resumed", resumed_at=time.time(), turn_id=accepted.get("turn_id"))
    atomic_json(request_path, request_doc)
    return 0


def schedule(args, arguments: dict) -> dict:
    if arguments.get("confirmation") != "restart pi-gateway":
        raise ValueError('confirmation must be exactly "restart pi-gateway"')
    note = arguments.get("recovery_note")
    if not isinstance(note, str) or not 1 <= len(note) <= 1000:
        raise ValueError("recovery_note must describe what to continue in 1..1000 characters")
    root = Path(args.data_root).resolve()
    database = root / "conversations.sqlite3"
    if not database.is_file() or not args.conversation_id.isalnum():
        raise ValueError("saved conversation is unavailable")
    with sqlite3.connect(database) as db:
        row = db.execute("SELECT provider,thread_id FROM conversations WHERE id=?",
                         (args.conversation_id,)).fetchone()
    if not row or row[0] != "codex" or not row[1]:
        raise ValueError("reset recovery requires an existing Codex thread")
    request_id = uuid4().hex
    request_dir = root / "reset-requests"
    request_dir.mkdir(mode=0o700, exist_ok=True)
    request_path = request_dir / f"{request_id}.json"
    atomic_json(request_path, {"reset_id": request_id, "conversation_id": args.conversation_id,
        "thread_id": row[1], "state": "scheduled", "requested_at": time.time(),
        "recovery_note": note})
    unit = "llm-gateway-reset-" + request_id[:12]
    command = ["sudo", "-n", "systemd-run", "--quiet", "--collect", "--unit", unit,
        "--uid", str(os.getuid()), sys.executable, str(Path(__file__).resolve()), "--worker",
        "--conversation-id", args.conversation_id, "--data-root", str(root),
        "--request-path", str(request_path), "--wait-seconds", str(args.wait_seconds)]
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode:
        doc = json.loads(request_path.read_text(encoding="utf-8"))
        doc.update(state="failed", error=(result.stderr or result.stdout).strip()[-500:])
        atomic_json(request_path, doc)
        raise RuntimeError(doc["error"] or "could not schedule recovery unit")
    return {"scheduled": True, "reset_id": request_id, "unit": unit,
            "message": "Restart is scheduled. Finish this response promptly; recovery will continue the saved thread."}


def serve(args) -> int:
    tool = {"name": "restart_gateway_and_resume",
        "description": ("Restart pi-gateway and automatically continue this saved Codex conversation. "
                        "Use only when the user explicitly asks for a gateway restart. The request is durable "
                        "and recovery runs outside the service being restarted."),
        "inputSchema": {"type": "object", "properties": {
            "confirmation": {"type": "string", "enum": ["restart pi-gateway"]},
            "recovery_note": {"type": "string", "minLength": 1, "maxLength": 1000}},
            "required": ["confirmation", "recovery_note"], "additionalProperties": False}}
    for line in sys.stdin:
        try:
            packet = json.loads(line)
            request_id, method = packet.get("id"), packet.get("method")
            if request_id is None:
                continue
            if method == "initialize":
                result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "gateway-reset", "version": "0.1.0"}}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": [tool]}
            elif method == "tools/call" and (packet.get("params") or {}).get("name") == tool["name"]:
                try:
                    value = schedule(args, (packet.get("params") or {}).get("arguments") or {})
                    result = {"content": [{"type": "text", "text": json.dumps(value)}],
                              "structuredContent": value}
                except Exception as exc:
                    result = {"isError": True, "content": [{"type": "text",
                              "text": f"{type(exc).__name__}: {exc}"}]}
            else:
                result = {"isError": True, "content": [{"type": "text", "text": "unsupported request"}]}
            print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}), flush=True)
        except (ValueError, TypeError):
            continue
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conversation-id", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--wait-seconds", type=int, default=180)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--request-path")
    args = parser.parse_args()
    if not 5 <= args.wait_seconds <= 300:
        parser.error("--wait-seconds must be 5..300")
    if args.worker:
        if not args.request_path:
            parser.error("--worker requires --request-path")
        return worker(args)
    return serve(args)


if __name__ == "__main__":
    raise SystemExit(main())
