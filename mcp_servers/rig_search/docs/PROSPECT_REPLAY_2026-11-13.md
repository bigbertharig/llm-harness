# Prospecting search replay, 2026-11-13

Four exact queries came from the research prospecting run
`research_prospector/history/20260502_205120/results/raw_search_results.json`.
The [fixture](../tests/fixtures/prospect_20260502_queries.json) stores those
queries and the old shoulder's accepted URL lists. The
[live receipt](../results/prospect_replay_20261113.json) records the new tool's
full response for each query. `tools/replay_queries.py` ran on the Pi against
its loopback SearXNG instance with a five-result cap and 15 seconds between
queries; it stops on a provider error or rate-limit signal.

| Query focus | Old accepted URLs | rig-search URLs | Exact URL overlap |
| --- | ---: | ---: | ---: |
| GIS program director and industry partnerships | 5 | 0 | 0 |
| Geospatial science and capstone coordinator | 5 | 2 | 0 |
| UCGIS member institutions and contact | 3 | 1 | 0 |
| AAG geography programs and director | 5 | 5 | 1 |

All four SearXNG responses were HTTP 200, with no reported unresponsive engine
or rate-limit signal. Provider latency was 0.5–1.5 seconds. All eight returned
URLs came from Google CSE. The Pi currently has Google CSE and Wikipedia as
its enabled general web engines. Zero or thin results here are a yield and
relevance problem, not an observed service outage. The old URL lists are from
May, so overlap alone cannot establish current relevance or a causal quality
change.

Two follow-up probes on the first zero-result query clarify the tradeoff:

- Removing quoted phrases returned five URLs, but several were broad GIS
  program pages rather than likely program-director or partnership contacts.
- Keeping the strict query and selecting Bing with `!bi` returned five URLs,
  mostly unrelated Manitoba GIS pages and a Canadian pension page. That
  engine route did not respect the intended site and role constraints well
  enough to be an automatic fallback.

A same-day call through the live research shoulder's old `ddg_search` for the
same strict query hit HTTP 429 on its primary `ddgs` route, then its HTML path
returned zero and Bing RSS returned five mostly off-topic URLs. Thus neither
current provider demonstrated the quality of the older accepted results on
this case. The shoulder command output was inspected during the run; it was
read-only and did not alter a research batch.

## Decision

Keep the new tool's exact query behavior and health metadata. Do not silently
broaden queries or switch engines based only on low count; both probes added
noise. The next quality iteration should keep query variants explicit, record
which variant and engine produced each hit, and apply the research arm's
selection rules before counting a URL as useful. Compare on current queries
with page verification and relevance labels, then rerun a small arm workflow.
CPU workers can process selected pages after search; they cannot repair weak
upstream search ranking.
