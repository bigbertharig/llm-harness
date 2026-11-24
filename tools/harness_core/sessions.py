"""Canonical session input adapter for queue-versus-steer delivery."""

from __future__ import annotations

import hashlib

from .input_queue import InputQueueState, PendingInput, apply_next_input
from .recorder import RunRecorder


def _digest(content: str) -> str:
    if not isinstance(content, str) or not content:
        raise ValueError("input content is required")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class SessionInputAdapter:
    """Journal submitted input and apply it only at its deterministic boundary."""

    def __init__(self, recorder: RunRecorder):
        self.recorder = recorder

    def submit(self, input_id: str, mode: str, content: str) -> str:
        if mode not in {"queue", "steer"}:
            raise ValueError("input mode must be queue or steer")
        content_digest = _digest(content)
        self.recorder.emit("input.queued" if mode == "queue" else "input.steered",
                           input_id=input_id, payload={"content_digest": content_digest})
        return content_digest

    def apply_next(self, boundary: str) -> PendingInput | None:
        state = self.recorder.state
        queue = InputQueueState(state.input_sequence, state.pending_inputs,
                                state.applied_input_ids)
        _updated, selected = apply_next_input(queue, boundary)
        if selected is None:
            return None
        self.recorder.emit("input.applied", input_id=selected.identifier,
                           payload={"boundary": boundary})
        return selected
