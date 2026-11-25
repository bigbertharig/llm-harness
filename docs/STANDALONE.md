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

`harness-workspace-read --root PROJECT` and `harness-workspace-git --root PROJECT` expose
independent stdio MCP tools. External coding engines can use them without the Harness loop.
Other installed scripts resolve through `llm_harness.tools.script(name)`; no sibling source
checkout is needed. Search is a separate optional package from `mcp_servers/rig_search`.

## Optional run service

`harness-service --config service.json --state PRIVATE_DIRECTORY` binds loopback port 8091.
Set `HARNESS_SERVICE_TOKEN` in its environment. The configuration owns `gateway`, `route`,
`expected_model`, `provider`, `workspace_root`, `allowed_profiles` and `tool_servers`.
Client submissions cannot override provider credentials, workspace roots or tool commands.

The `harness-control/1` API supports `POST /v1/runs`, `GET /v1/runs/ID`,
`GET /v1/runs/ID/events?after=N`, and `POST /v1/runs/ID/{input,cancel,resume}`.
Every POST carries `schema`; submission and input also carry a unique `request_id`.
Submission includes `prompt`, optional `agent_type`, `tool_profile`, `max_tokens`,
`timeout_s`, and `max_tool_calls`. Input includes `mode` (`steer` or `queue`) and `content`.
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
