# Open-source harness candidates: first-pass survey

Date: 2026-10-26
Status: historical first-pass survey, written before candidate trials. Subsequent trial results are recorded in the [test playbook](../HARNESS_TEST_PLAYBOOK.md) and linked research receipts. This survey is not a current performance ranking or runtime selection.

The resource boundary is the [harness-mode contract](harness_mode_contract_2026-10-26.md): the gateway and rig orchestration prepare and operate model resources; a harness runs agent work against an offered, ready roster without loading, unloading, resizing, or placing models. See the gateway's [manager contract](https://github.com/bigbertharig/llm-gateway/blob/main/docs/MANAGER.md) for manager-owned preparation and routing.

## Shortlist for a same-model trial

| Candidate | Why inspect it | Main question for this rig |
|---|---|---|
| [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) | Configurable model adapter, sessions, tools, and subagent backends; earlier research recommended a fork. | Can it be used with a fixed ready roster and a small local-model toolset without a large fork? Developer preview and breaking changes remain a maintenance concern. |
| [Hermes Agent](https://github.com/NousResearch/hermes-agent) | Chat Completions endpoints, delegation routing, session storage, compression, and explicit child concurrency. | Can its large tool and platform surface be reduced to a predictable, safe set for weaker local models and fixed resource limits? |
| [Nanobot](https://github.com/HKUDS/nanobot) | Python runtime, custom OpenAI-compatible providers, persistent gateway, tools, sessions, and subagents. | Is its delegation and model selection expressive enough for a supplied multi-model roster without altering provider/runtime state? |
| [Pi](https://github.com/earendil-works/pi) | Small agent loop with a deliberately small default tool set; custom models through an OpenAI-compatible adapter. Useful baseline for local-model tool reliability. | What must be added for durable remote sessions, hard policies, and multi-model delegation? |
| [OpenCode](https://github.com/anomalyco/opencode) | Mature agent profiles, model selection, tool permissions, and local-provider support. Plausible plug-and-play coding-agent candidate. | Can its server/SDK and permissions serve general agent tasks without carrying too much coding-product behavior? |

## References for specialized ideas

- [Goose](https://github.com/aaif-goose/goose): inspect MCP extension and provider patterns. Its own provider guide warns that local models without reliable tool calling cannot use its extensions, making this a demanding test for the smaller rig models.
- [OpenHands Agent Server/SDK](https://github.com/OpenHands/software-agent-sdk): inspect isolated execution, event streams, and durable agent-server contracts. Agent Canvas is a broader product than the harness core. Its local-model guide warns that tool-heavy tasks need a capable model.
- [Aider](https://github.com/Aider-AI/aider): inspect code-edit formats and repository context; treat it as a coding specialist rather than the general swarm controller.
- [Letta Code](https://github.com/letta-ai/letta-code): inspect durable memory and sessions if long-lived identity becomes a priority; do not assume those features improve short coding tasks.

## Evaluation needed before saying a candidate performs well here

Run the same prepared model(s), context window, task set, tool permissions, and output budget through each candidate. Include a long conversation with compaction, a constrained file task with external verification, error recovery, and delegation to a second already-ready model. Record success, tool-call validity, context/token use, cache behavior, latency, and whether any call changed model load state. Verify served model identity on every route. Use a no-load gateway policy once available; until then, pre-load and observe the roster and explicitly mark the test as an approximation of strict passive harness mode.

Feature lists and published scores from different models or tasks cannot establish a performance order for this local rig. The first trial should compare Pi or OpenCode as a compact baseline against DeepSeek and Hermes; Nanobot is the Python alternative. Keep the existing DeepSeek recommendation provisional until this evidence exists.

## Primary sources

- [DeepSeek Harness repo](https://github.com/deepseek-ai/deepseek-harness)
- [Hermes architecture](https://hermes-agent.nousresearch.com/docs/developer-guide/architecture) and [delegation configuration](https://hermes-agent.nousresearch.com/docs/user-guide/configuration)
- [Nanobot architecture](https://github.com/HKUDS/nanobot/blob/main/docs/architecture.md) and [providers](https://github.com/HKUDS/nanobot/blob/main/docs/providers.md)
- [Pi custom models](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md)
- [OpenCode agents](https://opencode.ai/docs/agents) and [providers](https://opencode.ai/docs/providers)
- [Goose providers](https://github.com/aaif-goose/goose/blob/main/documentation/docs/getting-started/providers.md)
- [OpenHands local LLM guide](https://github.com/OpenHands/docs/blob/main/openhands/usage/llms/local-llms.mdx)
