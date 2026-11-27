"""Public in-process engine boundary for a standalone Harness installation."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from harness_core.providers import validate_direct_provider
from harness_core.run_api import RunAPI

SCHEMA = "harness-engine/1"
TERMINAL = {"succeeded", "failed", "cancelled", "incomplete"}


class InProcessEngine:
    def __init__(self, runner: Callable, *, name: str, version: str):
        if not callable(runner):
            raise ValueError("engine runner must be callable")
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,96}", name):
            raise ValueError("invalid engine name")
        if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?", version):
            raise ValueError("invalid engine version")
        self.runner = runner
        self.name = name
        self.version = version

    def __call__(self, **kwargs):
        contract = kwargs.pop("engine_contract", None)
        if contract != SCHEMA:
            raise ValueError("unsupported engine contract")
        receipt = self.runner(**kwargs)
        if not isinstance(receipt, dict) or not isinstance(receipt.get("run"), dict):
            raise ValueError("engine returned no canonical run receipt")
        if receipt["run"].get("phase") not in TERMINAL:
            raise ValueError("engine returned a nonterminal run receipt")
        if receipt["run"].get("run_id") != kwargs.get("run_id"):
            raise ValueError("engine receipt run identity mismatch")
        return {**receipt, "engine": {"schema": SCHEMA, "name": self.name,
                                      "version": self.version}}


def project_agent_engine() -> InProcessEngine:
    from project_agent import run_agent
    return InProcessEngine(run_agent, name="big-bertha-project-agent", version="1.0")


def embedded_run_api(root: Path, *, endpoint: str, route: str, model: str,
                     provider: dict, engine: InProcessEngine | None = None,
                     tool_servers: dict | None = None,
                     workspace_root: Path | None = None) -> RunAPI:
    """Create a local run API; the caller owns provider and tool authority."""
    validate_direct_provider(provider, endpoint, route, model)
    servers = tool_servers or {}
    return RunAPI(root, engine or project_agent_engine(), {
        "engine_contract": SCHEMA,
        "gateway": endpoint, "route": route, "expected_model": model,
        "provider": provider, "workspace_root": workspace_root,
        "allowed_profiles": ["none", *servers.keys()],
        "tool_servers": servers,
    })
