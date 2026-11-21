# Harness tool inventory

Updated 2026-11-20. [Tool families](TOOL_FAMILIES.md) defines the current organization and promotion path. Ownership, origin, family, and availability are separate fields in `tools/tool_registry.json`. `tools/tool_fixtures.json` records the diagnostics test server, and `tools/dashboard_tool_catalog.json` is the generated projection. Gateway then applies separate Chat and Coding allowlists. The detailed notes below include historical test evidence; the registry controls current availability.

Change-scoped tests are named in `tests/suites.json` and run with `python tools/run_test_suite.py <suite>`. Use `--list` to inspect them. The `google_workspace` suite deliberately selects only the MCP schema, delegated-child loop/policy, and catalog contracts changed by that integration. Repository-wide `.venv/bin/python -m pytest -q` is also safe: `pytest.ini` excludes ignored receipts and archived candidate results and includes the current `rig_search` contracts.

| Ownership | Surfaces | Tool entries | Currently in dashboard chat |
| --- | ---: | ---: | ---: |
| Internal rig tools | 9 | 28 | 24 |
| External integrations | 6 | 40 | 7 public GitHub tools; 14 Google tools when OAuth is configured |
| Diagnostics fixture | 1 | 6 | 0 |

All 74 registry and fixture names are distinct. Prototype tools are available to tests. Dashboard export contains 45 enabled names across ten surfaces; Gateway narrows these by mode. Google tools require Gateway OAuth configuration; expanding the dedicated account from read-only to write access requires a fresh grant.

## Internal tools

| Surface | Status | Tools |
| --- | --- | --- |
| `rig_search` | Dashboard + prototypes | `search_web`, `fetch_page`; prototype `search_fixture_web`, `fetch_fixture_page` |
| `local_agents` | Dashboard + prototype | `list_local_agents`, `delegate_task`; prototype `delegate_fixture_task` |
| `rig_info` | Dashboard | `get_rig_status`, `get_model_status`, `get_benchmark_status`, `get_orchestration_status`, `get_orchestration_diagnostics`, `get_orchestration_activity` |
| `workspace_read` | Dashboard Coding and delegated coding children | `list_workspace_files`, `find_workspace_files`, `read_workspace_file`, `search_workspace_text` |
| `workspace_git` | Dashboard Coding | Status, log, working-tree diff, commit inspection, revision comparison, historical file read, file history |
| `google_workspace` | Dashboard Chat and delegated Chat children, auth gated | Gmail search/read/send; Drive search/read/create-folder/upload-text; Docs create/append; Sheets create/read/update/append |
| `github_public` | Dashboard Chat | Public repository inspect/list/find/read plus pinned commit inspection, comparison, and file history |
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

`workspace_read` serves only an explicitly selected Coding workspace and is exported for Coding turns. Chat does not receive it. `workspace_git` has the same selected-repository-root boundary. It builds on the installed Git CLI with optional locks, pagers, external diffs, text conversion, and inherited `GIT_*` overrides disabled. Revisions are limited to `HEAD` or returned hexadecimal commit IDs. Historical reads use Git blobs directly, require bounded UTF-8 text, and never check out a revision. The local adapter does not fetch, invoke hooks, change refs, stage files, or modify the working tree.

The separate `github_public` adapter builds on GitHub's public REST API. Repository inspection resolves the default branch to a full commit ID; every follow-up content/history operation requires a pinned 40-character SHA. Redirect hosts, repository paths, response sizes, and UTF-8 reads are bounded. It does not accept arbitrary Git URLs, credentials, private repositories, or mutation operations. A future GitLab adapter should retain this provider-specific boundary rather than broadening GitHub tools into a generic network clone command.

### Delegate

| Surface | Tool | Job |
| --- | --- | --- |
| `local_agents` | `list_local_agents` | Ask the gateway manager which child roles and candidates are available. |
| `local_agents` | `delegate_task` | Run one bounded coding or research child and return a receipt. |
| `local_agents` | `delegate_fixture_task` (prototype) | Give a child a fixed hidden arithmetic task and check its route, answer, and receipt. |

Cloud Codex and local model parents use the same `delegate_task` name and argument schema. The MCP launch supplies the parent route and permitted child candidates; the gateway admits the child and orchestration places its model. The prototype task tests that path with a fixed question; it is not offered in dashboard chat.

`delegate_task` accepts `tool_profile`, plus optional `acceptance_criteria` and `verification` strings that become labeled sections of the child assignment. The default `none` keeps the child isolated from tools. `public_research` gives it only `search_web` and `fetch_page`; `workspace_read` gives it only bounded repository reads; and `google_workspace` gives a Chat child the same generic Google schemas offered to any other model. Google children have no shell, filesystem, or delegation tools. The project-owned loop discovers each selected MCP server, publishes the reviewed schemas to Gateway, accepts normalized native tool calls, and retains strict JSON/XML compatibility parsing for routes that need it. Every call still passes the Harness allowlist and argument policy before MCP execution. Google writes require explicit confirmation and a unique request ID, and Gateway owns the durable external-operation receipt. All profiles share result budgets, a four-call batch cap, a six-turn cap, duplicate-call protection, a two-child concurrency cap, and cancellation/cleanup. Public queries leave the rig; do not use the public profile for private task text. The workspace MCP blocks hidden paths, symlinks, traversal, large files, and oversized results. The receipt records the project engine, limits, steps, tool calls, admission, and release.

The 2026-11-20 project-loop comparison used the same bounded two-document review task on shared Nemotron 74B and Qwen 35B children. Nemotron completed in six turns and 70.9 seconds after a forced tool-free synthesis; Qwen completed in three turns and 18.5 seconds. Both used reviewed workspace reads, retained stable route identity, and released their attached reservations. These are behavior observations, not a general quality ranking. The compatibility parser accepts exact allowlisted JSON envelopes, bounded JSON/XML batches, and the conventional `tool_name({...})` syntax emitted by some local models. The MCP server still validates every argument.

Targeted read results distinguish `requested_range_complete` from `more_lines_after`. A child should not page adjacent ranges merely because the source file continues after a requested range that was delivered successfully.

### Rig information

`rig_info` reads the gateway dashboard's read-only endpoints. `get_rig_status` returns a bounded GPU, profile, claim, and guard summary. `get_model_status` summarizes the imported model library. `get_benchmark_status` summarizes active lanes and recent campaigns. `get_orchestration_status`, `get_orchestration_diagnostics`, and `get_orchestration_activity` read the same current-state and job activity APIs as the orchestration dashboard tab. Activity pages follow one active or last-day batch journal by cursor. These tools do not run dashboard control actions.

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

The unified registry currently has **15 surfaces and 68 named entries**. The diagnostics fixture adds **1 surface and 6 tools**. The dashboard projection enables **45 tools across 10 surfaces**, subject to Gateway mode and credential gates. Earlier counts are superseded by the registry.

Harness exports the currently enabled projection with `python3 tools/export_dashboard_tool_catalog.py sync`. Gateway and benchmarking each use their own `sync_harness_tools.py --source ... what-new|sync|check` importer and keep a hash-pinned local snapshot. Gateway runtime reads its snapshot and the MCP server's live `tools/list` argument schema. Benchmarking uses the snapshot as a test input and records canonical model ID, served route, catalog hash, tool name, argument validity, result, and answer quality. Orchestration receives model load instructions and needs no tool catalog.

For a new production tool, implement and test its harness adapter, enter it as `disabled`, review its data and network boundary, then enable it and run both importer checks. A registry entry records a tool or integration candidate; only a dashboard-approved export makes it available to chat. Model-specific calling reliability requires a separate benchmarking receipt.
