# Harness candidate integration and test playbook

## Ownership update (2026-11-24)

The comparison cases and historical evidence below remain useful research. The accepted
[product boundary](../README.md#product-boundary) assigns reusable comparative evaluations to Benchmarking.
Harness retains deterministic engine/tool conformance, fixtures and development regressions.
Migration is Planned under the [implementation status](../README.md#implementation-status); historical receipts are preserved.
The Gateway readiness rules below describe the managed-rig lane, not a prerequisite for
future standalone provider adapters. The dated model matrix is historical evidence, not
a current required model selection.

Date: 2026-10-28
Status: process defined; frozen short-control and local MCP tool-use runners cover Pi, OpenCode, and DeepSeek; full shared comparison runner pending.

This is the harness counterpart to benchmarking's `NEW_MODEL_INTEGRATION.md`. Benchmarking establishes which model and context are usable. This playbook holds those fixed and tests what a harness adds: conversation continuity, context and output management, tools, asynchronous jobs, recovery, and control boundaries. The detailed conversation cases and metrics are in [harness comparison test design](research/harness_comparison_test_design_2026-10-26.md); the model-resource boundary is in the [harness-mode contract](research/harness_mode_contract_2026-10-26.md).

The gateway owns the inference and ready-roster APIs used for preflight; it and rig orchestration prepare model resources. The playbook's ready-only rules apply to candidate traffic. See the gateway's [manager contract](https://github.com/bigbertharig/llm-gateway/blob/main/docs/MANAGER.md) for gateway-side preparation and routing behavior.

## Rules for a valid comparison

- Use one externally prepared, ready model profile and its actually served context for every candidate in a comparison block. Read `GET /v1/rig/ready-roster` before each run and confirm served identity, optional tokenizer route, context, and readiness. Send `X-Require-Ready: true` on every completion and tokenizer request so a changed route returns 409 without loading. Confirm state again afterward. Do not let a harness load, unload, resize, or place a model.
- Freeze user turns, answer keys, tool fixtures, workspace, tool permissions, output ceiling, thinking setting when supported, and retry budget. Record any candidate-specific translation. Do not tune one harness during the baseline while leaving others at defaults.
- Give each candidate a thin driver for `configure`, `start_session`, `send_turn`, `resume_session`, `export_events`, and `close`. The driver may translate CLI/API shapes but must not supply a missing compactor, tool loop, or session store and then attribute it to the candidate. Record native, adapter-provided, patched, and unsupported capabilities separately.
- Preserve raw local traces, logs, configuration, and exit/finish reasons in a run directory; commit only a sanitized summary. Record `run_id`, candidate commit, driver commit, fixture version, model identity, served context, sampling/effort, output ceiling, start/end times, and gateway state before/after. A failure is a result, not a reason to silently change the fixture.
- A candidate is never promoted from a single overall score. Report correctness, control violations, context behavior, token/cached-prefill cost, wall time, and operational complexity by case. Run each real-model case more than once when stochastic behavior matters.

## Model matrix

Run every candidate against the same model within each block, then compare that candidate across the three required model classes. These are benchmarking's current picks. The IDs below identify benchmark models for test planning; the gateway must separately offer and mark a route ready before a harness can use it.

| Class | Required model ID | Placement | What the class probes |
|---|---|---|---|
| Large capacity | `nemotron-3.5-bolt:74b-a9b` | All six cards for the long-window trial | Whether the harness can use a measured approximately 227K window without excessive compaction or prompt reprocessing; general-agent behavior on a large model. |
| Strong 3090 | `gemma-4:31b` | 3090 Ti alone | Strong answer and tool quality at a much faster decode than the large-capacity pick; useful primary baseline for harness behavior. |
| Single 1060 | `ornith-1.5:9b` | One 1060 | Whether instructions, tools, recovery, and context policy still work with a smaller model and tighter resources. |

Optional speed controls, after the required matrix: `qwen3.6:35b-a3b` on the 3090 and `ministral-3:3b` on one 1060. The latter still has qualification notes in the registry; label that status and do not treat it as the quality representative. The user's measured decode rates are approximately 20-22, 38, and 18.5 tok/s for the three required picks, versus about 152 and 38-40 tok/s for the speed controls. Record the actual rate and setup in each harness run rather than treating these earlier measurements as a guaranteed trial speed.

Use two distinct comparisons:

1. **Harness comparison within a model:** freeze the prepared profile, actual context, prompt, thinking setting, output ceiling, tools, and fixture; run the same case through every candidate. This isolates harness differences as far as the model and runtime permit.
2. **Model robustness within a harness:** rerun a common short-chat/tool fixture that fits the smallest served window across all three classes. Attribute changes cautiously: a failed tool call may reflect the model, the harness's tool format, or their interaction. A direct gateway baseline and raw traces help separate them. Long-context/compaction cases run at each class's independently validated served context and are reported by capacity, not as equal-context quality scores.

Do not infer a served context from the model's trained ceiling or benchmark default. For example, Nemotron's registry default is 16K, while its all-six-card capacity result is about 226,816; the live test must verify which setup is actually ready. Preserve the externally chosen thinking mode, and record generated reasoning, visible output, finish reason, and the hard output ceiling where the server reports them. A response that spends its limit thinking without a final answer is incomplete. Run models sequentially when placements overlap; no harness test may take cards away from another active run.

## Phases and gates

| Phase | Work | Gate |
|---|---|---|
| 0. Pin candidate | Record source, license, commit, supported runtime, CLI/API entry point, and installation/build steps in an isolated directory. Inspect its closest native test/example. | Candidate starts without changing the rig or another candidate's files; exact version and install log retained. |
| 1. Offline contract | Use a deterministic OpenAI-compatible fake model endpoint. Exercise model configuration, request logging, output limits, finish reasons, malformed/overflow responses, session resume, and forbidden management endpoints. | Expected requests and agent events match the fixture; **zero** model-management calls; unsupported features marked honestly. No GPU required. |
| 2. Ready-roster preflight | Have gateway/orchestration prepare the model externally. Run `python tools/ready_roster.py --gateway http://127.0.0.1:8080`; match the returned gateway route, underlying benchmark model, actual context and optional tokenizer path to the pinned manifest. Establish a direct gateway baseline with the ready-only header and fixed output cap. | Target appears in the ready roster; no cold load or model change; baseline and preflight receipt saved. Otherwise stop the live lane. |
| 3. Chat smoke | Run a short, keyed multi-turn conversation, then close and resume the session. Check natural stop versus length stop, visible final answer, and request trace. | Correct keyed answers, no lost/duplicated turns, explicit handling of incomplete output. |
| 4. Context and compaction | Run long retention, correction, tool-output pressure, and boundary cases from the comparison design at the same validated context. Compare native policy first; tune later in a separate A/B. | Request input plus reserved output stays inside the served limit or a documented provider rule; key facts survive compaction; no unbounded overflow loop. Record compaction timing and prefill cost. |
| 5. Tools, MCP, and jobs | Run deterministic file/tool fixtures in an isolated workspace. Exercise a local stdio MCP and a remote Streamable HTTP MCP. Start a delayed script once; test success, nonzero exit, bounded output, and a deliberately denied tool action. | Verify MCP discovery and exact tool invocation from both transports, rather than accepting a plausible answer copied from files or the model's memory. Correct tool result, no unauthorized action, one completion wake-up, zero model status polling, full log retained outside context. |
| 6. Recovery | Inject transient model failure, truncated thinking/no final answer, restart before the next turn, and restart while a script is pending. | Explicit terminal outcome or bounded recovery; no duplicate tool execution or model result; session and pending-job state reconcile. |
| 7. Delegation | Only after the single-model lane passes, offer a second externally ready profile and a task with a verifiable child result. | Exact allowed model IDs used; child work and cost traced; no resource changes. Mark unsupported candidates as such rather than emulating delegation in the driver. |
| 8. Repeat and decide | Repeat the identical lane across candidates; inspect raw failures, then run separately labeled tuning A/Bs. | Case-level receipts and known limits support an adopt, fork, borrow, or build decision. No candidate is selected merely because a feature exists on paper. |

The first short lane is Phases 0-3, then one delayed-job case from Phase 5. Only expand to long context and recovery after the smoke passes. A direct gateway baseline helps separate model mistakes from harness mistakes. Where a case expects a final answer, a response stopped by an output limit without one is incomplete and must not be scored as a correct answer merely because its reasoning contains the key.

## Runner and receipt shape to build

One runner should own fixtures, scoring, model-state snapshots, and receipts. Candidate drivers should be small and isolated. The runner should fail before invoking a candidate if model identity, readiness, context, or allowed endpoint differs from the pinned manifest. Save one case receipt containing: input/answer-key version; candidate and driver versions; model request metadata and usage; tool calls/results; finish reason; compaction and recovery events; verdict with explicit failed assertions; and full log references. Keep raw traces local unless reviewed for public release.

`tools/live_preflight.py` covers the Phase 2 gateway boundary and writes a local JSON receipt. `research/external_harnesses/comparison_short_control.py` and `research/external_harnesses/comparison_tool_use.py` now own frozen short-chat and local stdio MCP cases for three native candidates. They are partial scored lanes; the full comparison runner still needs the offline fake-model contract, request-level traces, more candidate adapters, and the remaining phases. Do not treat a gateway preflight, upstream unit test, or direct model benchmark as a harness comparison receipt.

## MCP and compaction comparison details

- **Local MCP:** use one small stdio server whose tool returns a runtime-generated marker and records each call. Pass only if the candidate discovers the server, invokes the named MCP tool exactly once, and repeats its returned marker. Record startup errors, tool-list changes, elapsed time, and whether the agent instead reads fixture source or uses unrelated tools.
- **Remote MCP:** first use the same controlled tool over Streamable HTTP on another host for a deterministic comparison; then use one documented public, read-only MCP to check real network compatibility. Record DNS, TLS, proxy, authentication, discovery, call, and disconnect behavior separately. A public service's variable answer is not a fixed correctness key. Never send private workspace content to the public server.
- **Compaction mechanics:** keep the gateway's actual served context in the model profile. Use a separately labelled low-threshold policy to force a short multi-turn conversation with an early fact, a correction, and distractions. Pass only if the durable log contains a completed compaction transaction, the summary preserves the corrected facts, the final answer is right, and the ready roster is unchanged. Count summarization model calls and cached versus new input tokens.
- **Native and boundary policy:** repeat with each harness's untouched compaction defaults, then run a genuine near-window case at the served context with reserved output headroom, overflow and restart variants. A low-threshold mechanics pass alone does not establish safe behavior at the real context boundary. Keep native and tuned results separate.
- **Repeated compaction:** count a transaction only when the persisted log has a summary and an error-free end for the same compaction ID. Record failed attempts even when the model returns a correct answer. Disable model-facing tools for a conversation-only lane; file-backed memory is a separate result. Use a blind early-fact/correction case with one final keyed answer so intermediate answers do not refresh the facts. Track summary output tokens against its cap, missing/superseded facts, and whether later turns recover or fail after a truncated summary.

## First preflight, 2026-10-28

Reference checkouts exist for DeepSeek Harness, Codex, Pi, OpenCode, Hermes Agent, and Nanobot; `UPSTREAM.md` pins their commits. They are research clones, not installed harnesses. The gateway currently advertises `gpu-rig/chat-27b`, `coder-7b`, `coder-30b`, `devstral-24b`, `gpt-oss-20b`, and `nex-split`, but `/v1/rig/status` reports `bench` mode with `k2-v2-instruct:70b` ready at 8192 context. That is not a ready match for any advertised harness profile. The Phase 2 gate is therefore **not met**; no live candidate/model request was sent. First work is the offline runner/driver and a ready-route agreement with the gateway, while preserving the current benchmarking load.

## First live gateway preflight, 2026-10-28

With the user's authorization to use the idle rig, the Pi gateway was restarted with the ready-roster
API. The earlier idle `k2-v2-instruct:70b` benchmark load was unloaded through `rigctl`; the manager
then loaded offered `chat-27b` on GPU0. The roster identified `gpu-rig/chat-27b` as
`qwen3.6:27b`, interactive profile, ready at an actual 65,536-token context.

`tools/live_preflight.py` passed its first live run. Ready-only `/tokenize` returned four tokens;
ready-only chat returned a visible answer (`Okay`, finish reason `stop`); a request for cold
`gpu-rig/coder-7b` returned 409 `model_not_ready`. Rig profile ID, model, port, served context,
and lease were identical before and after. The full local receipt is
`results/ready_roster_preflight_2026-10-28.json` on the Pi. This validates the gateway boundary,
not any candidate's conversation, compaction, tools, or session behavior.

The first actual candidate smoke is [the rough live trial note](research/first_candidate_trial_2026-10-28.md). Codex exercised one tool call, a resumed turn, a cold-route refusal, and both tuned-trigger and native-trigger compaction. DeepSeek exercised model calls, local and public MCP tools, tuned early compaction, and an untouched native-policy long-context case on the same prepared model. The matching native long transcript exposed a Codex post-compaction answer error and DeepSeek's unusable default proactive headroom on this 65K route. These probes expose useful behavior but do not replace the offline contract, shared driver, repeated correctness runs, overflow recovery, or a complete true-boundary gate.

For a local route smaller than DeepSeek's shipped 65,536-token headroom, record the default-policy failure first. Then use a **separately labeled per-route policy** with headroom and summary output caps that fit the validated context; do not quietly alter the baseline. For Codex, inspect persisted session events as well as CLI JSONL: this trial's `context_compacted` checkpoints appeared in the session log, while the CLI event stream did not carry a dedicated compaction item. Score final-answer correctness independently from whether a checkpoint preserved the facts.

## Small-window follow-up, 2026-10-28

[The 16K/32K trial note](research/small_window_compaction_trial_2026-10-28.md) records a 7B model on the 3090 at an actual 16K context and a 30B model on the same card at an actual 32K context. Codex completed one usable 16K compaction cycle, then exceeded the served window after a second checkpoint. DeepSeek's adapted 16K policy completed five cycles with three facts but later lost four of nine details; a no-compaction control recalled all nine. On 30B/32K, a no-tools blind case retained nine corrected details after five compactions. A longer no-tools session reached nine successful summaries, then repeatedly hit the 1,024-token summary cap; increasing only that cap to 1,536 recovered one more checkpoint. These are single-run mechanics and failure-mode observations. The model and context both changed between 16K and 32K, so the improvement cannot yet be assigned to either alone.

## Pi candidate follow-up, 2026-10-29

[The Pi candidate trial](research/pi_candidate_trial_2026-10-29.md) used the same ready 30B/32K gateway route as the small-window DeepSeek case, with a separate native Pi RPC driver. Its default policy first compacted after overflow. A tuned no-tools blind case retained nine corrected facts through six completed compactions with a 1,536-token route output cap. At 768 tokens, incomplete summaries caused repeated failed attempts. These are exploratory mechanics observations, not a scored cross-candidate comparison; the shared frozen fixture, MCP, restart, and job cases remain open.

## Trial scorecard

Use the [Harness trial scorecard](research/harness_scorecard_2026-10-29.md) and its sortable `research/harness_scorecard_runs.csv` ledger to compare candidate results and open the detailed trial receipts. Keep each model/window and native/tuned policy in its own row.

## Frozen short-control pilot, 2026-11-02

The first shared runner is `python3 research/external_harnesses/comparison_short_control.py CANDIDATE --run-id UNIQUE_ID`, where `CANDIDATE` is `pi`, `opencode`, `deepseek`, `nanobot`, `codex`, or `hermes`. Its sanitized config inputs are under `research/external_harnesses/comparison_fixtures/`, with native controllers under `research/external_harnesses/candidate_controllers/`. Pi, OpenCode, DeepSeek, Nanobot, and Codex require `coder-30b` externally ready at the actual 32,768-token context; Hermes requires `chat-27b` externally ready at 65,536 context and is a separate block. The runner fails closed on a roster mismatch. Run `tools/live_preflight.py` first. Use a fresh ID for every invocation; the runner refuses to overwrite a receipt. The [short-control trial note](research/short_control_trial_2026-11-02.md) records the fixture hash, three repetitions for the original candidates, later single runs for Codex/Nanobot, two Hermes format-failure repeats, receipt paths, and limitations.

This pilot covers Phase 3's short conversation and part of Phase 2's ready-route check. It does not satisfy Phase 1's offline request contract, long-context Phase 4, tools/jobs Phase 5, or recovery Phase 6. Add candidate adapters and request-level evidence before treating it as the complete comparison runner. Keep the initial DeepSeek plan-mode tool-call failure in the ledger; a later corrected pass does not erase it.

## Frozen local MCP tool-use pilot, 2026-11-02

Run `python3 research/external_harnesses/comparison_tool_use.py CANDIDATE CASE --run-id UNIQUE_ID` after `tools/live_preflight.py`, with the same externally ready `coder-30b` route. `CANDIDATE` is `baseline`, `pi`, `opencode`, or `deepseek`; `CASE` is `text` or `structured`. The runner launches the `marker` profile of `tools/fixtures/diagnostics_mcp.mjs`, checks its direct protocol baseline, then records exact calls, model-visible answer, exit and finish, and ready-roster preservation in a unique ignored result directory. The server generates its marker only when called. Preserve failed setup receipts under their own IDs.

The [tool-use trial note](research/tool_use_trial_2026-11-02.md) and [MCP run ledger](research/harness_mcp_scorecard_runs.csv) contain two final-configuration runs per candidate and case. Pi passed both result shapes; DeepSeek lost structured-only content after a correct call; OpenCode discovered the tools but made no call. This pilot covers local MCP discovery, invocation, and result fidelity in part of Phase 5. The six-server follow-up below covers remote MCP separately. Denial, asynchronous jobs, and the offline request contract remain open. The next diagnostic is a request/response trace for OpenCode and a structured-result mapping check for DeepSeek.

## Six-server MCP matrix, 2026-11-02

Run `python3 research/external_harnesses/run_mcp_matrix_batch.py CANDIDATE --run-id UNIQUE_ID` with `CANDIDATE` set to `pi`, `deepseek`, `opencode`, `nanobot`, `codex`, or `hermes`. The active set has twelve questions across three local services (marker, DaedalMap Research, DaedalMap Geometry) and three public HTTPS services (DeepWiki, OpenAI Docs, Cloudflare Docs). `research/external_harnesses/comparison_mcp_matrix.py` first proves each question with direct MCP initialize, list, and call, including a concrete answer key. Only direct-baseline failures are excluded from the comparison. A case all harnesses fail remains scored when its direct call passed. Preserve server-response shape and argument difficulty as case tags; do not subtract difficult cases after seeing candidate results.

The local DaedalMap runtime can remain on the workstation at `127.0.0.1`; an SSH remote forward exposes it on the Pi's loopback. Do not bind its unauthenticated development endpoint to the LAN for this test. Each harness has its own `research/external_harnesses/candidate_controllers/` module and isolated run configuration; the pinned upstream checkouts are unchanged. Shared questions, direct baselines, and scoring live in the matrix runner. Direct baseline payloads are restored to the case receipt only after the candidate exits, preventing Codex's built-in shell from reading the answer file. Codex's MCP-only controller disables its shell tools using supported feature flags. The [matrix trial note](research/mcp_matrix_trial_2026-11-02.md) records the twelve baselines, candidate results, Geometry failures, and public DaedalMap catalog diagnostic. The [matrix ledger](research/harness_mcp_matrix_runs.csv) holds individual case verdicts. On the 30B/32K route Pi passed 10/12, DeepSeek 9/12, Nanobot 9/12, OpenCode 0/12, and Codex 0/12. Hermes passed 10/12 on its required 27B/65K route, a separate block. These are one-run exploratory results, not an overall harness ranking.

Web research is a separate multi-step lane: search JSON, select URLs, CPU fetch and extract, then answer with a source URL and a fact present in fetched page text. Run `python3 tools/web_research_control.py --scraper <orchestration-checkout>/shared/plans/shoulders/research_assistant/scripts/scrape_pages.py --out results/web_research_control_2026-11-02.json` for the direct JSON-and-scraper control. It passed six checks on 2026-11-02; its search fixture omits the answer from snippets and the CPU scraper extracts it from the page. This is a fixture control, not evidence of a live SearXNG endpoint or harness synthesis.

For the current live search backend, run `python3 scripts/experiments/search_provider_benchmark.py (from Benchmarking) --backend ddg --out results/SEARCH_ID.json` from the `llm-orchestration-venv` interpreter. It measures four fixed documentation queries in paced and short-burst rounds: latency, unique URL yield, expected official-domain rank, empty responses, and rate-limit signals. The optional `--backend searxng --searxng-url URL` uses the same queries when a real SearXNG service is available. Run `python3 research/external_harnesses/comparison_web_search.py CANDIDATE --run-id UNIQUE_ID` with the default `rig_search` backend for the native harness lane; it directly validates each MCP search before scoring a candidate's one search call, returned URL count, official-domain result, grounded answer, latency, and rate-limit signal. The six-candidate trial has 24/24 passing direct baselines. Pi, DeepSeek, and Nanobot passed 4/4; Hermes passed 3/4 on its separate 65K block; Codex and OpenCode scored 0/4 with no native search calls. The [search ledger](research/harness_web_search_runs.csv) stores timings and checks. A search-only pass does not prove page fetching or source-grounded synthesis; add that two-tool case after its own direct baseline.
