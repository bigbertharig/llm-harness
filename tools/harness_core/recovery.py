"""Fail-closed recovery policy for interrupted tool lifecycles."""

from __future__ import annotations

from dataclasses import dataclass

from .reducer import RunState


@dataclass(frozen=True)
class RecoveryDecision:
    action: str
    reason: str
    argument_digest: str | None = None


def decide_tool_recovery(state: RunState, tool_call_id: str) -> RecoveryDecision:
    """Choose the only safe next action; never repeat a possibly dispatched write."""
    tool = next((item for item in state.tools if item.identifier == tool_call_id), None)
    if tool is None:
        return RecoveryDecision("fail", "tool call is absent from the durable journal")
    digest = tool.argument_digest
    decisions = {
        "proposed": RecoveryDecision("validate", "tool proposal was not validated", digest),
        "validated": RecoveryDecision("approve", "tool proposal was not approved", digest),
        "approved": RecoveryDecision("execute", "dispatch has not started", digest),
        "executing": RecoveryDecision(
            "reconcile", "dispatch may have happened; repeating it is unsafe", digest),
        "committed": RecoveryDecision("persist_result", "tool outcome is committed", digest),
        "result_persisted": RecoveryDecision(
            "deliver_result", "durable result awaits model delivery", digest),
        "result_delivered": RecoveryDecision("done", "tool result was already delivered", digest),
        "failed": RecoveryDecision(
            "done", "tool call already reached a failed terminal state", digest),
    }
    return decisions.get(tool.state, RecoveryDecision("fail", "tool state is not recoverable"))
