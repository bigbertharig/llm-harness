# Harness quality rubric

This rubric combines Big Bertha's matched trial evidence with regression patterns in the six pinned
upstream reference checkouts recorded in `UPSTREAM.md`. The review is source-local: immutable rig
policy prevents direct Internet access, so it does not claim to be a current survey of unpinned
upstream branches or external benchmark literature.

## What a good harness does

A good harness makes model behavior observable, bounded, recoverable, and safe. Final-answer quality
is necessary but insufficient: the same answer can hide duplicate writes, lost tool results, silent
input truncation, an incomplete stream, or a corrupted session.

Score capabilities separately rather than collapsing them into one rank.

| Dimension | Required evidence | Important failure injections |
|---|---|---|
| Turn integrity | Ordered user, assistant, tool-call, and tool-result events; one terminal outcome | empty completion, partial EOF, late event, duplicated terminal event |
| Session continuity | Durable session ID and transcript; current corrections survive; no cross-session leakage | cold process restart, resume during inference, stale client snapshot |
| Context management | Measured input plus reserved output stays within the served window; atomic compaction receipt | real overflow, incomplete summary, summary timeout, repeated compaction |
| Tool correctness | Reviewed schema, exact arguments, one authoritative result adjacent to its call | malformed arguments, missing result, schema change, large/binary result |
| Side-effect safety | Stable request identity and replay receipt; approval tied to normalized action | lost acknowledgement, retry after commit, changed-argument replay |
| Permission boundary | Effective grants are explicit and enforced below the prompt layer | prompt injection in tool data, denied path/action, resumed-session privilege drift |
| Retry and cancellation | Retry classification and cap are visible; cancellation stops pending work | 429 delay, refused connection, stalled body, cancellation during backoff/tool call |
| Queue and steering | Queued input waits for the turn boundary; steering has an explicit ordering point | input during tool call, input during compaction, reconnect with queued input |
| Output integrity | Length/overflow/error are distinct from success; truncation is visible | output cap, oversized tool result, Unicode boundary, invalid structured output |
| Operability | Ready model identity, limits, timing, usage, logs, and cleanup appear in one receipt | route change, harness crash, orphan process, missing dependency |

## Patterns found across the six references

- **Codex:** treats bounded tool output, schema normalization, approval, transcript state, and
  compaction as independently testable contracts. Its useful lesson is strict typed boundaries, not
  any single prompt strategy.
- **Pi:** normalizes provider-specific overflow signals, caps retry delay, makes retry abortable, and
  tests tool additions/removals across a transcript. A harness cannot assume every provider reports
  context overflow or tool evolution in the same wire shape.
- **DeepSeek Harness:** records retry lifecycle events, distinguishes clean partial EOF from retryable
  transport failure, avoids committing an empty assistant message, and freezes the authoritative
  post-policy tool outcome. This is the strongest reference for event-pipeline observability.
- **OpenCode:** represents compaction as typed state rather than ordinary prose and repairs missing
  tool results before the next model step. This directly motivates call/result adjacency checks.
- **Hermes Agent:** tests queue-versus-steer order during active turns and compaction, continuation
  after compression, and cold/fast resume without duplicate transcript rows. This is the strongest
  reference for interactive turn ordering.
- **Nanobot:** tests recovery after committed tool results, explicit stop versus gateway shutdown,
  failed-summary fallback, atomic archive progress, no-op repeated compaction, and MCP reconnect
  cleanup. This is the broadest reference for failure recovery, though our live trials found its
  native summaries lost facts under repeated compaction.

Reference behavior is not automatically adopted. A pattern qualifies for Big Bertha only after a
small project-owned implementation and deterministic regression test; the external harness archive
must remain deletion-safe.

## Test architecture

Use three layers, because a real-model answer alone cannot isolate the harness.

1. **Deterministic offline contract:** a scripted fake endpoint controls stream fragments, failures,
   usage, and tool calls. It grades requests, retry count, event order, state commits, and terminal
   classification without model variance.
2. **Matched live model:** every harness uses one already-ready route with identical prompts, tools,
   context, output cap, and sampling where supported. It grades integration and model/harness
   interaction. Route state before and after must match.
3. **Hardware and endurance:** real boundary compaction, restart, long jobs, and concurrency run only
   after the first two layers pass. Orchestration retains final hardware authority.

Every case needs an answer key, invariants that do not depend on answer prose, raw trace references,
and explicit unsupported results. Preserve failures. Do not tune a candidate inside the baseline.

## Project-engine status on 2026-11-22

The rubric is now feeding the project-owned Harness rather than selecting one of the six references.
Implemented and deterministically tested: canonical run/tool/compaction/child/input events; terminal
classification that rejects empty or truncated success; a pure reducer and scripted provider;
append-only recovery journals; uncertain-write reconciliation policy; untrusted evidence envelopes;
central read/Git/research profiles; and a snapshot-pinned complete-document cursor driver. The active
engine is independent of `research/external_harnesses/`.

The current P1 slice normalizes the MCP result matrix. Still open: delayed-job checkpoints,
queue-versus-steer ordering, richer child cancellation/restart recovery, active session compaction,
the large-document map/reduce driver, limit boundary probes, repeated adversarial/live reliability,
and the 3/5/10 true-context compaction campaign.

## Deferred matched six-reference suite

When reference comparison resumes, the next six-way suite should be short and general before
returning to deep context:

1. corrected multi-turn state with exact early acknowledgements;
2. isolated sessions with conflicting facts to detect leakage;
3. exact structured output and Unicode transport under the route's output cap;
4. cold resume with exactly-once transcript rows where the native interface supports it;
5. one deterministic tool success, one tool error, and one denied tool;
6. one transient pre-response failure and one partial-stream failure using the offline endpoint.

Report native, adapter-provided, and unsupported behavior separately. The first live block may run on
the currently prepared Nemo route, but its results form a new model block and are not directly
comparable to the earlier 30B/32K and Hermes 27B/65K blocks.
