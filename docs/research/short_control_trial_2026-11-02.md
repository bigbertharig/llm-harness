# Frozen short control trial: 30B/32K

Date: 2026-11-02 (America/Denver). Status: first shared-runner pilot, not a harness ranking.

## Resource and method

The Pi controller loaded the existing `coder-30b` interactive profile on GPU0. No new profile or registry entry was needed. `tools/live_preflight.py` passed for `gpu-rig/coder-30b` / `qwen3-coder:30b-a3b` at the served 32,768-token context; ready-only chat and tokenizer worked, a cold `chat-27b` route returned 409, and the rig profile stayed unchanged. Receipt: ignored `results/preflight_2026-11-02_coder30b.json` on the Pi.

`tools/comparison_short_control.py` owns one frozen three-turn fixture (`short-control-v1`, SHA-256 `a0f05e4e83bbac424c391585864d93b1d210ee2ef706f66d4e555216c90cb325`). Turn 1 gives nine facts, turn 2 corrects four, and turn 3 asks for all current values. The answer key requires Nora, Tuesday, `amber-birch-17`, Vega, `atlas.csv`, `7c4e`, orange, QA-43, and 12 hours, with no Mira, Friday, QA-42, or 18 hours. Turns 1-2 must answer only `ACK`. All candidates use an empty workspace, a concise common system instruction, no intended tools, the same ready route, and a declared 1,536-token output ceiling. The runner checks the ready roster before each turn and afterward; raw events, config, stderr, progress, fixture, and summary live in an isolated ignored run directory. It does not load a model.

This is a **short conversation control**. It does not pressure context, test compaction, prove exact request budgets, or establish a speed ranking. Candidate startup and process patterns differ. OpenCode's CLI omits an explicit finish event on many turns, so `exit 0` plus a final text event is weaker finish evidence than Pi's `stop` and DeepSeek's `completed` events. The current runner also lacks an offline fake-provider contract, gateway request trace, and candidate-wide usage/cached-prefill normalization.

## Results

| Candidate | Version | Independent three-turn sessions | Keyed result | Ready roster | Notes |
|---|---|---:|---|---|---|
| Pi | 1.4.0 | 3/3 passed | Nine current facts, no old values | Unchanged | RPC session; no tools enabled. |
| OpenCode | 2.1.4 | 3/3 passed | Nine current facts, no old values | Unchanged | CLI resumed the session across processes; finish-event visibility varies. |
| DeepSeek Harness | checkout `687f282e86` | 3/3 passed with plan mode disabled | Nine current facts, no old values | Unchanged | Headless session resumed across processes; explicit `completed` event. A fourth run confirmed the same result using self-contained fixture configs. |

Raw directories: `results/comparison_short_control_2026-11-02_v1/` (Pi and OpenCode; initial DeepSeek failure), `results/comparison_short_control_2026-11-02_v1_no_plan/` (corrected DeepSeek), `results/comparison_short_control_2026-11-02_v1_repeat_/`, `results/comparison_short_control_2026-11-02_v1_repeat_3/`, `results/comparison_short_control_2026-11-02_v1_selfcontained/` (DeepSeek config portability check), and `results/comparison_short_control_2026-11-02_v1_final/` (all three candidates with the final runner). The final runner passed all three again with zero model-facing tool events and an unchanged roster. The trailing underscore on one repeat ID came from PowerShell expanding a remote shell variable; it did not change the fixture or results. Keep that directory name in receipts rather than silently renaming it.

The initial DeepSeek no-tools patch still exposed `exit_plan_mode`. The model called it twice on turn 1 and then answered `ACK`. The runner failed and stopped the run even though the final text was correct. The corrected patch explicitly disables DeepSeek's `plan-mode` plugin; the reruns had no tool calls and passed. The initial receipt remains a valid **configuration/control failure**, not a three-turn semantic failure.

## Procedure improvements and next gates

The pilot runner and sanitized configs now live under `tools/` and `tools/comparison_fixtures/`; they do not read the ignored October receipt directories. Each invocation writes a fresh run directory and refuses a route/model/context mismatch. To make the comparison decision-grade, add these gates in order:

1. Add a deterministic fake OpenAI-compatible endpoint and record actual request headers, model ID, output cap, retries, overflow handling, session resume, and zero management calls. This should run without a GPU. Keep candidate setup failures distinct from answer failures.
2. Verify Codex's output ceiling at the request level. The six-candidate follow-up below now covers Codex and Nanobot on 30B/32K and Hermes on its separate 27B/65K route; do not merge those model/window blocks into one ranking.
3. Freeze a realistic long-conversation fixture and run native compaction policies first, with tuned policies in separate rows. Repeat real-model cases, grade final answers and checkpoint completion separately, and measure prompt/cached token cost.
4. Add local and remote MCP text-plus-structured and structured-only fixtures, delayed-job terminal wake-up, restart, transient error, and cold-route denial cases. The existing scorecard lists the current candidate-specific gaps.

The existing `coder-30b` and `chat-27b` profiles are adequate for these first blocks. A new profile is justified only if the gateway cannot offer a required served window, output budget, or model capability after measurement. Profile creation would change the resource being compared and needs its own pinned block.

## Six-candidate follow-up and controller split

The same frozen three turns now run through per-harness `tools/candidate_controllers/` modules. The runner owns the shared prompts, key, roster check, and score; each controller owns native config, session continuation, event translation, and isolated home/workspace. The upstream harness checkouts were not edited. After extracting the existing Pi, DeepSeek, and OpenCode drivers, one regression run per candidate passed the original fixture (same `a0f05e...` fixture SHA-256) under `results/short_control_2026-11-02_modular_smoke/`.

Nanobot and OpenAI Codex each passed one complete three-turn session on the same 30B/32K route under `results/short_control_2026-11-02_six_v1/`. Both returned exact `ACK` on turns 1 and 2, retained all nine corrected facts on turn 3, used no model-facing tools, and preserved the ready roster. Codex used its isolated Responses provider and native `exec resume`; Nanobot used one SDK session with its model-facing tool registry emptied by the test controller. These single runs add coverage but do not replace the three-repetition pilot for the original candidates.

Hermes ran the same prompts on its required `gpu-rig/chat-27b` 65,536-context route, with separate fixture metadata hash `04a5ce...`. Two independent runs are preserved under `results/short_control_2026-11-02_six_v1/hermes/` and `results/short_control_2026-11-02_six_repeat/hermes/`. Both retained all nine corrected facts and completed naturally without tools or a roster change, but returned `ACK.` on turns 1 and 2 instead of the exact required `ACK`. Both therefore **fail the frozen format check**. This is a repeated instruction-format failure, not a fact-retention failure. The different 27B model and 65K context prevent a direct numerical comparison with the 30B candidates.
