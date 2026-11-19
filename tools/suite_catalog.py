"""List existing harness test lanes without starting a model or changing rig state."""

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "tools/suite_catalog.json"


def validate(catalog, root=ROOT):
    errors = []
    if catalog.get("schema_version") != 1:
        errors.append("unsupported schema_version")
    offline = catalog.get("offline", {})
    if offline.get("command") != ["python3", "-m", "pytest", "-q", "tests"]:
        errors.append("offline command must run the existing tests directory")
    if offline.get("test_directory") != "tests" or not (root / "tests").is_dir():
        errors.append("offline test directory is missing")
    seen = set()
    for lane in catalog.get("live_lanes", []):
        lane_id = lane.get("id")
        runner = lane.get("runner")
        if not lane_id or lane_id in seen:
            errors.append(f"missing or duplicate lane id: {lane_id!r}")
        seen.add(lane_id)
        if not isinstance(runner, str) or not runner.startswith("tools/") or not (root / runner).is_file():
            errors.append(f"missing runner for {lane_id}: {runner!r}")
        audit = lane.get("receipt_audit")
        if audit is not None and (not isinstance(audit, str) or not audit.startswith("tools/") or not (root / audit).is_file()):
            errors.append(f"missing receipt audit for {lane_id}: {audit!r}")
    if not seen:
        errors.append("no live lanes registered")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate paths and exit")
    args = parser.parse_args()
    catalog = json.loads(CATALOG.read_text())
    errors = validate(catalog)
    if errors:
        parser.exit(1, "\n".join(errors) + "\n")
    if args.check:
        print(f"OK: offline suite and {len(catalog['live_lanes'])} live lanes")
    else:
        print("offline: " + " ".join(catalog["offline"]["command"]))
        for lane in catalog["live_lanes"]:
            print(f"{lane['id']}: {lane['runner']}")


if __name__ == "__main__":
    main()
