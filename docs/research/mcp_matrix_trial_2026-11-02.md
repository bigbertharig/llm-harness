# Six-server MCP comparison, 2026-11-02

## Scope and denominator

This trial extends the [first local tool-use trial](tool_use_trial_2026-11-02.md) to three local services and three public HTTPS services, with two questions each. A case enters the comparison only after a direct MCP `initialize`, `tools/list`, and `tools/call` returns a valid result and a concrete answer key. **All twelve active cases passed that direct baseline.** An all-harness failure remains in the denominator; it is not evidence that the server is broken when the direct call passed. The [case ledger](harness_mcp_matrix_runs.csv) records every candidate verdict and failed check. Raw receipts are ignored under `results/mcp_matrix_2026-11-02_full_v1/` and `results/mcp_matrix_2026-11-02_refined_v2/` on the Pi.

| Service | Transport and data | Questions and key |
|---|---|---|
| Marker fixture | Local stdio on Pi | Text marker; structured-only marker. Marker is created only on call. |
| DaedalMap Research | Windows loopback, forwarded to Pi loopback | First installed pack ID (`cejst`); local source count (`52`). |
| DaedalMap Geometry | Same loopback tunnel | `get_shape` available count for a pinned Australian loc_id (`1`); `get_tool_help(topic=geometry)` help topic (`geometry`). |
| DeepWiki | Public HTTPS | Section 1 title in two repository outlines. |
| OpenAI Docs | Public HTTPS | First hit URL for two fixed documentation searches. |
| Cloudflare Docs | Public HTTPS | One URL actually present in each of two search results. |

The three public services are `https://mcp.deepwiki.com/mcp`, `https://developers.openai.com/mcp`, and `https://docs.mcp.cloudflare.com/mcp`. The model route was externally prepared `gpu-rig/coder-30b`, Qwen3 Coder 30B at the actual 32,768-token context. The ready-only preflight passed at `results/preflight_2026-11-02_mcp_matrix.json`; each candidate case saved before/after ready rosters. The adapter configs declared a 1,536-token output cap; request-level enforcement remains untraced.

The Research and Geometry process ran from the public `county-map/tools/mcp-runtime/server.py` checkout against the existing `D:\county-map-data` root, bound only to Windows `127.0.0.1:7010`. An SSH remote forward exposed it only as Pi `127.0.0.1:17010` for the test. This avoided putting the unauthenticated local MCP on a LAN address. The public runtime's own offline smoke passed (`geometry` 26 dispatches, `research` 20, downloaded Geometry 13). Direct calls through the tunnel then passed the four selected cases. The separate standalone Geometry launcher gave the same result for the probes below.

## Results

| Candidate | Raw result | Local marker | Local Research | Local Geometry | Public docs/search |
|---|---:|---:|---:|---:|---:|
| Pi | **10/12** | 2/2 | 2/2 | 0/2 | 6/6 |
| DeepSeek Harness | **9/12** | 1/2 | 2/2 | 0/2 | 6/6 |
| OpenCode | **0/12** | 0/2 | 0/2 | 0/2 | 0/6 |

Pi and DeepSeek both reached the Windows Research service over the tunnel, called the requested tools, and returned the keyed values. DeepSeek again lost a structured-only marker after a correct call. Both Pi and DeepSeek repeatedly called Geometry `get_shape` with `{}` although the prompt supplied `loc_id` and `include_polygon=false`; the server-side schema rejected the empty arguments. The direct call with those arguments returned `available=1`. Their Geometry help attempts also failed: Pi retried until the 120-second case timeout, and DeepSeek reached its output cap before a final answer. Geometry help's direct result was about 30 KB, making output pressure a material case factor. These two all-fail cases stay in the 12-case denominator because their direct baselines passed.

OpenCode discovered the local marker service and produced plausible text without a valid completed answer in the active cases. One earlier `marker_structured` receipt logged a real call and returned marker, but the answer contained a large fabricated prefix and no clean final completion; a repeat made no call. This is more precise than saying it never invokes MCP. The runner now recognizes OpenCode's completed `tool_use` event and its CLI's exit-0 final-text fallback; a marker answer still must equal the fresh marker exactly.

The first Cloudflare tasks asked for the *first* URL. Pi and DeepSeek each made one correct call but selected another URL in the large returned search result, so all three harnesses failed those strict cases. Their receipts remain under `results/mcp_matrix_2026-11-02_full_v1/`. The final two cases ask for any one URL present in the actual tool result; Pi and DeepSeek passed both, OpenCode made no call. These refined receipts are under `results/mcp_matrix_2026-11-02_refined_v2/`. This separates grounded use of a result from rank-sensitive extraction in a long result.

