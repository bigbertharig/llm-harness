# Frozen local MCP tool-use trial, 2026-11-02

## Purpose and earlier evidence

The October [local MCP trial](local_mcp_candidate_trial_2026-10-29.md) showed DeepSeek and Nanobot could use a text-result tool but lost a Geometry tool result supplied only in `structuredContent`. Pi and OpenCode discovered the servers, but their live CLI probes stalled before inference. The [cloud trial](cloud_mcp_candidate_trial_2026-10-29.md) repeated the structured-only issue with DaedalMap. This trial uses one controlled fixture and ready model route to separate discovery, invocation, result delivery, and final answer.

## Frozen setup

- Runner: `python3 research/external_harnesses/comparison_tool_use.py CANDIDATE CASE --run-id UNIQUE_ID`, with `CANDIDATE` in `baseline, pi, opencode, deepseek` and `CASE` in `text, structured`. Source: `research/external_harnesses/comparison_tool_use.py`; server: `tools/fixtures/local_mcp_marker.mjs`.
- Route: externally loaded `gpu-rig/coder-30b`, Qwen3 Coder 30B, actual context 32,768. `tools/live_preflight.py` passed and wrote `results/preflight_2026-11-02_tool_use.json`. Each candidate receipt saves ready rosters before and after. The adapter configs declare an output cap of 1,536; the gateway roster exposed `output_limit: null`, so request-level enforcement still needs tracing.
- The dependency-free stdio MCP server lists `read_marker` and `read_structured_marker`. The first returns text plus `structuredContent`; the second returns empty text `content` and the marker only in `structuredContent`. Each marker is randomly generated during `tools/call` and logged to a per-run JSONL receipt, so the prompt and fixture source cannot supply the answer. The direct protocol baseline initializes, lists both tools, calls each, and checks both response shapes before every candidate run.
- Each candidate gets an isolated workspace and configuration. The prompt requests one named local fixture call and only the returned marker. The scorer requires server initialization and listing, exactly one named call and one result, no other named tool event, exact marker in the final answer, a natural finish, a clean exit, and an unchanged ready roster. Raw events, stderr, configs, call log, direct baseline, and summary are under the ignored `results/` tree.

## Final-configuration results

| Candidate | Text result | Structured-only result | Observed behavior |
|---|---|---|---|
| Direct MCP baseline | Pass | Pass | Server protocol and response shapes passed in each run. |
| Pi | 2/2 pass | 2/2 pass | Exactly one correct MCP call and exact returned marker in both cases. |
| DeepSeek Harness | 2/2 pass | 0/2 fail | Correct call and server result in structured case, but the adapter rendered it as no model-visible content. |
| OpenCode | 0/2 fail | 0/2 fail | Server initialized and listed two tools; no tool call. Candidate exited 0 with fabricated or JSON-shaped text instead of a marker. |

First final-configuration receipts are under `results/comparison_tool_use_2026-11-02_v1_pi_tools/pi/text/`, `results/comparison_tool_use_2026-11-02_v1_struct/pi/structured/`, `results/comparison_tool_use_2026-11-02_v1/deepseek/text/`, `results/comparison_tool_use_2026-11-02_v1_struct/deepseek/structured/`, and `results/comparison_tool_use_2026-11-02_v1_struct/opencode/structured/`. OpenCode's first direct-exposure text receipt is `results/comparison_tool_use_2026-11-02_v1_opencode_direct/opencode/text/`. All six repeat receipts are under `results/comparison_tool_use_2026-11-02_v1_repeat/{candidate}/{case}/`. Each final-configuration case has two complete receipts; fixture and server hashes are in each summary. The OpenCode driver gained debug logging before the repeat, without changing its MCP exposure. See `summary.json` for individual checks and `calls.jsonl` for actual MCP traffic. A diagnostic `pi mcp list --json` was run after the first failed Pi setup and appended discovery traffic to that setup's call log; treat its original `summary.json` as the run verdict and that later discovery traffic as a separate diagnostic.

## Setup trials retained separately

- Pi initially exposed no callable MCP tool under `--no-builtin-tools --no-extensions`; adding `--tools` while keeping those flags still failed. With explicit `--tools mcp__fixture__<case-tool>` and without those disabling flags, both cases passed. Initial failures: `results/comparison_tool_use_2026-11-02_v1/pi/text/` and `results/comparison_tool_use_2026-11-02_v1_pi_allow/pi/text/`; corrected text run: `results/comparison_tool_use_2026-11-02_v1_pi_tools/pi/text/`.
- OpenCode's initial config, then `codemode: false` for direct MCP exposure, both initialized and listed the server but did not call it. A debug rerun also showed `mcp connected server=fixture tools=2`; the model emitted tool-shaped text with no native call. Receipts: `results/comparison_tool_use_2026-11-02_v1/opencode/text/`, `results/comparison_tool_use_2026-11-02_v1_opencode_direct/opencode/text/`, and `results/comparison_tool_use_2026-11-02_v1_opencode_debug/opencode/text/`. Current source uses `codemode: false` and retains debug logs. The cause within model/provider/harness tool-call handling is still unproven.
- DeepSeek's structured case called `read_structured_marker` once and received the server result, but its event stream stated that the tool returned no model-visible content. This reproduces the earlier Geometry/DaedalMap interoperability issue with a deterministic shape.

## Next gates

1. Trace OpenCode's model request and response tool schema, plus the gateway response, to locate where the native call is lost. Keep a source-level claim distinct from an observed call. Repeat with a direct gateway tool-call baseline if the trace remains ambiguous.
2. Fix or configure DeepSeek's MCP result mapping so `structuredContent` reaches the model when text `content` is empty; rerun this exact fixture before changing scorecard status.
3. Add adapters for Codex and Nanobot on this 30B/32K route. Run Hermes in a separately labeled compatible 65K model/window block. Extend cases to denied actions, failed and delayed jobs, bounded large output, and a controlled remote Streamable HTTP server. Preserve separate discovery, invocation, result, and wake-up checks.

This is a local stdio MCP tool-use result. It does not establish remote MCP compatibility, general tool reliability, asynchronous completion, or overall harness quality.
