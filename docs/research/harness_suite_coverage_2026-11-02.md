# Six-harness test coverage

Updated 2026-11-04. This is a coverage register, not a combined rank. The six candidates are Pi, DeepSeek Harness, OpenCode, Nanobot, OpenAI Codex, and Hermes Agent. OpenCode and OpenAI Codex are different harnesses.

| Lane | Same frozen suite run for all six? | Current evidence | Next gate |
|---|---|---|---|
| Short conversation and resume | Yes, one or more runs each | Five passed their strict control; Hermes twice retained all facts but returned `ACK.` instead of exact `ACK` | Repeat Codex/Nanobot to match the original three-run reliability sample; investigate Hermes format compliance |
| Local and online MCP tools | Yes, 12 cases each; Hermes separate 27B/65K block | All direct baselines passed; five candidates on 30B/32K, Hermes on 27B/65K | Trace Codex/OpenCode native tool requests; rerun Geometry argument/result cases with a gateway tool-call control |
| Live web search | Yes, four questions each on DDG and SearXNG; Hermes separate model block | SearXNG direct baselines 24/24; valid end-to-end passes: Pi 4, DeepSeek 4, Nanobot 4, Codex 3, OpenCode 3, Hermes 2 of 4. Later Google CSE rate limiting blocked provider recovery and load probes. | Paused; revisit after provider recovery or a validated fallback and evaluate independent egress if needed |
| Search → CPU fetch → cited answer | Yes, one frozen two-tool case each; Hermes separate model block | Direct MCP and real CPU scraper passed; Pi, DeepSeek, Nanobot, Hermes passed; Codex and OpenCode failed twice each | Trace model-visible tools for Codex and OpenCode; add more page-only answer keys after controller verification |
| Compaction and long context | Candidate-specific exploratory runs for all six, no matched six-candidate fixture | See [scorecard](harness_scorecard_2026-10-29.md); models, policies, and context differ | Freeze matching native and tuned lanes per model block, with repeated fact retention and completed-checkpoint checks |
| Subagents and delegation | Yes, one frozen `coding` case each | Six direct baselines and six native parent-to-child cases passed; manager routed parent GPU 0 to child GPU 1 | Repeat for `research`, add failure/timeout and two-child concurrency cases |
| Asynchronous jobs and wake-up | No shared suite | Design in [async completion contract](async_tool_completion_contract_2026-10-27.md) | Test one delayed completion with durable receipt and no model polling |
| Denial, restart, and failure recovery | Candidate-specific probes only | Some Codex/OpenCode/Hermes resume evidence | Freeze permission-denial, nonzero tool exit, interrupted-session resume, and cold-route rejection cases |

The shared runner boundary is in [candidate controllers](../../research/external_harnesses/candidate_controllers/README.md). Controllers own only native setup and event translation; the shared runners own tasks, direct baselines, score rules, and receipts. Pinned upstream harness source checkouts were unchanged by this pass. A new harness version should get a new run ID and controller compatibility check, leaving the old receipt intact.

## Codex compatibility follow-up, 2026-11-02

The isolated Codex controller now translates namespaced Responses MCP tools to the flat function surface supported by the local rig route and explicitly approves its one enabled test-server tool for noninteractive runs. No upstream Codex files were edited. The native marker integration passes with one actual call. Repeating the frozen lanes yielded **8/12 MCP** cases and **3/4 web-search** cases on Qwen3 Coder 30B/32K, versus the earlier 0/12 and 0/4. Details and limitations are in `docs/research/mcp_matrix_trial_2026-11-02.md` and the corresponding `codex_integrated_*` and `codex_search_fixed_2026-11-02` receipts.

The new `mcp_servers/searxng/server.py` contract passes 3/3 deterministic checks. Live SearXNG coverage is pending an endpoint with JSON search enabled; see `docs/research/searxng_mcp.md`.

