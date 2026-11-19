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


def test_prefers_public_ipv4_when_dns_has_both_families():
    answers = [
        (socket.AF_INET6, 1, 0, "", ("2600:1901:0:c831::", 443, 0, 0)),
        (socket.AF_INET, 1, 0, "", ("34.107.134.59", 443)),
    ]
    with patch.object(socket, "getaddrinfo", return_value=answers):
        _, address = page_fetch._public_address("https://pubmed.ncbi.nlm.nih.gov/39389132/")
    assert address == "34.107.134.59"


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


def test_page_reader_retains_bounded_same_site_links():
    page = page_fetch._Text("https://example.org/start")
    page.feed('<nav><a href="/about">About</a><a href="https://other.org/">Outside</a>'
              '<a href="/projects"><strong>Projects</strong></a></nav>')
    assert page.links == [
        {"url": "https://example.org/about", "label": "About"},
        {"url": "https://example.org/projects", "label": "Projects"},
    ]
