# OpenCode: native ready-only compaction trial

Date: 2026-10-29
Status: exploratory single candidate run; see the [scorecard](harness_scorecard_2026-10-29.md) for cross-candidate coverage.

The pinned OpenCode v2.1.4 ARM64 binary ran on the Pi with isolated config and data directories. Its custom OpenAI-compatible provider pointed at the externally prepared `gpu-rig/coder-30b` route (`qwen3-coder:30b-a3b`, actual context 32,768) and sent `X-Require-Ready: true`. The driver checked the ready roster before each turn and afterward; it did not change. The provider advertised a 1,536-token output limit. Agent permissions denied tools, and the recorded run emitted no tool calls. OpenCode's automatic compaction remained enabled with its native defaults.

The 23-turn blind fixture introduced nine project facts at turn 1, corrected four at turn 2, and then sent routine filler. The only fact recall was at turn 23. That run completed in 108.3 seconds with 9/9 current values in the final answer. The same persisted session then continued for nine more turns, with a second blind recall at turn 32. Its answer again gave 9/9. No command reported a model or session error.

The CLI's JSON stream did not surface compaction events, so the driver inspected the persisted `session_message` records in OpenCode's SQLite database. The 32-turn session contains **six** `type=compaction`, `status=completed`, `reason=auto` records. Every stored summary contains all nine current values. This demonstrates successful repeated native compaction in this synthetic case; the session was resumed across separate CLI processes. The model's quality and the harness's summary policy are intertwined, so this is case evidence, not an overall ranking.

Raw config, trial/extension drivers, roster checks, per-turn JSONL and stderr, summaries, the SQLite database, and the read-only database inspection script are in ignored `~/llm-harness/results/opencode_candidate_2026-10-29/`. The archive was verified against npm's SHA-512 integrity value before transfer. A later frozen comparison should use a common adapter contract and a realistic conversation alongside this pressure fixture.