The SearXNG MCP is now selectable in the shared four-question web-search runner with `--backend searxng`; the six candidate controllers receive the same standalone MCP command and the direct baseline gate runs first. SearXNG receipts live in their own `results/<run-id>/searxng/` tree. The combined adapter contract receipt `results/harness_adapter_contracts_2026-11-02.txt` passed 7/7 checks (Codex namespace translation 2, SearXNG MCP 3, runner integration 2). Live SearXNG quality and rate-limit measurements remain pending a configured instance with JSON output enabled.

The SearXNG upgrade preserves bounded result provenance, search suggestions and corrections, unresponsive-engine reasons, and degraded-search signals; it distinguishes HTTP 403 from 429 and records latency on failures. The MCP, comparison, and Codex namespace contracts passed **8/8** in `results/searxng_upgrade_contract_2026-11-02.txt`. Those are deterministic fixtures; the later live evidence is recorded below. The [SearXNG MCP note](searxng_mcp.md) records the design evidence and a future multi-instance pool option.

The Pi now hosts a private JSON-enabled SearXNG endpoint on `127.0.0.1:8888`. The tuned direct provider control passed **4/4** paced queries with ten URLs each, expected official domains at rank one, and no engine health signals in that short sample (`results/search_provider_searxng_pi_tuned_paced_2026-11-02.json`). The tuned native Pi-harness trial using GPT-OSS 20B on GTX 1060 GPUs 1–4 passed **4/4** end-to-end search cases (`results/searxng_1060_gptoss_tuned_four_v1/searxng/pi/batch_summary.json`). Earlier live calls exposed Brave rate limits and DuckDuckGo CAPTCHA; the benchmark now records those upstream failures, and the comparison runner separates backend health from harness behavior. Other harnesses and a second 1060 model have not yet run against live SearXNG. The 3090 is released for separate benchmarks. The gateway repo has a tested, staged GPU-pinned published-load change; its live service has not been restarted.

## SearXNG six-harness round, 2026-11-03 to 2026-11-04

The same four live SearXNG cases now have valid direct baselines for all six harnesses. Pi, DeepSeek, Nanobot, Codex, and OpenCode used Qwen3 Coder 30B/32K on the 3090; Hermes used Qwen3.6 27B/65K. End-to-end passes were **4/4, 4/4, 4/4, 3/4, 3/4, and 2/4** respectively. The [SearXNG MCP note](searxng_mcp.md) links each durable batch receipt and records failures separately from backend health.

The first Nanobot/Codex misses were a shared MCP child-environment error. The runner now passes an explicit SearXNG endpoint to the standalone server; an isolated-process contract passed 8/8. OpenCode's initial 0/4 came from its controller denying `execute`, which removed all model-visible tools in the installed build even though MCP discovery succeeded. The corrected isolated controller exposes the target MCP tool while denying other named actions; a sanitized gateway trace and a successful search call verify the repair. Its corrected suite is 3/4, with the MDN case still failing on call selection or final-answer format. These initial invalid runs remain in their original receipts and are excluded from the valid comparison.

The remaining native harness failures are bounded: Codex skipped one call but passed that case on repeat; Hermes received relevant URLs in every case but violated strict JSON output in two; OpenCode's MDN repeat made a correct call but returned an invalid final answer. Direct baselines were 24/24, with zero rate-limit signals in this short sequential round. The next evaluation lane is a two-tool search-to-CPU-fetch-to-cited-answer fixture, plus a provider-only concurrency and rate-limit window. The gateway's GPU-pinned load change remains staged and not deployed.

## Two-tool research chain and provider load, 2026-11-04

`research/external_harnesses/comparison_web_research.py` runs one frozen, page-only answer case through `tools/fixtures/web_research_mcp.py`. Search returns two URLs with snippets that omit the cadence fact; `fetch_page` invokes the existing `llm_orchestration` CPU scraper on the first URL. The candidate must call search once, fetch that exact URL once, return the cadence from page text, and cite the fetched URL in JSON. Each candidate has a direct MCP and real-scraper baseline before inference; all six baselines passed. The independent CPU scraper control passed 6/6 at `results/web_research_cpu_control_2026-11-04.json`; the final direct MCP control is `results/web_research_final_contract_2026-11-04/research/pi/summary.json`.

