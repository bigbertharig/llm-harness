# Gateway-managed child delegation: first six-harness matrix

Date: 2026-11-04. The manager offers two agent types for now: `coding` and `research`. The model-facing MCP tool takes only `agent_type` and `task`. Its controller supplies the parent route and receipt directory as MCP process arguments. The manager chooses a disjoint GPU route, cold-loads a published profile when needed, and returns a ready result or an error within five minutes. The harness then runs a separate native Pi child session against that ready route; the child has no delegation tool.

## Frozen first case

`research/external_harnesses/comparison_subagents.py` runs one `coding` case for each candidate through its existing isolated MCP controller. A direct MCP baseline creates a child before each native parent run. The parent does not see the arithmetic question until the tool returns the child's answer, so the final answer must be checked against both the child receipt and the question revealed in the tool result. Pass requires one `delegate_task` call with a nonempty task, one child receipt, answer `42` from child and parent, disjoint parent/child GPUs, unchanged ready roster, clean process finishes, and no tool error. Child output is capped at 96 tokens and its runtime at 90 seconds.

Run with a prepared parent route (`coder-30b`/32K for five harnesses, `chat-27b`/65K for Hermes):

```bash
python3 research/external_harnesses/comparison_subagents.py pi --run-id NEW_ID
python3 research/external_harnesses/comparison_subagents.py deepseek --run-id NEW_ID
python3 research/external_harnesses/comparison_subagents.py nanobot --run-id NEW_ID
python3 research/external_harnesses/comparison_subagents.py opencode --run-id NEW_ID
python3 research/external_harnesses/comparison_subagents.py codex --run-id NEW_ID
python3 research/external_harnesses/comparison_subagents.py hermes --run-id NEW_ID
python3 research/external_harnesses/comparison_subagents.py summary --run-id NEW_ID
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

On 2026-11-20, a read-only documentation comparison exposed two additional adapter cases. Nemotron 74B emitted allowlisted workspace calls as XML-shaped envelopes and as one batch. The child bridge now normalizes only a complete leading allowlisted XML call, validates every argument through the existing policy and MCP schema, and can execute a bounded batch sequentially before returning one combined evidence packet. This reduced a 12-call live pass from 401 seconds with repeated per-call generations to 87.9 seconds. The model still replayed its completed plan and produced no final answer, so the run is adapter-compatibility evidence, not a successful documentation result. Qwen 35 produced one useful evidence extraction but also one unsupported no-read answer. Require source-read receipts, complete output, and parent review for documentation work.

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

## Parent model size sweep, 2026-11-05

The first size sweep held the Pi harness, `coding` child route (`coder-7b` on GPU 1), hidden arithmetic task, and fixture hash `00a5eda3be222f4cf6bc6096dad52ba18d592ad55c90c54c47ac3d76b53e7a2c` fixed. Each parent had three native trials, each preceded by a passing direct MCP baseline. The durable summary is `results/model_size_sweep_20261105/matrix.json`; individual raw receipts are linked in that file. Parent models, placements, context lengths, and backend are recorded there.

| Parent size | Model | Parent placement | Native pass | Delegation call | Median trial time |
|---|---|---|---:|---:|---:|
| 7B | Qwen2.5 Coder 7B | GPU 0, 16K | 0/3 | 0/3 | 3.42 s |
| 14B | Qwen2.5 Coder 14B | GPU 0, 16K | 0/3 | 0/3 | 3.76 s |
| 30B | Qwen3 Coder 30B A3B | GPU 0, 32K | 3/3 | 3/3 | 5.30 s |
| 74B | Nemotron 3.5 Bolt 74B A9B | GPUs 0,2,3,4,5, 16K | 3/3 | 3/3 | 11.99 s |
| 125B main + 51B lookup | Qwen3.8 Flash-Next Q2_0 | Strata, GPU 0, 8K | 3/3 | 3/3 | 8.06 s |

The 7B and 14B parents each emitted a correctly shaped `mcp__subagent__delegate_task` JSON object as *text*. The native Pi harness treated it as a final answer, so no tool execution or child receipt occurred. This is a model-to-tool translation gap in this model/route/controller combination; it is not evidence that the models chose the wrong agent type or task. Keep these failed native results and test a separately labeled harness adapter that recognizes a validated textual tool request. Do not retroactively score text as a native tool call. The 30B, 74B, and Strata 125B parents used the MCP tool successfully in all three trials. These are one harness and one task; size alone cannot be credited for the difference because model families, quantization, context, backend, and GPU placement also changed.

The 125B case came from the benchmarking library's Strata pack under `/data/model-hotset/qwen3.8-flash-next-q2_0`. It has 125B main parameters, a 51B lookup table, and 6B active parameters per token; it is the locally available large-model case, not an exact 120B model. Its dynamic gateway route was ready-listed, and all three direct baselines and native trials passed. All test routes were unloaded; the manager reported six free GPUs.

## Next local retrieval test

Disaster Clippy's configured local backup directory is `D:\disaster-backups-local`. It contains populated 768- and 1536-dimension Chroma stores, source packs with accepted passages and vector JSON, and the local `all-mpnet-base-v2` embedding model. For the first harness comparison, derive a small immutable corpus and query set from selected source packs **read-only**; do not point test writers at the production Chroma directories. Record source/document/section IDs, text, metadata, vector dimension, embedding model/version, corpus hash, and expected relevant passage IDs. Import the same corpus into an isolated Chroma collection on the Pi. Direct queries must pass recall, metadata/source filtering, and exact-ID checks before any LLM trial. Expose one simple local MCP search tool with query, optional source filter, and result limit; return ranked passages with IDs, titles, snippets, scores, and citations. Then compare harnesses on tool choice, query reformulation, use of filters, grounded answer/citation quality, latency, and tool errors. Add exact-term and hybrid-search cases separately so embedding quality and agent behavior are not conflated. Pinecone is outside this local-only round.

The first direct local smoke used six passages from `builditsolar` and `wiki_top_100` in an in-memory Chroma collection. It generated document and query embeddings with the installed local `all-mpnet-base-v2` model, scored 3/3 intended passages in the top three and passed a source-filter query. Receipt: `results/local_chroma_smoke_20261105.json`. This tiny corpus only proves the local retrieval path is workable; it is not a quality benchmark or a six-harness result. The source pack files named `_vectors_768.json` identify their embedding model as `text-embedding-3-small`, so their vectors must **not** be mixed with queries from `all-mpnet-base-v2` even though both are 768-dimensional. Re-embed the frozen corpus with the local model for the actual suite, and hash both the corpus and model identity.

The local-only six-harness RAG comparison and 7B/14B/30B/74B Pi size slice were completed on 2026-11-05. The owning status and reproduction guide is `docs/research/local_rag_matrix_2026-11-05.md`; the direct-control corpus hash is `a6fde974595df0ed460db22e06f048209e099aa16139c7ea209222ee6df37bf8`.

## Pi controller tool bridge and small-model swaps, 2026-11-05

The frozen delegation fixture and pass criteria stayed unchanged (SHA-256 `00a5eda3be222f4cf6bc6096dad52ba18d592ad55c90c54c47ac3d76b53e7a2c`). `research/external_harnesses/candidate_controllers/text_tool_bridge.py` now gives Pi a controller-level fallback when a parent emits a complete MCP request as text rather than a native tool call. It accepts only a whole JSON object with `name` and `arguments`, optionally inside a complete JSON fence or `<tools>` wrapper. The name must be in the controller's exposed allowlist. Before execution the bridge calls `tools/list` and checks the arguments against the advertised JSON Schema. It supports stdio and Streamable HTTP MCP. It never extracts a command from prose. A no-call response gets one generic format-repair turn; bridged requests are limited to two distinct calls and share a 360-second parent deadline. The result is returned to the same Pi session, with a general reminder to follow the user's requested answer format. Receipts distinguish `native`, `text_bridge`, and `none` modes.

The controller also accepts an optional server `help` descriptor with an explicit `name` and `arguments`. It calls that advertised help tool before the parent turn and adds the returned guidance to the system prompt. For the known local Research and Geometry servers, the Pi controller supplies `get_tool_help` with the exact target `tool_name`, as documented by those servers. For all other servers, the advertised descriptions and schemas are the authoritative call instructions; the bridge does not guess help-tool arguments. This is a server adapter, not a model-specific prompt or a test-case answer.

| Parent | Initial native result | Controller iteration | Final observed case |
|---|---|---|---|
| Qwen2.5 Coder 7B | 0/3, JSON text | strict JSON bridge | pass in `bridge_7b_trial_01_20261105` and `_02` |
| Qwen2.5 Coder 14B | 0/3, JSON text | complete `<tools>` wrapper accepted | pass in `bridge_14b_trial_02_20261105` |
| Ministral 3 8B | no prior native sweep | same bridge | pass in `bridge_ministral8b_trial_02_20261105` |
| Ornith 1.5 9B | no prior native sweep | same bridge | pass in `bridge_ornith9b_trial_01_20261105` |
| Phi 4 14B | no prior native sweep | one generic no-call repair; result-format reminder | pass in `bridge_phi14b_trial_03_20261105` |

Each passing case had a passing direct MCP baseline, exactly one actual delegation call, one child receipt, disjoint GPUs, clean child and parent, and the verified `42` final line. The bridge's focused stdio, HTTP, allowlist, and schema checks passed 4/4. The early failed receipts remain: the first 14B attempt used JSON inside `<tools>` and was not parsed; the first Phi attempt described a call and invented a result, so the bridge correctly did not execute prose; the next Phi attempt made a valid call but added an explanation despite the requested number-only format. The first Ministral attempt was withheld because a temporary dynamic route was not in the gateway's ready roster, causing its direct control to fail. Published `harness-ministral-8b`, `harness-ornith-9b`, and `harness-phi-14b` routes removed that setup problem. These trials followed controller changes, so the table is evidence that several model families can use the same general mechanism, not a matched reliability estimate. Repeat all models on one pinned controller revision before estimating pass rates. Native and bridged success must remain separate metrics.

The 30B native-tool regression passed under the final controller in `results/bridge_native30b_regression_20261105/subagents/pi/summary.json`; its mode is `native` and its bridge call list is empty. Both loaded test routes were then unloaded and the rig manager showed six free GPUs.
