"""MCP stdio adapter for rig_search's search_web contract."""

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

from .searxng import MAX_RESULTS
from .router import KEY_ENV, PROVIDER_NAMES, search


ENV_FILE_NAMES = {"SEARXNG_URL", "RIG_SEARCH_STATE", "RIG_SEARCH_PROVIDERS",
                  "RIG_SEARCH_ROUTING_MODE", *KEY_ENV.values(),
                  *(f"RIG_SEARCH_MONTHLY_CAP_{name.upper()}" for name in KEY_ENV)}


def load_env_file(path):
    """Load literal KEY=VALUE entries without executing a shell or logging secrets."""
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("invalid search env file")
        name, value = (part.strip() for part in line.split("=", 1))
        if name not in ENV_FILE_NAMES:
            raise ValueError("unknown search env file variable")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ[name] = value

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
            "provider": {"type": "string", "enum": ["auto", *PROVIDER_NAMES]},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}


def tool_call(params, endpoint):
    args = params.get("arguments") if isinstance(params, dict) else None
    if (not isinstance(params, dict) or params.get("name") != "search_web" or
            not isinstance(args, dict) or set(args) - {"query", "max_results", "min_results", "provider"} or
            not isinstance(args.get("query"), str) or
            not 3 <= len(args["query"].strip()) <= 300 or
            type(args.get("max_results", 5)) is not int or
            not 1 <= args.get("max_results", 5) <= MAX_RESULTS or
            type(args.get("min_results", 1)) is not int or
            not 1 <= args.get("min_results", 1) <= args.get("max_results", 5) or
            args.get("provider", "auto") not in ("auto", *PROVIDER_NAMES)):
        return {"isError": True, "content": [{"type": "text", "text": "invalid search_web arguments"}]}
    try:
        data = search(args["query"].strip(), args.get("max_results", 5), endpoint,
                      min_results=args.get("min_results"),
                      provider=None if args.get("provider", "auto") == "auto" else args["provider"])
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
                  "serverInfo": {"name": "rig-search", "version": "0.3.0"},
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
    parser = argparse.ArgumentParser(description="Rig search MCP server")
    parser.add_argument("receipt", nargs="?", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--endpoint")
    parser.add_argument("--providers", help="comma-separated enabled provider subset")
    args = parser.parse_args()
    if args.env_file:
        try:
            load_env_file(args.env_file)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
    if args.providers:
        os.environ["RIG_SEARCH_PROVIDERS"] = args.providers
    endpoint = args.endpoint if args.endpoint is not None else os.environ.get("SEARXNG_URL", "")
    receipt = args.receipt

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
