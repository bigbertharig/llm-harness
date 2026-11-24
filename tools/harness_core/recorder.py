"""Canonical run recorder and private result artifact store."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from .contracts import make_event
from .journal import EventJournal, JournalError
from .reducer import RunState, reduce_event


class RunRecorder:
    def __init__(self, journal_root: Path | str | None = None, run_id: str | None = None,
                 *, conversation_id: str | None = None):
        self.run_id = run_id or uuid4().hex
        self.conversation_id = self.run_id if conversation_id is None else conversation_id
        if not isinstance(self.conversation_id, str) or not self.conversation_id:
            raise ValueError("conversation_id must be a non-empty identifier")
        self.state = RunState(self.run_id)
        self.events: list[dict] = []
        self.journal = EventJournal(journal_root, self.run_id) if journal_root is not None else None
        self.artifact_root = Path(journal_root) / "artifacts" / self.run_id if journal_root else None

    @classmethod
    def resume(cls, journal_root: Path | str, run_id: str) -> "RunRecorder":
        """Reopen one durable run at its last validated event boundary."""
        recorder = cls(journal_root, run_id)
        events, state = recorder.journal.read()
        recorder.events = events
        recorder.state = state
        recorder.conversation_id = state.conversation_id or run_id
        return recorder

    def emit(self, event_type: str, *, payload: dict | None = None, **links: str) -> dict:
        supplied = links.setdefault("conversation_id", self.conversation_id)
        if supplied != self.conversation_id:
            raise ValueError("event conversation_id does not match the recorder")
        event = make_event(run_id=self.run_id, sequence=self.state.next_sequence,
                           event_type=event_type, payload=payload, **links)
        self.state = self.journal.append(event) if self.journal else reduce_event(self.state, event)
        self.events.append(event)
        return event

    def persist_result(self, tool_call_id: str, result: object) -> str:
        encoded = json.dumps(result, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        if self.artifact_root is None:
            return f"memory:sha256:{digest}"
        root = self.artifact_root
        if root.is_symlink():
            raise JournalError("artifact root cannot be a symlink")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)
        target = root / f"{tool_call_id}-{digest}.json"
        temp = root / f".{uuid4().hex}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(temp, flags, 0o600)
        try:
            view = memoryview(encoded)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise JournalError("artifact write did not make progress")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temp, target)
        directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return os.fspath(target)

    def receipt(self) -> dict:
        return {"run_id": self.run_id, "conversation_id": self.conversation_id,
                "event_count": len(self.events),
                "phase": self.state.phase,
                "journal_ref": os.fspath(self.journal.path) if self.journal else None,
                "durable": self.journal is not None}
