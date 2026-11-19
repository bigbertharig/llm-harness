"""Contract checks for benchmark-gated helper selection and direct fallback."""

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tool_helper_policy", ROOT / "tools/tool_helper_policy.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_catalog_has_no_untested_default_helper():
    policy = module.load_policy()
    for task in policy["tasks"].values():
        assert task["preferred_candidates"] == []
    assert module.choose_executor("workspace_lookup", policy, {"candidates": []})["executor"] == "direct_tools"


def test_evidence_gates_selection_and_capacity_falls_back(tmp_path):
    policy = module.load_policy()
    task = policy["tasks"]["workspace_lookup"]
    task["preferred_candidates"] = [{"candidate_id": "small_helper", "benchmark_receipt": "bench/123"}]
    offers = {"candidates": [{"candidate_id": "small_helper", "agent_types": ["coding"],
                              "loaded": True, "available_worker_slots": 1}]}
    chosen = module.choose_executor("workspace_lookup", policy, offers)
    assert chosen["executor"] == "helper" and chosen["candidate_id"] == "small_helper"
    assert chosen["tool_profile"] == "workspace_read"
    offers["candidates"][0]["available_worker_slots"] = 0
    assert module.choose_executor("workspace_lookup", policy, offers)["executor"] == "direct_tools"
    path = tmp_path / "policy.json"
    task["preferred_candidates"] = [{"candidate_id": "small_helper", "benchmark_receipt": ""}]
    path.write_text(json.dumps(policy))
    try:
        module.load_policy(path)
    except ValueError as exc:
        assert "benchmark evidence" in str(exc)
    else:
        raise AssertionError("unproven helper was accepted")


def test_unlisted_tools_cannot_be_granted(tmp_path):
    policy = module.load_policy()
    policy["tasks"]["workspace_lookup"]["allowed_tools"].append("local_control.run_shell")
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy))
    try:
        module.load_policy(path)
    except ValueError as exc:
        assert "unapproved tools" in str(exc)
    else:
        raise AssertionError("unapproved tool was accepted")
