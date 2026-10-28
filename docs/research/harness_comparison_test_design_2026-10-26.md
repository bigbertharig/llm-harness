# Harness comparison: conversation and compaction test design

Date: 2026-10-26
Status: design only; no runner, fixture, model configuration, or harness integration has been created.

## Question

Given the same prepared model and served context window, which harness best preserves a useful conversation, stays within the window, recovers from pressure and interruption, and does so with acceptable prompt-processing cost? This compares the harness with a fixed model, not the model's standalone quality or the rig's placement decisions.

The [harness-mode contract](harness_mode_contract_2026-10-26.md) applies: the comparison never loads, unloads, resizes, or places models. Gateway and orchestration prepare the model and provide a ready roster. The harness uses only the advertised profile(s).

## Two stages

1. **Offline contract stage, before model integration:** a deterministic OpenAI-compatible fake model service records requests and can return scripted usage, overflow, and transient errors. This checks each adapter's configuration, session/resume path, output limit, response handling, and that a candidate makes no model-management calls. It cannot grade semantic compaction quality.
2. **Fixed-real-model stage, once the rig is ready:** use one externally prepared profile for every candidate. Confirm `/v1/models`, served model identity, actual context, tokenizer, and ready status before every run. Record rig state before and after; an unexpected load or model change invalidates the run. Start with a smaller validated window (16K or 32K) to exercise compaction cheaply, then repeat at the desired long window (for example Qwen 27B near 256K) only after gateway/orchestration validates that setup. The current `chat-27b` offer is smaller; 256K is a proposed test setup, not a present default.

The gateway cold-loads a published profile on requests without the ready-only header. Candidate
drivers must send `X-Require-Ready: true` on completion and tokenizer calls; the gateway then
returns 409 for a cold route. Preflight uses `GET /v1/rig/ready-roster` and checks the loaded
profile before and after each run. A model can still disappear after a readiness check, which is
reported as a failed run rather than repaired by the candidate.

## Common runner boundary

Give each candidate a small driver that can `configure`, `start_session`, `send_turn`, `resume_session`, `export_events`, and `close`. The runner supplies the model ID, endpoint, context/output limits, fixed user turns, tool fixtures, and isolated workspace. A driver translates those actions to that harness's CLI, SDK, or server API; it must not rewrite the candidate's agent loop or compactor. Keep candidate version, configuration, adapter version, and any unsupported action in the receipt. If a candidate cannot resume, record that failure rather than emulating resume outside it.

The runner owns fixtures and scoring; candidates own their native context policy. Do not force all candidates to the same compaction threshold for the primary comparison, because choosing when and what to compact is part of the behavior being measured. A second controlled-policy experiment may tune thresholds after the native baseline.

## Conversation cases

| Case | Stimulus | Checks |
|---|---|---|
| Short control | A few turns with stable facts and no context pressure. | Basic answer and session correctness; avoids attributing all errors to compaction. |
| Long retention | Early facts, task constraints, a later correction to one fact, then many relevant and distracting turns. Probe before and after compaction. | Retains important old facts, uses the latest correction, follows standing constraints. |
| Tool-output pressure | Deterministic file/search/test outputs, including one large result and a concise failure pointer. | Bounds or prunes low-value output without losing the fact needed to finish. |
| Boundary and recovery | Continue until cumulative history crosses the served window; inject a documented overflow or transient failure in a separate run. | Compacts or recovers without losing the task, preserves output headroom, avoids repeated overflow loops. |
| Restart | Stop the harness process after substantial history, then resume the same session. | Durable state, continuity, and transparent compaction history. |
| Asynchronous script completion | Start a delayed script that emits progress and a known final line; repeat with nonzero exit and with a harness restart before completion. | Captures the full log outside model context; wakes the agent once on a terminal event with bounded output, status, exit code, and log pointer; no repeated model status calls or duplicate tool results. |

Fixtures should be realistic conversations, not only repeated filler. Facts and corrections need explicit answer keys. For tool cases, use the same read-only fixture files and outputs, and keep full logs outside model context. A semantic grader checks answers against the keys; deterministic checks inspect limits, errors, and state. Preserve all raw requests/responses and grader receipts for audit, with secrets excluded.

## Measurements and pass criteria

- **Correctness:** answer-key accuracy before and after compaction, latest-correction accuracy, task completion, and violations of standing constraints.
- **Boundary:** maximum request tokens plus reserved output versus served window; overflow count; whether the harness recovers; model identity and ready-roster invariance.
- **Continuity:** session resume success, lost commitments, duplicate or omitted turns, and compaction count/timing.
- **Efficiency:** input/prefill tokens per turn, cached versus new tokens when reported, prompt-processing time, total wall time, and extra model calls for compaction. Report these alongside correctness, never as a substitute for it.
- **Compatibility:** configuration changes and driver code needed per harness, unsupported features, and whether upstream code was patched.
- **Async tools:** model status-call count while a job is running, wake-up latency after completion, duplicate or missed terminal events, output truncation, failure reporting, and recovery after restart. Distinguish native support from a thin adapter and from a changed agent loop. See the [script completion contract](async_tool_completion_contract_2026-10-27.md).

A valid run must use the intended model and context, leave load state unchanged, preserve a trace, and finish within its declared time/output budget. A passing case must answer its key probes correctly and recover without an unrecoverable overflow or lost session. Report case-level results and failure reasons; do not collapse them into one opaque score. Repeat real-model runs to distinguish stochastic variation from harness behavior.

## Existing work to reuse

- `llm-gateway/tools/model_check.py` already probes advertised versus served context, model identity, `/tokenize`, prompt speed, tool-call shape, streaming, and overflow. Use it as a preflight reference; it is not a conversation harness comparison.
- Benchmarking's `CHECKPOINT_SUITE_DESIGN.md` defines case/receipt separation and keeps the harness observation distinct from grading. Its `bench-checkpoint` work targets model capability on coding tasks; this design targets harness behavior with a fixed model.
- `docs/lessons_bench_checkpoint.md` records prompt-cache cost, compaction frequency, bounded tool output, and long-context lessons that should shape the fixtures and metrics.

Do not implement or run a non-trivial suite until its owning runner and suite-authoring instructions have been checked. The current deliverable is a comparison protocol that can accept any candidate through a thin driver when model integration is ready.
