"""Deterministic checks for optional adapters and shared routing state."""

from io import BytesIO
import json
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from urllib.error import HTTPError

from rig_search import ingest, providers, router


class Response(BytesIO):
    status = 200


def data(url, *, limited=False, error=None):
    rows = [{"url": url, "title": "Result", "snippet": "Snippet"}] if url else []
    result = {"results": rows, "result_count": len(rows),
              "rate_limit_signal": limited, "backend_latency_seconds": 0.01}
    if error:
        result["error"] = error
    return result


class AdapterTests(unittest.TestCase):
    def test_cloud_search_import_is_explicitly_unverified(self):
        packet = {"query": "research query", "source": "model_web_search", "results": [
            {"url": "https://Example.org/a#part", "title": "A", "snippet": "One"},
            {"url": "https://example.org/a", "title": "duplicate"},
            {"url": "javascript:alert(1)", "title": "invalid"},
        ]}
        result = ingest.normalize(packet)
        self.assertEqual(result["unique_urls"], ["https://example.org/a"])
        self.assertEqual(result["results"][0]["verification_status"], "unfetched")

    def test_each_api_response_maps_to_search_contract(self):
        packets = {
            "tavily": {"results": [{"url": "https://Example.org/a#one", "title": "A",
                                    "content": "Tavily text", "published_date": "2026-01-01"}]},
            "exa": {"results": [{"url": "https://Example.org/a#one", "title": "A",
                                 "publishedDate": "2026-01-01"}]},
            "firecrawl": {"success": True, "data": {"web": [{
                "url": "https://Example.org/a#one", "title": "A", "description": "Firecrawl text"}]}},
            "serpapi": {"organic_results": [{"link": "https://Example.org/a#one",
                                              "title": "A", "snippet": "Serp text"}]},
        }
        for name, packet in packets.items():
            with self.subTest(name=name):
                requests = []

                def opener(request, timeout):
                    requests.append(request)
                    return Response(json.dumps(packet).encode())

                result = providers.search(name, "research query", 5, "secret-key", opener=opener)
                self.assertEqual(result["unique_urls"], ["https://example.org/a"])
                self.assertEqual(result["result_count"], 1)
                self.assertNotIn("secret-key", json.dumps(result))
                self.assertEqual(len(requests), 1)
                self.assertIn(name, providers.API_URLS)
                if name == "serpapi":
                    self.assertIn("api_key=secret-key", requests[0].full_url)
                else:
                    self.assertNotIn("secret-key", requests[0].full_url)

    def test_http_429_keeps_only_safe_status(self):
        def opener(request, timeout):
            raise HTTPError(request.full_url, 429, "rate limited", {"Retry-After": "12"}, None)

        result = providers.search("serpapi", "research query", 5, "secret-key", opener=opener)
        self.assertTrue(result["rate_limit_signal"])
        self.assertEqual(result["retry_after_seconds"], 12)
        self.assertNotIn("secret-key", json.dumps(result))

    def test_serpapi_success_without_organic_results_is_empty(self):
        def opener(request, timeout):
            packet = {"search_metadata": {"status": "Success"},
                      "search_information": {"organic_results_state": "Fully empty"},
                      "error": "Google hasn't returned any results for this query."}
            return Response(json.dumps(packet).encode())

        result = providers.search("serpapi", "restrictive query", 5,
                                  "secret-key", opener=opener)
        self.assertEqual(result["result_count"], 0)
        self.assertNotIn("error", result)


