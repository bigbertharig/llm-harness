"""Deterministic terminal-state policy shared by provider adapters and loops."""

from __future__ import annotations

from dataclasses import dataclass


TRUNCATED_FINISH_REASONS = frozenset({"length", "max_tokens"})


@dataclass(frozen=True)
class TerminalDecision:
    action: str
    reason: str


def decide_terminal(*, answer: str, finish_reason: str | None,
                    repair_attempted: bool, can_repair: bool) -> TerminalDecision:
    """Classify one proposed final response without provider-specific branching."""
    if finish_reason in TRUNCATED_FINISH_REASONS:
        if not repair_attempted and can_repair:
            return TerminalDecision("repair", "output_truncated")
        return TerminalDecision("fail", "model final answer hit the output-token limit")
    if not answer.strip():
        return TerminalDecision("fail", "model returned an empty answer")
    return TerminalDecision("succeed", "completed")
