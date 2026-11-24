"""Durable delayed-process supervision and exactly-once result delivery."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import time
from typing import Callable, Sequence
from uuid import uuid4

from .journal import JournalError
from .recorder import RunRecorder
from .recovery import decide_job_recovery


MAX_JOB_LOG_BYTES = 1024 * 1024
MAX_JOB_PROGRESS_EVENTS = 1000
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_TERMINAL = frozenset({"succeeded", "failed", "cancelled", "timed_out"})


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _safe_directory(root: Path) -> None:
    if root.is_symlink():
        raise JournalError("job receipt root cannot be a symlink")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not root.is_dir() or root.is_symlink():
        raise JournalError("job receipt root is unavailable")
    root.chmod(0o700)


def _atomic_json(path: Path, value: dict) -> None:
    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")) + "\n").encode("utf-8")
    temp = path.parent / f".{uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(temp, flags, 0o600)
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise JournalError("job receipt write did not make progress")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temp, path)
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


class DelayedJobSupervisor:
    """Run one owned argv process and publish one durable terminal receipt."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        _safe_directory(self.root)

    def _paths(self, job_id: str, attempt: int) -> tuple[Path, Path]:
        if not isinstance(job_id, str) or not _IDENTIFIER.fullmatch(job_id):
            raise ValueError("job_id is not safe for a receipt path")
        if type(attempt) is not int or attempt < 1:
            raise ValueError("attempt must be a positive integer")
        directory = self.root / job_id
        _safe_directory(directory)
        return directory / f"attempt-{attempt}.log", directory / f"attempt-{attempt}.json"

    def read_receipt(self, job_id: str, attempt: int) -> dict | None:
        """Return one validated terminal receipt, or None while no receipt exists."""
        _log_path, receipt_path = self._paths(job_id, attempt)
        if not receipt_path.exists():
            return None
        if receipt_path.is_symlink() or receipt_path.stat().st_size > 64 * 1024:
            raise JournalError("job terminal receipt is unsafe")
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise JournalError("job terminal receipt is invalid") from exc
        required = {"job_id", "attempt", "session_id", "status", "started_at",
                    "finished_at", "duration_ms", "log_ref", "receipt_ref", "summary"}
        if (not isinstance(receipt, dict) or not required <= set(receipt)
                or receipt.get("job_id") != job_id or receipt.get("attempt") != attempt
                or receipt.get("status") not in _TERMINAL):
            raise JournalError("job terminal receipt does not match the requested attempt")
        return receipt

    @staticmethod
    def _stop_process(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=1)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()

    def run(self, recorder: RunRecorder, *, tool_call_id: str, job_id: str,
            attempt: int, session_id: str, argv: Sequence[str], timeout_s: float,
            cancel_requested: Callable[[], bool] | None = None) -> dict:
        """Supervise an already-approved delayed tool without model polling."""
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_id is required")
        if (not isinstance(argv, (list, tuple)) or not argv
                or not all(isinstance(item, str) and item for item in argv)):
            raise ValueError("argv must be a non-empty string sequence")
        if not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        log_path, receipt_path = self._paths(job_id, attempt)
        if receipt_path.exists() or log_path.exists():
            raise JournalError("job attempt already has durable artifacts")

        recorder.emit("job.started", tool_call_id=tool_call_id, job_id=job_id,
                      payload={"attempt": attempt, "session_id": session_id})
        started_at, started = _timestamp(), time.monotonic()
        process: subprocess.Popen[bytes] | None = None
        status, exit_code, progress_sequence = "failed", None, 0
        log_size, tail = 0, bytearray()
        failure = None

        log_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            log_flags |= os.O_NOFOLLOW
        log_fd = os.open(log_path, log_flags, 0o600)
        try:
            try:
                process = subprocess.Popen(
                    list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, start_new_session=True)
                assert process.stdout is not None
                selector = selectors.DefaultSelector()
                selector.register(process.stdout, selectors.EVENT_READ)
                line_buffer = bytearray()
                while process.poll() is None or selector.get_map():
                    elapsed = time.monotonic() - started
                    try:
                        cancelled = cancel_requested is not None and cancel_requested()
                    except Exception as exc:
                        failure = f"cancellation check failed: {type(exc).__name__}"
                        status = "failed"
                        self._stop_process(process)
                        cancelled = False
                    if cancelled:
                        status = "cancelled"
                        self._stop_process(process)
                    elif elapsed >= timeout_s:
                        status = "timed_out"
                        self._stop_process(process)
                    selected = selector.select(timeout=0.05)
                    for key, _mask in selected:
                        chunk = os.read(key.fileobj.fileno(), 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        if log_size + len(chunk) > MAX_JOB_LOG_BYTES:
                            failure = "job log exceeded the bounded log limit"
                            status = "failed"
                            self._stop_process(process)
                            chunk = chunk[:max(0, MAX_JOB_LOG_BYTES - log_size)]
                        if chunk:
                            os.write(log_fd, chunk)
                            log_size += len(chunk)
                            tail.extend(chunk)
                            del tail[:-4096]
                            line_buffer.extend(chunk)
                            while b"\n" in line_buffer:
                                raw, _, line_buffer = line_buffer.partition(b"\n")
                                if raw.startswith(b"PROGRESS "):
                                    if progress_sequence >= MAX_JOB_PROGRESS_EVENTS:
                                        failure = "job emitted too many progress events"
                                        status = "failed"
                                        self._stop_process(process)
                                        break
                                    recorder.emit("job.progressed", job_id=job_id, payload={
                                        "attempt": attempt,
                                        "progress_sequence": progress_sequence,
                                        "summary": raw.removeprefix(b"PROGRESS ").decode(
                                            "utf-8", errors="replace")[:500]})
                                    progress_sequence += 1
                    if status in {"cancelled", "timed_out"} and process.poll() is not None:
                        continue
                exit_code = process.wait()
                if status not in {"cancelled", "timed_out"}:
                    status = "succeeded" if exit_code == 0 and failure is None else "failed"
            except (OSError, RuntimeError) as exc:
                failure = f"process start or supervision failed: {type(exc).__name__}"
                status = "failed"
                if process is not None:
                    self._stop_process(process)
                    exit_code = process.returncode
            os.fsync(log_fd)
        finally:
            os.close(log_fd)

        receipt = {
            "job_id": job_id, "attempt": attempt, "session_id": session_id,
            "status": status, "exit_code": exit_code, "started_at": started_at,
            "finished_at": _timestamp(),
            "duration_ms": max(0, round((time.monotonic() - started) * 1000)),
            "log_ref": os.fspath(log_path), "receipt_ref": os.fspath(receipt_path),
            "summary": tail.decode("utf-8", errors="replace")[-2000:],
            **({"error": failure} if failure else {}),
        }
        _atomic_json(receipt_path, receipt)
        recorder.emit(f"job.{status}", job_id=job_id,
                      payload={"attempt": attempt, "receipt_ref": os.fspath(receipt_path)})
        return receipt

    def deliver_terminal(self, recorder: RunRecorder, job_id: str, receipt: dict) -> dict | None:
        """Advance a terminal job through tool commit, persistence, and one delivery."""
        job = next((row for row in recorder.state.jobs if row.identifier == job_id), None)
        if job is None:
            raise JournalError("job cannot be delivered: job is absent from the durable journal")
        durable = self.read_receipt(job_id, job.attempt)
        if durable is None or durable != receipt or durable.get("status") != job.state:
            raise JournalError("job cannot be delivered: terminal receipt does not match the journal")
        while True:
            decision = decide_job_recovery(recorder.state, job_id)
            job = next(row for row in recorder.state.jobs if row.identifier == job_id)
            tool = next(row for row in recorder.state.tools
                        if row.identifier == job.tool_call_id)
            if decision.action == "commit_tool_result":
                recorder.emit("tool.committed", tool_call_id=tool.identifier, payload={
                    "argument_digest": tool.argument_digest,
                    "receipt_ref": receipt["receipt_ref"]})
            elif decision.action == "persist_result":
                artifact = recorder.persist_result(tool.identifier, receipt)
                recorder.emit("tool.result_persisted", tool_call_id=tool.identifier,
                              payload={"artifact_ref": artifact})
            elif decision.action == "deliver_result":
                recorder.emit("tool.result_delivered", tool_call_id=tool.identifier, payload={})
                return receipt
            elif decision.action == "done":
                return None
            else:
                raise JournalError(f"job cannot be delivered: {decision.reason}")
