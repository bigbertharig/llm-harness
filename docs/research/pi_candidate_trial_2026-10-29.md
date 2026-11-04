# Pi harness: first ready-only compaction trial

Date: 2026-10-29
Status: exploratory single-run evidence, not a candidate ranking.

## Setup

Pi was the next candidate after Codex and DeepSeek. Its reference checkout is pinned at `6c384aa30f619d7b28963f2bab24d8dacbe73cb6` (`UPSTREAM.md`). This trial installed the published `@earendil-works/pi-coding-agent@1.4.0` package in the separate `~/harness-runtimes/pi-1.4.0` directory; it did **not** build the checkout. Installation added 121 packages with `--ignore-scripts`, using Node 24.14.0 and a temporary workstation npm proxy over an SSH reverse tunnel. The tunnel was only for installation and was not a model-call dependency.

The gateway's ready roster offered `gpu-rig/coder-30b` (`qwen3-coder:30b-a3b`) on the 3090 Ti at an actual 32,768-token context. Pi used its `openai-completions` custom-model adapter at the Pi gateway's loopback URL, with `X-Require-Ready: true` on model calls. The runner checked that exact ready route before every user turn and after the session. No model load, unload, placement, or context change was requested; before and after rosters matched. The smoke returned `READY-PI-29` with a natural stop and empty stderr.

The experiment used Pi's native JSONL/RPC events, durable session files, and compactor. A small Python driver supplied turns and recorded events; it did not provide summarization or hidden memory. Built-in, extension, and MCP tools were disabled, and project context files were excluded. The working directory was empty. The fixture introduced nine facts, then corrected owner, deadline, release gate, and budget; routine notes created context pressure. Correct answers required Nora, Tuesday, `amber-birch-17`, Vega, `atlas.csv`, `7c4e`, orange, QA-43, and 12 hours, without superseded values.

## Observations

| Lane | Policy and output cap | Result |
|---|---|---|
| Default | Pi's 16,384-token reserve and 20,000-token recent retention; route cap 768 | The first completed compaction occurred on turn 12 as **overflow recovery**, reducing estimated context from 24,718 to 22,551 tokens. This is only one cycle; the post-compaction estimate remained high. The lane stopped after that checkpoint. |
| Tuned repeated check | 20,000-token reserve, 2,048-token recent retention; route cap 768 | Across 35 turns, eight completed compactions and three failed attempts. All seven keyed answers at turns 5, 10, 15, 20, 25, 30, and 35 contained the nine current values and excluded old ones. The eighth attempt hit the 768-token summary cap at turn 32, failures recurred at turn 33, and the next attempt succeeded at turn 34 without changing the setting. Correct answers did not turn those failed checkpoints into passes. |
| Blind initial cap | Same policy and 768-token cap; no interim fact checks | Two completed compactions, then repeated incomplete-summary failures from turn 11 onward. The run was stopped after turn 15 because the same cap failure repeated; it has no final-recall verdict. The partial events remain saved. |
| Blind larger cap | Same policy and fixture; only route output cap raised to 1,536 | Twenty-three turns, **six completed compactions**, no failed attempts. All six summaries and the durable session checkpoints retained the nine current values. The sole keyed question was the final turn; its answer contained all nine values, excluded the superseded ones, and stopped naturally. The roster was unchanged. |

In the successful blind lane, summary lengths grew from 2,434 to 3,740 characters over six checkpoints, roughly 261 characters each cycle. That is a growth warning, not yet proof of an unbounded summary: a longer run and a fixed summary budget are still needed. The 768-token failures show that output allocation matters for Pi's summarizer on this model. Increasing the cap from 768 to 1,536 rescued this blind case, as a separately labeled configuration change.

The raw configuration, runner, JSONL events, stderr, before/after rosters, progress, and persisted session files are under ignored Pi directory `~/llm-harness/results/pi_candidate_2026-10-29/`. `summary.json` in each completed lane gives per-turn answers and compaction outcomes; the interrupted 768-token blind lane has `progress.json` and raw events but no completed summary. The successful blind lane's session contains six `compaction` entries, matching six successful `compaction_end` events.

## What remains

This is one model and one run per lane, with a pressure fixture different from the earlier DeepSeek/Codex sessions. It supports a Pi compaction-mechanics result, not a cross-harness quality or speed ranking. Pi's model-facing tools, local/HTTP MCP, delayed-job wake-up, restart/resume, malformed provider response, and second ready model have not been tested here. The next fair comparison needs the shared driver and frozen fixture from the playbook. Hermes Agent and Nanobot remain available as pinned source checkouts for the next candidate trials; OpenCode is also untested.

Pi's own [compaction reference](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/compaction.md), [custom-model guide](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md), and [RPC reference](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/rpc.md) describe the native mechanisms used here.
