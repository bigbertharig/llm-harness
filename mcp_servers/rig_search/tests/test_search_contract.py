"""Deterministic contract checks for the standalone SearXNG MCP server."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit


from rig_search import searxng as tool
from rig_search import mcp


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        if parsed.path != "/search" or query.get("format") != ["json"] or query.get("pageno") != ["1"]:
            self.send_error(400)
            return
        if query.get("q") == ["rate limit"]:
            self.send_response(429)
            self.send_header("Retry-After", "12")
            self.end_headers()
            return
        if query.get("q") == ["json forbidden"]:
            self.send_error(403)
            return
        packet = {"results": [
            {"url": "https://Example.org/a#part", "title": "  Alpha\n Title ", "content": " One   snippet ",
             "engines": ["brave", "duckduckgo"], "publishedDate": "2026-11-01T00:00:00Z"},
            {"url": "https://example.org/a", "title": "duplicate"},
            {"url": "javascript:alert(1)", "title": "bad"},
            {"url": "https://example.org/b", "title": "Beta", "content": "B"},
            {"url": "https://example.org/c", "title": "Gamma", "content": "C"},
        ]}
        if query.get("q") in (["degraded search"], ["all blocked"]):
            packet["unresponsive_engines"] = [["brave", "HTTP error 429"], ["bing", "timeout"]]
            packet["suggestions"] = ["narrow query", "another query"]
            packet["corrections"] = ["corrected query"]
        if query.get("q") == ["all blocked"]:
            packet["results"] = []
        body = json.dumps(packet).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


class SearchContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.endpoint = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_normalization_dedup_and_cap(self):
        data = tool.search("search terms", 2, self.endpoint)
        self.assertEqual(data["http_status"], 200)
        self.assertEqual(data["result_count"], 2)
        self.assertEqual(data["unique_url_count"], 2)
        self.assertEqual(data["unique_urls"], ["https://example.org/a", "https://example.org/b"])
        self.assertEqual([r["url"] for r in data["results"]],
                         ["https://example.org/a", "https://example.org/b"])
        self.assertEqual(data["results"][0]["title"], "Alpha Title")
        self.assertEqual(data["results"][0]["snippet"], "One snippet")
        self.assertEqual(data["results"][0]["engines"], ["brave", "duckduckgo"])
        self.assertEqual(data["results"][0]["published_at"], "2026-11-01T00:00:00Z")

    def test_discovery_urls_exclude_private_hosts_and_credentials(self):
        for url in ("http://127.0.0.1/admin", "http://10.0.0.3/",
                    "http://localhost/", "http://host.local/",
                    "https://user:secret@example.org/path", "http://[::1]/"):
            with self.subTest(url=url):
                self.assertIsNone(tool.url_key(url))
        self.assertEqual(tool.url_key("https://example.org/a#part"),
                         "https://example.org/a")

    def test_degraded_search_and_query_hints(self):
        data = tool.search("degraded search", 5, self.endpoint)
        self.assertTrue(data["degraded"])
        self.assertTrue(data["rate_limit_signal"])
        self.assertEqual(data["unresponsive_engines"][0],
                         {"engine": "brave", "reason": "HTTP error 429"})
        self.assertEqual(data["suggestions"], ["narrow query", "another query"])
        self.assertEqual(data["corrections"], ["corrected query"])
        self.assertEqual(data["result_count"], 3)
        with patch.dict(os.environ, {"RIG_SEARCH_PROVIDERS": "searxng"}):
            empty = mcp.tool_call({"name": "search_web", "arguments": {"query": "all blocked"}}, self.endpoint)
        self.assertTrue(empty["isError"])
        self.assertEqual(empty["structuredContent"]["result_count"], 0)

    def test_rate_limit_signal_and_missing_config(self):
        limited = tool.search("rate limit", 5, self.endpoint + "/search")
        self.assertTrue(limited["rate_limit_signal"])
        self.assertEqual(limited["http_status"], 429)
        self.assertEqual(limited["retry_after_seconds"], 12)
        self.assertIn("backend_latency_seconds", limited)
        forbidden = tool.search("json forbidden", 5, self.endpoint)
        self.assertEqual(forbidden["http_status"], 403)
        self.assertIn("JSON format disabled or access denied", forbidden["error"])
        self.assertEqual(tool.search("search terms", 5, "")["error"],
                         "SEARXNG_URL is not configured")

    def test_cli_contract(self):
        proc = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "search.py"),
                               "search terms", "--max-results", "2", "--endpoint", self.endpoint],
                              text=True, capture_output=True, timeout=8,
                              env={**os.environ, "RIG_SEARCH_PROVIDERS": "searxng"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["unique_urls"], ["https://example.org/a", "https://example.org/b"])
        self.assertEqual(data["result_count"], 2)

    def test_mcp_stdio_contract(self):
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                "name": "search_web", "arguments": {"query": "search terms", "max_results": 2}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
                "name": "search_web", "arguments": {"query": "x", "max_results": True}}},
        ]
        proc = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "mcp_server.py")],
                              input="\n".join(map(json.dumps, messages)) + "\n",
                              text=True, capture_output=True, timeout=8,
                              env={**os.environ, "SEARXNG_URL": self.endpoint,
                                   "RIG_SEARCH_PROVIDERS": "searxng"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, "")
        replies = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual([r["id"] for r in replies], [1, 2, 3, 4])
        self.assertIn("search_web", replies[0]["result"]["instructions"])
        self.assertEqual(replies[1]["result"]["tools"][0]["name"], "search_web")
        self.assertTrue(replies[1]["result"]["tools"][0]["annotations"]["readOnlyHint"])
        self.assertEqual(replies[2]["result"]["structuredContent"]["result_count"], 2)
        self.assertFalse(replies[2]["result"]["isError"])
        self.assertTrue(replies[3]["result"]["isError"])

    def test_mcp_receipt_omits_query_and_urls(self):
        with TemporaryDirectory() as temp:
            receipt = Path(temp) / "search.jsonl"
            message = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "search_web", "arguments": {
                           "query": "private project name", "max_results": 2}}}
            proc = subprocess.run(
                [sys.executable, str(Path(__file__).resolve().parents[1] / "mcp_server.py"),
                 str(receipt)], input=json.dumps(message) + "\n", text=True,
                capture_output=True, timeout=8,
                env={**os.environ, "SEARXNG_URL": self.endpoint,
                     "RIG_SEARCH_PROVIDERS": "searxng"})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            record = receipt.read_text()
            self.assertNotIn("private project name", record)
            self.assertNotIn("https://example.org", record)
            self.assertEqual([row["call_index"] for row in map(json.loads, record.splitlines())],
                             [1, 1])


if __name__ == "__main__":
    unittest.main()
