#!/usr/bin/env python3
"""Bounded, read-only Codex child using a model listed by the gateway catalog."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time
from urllib.request import Request, urlopen


def run_codex_child(*, candidate_id: str, agent_type: str, prompt: str, out: Path,
                    gateway: str, timeout_s: int = 120) -> dict:
    if not 1 <= timeout_s <= 600 or not 1 <= len(prompt) <= 4000:
        raise ValueError("child budget outside allowed bounds")
    headers = {}
    if os.environ.get("LLM_GATEWAY_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["LLM_GATEWAY_API_KEY"]
    with urlopen(Request(gateway.rstrip("/") + "/v1/manager/subagent-candidates",
                         headers=headers), timeout=10) as response:
        catalog = json.load(response)
    candidate = catalog.get("candidates", {}).get(candidate_id)
    if not candidate or candidate.get("provider") != "codex" or agent_type not in candidate.get("agent_types", []):
        raise ValueError("Codex candidate is not offered for this agent type")
    model = candidate["model"]
    with urlopen(Request(gateway.rstrip("/") + "/dashboard/api/chat/codex/models",
                         headers=headers), timeout=20) as response:
        offered = json.load(response)
    if model not in {row.get("model") for row in offered.get("models", [])}:
        raise ValueError("Codex account does not currently offer " + model)
    out = out.resolve()
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)
    workspace = out / "workspace"
    workspace.mkdir()
    final = out / "final.txt"
    command = ["codex", "exec", "--model", model, "--sandbox", "read-only",
               "--skip-git-repo-check", "--ephemeral", "--ignore-user-config",
               "--output-last-message", str(final), "--cd", str(workspace), "-"]
    started = time.monotonic()
    system = ("You are a bounded " + agent_type + " child agent. Work only on the assigned task. "
              "Do not use tools or modify files. Return a concise final answer.\n\nTask: " + prompt)
    with (out / "stdout.log").open("w") as stdout, (out / "stderr.log").open("w") as stderr:
        try:
            result = subprocess.run(command, input=system, text=True, stdout=stdout, stderr=stderr,
                                    timeout=timeout_s, cwd=workspace, check=False)
            exit_code, error = result.returncode, None
        except subprocess.TimeoutExpired:
            exit_code, error = 124, "timeout"
    answer = final.read_text().strip() if final.exists() else ""
    receipt = {"candidate_id": candidate_id, "agent_type": agent_type, "provider": "codex",
               "child_model": model, "answer": answer, "exit_code": exit_code, "error": error,
               "duration_s": round(time.monotonic() - started, 2), "timeout_s": timeout_s,
               "sandbox": "read-only", "tool_policy": "no tools requested"}
    (out / "summary.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt
