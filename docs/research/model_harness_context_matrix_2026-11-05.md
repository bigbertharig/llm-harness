# Model-first harness matrix: context and execution gate

The six candidate controllers are in `llm-harness/tools/candidate_controllers/`. The upstream harness source checkouts remain unchanged. `HARNESS_TEST_ROUTE`, `HARNESS_TEST_MODEL`, and `HARNESS_TEST_CONTEXT` now select the ready route in each isolated controller and in shared receipt metadata. Without those variables, the existing 30B defaults remain, and Hermes keeps its 27B/65K default.

The 14B route-swap pilot (`results/route_swap_14b_pilot_20261105/`) ran one frozen three-turn short control on all six controllers. Pi, DeepSeek, Nanobot, OpenCode, and Codex passed at the actual served 16,384-token context. Hermes stopped before inference with a runtime error that its minimum is **64,000** tokens. This is an incompatible harness-route pairing, not a failed language-model answer. The formal minimum of each of the other five harnesses has not been established; the pilot only proves that this setup accepted 16,384 tokens.

| Published route | Model | Served context | Model trained maximum in gateway catalog | Hermes on published route |
|---|---|---:|---:|---|
| `harness-gemma4-e4b-64k` | Gemma 4 E4B, one GTX 1060 | 65,536 | 131,072 | Context eligible; projected 4,197 MiB on GPU 2 with 1,943 MiB headroom |
| `harness-gemma4-12b-64k` | Gemma 4 12B, two GTX 1060s | 65,536 | 262,144 | Context eligible; projected 4,431 and 4,412 MiB on GPUs 2 and 3 |
| `gpt-oss-20b` | GPT-OSS 20B | 65,536 | 131,072 | Native core matrix attempted |
| `chat-27b` | Qwen3.6 27B | 65,536 | 262,144 | Existing prepared route and prior tests |
| `coder-30b` | Qwen3 Coder 30B A3B | 32,768 | 262,144 | Published route too short; a separate 64K route needs fit and compatibility validation |
| `harness-74b` | Nemotron Bolt 74B A9B | 16,384 | 262,144 | Published route too short; a separate 64K route needs fit and child-GPU validation |

The Qwen2.5 Coder 7B and 14B routes were removed from this matrix after the pilot: their trained maximum is 32,768, below Hermes' requirement. The replacement routes passed the gateway fit planner and loaded successfully at 65,536 tokens for the core matrix.

The current core matrix script marks Hermes cells below 64,000 as `incompatible_context` without starting the harness. It records route, model, served context, trained maximum, case status, logs, progress timestamps, and a terminal receipt. It loads each model once, cycles harnesses and frozen local suites, then unloads it. The first phase includes short conversation, six dependency-free local MCP cases, one managed-subagent case, and one search-to-CPU-fetch case. Provider-limited search, public MCPs, Windows-hosted Research/Geometry, and local Chroma RAG require their direct baselines and stable services before joining the background queue. Compaction remains exploratory and is not yet a matched suite.

Swapping a harness changes an isolated process/config and took roughly 3-12 seconds per completed 14B short-control session in this pilot. Loading the 14B model took roughly 90 seconds. Model-first order is therefore the sensible default, while each candidate still gets a fresh home/workspace and its own receipts. These timings are one pilot, not general performance estimates.

## Completed core matrix, 2026-11-05

`results/model_harness_core_20261105_v1/status.json` and `terminal_receipt.json` record all 324 scheduled cells across six models and six harness controllers. The job finished at 22:30:19 UTC with exit status 0. Here, `completed` means the existing case runner exited 0; `failed` means nonzero. The 18 `incompatible_context` cells are Hermes on the published 30B and 74B routes, which serve less than its 64,000-token minimum. They were not attempted.

| Model row | Completed | Failed | Incompatible context |
|---|---:|---:|---:|
| GPT-OSS 20B | 36 | 18 | 0 |
| Gemma 4 E4B, one GTX 1060 | 35 | 19 | 0 |
| Gemma 4 12B, two GTX 1060s | 38 | 16 | 0 |
| Qwen3.6 27B | 37 | 17 | 0 |
| Qwen3 Coder 30B | 30 | 15 | 9 |
| Nemotron Bolt 74B | 34 | 11 | 9 |
| **Total** | **210** | **96** | **18** |

Across models, Pi had 49 completed and 5 failed cases; Codex 45/9; Nanobot 39/15; DeepSeek 38/16; Hermes 29/7 plus 18 incompatible; OpenCode 10/44. Several failures repeat at the same harness/case across all six models, especially DeepSeek and Nanobot `marker_structured`/`lookup_nested`, and OpenCode's local MCP cases. Investigate controller or case-contract causes before attributing these repeated failures to model quality. This is the dependency-free core phase; it does not claim full compaction, public MCP, provider-limited search, or Chroma RAG coverage.

## Shared-failure audit and integration corrections, 2026-11-05

The six-model table above is a **before-fix snapshot**; do not silently replace its counts with the focused retests below. Direct MCP baselines passed. Raw tool-call receipts showed the fixture returned the expected values, so the repeated DeepSeek and Nanobot failures were result-transport gaps: their clients exposed `(no output)` for `structuredContent` with empty `content`. `tools/candidate_controllers/mcp_content_proxy.py` now adds a text content block containing the structured JSON for such successful stdio results while preserving `structuredContent`. The proxy changes no result that already has content and does not change the upstream harnesses or fixture. Its direct protocol smoke passed. The four previously repeated cases (`marker_structured` and `lookup_nested` on DeepSeek and Nanobot) then passed on both Gemma 4 E4B and Gemma 4 12B: eight of eight focused cases, each with one target call and the correct marker. Receipts: `results/compat_e4b_20261105/` and `results/compat_12b_20261105/`.

Hermes short control had real unintended `search_files` and `memory` calls. The old top-level `toolsets: []` setting is deprecated in the installed Hermes source; its explicit empty CLI allowlist is `platform_toolsets: {cli: []}`. The controller now writes that setting. The fresh three-turn E4B run passed with zero tool calls and correct recall: `results/compat_e4b_hermes_20261105/`.

OpenCode's general `execute` tool was available beside direct MCP tools, and some failures show models misusing it. We tested denying `execute`: direct `marker_text` passed on E4B and GPT-OSS 20B, but the six-model selective rerun exposed a larger regression in previously passing subagent and web cases. The restriction was **reverted**; the current controller is byte-identical to its pre-experiment version. A fresh E4B managed-subagent run passed after restoration (`results/compat_opencode_restore_e4b_20261105/`). The original OpenCode failures remain unresolved. Gemma 12B sometimes printed `<|tool_call>...` as ordinary text, and GPT-OSS 20B sometimes answered arithmetic without calling MCP. The denied-`execute` experimental receipts must not be used as the final OpenCode score.

The GPT-OSS 20B Codex web case had correct search, CPU fetch, answer, citation, and a completed turn, but the controller treated recovered `Reconnecting...` events as fatal. It now counts them as terminal errors only if no `turn.completed` follows; raw events remain in the receipt. Replaying the recorded trace yields zero terminal errors, and a fresh run passed every existing check: `results/compat_20b_codex_web_20261105/`.

Other recurring failures are not uniform controller defects on the available evidence. OpenCode managed-subagent cells passed on E4B, 27B, and 74B, but failed before a valid delegation on 20B, 12B, and 30B. Hermes web research passed on 20B while the smaller and 27B models failed at different search/fetch or final-answer steps. Preserve those as model-dependent observations until a matched assisted-call policy is designed and measured separately.

Use the selective rerun below to measure the retained controller corrections, then run the full frozen matrix before publishing final model rankings. Further OpenCode work should test a general tool-call recovery policy separately and record first-attempt versus assisted outcomes; the current native-call failures should stay visible.

## Selective post-fix rerun, completed 2026-11-06 UTC

`tools/model_harness_selective_rerun.py` used the existing frozen runners and six model routes. Run `model_harness_selective_20261105_v2` finished 76 cells with a clean job receipt at 00:10:46 UTC: 28 runner passes and 48 case failures. The v1 matrix remains the before-fix snapshot. The result by affected controller was:

| Controller | v1 passes on selected cells | Selective passes | Interpretation |
|---|---:|---:|---|
| DeepSeek | 0/12 | 12/12 | Structured-result adapter fixed all selected cells |
| Nanobot | 0/12 | 12/12 | Structured-result adapter fixed all selected cells |
| Hermes | 1/4 | 3/4 | Built-in calls removed; dual-1060 model missed early `ACK` responses despite zero tool calls |
| OpenCode | 6/48 | 1/48 | Experimental `execute` denial regressed previously passing cells; reverted, so keep v1 receipts |

The Codex 20B web case already passed its separate fresh rerun. These selective outcomes establish the structured-result fix across all six model routes and reveal the OpenCode regression. They are not a synchronized final ranking: OpenCode's current bytes are restored, and unchanged v1 receipts remain authoritative until a full sweep. All test-owned model loads were released after this pass.

## OpenCode second-fix pilot, 2026-11-06 UTC

OpenCode's `codemode: false` registration gives the model direct native MCP tools such as `marker_read_marker`, while its separate `execute` JavaScript catalog does not contain them. V1 traces show failed models repeatedly trying MCP names through `execute`; successful runs sometimes recovered to a direct call. We tested controller-generated guidance that names the direct tools. The checkpointed OpenCode-only run `results/model_harness_opencode_alias_20261105_v1/` completed the 20B and single-1060 rows, each with eight affected cases. It produced **2/16 passes**, both managed-subagent cases; all twelve local MCP cases and both web cases failed the existing strict checks. One 20B numeric case was interrupted by the Pi's full root filesystem and is invalid as model evidence. The run was stopped after those two rows because the MCP failures repeated. The terminal receipt records the deliberate stop, not a completed six-model matrix. An earlier uncheckpointed E4B spot check had passed numeric sum and subagent delegation, but that did not reproduce across the full row.

