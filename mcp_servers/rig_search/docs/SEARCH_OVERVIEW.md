# Search: evidence and lessons

Updated 2026-11-13. This is the entry point for search work in `rig-search`.
The tool discovers candidate URLs; the research arm decides which pages to
read and which claims to accept. Result count is not an answer-quality score.

## Where the evidence lives

| Evidence | What it measures | Important limit |
| --- | --- | --- |
| [Four-case provider comparison](PROVIDER_COMPARISON_2026-11-13.md) | Same GIS person, organization, publication, and event queries across SearXNG and four APIs | Four queries; only selected official pages were opened. |
| [Old-query replay](PROSPECT_REPLAY_2026-11-13.md) | Four preserved prospecting queries through SearXNG, compared with old accepted URL lists | Old URLs are from May; overlap alone is not relevance. |
| [Replacement readiness](REPLACEMENT_READINESS_2026-11-13.md) | MCP contract, direct provider selection, SearXNG parity, replacement gates | Native model candidate run was blocked by an unavailable pinned route. |
| `results/bryan_hellard_six_providers_2026-11-13.json` and `results/bryan_hellard_searxng_recheck_20261113.json` | One named query across all six, then a corrected SearXNG check with strict and broad variants | Snippet-level relevance only; pages were not fetched. Both files are Git-ignored on the Pi. |
| Prospector `TUNING_NOTES.md`, `reference/methodology_report.md`, and `history/_summary/ROLLUP_SUMMARY.md` in the orchestration arm | Earlier discovery, lead-quality, and pipeline failure patterns | The methodology report is a historical researcher account; its source-quality judgments are hypotheses until replayed. |
| Shoulder `research_upgrade.md` and `TIMEOUT_BASELINE.md` in the orchestration repo | Shared search/scrape boundary and phase budgets | Architectural notes, not current provider benchmarks. |

## What the provider tests suggest

| Provider | Positive evidence | Observed failure or uncertainty | Current use |
| --- | --- | --- | --- |
| SearXNG | Five results on the broad publication and event cases; two Bryan Hellard hits after shortening the query. One direct MCP parity check matched the old SearXNG tool's first official Python URL. | Zero on the four-case narrow person query and on `"Bryan Hellard" BCIT British Columbia`; only two results for `Bryan Hellard BCIT`. The old-query replay returned eight URLs total, all from Google CSE. | Cheap first pass for broad discovery; use explicit query variants when sparse. |
| Direct DuckDuckGo | Separate named helper has honest backend provenance and no API credits. | The Pi's `ddgs` calls returned no results on broad and narrow probes; the HTML endpoint returned HTTP 202 without result links. Older shoulder DDG hit HTTP 429 and fell through to Bing. | Keep selectable, but do not depend on it until a later live check succeeds. |
| Tavily | Five URLs in each four-case query; found the likely Bryan Hellard LinkedIn profile. | The five GIS person hits missed the requested role; four of five Bryan hits were unrelated people or a generic BCIT page. | Broad fallback; verify identity and role before accepting. |
| Exa | Found official UCGIS members, a journal review, and an official conference call in the four-case trial. On Bryan Hellard, surfaced a resume, BCIT/Georgia Straight coverage, LinkedIn, and a company release. | Its GIS person hits were three mirrors of one PDF. The Bryan relevance judgment is from URLs/titles, not fetched pages. | Early targeted option for organization, publication, event, or known-person discovery; deduplicate and fetch. |
| Firecrawl | Five results on publication/event cases; Bryan results included resume, press coverage, and BCIT club context. | Zero on the narrow GIS person query; event results included social/aggregator pages. Its page-scrape option was not tested in this comparison. | Search fallback and candidate for later search-plus-page-content testing. |
| SerpApi | Returned five event and organization URLs in the four-case trial, and a likely relevant LinkedIn hit for Bryan. | `site:` results were often unrelated during a reported Google issue. The Bryan call returned only two opaque `google.com/goto` links, one apparently a different person. | Last fallback until targeted tests and direct URL cleanup improve. |

The Bryan comparison used one call per paid provider with the same strict
query. The first script accidentally supplied an empty SearXNG endpoint and
recorded `unconfigured`. A separate, correctly configured receipt shows the
strict query produced zero results and a shorter variant produced two. Do
not count the script error as a SearXNG service failure. The apparent Bryan
matches above have not been identity-verified by reading their pages.

