#!/usr/bin/env python3
"""Replay preserved research queries through rig-search with bounded pacing."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rig_search.searxng import search, url_key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--endpoint", default=os.environ.get("SEARXNG_URL", ""))
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--pace-seconds", type=float, default=15)
    args = parser.parse_args()
    if not 1 <= args.max_results <= 10 or args.pace_seconds < 0:
        parser.error("max-results must be 1–10 and pace-seconds must be nonnegative")
    fixture = json.loads(args.fixture.read_text(encoding="utf-8-sig"))
    cases = fixture["cases"]
    if not isinstance(cases, list) or not 1 <= len(cases) <= 20:
        parser.error("fixture must contain 1–20 cases")

    receipt = {"at_utc": datetime.now(timezone.utc).isoformat(),
               "source_run": fixture.get("source_run"),
               "baseline_provider": fixture.get("baseline_provider"),
               "candidate": "rig-search SearXNG", "max_results": args.max_results,
               "pace_seconds": args.pace_seconds, "cases": [], "stop_reason": None}
    for index, case in enumerate(cases):
        query = case["query"]
        baseline = [url_key(url) for url in case.get("baseline_urls", [])]
        baseline = [url for url in baseline if url]
        result = search(query, args.max_results, args.endpoint)
        urls = result.get("unique_urls", [])
        row = {"query": query, "baseline_urls": baseline,
               "baseline_count": len(baseline), "candidate": result,
               "url_overlap": [url for url in urls if url in baseline]}
        receipt["cases"].append(row)
        print(f"{index + 1}/{len(cases)}: {len(urls)} URLs, "
              f"{len(row['url_overlap'])} overlap, "
              f"degraded={result.get('degraded', False)}, "
              f"limited={result.get('rate_limit_signal', False)}", file=sys.stderr, flush=True)
        if result.get("rate_limit_signal"):
            receipt["stop_reason"] = "rate_limit_signal"
            break
        if result.get("error"):
            receipt["stop_reason"] = "provider_error"
            break
        if index + 1 < len(cases):
            time.sleep(args.pace_seconds)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if not receipt["stop_reason"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