class RoutingTests(unittest.TestCase):
    def test_specific_provider_does_not_rotate_or_fall_back(self):
        with TemporaryDirectory() as temp:
            env = {"RIG_SEARCH_PROVIDERS": "searxng,exa", "SEARXNG_URL": "http://local",
                   "EXA_API_KEY": "secret", "RIG_SEARCH_MONTHLY_CAP_EXA": "1",
                   "RIG_SEARCH_ROUTING_MODE": "rotate"}
            state = router.BudgetState(Path(temp) / "state.sqlite3")
            calls = []
            searchers = {"searxng": lambda *_: self.fail("unexpected fallback"),
                         "exa": lambda *_: (calls.append("exa") or data(None))}
            result = router.search("research query", 5, env=env, state=state,
                                   searchers=searchers, provider="exa")
            self.assertEqual(calls, ["exa"])
            self.assertEqual(result["requested_provider"], "exa")
            self.assertEqual([a["provider"] for a in result["attempts"]], ["exa"])
            self.assertEqual(state.next_start(2), 0)
            exhausted = router.search("research query", 5, env=env, state=state,
                                      searchers=searchers, provider="exa")
            self.assertEqual(exhausted["attempts"], [{"provider": "exa",
                                                      "status": "budget_exhausted"}])
            with self.assertRaises(ValueError):
                router.search("research query", 5, env=env, provider="tavily")

    def test_rotates_and_reserves_paid_budget_across_calls(self):
        with TemporaryDirectory() as temp:
            env = {"RIG_SEARCH_PROVIDERS": "tavily,exa",
                   "RIG_SEARCH_ROUTING_MODE": "rotate",
                   "TAVILY_API_KEY": "t-secret", "EXA_API_KEY": "e-secret",
                   "RIG_SEARCH_MONTHLY_CAP_TAVILY": "2",
                   "RIG_SEARCH_MONTHLY_CAP_EXA": "2"}
            state = router.BudgetState(Path(temp) / "state.sqlite3")
            calls = []
            searchers = {name: (lambda query, limit, n=name: (calls.append(n) or
                                                    data(f"https://{n}.example/")))
                         for name in ("tavily", "exa")}
            first = router.search("research query", 5, env=env, state=state,
                                  searchers=searchers, min_results=1)
            second = router.search("research query", 5, env=env, state=state,
                                   searchers=searchers, min_results=1)
            self.assertEqual(calls, ["tavily", "exa"])
            self.assertEqual(first["provider"], "tavily")
            self.assertEqual(second["provider"], "exa")
            with closing(sqlite3.connect(state.path)) as db:
                self.assertEqual(db.execute("SELECT sum(used) FROM usage").fetchone()[0], 2)

    def test_budget_persists_across_state_instances(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "state.sqlite3"
            self.assertEqual(router.BudgetState(path).reserve("tavily", 1, now=1800000000), "ready")
            self.assertEqual(router.BudgetState(path).reserve("tavily", 1, now=1800000001),
                             "budget_exhausted")

    def test_paid_provider_requires_both_key_and_positive_cap(self):
        cases = (
            {"RIG_SEARCH_PROVIDERS": "tavily", "TAVILY_API_KEY": "secret"},
            {"RIG_SEARCH_PROVIDERS": "tavily", "RIG_SEARCH_MONTHLY_CAP_TAVILY": "1"},
        )
        for env in cases:
            with self.subTest(env=env):
                result = router.search("research query", 5, env=env,
                                       searchers={"tavily": lambda *_: self.fail("API was called")})
                self.assertEqual(result["attempts"],
                                 [{"provider": "tavily", "status": "unconfigured"}])

    def test_fallback_mode_keeps_first_healthy_provider(self):
        with TemporaryDirectory() as temp:
            env = {"RIG_SEARCH_PROVIDERS": "searxng,tavily",
                   "SEARXNG_URL": "http://local", "TAVILY_API_KEY": "secret",
                   "RIG_SEARCH_MONTHLY_CAP_TAVILY": "2"}
            state = router.BudgetState(Path(temp) / "state.sqlite3")
            calls = []
            searchers = {
                "searxng": lambda *_: (calls.append("searxng") or data("https://local.example/")),
                "tavily": lambda *_: self.fail("unneeded API call"),
            }
            for _ in range(2):
                router.search("research query", 5, env=env, state=state,
                              searchers=searchers, min_results=1)
            self.assertEqual(calls, ["searxng", "searxng"])

    def test_exhausted_budget_falls_back_without_extra_paid_call(self):
        with TemporaryDirectory() as temp:
            env = {"RIG_SEARCH_PROVIDERS": "tavily,searxng", "TAVILY_API_KEY": "secret",
                   "RIG_SEARCH_MONTHLY_CAP_TAVILY": "1", "SEARXNG_URL": "http://local"}
            state = router.BudgetState(Path(temp) / "state.sqlite3")
            calls = []
            searchers = {
                "tavily": lambda query, limit: (calls.append("tavily") or data("https://paid.example/")),
                "searxng": lambda query, limit: (calls.append("searxng") or data("https://local.example/")),
            }
            for _ in range(3):
                result = router.search("research query", 5, env=env, state=state,
                                       searchers=searchers, min_results=1)
            self.assertEqual(calls, ["tavily", "searxng", "searxng"])
            self.assertEqual(result["attempts"][0]["status"], "budget_exhausted")

    def test_rate_limit_cools_provider_and_uses_fallback(self):
        with TemporaryDirectory() as temp:
            env = {"RIG_SEARCH_PROVIDERS": "tavily,searxng", "TAVILY_API_KEY": "secret",
                   "RIG_SEARCH_MONTHLY_CAP_TAVILY": "5", "SEARXNG_URL": "http://local"}
            state = router.BudgetState(Path(temp) / "state.sqlite3")
            calls = []
            searchers = {
                "tavily": lambda query, limit: (calls.append("tavily") or
                                                data(None, limited=True, error="provider HTTP 429")),
                "searxng": lambda query, limit: (calls.append("searxng") or
                                                 data("https://local.example/")),
            }
            first = router.search("research query", 5, env=env, state=state,
                                  searchers=searchers, min_results=1)
            router.search("research query", 5, env=env, state=state,
                          searchers=searchers, min_results=1)
            third = router.search("research query", 5, env=env, state=state,
                                  searchers=searchers, min_results=1)
            self.assertEqual(calls, ["tavily", "searxng", "searxng", "searxng"])
            self.assertEqual(third["attempts"][0]["status"], "cooldown")
            self.assertFalse(first["rate_limit_signal"])
            self.assertEqual(first["attempts"][0]["status"], "rate_limited")

    def test_partial_results_merge_and_deduplicate(self):
        with TemporaryDirectory() as temp:
            env = {"RIG_SEARCH_PROVIDERS": "searxng,tavily", "TAVILY_API_KEY": "secret",
                   "RIG_SEARCH_MONTHLY_CAP_TAVILY": "1", "SEARXNG_URL": "http://local"}
            state = router.BudgetState(Path(temp) / "state.sqlite3")
            partial = data("https://example.org/a")
            extra = data("https://example.org/b")
            extra["results"].insert(0, {"url": "https://example.org/a#part", "title": "dup"})
            extra["result_count"] = 2
            result = router.search("research query", 5, env=env, state=state,
                                   searchers={"searxng": lambda *_: partial,
                                              "tavily": lambda *_: extra}, min_results=2)
            self.assertEqual(result["unique_urls"], ["https://example.org/a", "https://example.org/b"])
            self.assertEqual([row["provider"] for row in result["results"]],
                             ["searxng", "tavily"])


if __name__ == "__main__":
    unittest.main()
