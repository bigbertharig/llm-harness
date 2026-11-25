# Coding resume: runtime settings and child failure propagation

Date: 2026-11-24 (Mountain time)

## Completed

Benchmarking owns the Qwen3.8-27B interactive sampler in `model_registry.json`, including the
llama-server startup arguments. Harness no longer exposes per-run sampling parameters or forces
temperature zero. It sends the output budget and records `generation_settings_source=runtime_profile`.
The generic native-tool batching contract remains active.

The real `gateway_subagent_mcp.py` adapter is now exercised with controlled timeout, cancellation,
and reservation-release failures. Timeout and cancellation produce an error response, persist a
nonzero child receipt, release once, and return no invented answer. Release failures now also set
`exit_code=1`, matching the existing MCP error flag. These deterministic checks close the parent
failure-reporting boundary of P1 case 19; natural-language parent synthesis is a separate live gate.

## Validation

- Full Harness suite after sampler removal: 166 tests and 12 subtests passed.
- After the child-boundary change: registered `agent_runtime`, `catalog_routing`, and
  `test_infrastructure` suites passed 114 tests and 3 subtests.
- Benchmarking model-library, capacity, and suite-registration checks passed 49 tests and 48 subtests.
- Gateway's full registered suite passed 291 tests, including historical prompt timestamps and
  executable desktop/mobile activity-order regressions.
- Orchestration rig tests passed 101 tests.

A bounded Qwen audit read the two changed Harness files with four tool calls and three model turns.
It completed in 23.00 seconds with no transport or finalization error. All three captured completion
request shapes contained only `model`, `messages`, `max_tokens`, and optional `tools`. The runtime
reported temperature 0.7, top-p 0.8, top-k 20, min-p 0, presence penalty 1.5, and repeat penalty 1.
The temporary model load was released after the trial.

The audit answer correctly described the sampler boundary but did not confirm the release exit-code
change. It disclosed an evidence gap. Treat this as a passing request/profile integration check and
partial task accuracy, not a passed code review or comparative quality result. Preserve it as another
P2 evidence-selection case under the existing tool budget.

Private raw receipts are in the Pi's `Desktop/Transfer/coding_resume_20261124/` directory:
`qwen-harness-smoke.json`, `qwen-harness-wire-proof.json`, `qwen-runtime-settings.json`, and the
repository test logs and terminal JSON receipts. The model-library export hash is
`2ee8308ce3f544b008814180144fda5b01a2478df4dc4554c16964b1cd5d170f`.

## Remaining P1 work

Corrected facts across durable resume, compaction retention/non-reducing compaction, and active-agent
restart integration remain explicit pending gates. Existing reducer and broker recovery tests do not
establish those end-to-end behaviors. Repeat matched local-model fixtures only after their mechanism
contracts are defined and covered.
