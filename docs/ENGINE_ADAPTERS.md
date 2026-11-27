# Harness engine adapters

Status: **Owned Harness active; external compatibility selective**. The public in-process
adapter, Gateway-free direct-provider run factory, ordered events, receipts, and MCP tools
are active. Active layers are documented in [the framework](HARNESS_FRAMEWORK.md).

The project-owned Harness is our maintained model-use engine and gets the strongest
connections to Gateway, Orchestration, Benchmarking, and project tools. The six downloaded
harnesses are research and compatibility candidates, not six supported implementations
of the same internal API. A site can use another harness through the connection points it
already supports, adding a small adapter only for the capabilities it needs. We do not
reshape our agent loop or duplicate its policies to make every candidate interchangeable.
The fake alternate in-process engine exercises our adapter contract; it runs as trusted
Harness code and does not isolate untrusted engines.

## Compatibility levels

1. **Model access:** another harness can use a configured cloud provider or a prepared
   Gateway OpenAI-compatible route. Local loading and placement stay with Orchestration.
   This gives inference access, not Gateway conversation or run-control integration.
2. **Tools:** another harness can consume the standalone MCP servers it supports.
   Each tool-owning service enforces its own authorization; the external harness's tool
   loop, approvals, budgets, and receipts remain its responsibility unless it uses our
   Harness broker. Record native support, thin translation, and unsupported features
   separately.
3. **Gateway-managed work:** a harness that should run behind Gateway's dashboard needs
   a per-harness adapter for the specific run, event, input, cancel, and receipt
   capabilities it claims. Gateway keeps its conversation and approval authority.
   Only this level needs to speak the versioned Harness control contract, directly or
   through a tested translation layer. No candidate is assumed to support it.

## Boundary

For our owned Harness, the embedding caller supplies the objective, provider/model
selection, effective grants and permission authority. Gateway supplies these for its
conversations and owns authenticated operator actions, account connectors and history. Standalone callers supply their own
configuration. Orchestration owns local runtime admission and hardware state. The Harness
boundary owns provenance, tool validation and execution, budgets, ordered events, recovery semantics,
and terminal receipts. An engine decides how to reason within that envelope.

```text
Our Harness path:
Gateway or standalone embedding caller
  task envelope + explicit provider capabilities + effective grants
      -> Harness engine adapter
         engine reasoning <-> canonical model/provider adapter
         tool proposals ----> project-owned broker and approval checks
      <- ordered events + terminal receipt
```

The model-facing task does not carry raw credentials, a hardware-control handle,
authority to load a model, or permission to add tools to its grant. The trusted
in-process engine shares the Harness process and is not a credential isolation boundary.
Uploaded files, repository text, web pages, messages, and tool output remain typed
untrusted evidence. Instructions found in them cannot replace the operator objective or
change policy.

## Public run and tool interfaces

Our Harness owns the `harness-control/1` run contract. Gateway's optional Harness
client consumes it and may expose an authenticated proxy for its clients. An external
harness need not implement this contract for model-only or MCP-only use; a Gateway-managed
external harness needs a tested adapter for the operations it claims. In our run
contract, submission, additional input, cancellation and reconnect/resume use stable
run, attempt and request identities. Duplicate submissions reconcile to the existing
attempt; an interrupted write never becomes a blind retry. Events carry sequence/causal IDs;
resume uses a validated cursor/checkpoint. Each attempt has one terminal receipt. New input
and cancellation acknowledgements must distinguish accepted, pending and terminal state.

Harness inference adapters support configured providers. The Gateway adapter retains
ready-roster identity validation and ready-only calls. Direct providers supply explicit
identity, context/output limits and capabilities without rig discovery. Missing capabilities
produce a typed unsupported outcome. Model credentials stay in the provider/connector.

MCP tools can run independently of the Harness engine. A tool calls the owning service's
public operation for accounts, conversations or hardware; it does not read or mutate that
service's private files. In the integrated owned-Harness path, Gateway records approvals, Harness checks the
call against the grant, and the owning service authorizes the effect. An external
MCP client must supply its own caller-side checks.

