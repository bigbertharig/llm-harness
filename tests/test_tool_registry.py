"""The full harness tool registry and dashboard projection stay in sync."""

import importlib.util
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/export_dashboard_tool_catalog.py"
spec = importlib.util.spec_from_file_location("export_dashboard_tools", SCRIPT)
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


def test_registry_has_every_known_surface_and_existing_harness_code():
    registry = json.loads((ROOT / "tools/tool_registry.json").read_text())
    surfaces = registry["surfaces"]
    assert len(surfaces) == 16
    assert sum(len(surface["tools"]) for surface in surfaces.values()) == 42
    for name, surface in surfaces.items():
        assert surface["tools"], name
        names = [tool["name"] for tool in surface["tools"]]
        assert len(names) == len(set(names)), name
        if surface["owner"] == "llm-harness":
            implementation = surface["implementation"].split(" ", 1)[0]
            assert (ROOT / implementation).is_file(), implementation


def test_dashboard_catalog_is_generated_from_registry():
    registry = json.loads((ROOT / "tools/tool_registry.json").read_text())
    expected = export.build(registry)
    published = json.loads((ROOT / "tools/dashboard_tool_catalog.json").read_text())
    assert published == expected
    assert set(published["servers"]) == {"local_agents", "rig_search"}


def test_matrix_fixture_profiles_match_registry(tmp_path):
    registry = json.loads((ROOT / "tools/tool_registry.json").read_text())["surfaces"]
    script = ROOT / "tools/fixtures/local_mcp_matrix.mjs"
    for profile in ("numeric", "lookup"):
        run = subprocess.run(["node", str(script), profile, str(tmp_path / f"{profile}.jsonl")],
                             input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n",
                             text=True, capture_output=True, timeout=10)
        assert run.returncode == 0, run.stderr
        actual = [tool["name"] for tool in json.loads(run.stdout)["result"]["tools"]]
        assert actual == [tool["name"] for tool in registry[f"{profile}_fixture"]["tools"]]
