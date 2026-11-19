"""The Google MCP surface stays model-independent and validates before I/O."""

import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "tools/google_workspace_mcp.py"


def test_tools_and_invalid_request():
    packets = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "read_mail", "arguments": {"message_id": "../../token.json"}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "send_email", "arguments": {
             "to": "test@example.com", "subject": "test", "body": "body",
             "request_id": "email-test-001", "confirmed": False}}},
    ]
    run = subprocess.run([sys.executable, str(SCRIPT)],
                         input="\n".join(map(json.dumps, packets)) + "\n",
                         text=True, capture_output=True, timeout=5)
    assert run.returncode == 0, run.stderr
    rows = [json.loads(line) for line in run.stdout.splitlines()]
    assert {row["name"] for row in rows[0]["result"]["tools"]} == {
        "search_mail", "read_mail", "send_email", "search_drive", "read_drive_text",
        "create_drive_folder", "upload_drive_text", "create_google_doc",
        "append_google_doc_text", "create_google_sheet", "read_google_sheet",
        "update_google_sheet", "append_google_sheet_rows"}
    assert rows[1]["result"]["isError"] is True
    assert rows[2]["result"]["isError"] is True
    send = next(tool for tool in rows[0]["result"]["tools"] if tool["name"] == "send_email")
    assert send["inputSchema"]["properties"]["confirmed"]["const"] is True