These samples favor Exa for several targeted searches, but there is no
universal winner. The current router still uses fixed fallback or rotation;
the table is guidance for experiments, not implemented intent routing.

## Lessons from the older research assistant runs

1. **Short queries beat pasted task paragraphs.** The February prospecting
   benchmark's strategy model returned invalid JSON, and its fallback placed
   a long natural-language request into search queries. The resulting pool
   contained listicles, reports, and directories rather than funded startups.
   The tuning notes recommend compact thesis, funding, and time terms.
2. **Broad discovery and named verification need different queries.** The
   older methodology report found broad sector searches useful for finding
   company names, while company-name plus funding/CEO/date searches were
   more productive for confirming a lead. Wide geographic searches tended
   to surface listicles. Treat this as a pattern to replay, not a guarantee.
3. **A full result list can still be a bad research result.** In the February
   benchmark, goal state said 2 accepted/32 rejected while the batch output
   said 0 accepted/34 rejected. The notes judged the primary list unusable.
   A final score needs verified people, companies, dates, and source evidence,
   not URL count or a model's unexamined acceptance total.
4. **Keep source provenance and distinguish primary evidence.** The older
   report preferred original funding announcements and strong reporting to
   generic listicles or vendor blogs. For every accepted claim, record the
   source URL, publication date, evidence sentence, and check time. Search
   snippets are pointers to pages, not the evidence itself.
5. **Search health and pipeline health are separate.** The historical
   prospector rollup included missing-path errors, invalid model JSON, and
   zero-candidate failures. The topic and event arm rollups were mostly
   partial runs. None of those counts alone proves an engine ranked badly.
   Preserve which phase failed and compare candidate/accepted yield only for
   runs that reached those phases.
6. **Do not hide fallback engines.** The old `web_common.ddg_search` tries
   `ddgs` auto mode, DDG HTML, then Bing RSS/HTML. A result from that path
   cannot be assumed to be DuckDuckGo. The new direct DDG adapter forces the
   DDG backend and reports failure to the router, which labels its own
   provider attempts.
7. **CPU workers belong after URL selection.** Search returns candidates;
   workers can fetch and clean selected pages. Fetch capacity does not fix
   weak search ranking or mistaken identity. The shared extraction path is
   `research_assistant/scripts/lib/web_common.py`; generalizing it remains
   future work.

## Working search flow

1. Turn the request into a few explicit, compact query variants. Keep exact
   names, aliases, site restrictions, geography, and recency as recorded
   inputs so a broadening step is visible.
2. Run a low-cost first pass and inspect provider attempts, health, and
   distinct URLs. Retry only a meaningful query variant or a provider suited
   to the missing evidence; a sparse response alone is not a reason to
   silently remove constraints.
3. Deduplicate URLs and likely mirror pages, filter obvious wrong identities
   and generic sources, then choose a small number of pages to fetch.
4. Fetch/clean those pages, keep source and fetch metadata, and have the model
   judge only evidence present in the fetched text. Keep unresolved leads
   separate from verified claims.
5. Report **useful verified pages per query, per paid credit, and per fetched
   page**, plus candidate and final acceptance yield. Record failures by
   search, fetch, extraction, and model stage.

The tool currently implements provider calls, normalization, provenance,
fallback, and local request caps. It does not yet implement query planning,
relevance scoring, CPU page dispatch, or page verification. `ingest.py` can
accept a cloud model's search hits as explicit candidates.

## Next comparisons to keep this document honest

- Replay the same person, organization, publication, event, and old
  prospecting queries across selected providers. Label each URL as useful,
  wrong entity, duplicate, or inaccessible **after** page fetching.
- Test strict and broadened queries as separate variants. Track whether a
  broad query rescues a useful page or mostly increases noise.
- Check whether SerpApi's `google.com/goto` URLs can be resolved to stable
  source URLs, and retest `site:` behavior before promoting it.
- Recheck direct DDG from the Pi after cooldown; retain the failure if it is
  still blocked. Do not enable DDG inside SearXNG just to mask this result.
- Run one bounded research-arm workflow using selected `rig-search` URLs,
  then compare fetched evidence and accepted output against the old route.

For each new experiment, append a dated note or a linked receipt with: query
and variant, provider and engine, requested/returned URLs, relevant and
verified URL counts, duplicate and wrong-identity counts, fetch success,
credits or requests used, latency, failure stage, and the decision it changed.
Never store API keys or authenticated request URLs in receipts.
