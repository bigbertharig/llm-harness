# Project-owned Harness framework

The active Harness is a small control plane around probabilistic models. External harnesses remain
removable references. Provider vocabulary terminates at adapters; authorization, state transitions,
tool execution, recovery, and terminal classification are deterministic project-owned mechanisms.

## Layers

1. **Contracts** — versioned run and event schemas, route/model identity, budgets, grants, fixture
   identity, and terminal reasons.
2. **Provenance boundary** — operator objectives remain separate from uploads, repositories, web
   pages, external messages, and tool results. External content is admitted as typed, digest-bound
   `untrusted_evidence`; callers cannot supply its role or trust. Evidence can inform an answer but
   cannot alter grants, approvals, policy, or the objective.
3. **Adapters** — translate Chat Completions, Responses, MCP, and validated text bridges into the
   canonical event vocabulary. Adapters do not decide permissions or success.
4. **Reducer** — a pure state machine consumes ordered events and decides the next allowed action.
   Every loop has a bound and progress invariant.
5. **Tool broker** — discovery, schema normalization, validation, approval binding, idempotency,
   execution, reconciliation, and result persistence are distinct transitions.
6. **Drivers** — deterministic multi-step operations such as complete-document reading and delayed
   jobs own their cursors/checkpoints. Models interpret evidence; they do not control mechanical
   progress loops.
7. **Journal and receipts** — append-only events are the recovery source of truth. A versioned run
   receipt references events and protected artifacts, while redacting sensitive payloads by default.
8. **Policies** — retry, compaction, delegation, cancellation, and finalization are small replaceable
   policies tested with fake providers and clocks.

Gateway owns conversations, operator policy, and requested work. Orchestration alone owns hardware
admission and monitoring. Harness consumes a ready route and explicit grants, then returns auditable
events and a terminal receipt.

## Implementation sequence

- P0a (built): canonical schemas and centralized terminal classification.
- P0b (integrated): scripted provider transport and a pure reducer for ordered model, tool,
  retry, compaction, child, input, and terminal events. Conformance tests cover full tool
  lifecycle, truncation repair, sequence/link rejection, transport errors, malformed provider
  payloads, and defensive request/response copies. The active project-agent adapter now emits the
  same canonical events used by these conformance tests.
- P0c (integrated for the project agent): a private JSONL journal validates the pure reducer under an exclusive
  process lock and fsyncs every accepted event. Recovery policy resumes validation/approval,
  permits execution only from the durable `approved` state, and treats `executing` as an uncertain
  outcome that must be reconciled rather than repeated. Committed results are persisted and then
  delivered as separate steps. Tool results are private artifacts and model-visible results cross
  the provenance boundary as untrusted evidence. Tool-specific reconciliation remains required
  before write-capable profiles can recover an uncertain dispatch automatically.
- P0-security (integrated boundary): uploaded files and all other external evidence have fixed
  source types, origins, content digests, and system-owned trust. Receipts retain provenance without
  copying content. Allowlist validation and approvals remain the authority boundary; prompt labels
  are defense in depth, not the security mechanism.
- P0d (document driver integrated): a model selects targeted reading or requests a complete read
  with cursor zero. The Harness then advances every cursor mechanically, pins the snapshot digest,
  journals each chunk, and reports exact contiguous coverage. Bounded compaction transactions remain.
- P1 (in progress): the MCP result-shape matrix is integrated so text-only, structured-only,
  mirrored mixed, distinct mixed, explicit error, malformed, empty, and oversized results have one
  canonical outcome. The pure input policy now makes normal sends wait for `turn_end`, permits steers
  only after a model, tool, or compaction boundary, and preserves FIFO order within each class.
  Session adapters still need to emit/apply that policy. Remaining P1 work is delayed jobs and richer
  child lifecycle/recovery.
- P2/P3: repeated live reliability, security adversaries, endurance, and pinned external subsets.

No new general-purpose tool enters the active catalog without a named failure class, deterministic
contract test, receipt fields, permission owner, and rollback/recovery behavior.

The broker must append and fsync `tool.executing` before external dispatch. After that boundary it
must never infer that a missing response means the action did not happen. A retry requires either a
connector idempotency key tied to the normalized argument digest or a reconciliation result proving
the original action absent. `tool.committed` means the external outcome is known and references its
receipt; it does not mean the result has yet been durably stored or returned to the model.