The public DaedalMap free Geometry endpoint was probed as an additional diagnostic, but **not** substituted for a passing baseline. Its direct `get_catalog(catalog=geometry)` returned `coverage_catalog_unconfigured`; both attempted receipts are under `results/mcp_matrix_2026-11-02_baseline*/baseline/daedal_*/`. The Windows local server also returned that code for `get_catalog(geometry)` because this data root lacks an active coverage catalog directory. Its direct `get_shape`, Geometry help, Research catalog, and Research location calls did succeed. The local catalog state and public endpoint state are separate findings; neither failed catalog call entered the comparison denominator.

## Runner and scoring

Run `python3 tools/run_mcp_matrix_batch.py CANDIDATE --run-id UNIQUE_ID` on the Pi for the current twelve-case set. `tools/comparison_mcp_matrix.py` owns case definitions, direct baselines, answer extraction, exact tool/argument checks, candidate event scoring, and ready-roster checks; `tools/comparison_tool_use.py` supplies the native Pi, DeepSeek, and OpenCode drivers. `tools/summarize_mcp_matrix.py` regenerates the ledger and `results/mcp_matrix_2026-11-02_matrix_summary.json` from immutable case summaries. Raw baseline and candidate payloads remain in each case directory. No credentials were used.

Case tags describe response shape and argument complexity; they are not adjustments to the candidate score. Passing requires a real named call with expected arguments, one successful tool result, grounded answer value, a natural finish, clean process exit, and unchanged ready roster. Exact formatting is recorded separately. Random marker cases still require the exact marker. If a public result changes between baseline and candidate call, the candidate's actual result is used where it can be parsed; the direct baseline remains a validity gate.

## Next tests

1. Trace the gateway's model tool-call arguments for Geometry's `oneOf`/required-field schemas. Compare a reduced schema offline before changing the server or attributing the empty-argument calls to a particular layer.
2. Test long Geometry help with a larger, separately labeled output budget and measure result size and retry count. Keep the 1,536-cap failures as evidence.
3. Trace OpenCode's model request and response tool surface, including its intermittent native call. Add a direct gateway tool-call control.
4. Add a harness web-research lane for search, CPU-worker page fetch, extraction, and source-grounded synthesis; keep it separate from one-call MCP scores. The direct control below establishes the search/fetch key first.

## Web-research direct control

`tools/web_research_control.py` passed all six direct checks, with receipt `results/web_research_control_2026-11-02.json`. Its local HTTP fixture serves a SearXNG-compatible `/search?format=json` response containing an archive page and a distractor. The search snippets omit the keyed answer. The test feeds the selected URL to the existing `llm_orchestration` `research_assistant/scripts/scrape_pages.py` CPU step; `scraped.json` had `fetch_status=ok`, preserved the source URL, and extracted the page-only fact, **37 minutes**. This verifies the actual CPU scraper against a controlled page and prevents a search-snippet-only answer from passing the future harness case.

The checked-out `llm_orchestration` code uses DuckDuckGo for its current search path. A tracked-code search outside downloaded skill packages found no SearXNG integration, and neither the Pi nor rig had a SearXNG listener during this trial. Thus this receipt validates the JSON contract fixture and scraper, not a live SearXNG service or a harness's multi-step research behavior. The next gate is to start or locate a real SearXNG endpoint and repeat direct search/fetch baselines against it. The live search lane below tests native search calls; a later two-tool case should require the harness to fetch a result page, answer from page text, and cite that fetched URL.

## Six-candidate follow-up

The matrix now includes all six installed harnesses. The [case ledger](harness_mcp_matrix_runs.csv) and `results/mcp_matrix_2026-11-02_matrix_summary_v2.json` list each receipt. All twelve direct baselines passed for each candidate case. The frozen questions and direct baseline rule stayed the same.

| Candidate | Model block | Passed | Main failures |
|---|---|---:|---|
| Pi | Qwen3 Coder 30B / 32,768 | 10/12 | Both Geometry cases |
| DeepSeek Harness | Qwen3 Coder 30B / 32,768 | 9/12 | Structured marker; both Geometry cases |
| Nanobot | Qwen3 Coder 30B / 32,768 | 9/12 | Structured marker; both Geometry cases |
| OpenCode | Qwen3 Coder 30B / 32,768 | 0/12 | No complete keyed MCP answer in active cases |
| OpenAI Codex | Qwen3 Coder 30B / 32,768 | 0/12 | Discovered MCP, but used resource operations or answered without the named tool call |
| Hermes Agent | Qwen3.6 27B / 65,536 | 10/12 | Both OpenAI Docs first-URL answers |

