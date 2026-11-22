"""Deterministic multi-call drivers selected by a model but advanced by Harness."""

from __future__ import annotations

import re


_SHA256 = re.compile(r"[0-9a-f]{64}")


class DocumentDriverError(ValueError):
    pass


def next_document_request(tool: str, arguments: dict, evidence: dict,
                          calls_used: int, calls_max: int) -> dict | None:
    """Return the exact next immutable-snapshot read, or None when complete/bounded."""
    if tool != "read_workspace_document_chunk":
        return None
    if not isinstance(evidence, dict):
        raise DocumentDriverError("complete-document result is not an object")
    if evidence.get("complete") is True:
        return None
    if evidence.get("complete") is not False:
        raise DocumentDriverError("complete-document result lacks an explicit completion state")
    if calls_used >= calls_max:
        return None
    cursor = arguments.get("cursor", 0)
    start, end, next_cursor = (evidence.get("cursor_start"), evidence.get("cursor_end"),
                               evidence.get("next_cursor"))
    snapshot = evidence.get("snapshot_sha256")
    if (type(cursor) is not int or start != cursor or type(end) is not int
            or type(next_cursor) is not int or next_cursor != end or next_cursor <= cursor
            or not isinstance(snapshot, str) or not _SHA256.fullmatch(snapshot)
            or evidence.get("path") != arguments.get("path")):
        raise DocumentDriverError("complete-document continuation receipt is invalid")
    return {"path": arguments["path"], "cursor": next_cursor,
            "snapshot_sha256": snapshot, "max_chars": arguments.get("max_chars", 12000)}