Freeze schemas, version negotiation, authenticated transport, error categories and producer/
consumer fixtures for any new Gateway-managed adapter. The in-process adapter and fake engine
are active. Add a remote adapter only for a concrete integration, with its supported
capabilities stated explicitly. This document does not define new HTTP routes.
See the [product boundary](../README.md#product-boundary).

## Versioned inputs

For an engine using our run adapter, the launch envelope should contain:

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

A Gateway-managed adapter emits the canonical ordered events defined by the framework;
model-only and MCP-only integrations may retain their native logs.
Our stream has event types for model boundaries, tool proposals and lifecycle, compaction,
child work, input/cancellation, retry, recovery, and terminal classification. An external
adapter emits only the supported types and reports unsupported capabilities explicitly. Payloads carry sequence
and causal identities so the reducer can reject gaps, duplicates, and illegal transitions.

Our terminal receipt records the engine and contract versions, route/model identity,
effective grants and budgets, evidence and journal references, tool/child receipts,
usage, recovery history, and terminal reason. An external adapter must supply the
fields needed for its claimed capabilities and identify any unavailable evidence. Engine-specific diagnostics may be attached as bounded
artifacts, but they cannot replace canonical fields or turn a failed/incomplete run into success.

## Security invariants for Gateway-managed runs

The following guarantees apply to our Harness and must be demonstrated by any adapter
claiming equivalent Gateway-managed behavior. An external harness using only inference
or standalone MCP tools does not inherit our broker or journal guarantees.

- Tool discovery is not permission. Our broker uses the reviewed registry, normalized schema,
  argument validation, approval binding, budget checks, durable dispatch boundary, and result
  policy. A Gateway-managed external adapter must demonstrate equivalent grant enforcement
  for its claimed tools; it need not duplicate our broker implementation.
- The current trusted in-process engine writes through `RunRecorder`, whose reducer validates
  state transitions; it shares journal access with Harness. A future untrusted remote
  engine would require an adapter that validates and appends events without granting
  direct journal access. Engine prose never determines terminal success.
- External evidence never becomes system instructions. Provenance type, origin, digest, and trust are
  system-owned fields.
- Write retries require an idempotency key bound to normalized arguments or reconciliation proving the
  original action absent. Missing output is not evidence that a write did not occur.
- Secrets remain in connector or broker identities. Engines receive redacted results appropriate to
  the task grant.

## Conformance by claimed capability

Model access needs identity, readiness, context, and no-surprise-load checks for the selected
route. MCP access needs schema, authorization, and result handling checks for each exposed tool.
Neither level promises our run API or requires changes to the external harness's agent loop.

A Gateway-managed adapter must pass producer/consumer fixtures for each operation it exposes:
schema/version rejection, identity and grant checks, event ordering, terminal receipts, and
cancellation or resume if claimed. An adapter must report unsupported capabilities rather
than emulate them silently or call a partial run fully equivalent. Claiming full substitution
additionally requires malformed/duplicate-call, budget, prompt-injection, complete-document,
compaction, transport-failure, uncertain-write/reconciliation, and restart-recovery tests.
Matched live trials can then evaluate quality, latency, and cost separately.

The six archived harnesses remain deletion-safe research inputs. Integrate one only when a
real use case justifies its adapter and maintenance cost. Our owned Harness remains the
default and does not depend on those checkouts.

## Standalone status and next Harness work

The in-process embedding entry point, direct provider, and fake alternate engine pass
Gateway-free identity, version, grant, cancellation, ordered-event, terminal-receipt,
and brokered workspace-tool fixtures. The adapter fixture is part of the named
`agent_runtime` suite.

Next, test the owned Harness and Gateway client together at the run boundary, then
keep improving our broker, budgets, recovery, and provider/tool adapters. For any
specific external harness, record which compatibility level it reaches and add only
the translation that integration needs. Full substitution is an optional later claim,
not a prerequisite for reusing models or tools.
