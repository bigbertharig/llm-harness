# Standalone Harness

Active source interface, validated with a local fake provider. No cloud account is required
for the deterministic installation check. Install this repository with `python -m pip install .`.
This package currently targets POSIX hosts; its file locks use `fcntl`.

`harness-run` runs the bounded engine. For a direct OpenAI-compatible provider, supply
`--gateway https://provider.example` and `--provider-config provider.json`, alongside
`--route`, `--model`, `--agent-type coding`, `--out receipt.json` and the task prompt.
The base URL precedes `/v1/chat/completions`. Direct configuration declares:

```json
{"schema":"harness-direct-provider/1","route":"user-route","model":"user-model",
 "context_length":8192,"output_limit":1024,"api_key_env":"HARNESS_PROVIDER_API_KEY"}
```

Capabilities are caller declarations, not measured context evidence. Direct mode makes no
rig request and sends no ready-only header. Omitting `--provider-config` selects the Gateway
adapter, which checks the published ready roster and sends `X-Require-Ready: true`.
Neither adapter injects sampler settings. Receipts distinguish provider defaults from runtime
profiles, requested identity from reported identity, and cancellation from successful completion.

Python callers can create the same durable run boundary with
`llm_harness.engine.embedded_run_api(state_dir, endpoint=..., route=..., model=...,
provider=..., tool_servers=..., workspace_root=...)`. The caller supplies the provider,
reviewed tool servers, and project root; a run may request only a configured tool profile.
The project root enables workspace tools without a Gateway checkout. The in-process
adapter is trusted code and is not an isolation boundary for an untrusted engine.

`--tool-profile workspace_coding --workspace-root PROJECT` enables workspace-bound
read, versioned text replacement/file creation and named checks in standalone
`harness-run`. Pass `--checks-file checks.json` to expose checks whose values are
argument arrays, for example `{"pytest":["python","-m","pytest","-q"]}`.
The model chooses a configured check name, not a shell command. Named checks
do not inherit service credentials. Existing `workspace_read` remains read-only.

Optional `--tool-selector jev` uses TypeSafe's hosted API (`TYPESAFE_API_KEY`)
to narrow advertised tools; the default remains model selection. This needs
internet, so offline use would require a future local decision-model adapter.

The `workspace_coding` profile also exposes Git status and diff. Guarded edits use
`sha256` from a workspace read. A named check should run after the final edit; the run
receipt reports `verification.status` (`passed`, `failed`, `not_checked`, or
`stale_after_write`) so a check performed before the last edit is not mistaken for
final-state validation.

`harness-workspace-read --root PROJECT` and `harness-workspace-git --root PROJECT` expose
independent stdio MCP tools. External coding engines can use them without the Harness loop.
Other installed scripts resolve through `llm_harness.tools.script(name)`; no sibling source
checkout is needed. Search is a separate optional package from `mcp_servers/rig_search`.

## Optional run service

`harness-service --config service.json --state PRIVATE_DIRECTORY` binds loopback port 8091.

For Gateway's local Coding dropdown, the service configuration can omit a fixed
`route`/`expected_model` and set `"allow_ready_routes": true`. Each submitted run
then selects one ready route/model pair, checked against Gateway's ready roster. Add
`"allowed_workspace_roots": ["/absolute/project/path"]` and
`"workspace_coding": {"checks_file": "/absolute/checks.json"}` to grant coding
tools for those exact selected workspaces. The checks file is optional; omitting it
allows guarded edits and reads without command execution. The service token
authorizes submissions, while the configured root list and tool profile bound their
effects. A fixed-route service retains the prior behavior when the flag is absent.

For example, a service that can run any currently ready local model in one project:

```json
{
  "gateway": "http://127.0.0.1:8080",
  "allow_ready_routes": true,
  "allowed_workspace_roots": ["/srv/projects/example"],
  "allowed_profiles": ["none"],
  "workspace_coding": {"checks_file": "/srv/harness/checks.json"}
}
```

