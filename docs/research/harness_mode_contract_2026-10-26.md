# Harness mode: prepared resources, agent-owned work

Date: 2026-10-26
Status: design direction; the gateway ready-roster API and harness reader are implemented, but no candidate is integrated.

## Requirement

Gateway and rig orchestration prepare the model resources before the harness uses them. They choose and load models, configure and validate the largest context window they can safely serve for the selected setup, and keep responsibility for llama-server, placement, leases, hardware health, and load/unload lifecycle. The harness receives the resulting resource envelope and does not load, unload, resize, or place models.

The harness owns the AI work inside that envelope: agent and tool loops, conversation sessions, context selection and compaction, tool permissions and other guardrails, delegation among offered models, result verification, and agent-level recovery. It may choose from the models it was offered, but must treat those models and their limits as supplied resources.

"Context" has two owners:

- **Server context window:** gateway/orchestration configure the actual model runtime window and advertise the validated usable limit. "Maximum" means the largest safe, supported fit for that setup, not an unconditional claim that the model's trained maximum fits or works well.
- **Conversation context:** the harness decides which messages, tool results, summaries, and instructions occupy that window. It counts or estimates tokens, reserves output headroom, and compacts before exceeding the advertised limit. It responds to a `context_length_exceeded` error by recovering within the same resource envelope.

## Integration contract to establish

1. A prepared roster identifies the allowed model/profile IDs, actual context window, output limit, tool-call format/capability, and current availability. The harness verifies the served model identity before relying on a route.
2. Harness model requests use the gateway's stable inference API. The gateway and rig remain responsible for routing, execution, health, and hardware failure reporting.
3. Harness mode must not silently trigger a cold load. Candidate adapters send `X-Require-Ready: true` on every gateway completion and tokenizer request; the gateway returns 409 `model_not_ready` for a cold route. Calls without that header keep the existing cold-load behavior.
4. A changed or unavailable roster is reported to the harness. The harness may pause, fail, or choose another already offered model under its task policy; it does not repair hardware or reload models itself.
5. The same resource contract should work with an unmodified external harness and a later custom harness. Candidate comparison should test this boundary rather than require each harness to understand the rig.

For subagent creation, the harness may request an `agent_type` from the manager through the separate `agent-routes/resolve` API. The manager may load a cold published profile, then returns a ready route or a bounded failure within five minutes. The harness waits for that result and runs the child only on the returned route; the model-facing tool never names GPUs or model IDs. This explicit preparation request is distinct from an inference call: `X-Require-Ready: true` still prevents accidental cold loads during child work. See the gateway manager contract and `tools/gateway_subagent_mcp.py`.

The roster is a runtime offer, not another model registry. Benchmarking remains the source of tested
model settings and evidence. The gateway imports that knowledge and, together with orchestration,
prepares the model routes. A read-only roster response should identify each allowed gateway route,
its underlying benchmark model and profile, current readiness, actual served context and output cap,
tokenizer route when available, and supported tool-call format when known. The first API version returns only ready
routes; cold advertised models remain visible through `/v1/models`. The gateway returns `null` for
output limit and tool-call format until verified metadata exists, so the harness must set a conservative
task output ceiling and test tool behavior rather than assume either capability. The harness may choose only among ready allowed routes; it never calls
model-management endpoints. If the roster changes mid-session, the harness pauses or chooses another already offered
route under its task policy.

The ready roster may report a null tokenizer_path. The current Strata route has no
gateway /tokenize endpoint. A harness must accept that route as ready, use a
validated model-compatible local tokenizer or a conservative token estimate,
reserve output space, and verify actual usage and finish reasons. It must not
treat null as a URL or assume a llama tokenizer describes Strata's accounting.
See the [Strata integration note](strata_harness_integration_2026-11-03.md).

## Research implications

Compare candidate harnesses on tool reliability with local models, context accounting and compaction, guardrails, session durability, delegation within a fixed roster, API compatibility, and how much rig-specific code they would require. Keep model loading and hardware controls out of candidate-specific integrations.

This direction supersedes the earlier proposed harness-side benchmarking importer. The harness adapter
translates the prepared gateway roster into candidate-specific configuration, without deciding
placement or creating capacity. Benchmark model IDs in a test manifest must be matched to gateway
route IDs and served identities during preflight.
