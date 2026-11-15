"""The rig information MCP keeps dashboard status bounded and read-only."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/rig_info_mcp.py"
spec = importlib.util.spec_from_file_location("rig_info_mcp", SCRIPT)
rig_info = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rig_info)


def test_tool_list_and_loopback_boundary():
    packet = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
    run = subprocess.run([sys.executable, str(SCRIPT)], input=packet, text=True,
                         capture_output=True, timeout=10)
    assert run.returncode == 0, run.stderr
    names = [tool["name"] for tool in json.loads(run.stdout)["result"]["tools"]]
    assert names == [name for name, _ in rig_info.TOOLS]
    for bad in ("https://example.com", "http://10.0.0.2:8080", "http://127.0.0.1:8080/other"):
        try:
            rig_info.endpoint(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted non-loopback dashboard endpoint: {bad}")


def test_status_projection_drops_unbounded_plan_and_preserves_heartbeat():
    status = {"observed_at": "2026-11-14T12:00:00", "mode": "idle", "summary": {"free": 5},
              "guard": {"level": "ok", "loads_admitted": True},
              "gpu_scan": {"ok": True, "ids": [0], "errors": []},
              "gpus": [{"gpu": 0, "verdict": "busy", "observed": {"secret": "noise"}}],
              "plan": {"items": [{"args": {"env": {"TOKEN": "must not leak"}}}]},
              "jobs": [], "controller": {"in_control": True,
              "active": {"id": "pi", "heartbeat_at": "2026-11-14T12:00:00Z", "stale": False}},
              "rig": {"reachable": True}}
    compact = rig_info.project("get_rig_status", status)
    assert compact["summary"] == {"free": 5}
    assert compact["gpus"] == [{"gpu": 0, "name": None, "verdict": "busy", "claim": None,
                                "vram_mb": None}]
    assert "TOKEN" not in json.dumps(compact)
    assert compact["controller"]["id"] == "pi" and compact["controller"]["stale"] is False
    assert isinstance(compact["controller"]["heartbeat_age_seconds"], int)
    assert compact["rig"]["reachable"] is True
    assert compact["gpu_scan"] == {"ok": True, "ids": [0], "errors": []}
    assert "check_rig_heartbeats" not in [name for name, _ in rig_info.TOOLS]
