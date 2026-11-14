"""Published dashboard tools must match the harness MCP tools/list surface."""

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_tool_catalog_matches_mcp_servers(tmp_path):
    catalog = json.loads((ROOT / "tools/dashboard_tool_catalog.json").read_text())
    commands = {
        "local_agents": [sys.executable, str(ROOT / "tools/gateway_subagent_mcp.py"),
                         "--cloud-parent", "--receipt-dir", str(tmp_path)],
        "rig_search": [sys.executable, str(ROOT / "mcp_servers/rig_search/mcp_server.py")],
    }
    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
    for server, command in commands.items():
        run = subprocess.run(command, input=request, text=True, capture_output=True, timeout=10)
        assert run.returncode == 0, run.stderr
        actual = [tool["name"] for tool in json.loads(run.stdout)["result"]["tools"]]
        published = [tool["name"] for tool in catalog["servers"][server]["tools"]]
        assert actual == published
