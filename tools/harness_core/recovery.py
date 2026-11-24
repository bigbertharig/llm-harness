"""Fail-closed recovery policy for interrupted tool lifecycles."""

from __future__ import annotations

from dataclasses import dataclass

from .reducer import RunState


@dataclass(frozen=True)
class RecoveryDecision:
    action: str
    reason: str
    argument_digest: str | None = None
    attempt: int | None = None


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
        "uncertain": RecoveryDecision(
            "reconcile", "dispatch outcome is unknown; repeating it is unsafe", digest),
    }
    return decisions.get(tool.state, RecoveryDecision("fail", "tool state is not recoverable"))


def decide_job_recovery(state: RunState, job_id: str) -> RecoveryDecision:
    """Reconcile active work or deliver one already-terminal receipt; never resubmit."""
    job = next((item for item in state.jobs if item.identifier == job_id), None)
    if job is None:
        return RecoveryDecision("fail", "job is absent from the durable journal")
    if job.state == "active":
        return RecoveryDecision(
            "reconcile", f"job attempt {job.attempt} may still be running; do not resubmit",
            attempt=job.attempt)
    if job.state in {"succeeded", "failed", "cancelled", "timed_out"}:
        tool = next((item for item in state.tools if item.identifier == job.tool_call_id), None)
        actions = {
            "executing": ("commit_tool_result", "terminal job receipt awaits tool commit"),
            "committed": ("persist_result", "committed terminal job result is not persisted"),
            "result_persisted": ("deliver_result", "persisted terminal job result awaits delivery"),
            "result_delivered": ("done", "terminal job result was already delivered"),
        }
        if tool is None or tool.state not in actions:
            return RecoveryDecision(
                "fail", "terminal job is inconsistent with its linked tool state",
                attempt=job.attempt)
        action, reason = actions[tool.state]
        return RecoveryDecision(
            action, f"job attempt {job.attempt}: {reason}", attempt=job.attempt)
    return RecoveryDecision("fail", "job state is not recoverable")


def decide_child_recovery(state: RunState, child_run_id: str) -> RecoveryDecision:
    """Reconcile one active child or confirm its durable terminal outcome."""
    child = next((item for item in state.children if item.identifier == child_run_id), None)
    if child is None:
        return RecoveryDecision("fail", "child run is absent from the durable journal")
    if child.state == "active":
        return RecoveryDecision(
            "reconcile", "child may still be running; inspect its durable receipt before resubmission")
    if child.state in {"completed", "failed", "cancelled", "timed_out"}:
        return RecoveryDecision("done", f"child already reached terminal state {child.state}")
    return RecoveryDecision("fail", "child state is not recoverable")
