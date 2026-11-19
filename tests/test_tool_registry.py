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
    assert set(surfaces) == {"local_agents", "gateway_reset", "google_workspace", "github_public", "rig_search", "rig_info", "workspace_read", "workspace_git",
                             "local_control", "private_control", "local_rag_fixture", "daedalmap",
                             "deepwiki", "openai_docs", "cloudflare_docs"}
    assert sum(len(surface["tools"]) for surface in surfaces.values()) == 51
    for name, surface in surfaces.items():
        assert surface["tools"] or surface["status"] == "discovery_pending", name
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
    assert set(published["servers"]) == {"local_agents", "gateway_reset", "google_workspace", "github_public", "rig_search", "rig_info",
                                         "workspace_read", "workspace_git", "local_control", "private_control"}


def test_tool_categories_and_live_daedalmap_discovery():
    files = ("tool_registry.json", "tool_fixtures.json")
    categories = [json.loads((ROOT / "tools" / name).read_text())["surfaces"] for name in files]
    assert [sum(len(surface["tools"]) for surface in group.values()) for group in categories] == [51, 6]
    names = [name for group in categories for name in group]
    assert len(names) == len(set(names))
    assert categories[0]["daedalmap"]["category"] == "external"
    assert categories[0]["daedalmap"]["implementation"] == "https://app.daedalmap.com/mcp?registry=site"
    assert categories[0]["daedalmap"]["observed_version"] == "0.4.0"
    assert {surface["category"] for surface in categories[0].values()} == {
        "search", "local_info", "delegate", "external", "diagnostics"}
    assert {surface["origin"] for surface in categories[0].values()} == {"internal", "external"}
    assert categories[0]["google_workspace"]["family"] == "google"
    assert categories[0]["google_workspace"]["source_bundle"] == "google"
    assert categories[0]["workspace_git"]["family"] == "internal"
    registry = json.loads((ROOT / "tools/tool_registry.json").read_text())
    assert {"internal", "google", "github", "codex", "claude"} <= set(registry["bundles"])
    assert set(tool["name"] for tool in categories[0]["rig_search"]["tools"]) == {
        "search_web", "fetch_page", "search_fixture_web", "fetch_fixture_page"}
    assert set(tool["name"] for tool in categories[0]["local_agents"]["tools"]) == {
        "list_local_agents", "delegate_task", "delegate_fixture_task"}
    assert set(tool["name"] for tool in categories[0]["workspace_read"]["tools"]) == {
        "list_workspace_files", "find_workspace_files", "read_workspace_file", "search_workspace_text"}


def test_diagnostics_profiles_match_registry(tmp_path):
    registry = json.loads((ROOT / "tools/tool_fixtures.json").read_text())["surfaces"]
    script = ROOT / "tools/fixtures/diagnostics_mcp.mjs"
    expected = [tool["name"] for tool in registry["diagnostics"]["tools"]]
    for profile in ("marker", "numeric", "lookup", "all"):
        run = subprocess.run(["node", str(script), profile, str(tmp_path / f"{profile}.jsonl")],
                             input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n",
                             text=True, capture_output=True, timeout=10)
        assert run.returncode == 0, run.stderr
        actual = [tool["name"] for tool in json.loads(run.stdout)["result"]["tools"]]
        assert actual == (expected if profile == "all" else [name for name in expected if name in {
            "marker": {"read_marker", "read_structured_marker"},
            "numeric": {"calculate_sum", "calculate_product"},
            "lookup": {"get_entry", "get_nested_entry"},
        }[profile]])


def test_diagnostics_combined_surface_preserves_result_shapes(tmp_path):
    script = ROOT / "tools/fixtures/diagnostics_mcp.mjs"
    calls = [
        ("read_marker", {}), ("read_structured_marker", {}),
        ("calculate_sum", {"a": 17, "b": 28}),
        ("calculate_product", {"a": 6, "b": 7}),
        ("get_entry", {"key": "alpha"}),
        ("get_nested_entry", {"key": "beta"}),
    ]
    packets = [json.dumps({"jsonrpc": "2.0", "id": index, "method": "tools/call",
                           "params": {"name": name, "arguments": arguments}})
               for index, (name, arguments) in enumerate(calls, 1)]
    run = subprocess.run(["node", str(script), "all", str(tmp_path / "all.jsonl")],
                         input="\n".join(packets) + "\n", text=True, capture_output=True, timeout=10)
    assert run.returncode == 0, run.stderr
    results = [json.loads(line)["result"] for line in run.stdout.splitlines()]
    assert len(results) == 6 and all(not result["isError"] for result in results)
    assert results[0]["content"][0]["text"] == results[0]["structuredContent"]["marker"]
    assert results[1]["content"] == [] and results[1]["structuredContent"]["marker"].startswith("MCP-STRUCT-")
    assert [result["structuredContent"]["value"] for result in results[2:4]] == [45, 42]
    assert results[4]["content"][0]["text"] == results[4]["structuredContent"]["receipt"]
    assert results[5]["content"] == [] and results[5]["structuredContent"]["entry"]["key"] == "beta"
