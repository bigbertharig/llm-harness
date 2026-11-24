"""Scripted provider transport for deterministic Harness conformance tests."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from .retry import ProviderFailure


@dataclass(frozen=True)
class ScriptedProviderError(ProviderFailure):
    pass


class ScriptedProvider:
    """Return exact scripted payloads or errors and retain normalized requests."""

    def __init__(self, steps: list[dict] | tuple[dict, ...]):
        if not isinstance(steps, (list, tuple)) or not steps:
            raise ValueError("script requires at least one step")
        self._steps = tuple(deepcopy(step) for step in steps)
        self._cursor = 0
        self.requests: list[dict] = []

    @property
    def remaining(self) -> int:
        return len(self._steps) - self._cursor

    def complete(self, request: dict) -> object:
        if not isinstance(request, dict):
            raise TypeError("provider request must be an object")
        if self._cursor >= len(self._steps):
            raise AssertionError("scripted provider received an unexpected request")
        self.requests.append(deepcopy(request))
        step = self._steps[self._cursor]
        self._cursor += 1
        if not isinstance(step, dict) or step.get("kind") not in {"response", "error"}:
            raise AssertionError("script step must be a response or error")
        if step["kind"] == "error":
            code, message = step.get("code"), step.get("message")
            if not isinstance(code, str) or not code or not isinstance(message, str) or not message:
                raise AssertionError("scripted error requires code and message")
            raise ScriptedProviderError(code, message, step.get("retryable") is True)
        if "payload" not in step:
            raise AssertionError("scripted response requires payload")
        return deepcopy(step["payload"])

    def assert_consumed(self) -> None:
        if self.remaining:
            raise AssertionError(f"scripted provider has {self.remaining} unused step(s)")
