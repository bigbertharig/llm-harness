"""Optional search API adapters. Only normalized search results leave this module."""

import json
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .searxng import MAX_RESPONSE_BYTES, clean_text, url_key


API_URLS = {
    "tavily": "https://api.tavily.com/search",
    "exa": "https://api.exa.ai/search",
    "firecrawl": "https://api.firecrawl.dev/v2/search",
    "serpapi": "https://serpapi.com/search.json",
}


def _request(provider, query, max_results, key):
    """Build a bounded, discovery-only request; never request page contents."""
    if provider == "tavily":
        body = {"query": query, "search_depth": "basic", "max_results": max_results,
                "include_answer": False, "include_raw_content": False}
        return Request(API_URLS[provider], data=json.dumps(body).encode(), headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json",
            "Accept": "application/json", "User-Agent": "rig-search/0.2"})
    if provider == "exa":
        body = {"query": query, "type": "auto", "numResults": max_results}
        return Request(API_URLS[provider], data=json.dumps(body).encode(), headers={
            "x-api-key": key, "Content-Type": "application/json",
            "Accept": "application/json", "User-Agent": "rig-search/0.2"})
    if provider == "firecrawl":
        body = {"query": query, "limit": max_results, "sources": [{"type": "web"}],
                "highlights": False}
        return Request(API_URLS[provider], data=json.dumps(body).encode(), headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json",
            "Accept": "application/json", "User-Agent": "rig-search/0.2"})
    if provider == "serpapi":
        # SerpApi's public search endpoint requires the key as a query parameter.
        url = API_URLS[provider] + "?" + urlencode({
            "engine": "google", "q": query, "num": max_results, "api_key": key})
        return Request(url, headers={"Accept": "application/json",
                                     "User-Agent": "rig-search/0.2"})
    raise ValueError("unknown search provider")


def _items(provider, packet):
    if not isinstance(packet, dict):
        raise ValueError("invalid provider response")
    if provider == "firecrawl":
        data = packet.get("data")
        if packet.get("success") is not True or not isinstance(data, dict):
            raise ValueError("invalid provider response")
        items = data.get("web")
    elif provider == "serpapi":
        metadata = packet.get("search_metadata")
        information = packet.get("search_information")
        if (isinstance(metadata, dict) and metadata.get("status") == "Success" and
                isinstance(information, dict) and
                str(information.get("organic_results_state", "")).strip().lower() == "fully empty"):
            return []
        if packet.get("error") or (isinstance(metadata, dict) and metadata.get("status") == "Error"):
            raise ValueError("provider reported an error")
        items = packet.get("organic_results")
        if items is None and isinstance(metadata, dict) and metadata.get("status") == "Success":
            items = []
    else:
        items = packet.get("results")
    if not isinstance(items, list):
        raise ValueError("invalid provider response")
    return items


def _normalize(provider, items, max_results):
    seen = set()
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = url_key(item.get("link") if provider == "serpapi" else item.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        snippet = item.get("snippet") if provider == "serpapi" else (
            item.get("content") if provider == "tavily" else (
                item.get("description") if provider == "firecrawl" else
                item.get("text") or item.get("summary") or ""))
        row = {"url": url, "title": clean_text(item.get("title"), 180),
               "snippet": clean_text(snippet, 320)}
        published = (item.get("published_date") if provider == "tavily" else
                     item.get("publishedDate") if provider == "exa" else item.get("date"))
        if isinstance(published, str):
            row["published_at"] = clean_text(published, 40)
        rows.append(row)
        if len(rows) >= max_results:
            break
    return rows


def search(provider, query, max_results, key, opener=None, timeout=15):
    """Search one optional provider; return the rig-search result contract."""
    if provider not in API_URLS:
        raise ValueError("unknown search provider")
    if not key:
        return {"results": [], "result_count": 0, "rate_limit_signal": False,
                "error": "provider key is not configured"}
    request = _request(provider, query, max_results, key)
    started = time.monotonic()
    opener = opener or urlopen
    try:
        with opener(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("response too large")
            packet = json.loads(raw)
        rows = _normalize(provider, _items(provider, packet), max_results)
        urls = [row["url"] for row in rows]
        return {"results": rows, "result_count": len(rows),
                "unique_urls": urls, "unique_url_count": len(urls),
                "rate_limit_signal": False, "degraded": False,
                "http_status": status,
                "backend_latency_seconds": round(time.monotonic() - started, 3)}
    except HTTPError as exc:
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        result = {"results": [], "result_count": 0, "rate_limit_signal": exc.code == 429,
                  "degraded": True, "http_status": exc.code,
                  "backend_latency_seconds": round(time.monotonic() - started, 3),
                  "error": f"provider HTTP {exc.code}"}
        if retry_after and retry_after.isdecimal():
            result["retry_after_seconds"] = min(int(retry_after), 3600)
        return result
    except (URLError, TimeoutError, OSError) as exc:
        kind = "timeout" if isinstance(exc, (TimeoutError, socket.timeout)) or isinstance(
            getattr(exc, "reason", None), (TimeoutError, socket.timeout)) else "network_error"
        return {"results": [], "result_count": 0, "rate_limit_signal": False,
                "degraded": True, "backend_latency_seconds": round(time.monotonic() - started, 3),
                "error": f"provider {kind}"}
    except (ValueError, UnicodeError):
        return {"results": [], "result_count": 0, "rate_limit_signal": False,
                "degraded": True, "backend_latency_seconds": round(time.monotonic() - started, 3),
                "error": "invalid provider JSON response"}
