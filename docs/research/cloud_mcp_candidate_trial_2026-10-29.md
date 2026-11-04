# Cloud MCP candidate trial

Date: 2026-10-29
Status: exploratory, same ready model and tasks for two candidates; no final harness ranking.
Receipts: ignored `results/cloud_mcp_2026-10-29/` (bridged) and `results/cloud_mcp_direct_2026-10-29/` (direct HTTPS) on the Pi.

## Scope and network path

This follows the [local MCP trial](local_mcp_candidate_trial_2026-10-29.md). The first cloud run used a temporary Windows loopback bridge and SSH reverse tunnel. At the time, ordinary Pi HTTPS reported `Network is unreachable`; that was misdiagnosed as lack of Internet connectivity. The Pi was connected to the Internet-capable Pretty Fly Wi-Fi, but `eth0` advertised a lower-metric default route through the rig LAN at `10.0.0.1`. An explicit `curl --interface wlan0` returned HTTP 200 while `--interface eth0` failed. The bridge and tunnel were stopped after the first run.

The Pi's NetworkManager `home-ethernet` profile was changed to `ipv4.never-default=yes` and reapplied without disconnecting Ethernet. The default route then selected Pretty Fly via `192.168.50.1`; the `10.0.0.0/24` Ethernet route and ping to `10.0.0.1` still worked. Direct HTTPS and MCP tool discovery returned HTTP 200 for DaedalMap, DeepWiki, and OpenAI Docs. The second run used their HTTPS URLs directly from the Pi. Neither run used authentication; OAuth remains untested. All target tools were read-only.

The same ready route, `gpu-rig/coder-30b` (Qwen3 Coder 30B, 32,768 context), served both candidates with `X-Require-Ready: true` and a 1,536 output-token ceiling. Nanobot's before/after ready roster was unchanged. The candidate tool surfaces differed: Nanobot's model-facing registry was narrowed to the three target MCP tools; DeepSeek's standard headless profile retained other tools. Compare the three task outcomes, not overall harness quality or retry efficiency, as if they were a frozen benchmark.

## Direct server baseline

The first run's `baseline.json` records an anonymous HTTP 200 `initialize`, `tools/list`, and one `tools/call` per server from the workstation. Direct Pi `tools/list` later returned HTTP 200 with the same tool counts:

| Server | Endpoint | Tool list | Call and result envelope |
|---|---|---:|---|
| DaedalMap free | `https://app.daedalmap.com/mcp/free` | 11 | `get_catalog(catalog=geometry)` returned `structuredContent` with first `family_id: administrative`; `content` was empty |
| DeepWiki | `https://mcp.deepwiki.com/mcp` | 3 | `read_wiki_structure(repoName=modelcontextprotocol/servers)` returned text and structured content |
| OpenAI Docs | `https://developers.openai.com/mcp` | 5 | `search_openai_docs(query="Responses API streaming", limit=1)` returned text with first hit `https://developers.openai.com/api/docs/guides/streaming-responses` |

DaedalMap's structured-only discovery output is an intentional project choice documented in `county-map-private/docs/API/mcp_contract_closure_audit_2026-10-15.md`. The [MCP 2025-06-18 tool result specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools#structured-content) recommends (`SHOULD`) mirroring structured JSON in a text block for backward compatibility, but does not make that a requirement. This test exposes an interoperability gap between that server choice and these two clients; it does not prove that either side violated a mandatory protocol rule.

## Live harness results

| Candidate | DaedalMap structured-only catalog | DeepWiki text result | OpenAI Docs text result | Result |
|---|---|---|---|---|
| Nanobot 0.3.5 | Called three times; model saw no output and could not name `administrative` | One call; grounded top-level heading | One call; exact first-hit URL | 2/3 task answers passed |
| DeepSeek Harness 0.2.1-rc.2 | First `get_catalog` call completed but the model-visible result said no content; it retried and later hit DaedalMap burst limits; final answer was not grounded in the catalog | One call; grounded top-level heading | One call; exact first-hit URL | 2/3 task answers passed |

Nanobot's `nanobot/summary.json`, `registered_tools.json`, and roster files are the primary receipts. DeepSeek's `deepseek/{daedalmap,deepwiki,openai_docs}.jsonl` and `status.txt` capture calls, tool results, final answers, and process exit codes. DeepSeek's DaedalMap process exited 0 despite a failed task answer. Its extra `get_tool_help`/resource calls and `curl` attempt occurred after the initial empty catalog result; the burst limit also reflects cumulative requests during this trial, so it is not a standalone harness reliability score.

The earlier DeepSeek [public DeepWiki probe](first_candidate_trial_2026-10-28.md) passed. This round adds two more public providers and a same-model Nanobot comparison. OpenCode and Pi were not rerun for cloud tool-use because their local trial CLI sessions stalled before inference even without MCP; their cloud behavior remains unknown. Authentication, OAuth, SSE-only servers, multimodal content, retries after a deliberate outage, and permissions remain untested.

## Direct Pi HTTPS rerun after route correction

Both candidates were rerun with isolated configs using the three public HTTPS URLs, the same ready model, and the same prompts. This removes the bridge as a limitation for these three tasks.

| Candidate | DaedalMap | DeepWiki | OpenAI Docs | Direct result |
|---|---|---|---|---|
| Nanobot 0.3.5 | Three `get_catalog` calls; model still saw no catalog data and could not name `administrative` | Grounded heading | Exact first-hit URL | 2/3 answers passed; ready roster unchanged |
| DeepSeek Harness 0.2.1-rc.2 | Two `get_catalog` calls surfaced no model-visible content. The model then found and read `daedalmap://catalog` as an MCP resource; after that large response, the final event was only `Based`, turn reason `max-tokens`, process exit 1 | Grounded heading | Exact first-hit URL | 2/3 answers passed; catalog task failed despite resource fallback |

The direct receipts are `results/cloud_mcp_direct_2026-10-29/nanobot/summary.json`, `registered_tools.json`, `ready_before.json`, `ready_after.json`, and `results/cloud_mcp_direct_2026-10-29/deepseek/{daedalmap,deepwiki,openai_docs}.jsonl` plus `status.txt`. DeepSeek's resource fallback demonstrates a separate large-result/budget failure mode; it does not repair the missing model-visible `get_catalog` result. The direct rerun does not test OAuth or general Internet reliability across time.

## Next gate

Preserve two response classes in the shared fixture: text-bearing results and structured-only results. Score `initialize`, discovery, actual tool call, model-visible payload, grounded final answer, retry behavior, and permissions separately. For DaedalMap interoperability, either mirror structured discovery JSON in a text block at the server or normalize `structuredContent` into model-visible text in the harness adapter, then repeat the exact catalog call. The server-side change would need its own payload-size and contract review.
