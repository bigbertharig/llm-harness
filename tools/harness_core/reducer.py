"""Pure reducer for ordered, provider-neutral Harness events."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import re
from typing import TypeVar

from .contracts import EVENT_SCHEMA_VERSION, EVENT_TYPES


class InvalidTransition(ValueError):
    """An event is malformed, out of order, or illegal for the current state."""


@dataclass(frozen=True)
class LinkedState:
    identifier: str
    state: str


@dataclass(frozen=True)
class ToolState(LinkedState):
    argument_digest: str


Linked = TypeVar("Linked", bound=LinkedState)


@dataclass(frozen=True)
class RunState:
    run_id: str
    next_sequence: int = 0
    phase: str = "new"
    active_model_step_id: str | None = None
    completed_model_steps: tuple[str, ...] = ()
    tools: tuple[ToolState, ...] = ()
    retry_state: str | None = None
    needs_repair: bool = False
    awaiting_model_followup: bool = False
    tool_cycle_has_proposal: bool = False
    active_compaction_id: str | None = None
    children: tuple[LinkedState, ...] = ()
    terminal_reason: str | None = None
    seen_event_ids: frozenset[str] = frozenset()


_TOOL_TRANSITIONS = {
    "tool.validated": ("proposed", "validated"),
    "tool.approved": ("validated", "approved"),
    "tool.executing": ("approved", "executing"),
    "tool.committed": ("executing", "committed"),
    "tool.result_persisted": ("committed", "result_persisted"),
    "tool.result_delivered": ("result_persisted", "result_delivered"),
}
_TERMINAL_EVENTS = {
    "run.succeeded": "succeeded", "run.failed": "failed",
    "run.cancelled": "cancelled", "run.timed_out": "timed_out",
}
_EVENT_KEYS = {"schema_version", "event_id", "run_id", "sequence", "type", "occurred_at",
               "conversation_id", "model_step_id", "tool_call_id", "approval_id", "attempt_id",
               "compaction_id", "child_run_id", "payload"}
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _linked(items: tuple[Linked, ...], identifier: str) -> tuple[int, Linked | None]:
    for index, item in enumerate(items):
        if item.identifier == identifier:
            return index, item
    return -1, None


def _replace_link(items: tuple[Linked, ...], index: int,
                  replacement: Linked) -> tuple[Linked, ...]:
    return items[:index] + (replacement,) + items[index + 1:]


def _link(event: dict, name: str) -> str:
    value = event.get(name)
    if not isinstance(value, str) or not value:
        raise InvalidTransition(f"{event.get('type')} requires {name}")
    return value


def _validate_envelope(state: RunState, event: dict) -> str:
    if not isinstance(event, dict):
        raise InvalidTransition("event must be an object")
    if event.get("schema_version") != EVENT_SCHEMA_VERSION:
        raise InvalidTransition("event schema version is not supported")
    if set(event) - _EVENT_KEYS:
        raise InvalidTransition("event contains fields outside the canonical schema")
    event_id = event.get("event_id")
    if not isinstance(event_id, str) or not event_id:
        raise InvalidTransition("event_id is required")
    if event_id in state.seen_event_ids:
        raise InvalidTransition("event_id was already consumed")
    occurred_at = event.get("occurred_at")
    try:
        timestamp = datetime.fromisoformat(occurred_at) if isinstance(occurred_at, str) else None
    except ValueError as exc:
        raise InvalidTransition("occurred_at must be an ISO timestamp") from exc
    if timestamp is None or timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise InvalidTransition("occurred_at must include an offset")
    if event.get("run_id") != state.run_id:
        raise InvalidTransition("event belongs to another run")
    if type(event.get("sequence")) is not int:
        raise InvalidTransition("event sequence must be an integer")
    if event.get("sequence") != state.next_sequence:
        raise InvalidTransition(
            f"expected event sequence {state.next_sequence}, got {event.get('sequence')}")
    event_type = event.get("type")
    if event_type not in EVENT_TYPES:
        raise InvalidTransition("event type is not supported")
    if not isinstance(event.get("payload"), dict):
        raise InvalidTransition("event payload must be an object")
    for key in _EVENT_KEYS & set(event) - {
            "schema_version", "event_id", "run_id", "sequence", "type", "occurred_at", "payload"}:
        if not isinstance(event[key], str) or not event[key]:
            raise InvalidTransition(f"{key} must be a non-empty identifier")
    if state.phase in {"succeeded", "failed", "cancelled", "timed_out"}:
        raise InvalidTransition("terminal run cannot accept another event")
    return event_type


def reduce_event(state: RunState, event: dict) -> RunState:
    """Return a new state after one canonical event; never mutate input state."""
    event_type = _validate_envelope(state, event)
    updated = state

    if event_type == "run.started":
        if state.phase != "new" or state.next_sequence != 0:
            raise InvalidTransition("run.started must be the first event")
        updated = replace(state, phase="running")
    elif state.phase != "running":
        raise InvalidTransition("run must be started before work events")
    elif event_type == "model.started":
        step = _link(event, "model_step_id")
        if state.active_model_step_id is not None:
            raise InvalidTransition("another model step is already active")
        if step in state.completed_model_steps:
            raise InvalidTransition("model step identifier was already completed")
        if state.awaiting_model_followup:
            if not state.tool_cycle_has_proposal:
                raise InvalidTransition("tool-call response has no proposed tool")
            if any(tool.state not in {"result_delivered", "failed"} for tool in state.tools):
                raise InvalidTransition("tool results must settle before the next model step")
        updated = replace(state, active_model_step_id=step,
                          awaiting_model_followup=False, tool_cycle_has_proposal=False)
    elif event_type in {"model.completed", "model.failed", "model.truncated"}:
        step = _link(event, "model_step_id")
        if state.active_model_step_id != step:
            raise InvalidTransition("model completion does not match the active step")
        needs_repair = event_type != "model.completed"
        finish_reason = event["payload"].get("finish_reason")
        retry_state = (None if event_type == "model.completed" else
                       "attempt_failed" if state.retry_state == "started" else state.retry_state)
        updated = replace(state, active_model_step_id=None,
                          completed_model_steps=state.completed_model_steps + (step,),
                          needs_repair=needs_repair,
                          awaiting_model_followup=(event_type == "model.completed"
                                                   and finish_reason == "tool_calls"),
                          tool_cycle_has_proposal=False,
                          retry_state=retry_state)
    elif event_type == "tool.proposed":
        call = _link(event, "tool_call_id")
        if state.active_model_step_id is not None:
            raise InvalidTransition("tool proposal cannot precede model-step completion")
        if not state.awaiting_model_followup:
            raise InvalidTransition("tool proposal requires a model tool-call response")
        if _linked(state.tools, call)[1] is not None:
            raise InvalidTransition("tool call identifier was already proposed")
        name, digest = event["payload"].get("name"), event["payload"].get("argument_digest")
        if not isinstance(name, str) or not name or not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise InvalidTransition("tool proposal requires name and normalized SHA-256 argument digest")
        updated = replace(state, tools=state.tools + (ToolState(call, "proposed", digest),),
                          tool_cycle_has_proposal=True)
    elif event_type in _TOOL_TRANSITIONS:
        call = _link(event, "tool_call_id")
        before, after = _TOOL_TRANSITIONS[event_type]
        index, current = _linked(state.tools, call)
        if current is None or current.state != before:
            raise InvalidTransition(f"{event_type} requires tool state {before}")
        if event_type == "tool.approved":
            _link(event, "approval_id")
        if event_type == "tool.committed":
            digest, receipt = (event["payload"].get("argument_digest"),
                               event["payload"].get("receipt_ref"))
            if digest != current.argument_digest or not isinstance(receipt, str) or not receipt:
                raise InvalidTransition("committed tool outcome requires matching digest and receipt_ref")
        if event_type == "tool.result_persisted":
            artifact = event["payload"].get("artifact_ref")
            if not isinstance(artifact, str) or not artifact:
                raise InvalidTransition("persisted tool result requires artifact_ref")
        updated = replace(state, tools=_replace_link(
            state.tools, index, ToolState(call, after, current.argument_digest)))
    elif event_type == "tool.failed":
        call = _link(event, "tool_call_id")
        index, current = _linked(state.tools, call)
        if current is None or current.state not in {"proposed", "validated", "approved"}:
            raise InvalidTransition("tool.failed requires a tool call that was not dispatched")
        updated = replace(state, tools=_replace_link(
            state.tools, index, ToolState(call, "failed", current.argument_digest)))
    elif event_type == "tool.uncertain":
        call = _link(event, "tool_call_id")
        index, current = _linked(state.tools, call)
        if current is None or current.state != "executing":
            raise InvalidTransition("tool.uncertain requires a dispatched tool call")
        updated = replace(state, tools=_replace_link(
            state.tools, index, ToolState(call, "uncertain", current.argument_digest)))
    elif event_type == "retry.scheduled":
        if not state.needs_repair or state.retry_state not in (None, "attempt_failed"):
            raise InvalidTransition("retry may be scheduled only for a failed or truncated step")
        updated = replace(state, retry_state="scheduled")
    elif event_type == "retry.started":
        if state.retry_state != "scheduled":
            raise InvalidTransition("retry.started requires a scheduled retry")
        updated = replace(state, retry_state="started")
    elif event_type == "retry.exhausted":
        if state.retry_state not in {"scheduled", "started", "attempt_failed"}:
            raise InvalidTransition("retry.exhausted requires an active retry")
        updated = replace(state, retry_state="exhausted")
    elif event_type == "compaction.started":
        compaction = _link(event, "compaction_id")
        if state.active_compaction_id is not None:
            raise InvalidTransition("another compaction is already active")
        updated = replace(state, active_compaction_id=compaction)
    elif event_type in {"compaction.checkpointed", "compaction.committed", "compaction.aborted"}:
        compaction = _link(event, "compaction_id")
        if state.active_compaction_id != compaction:
            raise InvalidTransition("compaction event does not match the active transaction")
        updated = (state if event_type == "compaction.checkpointed"
                   else replace(state, active_compaction_id=None))
    elif event_type == "child.delegated":
        child = _link(event, "child_run_id")
        if _linked(state.children, child)[1] is not None:
            raise InvalidTransition("child run identifier was already delegated")
        updated = replace(state, children=state.children + (LinkedState(child, "active"),))
    elif event_type in {"child.completed", "child.cancelled"}:
        child = _link(event, "child_run_id")
        index, current = _linked(state.children, child)
        if current is None or current.state != "active":
            raise InvalidTransition("child terminal event requires an active child")
        updated = replace(state, children=_replace_link(
            state.children, index, LinkedState(child, event_type.removeprefix("child."))))
    elif event_type in {"input.queued", "input.steered", "input.applied"}:
        updated = state
    elif event_type in _TERMINAL_EVENTS:
        if state.active_model_step_id or state.active_compaction_id:
            raise InvalidTransition("active work must settle before run termination")
        if any(tool.state not in {"result_delivered", "failed", "uncertain"} for tool in state.tools):
            raise InvalidTransition("tool calls must settle before run termination")
        if any(child.state == "active" for child in state.children):
            raise InvalidTransition("child runs must settle before run termination")
        if event_type == "run.succeeded" and (state.needs_repair or state.awaiting_model_followup
                                               or not state.completed_model_steps):
            raise InvalidTransition("successful run requires a complete model response")
        reason = event["payload"].get("reason")
        if not isinstance(reason, str) or not reason:
            raise InvalidTransition("terminal event requires a reason")
        updated = replace(state, phase=_TERMINAL_EVENTS[event_type], terminal_reason=reason)
    else:
        raise InvalidTransition(f"reducer has no transition for {event_type}")

    return replace(updated, next_sequence=state.next_sequence + 1,
                   seen_event_ids=state.seen_event_ids | {event["event_id"]})


def reduce_events(run_id: str, events: list[dict] | tuple[dict, ...]) -> RunState:
    state = RunState(run_id=run_id)
    for event in events:
        state = reduce_event(state, event)
    return state