We also tried OpenCode's `codemode: true` path behind a temporary controller flag, with generic and then exact callable-path guidance. The 20B model sometimes returned the correct numeric or structured marker after one real MCP invocation (`results/compat_opencode_codemode_20b_20261105/`), but it also made extra `execute` calls, guessed bracket syntax the interpreter rejected, returned the wrong marker, or answered arithmetic without using MCP (`results/compat_opencode_codemode_exact_20b_20261105/`). The current MCP scorer requires one native MCP tool event by name, so every code-mode case fails its direct-tool check even when the underlying MCP call and answer are correct. These are exploratory traces, not comparable pass counts. A future code-mode lane needs a declared, general tool-event adapter and separate call-efficiency measures before it can be ranked against direct-tool runs; do not silently waive failed or exploratory calls.

Both controller experiments were reverted. `tools/candidate_controllers/opencode.py` matches its saved pre-pilot bytes, and the upstream OpenCode checkout was untouched. OpenCode's v1 results remain the comparable scores. The Pi ran out of root space during the attempted rerun; 44 inactive duplicated Codex plugin checkout caches inside old test output folders (4.4 GB) were removed while preserving receipts and raw traces. All model loads started by these pilots were released; the preexisting GPU-1 `coder-7b` lease was left alone.

### Pi storage follow-up

The Pi root filesystem is 28 GB. A follow-up audit found another 86 inactive `codex_home/.tmp/plugins-clone-*` folders under historical harness results, totaling 2.2 GB; these were removed while retaining case receipts and raw traces. Free space rose from 4.3 GB to 6.5 GB (76% used). Other large areas include the remaining harness results (2.3 GB), pnpm's package store (2.0 GB), Hugging Face cache (0.9 GB), and the configured `/var/swap` file (2.0 GB); these were retained.

To prevent the same growth, `tools/candidate_controllers/codex.py` now prunes only `plugins` and `plugins-clone-*` under each isolated `codex_home/.tmp` after a run and records removed names in `plugin_cache_cleanup.json`. A temporary-directory smoke test verified the exact targets, preservation of unrelated folders, and refusal to follow a symlink outside the test home. The upstream Codex checkout was not changed.

## OpenCode restored-controller rerun, completed 2026-11-06 UTC

The OpenCode-only run `results/model_harness_opencode_restored_20261106_v1/` used the restored pre-experiment controller and the existing eight selected cases for each of the six published model routes. Its `status.json` and `terminal_receipt.json` record all **48/48** scheduled cases, finished at 03:29:20 UTC with job exit status 0. All six test-owned loads were unloaded successfully (`unload.exit_code = 0`); the preexisting GPU-1 lease was not part of the run. The Pi had 6.3 GB free afterward.

| Model row | Runner completed | Runner failed | Passing selected case |
|---|---:|---:|---|
| GPT-OSS 20B | 1 | 7 | managed subagent |
| Gemma 4 E4B, one GTX 1060 | 1 | 7 | managed subagent |
| Gemma 4 12B, two GTX 1060s | 0 | 8 | none |
| Qwen3.6 27B | 1 | 7 | managed subagent |
| Qwen3 Coder 30B | 0 | 8 | none |
| Nemotron Bolt 74B | 1 | 7 | web research |
| **Total** | **4** | **44** | |

Here `completed` is the case runner's zero exit and `failed` is nonzero, not a new score rule. The 74B local MCP marker case discovered the expected tools and kept the ready roster unchanged, but made no target tool call and timed out at roughly 120 seconds; its managed-subagent case also failed its delegation and child-receipt checks. The 74B web-research case passed. This fresh run confirms that removing the experimental `execute` restriction did not by itself repair OpenCode's local MCP path. Its 4/48 passes differ from the original core snapshot's 6/48 selected OpenCode passes, so report both run IDs and do not merge the counts or claim a stable model ranking. The restored controller is the retained code; the alias and code-mode experiments remain excluded from comparable scores.

Next OpenCode work: inspect the actual model-visible tool catalog and failed call traces across several short repeated trials, then test a general, controller-owned recovery rule with explicit assisted-call scoring. Separate failure to choose a tool, malformed native calls, wrong tool namespace, tool transport errors, and answers invented without a call. Preserve each case's direct baseline and original native result. A fix must generalize across multiple model families and keep the upstream OpenCode checkout unchanged before another full matrix is justified.
