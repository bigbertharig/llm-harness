"""MCP stdio adapter for rig_search's search_web contract."""

import json
import os
from pathlib import Path
import sqlite3
import sys
import time

from .searxng import MAX_RESULTS
from .router import search

TOOL = {
    "name": "search_web",
    "title": "Search the Web",
    "description": "Search the live web through configured providers. Returns distinct URLs, provenance, and search-health signals. Use a separate page reader for details absent from snippets.",
    "annotations": {"readOnlyHint": True},
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 3, "maxLength": 300},
            "max_results": {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS},
            "min_results": {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}


def tool_call(params, endpoint):
    args = params.get("arguments") if isinstance(params, dict) else None
    if (not isinstance(params, dict) or params.get("name") != "search_web" or
            not isinstance(args, dict) or set(args) - {"query", "max_results", "min_results"} or
            not isinstance(args.get("query"), str) or
            not 3 <= len(args["query"].strip()) <= 300 or
            type(args.get("max_results", 5)) is not int or
            not 1 <= args.get("max_results", 5) <= MAX_RESULTS or
            type(args.get("min_results", 1)) is not int or
            not 1 <= args.get("min_results", 1) <= args.get("max_results", 5)):
        return {"isError": True, "content": [{"type": "text", "text": "invalid search_web arguments"}]}
    try:
        data = search(args["query"].strip(), args.get("max_results", 5), endpoint,
                      min_results=args.get("min_results"))
    except (ValueError, OSError, sqlite3.Error):
        data = {"results": [], "result_count": 0, "rate_limit_signal": False,
                "error": "search routing configuration or state failed"}
    return {"isError": bool(data.get("error")), "content": [{"type": "text", "text": json.dumps(data)}],
            "structuredContent": data}


def handle(message, endpoint):
    method = message.get("method")
    if method == "notifications/initialized" or "id" not in message:
        return None
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "rig-search", "version": "0.2.0"},
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
            raise SystemExit("usage: mcp_server.py [receipt.jsonl] [--endpoint URL]")
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
                       "provider": data.get("provider"),
                       "attempts": data.get("attempts", []),
                       "unresponsive_engines": data.get("unresponsive_engines", []),
                       "http_status": data.get("http_status"), "error": data.get("error")})
            if reply is not None:
                print(json.dumps(reply), flush=True)
        except (ValueError, TypeError):
            # Invalid JSON cannot be associated with a request id.
            continue
