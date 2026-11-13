"""Command line access to the same search contract as the MCP adapter."""

import argparse
import json
import os
import sqlite3

from .searxng import MAX_RESULTS
from .router import search


def main(argv=None):
    parser = argparse.ArgumentParser(description="Search through configured web providers")
    parser.add_argument("query", help="search query, 3 to 300 characters")
    parser.add_argument("--max-results", type=int, default=5, choices=range(1, MAX_RESULTS + 1))
    parser.add_argument("--min-results", type=int, default=None,
                        help="try a fallback until this many distinct URLs are found (default: 3)")
    parser.add_argument("--endpoint", default=os.environ.get("SEARXNG_URL", ""))
    args = parser.parse_args(argv)
    query = args.query.strip()
    if not 3 <= len(query) <= 300:
        parser.error("query must contain 3 to 300 characters")
    if args.min_results is not None and not 1 <= args.min_results <= args.max_results:
        parser.error("min-results must be between 1 and max-results")
    try:
        data = search(query, args.max_results, args.endpoint, min_results=args.min_results)
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.error(str(exc))
    print(json.dumps(data, ensure_ascii=False))
    return 1 if data.get("error") else 0
