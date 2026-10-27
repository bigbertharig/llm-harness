# Harness candidate integration and test playbook

Date: 2026-10-28
Status: process defined; no candidate adapter, runner, fixture, or harness trial has been run.

This is the harness counterpart to benchmarking's `NEW_MODEL_INTEGRATION.md`. Benchmarking establishes which model and context are usable. This playbook holds those fixed and tests what a harness adds: conversation continuity, context and output management, tools, asynchronous jobs, recovery, and control boundaries. The detailed conversation cases and metrics are in [harness comparison test design](research/harness_comparison_test_design_2026-10-26.md); the model-resource boundary is in the [harness-mode contract](research/harness_mode_contract_2026-10-26.md).

## Rules for a valid comparison

- Use one externally prepared, ready model profile and its actually served context for every candidate in a comparison block. Confirm served identity, tokenizer, context, and load state before and after each run. Do not let a harness load, unload, resize, or place a model. Gateway calls that might cold-load are prohibited until ready-only admission exists or the target is independently confirmed ready; label preloaded checks as an interim approximation.
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
| 2. Ready-roster preflight | Have gateway/orchestration prepare the model externally. Read the advertised and served IDs, readiness, actual context/tokenizer, and rig state. Establish a direct gateway baseline for the same fixed prompts and output cap. | Target is already ready through the route the harness will use; no cold load or model change; baseline and preflight receipt saved. Otherwise stop the live lane. |
| 3. Chat smoke | Run a short, keyed multi-turn conversation, then close and resume the session. Check natural stop versus length stop, visible final answer, and request trace. | Correct keyed answers, no lost/duplicated turns, explicit handling of incomplete output. |
| 4. Context and compaction | Run long retention, correction, tool-output pressure, and boundary cases from the comparison design at the same validated context. Compare native policy first; tune later in a separate A/B. | Request input plus reserved output stays inside the served limit or a documented provider rule; key facts survive compaction; no unbounded overflow loop. Record compaction timing and prefill cost. |
| 5. Tools and jobs | Run deterministic file/tool fixtures in an isolated workspace. Start a delayed script once; test success, nonzero exit, bounded output, and a deliberately denied tool action. | Correct tool result, no unauthorized action, one completion wake-up, zero model status polling, full log retained outside context. |
| 6. Recovery | Inject transient model failure, truncated thinking/no final answer, restart before the next turn, and restart while a script is pending. | Explicit terminal outcome or bounded recovery; no duplicate tool execution or model result; session and pending-job state reconcile. |
| 7. Delegation | Only after the single-model lane passes, offer a second externally ready profile and a task with a verifiable child result. | Exact allowed model IDs used; child work and cost traced; no resource changes. Mark unsupported candidates as such rather than emulating delegation in the driver. |
| 8. Repeat and decide | Repeat the identical lane across candidates; inspect raw failures, then run separately labeled tuning A/Bs. | Case-level receipts and known limits support an adopt, fork, borrow, or build decision. No candidate is selected merely because a feature exists on paper. |

The first short lane is Phases 0-3, then one delayed-job case from Phase 5. Only expand to long context and recovery after the smoke passes. A direct gateway baseline helps separate model mistakes from harness mistakes. Where a case expects a final answer, a response stopped by an output limit without one is incomplete and must not be scored as a correct answer merely because its reasoning contains the key.

## Runner and receipt shape to build

One runner should own fixtures, scoring, model-state snapshots, and receipts. Candidate drivers should be small and isolated. The runner should fail before invoking a candidate if model identity, readiness, context, or allowed endpoint differs from the pinned manifest. Save one case receipt containing: input/answer-key version; candidate and driver versions; model request metadata and usage; tool calls/results; finish reason; compaction and recovery events; verdict with explicit failed assertions; and full log references. Keep raw traces local unless reviewed for public release.

The runner does not exist yet. Use the existing comparison design as the fixture specification, then implement an offline fake-model contract case and one native candidate driver before running a real-model lane. Do not treat an upstream unit test or a direct model benchmark as a harness comparison receipt.

## First preflight, 2026-10-28

Reference checkouts exist for DeepSeek Harness, Codex, Pi, OpenCode, Hermes Agent, and Nanobot; `UPSTREAM.md` pins their commits. They are research clones, not installed harnesses. The gateway currently advertises `gpu-rig/chat-27b`, `coder-7b`, `coder-30b`, `devstral-24b`, `gpt-oss-20b`, and `nex-split`, but `/v1/rig/status` reports `bench` mode with `k2-v2-instruct:70b` ready at 8192 context. That is not a ready match for any advertised harness profile. The Phase 2 gate is therefore **not met**; no live candidate/model request was sent. First work is the offline runner/driver and a ready-route agreement with the gateway, while preserving the current benchmarking load.
