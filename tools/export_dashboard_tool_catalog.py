#!/usr/bin/env python3
"""Export the enabled dashboard projection from harness's full tool registry."""

import argparse
import json
import os
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "tool_registry.json"
OUTPUT = ROOT / "dashboard_tool_catalog.json"


def build(registry: dict) -> dict:
    if registry.get("schema_version") != 1 or not isinstance(registry.get("surfaces"), dict):
        raise ValueError("unsupported tool registry")
    servers = {}
    all_names = set()
    for name, surface in registry["surfaces"].items():
        if not isinstance(surface, dict) or not isinstance(surface.get("tools"), list):
            raise ValueError(f"invalid tool surface: {name}")
        if surface.get("category") not in {"search", "local_info", "delegate", "external", "diagnostics"}:
            raise ValueError(f"invalid tool category: {name}")
        if surface.get("status") not in {"dashboard", "candidate", "prototype", "external_observed", "external_live_discovered",
                                         "discovery_pending"}:
            raise ValueError(f"invalid tool status: {name}")
        tools = surface["tools"]
        if surface["status"] == "discovery_pending" and tools or surface["status"] != "discovery_pending" and not tools:
            raise ValueError(f"invalid discovery state: {name}")
        names = [tool.get("name") if isinstance(tool, dict) else None for tool in tools]
        if any(not isinstance(tool_name, str) or not tool_name.isidentifier() for tool_name in names):
            raise ValueError(f"invalid tool name: {name}")
        if len(names) != len(set(names)) or all_names.intersection(names):
            raise ValueError(f"tool name collision: {name}")
        all_names.update(names)
        if surface.get("status") != "dashboard":
            continue
        if surface.get("owner") != "llm-harness" or not name.isidentifier():
            raise ValueError(f"invalid dashboard surface: {name}")
        if any((set(tool) != {"name", "approval"} or
                tool["approval"] not in {"automatic", "disabled"}) if "status" not in tool else
               (tool["status"] != "prototype" or set(tool) != {"name", "status", "implementation"})
               for tool in tools):
            raise ValueError(f"invalid dashboard tools: {name}")
        enabled = [tool for tool in tools if "approval" in tool]
        if not enabled:
            raise ValueError(f"no dashboard tools: {name}")
        servers[name] = {"purpose": surface["purpose"], "tools": enabled}
    if not servers:
        raise ValueError("no dashboard tools")
    return {"schema_version": 1, "servers": servers}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "sync"))
    args = parser.parse_args()
    try:
        output = build(json.loads(REGISTRY.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    expected = json.dumps(output, indent=2, ensure_ascii=False) + "\n"
    current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else None
    if args.mode == "check":
        print("current" if current == expected else "stale")
        return 0 if current == expected else 1
    if current != expected:
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=OUTPUT.parent,
                                             prefix=".dashboard_tool_catalog.", suffix=".tmp", delete=False) as tmp:
                tmp.write(expected)
                tmp.flush()
                os.fsync(tmp.fileno())
                temp_name = tmp.name
            os.replace(temp_name, OUTPUT)
        finally:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)
    print("synced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
