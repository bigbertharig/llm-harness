# Harness engine adapters

Status: **Partial implementation**. The public in-process adapter and Gateway-free
direct-provider run factory are active; remote engine substitution and the full conformance
set below remain planned. Active loop journals, receipts and MCP adapters are documented
in [the framework](HARNESS_FRAMEWORK.md).

The project-owned Harness is the default model-use engine. The engine contract allows a site to add
another harness without coupling Gateway to that implementation or transferring tool, policy, or
hardware authority. The in-process `project_agent.py` adapter and a fake alternate engine now exercise
version rejection, provider identity, grants, cancellation, ordered events and terminal
receipts. Broader conformance below remains required before remote substitution. The current
in-process alternate engine runs in the trusted Harness process and receives the existing
run API's journal context; it is not yet an isolation boundary for untrusted engine code.

## Boundary

The embedding caller supplies the objective, provider/model selection, effective grants and
permission authority. Gateway supplies these for its conversations and owns authenticated operator
actions, account connectors and conversation history. Standalone callers supply their own
configuration. Orchestration owns local runtime admission and hardware state. The Harness
boundary owns provenance, tool validation and execution, budgets, ordered events, recovery semantics,
and terminal receipts. An engine decides how to reason within that envelope.

```text
Gateway or standalone embedding caller
  task envelope + explicit provider capabilities + effective grants
      -> Harness engine adapter
         engine reasoning <-> canonical model/provider adapter
         tool proposals ----> project-owned broker and approval checks
      <- ordered events + terminal receipt
```

An engine never receives raw credentials, a hardware-control handle, authority to load a model, or the
ability to add tools to its grant. Uploaded files, repository text, web pages, messages, and tool output
remain typed untrusted evidence. Instructions found in them cannot replace the operator objective or
change policy.

## Public run and tool interfaces

Harness owns the public run contract. Gateway is a consumer and may expose an authenticated
proxy for its clients. Submission, additional input, cancellation and reconnect/resume use
stable run, attempt and request identities. Duplicate submissions reconcile to the existing
attempt; an interrupted write never becomes a blind retry. Events carry sequence/causal IDs;
resume uses a validated cursor/checkpoint. Each attempt has one terminal receipt. New input
and cancellation acknowledgements must distinguish accepted, pending and terminal state.

Harness inference adapters support configured providers. The Gateway adapter retains
ready-roster identity validation and ready-only calls. Direct providers supply explicit
identity, context/output limits and capabilities without rig discovery. Missing capabilities
produce a typed unsupported outcome. Model credentials stay in the provider/connector.

MCP tools can run independently of the Harness engine. A tool calls the owning service's
public operation for accounts, conversations or hardware; it does not read or mutate that
service's private files. Gateway records approvals in the integrated installation; Harness
checks the call against the grant and the owning service authorizes the effect.

Freeze schemas, version negotiation, authenticated transport, error categories and producer/
consumer fixtures before implementing a remote adapter. The first milestone remains an
in-process adapter and fake engine. This document defines behavior, not new HTTP routes.
See the [product boundary](../README.md#product-boundary) and [implementation status](../README.md#implementation-status).

## Versioned inputs

The launch envelope should contain:

- contract and engine-adapter versions plus run, task and attempt IDs; an explicit
  caller-owned conversation/session reference when the task belongs to one;
- operator objective and system-owned operating rules, kept separate from untrusted evidence;
- provider/model identity, context/output limits and capability facts; route identity and
  observed readiness for the Gateway adapter; optional Benchmarking evidence identity;
- explicit tool/profile grants, approvals, call/byte/turn/time budgets, and cancellation handle;
- journal checkpoint or recovery instruction and digest-bound evidence/artifact references.

The adapter must reject an unknown major version, a missing required identity, a mismatched
provider/model identity, an unready Gateway route, an unsupported recovery state, or a grant it cannot enforce. It may negotiate a narrower feature
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
adapter retains its ready-only checks. See the [implementation status](../README.md#implementation-status).
