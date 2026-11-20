"""Shared limits for one local delegated child task."""

from __future__ import annotations

import fcntl
import json
import os
import re
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

MAX_TOOL_CALLS = 12
MAX_TOOL_RESULT_BYTES = 32_000
MAX_TOTAL_TOOL_BYTES = 80_000
MAX_ACTIVE_CHILDREN = 2
SENSITIVE_QUERY = re.compile(r'(?i)(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]|'
                             r'(?:[A-Za-z]:\\|/home/[^\s]+/|/Users/[^\s]+/)')


def validate_request(profile: str, tool: str, arguments: dict, workspace_root: Path | None) -> None:
    allowed = {'public_research': {'search_web', 'fetch_page'},
               'workspace_read': {'list_workspace_files', 'find_workspace_files',
                                  'read_workspace_file', 'search_workspace_text'},
               'google_workspace': {'search_mail', 'read_mail', 'send_email',
                                    'search_drive', 'read_drive_text', 'create_drive_folder',
                                    'upload_drive_text', 'upload_drive_image', 'create_google_doc',
                                    'append_google_doc_text', 'create_google_sheet',
                                    'read_google_sheet', 'update_google_sheet',
                                    'append_google_sheet_rows'}}
    if tool not in allowed.get(profile, set()) or not isinstance(arguments, dict):
        raise ValueError('child tool is outside its selected profile')
    if profile == 'public_research':
        query = arguments.get('query') if tool == 'search_web' else arguments.get('url')
        if not isinstance(query, str) or len(query) > 2000:
            raise ValueError('public tool request is invalid')
        if SENSITIVE_QUERY.search(query) or (workspace_root and str(workspace_root) in query):
            raise ValueError('public tool request contains a private path or credential pattern')


class ToolBudget:
    def __init__(self):
        self.calls = 0
        self.result_bytes = 0

    def before_call(self) -> None:
        if self.calls >= MAX_TOOL_CALLS:
            raise ValueError('child exceeded its tool-call limit')

    def record(self, result: dict) -> int:
        size = len(json.dumps(result, ensure_ascii=False).encode('utf-8'))
        if size > MAX_TOOL_RESULT_BYTES or self.result_bytes + size > MAX_TOTAL_TOOL_BYTES:
            raise ValueError('child tool result exceeded its data budget')
        self.calls += 1
        self.result_bytes += size
        return size

    def receipt(self) -> dict:
        return {'max_calls': MAX_TOOL_CALLS, 'max_result_bytes': MAX_TOOL_RESULT_BYTES,
                'max_total_bytes': MAX_TOTAL_TOOL_BYTES, 'calls': self.calls,
                'result_bytes': self.result_bytes}


@contextmanager
def child_slot():
    """Cap simultaneous children across independent MCP adapter processes."""
    count = int(os.environ.get('SUBAGENT_MAX_ACTIVE', str(MAX_ACTIVE_CHILDREN)))
    if not 1 <= count <= 8:
        raise ValueError('SUBAGENT_MAX_ACTIVE must be between 1 and 8')
    root = Path(os.environ.get('SUBAGENT_SLOT_DIR', '/tmp/llm-harness-child-slots'))
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    for index in range(count):
        fd = os.open(root / f'slot-{index}.lock', os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            continue
        try:
            yield index
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        return
    raise RuntimeError('maximum concurrent child tasks reached')


def guard_child_run(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        with child_slot():
            return func(*args, **kwargs)
    return wrapped
