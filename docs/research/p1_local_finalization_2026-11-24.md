# P1 local finalization regression

**Date:** 2026-11-24  
**Harness revision:** `47c77c8`  
**Fixture:** six ordered `search_workspace_text` calls followed by one tool-free final answer

## Result

The project-owned Harness preserved tools through all six bounded tool-capable turns and supplied a
separate seventh finalization turn to both local models. Each model made the six required calls in the
specified order, received the same evidence, began its answer with `SIX_CALL_FINALIZED`, reported the
five present symbols and one absent marker correctly, and released its child reservation.

| Model | Served context | Tool calls | Model steps | Duration | Outcome |
|---|---:|---:|---:|---:|---|
| Nemotron 3.5 Bolt 74B A9B | 262,144 | 6 | 7 | 59.03 s | Passed |
| Qwen 3.6 35B A3B XL | 65,536 | 6 | 7 | 27.05 s | Passed |

Qwen completed this single matched control 2.18 times faster. One trial does not establish a general
quality or reliability ranking.

## Receipts

- Nemo: `results/p1-nemo-six-tool-finalization-20261124T0715Z/summary.json`
- Qwen: `results/p1-qwen35-six-tool-finalization-20261124T0720Z/summary.json`

Both receipts contain 58 canonical events, six successful `mixed_mirrored` tool results, no format or
truncation repair, a successful terminal run, stable roster identity, and a released reservation.

## Failure converted into a regression

Before revision `47c77c8`, the Harness removed tools after the fifth tool-capable turn so the sixth
request could only attempt final synthesis. Nemo legitimately requested another repository search and
Gateway returned `shared model repeatedly requested a tool, but no tools were available for this turn`.
The preserved failed receipt is:

`results/supervised-nemo-dashboard-theme-escape-20261123T2240Z/summary.json`

The deterministic unit regression now enforces six tool-capable turns plus one tool-free finalization
turn. These two live local-model passes verify that the policy works through both shared serving modes.

## Next local work

Continue P1 historical-failure conversion with deterministic contracts first, then rerun the same
fixture on Qwen and Nemo only when model behavior is part of the failure. OpenRouter remains deferred
provider-adapter evidence after the local P2 suite is frozen.
