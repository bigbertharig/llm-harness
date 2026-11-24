# Qwen3.8-27B sampler and tool-contract trial

Date: 2026-11-24

This is a three-cell supervised Harness trial, not a general model ranking. Every cell used the same
Qwen3.8-27B Q4_K_M route, read-only workspace tools, reconciliation-audit assignment, 1,536-token
output cap, ten-call tool budget, and 300-second deadline. Raw local receipts are under
`results/p1_qwen38_sampler_ab_20261124/`.

## Why this trial was run

The project-agent baseline forced temperature zero for every model. The official
[Qwen3.8-27B model card](https://huggingface.co/Qwen/Qwen3.8-27B) recommends:

- thinking: temperature 1.0, top-p 0.95, top-k 20, min-p 0, presence penalty 0, repetition penalty 1;
- non-thinking: temperature 0.7, top-p 0.8, top-k 20, min-p 0, presence penalty 1.5,
  repetition penalty 1.

The official deployment examples use the `qwen3` reasoning parser and `qwen3_coder` tool parser.
An upstream [long-prompt tool issue](https://github.com/QwenLM/Qwen3.8/issues/236) reports less stable
tool calling with thinking disabled, so the non-thinking profile is a candidate lane rather than a
universal default.

## Results

| Cell | Sampler | Contract | Tool calls / model turns | Duration | Trajectory result |
|---|---|---:|---:|---:|---|
| baseline | temperature 0 | v3 | 10 / 11 | 49.64 s | Broad searches; never opened a relevant test or implementation. |
| official non-thinking | 0.7, 0.8, top-k 20, presence 1.5 | v3 | 10 / 11 | 49.05 s | Opened the exact reconciliation test and identified the active-agent integration question, but did not inspect implementation. |
| official non-thinking | same | v4 | 10 / 6 | 67.71 s | Batched native calls (up to three observed), found exact recovery symbols and test evidence, but still chased literal case-number labels and proposed partially duplicate coverage. |

All three runs terminated cleanly and disclosed their evidence limitations. The v4 run used five tool
turns plus one final turn; the earlier runs used ten tool turns plus one final turn. Native batching
therefore improved action throughput, while judgment and evidence prioritization remained incomplete.

## Harness changes retained

- Sampling is an explicit, validated, receipt-visible run input. The default remains temperature zero,
  so other models do not change silently.
- Task contract v4 allows at most four independent native calls per turn. The text bridge remains one
  strict complete JSON call.
- Workspace guidance prioritizes named tests, source paths, and symbols over broad documentation
  searches and tells the model to open exact search hits directly.

The full deterministic suite after these changes passes 167 tests and 12 subtests. Do not promote one
Qwen sampler from a single run. Repeat this fixture and add a version whose prompt explicitly says the
case definitions after the colon are complete and must not be searched as literal labels. Then run the
same cells on Qwen 35 and Nemotron to separate model behavior from Harness behavior.
