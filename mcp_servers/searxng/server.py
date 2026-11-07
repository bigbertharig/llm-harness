#!/usr/bin/env python3
"""Small stdio MCP search server backed by a configured SearXNG JSON endpoint.

Set SEARXNG_URL to the instance root (or its /search path). No search is
attempted until a tools/call request arrives.
"""

import json
import os
from pathlib import Path
import socket
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


MAX_RESULTS = 10
MAX_RESPONSE_BYTES = 2_000_000
TOOL = {
    "name": "search_web",
    "title": "Search the Web",
    "description": "Search the live web through SearXNG. Returns ranked, distinct URLs with titles, snippets, source engines, and search-health signals. Choose the query; use a separate page reader for details absent from snippets.",
    "annotations": {"readOnlyHint": True},
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 3, "maxLength": 300},
            "max_results": {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}


def clean_text(value, limit):
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def url_key(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            return None
        host = parts.hostname.lower()
        port = parts.port
        if port and not ((parts.scheme.lower(), port) in (("http", 80), ("https", 443))):
            host += f":{port}"
        return urlunsplit((parts.scheme.lower(), host, parts.path or "/", parts.query, ""))
    except ValueError:
        return None


def endpoint_url(endpoint, query):
    parts = urlsplit(endpoint.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc or parts.username or parts.password:
        raise ValueError("SEARXNG_URL must be an http(s) instance URL without embedded credentials")
    path = parts.path.rstrip("/")
    if not path.endswith("/search"):
        path += "/search"
    return urlunsplit((parts.scheme, parts.netloc, path,
                       urlencode({"q": query, "format": "json", "pageno": 1}), ""))


def unresponsive_engines(value):
    """Keep bounded diagnostics without assuming every SearXNG engine uses one shape."""
    if not isinstance(value, list):
        return []
    issues = []
    for item in value[:8]:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            name, reason = item[:2]
        elif isinstance(item, dict):
            name, reason = item.get("name") or item.get("engine"), item.get("reason") or item.get("error")
        else:
            continue
        name, reason = clean_text(name, 60), clean_text(reason, 160)
        if name or reason:
            issues.append({"engine": name, "reason": reason})
    return issues


def search(query, max_results, endpoint, opener=urlopen, timeout=15):
    """Return compact results and operational status; never expose endpoint details."""
    if not endpoint:
        return {"results": [], "result_count": 0, "rate_limit_signal": False,
                "error": "SEARXNG_URL is not configured"}
    try:
        request = Request(endpoint_url(endpoint, query), headers={
            "Accept": "application/json", "User-Agent": "llm-harness-searxng-mcp/1"})
    except ValueError as exc:
        return {"results": [], "result_count": 0, "rate_limit_signal": False, "error": str(exc)}
    started = time.monotonic()
    try:
        with opener(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("response too large")
            packet = json.loads(raw)
        if not isinstance(packet, dict) or not isinstance(packet.get("results"), list):
            raise ValueError("invalid SearXNG JSON response")
        seen = set()
        results = []
        for item in packet["results"]:
            if not isinstance(item, dict):
                continue
            key = url_key(item.get("url"))
            if not key or key in seen:
                continue
            seen.add(key)
            result = {"url": key, "title": clean_text(item.get("title"), 180),
                      "snippet": clean_text(item.get("content"), 320)}
            sources = item.get("engines")
            if isinstance(sources, list):
                sources = [clean_text(name, 40) for name in sources[:4] if isinstance(name, str)]
            else:
                sources = []
            if not sources and isinstance(item.get("engine"), str):
                sources = [clean_text(item["engine"], 40)]
            if sources:
                result["engines"] = sources
            if isinstance(item.get("publishedDate"), str):
                result["published_at"] = clean_text(item["publishedDate"], 40)
            results.append(result)
            if len(results) >= max_results:
                break
        issues = unresponsive_engines(packet.get("unresponsive_engines"))
        engine_notes = json.dumps(issues).lower()
        limited = any(term in engine_notes for term in ("429", "rate limit", "too many", "throttl"))
        urls = [item["url"] for item in results]
        suggestions = packet.get("suggestions")
        suggestions = [clean_text(item, 120) for item in suggestions[:3] if isinstance(item, str)] if isinstance(suggestions, list) else []
        corrections = packet.get("corrections")
        corrections = [clean_text(item, 120) for item in corrections[:2] if isinstance(item, str)] if isinstance(corrections, list) else []
        data = {"results": results, "result_count": len(results),
                "unique_urls": urls, "unique_url_count": len(urls),
                "rate_limit_signal": limited, "degraded": bool(issues),
                "unresponsive_engines": issues, "http_status": status,
                "backend_latency_seconds": round(time.monotonic() - started, 3)}
        if suggestions:
            data["suggestions"] = suggestions
        if corrections:
            data["corrections"] = corrections
        if not results and issues:
            data["error"] = "no results; upstream engines reported failures"
        return data
    except HTTPError as exc:
        result = {"results": [], "result_count": 0, "rate_limit_signal": exc.code == 429,
                  "degraded": True, "http_status": exc.code,
                  "backend_latency_seconds": round(time.monotonic() - started, 3),
                  "error": ("SearXNG HTTP 403: JSON format disabled or access denied" if exc.code == 403
                            else f"SearXNG HTTP {exc.code}")}
        if exc.code == 429:
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            if retry_after and retry_after.isdecimal():
                result["retry_after_seconds"] = min(int(retry_after), 3600)
        return result
    except (URLError, TimeoutError, OSError) as exc:
        kind = "timeout" if isinstance(exc, (TimeoutError, socket.timeout)) or isinstance(getattr(exc, "reason", None), (TimeoutError, socket.timeout)) else "network_error"
        return {"results": [], "result_count": 0, "rate_limit_signal": False,
                "degraded": True, "backend_latency_seconds": round(time.monotonic() - started, 3),
                "error": f"SearXNG {kind}"}
    except (ValueError, UnicodeError):
        return {"results": [], "result_count": 0, "rate_limit_signal": False,
                "degraded": True, "backend_latency_seconds": round(time.monotonic() - started, 3),
                "error": "invalid SearXNG JSON response"}


def tool_call(params, endpoint):
    args = params.get("arguments") if isinstance(params, dict) else None
    if (not isinstance(params, dict) or params.get("name") != "search_web" or
            not isinstance(args, dict) or set(args) - {"query", "max_results"} or
            not isinstance(args.get("query"), str) or
            not 3 <= len(args["query"].strip()) <= 300 or
            type(args.get("max_results", 5)) is not int or
            not 1 <= args.get("max_results", 5) <= MAX_RESULTS):
        return {"isError": True, "content": [{"type": "text", "text": "invalid search_web arguments"}]}
    data = search(args["query"].strip(), args.get("max_results", 5), endpoint)
    return {"isError": bool(data.get("error")), "content": [{"type": "text", "text": json.dumps(data)}],
            "structuredContent": data}


def handle(message, endpoint):
    method = message.get("method")
    if method == "notifications/initialized" or "id" not in message:
        return None
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "harness-searxng-search", "version": "1.0.0"},
                  "instructions": "Use search_web for web discovery. Choose a concise query, then inspect returned source URLs and snippets. Fetch a page with a separate page-reading tool before relying on details absent from a snippet."}
    elif method == "tools/list":
        result = {"tools": [TOOL]}
    elif method == "tools/call":
        result = tool_call(message.get("params"), endpoint)
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": message["id"],
                "error": {"code": -32601, "message": "Method not found"}}
    return {"jsonrpc": "2.0", "id": message["id"], "result": result}


