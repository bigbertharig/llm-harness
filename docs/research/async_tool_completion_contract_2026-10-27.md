# Harness script output and completion contract

Date: 2026-10-27
Status: design requirement; no runner or model integration yet.

## Goal

A model can start a script, receive its useful output, and continue when that script finishes without spending model turns on repeated status checks. The harness owns the wait and wakes the agent on a terminal job event. A human-facing terminal can show live output and a completion alert, while the model receives a bounded, durable tool result.

This is part of harness tool and session management. It does not grant the harness authority to load, unload, resize, or place models; the [harness-mode contract](harness_mode_contract_2026-10-26.md) still applies.

## Execution flow

1. The agent calls a script tool once. The harness allocates a `job_id` and `attempt`, records the session/tool-call association, and starts the process or submits it to an existing worker. It sends a `job_started` acknowledgement to the runtime or human UI, while keeping the agent's tool call pending. Independent work can continue under an explicit policy; the waiting agent does not receive a tool result until a terminal event arrives.
2. A job supervisor captures stdout and stderr to an append-only log, timestamps the start, and sends progress to the human terminal or UI. It may retain a small tail or structured progress summary for the agent. It never streams an unbounded log into the model context.
3. The supervisor observes the authoritative completion signal. For a child process it owns, process exit and exit code are sufficient; the script does not need to implement an alert. For a detached or remote job, the executing wrapper or worker must publish a durable terminal receipt and notify the harness. An audible beep or printed marker alone is not a reliable completion event.
4. On completion, the harness records the terminal event, verifies its `job_id` and `attempt`, reads the bounded result, and resumes the waiting agent with one tool result. The result includes success or failure, exit code, elapsed time, relevant output or failure pointers, and the full log reference. The model may request more log content when needed.

Suggested receipt fields: `job_id`, `attempt`, `session_id`, `status` (`succeeded`, `failed`, `cancelled`, `timed_out`), `exit_code` when available, `started_at`, `finished_at`, `log_ref`, and an optional short summary. Write the receipt atomically. The exit code and any declared validator determine outcome; a script's prose or beep does not override them.

The existing `completion_alert.py` pattern shows how a script wrapper can save a log and an atomic JSON terminal receipt. Its alert is useful for a person. The harness needs a separate event bridge from process exit or that receipt to session resumption. The existing `wait_for_completion.py` demonstrates receipt freshness checks, but its blocking wait is not itself an agent wake-up mechanism.

## Delivery and recovery

- Keep a durable pending-job registry tied to the session and tool call. Persist the terminal event before resuming the agent. On restart, reconcile pending jobs with owned process state or terminal receipts and deliver missed results.
- Treat event delivery as potentially repeated. Deduplicate by `job_id` plus `attempt` and terminal-event identity so a duplicate notification cannot create a second model turn or tool result. Reject stale receipts from earlier attempts.
- Define timeout and cancellation as terminal outcomes. If a child exits without writing an expected receipt, use its exit code. If a remote job loses its event channel, reconcile against the durable receipt; if neither a process state nor receipt can be established, surface an explicit unknown/interrupted outcome instead of waiting forever.
- The gateway or orchestration layer may execute or supervise remote work and emit job events. The harness owns the agent-facing tool result and wake-up; it does not need to replace the existing script or hardware managers.

## Comparison requirement

Compare candidate harnesses with a delayed deterministic script that emits progress, writes a known final line, and exits. Assert that the agent starts it once, makes no repeated status tool calls while waiting, and receives exactly one correct completion result. Repeat with a nonzero exit and with a harness restart before completion. Record whether support is native, available through a thin adapter, or requires changing the candidate's agent loop. This test can run against the fake model service before a rig profile is ready.
