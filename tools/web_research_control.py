#!/usr/bin/env python3
"""Direct search-JSON -> llm_orchestration CPU scraper contract control."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import tempfile
from threading import Thread
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen


FACT = "The archive beacon cadence is 37 minutes."
QUERY = "archive beacon cadence"


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlsplit(self.path)
        base = f"http://127.0.0.1:{self.server.server_port}"
        if parsed.path == "/search":
            params = parse_qs(parsed.query)
            if params.get("format") != ["json"] or params.get("q") != [QUERY]:
                self.send_error(400)
                return
            payload = {"query": QUERY, "results": [
                {"title": "Archive operations", "url": base + "/article/archive", "content": "An operations note; cadence absent from snippet."},
                {"title": "Unrelated archive", "url": base + "/article/distractor", "content": "No beacon measurement here."},
            ]}
            body = json.dumps(payload).encode()
            ctype = "application/json"
        elif parsed.path == "/article/archive":
            body = f"<html><head><title>Archive operations</title></head><body><main><h1>Beacon operations</h1><p>{FACT}</p></main></body></html>".encode()
            ctype = "text/html; charset=utf-8"
        elif parsed.path == "/article/distractor":
            body = b"<html><body><p>This page has no cadence fact.</p></body></html>"
            ctype = "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scraper", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        search_url = f"http://127.0.0.1:{server.server_port}/search?q=archive%20beacon%20cadence&format=json"
        with urlopen(search_url, timeout=5) as response:
            search = json.load(response)
        results = search.get("results", [])
        assert len(results) == 2 and all(item.get("url") for item in results)
        assert all(FACT not in item.get("content", "") for item in results)
        with tempfile.TemporaryDirectory(prefix="web_research_control_") as temp:
            batch = Path(temp)
            target = batch / "results"
            target.mkdir()
            (target / "approved_urls.json").write_text(json.dumps({"items": [{"id": "source_1", **results[0]}]}), encoding="utf-8")
            proc = subprocess.run(["python3", str(args.scraper), "--batch-id", "fixture", "--batch-path", str(batch), "--rate-limit", "0", "--timeout", "5"], capture_output=True, text=True, timeout=30)
            scraped_path = target / "source_1" / "scraped.json"
            scraped = json.loads(scraped_path.read_text(encoding="utf-8")) if scraped_path.exists() else {}
        checks = {
            "search_json": len(results) == 2,
            "snippet_does_not_contain_answer": all(FACT not in item.get("content", "") for item in results),
            "cpu_scraper_exit_zero": proc.returncode == 0,
            "cpu_scraper_status_ok": scraped.get("fetch_status") == "ok",
            "fact_in_fetched_page": FACT in scraped.get("page_text", ""),
            "source_url_preserved": scraped.get("url") == results[0]["url"],
        }
        receipt = {"kind": "searxng_json_compatible_fixture_plus_cpu_scraper", "passed": all(checks.values()), "checks": checks,
                   "expected_answer": "37 minutes", "source_url": results[0]["url"], "scraper": str(args.scraper),
                   "scraper_exit_code": proc.returncode, "scraper_stdout": proc.stdout.strip(), "scraper_stderr": proc.stderr.strip()[:500]}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"passed": receipt["passed"], "checks": checks, "receipt": str(args.out)}))
        raise SystemExit(0 if receipt["passed"] else 1)
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