Hermes requires at least 64K context and rejected the 30B/32K route before inference in its earlier trial. Its 10/12 is therefore a separate model/context block, not a numerical win over the 30B results. It passed the same direct-baseline-gated Geometry questions on the 27B/65K route. In that block, no case failed for all six; on the shared 30B route, both Geometry cases failed for all five candidates and remain in the denominator. The single-run data cannot separate model effects from harness effects across the two blocks.

Codex is **OpenAI Codex**, distinct from OpenCode. Its first setup attempt left stdin open and timed out; a corrected run closed stdin. A later run showed Codex's built-in shell reading a direct baseline file during a Research task. The final `codex_mcp_only_v2` receipt uses supported `shell_tool=false` and `unified_exec=false` settings and withholds direct baseline files until Codex exits. It still scored 0/12, with MCP discovery but no correct named tool call. This is a local Codex 0.147.0 plus Qwen3 Coder 30B result, not a general statement about Codex. A direct gateway tool-call control and request trace are needed to isolate the cause.

Each candidate now has its own controller under `tools/candidate_controllers/`; shared questions, direct baselines, and scoring remain in `tools/comparison_mcp_matrix.py`. The controllers create isolated config/home/workspace paths inside each receipt. The pinned harness reference checkouts were not edited. Hermes's declared optional `mcp==2.3.0`, `httpx2==2.15.1`, and `starlette==1.9.0` dependencies were installed into its separate test virtual environment before its MCP cases. Nanobot's controller logs native tool calls by wrapping its registered MCP tool object inside the isolated test process; no upstream source is patched.

After the existing Pi, DeepSeek, and OpenCode MCP functions moved into their own modules, one fresh `marker_text` regression per candidate ran under `results/mcp_matrix_2026-11-02_controller_regression/`. Pi and DeepSeek passed the same exact-call checks; OpenCode again discovered the server but made no target call. This verifies the code split preserved the observed MCP behavior.

### Search-provider baseline

`tools/search_provider_benchmark.py` ran the current `llm_orchestration` DuckDuckGo helper on four stable documentation queries, once paced and once in a short burst. Receipt: `results/search_provider_ddg_2026-11-02.json`. All 8 requests returned results and had an expected official domain in the first five; median latency was 2.857 seconds, observed p95 was 6.59 seconds, median unique URLs was 10, and no 429/throttling or empty-result signal appeared. The small sample does not establish a rate-limit ceiling. The same runner accepts a live SearXNG JSON endpoint through `--backend searxng --searxng-url URL` when one is available. `tools/comparison_web_search.py` is the separate four-question native-harness lane: it gates each question on a direct MCP search, then measures the actual returned URL count, backend latency, relevant-domain position, source-grounded answer, candidate duration, and rate-limit signals.

### Six-candidate live search results

The live search MCP fixture wraps the existing `llm_orchestration` DuckDuckGo helper and returns up to ten URLs with titles and snippets. Each of four official-documentation questions first passed a direct MCP initialize/list/call, relevance, URL-yield, and no-throttle gate for each candidate: **24/24 direct baselines passed**. The [search ledger](harness_web_search_runs.csv) and `results/web_search_2026-11-02_six_summary.json` preserve each native call, actual result URLs, backend latency, candidate duration, answer, and failed check.

| Candidate | Model block | Scored | Native calls | Median candidate turn | Observed URL yield |
|---|---|---:|---:|---:|---|
| Pi | 30B/32K | 4/4 | 4 | 6.52 s | 7â€“10 |
| DeepSeek Harness | 30B/32K | 4/4 | 4 | 6.08 s | 10 |
| Nanobot | 30B/32K | 4/4 | 4 | 9.37 s | 7â€“10 |
| OpenCode | 30B/32K | 0/4 | 0 | 4.63 s | No returned URLs |
| OpenAI Codex | 30B/32K | 0/4 | 0 | 3.57 s | No returned URLs |
| Hermes Agent | 27B/65K | 3/4 | 4 | 29.35 s | 7â€“10 |

All 16 actual search calls returned an official-domain result within the first five and had no observed rate-limit signal. The direct baselines likewise had no observed rate-limit signal. The **zero-call** Codex and OpenCode turn times are failure timings, not search-speed measurements. Hermes's last answer failed the grounded URL/count JSON check despite a correct call and relevant result. Separate backend timings are in the ledger; the candidate-turn medians include model startup, tool use, and answer generation. This tiny run cannot estimate sustained throughput or a rate-limit ceiling. Repeat with controlled concurrency and enough requests to observe 429/Retry-After, while stopping at a provider's published limits. A later SearXNG service can use the same direct benchmark input and its own separately labeled harness lane; this run does not claim SearXNG coverage.

### Codex tool-call isolation, 2026-11-02

