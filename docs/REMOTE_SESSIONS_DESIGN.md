# Durable sessions and remote attachment (design)

Status: research and evolving design only, 2026-11-06. No implementation or deployment authorized by this document. Owning repo: `llm-harness`. Companion: `llm-gateway/docs/REMOTE_SESSION_ACCESS_DESIGN.md`.

## Goal and ownership

One operator can start an agent session on the Pi, leave it running, reconnect from a local browser or phone, read its progress, and continue the same conversation. The session must survive a disconnected client and, after recovery, a harness process restart. The harness owns the instructions, context, tool loop, delegation, approvals, and durable conversation record. The gateway owns the authenticated network front door and relays session requests and events. The manager owns model preparation, leases, placement, and readiness. The rig runs models; it never hosts the session UI.

This extends the existing `README.md` and `docs/research/harness_mode_contract_2026-10-26.md` boundaries. It does not depend on a public network endpoint. First test on the Pi and local network; private access from elsewhere is a later gateway/network milestone.

The Pi's host ingress firewall and key-only SSH were deployed on 2026-11-13, but Tailscale remains disabled and unauthenticated. The future harness session service must bind only to loopback or a private Unix socket. Tailscale Serve should expose a narrow gateway session front door after restrictive tailnet grants are tested; it must not expose the administrative dashboard, manager API, or harness backend. The host firewall drops forwarding, so the rig does not become a tailnet subnet route. A Codex command sandbox does not enforce network policy for host-side MCP processes: each harness tool needs its own server-side capability check and destination policy before remote general-agent work is enabled. See the gateway companion design for the current host rule and activation gate.

## Session behavior

- Give each session a stable opaque ID, creation time, owner (one operator initially), selected offered route/role, state, and monotonic event sequence. Persist messages, tool calls/results, approvals, compaction checkpoints, child session links, and terminal outcome in an append-only record. Keep credentials and raw secrets out of records and event payloads.
- A request to submit a user message gets an idempotency key. The harness accepts it once, queues it behind the active turn, and returns the assigned event/turn ID. Reconnecting or retrying the HTTP request must not create a duplicate turn.
- Stream committed events with sequence numbers. A client reconnects with `after=<last_sequence>` and receives the gap before live events. A disconnected browser is never the owner of the running turn. Multiple viewers may read; initially only one active writer/approval actor is allowed per session.
- Model calls continue through the gateway inference API. For a prepared session route, use `X-Require-Ready: true`; a cold or vanished route pauses the turn and reports a clear state. The harness must not place or load GPUs implicitly. If an explicit role request is needed, ask the manager through its published preparation API and wait for ready/failure under the existing five-minute bound.
- The model-facing child request stays small: `agent_type` (`coding` or `research`) plus task. The controller builds the child prompt, calls `agent-routes/resolve`, waits for ready, starts a child session, records its receipt, and gives the parent a bounded result. Do not expose GPU or model selection to the model. Keep candidate upstream repos unchanged; each controller adapts to this common service.
- Support `pause`, `resume`, and `cancel` at the session/turn level with explicit acknowledgments. Cancel must stop agent work and any owned tool process or model stream when possible; it must not unload unrelated model leases or cancel another controller's claim. A client disconnect alone never cancels work.
- Tool calls have names, validated schemas, budgets, timeouts, and idempotency rules. A pending approval is a durable state with a short, unambiguous action summary. A resumed process must not repeat a side-effecting call simply because its final event was not delivered.
- Use the existing general tool bridge/help discovery where required; keep native and bridged calls distinguishable in receipts. Do not add model-specific fixes to the shared session service.

## Proposed harness API to the gateway

These are candidate shapes, not implemented endpoints. Version and transport should be settled in an integration test before coding.

| Operation | Proposed shape | Required behavior |
|---|---|---|
| Create/list/get | `POST /sessions`, `GET /sessions`, `GET /sessions/{id}` | Stable ID, state, route/role, last event sequence; pagination |
| Send message | `POST /sessions/{id}/messages` | Idempotency key, turn ID, queued/running state |
| Attach | `GET /sessions/{id}/events?after=N` | Replay from durable sequence, then stream; bounded backlog |
| Approve/deny | `POST /sessions/{id}/approvals/{id}` | Idempotent decision with actor and timestamp |
| Pause/resume/cancel | `POST /sessions/{id}/{action}` | Scoped to session; explicit terminal acknowledgment |

