"""Contract checks for the harness's read-only gateway roster client."""

import io
import json
from unittest.mock import patch

import pytest

from ready_roster import fetch_ready_roster


def test_fetch_ready_roster_uses_only_status_endpoint():
    payload = {"object": "ready_roster", "version": 1, "data": [
        {"id": "gpu-rig/coder-7b", "model": "qwen2.5-coder:7b", "state": "ready",
         "context_length": 8192}]}
    with patch("ready_roster.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())) as open_url:
        assert fetch_ready_roster("http://localhost:8080/", "secret") == payload
    request = open_url.call_args.args[0]
    assert request.full_url == "http://localhost:8080/v1/rig/ready-roster"
    assert request.get_method() == "GET"
    assert request.get_header("Authorization") == "Bearer secret"


def test_fetch_ready_roster_rejects_incomplete_contract():
    payload = {"object": "ready_roster", "version": 1, "data": [
        {"id": "gpu-rig/coder-7b", "model": "qwen2.5-coder:7b", "state": "ready"}]}
    with patch("ready_roster.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())):
        with pytest.raises(ValueError, match="invalid ready route"):
            fetch_ready_roster("http://localhost:8080")