| Harness | Native chain | Receipt |
|---|---|---|
| Pi | Pass | `results/web_research_native_2026-11-04_v3/research/pi/summary.json` |
| DeepSeek Harness | Pass | `results/web_research_native_2026-11-04_v3/research/deepseek/summary.json` |
| Nanobot | Pass | `results/web_research_native_2026-11-04_v3/research/nanobot/summary.json` |
| Hermes Agent (27B/65K) | Pass | `results/web_research_native_2026-11-04_v3/research/hermes/summary.json` |
| OpenAI Codex | Fail twice: searched, did not fetch, then supplied a cadence absent from the page | `results/web_research_native_2026-11-04_v3/research/codex/summary.json`; `results/web_research_native_2026-11-04_repeat/research/codex/summary.json` |
| OpenCode | Fail twice: connected to the two-tool MCP, made no call, then supplied an unsupported answer and URL | `results/web_research_native_2026-11-04_v3/research/opencode/summary.json`; `results/web_research_native_2026-11-04_repeat/research/opencode/summary.json` |

The first Pi attempt exposed a one-tool allowlist in its isolated controller, not a model failure. Pi, Codex, Nanobot, and Hermes controllers now accept an exact list of allowed MCP tools; DeepSeek and OpenCode already receive the server's tool list. The second Pi attempt completed the chain and gave the full factual sentence; the final prompt asks for the cadence value and the scorer accepts either the exact value or that exact sentence. The first two Pi receipts remain as test-design evidence. All six harnesses ran the same final task and scoring rule. No upstream harness checkout was edited. The current fixture is a test control dependent on the orchestration CPU scraper; it is not a production URL-fetch MCP.

The direct provider control `results/searxng_provider_preflight_2026-11-04.json` returned ten URLs and the official domain at rank one on 8/8 sequential paced/burst requests, with no rate signal; Wikipedia timed out or remained suspended on five. The later bounded 1/2/4-worker probe `results/searxng_provider_concurrency_2026-11-04.json` received HTTP 200 but zero URLs and a Google CSE `too many requests` or suspended-engine signal on all 36 requests, beginning at one worker. This is an upstream engine limit; whether it is keyed specifically to the Pi's egress IP is unverified. The probe cannot support a concurrency speed comparison. The reusable probe now stops after a whole batch returns only rate-limited zero-result responses. A fresh run needs engine recovery or an independently validated fallback, with cooldown between levels.

`python3 -m unittest -v tests.test_comparison_searxng tests.test_searxng_mcp` passed 6/6 after the controller and runner changes. The rig's 3090 route was unloaded after the native runs.

## Paced provider recovery, 2026-11-04

The SearXNG provider remained blocked after a three-minute interval between each of the four frozen queries: 0/4 returned URLs, and all four HTTP 200 responses carried Google CSE `too many requests` or suspended-engine signals (`results/searxng_spaced_recovery_2026-11-04.json`). An earlier single-query preflight was also blocked. Engine-specific checks separated by three minutes found ten Bing URLs but placed the expected official page seventh, while Qwant returned zero URLs with a CAPTCHA (`results/searxng_fallback_bing_2026-11-04.json` and `results/searxng_fallback_qwant_2026-11-04.json`). Pacing alone did not clear the current Google CSE limit; these one-query fallback checks are not a replacement for the four-question relevance gate. The full details and future acceptance gate are in [SearXNG MCP research](searxng_mcp.md). No model route was loaded for this provider-only pass.

## Next function after pausing live search, 2026-11-04

