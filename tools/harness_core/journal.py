"""Crash-durable append-only journal for canonical Harness events."""

from __future__ import annotations

import fcntl
import json
import os
import re
from pathlib import Path

from .reducer import RunState, reduce_event


MAX_EVENT_BYTES = 1024 * 1024
MAX_JOURNAL_BYTES = 64 * 1024 * 1024
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class JournalError(RuntimeError):
    pass


class EventJournal:
    """Serialize validated events with process locking and fsync on every append."""

    def __init__(self, root: Path | str, run_id: str):
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise ValueError("run_id is not safe for a journal filename")
        self.root = Path(root)
        if self.root.is_symlink():
            raise JournalError("journal root cannot be a symlink")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.root.is_dir() or self.root.is_symlink():
            raise JournalError("journal root is unavailable")
        self.root.chmod(0o700)
        self.run_id = run_id
        self.path = self.root / f"{run_id}.jsonl"

    def _open(self, *, create: bool) -> int:
        flags = os.O_RDWR | os.O_APPEND | (os.O_CREAT if create else 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        existed = self.path.exists()
        try:
            fd = os.open(self.path, flags, 0o600)
            os.fchmod(fd, 0o600)
            if create and not existed:
                directory_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            return fd
        except OSError as exc:
            raise JournalError("journal file cannot be opened safely") from exc

    @staticmethod
    def _read_fd(fd: int) -> bytes:
        size = os.fstat(fd).st_size
        if size > MAX_JOURNAL_BYTES:
            raise JournalError("journal exceeds the replay limit")
        os.lseek(fd, 0, os.SEEK_SET)
        chunks = []
        remaining = size
        while remaining:
            chunk = os.read(fd, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _decode(self, data: bytes) -> tuple[list[dict], RunState]:
        if data and not data.endswith(b"\n"):
            raise JournalError("journal has an incomplete final record")
        events = []
        state = RunState(self.run_id)
        for line_number, line in enumerate(data.splitlines(), 1):
            if not line or len(line) > MAX_EVENT_BYTES:
                raise JournalError(f"journal record {line_number} has an invalid size")
            try:
                event = json.loads(line)
                state = reduce_event(state, event)
            except (ValueError, TypeError) as exc:
                raise JournalError(f"journal record {line_number} is invalid: {exc}") from exc
            events.append(event)
        return events, state

    def read(self) -> tuple[list[dict], RunState]:
        if not self.path.exists():
            return [], RunState(self.run_id)
        fd = self._open(create=False)
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            return self._decode(self._read_fd(fd))
        finally:
            os.close(fd)

    def append(self, event: dict) -> RunState:
        try:
            encoded = (json.dumps(event, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":")) + "\n").encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise JournalError("event is not JSON serializable") from exc
        if len(encoded) > MAX_EVENT_BYTES:
            raise JournalError("event exceeds the journal record limit")
        fd = self._open(create=True)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            data = self._read_fd(fd)
            _events, state = self._decode(data)
            try:
                next_state = reduce_event(state, event)
            except (ValueError, TypeError) as exc:
                raise JournalError(f"event cannot be appended: {exc}") from exc
            if len(data) + len(encoded) > MAX_JOURNAL_BYTES:
                raise JournalError("journal would exceed the replay limit")
            view = memoryview(encoded)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise JournalError("journal append did not make progress")
                view = view[written:]
            os.fsync(fd)
            return next_state
        finally:
            os.close(fd)
