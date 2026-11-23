"""Canonical, model-neutral normalization for MCP tool results."""

from __future__ import annotations

from dataclasses import dataclass
import json


class MCPResultError(ValueError):
    """A tool returned a transport shape that cannot be delivered safely."""


@dataclass(frozen=True)
class NormalizedMCPResult:
    evidence: object
    driver_evidence: object
    shape: str
    is_error: bool


def _json_value(value: object, label: str) -> object:
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise MCPResultError(f"{label} is not valid JSON evidence") from exc
    return value


def _content_evidence(content: object) -> object:
    if not isinstance(content, list) or not content:
        raise MCPResultError("MCP content must be a non-empty block list")
    if not all(isinstance(block, dict) and isinstance(block.get("type"), str)
               for block in content):
        raise MCPResultError("MCP content contains an invalid block")
    _json_value(content, "MCP content")
    if len(content) == 1 and content[0].get("type") == "text":
        text = content[0].get("text")
        if not isinstance(text, str):
            raise MCPResultError("MCP text block has no text")
        return text
    return {"content": content}


def _mirrors_structured(content_evidence: object, structured: dict) -> bool:
    if not isinstance(content_evidence, str):
        return False
    try:
        return json.loads(content_evidence) == structured
    except (TypeError, ValueError):
        return False


def normalize_mcp_result(result: object) -> NormalizedMCPResult:
    """Normalize text, structured, and mixed MCP replies without double delivery.

    Structured content is the mechanical driver's authoritative view. Distinct
    text remains supplemental evidence; a serialized mirror is discarded.
    """
    if not isinstance(result, dict):
        raise MCPResultError("MCP tool result must be an object")
    raw_error = result.get("isError", False)
    if not isinstance(raw_error, bool):
        raise MCPResultError("MCP isError must be a boolean")
    has_structured = "structuredContent" in result
    has_content = "content" in result
    structured = result.get("structuredContent")
    if has_structured:
        if not isinstance(structured, dict):
            raise MCPResultError("MCP structuredContent must be an object")
        _json_value(structured, "MCP structuredContent")
    content_evidence = _content_evidence(result.get("content")) if has_content else None
    if has_structured and has_content:
        if _mirrors_structured(content_evidence, structured):
            evidence, shape = structured, "mixed_mirrored"
        else:
            evidence = {"structuredContent": structured,
                        "supplementalContent": content_evidence}
            shape = "mixed_distinct"
        return NormalizedMCPResult(evidence, structured, shape, raw_error)
    if has_structured:
        return NormalizedMCPResult(structured, structured, "structured_only", raw_error)
    if has_content:
        return NormalizedMCPResult(content_evidence, content_evidence, "content_only", raw_error)
    raise MCPResultError("MCP tool result contains no content")
