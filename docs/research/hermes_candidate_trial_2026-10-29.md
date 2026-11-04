# Hermes Agent: 65K native compaction trials

Date: 2026-10-29
Status: exploratory; separate model/window block from the 30B/32K candidates.

The pinned Hermes Agent checkout (`e5f2b15300a3`) was installed from its `uv.lock` in an isolated Python 3.14 environment on the Pi. The source's direct dependencies conflict under plain editable `uv pip install`; its own lockfile and uv overrides resolve them. Its isolated `HERMES_HOME` configured a named OpenAI-compatible provider with `X-Require-Ready: true`, native compression defaults, no configured toolsets, and the actual served context. No model management was delegated to Hermes.

Hermes rejected the existing `gpu-rig/coder-30b` route at 32,768 context **before inference**, citing its built-in 64,000-token minimum. Gateway/orchestration then externally loaded the existing `chat-27b` profile: `qwen3.6:27b`, 65,536 context on the 3090. The ready-only smoke call passed. This is a separate model and context lane; its fact score must not be directly ranked against the 30B/32K runs.

The long blind fixture used the same nine early facts, four corrections, routine filler, and final recall structure. Hermes' first native compression completed in about 30.6 seconds. The second compression began later with a larger summary prompt and took about six minutes to finish while the GPU actively generated. The 180-second driver limit expired at turn 18 before that completion, so the client never reached final recall. The verified isolated Hermes gateway was stopped after the long call. The run is a **partial** result with a severe latency/turn-completion problem; it is not a proven fact-retention failure or failed compaction.

A shorter fresh-session lane reached one native compaction after turn 13 (about 31.8 seconds), then asked the blind final question at turn 15. Hermes returned the correct owner Nora, deadline Tuesday, codeword amber-birch-17, client Vega, artifact atlas.csv, checksum 7c4e, risk orange, release gate QA-43, and budget 12 hours: **9/9**. All 15 turns completed; the ready roster was unchanged. This is a pass for first-compaction fact retention on the 27B/65K case, with the separate long-call limitation above. It does not establish repeated-compaction reliability.

Raw config, Python drivers, before/after ready rosters, per-turn stream JSON and stderr, progress, `HERMES_HOME` logs/session data, installation receipts, and run logs are under ignored `~/llm-harness/results/hermes_candidate_2026-10-29/` and `~/harness-runtimes/hermes/`. The comparison follow-up should isolate why the second summary call generates so long on this local model and measure output tokens/latency before tuning Hermes' compression policy.

## Receipt reinspection, 2026-11-02

The retained `home/logs/agent.log` shows the first long-lane summary used an estimated 12,107 auxiliary prompt tokens and took 30.581 seconds. The second used 18,364 auxiliary prompt tokens (about 1.52 times the first) and took 364.325 seconds (about 11.9 times). It was still streaming at 300 seconds and then **committed successfully**: the log reports 21 messages reduced to 11 and about 12,384 rough tokens reclaimed. The CLI client disconnected at its 180-second limit while the model call continued, so the observed problem is turn latency and client deadline mismatch, not proof of a hung gateway or failed summary.

The telemetry records `aux_output_reservation: null` but no actual completion-token count for that summary. The disproportionate duration suggests generated output or a decode slowdown warrants investigation; this is an inference, not a measured cause. The next diagnostic should capture actual auxiliary output tokens, finish reason, streaming rate, and gateway usage for both summary calls under a bounded output budget, then repeat the same fixture. Keep the unmodified 364-second result as the native baseline.
