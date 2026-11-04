"""Preflight handles both tokenizable and Strata-style ready routes."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from live_preflight import run


class LivePreflightTokenizerTest(unittest.TestCase):
    def check_route(self, tokenizer_path):
        route = {"id": "gpu-rig/test", "model": "test-model", "state": "ready",
                 "context_length": 8192, "tokenizer_path": tokenizer_path}
        roster = {"object": "ready_roster", "version": 1, "data": [route]}
        calls = []

        def fake_call(base, path, body=None):
            calls.append(path)
            if path == "/v1/rig/status":
                return 200, {"profiles": [{"id": "test", "model": "test-model",
                                            "port": 9000, "ctx_size": 8192, "lease": "abc"}]}
            if path == "/tokenize":
                return 200, {"tokens": [1, 2, 3]}
            if path == "/v1/chat/completions" and body["model"] == "gpu-rig/test":
                return 200, {"choices": [{"message": {"content": "ready"},
                                          "finish_reason": "stop"}]}
            if path == "/v1/models":
                return 200, {"data": [{"id": "gpu-rig/test"},
                                      {"id": "gpu-rig/cold"}]}
            if path == "/v1/chat/completions":
                return 409, {"error": {"type": "model_not_ready"}}
            raise AssertionError(path)

        with patch("live_preflight.fetch_ready_roster", return_value=roster), \
             patch("live_preflight.call", side_effect=fake_call):
            receipt = run("http://localhost:8080", "gpu-rig/test", "test-model")
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["tokenizer_check"],
                         "passed" if tokenizer_path else "unavailable")
        self.assertEqual(receipt["token_count"], 3 if tokenizer_path else None)
        self.assertEqual("/tokenize" in calls, bool(tokenizer_path))

    def test_no_tokenizer_path(self):
        self.check_route(None)

    def test_tokenizer_path(self):
        self.check_route("/tokenize")


if __name__ == "__main__":
    unittest.main()
