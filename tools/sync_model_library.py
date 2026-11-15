#!/usr/bin/env python3
"""Import the benchmark-owned model library into a harness planning snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "tools/model_catalog.json"
DEFAULT_SOURCE = Path("/media/bryan/shared/plans/shoulders/benchmarking/model_library_export.json")


def load_source(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != "gpu-rig-model-library/1":
        raise ValueError("unsupported model-library export")
    payload = {key: value for key, value in doc.items() if key != "source_sha256"}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=True).encode("utf-8")).hexdigest()
    if digest != doc.get("source_sha256"):
        raise ValueError("model-library export hash mismatch")
    if not isinstance(doc.get("registry", {}).get("models"), dict) or not isinstance(doc.get("roles", {}).get("roles"), dict):
        raise ValueError("incomplete model-library export")
    return doc


def projection(source: Path) -> dict:
    doc = load_source(source)
    models = {}
    for mid, entry in doc["registry"]["models"].items():
        resolved = doc["resolved_profiles"][mid]
        models[mid] = {"status": entry["status"], "in_testing": bool(entry.get("in_testing")),
                       "aliases": entry.get("aliases", []),
                       "profiles": {name: {"context_limit": profile.get("runtime", {}).get("ctx_size"),
                                           "good_for": profile.get("good_for", [])}
                                    for name, profile in resolved.items()}}
    return {"schema": "harness-model-library/1", "source_sha256": doc["source_sha256"],
            "models": models,
            "roles": {name: {"model": row["model"], "profile": row.get("profile")}
                      for name, row in doc["roles"]["roles"].items()},
            "load_recipes": doc["load_recipes"]["recipes"],
            "subagent_catalog": doc["subagent_catalog"]["candidates"]}


def changes(old: dict, new: dict) -> dict:
    before, after = old.get("models", {}), new["models"]
    return {"added": sorted(after.keys() - before.keys()),
            "removed": sorted(before.keys() - after.keys()),
            "changed": sorted(key for key in before.keys() & after.keys() if before[key] != after[key])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("what-new", "sync", "check"))
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    try:
        after = projection(args.source)
        before = json.loads(DESTINATION.read_text(encoding="utf-8")) if DESTINATION.is_file() else {}
        stale = before != after
        print(json.dumps({"stale": stale, "source_sha256": after["source_sha256"],
                          "models": changes(before, after)}, sort_keys=True))
        if args.mode == "sync" and stale:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=DESTINATION.parent,
                                             prefix=".model_catalog.", suffix=".tmp",
                                             delete=False) as handle:
                json.dump(after, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
                temp = Path(handle.name)
            try:
                os.replace(temp, DESTINATION)
            finally:
                temp.unlink(missing_ok=True)
        return 1 if args.mode == "check" and stale else 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
