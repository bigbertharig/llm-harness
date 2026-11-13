"""Cycle configured search providers with persistent budgets and cooldowns."""

import os
from pathlib import Path
import sqlite3
import time
from contextlib import contextmanager

from . import providers, searxng


PROVIDER_NAMES = ("searxng", "tavily", "exa", "firecrawl", "serpapi")
KEY_ENV = {"tavily": "TAVILY_API_KEY", "exa": "EXA_API_KEY",
           "firecrawl": "FIRECRAWL_API_KEY", "serpapi": "SERPAPI_API_KEY"}


class BudgetState:
    """One local SQLite file shared by all search processes on the Pi."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS usage (month TEXT, provider TEXT, used INTEGER NOT NULL, PRIMARY KEY(month, provider))")
            db.execute("CREATE TABLE IF NOT EXISTS cooldown (provider TEXT PRIMARY KEY, until_unix REAL NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS rotation (slot INTEGER PRIMARY KEY CHECK(slot=1), next_index INTEGER NOT NULL)")
            db.execute("INSERT OR IGNORE INTO rotation VALUES (1, 0)")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA busy_timeout=10000")
        try:
            with db:
                yield db
        finally:
            db.close()

    def next_start(self, count):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            value = db.execute("SELECT next_index FROM rotation WHERE slot=1").fetchone()[0]
            db.execute("UPDATE rotation SET next_index=? WHERE slot=1", (value + 1,))
        return value % count

    def reserve(self, provider, cap, now=None):
        """Reserve before a call; uncertain network failures may still be billed."""
        now = time.time() if now is None else now
        month = time.strftime("%Y-%m", time.gmtime(now))
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT until_unix FROM cooldown WHERE provider=?", (provider,)).fetchone()
            if row and row[0] > now:
                return "cooldown"
            if provider == "searxng":
                return "ready"
            if cap <= 0:
                return "budget_disabled"
            row = db.execute("SELECT used FROM usage WHERE month=? AND provider=?",
                             (month, provider)).fetchone()
            if row and row[0] >= cap:
                return "budget_exhausted"
            db.execute("INSERT INTO usage(month,provider,used) VALUES (?,?,1) "
                       "ON CONFLICT(month,provider) DO UPDATE SET used=used+1", (month, provider))
        return "ready"

    def cool(self, provider, seconds, now=None):
        now = time.time() if now is None else now
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO cooldown(provider,until_unix) VALUES (?,?) "
                       "ON CONFLICT(provider) DO UPDATE SET until_unix=max(until_unix,excluded.until_unix)",
                       (provider, now + seconds))


def _configured(env):
    value = env.get("RIG_SEARCH_PROVIDERS", ",".join(PROVIDER_NAMES))
    names = [part.strip().lower() for part in value.split(",") if part.strip()]
    if not names or len(names) != len(set(names)) or any(name not in PROVIDER_NAMES for name in names):
        raise ValueError("RIG_SEARCH_PROVIDERS must contain distinct supported providers")
    return names


def _cap(env, provider):
    value = env.get(f"RIG_SEARCH_MONTHLY_CAP_{provider.upper()}", "0")
    try:
        cap = int(value)
    except ValueError as exc:
        raise ValueError(f"invalid monthly cap for {provider}") from exc
    if not 0 <= cap <= 1_000_000:
        raise ValueError(f"invalid monthly cap for {provider}")
    return cap


def search(query, max_results, endpoint=None, *, env=None, state=None, min_results=None,
           searchers=None, provider=None):
    """Return normalized URLs, trying another provider only for insufficient yield.

    Keys enable a provider; a positive local monthly cap authorizes its use.
    A cap is a safeguard for this tool, not an account-wide billing guarantee.
    """
    env = os.environ if env is None else env
    names = _configured(env)
    if provider is not None:
        if provider not in names:
            raise ValueError("provider is not enabled in RIG_SEARCH_PROVIDERS")
        names = [provider]
    mode = env.get("RIG_SEARCH_ROUTING_MODE", "fallback").strip().lower()
    if mode not in ("fallback", "rotate"):
        raise ValueError("RIG_SEARCH_ROUTING_MODE must be fallback or rotate")
    if min_results is None:
        min_results = min(3, max_results)
    if not 1 <= min_results <= max_results <= searxng.MAX_RESULTS:
        raise ValueError("invalid result target")
    endpoint = env.get("SEARXNG_URL", "") if endpoint is None else endpoint
    configured_paid = any(env.get(KEY_ENV[name]) and _cap(env, name) > 0
                          for name in names if name != "searxng")
    if state is None and (configured_paid or env.get("RIG_SEARCH_STATE")):
        state = BudgetState(env.get("RIG_SEARCH_STATE") or
                            Path.home() / ".local/state/rig-search/state.sqlite3")
    start = state.next_start(len(names)) if state and mode == "rotate" and provider is None else 0
    ordered = names[start:] + names[:start]
    searchers = searchers or {}
    rows, seen, attempts = [], set(), []
    any_error = False
    last_data = None
    for name in ordered:
        key = env.get(KEY_ENV[name], "") if name != "searxng" else ""
        if name == "searxng" and not endpoint:
            attempts.append({"provider": name, "status": "unconfigured"})
            continue
        if name != "searxng" and (not key or _cap(env, name) == 0):
            attempts.append({"provider": name, "status": "unconfigured"})
            continue
        if state:
            ready = state.reserve(name, _cap(env, name) if name != "searxng" else 0)
            if ready != "ready":
                attempts.append({"provider": name, "status": ready})
                continue
        searcher = searchers.get(name)
        if searcher is None:
            data = (searxng.search(query, max_results, endpoint) if name == "searxng" else
                    providers.search(name, query, max_results, key))
        else:
            data = searcher(query, max_results)
        last_data = data
        count = data.get("result_count", 0)
        status = ("rate_limited" if data.get("rate_limit_signal") else
                  "error" if data.get("error") else "ok" if count else "empty")
        attempt = {"provider": name, "status": status, "result_count": count,
                   "degraded": bool(data.get("degraded", False)),
                   "backend_latency_seconds": data.get("backend_latency_seconds")}
        if data.get("http_status") is not None:
            attempt["http_status"] = data["http_status"]
        if data.get("error"):
            attempt["error"] = data["error"]
            any_error = True
        attempts.append(attempt)
        if state:
            if data.get("rate_limit_signal"):
                state.cool(name, max(60, data.get("retry_after_seconds", 3600)))
            elif data.get("error"):
                state.cool(name, 300 if (data.get("http_status") or 500) >= 500 else 3600)
        for row in data.get("results", []):
            url = searxng.url_key(row.get("url")) if isinstance(row, dict) else None
            if not url or url in seen:
                continue
            seen.add(url)
            rows.append({**row, "url": url, "provider": name})
            if len(rows) >= max_results:
                break
        if len(rows) >= min_results:
            break
    rows = rows[:max_results]
    urls = [row["url"] for row in rows]
    called = [a for a in attempts if a.get("backend_latency_seconds") is not None]
    last_limited = max((i for i, a in enumerate(attempts) if a["status"] == "rate_limited"),
                       default=-1)
    last_ok = max((i for i, a in enumerate(attempts) if a["status"] == "ok"), default=-1)
    result = {"results": rows, "result_count": len(rows), "unique_urls": urls,
              "unique_url_count": len(urls), "attempts": attempts,
              "requested_provider": provider or "auto",
              "rate_limit_signal": last_limited > last_ok,
              "degraded": any(a.get("degraded") or a["status"] in ("error", "rate_limited")
                              for a in attempts),
              "backend_latency_seconds": round(sum(a["backend_latency_seconds"] for a in called), 3)}
    if len(called) == 1 and last_data is not None:
        for field in ("http_status", "unresponsive_engines", "suggestions", "corrections",
                      "retry_after_seconds"):
            if field in last_data:
                result[field] = last_data[field]
    result["provider"] = rows[0]["provider"] if rows and all(
        row["provider"] == rows[0]["provider"] for row in rows) else "mixed" if rows else None
    if not rows and (any_error or not called):
        result["error"] = "no search provider returned usable results"
    return result
