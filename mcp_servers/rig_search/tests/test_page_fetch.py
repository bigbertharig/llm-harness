"""Page reader's public-address and MCP contract checks."""

import json
import socket
from unittest.mock import patch

import pytest

from rig_search import mcp, page_fetch


def test_rejects_private_dns_and_non_https():
    with patch.object(socket, "getaddrinfo", return_value=[(socket.AF_INET, 1, 0, "", ("10.0.0.3", 443))]):
        with pytest.raises(ValueError, match="public internet"):
            page_fetch._public_address("https://example.org/private")
    with pytest.raises(ValueError, match="public HTTPS"):
        page_fetch._public_address("http://example.org/")
    with pytest.raises(ValueError, match="public HTTPS"):
        page_fetch._public_address("https://user:pass@example.org/")


def test_mcp_fetch_page_returns_bounded_cpu_text():
    with patch.object(mcp, "fetch_page", return_value={"url": "https://example.org/a",
                                                    "title": "Source", "text": "Evidence",
                                                    "executor": "pi_cpu"}) as fetch:
        result = mcp.tool_call({"name": "fetch_page", "arguments": {
            "url": "https://example.org/a", "max_chars": 1000}}, "")
    assert not result["isError"]
    assert json.loads(result["content"][0]["text"])["text"] == "Evidence"
    fetch.assert_called_once_with("https://example.org/a", 1000)
    assert mcp.tool_call({"name": "fetch_page", "arguments": {
        "url": "https://example.org/a", "max_chars": True}}, "")["isError"]
