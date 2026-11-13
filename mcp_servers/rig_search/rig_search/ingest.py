"""Normalize candidate URLs supplied by a cloud model's native web search."""

import argparse
import json
from pathlib import Path
import sys

from .searxng import MAX_RESULTS, clean_text, url_key


def normalize(packet, max_results=MAX_RESULTS):
    """Accept URLs as candidates; page fetch is required for verification."""
    if not isinstance(packet, dict) or not isinstance(packet.get("query"), str) or not isinstance(
            packet.get("results"), list):
        raise ValueError("expected an object with query and results")
    if not 3 <= len(packet["query"].strip()) <= 300 or not 1 <= max_results <= MAX_RESULTS:
        raise ValueError("invalid query or result limit")
    source = clean_text(packet.get("source", "cloud_model"), 80) or "cloud_model"
    rows, seen = [], set()
    for item in packet["results"]:
        if not isinstance(item, dict):
            continue
        url = url_key(item.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        rows.append({"url": url, "title": clean_text(item.get("title"), 180),
                     "snippet": clean_text(item.get("snippet"), 320),
                     "provider": source, "verification_status": "unfetched"})
        if len(rows) >= max_results:
            break
    urls = [row["url"] for row in rows]
    return {"query": packet["query"].strip(), "results": rows,
            "result_count": len(rows), "unique_urls": urls,
            "unique_url_count": len(urls), "provider": source,
            "verification_status": "unfetched"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", help="JSON file with query and results, or - for stdin")
    parser.add_argument("--max-results", type=int, default=MAX_RESULTS)
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8-sig")
        data = normalize(json.loads(raw), args.max_results)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(data, ensure_ascii=False))
    return 0
