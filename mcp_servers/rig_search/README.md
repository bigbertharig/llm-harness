# rig-search

Experimental web discovery tool in the main Pi's `llm-harness/mcp_servers/rig_search`
directory. It normalizes search
hits from SearXNG, Tavily, Exa, Firecrawl, and SerpApi into one `search_web`
contract. Projects retain their own query strategy, ranking, page selection,
and acceptance rules. This package uses only the Python standard library.

Entry points:

- `mcp_server.py`: stdio MCP server for the harness and research shoulder.
- `search.py`: one JSON search response for scripts and jobs.
- `ingest.py`: normalize URLs supplied by a model's native web search.

Installed commands are `rig-search`, `rig-search-mcp`, and `rig-search-ingest`.

## Search routing

The default order is `searxng,tavily,exa,firecrawl,serpapi`. In the default
`fallback` mode, every query starts with the first provider in that list.
Set `RIG_SEARCH_ROUTING_MODE=rotate` to start successive queries at the next
provider; the position persists in local state. If a provider returns
fewer than `min_results` distinct URLs (default: 3, bounded by `max_results`),
the router tries the next provider and merges new URLs. It also falls through
on an error, HTTP 429, empty response, disabled budget, or provider cooldown.
It stops once the result target is met. The response records every attempt and
labels each hit with its provider. Result counts are discovery yield, not a
relevance or factual accuracy score.

Set `RIG_SEARCH_PROVIDERS` to a comma-separated subset in preferred order.
For example, `searxng,tavily,exa` uses only those three. When only
SearXNG is configured, no state database is needed and its previous behavior
is preserved.

The optional provider environment variables are:

| Provider | API key variable | Monthly request cap variable |
| --- | --- | --- |
| Tavily | `TAVILY_API_KEY` | `RIG_SEARCH_MONTHLY_CAP_TAVILY` |
| Exa | `EXA_API_KEY` | `RIG_SEARCH_MONTHLY_CAP_EXA` |
| Firecrawl | `FIRECRAWL_API_KEY` | `RIG_SEARCH_MONTHLY_CAP_FIRECRAWL` |
| SerpApi | `SERPAPI_API_KEY` | `RIG_SEARCH_MONTHLY_CAP_SERPAPI` |

Each optional provider needs both a key and a positive cap. Every cap
defaults to 0. Set conservative caps based on the account's current allowance
and usage elsewhere. The cap counts attempted requests by this tool, including
uncertain network failures; it is not an account-wide billing limit. Exa and
Firecrawl bill in credits rather than one universal request unit, so their
request caps cannot guarantee staying inside a credit allowance. Set account
spend limits where available and check current vendor terms before enabling.
SearXNG has no local monthly cap here, though its upstream engines can throttle.

`RIG_SEARCH_STATE` selects the SQLite state file. With optional providers
configured, it defaults to `~/.local/state/rig-search/state.sqlite3`. Put it on
the Pi's local disk and point every Pi search process at that same file. It
stores UTC monthly counters, the rotation position, and temporary cooldowns.
Do not use separate state files for clients sharing one API account. The
router does not access vendor account quota endpoints.

Example:

```sh
export SEARXNG_URL=http://127.0.0.1:8888
export RIG_SEARCH_PROVIDERS=searxng,tavily,exa
export RIG_SEARCH_ROUTING_MODE=fallback
export RIG_SEARCH_STATE=/path/to/rig-search-state.sqlite3
export TAVILY_API_KEY=...              # load from a local secret manager
export RIG_SEARCH_MONTHLY_CAP_TAVILY=100
export EXA_API_KEY=...
export RIG_SEARCH_MONTHLY_CAP_EXA=25
python3 search.py "research topic" --max-results 5 --min-results 3
python3 mcp_server.py
```

The CLI exits nonzero if every available provider fails and yields no URLs.
The MCP tool accepts a 3–300 character query, `max_results` 1–10, and optional
`min_results` 1–`max_results`. Each result has a normalized URL, title,
snippet, provider, and optional date. Top-level fields include distinct URLs,
counts, attempts, latency, degradation, rate limit, and upstream status where
available. The MCP server accepts an optional JSONL receipt path as its first
argument and `--endpoint URL` after that. Receipts contain query arguments,
URLs, and safe provider status; they contain no API keys or raw request URLs.
SerpApi requires its key in the HTTPS request URL, so avoid request tracing or
proxy logs that record the full URL.

The research shoulder can set `RESEARCH_SEARCH_BACKEND=searxng_mcp` and point
`RESEARCH_SEARXNG_MCP_SERVER` at this repo's `mcp_server.py`. That existing
adapter consumes the same result shape. Its local fixture test passes with the
router. The backend variable keeps its historical name for now.

## Model search and CPU page work

If a cloud model performs initial discovery with its own web search, export
its candidate hits as JSON and pass them through `ingest.py`:

```json
{"query":"research topic","source":"model_web_search","results":[{"url":"https://example.org/a","title":"A","snippet":"Candidate"}]}
```

```sh
python3 ingest.py candidates.json
```

This route is an explicit import, not an automatic API fallback. Imported hits
carry `verification_status: unfetched`. The model or an arm chooses URLs; a
separate page worker then fetches and extracts them before the model relies on
details absent from snippets. This keeps model-native discovery and the
reusable URL-fetch boundary separate.

Run SearXNG discovery near the Pi instance, which currently listens on Pi
loopback. CPU workers should receive selected URLs for fetch and extraction.
Seven workers were healthy at the last check, but current dispatch has no
worker affinity and Pi brain tasks run synchronously. This repo does not yet
dispatch page work. The research shoulder's `lib.web_common.fetch_page_text`
is an existing extraction path to generalize. A future shared page receipt
should carry source query/hit ID, URL, fetched time, status, content hash, and
text length. Per-domain pacing belongs at the coordinator.

## Status and tests

This is an isolated prototype. The harness still has its original SearXNG
server; its MCP registration has not moved here. The five providers were
compared live on four matched queries from the main Pi. This small trial
suggests an intent-aware order, but the router still uses fixed fallback or
rotation. Account usage elsewhere and future API changes require separate
checks.

Run `python -m unittest discover -s tests -v` for the deterministic contracts.
For a bounded SearXNG replay, see
[`docs/PROSPECT_REPLAY_2026-11-13.md`](docs/PROSPECT_REPLAY_2026-11-13.md).
That replay compares preserved old queries and is an observation, not a
relevance verdict.

The matched four-case, under-5%-of-free-tier provider trial is recorded in
[`docs/PROVIDER_COMPARISON_2026-11-13.md`](docs/PROVIDER_COMPARISON_2026-11-13.md).
