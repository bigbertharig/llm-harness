"""Versioned, provider-neutral event primitives for Harness runs."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


EVENT_SCHEMA_VERSION = "harness-event/v1"
RUN_SCHEMA_VERSION = "harness-run/v1"
EVENT_TYPES = frozenset({
    "run.started", "run.succeeded", "run.failed", "run.cancelled", "run.timed_out",
    "model.started", "model.completed", "model.failed", "model.truncated",
    "tool.proposed", "tool.validated", "tool.approved", "tool.executing",
    "tool.committed", "tool.failed", "tool.uncertain", "tool.result_persisted", "tool.result_delivered",
    "compaction.started", "compaction.checkpointed", "compaction.committed",
    "compaction.aborted", "retry.scheduled", "retry.started", "retry.exhausted",
    "child.delegated", "child.completed", "child.cancelled",
    "input.queued", "input.steered", "input.applied",
})


def make_event(*, run_id: str, sequence: int, event_type: str,
               payload: dict | None = None, **links: str) -> dict:
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_id is required")
    if type(sequence) is not int or sequence < 0:
        raise ValueError("sequence must be a non-negative integer")
    if event_type not in EVENT_TYPES:
        raise ValueError("unknown harness event type")
    allowed_links = {"conversation_id", "model_step_id", "tool_call_id", "approval_id",
                     "attempt_id", "compaction_id", "child_run_id"}
    if set(links) - allowed_links or not all(isinstance(value, str) and value
                                             for value in links.values()):
        raise ValueError("event links must be named non-empty identifiers")
    if payload is not None and not isinstance(payload, dict):
        raise ValueError("event payload must be an object")
    return {"schema_version": EVENT_SCHEMA_VERSION, "event_id": uuid4().hex,
            "run_id": run_id, "sequence": sequence, "type": event_type,
            "occurred_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            **links, "payload": payload or {}}
