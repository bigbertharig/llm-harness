# First candidate trial: Codex, then DeepSeek setup check

Date: 2026-10-28
Status: rough live observations; no comparative grade yet.

## Fixed resource

The Pi gateway offered `gpu-rig/chat-27b`, backed by `qwen3.6:27b` on GPU0 at an actual 65,536-token context. Gateway commit `e08271e` added a read-only, ready-only `/v1/responses` passthrough because this Codex version uses the Responses API and the loaded llama-server supports it. The rig roster remained the same after all trials. The CLI tested was the Pi's installed `codex-cli 0.147.0`; `~/codex` is a separate pinned source checkout at `7389eebf45`, so these results apply to the installed binary.

An isolated Codex home supplied a custom provider with `base_url = "http://127.0.0.1:8080/v1"`, `wire_api = "responses"`, `http_headers = { "X-Require-Ready" = "true" }`, `model_context_window = 65536`, and no OpenAI authentication. Trials ran in a disposable workspace with a read-only sandbox and no approvals. The first unisolated attempt reached the model but also tried to refresh a pre-existing login and contact unrelated MCP services; isolation removed that noise. Raw event traces and stderr remain in the ignored `results/codex_smoke_2026-10-28*` and `results/codex_two_turn_2026-10-28/` directories on the Pi.

## Observations

| Probe | Observation |
|---|---|
| One short turn | Codex returned “Yes, I can read your message.” through the gateway Responses route. The isolated run completed without account or MCP network errors. |
| Tool and continuation | On turn 1, Codex called a shell tool to read `marker.txt`, received `RIG-482`, and reported it. After the process exited, `codex exec resume` restored the same thread ID and answered `RIG-482` on turn 2 without another file read. Both turns completed. |
| Trace | JSONL recorded thread start, tool command, tool output, agent text, turn completion, and token usage. This made the result inspectable without relying on terminal prose. |
| Context cost | The first tool-turn model request processed 7,672 prompt tokens and took 5.1 seconds of prompt processing. Its following request reused 7,728 cached tokens and processed 62 new tokens; the resumed turn reused 7,820 and processed 34 new tokens. These are gateway llama-server timings, not a model-quality score. |
| Model metadata | Codex warned that `gpu-rig/chat-27b` was missing from its model catalog and used fallback metadata. The 65,536 context was passed explicitly. Long-context or compaction tests should wait for a verified model-catalog/config adapter. |
| Ready-only control | A Codex request for offered but cold `gpu-rig/coder-7b` received 409 `model_not_ready`; the rig roster stayed unchanged. Codex retried the 409 five times before reporting `turn.failed`, even with provider `request_max_retries = 0`. Its separate stream retry setting was left at the default. This is unnecessary wait/work for a known non-transient refusal. |

No compaction, output-budget, long asynchronous job, guardrail denial, or multi-model delegation case has been run. This is enough to confirm a Codex tool loop and durable session on one local model, not enough to declare Codex better than another harness.

## Measures suggested by this trial

Keep case-level observations before choosing weights or a winner:

1. **Task result:** correct final answer, tool result used correctly, no duplicate tool execution.
2. **Continuity:** same session after restart, key facts retained, visible compaction behavior under pressure.
3. **Resource discipline:** uses only ready routes, stays within served context, accounts for output headroom, never initiates a model load.
4. **Efficiency:** input tokens, uncached prompt tokens, cache reuse, model calls, avoidable retries, and elapsed time per case.
5. **Control and observability:** enforceable permissions, approval behavior, complete event trace, useful failure reason, and asynchronous job wake-up without model polling.
6. **Integration cost:** candidate patches, gateway changes, required adapter/config code, installation effort, and behavior with our small and large models.

For each case, compare candidates on the *same prepared model*, input, tools, and limits. Record unsupported cases and setup failures separately from incorrect agent behavior. A small model's mistaken answer does not by itself prove the harness is poor; a missing trace, unbounded retry, or cold load is directly attributable to harness/integration behavior.

## DeepSeek second: setup check

The pinned DeepSeek Harness checkout is present but has no installed dependencies. Its `package.json` requires Node `^22.19.0 || >=24.0.0` and pnpm `11.28.5`; the Pi has Node `20.20.0`. Both npm and Corepack could not reach `registry.npmjs.org` during this check. No DeepSeek agent run occurred, so it has no outcome score. Next, supply a compatible Node runtime and dependency cache to the Pi or run the pinned candidate in another isolated environment with a route to the same gateway, then repeat the Codex file/continuation cases before widening the suite.
