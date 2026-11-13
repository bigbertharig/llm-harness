"""Direct DuckDuckGo discovery through the optional ddgs client.

The named backend is required: ddgs's default is a multi-engine search.
Other search providers are routed by rig_search, not hidden inside this adapter.
"""

import time

from .searxng import clean_text, url_key


def _failure(kind, started, *, limited=False):
    return {"results": [], "result_count": 0, "unique_urls": [],
            "unique_url_count": 0, "rate_limit_signal": limited, "degraded": True,
            "backend_latency_seconds": round(time.monotonic() - started, 3),
            "error": f"duckduckgo {kind}"}


def search(query, max_results, *, client_factory=None, timeout=12):
    """Return normalized hits from DuckDuckGo only, with safe status fields."""
    started = time.monotonic()
    if client_factory is None:
        try:
            from ddgs import DDGS
        except ImportError:
            return _failure("client_unavailable", started)
        client_factory = DDGS
    try:
        with client_factory(timeout=timeout) as client:
            items = client.text(query, max_results=max_results, backend="duckduckgo")
        if not isinstance(items, list):
            return _failure("invalid_response", started)
        rows, seen = [], set()
        for item in items:
            if not isinstance(item, dict):
                continue
            url = url_key(item.get("href"))
            if not url or url in seen:
                continue
            seen.add(url)
            rows.append({"url": url, "title": clean_text(item.get("title"), 180),
                         "snippet": clean_text(item.get("body"), 320)})
            if len(rows) >= max_results:
                break
        urls = [row["url"] for row in rows]
        return {"results": rows, "result_count": len(rows), "unique_urls": urls,
                "unique_url_count": len(urls), "rate_limit_signal": False,
                "degraded": False, "search_backend": "duckduckgo",
                "backend_latency_seconds": round(time.monotonic() - started, 3)}
    except Exception as exc:
        # Keep exception text out of tool output: libraries may include query
        # strings or request URLs in it.
        name = type(exc).__name__.lower()
        message = str(exc).lower()
        if any(word in name or word in message for word in
               ("ratelimit", "rate limit", "429", "captcha", "throttl")):
            return _failure("rate_limited", started, limited=True)
        if "timeout" in name or "timeout" in message:
            return _failure("timeout", started)
        return _failure("search_failed", started)
