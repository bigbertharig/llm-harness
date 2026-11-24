#!/usr/bin/env python3
"""Deterministic delayed-job fixture for supervisor and restart contracts."""

from __future__ import annotations

import argparse
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=2)
    parser.add_argument("--delay-ms", type=int, default=10)
    parser.add_argument("--exit-code", type=int, default=0)
    parser.add_argument("--marker", default="DELAYED_JOB_COMPLETE")
    args = parser.parse_args()
    if not 0 <= args.steps <= 100 or not 0 <= args.delay_ms <= 10_000:
        parser.error("fixture bounds exceeded")
    for index in range(args.steps):
        print(f"PROGRESS {index + 1}/{args.steps}", flush=True)
        time.sleep(args.delay_ms / 1000)
    print(args.marker, flush=True)
    if args.exit_code:
        print(f"fixture exiting with {args.exit_code}", file=sys.stderr, flush=True)
    return args.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
