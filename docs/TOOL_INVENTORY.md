# Harness tool inventory

Updated 2026-11-15. Ownership is the top-level split: **internal** means a tool implemented and maintained by the GPU Rig harness; **external** means a tool served by another provider, including DaedalMap. Availability is separate from ownership. `tools/tool_registry.json` is the integration inventory, `tools/tool_fixtures.json` records the diagnostics test server, and `tools/dashboard_tool_catalog.json` is the generated projection currently offered in gateway chat. Prototype tools under Search and Delegate are recorded with their parent surface and are omitted from the dashboard projection.

| Ownership | Surfaces | Tool entries | Currently in dashboard chat |
| --- | ---: | ---: | ---: |
| Internal, including diagnostics fixtures | 5 | 21 | 11 |
| External | 4 | 19 | 0 |

All 21 internal tool names are distinct. Prototype tools are available to tests, while the seven rig information tools and four operational tools are offered in dashboard chat.

## Internal tools

| Surface | Status | Tools |
| --- | --- | --- |
| `rig_search` | Dashboard + prototypes | `search_web`, `fetch_page`; prototype `search_fixture_web`, `fetch_fixture_page` |
| `local_agents` | Dashboard + prototype | `list_local_agents`, `delegate_task`; prototype `delegate_fixture_task` |
| `rig_info` | Dashboard | `get_rig_status`, `check_rig_heartbeats`, `get_model_status`, `get_benchmark_status`, `get_orchestration_status`, `get_orchestration_diagnostics`, `get_orchestration_activity` |
| `local_rag_fixture` | Prototype | `search_passages` |
| `diagnostics` | Test fixture | `read_marker`, `read_structured_marker`, `calculate_sum`, `calculate_product`, `get_entry`, `get_nested_entry` |

### Search

| Surface | Tool | Job |
| --- | --- | --- |
| `rig_search` | `search_web` | Search public sources with one six-provider router: SearXNG, direct DuckDuckGo, Tavily, Exa, Firecrawl, and SerpApi. |
| `rig_search` | `fetch_page` | Read one selected public HTTPS page on the Pi CPU with bounded output. |
| `rig_search` | `search_fixture_web`, `fetch_fixture_page` (prototype) | Fixed local search result and page read for measuring whether an agent searches, fetches, and cites an answer. |

The first two are the live public search tools. The prototype tools run against an isolated local test page, so their results stay fixed between benchmark runs. The old standalone SearXNG and DuckDuckGo MCP adapters were removed. Search-provider comparison scripts remain for measuring backend quality.

### Local information

`search_passages` is a Chroma RAG fixture over an isolated eight-passage corpus. It tests passage filters and citation IDs. It is distinct from public web search and is not enabled in dashboard chat. The 2026-11-05 comparison passed 23/24 adjudicated cases; that small fixture does not establish a production local index. Its prototype record lives in the unified registry so it can follow the same review path when a real local index is ready.

### Delegate

| Surface | Tool | Job |
| --- | --- | --- |
| `local_agents` | `list_local_agents` | Ask the gateway manager which child roles and candidates are available. |
| `local_agents` | `delegate_task` | Run one bounded coding or research child and return a receipt. |
| `local_agents` | `delegate_fixture_task` (prototype) | Give a child a fixed hidden arithmetic task and check its route, answer, and receipt. |

Cloud Codex and local model parents use the same `delegate_task` name and argument schema. The MCP launch supplies the parent route and permitted child candidates; the gateway admits the child and orchestration places its model. The prototype task tests that path with a fixed question; it is not offered in dashboard chat.

### Rig information

`rig_info` reads the gateway dashboard's read-only endpoints. `get_rig_status` returns a bounded GPU, profile, claim, and guard summary. `check_rig_heartbeats` reports controller heartbeat age and staleness plus rig reachability. `get_model_status` summarizes the imported model library. `get_benchmark_status` summarizes active lanes and recent campaigns. `get_orchestration_status`, `get_orchestration_diagnostics`, and `get_orchestration_activity` read the same current-state and job activity APIs as the orchestration dashboard tab. Activity pages follow one active or last-day batch journal by cursor. These tools do not run dashboard control actions.

