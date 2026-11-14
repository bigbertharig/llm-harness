# Harness tool inventory and promotion queue

Updated 2026-11-14. This inventory distinguishes the dashboard's enabled tools from tools that appeared in comparison trials. A provider behind a tool is not another model-facing tool. `tools/tool_registry.json` is the authoritative harness inventory; `tools/dashboard_tool_catalog.json` is its generated gateway projection. This document records the evidence and promotion choices.

## Enabled in dashboard chat: 4 tools, 2 MCP servers

| Server | Tool | What it does | Executor |
| --- | --- | --- | --- |
| `rig_search` | `search_web` | Discover URLs with provider and attempt provenance | Pi search router; SearXNG, DuckDuckGo, Tavily, Exa, Firecrawl, and SerpApi are six backends of this one tool |
| `rig_search` | `fetch_page` | Fetch and clean a selected public HTTPS page | Pi CPU |
| `local_agents` | `list_local_agents` | Report local agent roles and model candidates | Harness adapter reads gateway manager offers |
| `local_agents` | `delegate_local_task` | Run one bounded coding or research child and return its receipt | Harness child runner; gateway admits route; orchestration places model |

The local-parent variant of the subagent adapter exposes `delegate_task` instead of `delegate_local_task`. It is a different surface of the same harness adapter, not a fifth dashboard tool.

The registry records 16 MCP surfaces and 42 named entries across them. Names repeat across surfaces: `search_web`, `fetch_page`, `delegate_task`, `get_catalog`, and `get_tool_help` each have more than one implementation or service. Only the four dashboard entries are live in gateway chat. The six search providers are backends of one entry, not six additional tools.

## Other harness-owned tools and test fixtures

| Surface | Tool names | Status and evidence |
| --- | --- | --- |
| Standalone SearXNG MCP | `search_web` | Earlier single-backend search adapter, used in the six-harness search comparison; `rig_search.search_web` is the current dashboard path. |
| Local RAG fixture | `search_passages` | Chroma passage search with source filter and cited IDs. The 2026-11-05 eight-passage comparison passed 23/24 adjudicated harness cases; corpus and service were isolated test fixtures, not a production index. |
| Marker fixture | `read_marker`, `read_structured_marker` | Deterministic MCP call and structured-result checks. Test tools only. |
| Numeric and lookup fixtures | `calculate_sum`, `calculate_product`, `get_entry`, `get_nested_entry` | Required-argument, arithmetic, and nested structured-result checks in the six-harness matrix. Test tools only. |
| Web-research fixture | `search_web`, `fetch_page` | Frozen search → real CPU scrape → page-only fact test. Test tools; current `rig_search` supplies the operational equivalents. |
| Subagent fixture | `delegate_task` | Frozen parent-to-child delegation comparison; the operational adapter is `gateway_subagent_mcp.py`. |
| Older web-search adapter | `search_web` | Calls orchestration's old DuckDuckGo helper; comparison only. |
| MCP call guard | No model-facing name | Bounded repeat/error/call counts for HTTP MCP comparison runs. Useful harness middleware; not yet applied to dashboard stdio MCP. |

## Tested tools outside the harness repo

These were reached through local loopback tunnels or public MCP endpoints during the 2026-10-29 and 2026-11-02 comparisons. They are not currently registered in dashboard chat. Tool names below are from captured `tools/list` results or frozen comparison cases, not a claim that every service is reachable today.

| Owner/service | Tested tool list | Evidence and boundary |
| --- | --- | --- |
| DaedalMap Research, 10 captured tools | `get_tool_help`, `how_research_mcp_works`, `where_is_research_data`, `get_catalog`, `resolve_research_geography`, `search_research_sources`, `resolve_research_corpus_intent`, `get_research_pack`, `ask_research_sources`, `query_research_source_data` | Windows local MCP against installed data; Research cases passed for Pi and DeepSeek in the six-server matrix. `where_is_research_data` can change the local data root, so it requires a stricter policy than read-only discovery. |
| DaedalMap Geometry, 12 captured tools | `get_tool_help`, `get_catalog`, `get_pack`, `get_geography`, `resolve_point`, `resolve_deep_point`, `get_loc_id_info`, `identify_dataset_geography`, `identify_reference_system`, `convert_reference`, `compare_geographies`, `get_shape` | Local MCP; direct calls worked, but the shared 30B harness block failed both geometry cases. Empty `get_shape` arguments and a roughly 30 KB help result were observed. |
| DeepWiki | `read_wiki_structure` | Two public MCP matrix cases tested repository outlines. |
| OpenAI Docs | `search_openai_docs` | Two public MCP matrix cases tested documentation lookup. |
| Cloudflare Docs | `search_cloudflare_documentation` | Two public MCP matrix cases tested result-grounded URLs. |

## Promotion order

1. **Source-bound Research discovery:** Build a harness-owned read-only adapter for `search_research_sources`, `get_research_pack`, and `ask_research_sources`, backed by the existing Research MCP service. Keep data-root switching and corpus mutation out of the dashboard surface. Verify the loopback route, authentication, source IDs, and bounded result shape before enabling it.
2. **Local passage retrieval:** Generalize `search_passages` to a configured corpus/index with explicit embedding-model identity, source filter, passage ID, and citation. Keep the eight-passage fixture as a regression control; it is too small to establish production retrieval quality.
3. **Research call guard:** Adapt the tested HTTP MCP guard to the dashboard stdio path so repeated searches or child calls have bounded retry/error budgets and durable receipts. Discovery must remain available without consuming the call budget.
4. **Documentation lookup:** Add narrowly scoped public documentation tools only when a task needs them. Check current endpoints and tool schemas first; do not treat a 2026-11-02 comparison result as current availability.
5. **Geometry:** Start with small read-only discovery/lookup calls. Reduce long help responses and retest required arguments and structured-only results before exposing a broad Geometry surface.

For each promotion: implement the adapter in harness, add a focused direct MCP contract test and one agent-use test, record it as `disabled` in `tools/tool_registry.json`, review its data and network boundary, then switch it to `automatic`. Run `python3 tools/export_dashboard_tool_catalog.py sync`, then the gateway's `what-new`, `sync`, and `check` import flow. A new MCP server also needs gateway launch configuration. Keep adapters and the inventory in harness; keep underlying DaedalMap data services in their source repo, model offers/admission in gateway, and hardware execution in orchestration.

## Source receipts

- `docs/research/mcp_matrix_trial_2026-11-02.md` and `results/local_mcp_2026-10-29/{research,geometry}_tools.json`
- `docs/research/harness_suite_coverage_2026-11-02.md`
- `docs/research/local_rag_matrix_2026-11-05.md`
- `docs/research/subagent_delegation_matrix_2026-11-04.md`
- `mcp_servers/rig_search/docs/SEARCH_OVERVIEW.md`
