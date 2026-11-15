#!/usr/bin/env python3
"""Read-only MCP projection of the gateway dashboard's rig and activity data."""

import argparse
from datetime import datetime, timezone
import json
import os
import sys
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


TOOLS = [
    ("get_rig_status", "Report rig reachability, controller heartbeat, GPU scan, availability, loaded profiles, claims, and safety guard."),
    ("get_model_status", "List the dashboard's active and candidate models with roles."),
    ("get_benchmark_status", "Summarize active and recent benchmark lanes and campaigns."),
    ("get_orchestration_status", "Read orchestration brain, worker, and active batch status."),
    ("get_orchestration_diagnostics", "Check orchestration brain and worker heartbeats."),
    ("get_orchestration_activity", "Page through an active or last-day batch event journal."),
]
SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}
ACTIVITY_SCHEMA = {"type": "object", "properties": {
    "batch_id": {"type": "string", "description": "Active or recently finished batch ID"},
    "after": {"type": "integer", "minimum": 0, "description": "Cursor from a previous page"}},
    "required": ["batch_id"], "additionalProperties": False}
ROUTES = {
    "get_rig_status": "/v1/manager/status",
    "get_model_status": "/dashboard/api/models",
    "get_benchmark_status": "/dashboard/api/benchmarks",
    "get_orchestration_status": "/dashboard/api/orchestration",
    "get_orchestration_diagnostics": "/dashboard/api/orchestration/diagnostics",
    "get_orchestration_activity": "/dashboard/api/orchestration/activity",
}


def endpoint(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost")
            or parsed.username or parsed.password or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment):
        raise ValueError("gateway endpoint must be loopback HTTP")
    return value.rstrip("/")


def read(base, name, arguments=None):
    headers = {}
    if os.environ.get("LLM_GATEWAY_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["LLM_GATEWAY_API_KEY"]
    path = ROUTES[name]
    if name == "get_orchestration_activity":
        path += "?" + urlencode(arguments)
    with urlopen(Request(base + path, headers=headers), timeout=15) as response:
        data = json.load(response)
    if not isinstance(data, dict) or "error" in data:
        raise ValueError("dashboard source unavailable")
    return data


def project(name, data):
    if name in ("get_orchestration_status", "get_orchestration_diagnostics", "get_orchestration_activity"):
        return data
    if name == "get_rig_status":
        controller = data.get("controller") or {}
        active = controller.get("active") or {}
        stamp = active.get("heartbeat_at")
        try:
            age = max(0, round((datetime.now(timezone.utc) -
                                datetime.fromisoformat(stamp.replace("Z", "+00:00"))).total_seconds()))
        except (AttributeError, TypeError, ValueError):
            age = None
        rig = data.get("rig") or {}
        scan = data.get("gpu_scan") or {}
        return {
            "observed_at": data.get("observed_at"), "mode": data.get("mode"),
            "from_copy": data.get("from_copy", False), "summary": data.get("summary"),
            "rig": {k: rig.get(k) for k in ("reachable", "down_since", "copy_saved_at")},
            "controller": {"id": active.get("id"), "in_control": controller.get("in_control"),
                           "heartbeat_at": stamp, "heartbeat_age_seconds": age,
                           "stale": active.get("stale")},
            "gpu_scan": {k: scan.get(k) for k in ("ok", "ids", "errors")},
            "guard": {k: (data.get("guard") or {}).get(k) for k in
                      ("level", "loads_admitted", "why", "gpu_temp_max_c", "mem_available_mb")},
            "gpus": [{k: row.get(k) for k in ("gpu", "name", "verdict", "claim", "vram_mb")}
                     for row in (data.get("gpus") or [])[:16]],
            "profiles": [{"id": key, "state": value.get("state"), "model": value.get("model"),
                          "gpus": value.get("gpus")}
                         for key, value in list((data.get("profiles") or {}).items())[:20]
                         if isinstance(value, dict)],
            "claims": [{"name": row.get("name"), "gpu_ids": row.get("gpu_ids"),
                        "purpose": row.get("purpose")}
                       for row in (data.get("claims") or [])[:20]],
            "active_jobs": sum(row.get("state") not in ("done", "finished", "failed", "cancelled", "stopped")
                               for row in (data.get("jobs") or [])),
        }
    if name == "get_model_status":
        rows = data.get("models") or []
        return {"generated_at": data.get("generated_at"), "total_models": len(rows),
                "models": [{k: row.get(k) for k in ("model", "status", "placement", "tier", "roles")}
                           for row in rows if row.get("status") in ("active", "candidate")][:50],
                "roles": data.get("roles") or {}}
    lanes = data.get("lanes") or []
    campaigns = data.get("campaigns") or []
    return {"generated_at": data.get("generated_at"), "active_lanes": [
                {"run": row.get("run"), "lane": row.get("lane"),
                 "last": str(row.get("last") or "")[:240], "age_s": row.get("age_s"),
                 "queued": (row.get("queued") or [])[:10]}
                for row in lanes if row.get("active")][:12],
            "recent_campaigns": [{"campaign": row.get("campaign"), "run_id": row.get("run_id"),
                                  "status": row.get("status"), "blocks": row.get("blocks"),
                                  "current": (row.get("current") or [])[:10],
                                  "updated_age_s": row.get("updated_age_s")}
                                 for row in campaigns[:12]]}


def respond(ident, result):
    print(json.dumps({"jsonrpc": "2.0", "id": ident, "result": result}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway", default="http://127.0.0.1:8080")
    base = endpoint(parser.parse_args().gateway)
    for line in sys.stdin:
        try:
            packet = json.loads(line)
            ident, method = packet.get("id"), packet.get("method")
            if ident is None:
                continue
            if method == "initialize":
                respond(ident, {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                                "serverInfo": {"name": "rig-info", "version": "1.0.0"}})
            elif method == "ping":
                respond(ident, {})
            elif method == "tools/list":
                respond(ident, {"tools": [{"name": name, "description": description,
                                           "inputSchema": ACTIVITY_SCHEMA if name == "get_orchestration_activity" else SCHEMA}
                                          for name, description in TOOLS]})
            elif method == "tools/call":
                params = packet.get("params") or {}
                name, arguments = params.get("name"), params.get("arguments") or {}
                valid_activity = (name == "get_orchestration_activity" and
                                  isinstance(arguments.get("batch_id"), str) and
                                  0 < len(arguments["batch_id"]) <= 160 and
                                  set(arguments) <= {"batch_id", "after"} and
                                  isinstance(arguments.get("after", 0), int) and arguments.get("after", 0) >= 0)
                if name not in ROUTES or (not valid_activity if name == "get_orchestration_activity" else arguments != {}):
                    result = {"isError": True, "content": [{"type": "text", "text": "unknown tool or arguments"}]}
                else:
                    try:
                        value = project(name, read(base, name, arguments))
                        result = {"isError": False, "content": [{"type": "text", "text": json.dumps(value)}],
                                  "structuredContent": value}
                    except Exception as exc:
                        result = {"isError": True, "content": [{"type": "text", "text":
                                  f"{type(exc).__name__}: dashboard source unavailable"}]}
                respond(ident, result)
            else:
                print(json.dumps({"jsonrpc": "2.0", "id": ident, "error":
                                  {"code": -32601, "message": "Method not found"}}), flush=True)
        except (ValueError, TypeError, AttributeError):
            continue


if __name__ == "__main__":
    main()
