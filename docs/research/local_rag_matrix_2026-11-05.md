# Local Chroma RAG comparison, 2026-11-05

This is the first local-only retrieval comparison across all six candidate harnesses and a Pi parent-model size slice. It uses one frozen eight-passage Disaster Clippy corpus and one `search_passages` MCP tool. The corpus contains source excerpts from `builditsolar` and `wiki_top_100`, selected by `tools/fixtures/build_local_rag_corpus.py`; its canonical SHA-256 is `a6fde974595df0ed460db22e06f048209e099aa16139c7ea209222ee6df37bf8`. The builder records source document IDs, source text hashes, offsets, titles, and URLs. The excerpt JSON is kept only in ignored `results/local_rag_fixture/rag_corpus_v1.json`, not committed to the public harness repo.

The local embedding model is the installed `all-mpnet-base-v2` (768 dimensions). The eight passages were re-embedded with it into an isolated Chroma 1.5.9 collection; the production Chroma stores were read only for inspiration and were never opened by the fixture server. The existing source-pack `_vectors_768.json` files declare `text-embedding-3-small`, so those vectors were not mixed with local-model query vectors. The fixture server ran on the Windows workstation with Sentence Transformers 6.0.1, bound to loopback, and was forwarded by SSH to `127.0.0.1:17021` on the Pi. Rig models reached only the Pi gateway and MCP proxy; they did not need internet. The service, tunnel, and all test model routes were stopped after the run. The rig manager reported six free GPUs.

## Controls and score

The frozen cases ask why batch solar heaters are drained in cold climates, what stopped an undershot water wheel, why the Moon does not fully cover the Sun in an annular eclipse, and what covers the Sun during a total eclipse when the search is filtered to `wiki_top_100`. Direct Chroma and MCP controls put the intended passage at rank 1 in all four cases, including the source filter. Every candidate attempt was preceded by a passing direct MCP baseline. The Windows direct-control receipt is `rag_direct_control.json` in the local fixture directory; the Pi MCP control receipts are under `results/rag_baseline_20261105`.

Candidate success requires 1–4 actual `search_passages` calls, the expected passage in a returned top-three result, the exact retrieved ID cited in the final answer, case-specific factual wording, the required source filter on every call in that case, a clean parent finish, and an unchanged ready roster. Search count, embedding-query time, full parent time, and one-line format are recorded separately. A repeated identical query is counted as another call. A correct answer with no observed retrieval call is not a pass. The original one-call scorer remains in `results/rag_six_30b_20261105`; it was too strict for legitimate query reformulation and was superseded before the matched matrix.

## Six harnesses

The matched run is `results/rag_six_30b_v2_20261105/local_rag/`. Five harnesses used `qwen3-coder:30b-a3b` at 32K. Hermes used its prepared `qwen3.6:27b` at 65K, so this is a harness integration matrix, not a pure same-model ranking.

| Harness | Passing cases | Observed issue |
|---|---:|---|
| Pi | 3/4 | Five water-wheel searches, including repeated identical queries, exceeded the four-call bound. |
| DeepSeek Harness | 4/4 | No scored failure. |
| Nanobot | 4/4 | No scored failure. |
| OpenCode | 4/4 | No scored failure. |
| OpenAI Codex | 4/4 | No scored failure; water-wheel query reformulation used multiple calls. |
| Hermes Agent | 4/4 after scorer adjudication | The original scorer missed the valid phrase “too far from Earth.” |

The original v2 receipts record 22/24 passes. `adjudication_v2.json` preserves those receipts and independently rescored the one Hermes wording false negative, yielding 23/24. The only substantive matrix failure is Pi's call-budget miss. This is one trial per harness and case. Do not infer reliability or a general ranking from these rates.

## Parent model size slice on Pi

The same four questions, corpus, tool, direct baseline, and corrected fact rule were used with published ready routes. Raw receipts and per-run matrices are under `results/rag_pi_{7b,14b,30b,74b}_v3_20261105/local_rag/`.

| Parent | Context | Pass | Tool mode and notable failure |
|---|---:|---:|---|
| Qwen2.5 Coder 7B | 16K | 1/4 | Text bridge; one complete `<function-call>` envelope was not recognized, and other cases had retrieval or final-answer errors. |
| Qwen2.5 Coder 14B | 16K | 3/4 | Text bridge; batch-heater JSON supplied `source: null`, which the advertised non-nullable schema rejected before execution. |
| Qwen3 Coder 30B A3B | 32K | 4/4 | Native calls. An earlier matched run had five repeated water-wheel searches; this repeat passed, showing variance. |
| Nemotron 3.5 Bolt 74B A9B | 16K | 3/4 | Native calls; water-wheel search loop made eight calls and hit the controller's 360-second deadline without a final answer. |

The 74B load occupied four GPUs during this run and was unloaded immediately afterward. These models differ in family, quantization, context, and placement, so the table is a model-by-harness behavior slice rather than a controlled parameter-count effect.

## Reproduction and next work

Rebuild the ignored corpus on the Windows workstation with `build_local_rag_corpus.py --source-root D:\disaster-backups-local --output rag_corpus_v1.json`. A rebuild on 2026-11-05 was byte-identical to the tested corpus. Start `local_rag_mcp.py` with explicit `--corpus`, `--model`, `--db`, and `--receipt-dir` paths using the Disaster Clippy virtual environment; run `--self-test` before serving. The tested service used `--bind 127.0.0.1 --port 17021`. Forward that port with `ssh -N -o ExitOnForwardFailure=yes -R 127.0.0.1:17021:127.0.0.1:17021 pi-wifi`, then run `python3 tools/comparison_local_rag.py CANDIDATE --run-id NEW_ID` on the Pi against ready routes. The direct MCP baseline gates every case. The run ID must be fresh.

The next harness improvement is a generic repeated-call guard and better handling of complete tool envelopes plus optional null fields. It should apply to any advertised MCP schema and be checked with multiple small models before adoption. Repeat this matrix several times after that change, record native versus bridged calls explicitly for every controller, and add a larger corpus with hard negatives and multi-passage questions. The eight-passage corpus confirms integration and elementary grounding; it is too small to measure broad retrieval quality.