Live campaign testing on 2026-11-15 identified one candidate for this surface:
`check_campaign_readiness`. It should combine the rig safety guard, selected-card
availability, direct rig-to-Pi control reachability, model file/profile readiness,
and suite image checks in one read-only answer before a load. Benchmarking should
own the check and its receipt first; only then should the harness offer it as a
tool. The current campaign `--dry-run` verifies manifest structure and commands
but does not establish live readiness.

### Diagnostics and frozen test doubles

| Fixture | Tools | What it checks |
| --- | --- | --- |
| Marker | `read_marker`, `read_structured_marker` | Whether an MCP client calls the named tool and handles plain text and structured results. It returns fresh markers, not real information. |
| Numeric | `calculate_sum`, `calculate_product` | Whether a model supplies required numeric arguments and uses returned arithmetic results. |
| Lookup | `get_entry`, `get_nested_entry` | Whether a model supplies required lookup keys and can read nested structured-only results. |

These six tools share one `diagnostics` MCP surface and implementation, `tools/fixtures/diagnostics_mcp.mjs`. Benchmark profiles `marker`, `numeric`, and `lookup` limit the visible tools to preserve the comparison cases; the default `all` profile exposes all six. Diagnostics is a test category, but it can follow the same catalog promotion process if a user-facing diagnostic becomes useful.

The MCP call guard is middleware for bounded repeat and error counts; it has no model-facing tool name.

### Benchmark migration note

Older web-research receipts used fixture tools named `search_web` and `fetch_page`; new runs use `search_fixture_web` and `fetch_fixture_page`. Older delegation receipts used a fixture tool named `delegate_task`; new runs use `delegate_fixture_task`. The test servers still supply fixed cases, but the named-tool contract changed, so compare results across that boundary with this difference in mind. Historical receipts are left as records, not copied into active tool surfaces.

## External tools

The unified registry keeps separately owned services under the `external` category. DeepWiki `read_wiki_structure`, OpenAI Docs `search_openai_docs`, and Cloudflare Docs `search_cloudflare_documentation` are past observations, not promises of current availability.

### DaedalMap

The current hosted server is `https://app.daedalmap.com/mcp?registry=site`, with metadata at `https://app.daedalmap.com/mcp/server.json`. A live `initialize` and `tools/list` on 2026-11-14 reported server version `0.4.0` and these 16 tools: `get_tool_help`, `get_catalog`, `get_pack`, `get_geography`, `get_event`, `resolve_point`, `resolve_bbox`, `resolve_deep_bbox`, `resolve_deep_point`, `get_loc_id_info`, `identify_dataset_geography`, `identify_reference_system`, `convert_reference`, `compare_geographies`, `get_shape`, `get_data`. The Research, Geometry, and unified name snapshots represented older overlapping endpoints and have been retired from the current inventory. Discover schemas again when connecting. This external service is not yet enabled in dashboard chat; its hosted access and payment behavior need an adapter and review before enabling. Historical comparison receipts remain under `results/` and `docs/research/`.

## Counts and handoff

The unified registry has **8 surfaces and 34 named entries**: three dashboard surfaces with eleven offered tools, three search/delegation prototype tools under their owning surfaces, one local-information prototype, DaedalMap with 16 live-discovered tools, and three other external observations. The diagnostics fixture adds **1 surface and 6 tools**. Thus the current inventory describes **9 surfaces and 40 distinct tool names**. The original 17/59 count included retired duplicate harness surfaces and dated DaedalMap names.

Harness exports the currently enabled projection with `python3 tools/export_dashboard_tool_catalog.py sync`. Gateway and benchmarking each use their own `sync_harness_tools.py --source ... what-new|sync|check` importer and keep a hash-pinned local snapshot. Gateway runtime reads its snapshot and the MCP server's live `tools/list` argument schema. Benchmarking uses the snapshot as a test input and records canonical model ID, served route, catalog hash, tool name, argument validity, result, and answer quality. Orchestration receives model load instructions and needs no tool catalog.

For a new production tool, implement and test its harness adapter, enter it as `disabled`, review its data and network boundary, then enable it and run both importer checks. A registry entry records a tool or integration candidate; only a dashboard-approved export makes it available to chat. Model-specific calling reliability requires a separate benchmarking receipt.
