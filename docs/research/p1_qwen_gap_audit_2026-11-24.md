# Qwen 35B P1 regression-gap audit — 2026-11-24

Qwen 3.6 35B A3B was used as a read-only local coding subagent to audit the project-owned Harness
against the concrete first-20 regression list. The durable run is stored at
`results/p1-qwen35-regression-gap-audit-20261124T0735Z/summary.json`.

## What the run established

- Qwen selected case 6, 429 retry with cancellable backoff, as the highest-priority missing contract.
- Direct parent inspection confirmed that provider HTTP errors were flattened into a terminal
  `AgentLoopError`; status, `Retry-After`, and transport retryability were not preserved.
- The resulting local implementation classifies provider failures, permits one known-safe
  pre-response retry, caps delay at five seconds, checks cancellation every 100 ms, and records
  attempts independently from logical model turns.

## Capability and Harness feedback

The conclusion was useful, but the run itself failed its terminal contract. Qwen spent four of six
tool calls listing directories, used two broad searches, and then hit the 512-token output ceiling
while proposing a larger abstraction than the verified gap required. It also inferred that session
tests were absent from a zero-result phrase search even though differently named session-policy tests
exist.

This is evidence for three future upgrades rather than grounds for model-specific behavior:

1. Give audit tasks a compact repository map or targeted file hints when known.
2. Reserve answer space explicitly and grade unsupported absence claims.
3. Keep final implementation decisions in deterministic project-owned contracts; use local-model
   audits as evidence generators, not authorities.

The model was still valuable: it found the correct missing case quickly enough to guide a concrete P1
upgrade, and the failed receipt preserved exactly how its search and finalization degraded.

## Targeted patch-review follow-up

A second run at `results/p1-qwen35-retry-patch-review-20261124T0800Z/summary.json` constrained Qwen to
the current Git diff, three calls, and a 180-word answer. It terminated successfully without hitting
the output limit, and its live receipt exercised the new distinction between model attempts and
logical model steps.

It did not provide useful review coverage. Qwen called status before diff despite the explicit order,
the Git tool could not diff the untracked `retry.py`, and the model said the third tool result was not
retrieved even though the durable receipt records its successful delivery. This adds two concrete
future cases: Git review must expose untracked additions, and a model must not deny a delivered tool
result. `NO_BLOCKING_ISSUE` from this run is not accepted as evidence that the patch is correct.

## Focused session-isolation audit

The third run at `results/p1-qwen35-session-isolation-audit-20261124T0810Z/summary.json` was better
shaped: it used three relevant calls, stayed within its answer budget, and correctly classified the
contradictory-session case as a gap. Its explanation incorrectly called two input IDs in the existing
queue/steer test two session IDs, but direct inspection supported the main result: no deterministic
test bound contradictory model contexts and receipts to two distinct conversations.

The follow-up contract binds every run event and receipt to one immutable conversation ID, preserves
that binding on journal resume, rejects cross-conversation event injection, and verifies that two
contradictory prompts produce isolated model requests and durable receipts. Corrected-fact resume and
compaction retention remain separate cases.

A final targeted review at
`results/p1-qwen35-conversation-binding-review-20261124T0820Z/summary.json` gave Qwen two exact tracked
files and an ordered two-call review. It followed the order, inspected both complete diffs, finished
within budget, and found no blocking issue while citing the relevant resume, validation, reducer, and
receipt behavior. This is a useful successful control against the earlier broad and unreachable-diff
tasks: Qwen is materially more reliable when the task names reachable evidence and reserves a short
terminal answer.
