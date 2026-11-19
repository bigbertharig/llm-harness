"""Choose a benchmark-approved helper for a bounded tool task.

This module makes a routing decision. It never executes tools, loads models,
or assigns GPUs. A caller may delegate using the returned candidate and tool
profile, or expose the direct tools to the controlling chat on fallback.
"""

from __future__ import annotations

import json
from pathlib import Path


POLICY = Path(__file__).with_name("tool_helper_policy.json")
REGISTRY = Path(__file__).with_name("tool_registry.json")


def load_policy(path: Path = POLICY, registry_path: Path = REGISTRY) -> dict:
    policy = json.loads(path.read_text(encoding="utf-8"))
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if policy.get("schema_version") != 1 or not isinstance(policy.get("tasks"), dict):
        raise ValueError("unsupported helper policy")
    for task_key, task in policy["tasks"].items():
        if not isinstance(task_key, str) or not task_key.isidentifier() or not isinstance(task, dict):
            raise ValueError("invalid helper task")
        if task.get("agent_type") not in ("coding", "research") or task.get("tool_profile") not in (
                "workspace_read", "public_research") or task.get("fallback") != "direct_tools":
            raise ValueError(f"invalid helper task contract: {task_key}")
        tools = task.get("allowed_tools")
        if not isinstance(tools, list) or not tools or len(tools) != len(set(tools)):
            raise ValueError(f"invalid allowed tools: {task_key}")
        expected_surface = "workspace_read" if task["tool_profile"] == "workspace_read" else "rig_search"
        surface = registry["surfaces"][expected_surface]
        approved = {f"{expected_surface}.{row['name']}" for row in surface["tools"]
                    if row.get("approval") == "automatic"}
        if not set(tools) <= approved:
            raise ValueError(f"helper task has unapproved tools: {task_key}")
        candidates = task.get("preferred_candidates")
        if not isinstance(candidates, list) or len(candidates) != len({
                row.get("candidate_id") for row in candidates if isinstance(row, dict)}):
            raise ValueError(f"invalid helper candidates: {task_key}")
        for row in candidates:
            if (not isinstance(row, dict) or set(row) != {"candidate_id", "benchmark_receipt"}
                    or not isinstance(row["candidate_id"], str) or not row["candidate_id"]
                    or not isinstance(row["benchmark_receipt"], str) or not row["benchmark_receipt"]):
                raise ValueError(f"candidate lacks benchmark evidence: {task_key}")
        if type(task.get("allow_cold_load")) is not bool:
            raise ValueError(f"invalid cold-load policy: {task_key}")
    return policy


def choose_executor(task_key: str, policy: dict, capabilities: dict) -> dict:
    """Prefer the first approved capable offer; return a visible direct fallback."""
    task = policy["tasks"].get(task_key)
    if task is None:
        raise ValueError("unknown helper task")
    offers = {row.get("candidate_id"): row for row in capabilities.get("candidates", [])
              if isinstance(row, dict) and isinstance(row.get("candidate_id"), str)}
    for approved in task["preferred_candidates"]:
        candidate_id = approved["candidate_id"]
        offer = offers.get(candidate_id)
        if not offer or task["agent_type"] not in offer.get("agent_types", []):
            continue
        loaded = offer.get("loaded") is True
        slots = offer.get("available_worker_slots")
        if loaded and type(slots) is int and slots < 1:
            continue
        if not loaded and not task["allow_cold_load"]:
            continue
        return {"executor": "helper", "task_type": task_key,
                "candidate_id": candidate_id, "agent_type": task["agent_type"],
                "tool_profile": task["tool_profile"],
                "allowed_tools": list(task["allowed_tools"]),
                "benchmark_receipt": approved["benchmark_receipt"]}
    return {"executor": "direct_tools", "task_type": task_key,
            "allowed_tools": list(task["allowed_tools"]),
            "reason": "no benchmark-approved helper is available"}
