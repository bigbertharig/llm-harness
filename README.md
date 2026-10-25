# llm-harness

The agent harness for the local rig: the software around one model. It builds the prompt and
context, defines and runs tools, compacts long histories, keeps sessions, retries, and hands
subtasks to other models. It does not know about GPUs.

Status (2026-10-23): started, no code yet; on GitHub since 2026-10-22. The research and lessons below
moved here from llm-gateway `docs/harness/` with their history. Build base: a fork of DeepSeek Harness,
with OpenAI Codex as the reference design (`UPSTREAM.md`).

**Start here:** the reading order below, then the backlog.

## Where it sits

| Repo | Owns | Start at |
|---|---|---|
| [llm-gateway](https://github.com/bigbertharig/llm-gateway) | the machines and the API: rig manager (leases, placement, model fit, runs, `rigctl`) and the OpenAI-compatible gateway on the Pi | `docs/MANAGER.md` |
| [llm_orchestration](https://github.com/bigbertharig/llm_orchestration) | parallel batch work (brain + workers on a task queue), the rig-side hardware scripts, CPU workers | `shared/workspace/CONTEXT.md` |
| [benchmarking](https://github.com/bigbertharig/benchmarking) | which models are good: `model_registry.json` (every model and how it loads), `model_roles.json` (which model per job), suites, results | `NEW_MODEL_INTEGRATION.md`, `MODEL_LIBRARY.md` |
| **llm-harness** (this one) | one model in an interactive loop: chat, tools, context, sessions, delegation | this README |

llm_orchestration is the "load many models, do parallel work" mode. This repo is the "load one model
and talk to it" mode, and later a leader that delegates to followers. Both sit on top of the gateway
and never touch cards directly. One user (the operator); no multi-user features.

## What it builds on (as of 2026-10-20)

The gateway runs on the Pi (`pi-gateway.service`, 127.0.0.1:8080, OpenAI-compatible):

| Endpoint | Use for the harness |
|---|---|
| `GET /v1/models` | the offered profiles as `gpu-rig/<id>`, each with `context_length` |
| `POST /v1/chat/completions`, `/v1/completions` | the model calls; a cold profile is loaded by the manager and the request is held until it is ready |
| `POST /tokenize`, `/detokenize` | exact token counts, routed by model |
| `GET /v1/rig/status` | per-profile state |
| `/v1/manager/...` | leases, claims, model loads (llm-gateway `docs/MANAGER.md`) |

- Context overflow comes back as OpenAI's `context_length_exceeded`, so the harness can react to it.
- Offered profiles: llm-gateway `tools/generate_profiles.py` (`OFFER`) writes `remote_profiles.json`
  from the benchmarking registry; today `chat-27b` (qwen3.6:27b, 65k), `gpt-oss-20b`, `coder-30b`,
  `devstral-24b`, `nex-split`, `coder-7b`. Tool calling: gpt-oss-20b passed all six native tool-call
  probes; coder-7b writes calls as text; nex-split misses `attempt_completion`.
- The gateway listens on loopback only and has no API key file yet; remote clients come later.
- Model choice belongs to benchmarking roles (llm-gateway `tools/role_model.py` resolves a role to a
  model). Do not hard-code model names here.

## Reading order

1. `docs/research/harness_research_summary_2026-09-30.md`: the recommendation (DeepSeek Harness fork
   and own as the backbone, Codex as cloud escalation and remote-attach reference, an MCP escape
   hatch), lessons, next steps.
2. `docs/research/deepseek_harness_research_2026-08-14.md`: what DeepSeek Harness does and what stays
   in our own code; its compaction section is the reference for long chats.
3. `docs/lessons_bench_checkpoint.md`: what the bench-checkpoint runs showed about context size,
   compaction, prompt caching, retries and exploration, as harness requirements.

The research names some files that have changed since: `model_task_library.json`,
`model_access.json` and `agents/model_assignments.json` were deleted on 2026-10-15 (the registry and
roles replaced them), the gateway moved from the rig to the Pi on 2026-10-17, and the `worker.py`
`max_tokens` fix is done (the cap comes from the model library).

## Backlog

1. **Fork and prune DeepSeek Harness** (research summary section 6): remove telemetry, confirm the
   build, add a `rig` profile with the gateway route and one chat preset.
2. **Chat first:** one model, one long conversation. llama-server reuses the cached prompt prefix,
   so only new tokens are processed; compaction rewrites the history and costs a full re-read. Compact
   rarely and in big chunks (DeepSeek defaults: threshold 0.8, retain 0.16). Measure prompt tok/s per
   profile first (llm-gateway `tools/model_check.py`). Returning to an old chat cheaply needs the
   host prompt cache for conversations (llm-gateway `docs/DESIGN_NOTES.md`, "on, bounded (build
   later)").
3. **Sessions:** append-only session log (`session-persistence-jsonl`) for resume and fork. A chat UI
   such as Open WebUI already stores its own history; the harness log is for agent sessions.
4. **Tool format per model:** run `bench-agent` (benchmarking `docker/bench-agent/`) on the offered
   profiles and pick native tool calls, text edits or GBNF per model.
5. **Roster generator:** registry + roles + loaded profiles -> the pi-ai route `models` list and one
   `tool-subagent` per lane, with model-identity checks (`/v1/models`).
6. **Gateway as dispatcher** (llm-gateway work): per-profile queue, queue depth in status, cancel on
   disconnect.
7. **Later:** durable leader on the rig side with remote attach (Codex `app-server-daemon` design),
   MCP server for the rig, a ledger of outcomes feeding back into the roster.

## Boundaries

All four repos run on their own; none reads another at runtime. Knowledge moves through two files per repo:

- **In, from benchmarking (to build):** an importer in this repo reads the benchmarking model library
  (registry and roles) and writes the harness's own model list, committed here; the harness runs from that
  copy and keeps running on the last import without a benchmarking checkout. The pattern is llm-gateway's
  `tools/generate_profiles.py`.
- **Out, to benchmarking:** `lessons/` (see `lessons/README.md`): what the harness learns while it runs.
  Benchmarking copies it when it wants (`scripts/active/collect_lessons.py`).
- **At runtime:** only the gateway's OpenAI-compatible API.

## Rules

- The harness talks to models only through the gateway API, never to llama-server ports or the rig.
- Model names come from this repo's imported copy of the benchmarking roles and registry (the importer
  above), never typed into code.
- This repo is public: no keys, hostnames beyond the 10.0.0.x rig network, or private project notes.
- Keep upstream code out of this repo until the fork exists; record what is used in `UPSTREAM.md`.
