# Harness search replacement readiness, 2026-11-13

> Historical comparison record. The standalone SearXNG and DuckDuckGo MCP adapters were retired; `rig_search` is the operational search MCP.


For the combined evidence and lessons from the research assistant, see
[Search: evidence and lessons](SEARCH_OVERVIEW.md).

## What each provider is useful for

The four matched live queries are documented in
[PROVIDER_COMPARISON_2026-11-13.md](PROVIDER_COMPARISON_2026-11-13.md).
They are too small for a universal ranking, but they give a working order:

| Provider | Best current role | Observed limit |
| --- | --- | --- |
| SearXNG | Free first pass for broad queries and an available local MCP baseline | The narrow person query returned zero; Google CSE has previously reported upstream throttling. |
| DuckDuckGo | Separate free direct fallback when SearXNG is sparse | The Pi's SearXNG DuckDuckGo engine was disabled after CAPTCHA failures; the direct adapter still needs quality and rate-limit validation. |
| Exa | Official organization pages, scholarly reviews, and event calls | Its person hits were mirrors of one PDF; semantic matches need deduplication and verification. |
| Tavily | Broad fallback when a first pass is sparse | All five person hits missed the requested role in this trial. |
| Firecrawl | Broad discovery and a future search-to-content experiment | Its event hits included social and aggregator pages; this trial did not test its scrape option. |
| SerpApi | Last fallback or a fresh targeted probe | Its site-restricted results were unrelated during a documented Google `site:` issue. |

The router's fixed order is now SearXNG, direct DuckDuckGo, Tavily, Exa,
Firecrawl, SerpApi.
Intent-aware routing is an experiment to build after the next research-arm
replay, not an implemented feature. Page fetching and CPU distribution remain
outside this search tool.

## Direct calls

`search_web` now accepts optional `provider`: `auto`, `searxng`,
`duckduckgo`, `tavily`, `exa`, `firecrawl`, or `serpapi`. For example,
`{"query":"urban heat island systematic review","provider":"exa","max_results":5}`
calls Exa only, subject to its configured cap. `provider:"auto"` uses the
configured fallback or rotation. A named provider does not fall back on
empty results, error, cooldown, or exhausted budget. The response includes
`requested_provider`, per-hit `provider`, and `attempts` for inspection.

For local scripts, use `python3 search.py "query" --provider exa` after
loading the private env. MCP children can use
`python3 mcp_server.py --env-file /home/bryan/llm-harness/.env`; this is
important for harnesses that isolate child process environments.

## Existing harness paths and replacement boundary

The current comparison runner defaults to
`tools/local_mcp_web_search.py` (DuckDuckGo). Its optional SearXNG lane
launches `mcp_servers/searxng/server.py`. The latter has one `search_web`
tool with `query` and `max_results`, and emits ranked URLs, snippets,
engine provenance, HTTP status, latency, and health signals. The new package
keeps that tool name and those fields for SearXNG results, and adds
`min_results`, explicit provider choice, multi-source fallback, persistent
request budgets, cooldowns, and source attribution. Its model-visible result
shape remains compatible with the research shoulder's MCP adapter.

The comparison runner now accepts `--backend rig_search`. That lane launches
the new MCP entry point with the private harness env file and defaults to
`--providers searxng`, so the first native harness gate compares the same
underlying engine without paid provider calls. The existing DDG and SearXNG
lanes remain available as controls. Example:

```sh
cd /home/bryan/llm-harness
python3 research/external_harnesses/comparison_web_search.py pi --run-id rig-search-smoke --backend rig_search --case python_taskgroup
```

The runner still applies its direct MCP relevance gate before launching a
candidate. After SearXNG-only parity, try a bounded Exa or mixed-source lane
with `RIG_SEARCH_COMPARE_PROVIDERS` and explicit account budget review. The
private `.env` caps are now Tavily 8, Exa 8, Firecrawl 8, and SerpApi 12
requests per UTC month. The earlier trial used four requests each for Tavily,
Exa, and Firecrawl, and eight for SerpApi. One later explicit MCP call to each
paid provider succeeded. The Bryan Hellard comparison used one more call to
each. Current recorded use is therefore 6, 6, 6, and 10 requests
respectively, still below 5% of every published free allowance.
These local counters do not include calls from other clients.
Each named-provider call returned exactly one matching provider attempt and
three URLs. Tavily, Exa, and Firecrawl put the Python documentation first.
SerpApi returned three URLs, but its first was a GitHub issue despite the
`site:docs.python.org` query. This verifies the selector and reinforces the
need for source checks.

## Direct DuckDuckGo option

The separate `duckduckgo` provider uses the optional `ddgs` package with
`backend="duckduckgo"` fixed. The package's default `auto` mode is
metasearch, so using it would mislabel results from other engines. The old
`tools/local_mcp_web_search.py` launches the research shoulder's helper,
which may fall back to Bing without changing its top-level DDG label. The new
adapter instead reports a DDG limit or error and lets this router choose a
different named provider. It shares the SQLite cooldown state and requires no
API key or paid request cap. The Pi's SearXNG DDG engine is still disabled;
this direct helper does not change SearXNG settings.

The first live named DDG call on the Pi returned no results (`ddgs` raised
`DDGSException: No results found`); a second broad query did the same. A
direct check of DDG's HTML endpoint returned HTTP 202 with no result links.
The adapter surfaced the failure and its router cooldown, rather than
presenting another engine's results as DDG. This option is implemented and
selectable, but live DDG availability on this Pi is currently unverified.
Keep SearXNG or another provider in the fallback list and rerun a bounded
quality replay when DDG is accessible.

## Acceptance before switching the default

1. The deterministic package and comparison-runner contracts pass. On the Pi,
   20 package tests and 3 existing-runner integration tests passed.
2. Compare the new SearXNG-only lane against the old MCP and pass one native
   candidate case. The direct comparison passed on one live Python
   documentation query: both servers returned five URLs, the same first
   official URL, HTTP 200, and no degradation or rate signal. The native
   candidate run could not start because the Pi harness's pinned model route
   was unavailable; no model result or candidate pass is claimed.
3. A research-assistant replay verifies selected pages, not just URL counts,
   and checks that its existing output contract survives.
4. A bounded mixed-source case demonstrates fallback when SearXNG is sparse
   or limited, with receipts showing which provider was used and how much
   budget was reserved.

The default comparison backend and existing MCP registrations have not yet
been switched. This preserves a measured control while the replacement is
qualified.
