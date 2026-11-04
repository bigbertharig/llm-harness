# Local MCP candidate trial

Date: 2026-10-29
Status: exploratory; no shared scored fixture yet.
Receipts: `results/local_mcp_2026-10-29/` (ignored, retained on Pi).

## Setup and direct baseline

The local `county-map/tools/mcp-runtime` served Research and Geometry on Windows loopback, using the existing `county-map-data` catalog read-only. A temporary SSH reverse tunnel exposed them only on Pi loopback ports 17011 and 17010. The Pi gateway's ready route was `gpu-rig/coder-30b` (Qwen3 Coder 30B, 32,768 context); harness trials used the existing ready model. The runtime's local smoke test passed 44 dispatched calls before the tunnel test. No hosted service or hosted authentication was involved.

A direct Pi HTTP MCP baseline succeeded for both servers: `initialize`, `tools/list`, and `tools/call` returned HTTP 200 with `isError: false`. Research listed 10 tools; Geometry listed 12. `how_research_mcp_works` returned text and structured content. Geometry `get_catalog({"catalog":"geometry"})` returned **empty `content` and nonempty `structuredContent`**. The structured result contained `ok: true`, `catalog: "geometry"`, and families including `family_id: "administrative"`. This difference in result envelopes is the key fixture in the candidate trials. Baseline receipts are `baseline_summary.json`, `research_*.json`, and `geometry_*.json`.

## Candidate observations

| Candidate | MCP discovery | Research text result | Geometry structured-only result | Assessment |
|---|---|---|---|---|
| DeepSeek Harness 0.2.1-rc.2 | Both local HTTP servers configured and called | Called `how_research_mcp_works` once and gave a grounded answer | Called `get_catalog`; model-visible tool result was `(no output)`; final answer could not extract the catalog | Research pass; Geometry result fidelity fail |
| Nanobot 0.3.5 | Native provider connected; target tools registered | Called the Research tool once and gave a grounded answer | Called `get_catalog` twice; final answer said the tool returned no output | Research pass; Geometry result fidelity fail |
| OpenCode 2.1.4 | `mcp list` showed both servers connected | Live run did not reach inference | Live run did not reach inference | Discovery pass; tool-use inconclusive |
| Pi 1.4.0 | `mcp list --json` showed both servers connected | `--print` run did not reach inference | Not attempted after Research startup stall | Discovery pass; tool-use inconclusive |

DeepSeek's raw events are `deepseek/research.jsonl` and `deepseek/geometry.jsonl`. Nanobot's `nanobot/summary.json`, `registered_tools.json`, and `run.log` show the native MCP tool loop and calls. The Nanobot adapter at `nanobot/agent/tools/mcp.py` renders `result.content` and does not render `structuredContent`; this matches the observed empty model-visible Geometry output. DeepSeek's client likewise surfaced `(no output)` for that response in this run. Its subsequent extra tool calls and final failure are recorded in the Geometry JSONL; the zero-process-error exit is not a semantic pass.

OpenCode's first configuration used an obsolete flat MCP key and discovered no servers. The corrected V2 `mcp.servers` configuration discovered both. Its live run then stalled before a model request. No-MCP controls, including the previously working compaction configuration, stalled at the same startup point, so this trial cannot attribute the stall to MCP. A temporary proxy that returned HTTP 405 to GET and forwarded POST did not change that result. OpenCode receipts are under `opencode/`, `opencode_nomcp/`, `opencode_notools/`, `opencode_denyonly/`, and `opencode_compat/`.

Pi discovered both servers with its native `mcp.json`. Its `--print` live run stalled before model inference with both the direct tunnel and the GET-405 compatibility proxy. Its receipt files are under `pi/`; the empty JSONL and timeout exit mean no model tool-use conclusion is possible.

## Next test gate

Keep this direct baseline as a contract fixture: one text-plus-structured result and one structured-only result. A usable harness must show the model the latter's fields and preserve tool error/status information. Retest OpenCode and Pi after isolating their current CLI startup stalls, then add the same two calls to the shared candidate runner. Maintain these results separately from compaction scores; the cases have different pass criteria.
