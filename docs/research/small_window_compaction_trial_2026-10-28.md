# Small-window compaction trials: 16K and 32K

Date: 2026-10-28
Status: exploratory single-run evidence; no candidate ranking.

## Setup and invariant

The rig was idle apart from the previous `chat-27b` load. The manager unloaded it, loaded published `coder-7b` on GPU0, then later unloaded that and loaded published `coder-30b` on GPU0. Ready-roster and rig status confirmed **qwen2.5-coder:7b at an actual 16,384-token context** and then **qwen3-coder:30b-a3b at an actual 32,768-token context**. All harness requests used the Pi gateway with `X-Require-Ready: true`; none requested a model load. The ready roster was unchanged within each test block. The 30B/32K model remains loaded at the end of this trial.

The key was an initial nine-value project state with owner Mira, deadline Friday, release gate QA-42, and budget 18 hours; the next turn corrected those four values to Nora, Tuesday, QA-43, and 12 hours. The other values were codeword `amber-birch-17`, client Vega, artifact `atlas.csv`, checksum `7c4e`, and risk orange. Routine CPU-worker notes built context pressure without changing those values. A keyed answer passed only if it contained every currently expected value and omitted superseded gate/budget values.

Raw prompts, per-turn JSONL/stderr, configuration patches, model-roster snapshots, persisted sessions, and machine-readable `summary.json` receipts are under ignored Pi directories `results/compaction_16k_2026-10-28/` and `results/compaction_32k_2026-10-28/`. The exact probe and receipt scripts are saved in `results/` beside them. Codex is installed CLI 0.147.0; DeepSeek source is pinned at `687f282e86`. These are independent candidate sessions, not a shared comparison runner.

## Results

| Model and candidate | Compaction policy | Observed result |
|---|---|---|
| 7B/16K, Codex | Native trigger from `model_context_window=16384`; no compaction threshold override | Turn 6 recorded one checkpoint and correctly recalled the three initial/corrected facts. Turn 7 recorded a second checkpoint, but the following model request had 17,888 prompt tokens against the 16,384 limit and failed with `context_length_exceeded`. The second checkpoint is **not** a usable completed cycle. The CLI JSONL did not expose a dedicated compaction item; the durable Codex session did. |
| 7B/16K, DeepSeek | Adapted policy: trigger ratio 0.55, headroom 2,048, retain ratio 0.08, summary cap 384, route output cap 512 | Five complete `start`/`summary`/`end` transactions preserved the three original facts. At seven complete compactions, a richer final check retained Nora, Tuesday, codeword, QA-43, and 12 hours but answered “not specified” for Vega, `atlas.csv`, `7c4e`, and orange. Its saved summary omitted those four details. A fresh **no-compaction** control on the same 7B model recalled all nine, so the loss occurred along this repeated-compaction path; this one run does not separate model summarization from retention-policy effects. |
| 30B/32K, DeepSeek with normal tools | Adapted policy: trigger ratio 0.5, headroom 4,096, retain ratio 0.12, summary cap 1,024, route output cap 768 | Five compactions and keyed answers returned all nine values, but the agent created `project_facts.txt` on turn 6 and read it later. This measures agent use of external memory, **not** pure compaction retention. The tool calls and file are preserved in the receipt. |
| 30B/32K, DeepSeek with model-facing tools disabled | Same policy, plus an explicit plugin patch disabling shell, filesystem, web, delegation, and other model-facing tools | Seven complete compactions over 36 turns preserved all nine values in every saved summary and every keyed answer. The workspace stayed empty and no tool call appeared. A stricter blind session introduced and corrected the nine values in its first two turns, made five complete compactions with only `ACK` replies between them, and recalled all nine once at turn 19. No intermediate answer refreshed the facts in that blind case. |

The 32K and 16K runs change **both** the model and the context size. They show that the 30B/32K combination handled this richer case better; they do not establish which change caused the improvement. DeepSeek's shipped 65,536-token headroom is too large for either context, so its compaction policy was explicitly adapted for these mechanics trials. These are not default-policy passes.

## Summary-cap boundary on the 30B/32K no-tools session

The no-tools repeated-check session continued past seven compactions. Its first nine summaries all included the nine facts, but summary output grew from 260 to 1,004 tokens as it copied more routine notes. The tenth attempt, at turn 48, recorded `compaction/start` and `compaction/end` with error `summarization truncated at the token cap (incomplete checkpoint)` and **no** `compaction/summary`. The same failure repeated at turns 49 and 50. Turn 48 still produced a correct answer, so a good final answer or an `end` marker alone would have falsely scored compaction as successful. Turn 50 ended `max-tokens` and the headless process exited 1.

One separately labeled recovery turn changed only the summary cap from 1,024 to 1,536. In the same persisted session, turn 51 produced a complete `start`/`summary`/`end` transaction with a 1,159-token summary and answered all nine values correctly. The complete no-tools history therefore contains **10 successful compactions and three failed attempts**; the clean result before the first failure was nine successes. Enlarging the cap recovered this one case, but does not solve unbounded growth. A production policy should keep salient facts while dropping routine filler, then test that bounded summary across many cycles.

## What this changes in the test design

1. Count a compaction only when a matching summary and error-free end are persisted. Report failed attempts even if the user turn exits 0 or answers correctly.
2. Run a no-tools lane to isolate conversation compaction. File-backed memory is a separate capability worth testing, but cannot be counted as summary retention.
3. Include a blind early-fact case with one final recall check. Repeated intermediate answers can refresh facts and make a weak summary look reliable.
4. Score fact retention, superseded-value rejection, final-answer completeness, summary size, and model-call cost separately. Repeat with other models and a same-model context comparison before attributing the 16K/32K difference to context size alone.
