"""SearXNG JSON provider; independent of harness and orchestration."""

import json
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

MAX_RESULTS = 10
MAX_RESPONSE_BYTES = 2_000_000

def clean_text(value, limit):
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def url_key(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            return None
        host = parts.hostname.lower()
        port = parts.port
        if port and not ((parts.scheme.lower(), port) in (("http", 80), ("https", 443))):
            host += f":{port}"
        return urlunsplit((parts.scheme.lower(), host, parts.path or "/", parts.query, ""))
    except ValueError:
        return None


def endpoint_url(endpoint, query):
    parts = urlsplit(endpoint.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc or parts.username or parts.password:
        raise ValueError("SEARXNG_URL must be an http(s) instance URL without embedded credentials")
    path = parts.path.rstrip("/")
    if not path.endswith("/search"):
        path += "/search"
    return urlunsplit((parts.scheme, parts.netloc, path,
                       urlencode({"q": query, "format": "json", "pageno": 1}), ""))


def unresponsive_engines(value):
    """Keep bounded diagnostics without assuming every SearXNG engine uses one shape."""
    if not isinstance(value, list):
        return []
    issues = []
    for item in value[:8]:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            name, reason = item[:2]
        elif isinstance(item, dict):
            name, reason = item.get("name") or item.get("engine"), item.get("reason") or item.get("error")
        else:
            continue
        name, reason = clean_text(name, 60), clean_text(reason, 160)
        if name or reason:
            issues.append({"engine": name, "reason": reason})
    return issues


def search(query, max_results, endpoint, opener=urlopen, timeout=15):
    """Return compact results and operational status; never expose endpoint details."""
    if not endpoint:
        return {"results": [], "result_count": 0, "rate_limit_signal": False,
                "error": "SEARXNG_URL is not configured"}
    try:
        request = Request(endpoint_url(endpoint, query), headers={
            "Accept": "application/json", "User-Agent": "rig-search/0.1"})
    except ValueError as exc:
        return {"results": [], "result_count": 0, "rate_limit_signal": False, "error": str(exc)}
    started = time.monotonic()
    try:
        with opener(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("response too large")
            packet = json.loads(raw)
        if not isinstance(packet, dict) or not isinstance(packet.get("results"), list):
            raise ValueError("invalid SearXNG JSON response")
        seen = set()
        results = []
        for item in packet["results"]:
            if not isinstance(item, dict):
                continue
            key = url_key(item.get("url"))
            if not key or key in seen:
                continue
            seen.add(key)
            result = {"url": key, "title": clean_text(item.get("title"), 180),
                      "snippet": clean_text(item.get("content"), 320)}
            sources = item.get("engines")
            if isinstance(sources, list):
                sources = [clean_text(name, 40) for name in sources[:4] if isinstance(name, str)]
            else:
                sources = []
            if not sources and isinstance(item.get("engine"), str):
                sources = [clean_text(item["engine"], 40)]
            if sources:
                result["engines"] = sources
            if isinstance(item.get("publishedDate"), str):
                result["published_at"] = clean_text(item["publishedDate"], 40)
            results.append(result)
            if len(results) >= max_results:
                break
        issues = unresponsive_engines(packet.get("unresponsive_engines"))
        engine_notes = json.dumps(issues).lower()
        limited = any(term in engine_notes for term in ("429", "rate limit", "too many", "throttl"))
        urls = [item["url"] for item in results]
        suggestions = packet.get("suggestions")
        suggestions = [clean_text(item, 120) for item in suggestions[:3] if isinstance(item, str)] if isinstance(suggestions, list) else []
        corrections = packet.get("corrections")
        corrections = [clean_text(item, 120) for item in corrections[:2] if isinstance(item, str)] if isinstance(corrections, list) else []
        data = {"results": results, "result_count": len(results),
                "unique_urls": urls, "unique_url_count": len(urls),
                "rate_limit_signal": limited, "degraded": bool(issues),
                "unresponsive_engines": issues, "http_status": status,
                "backend_latency_seconds": round(time.monotonic() - started, 3)}
        if suggestions:
            data["suggestions"] = suggestions
        if corrections:
            data["corrections"] = corrections
        if not results and issues:
            data["error"] = "no results; upstream engines reported failures"
        return data
    except HTTPError as exc:
        result = {"results": [], "result_count": 0, "rate_limit_signal": exc.code == 429,
                  "degraded": True, "http_status": exc.code,
                  "backend_latency_seconds": round(time.monotonic() - started, 3),
                  "error": ("SearXNG HTTP 403: JSON format disabled or access denied" if exc.code == 403
                            else f"SearXNG HTTP {exc.code}")}
        if exc.code == 429:
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            if retry_after and retry_after.isdecimal():
                result["retry_after_seconds"] = min(int(retry_after), 3600)
        return result
    except (URLError, TimeoutError, OSError) as exc:
        kind = "timeout" if isinstance(exc, (TimeoutError, socket.timeout)) or isinstance(getattr(exc, "reason", None), (TimeoutError, socket.timeout)) else "network_error"
        return {"results": [], "result_count": 0, "rate_limit_signal": False,
                "degraded": True, "backend_latency_seconds": round(time.monotonic() - started, 3),
                "error": f"SearXNG {kind}"}
    except (ValueError, UnicodeError):
        return {"results": [], "result_count": 0, "rate_limit_signal": False,
                "degraded": True, "backend_latency_seconds": round(time.monotonic() - started, 3),
                "error": "invalid SearXNG JSON response"}
