"""Direct DuckDuckGo adapter contracts with no network requests."""

import unittest

from rig_search import duckduckgo


class FakeClient:
    def __init__(self, timeout):
        self.timeout = timeout
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def text(self, query, max_results, backend):
        self.calls.append((query, max_results, backend))
        return [
            {"href": "https://Example.org/a#part", "title": " First ", "body": " One "},
            {"href": "https://example.org/a", "title": "duplicate"},
            {"href": "javascript:bad", "title": "invalid"},
            {"href": "https://example.org/b", "title": "Second", "body": "Two"},
        ]


class RatelimitException(Exception):
    pass


class FailingClient(FakeClient):
    def text(self, query, max_results, backend):
        raise RatelimitException("429 on a private request URL")


class DirectDuckDuckGoTests(unittest.TestCase):
    def test_forces_named_backend_and_normalizes_results(self):
        client = FakeClient(timeout=12)
        result = duckduckgo.search("research query", 5, client_factory=lambda timeout: client)
        self.assertEqual(client.calls, [("research query", 5, "duckduckgo")])
        self.assertEqual(result["unique_urls"], ["https://example.org/a", "https://example.org/b"])
        self.assertEqual(result["search_backend"], "duckduckgo")
        self.assertFalse(result["rate_limit_signal"])

    def test_rate_limit_is_safe_and_available_to_router(self):
        result = duckduckgo.search("research query", 5, client_factory=FailingClient)
        self.assertTrue(result["rate_limit_signal"])
        self.assertEqual(result["error"], "duckduckgo rate_limited")
        self.assertNotIn("private request URL", str(result))


if __name__ == "__main__":
    unittest.main()