The failing `marker_text` Codex receipt (`results/mcp_matrix_2026-11-02_codex_mcp_only_v2/codex/marker_text/`) shows successful MCP `initialize` and `tools/list`, followed by two `resources/read` requests and one `resources/list` request. The marker fixture implements tools, not resources, so those requests correctly returned MCP `-32601 Method not found`. Codex never sent `tools/call` for `read_marker`; its exit was clean and its short conversational control passed. This is a native-tool selection/exposure failure, not an MCP transport failure or a general text-generation failure.

The independent Responses API controls in `results/codex_direct_tool_required_2026-11-02.json` and `results/codex_direct_tool_auto_2026-11-02.json` both returned a `function_call` for `read_marker` with `{}` on the same `gpu-rig/coder-30b` route. This rules out a basic model/gateway inability to call a simple named function. It does not prove that Codex sent the same schema or tool list. Codex source exposes regular MCP tools directly when `supports_search_tool` is false, and its resource operations are separate registered tools; the installed binary's actual request tool list still needs a trace before attributing the failure to a specific Codex config or model behavior.

Next diagnostic: capture one sanitized Codex-to-gateway request's tool names and schemas (without prompts or credentials), then compare them with the direct control. If `mcp__marker__read_marker` is absent, correct the isolated controller/config or model metadata; if present, test a prompt naming the exact exposed tool and compare model tool choice. Keep upstream Codex untouched and rerun the marker and search lanes only after the mechanism is identified.

### Codex local-route compatibility fix, 2026-11-02

The sanitized request trace at `results/codex_tool_trace_full_2026-11-02/gateway_tool_trace.jsonl` showed Codex 0.147.0 advertising the marker as a Responses `namespace` named `mcp__marker` with nested `read_marker`, while also advertising generic MCP resource functions. A direct gateway replay of the same namespace did not issue a function call; with all tools present, the 30B model chose `list_mcp_resources`. Flattening that declaration to the ordinary function `mcp__marker__read_marker` caused a direct model call with `{}`. This is a compatibility issue between Codex's namespaced Responses tool surface and the local rig route, not a failure to discover the MCP server.

The first translated Codex run reached `read_marker`, but Codex returned `user cancelled MCP tool call`: the test had `approval_policy = "never"` and a read-only sandbox, which does not auto-approve MCP calls. The isolated controller now sets `default_tools_approval_mode = "approve"` for its one configured test server, and `tools/codex_responses_compat.py` translates namespace declarations to flat functions and restores the namespace field on returned function calls. The controller runs the adapter on a temporary loopback port, logs only tool names/status in each receipt, and leaves the Codex checkout unchanged. `results/codex_integrated_fix_2026-11-02/codex/marker_text/summary.json` passes all checks with one actual `read_marker({})` call and the exact fresh marker.

The post-fix frozen MCP rerun passed **8/12** strict cases on Qwen3 Coder 30B/32K: two marker, Research packs, two DeepWiki, OpenAI function calling, and two Cloudflare cases. See `results/codex_integrated_matrix_2026-11-02/codex/batch_summary.json` and `results/codex_integrated_local_2026-11-02/codex/batch_summary.json`. The first batch's four local Research/Geometry cases were invalid because the loopback Research/Geometry endpoint was stopped; they were rerun after restoring it. Research sources called the specified `where_is_research_data` tool and returned the correct count, but supplied an extra `catalog_file` argument, violating the frozen exact-arguments criterion. OpenAI streaming called the target tool successfully and returned the correct URL, but also called `list_mcp_resources`, violating the frozen exactly-one-call criterion. Both Geometry cases called their target repeatedly with `{}` and failed required argument validation; the 30B shared block previously showed Geometry failures across Pi, DeepSeek, and Nanobot too, so this is a model/schema problem to investigate separately. Do not reinterpret those as server failures: the direct MCP baselines passed.

The frozen web-search rerun improved from **0/4 to 3/4**: `results/codex_search_fixed_2026-11-02/codex/batch_summary.json`. Codex made a native `search_web` call in all four cases and returned ten URLs without a rate-limit signal. The remaining NumPy case selected a result URL outside the required top five despite a relevant top-five result. This was the existing DuckDuckGo-backed MCP lane, not live SearXNG.

The separate reusable SearXNG MCP implementation is `mcp_servers/searxng/server.py` with contract tests and usage in `docs/research/searxng_mcp.md`; its 3/3 deterministic receipt is `results/searxng_contract_2026-11-02.txt`. No live `SEARXNG_URL` was configured on the Pi. SearXNG's documented `/search?q=...&format=json` contract requires JSON to be enabled in the instance settings; the next live gate is an endpoint smoke plus the existing provider benchmark, then the candidate lane. The service may return 403 if JSON output is disabled.
