# Gateway-managed child delegation: first six-harness matrix

Date: 2026-11-04. The manager offers two agent types for now: `coding` and `research`. The model-facing MCP tool takes only `agent_type` and `task`. Its controller supplies the parent route and receipt directory as MCP process arguments. The manager chooses a disjoint GPU route, cold-loads a published profile when needed, and returns a ready result or an error within five minutes. The harness then runs a separate native Pi child session against that ready route; the child has no delegation tool.

## Frozen first case

`tools/comparison_subagents.py` runs one `coding` case for each candidate through its existing isolated MCP controller. A direct MCP baseline creates a child before each native parent run. The parent does not see the arithmetic question until the tool returns the child's answer, so the final answer must be checked against both the child receipt and the question revealed in the tool result. Pass requires one `delegate_task` call with a nonempty task, one child receipt, answer `42` from child and parent, disjoint parent/child GPUs, unchanged ready roster, clean process finishes, and no tool error. Child output is capped at 96 tokens and its runtime at 90 seconds.

Run with a prepared parent route (`coder-30b`/32K for five harnesses, `chat-27b`/65K for Hermes):

```bash
python3 tools/comparison_subagents.py pi --run-id NEW_ID
python3 tools/comparison_subagents.py deepseek --run-id NEW_ID
python3 tools/comparison_subagents.py nanobot --run-id NEW_ID
python3 tools/comparison_subagents.py opencode --run-id NEW_ID
python3 tools/comparison_subagents.py codex --run-id NEW_ID
python3 tools/comparison_subagents.py hermes --run-id NEW_ID
python3 tools/comparison_subagents.py summary --run-id NEW_ID
```

Use a fresh ID for each attempt. The 2026-11-04 matrix is `results/subagent_six_native_v2/subagents/matrix.json`, pinned to fixture SHA-256 `eb7d04d2b844265849cf8b6e752edffb5d3b577fef7a7499fc17e37611ab4bd5`.

| Harness | Parent route | Child route | Pass | Duration |
|---|---|---|---:|---:|
| Pi | `coder-30b` | `coder-7b` | 1/1 | 5.44 s |
| DeepSeek Harness | `coder-30b` | `coder-7b` | 1/1 | 6.35 s |
| Nanobot | `coder-30b` | `coder-7b` | 1/1 | 7.00 s |
| OpenCode | `coder-30b` | `coder-7b` | 1/1 | 12.28 s |
| OpenAI Codex | `coder-30b` | `coder-7b` | 1/1 | 11.52 s |
| Hermes Agent | `chat-27b` | `coder-7b` | 1/1 | 30.96 s |

Every direct baseline passed. Parent GPU 0 and child GPU 1 were observed in every native receipt. The manager loaded the cold child route on the first request. The initial direct control timed out because the generic MCP baseline allowed only 12 seconds; the delegation baseline now waits for the manager's readiness deadline. Nanobot's first native attempt reached the tool but its MCP subprocess did not inherit the controller environment. Passing parent route and receipt directory as launch arguments fixed that; all six candidates ran the corrected fixture. Earlier failure receipts remain under `subagent_six_v1` and `subagent_six_native_v1`. Both model routes were unloaded after the suite, leaving six GPUs free.

This measures the shared MCP delegation integration across harnesses. It does not measure each harness's built-in subagent feature or compare parent model quality. The next cases should cover `research`, failed and timed-out loads, concurrent children, a larger child task, and repeated runs.

## Child prompt research to add later

The user supplied a Claude cleanup-agent prompt as a useful example. It specifies the role and handoff, exact edit scope and exclusions, execution environment, baseline evidence, deterministic checks, and a concise report. A later study can compare past Claude, Codex, and other child-agent prompts with their actual outcomes, then turn the supported patterns into a short harness-owned prompt guide. Preserve provenance and failure examples; test prompt variants on fixed tasks before adopting a template. No old-chat scan was done in this pass.

## Follow-up round and reliability finding

The revised fixture gives the `coding` child a harness-owned role prompt and normalizes a valid numeric answer such as `42.0` to `42`; it rejects a wrong answer. The parent scorer accepts a correct final nonempty line while recording whether the entire answer was exactly the requested number. This separates successful delegation from response-format compliance. The model still sees a simple `agent_type` and `task` request; the controller handles prompt style, MCP invocation, ready-route waiting, receipts, and response checks. `tests/test_gateway_subagent.py` passed 3/3 after this change.

The fresh six-harness run is `results/subagent_six_native_v5/subagents/matrix.json`, fixture SHA-256 `00a5eda3be222f4cf6bc6096dad52ba18d592ad55c90c54c47ac3d76b53e7a2c`. Every direct MCP baseline passed. Five of six native runs passed:

| Harness | Native result | Exact parent format | Duration |
|---|---:|---:|---:|
| Pi | pass | yes | 5.72 s |
| DeepSeek Harness | pass | yes | 7.31 s |
| Nanobot | pass | yes | 8.41 s |
| OpenCode | fail: no delegation call | no | 14.81 s |
| OpenAI Codex | pass | yes | 12.05 s |
| Hermes Agent | pass | no; ended with `42` | 30.75 s |

OpenCode's MCP server connected with one tool, but the model ignored the explicit call instruction, invented an arithmetic problem, and returned `53`. An identical, separately preserved retry passed in `results/subagent_opencode_repeat_v6/subagents/opencode/summary.json` (10.69 s). This is intermittent tool avoidance in the tested model/controller pair; one pass is insufficient reliability evidence. The previous v3 receipt also records a strict false negative for Codex's valid `42.0` answer, and v4 records Hermes's correct final line with extra explanation. Those receipts motivated the normalization and separate format metric; they were not deleted. Both test routes were unloaded after v5, and the manager reported six free GPUs.

## Next comparison design

Run repeated trials per harness and report call rate, correct child result rate, final-answer rate, exact-format rate, latency distribution, and failure type. Pin the same parent model, model settings, child model, task, fixture hash, and ready-route state across harnesses where feasible. Then hold one harness fixed and vary parent size: a small model, approximately 30B, and a larger model. Keep hardware placement, quantization, context, and time limits in the receipt so a model-size effect is not confused with a harness difference. Use several tasks, including `research` and failure/timeout paths, before drawing a general ranking. Keep the deterministic direct MCP baseline before every native trial; a failed baseline invalidates that trial as a harness comparison.
