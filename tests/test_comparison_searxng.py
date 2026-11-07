"""Offline integration check for the optional SearXNG web-search lane."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import comparison_web_search as comparison  # noqa: E402


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlsplit(self.path)
        params = parse_qs(parsed.query)
        if parsed.path != "/search" or params.get("format") != ["json"]:
            self.send_error(400)
            return
        if params.get("q") == ["rate limit"]:
            self.send_response(429)
            self.end_headers()
            return
        urls = ["https://example.org/one", "https://docs.python.org/3/library/asyncio-task.html",
                "https://example.org/three", "https://example.org/four",
                "https://example.org/five", "https://example.org/six"]
        body = json.dumps({"results": [{"url": url, "title": f"Result {i}", "content": "Snippet"}
                                         for i, url in enumerate(urls)]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


class ComparisonSearxngContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
        Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.endpoint = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_direct_gate_and_candidate_share_searxng_server(self):
        case = comparison.QUERIES[0]
        invoked = []
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"SEARXNG_URL": self.endpoint}), \
             patch.object(comparison.common, "ROOT", Path(temp)), \
             patch.object(comparison.matrix, "candidate_roster", return_value={"ready": True}):
            def candidate_driver(out, prompt, server, target, system):
                invoked.append(server)
                self.assertEqual(server["command"][1], str(comparison.SERVERS["searxng"]))
                self.assertEqual(server["command"][-2:], ["--endpoint", self.endpoint])
                self.assertEqual(target, "search_web")
                with patch.dict(os.environ, {"SEARXNG_URL": ""}):
                    call = comparison.direct_baseline(server, {"query": case["query"], "max_results": 10}, out)
                (out / "baseline_calls.jsonl").replace(out / "calls.jsonl")
                url = call["structuredContent"]["unique_urls"][1]
                return {"answer": json.dumps({"url": url, "unique_url_count": 6}),
                        "finish_reason": "stop", "exit_code": 0, "errors": []}

            with patch.dict(comparison.DRIVERS, {"pi": candidate_driver}):
                row = comparison.run_case("pi", case, "fixture", backend="searxng")
            self.assertTrue(row["passed"], row)
            self.assertEqual(len(invoked), 1)
            out = Path(temp) / "results" / "fixture" / "searxng" / "pi" / case["id"]
            self.assertEqual(json.loads((out / "fixture.json").read_text())["backend"], "searxng")
            self.assertEqual(json.loads((out / "summary.json").read_text())["backend"], "searxng")
            self.assertTrue((out / "baseline_calls.jsonl").exists())
            self.assertEqual(comparison.result_root("fixture", "ddg"), Path(temp) / "results" / "fixture")

    def test_rate_limit_and_low_yield_block_candidate(self):
        case = comparison.QUERIES[0]
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"SEARXNG_URL": self.endpoint}):
            server = comparison.search_server("searxng", Path(temp) / "calls.jsonl")
            limited = comparison.direct_baseline(server, {"query": "rate limit", "max_results": 10}, Path(temp))
            self.assertFalse(comparison.baseline_passes(limited, case))
            self.assertTrue(limited["structuredContent"]["rate_limit_signal"])
            small = comparison.direct_baseline(server, {"query": case["query"], "max_results": 2}, Path(temp))
            self.assertFalse(comparison.baseline_passes(small, case))
            self.assertTrue(comparison.baseline_passes(
                comparison.direct_baseline(server, {"query": case["query"], "max_results": 10}, Path(temp)), case))


if __name__ == "__main__":
    unittest.main()
