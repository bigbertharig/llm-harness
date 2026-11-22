# Project-owned Harness framework

The active Harness is a small control plane around probabilistic models. External harnesses remain
removable references. Provider vocabulary terminates at adapters; authorization, state transitions,
tool execution, recovery, and terminal classification are deterministic project-owned mechanisms.

## Layers

1. **Contracts** — versioned run and event schemas, route/model identity, budgets, grants, fixture
   identity, and terminal reasons.
2. **Adapters** — translate Chat Completions, Responses, MCP, and validated text bridges into the
   canonical event vocabulary. Adapters do not decide permissions or success.
3. **Reducer** — a pure state machine consumes ordered events and decides the next allowed action.
   Every loop has a bound and progress invariant.
4. **Tool broker** — discovery, schema normalization, validation, approval binding, idempotency,
   execution, reconciliation, and result persistence are distinct transitions.
5. **Drivers** — deterministic multi-step operations such as complete-document reading and delayed
   jobs own their cursors/checkpoints. Models interpret evidence; they do not control mechanical
   progress loops.
6. **Journal and receipts** — append-only events are the recovery source of truth. A versioned run
   receipt references events and protected artifacts, while redacting sensitive payloads by default.
7. **Policies** — retry, compaction, delegation, cancellation, and finalization are small replaceable
   policies tested with fake providers and clocks.

Gateway owns conversations, operator policy, and requested work. Orchestration alone owns hardware
admission and monitoring. Harness consumes a ready route and explicit grants, then returns auditable
events and a terminal receipt.

## Implementation sequence

- P0a (built): canonical schemas and centralized terminal classification.
- P0b (built foundation): scripted provider transport and a pure reducer for ordered model, tool,
  retry, compaction, child, input, and terminal events. Conformance tests cover full tool
  lifecycle, truncation repair, sequence/link rejection, transport errors, malformed provider
  payloads, and defensive request/response copies. Provider adapters still need to be migrated to
  emit these events before P0b is considered integrated.
- P0c: append-only journal plus exactly-once tool reconciliation.
- P0d: harness-owned complete-document driver and bounded compaction transaction.
- P1: MCP shape matrix, delayed jobs, queue/steer ordering, and child lifecycle.
- P2/P3: repeated live reliability, security adversaries, endurance, and pinned external subsets.

No new general-purpose tool enters the active catalog without a named failure class, deterministic
contract test, receipt fields, permission owner, and rollback/recovery behavior.
