#!/usr/bin/env python3
"""Bounded live comparison of the current provider adapters on matched queries."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rig_search import providers, searxng
from rig_search.router import BudgetState, KEY_ENV, PROVIDER_NAMES


MAX_CALLS_PER_PROVIDER = 8
DEFAULT_FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/provider_comparison_queries.json"
DEFAULT_STATE = Path.home() / ".local/state/rig-search/state.sqlite3"
ENV_FILE_NAMES = {"SEARXNG_URL", "RIG_SEARCH_STATE", "RIG_SEARCH_PROVIDERS",
                  "RIG_SEARCH_ROUTING_MODE", *KEY_ENV.values(),
                  *(f"RIG_SEARCH_MONTHLY_CAP_{name.upper()}" for name in KEY_ENV)}


def load_env_file(path):
    """Read the simple KEY=VALUE template without executing shell code."""
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("invalid env file line")
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if name not in ENV_FILE_NAMES:
            raise ValueError("unknown env file variable")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ[name] = value


def plan(fixture, names, env):
    cases = fixture.get("cases")
    if not isinstance(cases, list) or len(cases) != 4:
        raise ValueError("comparison fixture must contain exactly four cases")
    ids = [case.get("id") for case in cases if isinstance(case, dict)]
    if len(ids) != len(cases) or len(set(ids)) != len(ids):
        raise ValueError("comparison cases need distinct IDs")
    if any(not isinstance(case.get("query"), str) or
           not 3 <= len(case["query"].strip()) <= 300 for case in cases):
        raise ValueError("invalid comparison query")
    if not names or len(names) != len(set(names)) or any(name not in PROVIDER_NAMES for name in names):
        raise ValueError("providers must be distinct supported names")
    configured = {name: bool(env.get("SEARXNG_URL") if name == "searxng" else
                             env.get(KEY_ENV[name])) for name in names}
    return cases, configured


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--env-file", type=Path, help="private KEY=VALUE file to load without printing keys")
    parser.add_argument("--providers", default=",".join(PROVIDER_NAMES),
                        help="comma-separated providers; default is all five")
    parser.add_argument("--output", type=Path, help="JSON receipt path (required for --live)")
    parser.add_argument("--live", action="store_true", help="make at most eight calls per provider across runs")
    parser.add_argument("--pace-seconds", type=float, default=5)
    args = parser.parse_args(argv)
    if args.pace_seconds < 0 or (args.live and args.output is None):
        parser.error("live runs need --output and nonnegative pacing")
    names = [part.strip().lower() for part in args.providers.split(",") if part.strip()]
    try:
        if args.env_file is not None:
            load_env_file(args.env_file)
        fixture = json.loads(args.fixture.read_text(encoding="utf-8-sig"))
        cases, configured = plan(fixture, names, os.environ)
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    if not args.live:
        print(json.dumps({"mode": "dry_run", "cases": [case["id"] for case in cases],
                          "calls_per_provider_max": MAX_CALLS_PER_PROVIDER,
                          "configured": configured}, indent=2))
        return 0
    if not all(configured.values()):
        parser.error("all selected providers need a configured key or SEARXNG_URL")
    state = BudgetState(os.environ.get("RIG_SEARCH_STATE") or DEFAULT_STATE)
    receipt = {"at_utc": datetime.now(timezone.utc).isoformat(),
               "method": "same four queries; current generic adapters; five results each",
               "calls_per_provider_max": MAX_CALLS_PER_PROVIDER,
               "state_path": str(state.path), "cases": cases,
               "providers": names, "observations": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(args.output)

    save()
    for name in names:
        for case in cases:
            # Reserve before the request, including failures that might be billed.
            ready = state.reserve(name, MAX_CALLS_PER_PROVIDER)
            if ready != "ready":
                receipt["observations"].append({"provider": name, "case_id": case["id"],
                                                "status": ready})
                save()
                break
            result = (searxng.search(case["query"], 5, os.environ["SEARXNG_URL"]) if name == "searxng"
                      else providers.search(name, case["query"], 5, os.environ[KEY_ENV[name]]))
            receipt["observations"].append({"provider": name, "case_id": case["id"],
                                            "result": result})
            save()
            print(f"{name} {case['id']}: {result.get('result_count', 0)} URLs; "
                  f"error={bool(result.get('error'))}; limited={result.get('rate_limit_signal', False)}",
                  file=sys.stderr, flush=True)
            if result.get("rate_limit_signal") or result.get("error"):
                break
            time.sleep(args.pace_seconds)
    print(str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