Live SearXNG provider load testing is paused after the spaced recovery and alternate-engine receipts above. More independent egress IPs may be worth testing later if limits prove egress-specific; the current evidence does not establish that they will solve relevance, CAPTCHA, or per-provider quota limits. Continue with the subagents/delegation lane. Its first shared fixture should give a parent one bounded child task with a hidden deterministic key, require the parent to verify the child's result, and record child creation, depth, tool budget, completion, and final answer across all six harnesses. Run direct and fake-model controls before spending rig time. The asynchronous completion lane follows once this parent-child event path is measured.

### Gateway-managed child route smoke, 2026-11-04

The first Pi integration exposes an MCP `delegate_task` tool with only `agent_type` and `task` arguments. Its controller supplies the parent route; the gateway manager resolves or cold-loads a disjoint ready route within five minutes, then the adapter starts a separate native Pi child session with a bounded output and runtime. The child receives no delegation tool, limiting depth to one. The gateway roster now includes observed GPU IDs, and the adapter checks the returned route before and after the child run. No upstream harness checkout was edited.

With parent `chat-27b` on GPU 0, a `coding` request cold-loaded `coder-7b` on GPU 1. The direct child control returned an answer on the separate route (`results/subagent_gateway_live_2026-11-04_v3/summary.json`). The parent MCP control made the delegate call, received child answer `42`, verified it, and returned `42` (`results/subagent_gateway_parent_mcp_2026-11-04_v1/summary.json` and its `children/*/summary.json`). An initial client timeout and a relative Pi config path error were fixed; their v1/v2 receipts remain as failure evidence. Gateway regression passed 33/33, harness request contract 1/1. The matched six-harness round followed below.

### Matched six-harness delegation round, 2026-11-04

`research/external_harnesses/comparison_subagents.py` now runs one frozen `coding` case through the existing six isolated MCP controllers. The parent sees only the task and `agent_type=coding`; the fixture injects a private arithmetic question into the child task, then reveals that question with the child's answer for the parent to verify. The child runs in a separate Pi process with no delegation tool, a 96-token output cap, and a 90-second child timeout. The gateway manager resolves or loads a disjoint ready route and has a five-minute preparation deadline. The runner gates each native run on a direct MCP/child baseline and records native calls, child receipts, parent answer, route stability, and GPU separation. The frozen fixture hash is `eb7d04d2b844265849cf8b6e752edffb5d3b577fef7a7499fc17e37611ab4bd5`.

| Harness | Parent route | Native pass | Duration |
|---|---|---:|---:|
| Pi | `coder-30b` | 1/1 | 5.44 s |
| DeepSeek Harness | `coder-30b` | 1/1 | 6.35 s |
| Nanobot | `coder-30b` | 1/1 | 7.00 s |
| OpenCode | `coder-30b` | 1/1 | 12.28 s |
| OpenAI Codex | `coder-30b` | 1/1 | 11.52 s |
| Hermes Agent | `chat-27b` | 1/1 | 30.96 s |

All six direct baselines and all six native cases passed, with parent GPU 0 and child `coder-7b` on GPU 1 (`results/subagent_six_native_v2/subagents/matrix.json`). The first Nanobot run reached the tool but its MCP subprocess lacked a controller environment variable; the fixture and production MCP adapter now accept parent route and receipt directory as launch arguments. All six were rerun against that corrected fixture. The earlier direct baseline's 12-second generic MCP wait also failed during a cold load; the delegation control now waits up to the manager readiness deadline. The earlier receipts remain under `subagent_six_v1` and `subagent_six_native_v1`.

This proves a reusable MCP delegation path across the six harnesses. It does not yet measure each harness's built-in subagent feature or compare model quality: five parents used 30B/32K, Hermes used 27B/65K, and all children used the same 7B model. The manager currently accepts `coding` and `research`; only `coding` has a matched six-harness result. Next, test `research`, load failure/timeout behavior, and simultaneous child requests before ranking delegation reliability.