The gateway authenticates and authorizes the request, then forwards an asserted operator identity over a local trusted channel. The harness must reject direct untrusted callers or verify the gateway's assertion. Avoid duplicating conversation state in the gateway. A simple local HTTP service plus server-sent events is a starting candidate; compare against WebSocket only if bidirectional streaming requirements justify it.

## Resource and reconnect policy

The session lifetime is separate from a model lease and from a phone connection. Keep the transcript and tool receipts even when the selected model unloads. On the next turn, check the ready roster and either wait for an explicit preparation request or present a recoverable unavailable state. Do not pin a large model indefinitely just because a phone tab remains open. Set an inactivity policy for cache/lease retention after measuring prompt reload cost; distinguish this from deleting a session. Child preparation has its own five-minute deadline; parent turn timeout and tool budgets need separate values.

Remote attachment must not depend on the client retaining all text. The UI can reconstruct a session from the snapshot and event log. Record the served route, model identity, context window, compaction revision, controller revision, and tools available per turn so a resumed turn is auditable. If the original model is gone, a route change requires explicit policy and an event in the log.

## Delegation to a shared model pool

The model-facing request remains small: agent_type and task, with an optional explicit model preference when the user or task requires one. The harness creates a separate child session and calls the manager with the parent route, capability, context requirement, and concurrency budget. It does not decide whether a child reuses the parent's loaded model, shares another ready model, gets a duplicate instance of that model, or uses a different model on free GPUs. The manager returns an admitted ready route or a typed queued, busy, failed-load, or timeout result. Only then does the harness start the child turn. Keep the child transcript, tool authority, context, and result receipt separate even when the serving endpoint is shared.

The existing gateway resolver is deliberately disjoint-GPU and current registered runtimes use one parallel slot. Sharing one model server among multiple agents is therefore a research path, not an enabled feature. The manager must measure and enforce active slots, per-slot context/KV memory, queuing, cancellation, fairness, and throughput. It may instead load a second instance on disjoint GPUs, or a different eligible model. The harness should expose no GPU mechanics to the model and should never treat a second child as permission to evict an active profile.

Tests: direct two-request shared-server baseline, then one parent and two children with independent prompts and tool receipts; compare serial versus concurrent throughput and token/context accounting. Include saturation, cancellation, a failed child, a cold duplicate instance, a busy rig, and a manager restart. Run the same simple delegation task through all six controller adapters and several model sizes once manager admission is stable. Record whether children shared an instance or used separate instances; do not merge those results.

## Machine inspection and coding tools

The basic gateway Chat tab is text completion today. In a live Qwen chat, the user asked whether it could read information about the Pi; the model said it could not access hardware, logs, IP address, or internal configuration. That is the expected limitation of a text-only route, not evidence that the Pi is inaccessible. Add a harness tool bundle for explicit, scoped tasks: inspect permitted machine status, list/read files under allowed roots, search content, inspect Git state, and propose or apply bounded edits. The harness should give the model a clear tool manifest and usage help, enforce roots and budgets outside the prompt, record each call/result, and report unavailable or denied capabilities accurately. Shell execution and edits need distinct grants; a generic machine-information request should not imply either. Test read-only inspection first, then a coding task in a disposable worktree with diff review, blocked paths, and a restart/reconnect. Compare multiple harness controllers and model sizes with the same fixture. Keep the raw upstream harness repos unchanged.

## Milestones and tests

Order of work: finish the underlying harness session/tool/delegation design and tests first; then prove a local Pi/browser session; then test access from another device on the same home network; only after those phases and their security reviews consider access from outside the home. The last two phases are deliberately deferred. This document records options and test gates, not a committed implementation plan.

