# Harness engine adapters

The project-owned Harness is the default model-use engine. The engine contract allows a site to add
another harness without coupling Gateway to that implementation or transferring tool, policy, or
hardware authority. The in-process `project_agent.py` adapter and conformance runner are the first
implementation milestone.

## Boundary

Gateway owns the conversation, authenticated operator action, objective, assignment, effective grants,
and choice of a currently ready route. Orchestration owns admission and hardware state. The Harness
boundary owns provenance, tool validation and execution, budgets, ordered events, recovery semantics,
and terminal receipts. An engine decides how to reason within that envelope.

```text
Gateway
  task envelope + ready route + effective grants
      -> Harness engine adapter
         engine reasoning <-> canonical model/provider adapter
         tool proposals ----> project-owned broker and approval checks
      <- ordered events + terminal receipt
```

An engine never receives raw credentials, a hardware-control handle, authority to load a model, or the
ability to add tools to its grant. Uploaded files, repository text, web pages, messages, and tool output
remain typed untrusted evidence. Instructions found in them cannot replace the operator objective or
change policy.

## Versioned inputs

The launch envelope should contain:

- contract and engine-adapter versions plus run, task, conversation, and attempt IDs;
- operator objective and system-owned operating rules, kept separate from untrusted evidence;
- selected route identity, canonical model identity, served context/output limits, and capability facts;
- explicit tool/profile grants, approvals, call/byte/turn/time budgets, and cancellation handle;
- journal checkpoint or recovery instruction and digest-bound evidence/artifact references.

The adapter must reject an unknown major version, a missing required identity, an unready/mismatched
route, an unsupported recovery state, or a grant it cannot enforce. It may negotiate a narrower feature
set; it may not silently broaden one.

## Versioned outputs

Engines emit the canonical ordered events defined by the framework rather than provider-native logs.
At minimum the stream covers model boundaries, tool proposals and lifecycle, compaction, child work,
input/cancellation, retry, recovery, and exactly one terminal classification. Payloads carry sequence
and causal identities so the reducer can reject gaps, duplicates, and illegal transitions.

The terminal receipt records the engine name/version/digest, adapter and contract versions, route/model
identity, effective grants and budgets, evidence digests, event-journal reference, tool/child receipts,
usage, recovery history, and terminal reason. Engine-specific diagnostics may be attached as bounded
artifacts, but they cannot replace canonical fields or turn a failed/incomplete run into success.

## Security invariants

- Tool discovery is not permission. Every call goes through the reviewed registry, normalized schema,
  argument validation, approval binding, budget checks, durable dispatch boundary, and result policy.
- The engine cannot write canonical journal events directly. The adapter validates and appends them;
  the reducer, not engine prose, determines legal state and terminal success.
- External evidence never becomes system instructions. Provenance type, origin, digest, and trust are
  system-owned fields.
- Write retries require an idempotency key bound to normalized arguments or reconciliation proving the
  original action absent. Missing output is not evidence that a write did not occur.
- Secrets remain in connector or broker identities. Engines receive redacted results appropriate to
  the task grant.

## Conformance before substitution

A replacement engine is eligible only after the same deterministic suite covers schema/version
rejection, route mismatch, tool grant denial, malformed calls, duplicate calls, byte/call/turn limits,
prompt-injection fixtures, complete-document progress, compaction, cancellation, transport failure,
write uncertainty and reconciliation, restart recovery, event ordering, and terminal classification.
Matched live trials then evaluate answer quality, latency, and cost separately from protocol compliance.

The six archived harnesses are research inputs, not automatically conforming engines. Their directory
must remain deletion-safe. The first implementation milestone is an in-process adapter around
`tools/project_agent.py` plus a fake engine; only after those pass should a subprocess or remote adapter
be added.

## Standalone status (2026-11-24)

The generic engine envelope and substitution conformance described here remain an
implementation target. Existing loop journals and receipts do not establish that full
boundary. `tools/project_agent.py` currently requires Gateway ready-roster discovery
even for a tool-free task. A standalone provider adapter and a public embedding entry
point must support another project without Gateway, while the optional Gateway
adapter retains its ready-only checks. See the [source audit and acceptance
criteria](https://github.com/bigbertharig/benchmarking/blob/master/reports/STANDALONE_ISOLATION_AUDIT_2026-11-24.md).