def main():
    endpoint = os.environ.get("SEARXNG_URL", "")
    receipt = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if len(sys.argv) > 2:
        if len(sys.argv) != 4 or sys.argv[2] != "--endpoint":
            raise SystemExit("usage: server.py [receipt.jsonl] [--endpoint URL]")
        endpoint = sys.argv[3]

    def write(entry):
        if receipt is not None:
            with receipt.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"at_unix": time.time(), **entry}) + "\n")

    for line in sys.stdin:
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                continue
            reply = handle(message, endpoint)
            if message.get("method") == "tools/call":
                params = message.get("params")
                params = params if isinstance(params, dict) else {}
                result = (reply or {}).get("result", {})
                data = result.get("structuredContent", {})
                write({"method": "tools/call", "tool": params.get("name"),
                       "arguments": params.get("arguments")})
                write({"method": "tool/result", "tool": params.get("name"),
                       "arguments": params.get("arguments"), "urls": data.get("unique_urls", []),
                       "result_count": data.get("result_count", 0),
                       "unique_url_count": data.get("unique_url_count", 0),
                       "backend_latency_seconds": data.get("backend_latency_seconds"),
                       "rate_limit_signal": data.get("rate_limit_signal", False),
                       "degraded": data.get("degraded", False),
                       "unresponsive_engines": data.get("unresponsive_engines", []),
                       "http_status": data.get("http_status"), "error": data.get("error")})
            if reply is not None:
                print(json.dumps(reply), flush=True)
        except (ValueError, TypeError):
            # Invalid JSON cannot be associated with a request id.
            continue


if __name__ == "__main__":
    main()
