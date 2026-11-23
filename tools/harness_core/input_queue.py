"""Deterministic queue-versus-steer ordering at explicit safe boundaries."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re


_SHA256 = re.compile(r"[0-9a-f]{64}")
SAFE_BOUNDARIES = frozenset({"model_end", "tool_end", "compaction_end", "turn_end"})


@dataclass(frozen=True)
class PendingInput:
    identifier: str
    sequence: int
    mode: str
    content_digest: str


@dataclass(frozen=True)
class InputQueueState:
    next_sequence: int = 0
    pending: tuple[PendingInput, ...] = ()
    applied_ids: tuple[str, ...] = ()


def submit_input(state: InputQueueState, identifier: str, mode: str,
                 content_digest: str) -> InputQueueState:
    if not isinstance(identifier, str) or not identifier:
        raise ValueError("input identifier is required")
    if mode not in {"queue", "steer"}:
        raise ValueError("input mode must be queue or steer")
    if not isinstance(content_digest, str) or not _SHA256.fullmatch(content_digest):
        raise ValueError("input requires a normalized SHA-256 content digest")
    if identifier in state.applied_ids or any(row.identifier == identifier for row in state.pending):
        raise ValueError("input identifier was already submitted")
    row = PendingInput(identifier, state.next_sequence, mode, content_digest)
    return replace(state, next_sequence=state.next_sequence + 1,
                   pending=state.pending + (row,))


def apply_next_input(state: InputQueueState,
                     boundary: str) -> tuple[InputQueueState, PendingInput | None]:
    """Apply one eligible input, preserving FIFO order within its delivery class.

    Steers may enter at the next completed work boundary. Queued sends wait for
    the entire turn to end. A later steer can therefore pass an earlier queued
    send, but two steers and two queued sends remain FIFO.
    """
    if boundary not in SAFE_BOUNDARIES:
        raise ValueError("input may be applied only at a safe completed boundary")
    eligible = [row for row in state.pending
                if boundary == "turn_end" or row.mode == "steer"]
    if not eligible:
        return state, None
    selected = min(eligible, key=lambda row: row.sequence)
    pending = tuple(row for row in state.pending if row.identifier != selected.identifier)
    return (replace(state, pending=pending,
                    applied_ids=state.applied_ids + (selected.identifier,)), selected)
