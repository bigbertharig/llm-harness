# Four-case provider comparison, 2026-11-13

## Live result

The main Pi ran the same four queries through SearXNG, Tavily, Exa,
Firecrawl, and SerpApi. Each request asked for at most five results. The
queries cover a GIS program contact, UCGIS member institutions, a recent
urban heat island review, and a 2027 geospatial conference call. The JSON
receipts are in `results/` on the Pi and are Git-ignored because they contain
queries and result URLs. No key or raw authenticated request URL is recorded.

| Provider | Person URLs | Organization URLs | Publication URLs | Event URLs | Observed usefulness |
| --- | ---: | ---: | ---: | ---: | --- |
| SearXNG | 0 | 1 | 5 | 5 | Useful review and event discovery; sparse on narrow site queries. |
| Tavily | 5 | 5 | 5 | 5 | Broad discovery, but the five person hits missed the requested program director. |
| Exa | 3 | 5 | 5 | 5 | Best apparent primary-source precision for the organization, publication, and event cases. Person hits were three mirrors of one PDF. |
| Firecrawl | 0 | 2 | 5 | 5 | Good broad coverage; event hits included social and aggregator pages. |
| SerpApi | 0 | 5 | 5 | 5 | Site-restricted organization and publication results were largely unrelated; event results mixed aggregators with one official page. |

These are discovery results, not verified answers. URL count alone is
misleading. Exa found the actual [UCGIS member list](https://www.ucgis.org/site/members),
a [2025 systematic review at its journal](https://gaee.agh.edu.pl/gaee/article/view/833),
and the [ISPRS GeoSpatial Week 2027 call](https://gsw2027.pl/calls.html).
The official pages were opened and the relevant content was present. The
person query was too narrow for a useful answer from any provider in this
small sample. Some Exa person results duplicated the same college PDF across
hosts; cross-provider URL and content deduplication still matters.

SerpApi returned unrelated results for `site:ucgis.org` even though the
request carried the intended query. Its [status page](https://status.serpapi.com/)
reported a contemporaneous Google `site:` operator problem, so this may be
temporary. A successful HTTP response with `organic_results_state=Fully empty`
and no organic hits is now handled as an empty result, following
[SerpApi's documented behavior](https://serpapi.com/api-status-and-error-codes).
The corresponding contract test passes.

## Budget and receipts

The trial, including SerpApi diagnosis and rechecks, stayed below 5% of each
published free allowance. The SQLite state reserves each attempted vendor
request before sending it. The comparison runner currently caps each
provider at eight requests per UTC month in that shared state; the normal
tool's `.env` request caps are separate.

| Provider | Published free allowance | Calls used | Share used |
| --- | ---: | ---: | ---: |
| Tavily basic search | 1,000 credits/month | 4 | 0.4% |
| Exa auto search | $10 credits/month, $0.007/search | 4, about $0.028 | 0.28% |
| Firecrawl search | 1,000 credits/month, 2 credits/search | 4, about 8 credits | 0.8% |
| SerpApi | 250 searches/month | 8 | 3.2% |
| SearXNG | Self-hosted | 4 | No account quota |

The preserved receipts are `provider_comparison_20261113.json`,
`serpapi_recheck_20261113.json`, and `serpapi_final_20261113.json` under
`results/`. The first full pass and final SerpApi pass are the basis of the
table above. Separate diagnostic requests account for the remaining SerpApi
usage. The local state cannot account for calls made by other applications
using the same account.

Sources: [Tavily pricing](https://www.tavily.com/pricing),
[Exa pricing](https://exa.ai/pricing),
[Firecrawl pricing](https://www.firecrawl.dev/pricing),
[SerpApi pricing](https://serpapi.com/pricing).

## Routing implication

Keep SearXNG as the cheap first pass for broad discovery. Try Exa early when
the query needs an official organization page, scholarly source, or event
call; the four cases favor it over simple round-robin routing. Tavily is a
reasonable broad fallback. Use Firecrawl only after the earlier choices or
where its page-content option is being tested separately. Put SerpApi behind
the others until a new targeted probe confirms its `site:` results are useful.
This is a hypothesis from four queries, not a general provider ranking.

The router currently uses a fixed fallback order or rotation. It does not
implement intent-aware routing, page verification, or CPU worker fetching.
The next small experiment should route the old research-assistant queries
through this tool, fetch selected URLs with the existing CPU extraction path,
and score useful verified pages per request and per fetched page. Preserve the
old query set and compare against its earlier receipts.

Run the deterministic contracts with
`python3 -m unittest discover -s tests -v`. The Pi run passed all 16 tests.