1. Local Pi harness service: one session, two turns, streamed events, a tool call, reconnect after client disconnect. Check exact event order and no duplicate turns on retry.
2. Restart recovery: stop the harness between events and resume from the durable log. Verify no duplicated side effects, lost approvals, or repeated child launches.
3. Gateway relay on loopback, then local-network phone/browser test: resume, send message, inspect tool progress, approve/deny, cancel. Check that the existing rig-control dashboard is not part of the session surface.
4. Cold/failed model, five-minute child-load timeout, ready roster change, gateway/rig outage, and bounded event backlog. Verify the UI shows a recoverable state rather than silently losing the turn.
5. Same fixed session task through all six candidate controllers and more than one model size. Keep upstream checkouts untouched; record native versus bridged tool calls, latency, failures, and controller revision.
6. Private away-from-home networking and authentication are gateway work. Repeat the same session tests over that path, including a lost phone and revoked device, before enabling it for daily use.

## Open questions

- Which session store fits the Pi's disk and backup/recovery needs: JSONL with periodic snapshots or SQLite with an append-only events table? Define corruption recovery and retention before implementation.
- What is the exact trust mechanism between gateway and harness, and can the harness service remain loopback-only? How are per-session write and approval permissions represented with one operator now and possible multiple clients later?
- Which operations can be safely replayed after a crash? Define tool-specific idempotency and a manual reconciliation state for uncertain side effects.
- Should an idle session request a cold load automatically on a new user turn, or require an explicit prepare action? Keep this separate from the existing `X-Require-Ready` inference rule.
- What is the maximum event size, backlog, attachment size, and log retention? How are sensitive tool outputs redacted without breaking an audit trail?
- What should happen when two devices submit messages or approval decisions at nearly the same time? Establish queue and conflict behavior in deterministic tests.
- What prompt template for delegated agents improves real outcomes? Study prior agent prompts with provenance and fixed tasks, then change harness-owned templates only after controlled comparisons.

## Channel-neutral work on the go (proposal, 2026-11-06)

A harness session and its work items must be independent of how the operator contacted it. The Pi browser, a later Tailscale connection, Gmail, WhatsApp, and other channels can all attach to the same durable session. A channel adapter supplies authenticated source identity, source event ID, text and attachment references, reply capability, and channel limits. The harness owns intent interpretation, context, tool policy, execution, approvals, and progress events. A request can be a chat turn, a long-running task, or a scheduled task; the client connection and the model turn do not have to remain open while work runs.

The model-facing work request is a simple goal plus bounded constraints. The harness deterministically creates a work ID, records the source channel/message, chooses an allowed executor, tracks state, and produces an artifact manifest and terminal receipt. An executor can be the harness's own tools and child agents, the orchestration plan runner, or a later service. Orchestration is not a mandatory path for work requests. GPU selection remains with the manager whenever models are needed. Existing candidate upstream repos stay unchanged behind controller adapters.

| Common operation | Harness responsibility |
|---|---|
| `submit_work(goal, constraints, source_ref, idempotency_key)` | Validate policy and budget, create one durable work item, acknowledge with work ID, then run or queue it |
| `get_work` / `events(after=N)` | Return current state and ordered progress events for any authorized channel to render |
| `clarify(work_id, question)` | Record a question and pause dependent steps until an authorized reply arrives, without discarding work |
| `approve(work_id, action_id, decision)` | Apply a scoped decision once; channel identity alone does not bypass approval policy |
| `publish_result(work_id, artifact_id, destination_role)` | Request gateway delivery of an admitted artifact; keep the local receipt canonical |

Channels receive the same state vocabulary: `received`, `accepted`, `queued`, `running`, `needs_input`, `report_validated`, `delivery_pending`, `delivered`, `failed`, and `cancelled`. The harness emits events once; the gateway chooses which changes merit a short email/WhatsApp notification or a richer browser view. An outbound message does not imply that every reply is an authorized command. The harness records each external delivery ID so retries after crashes do not duplicate a send or re-run work.

Google integration is one provider of channel and tool capabilities. The gateway owns OAuth and exposes typed mail/Drive operations with policy-bound recipients, folder aliases, and idempotency keys. The harness never sees refresh tokens or calls Google from a candidate controller. An optional `search_mail` or `read_drive_file` tool requires an explicit grant; fetched content is task data, not an instruction source. The dedicated automation account remains separate from the operator's primary account. WhatsApp can later implement the same event/command contract without changing the work engine.