Set `LLM_GATEWAY_API_KEY` in the Harness service environment if Gateway requires a
bearer key. Keep `HARNESS_SERVICE_TOKEN` in that environment as well. Gateway must
point `HARNESS_SERVICE_URL` at this service and use the same service token.
The service configuration owns provider credentials and tool commands. With
`allow_ready_routes`, a submission selects only a roster-validated ready route/model;
with `allowed_workspace_roots`, it selects only a configured workspace.

A Coding run may send `parent_run_id` to continue a successful run in the same
conversation and workspace. Harness stores the link and reconstructs completed user/assistant exchanges
for each new model request; each run keeps its own durable receipt. A submitted run
may set `context_policy` to `conversation` for ongoing main chats or `agent`
(the default) for bounded task agents. Conversation policy starts compaction at
roughly 80% of the selected model context; agent policy waits until roughly 90%
but can still compact and continue a long task. Both retain recent complete
exchanges and summarize older history on the same selected route. The original
run records stay intact, while a committed summary and retained tail are saved
in the new run receipt and reconstructed after restart. Truncated or non-shrinking
summaries are refused. A single oversized current request with no older turns
cannot be repaired by compaction. Context costs currently use a conservative
text estimate rather than exact tokenization.

The `harness-control/1` API supports `POST /v1/runs`, `GET /v1/runs/ID`,
`GET /v1/runs/ID/events?after=N`, and `POST /v1/runs/ID/{input,cancel,resume}`.
Every POST carries `schema`; submission and input also carry a unique `request_id`.
Submission includes `prompt`, optional `agent_type`, `tool_profile`, `max_tokens`,
`timeout_s`, `max_tool_calls`, caller-owned `conversation_id`, and, when enabled,
`route`, `expected_model` and `workspace_root`. Input includes `mode` (`steer` or `queue`) and `content`.
Steers enter at model boundaries; queued messages enter after a tool-free turn completes,
within the original run budget. Inputs left unapplied are visible in `pending_inputs`.

Repeated identical request IDs return the durable result. Changed arguments under the same
ID are refused. Events retain `harness-event/v1`, stable run IDs and contiguous sequences.
Cancellation becomes effective at the next bounded provider/tool boundary; it does not claim
to undo an already dispatched operation. Resume starts a queued run or returns a terminal run.
After a service restart, active runs require reconciliation; they are never automatically
replayed. This release does not reconstruct and continue an interrupted model/tool stack.
The existing journal/recovery API remains the reconciliation surface for exact operation receipts.

The restart MCP tool calls Gateway's authenticated `gateway-reset/1` API. It has no database,
service-control or private Gateway-path dependency. Configure `LLM_GATEWAY_URL` and
`LLM_GATEWAY_API_KEY`; explicit confirmation is required by the operation owner as well.

## Validation

Use the registered `agent_runtime`, `local_tools`, `catalog_routing`, `github_public`,
`google_workspace`, `rig_search` and `test_infrastructure` suites. For an isolated install,
build a wheel and run `tools/verify_install.py --wheel FILE --receipt OUTPUT`.
It installs declared dependencies in a fresh virtual environment and HOME, runs a real tool
in an external project through a fake HTTP provider, and discovers installed MCP tools.
Search comparison runners moved to Benchmarking; historical research receipts and their frozen
query set remain here. Native provider sessions retain their provider-owned session behavior.

Reviewed MCP schemas are frozen in the Harness artifact with normalized SHA-256 digests.
Gateway's MCP dispatcher checks the discovered input schema against the imported digest before advertising a
tool. Unknown or changed schemas fail closed until the producer snapshot is reviewed and
imported again. Both artifact importers validate the digest before replacing their last valid
snapshot. Legacy name-only artifacts can be read for migration, but cannot authorize live
Gateway tool dispatch without a schema digest. Harness checks all ten owned MCP surfaces
using discovery-only requests (`tools/mcp_schema_snapshot.py check`).
