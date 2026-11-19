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
    ]
    run = subprocess.run([sys.executable, str(SCRIPT)],
                         input="\n".join(map(json.dumps, packets)) + "\n",
                         text=True, capture_output=True, timeout=5)
    assert run.returncode == 0, run.stderr
    rows = [json.loads(line) for line in run.stdout.splitlines()]
    assert {row["name"] for row in rows[0]["result"]["tools"]} == {
        "search_mail", "read_mail", "search_drive", "read_drive_text"}
    assert rows[1]["result"]["isError"] is True