The GitHub analyzer is one useful acceptance case: receive "analyze this repository," acknowledge a work ID, perform bounded analysis through an appropriate executor, and deliver a quality-gated report an hour later. The current orchestration analyzer has a claimed-behavior focus, so a general analysis mode and URL-only path need validation before using it for that case. Other first-class cases should include research, a coding task, a local data task, a scheduled digest, and a task that asks for clarification or approval midway.

Tests: submit the same work from browser and mocked email; duplicate delivery and restart create one work item; progress can be read from another channel; an authorized clarification resumes the existing item; a spoofed or unauthorized reply cannot approve; delivery failure retries without rerunning the task; one task executes in the harness and one through orchestration; a second model/controller consumes the same structured event. Keep no-op, rejection, and failed-delivery receipts.

## Inbound trust and tool authority (security design)

An inbound message is untrusted data even when it appears to come from an allowed account. The harness must not infer authority from its wording, a model's interpretation, a retrieved page, or a repository file. Every work item carries a server-issued capability envelope: authenticated actor, source channel, permitted workflow/tool IDs, permitted resource scopes, budgets, expiry, and required approval level. The model may propose an action; deterministic code checks the envelope again immediately before execution. Prompt instructions and injection classifiers can improve behavior, but cannot grant or enforce permission. [OWASP prompt injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/), [excessive agency](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/).

| Capability class | Example | Default from ordinary inbound email |
|---|---|---|
| Observe | Read the sender's work status and approved result | Allowed only for the linked work ID |
| Bounded workflow | Start a registered, read-only analysis with typed inputs and resource limits | Possible after exact validation and explicit policy |
| General agent work | Research or coding with tools, file access, or outbound network | Queue as a proposal; require stronger authenticated session and scoped approval |
| Privileged control | Shell, package install, repository write/push, credential access, GPU override, arbitrary recipient upload | Never granted by email text; separate operator/admin path |

The harness should expose a fixed workflow catalog with typed input schemas and an explicit tool manifest for each run. A remote request cannot create a new workflow definition or expand its tools. External material is marked as source data; a tool result or repo instruction cannot become a system instruction, approve an action, change destination roles, or request a different executor. For a risky proposed action, record the exact action and resources, pause the work, and ask the operator through an independently authenticated UI. The model cannot approve its own proposal, and a reply to an email is not an approval token.

Security tests must inject hostile instructions into email bodies, attachments, web results, repository docs, tool output, and Drive files. Verify that none can broaden tool grants, read unrelated files, change the delivery recipient, call the manager directly, or trigger an unapproved shell command. Test replay, duplicate messages, forged sender display names, stale approvals, and attempts to hide high-impact actions in a benign workflow. Keep denial receipts and a visible reason for the operator.

## Public code, private runtime state

This public repo can define capability schemas, permission checks, rejection behavior, threat models, and synthetic test fixtures. The actual actor IDs, tool grants, session-signing material, account identifiers, approvals, and work contents belong in private runtime state or a private deployment policy, not in the repo. A candidate controller receives only the allowed tools and an opaque work/session ID; it must never receive Google refresh tokens, SSH keys, encrypted-key material, or a dump of the private policy. A model-facing error should state the denied action and a safe reason without disclosing credentials or hidden policy details.

The harness should authorize every tool invocation from the current server-side capability envelope, not merely from a prompt or a cached model-visible tool list. Persist policy version and decision IDs in receipts so a later audit can explain why an action was allowed while leaving secret values out. On policy change or key rotation, already queued work must be rechecked before its next side effect. Include tests that public example configuration cannot grant real privileges and that log/trace redaction survives failed calls.

## Related work

`docs/research/subagent_delegation_matrix_2026-11-04.md` documents the manager-ready child route and prompt research. `docs/research/async_tool_completion_contract_2026-10-27.md` covers durable tool completion. `docs/research/model_harness_context_matrix_2026-11-05.md` records current six-harness and model-size comparisons.
