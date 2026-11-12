# Shared 35B subagent trial ? 2026-11-12

The parent harness uses the resident Qwen3.6 35B-A3B model on GPU0. The manager attaches a fresh 1060 chat for `delegate_task` on demand, then detaches it. The model weights stay resident. The production MCP tool also offers `codex_terra` and `codex_luna` as bounded online children after checking the connected Codex account's model list. All calls use the gateway's OpenAI-shaped chat and Responses adapters.

## Evidence

The scored fixture asks the parent to delegate a hidden arithmetic problem, verify the child's answer, and return 42. Each harness had a fresh parent chat. The first full matrix is `results/shared35_six_20261112_v1/subagents/matrix.json`. These are correctness/tool-flow probes, not speed or quality benchmarks.

| Harness | First matrix | Later retest | Observation |
| --- | --- | --- | --- |
| Pi | Pass | ? | Delegated and verified. |
| DeepSeek | Fail | Pass | First child answered 48; later fresh-chat run passed. |
| Nanobot | Pass | ? | Delegated and verified. |
| OpenCode | Pass | ? | Fixture passed; transcript includes verbose tool-wrapper text. |
| Codex | Fail | Pass | First run needed Responses handling; fenced tool-call repair enabled a later pass. |
| Hermes | Fail | Fail | Did not complete a valid delegate call; after wrapper handling, retry timed out. |

Retest receipts: `results/shared35_behavior_retest_20261112_v1/subagents/deepseek/`, `results/shared35_codex_fence_20261112_v1/subagents/codex/`, and `results/shared35_hermes_wrap_20261112_v1/subagents/hermes/`. The direct local child receipt `results/shared35_direct_child_20261112_v5/summary.json` shows parent on GPU0, child on GPU2, answer 42, stable roster, and release. Direct Codex child receipts `results/codex_luna_direct_child_20261112/` and `results/codex_terra_direct_child_20261112/` both answered 42. `results/production_mcp_smoke_20261112/` exercised all three candidate IDs through the production `delegate_task` MCP tool.

## Contract and limits

The parent supplies only `agent_type`, `task`, and optionally `candidate_id`; the manager chooses the local card. The child cannot delegate again. Local child sessions use Pi with tools disabled. Online Codex children run in an isolated read-only ephemeral workspace and are instructed not to use tools. The gateway route supports bounded text and function calls via OpenAI-shaped Chat Completions and Responses; it buffers streaming output and is not a complete OpenAI implementation. Resident chats require stable IDs and aligned histories. The dashboard still calls the model directly and has not yet been wired to launch a harness. Hermes needs a separate tool-call compatibility investigation before it can be treated as supported on this model.
