# llm-harness

The agent harness for the local rig: the software around one model. It builds the prompt and
context, defines and runs tools, compacts long histories, keeps sessions, retries, and hands
subtasks to other models. It does not know about GPUs.

Status (2026-10-23): started, no code yet; on GitHub since 2026-10-22. The research and lessons below
moved here from llm-gateway `docs/harness/` with their history. Build base: a fork of DeepSeek Harness,
with OpenAI Codex as the reference design (`UPSTREAM.md`).

**Start here:** the reading order below, then the backlog.

For candidate trials, use `docs/HARNESS_TEST_PLAYBOOK.md`: phased gates and receipts adapted from
benchmarking's new-model integration process. The live lane requires a model already ready through
the gateway route the candidate will use.

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

1. `docs/HARNESS_TEST_PLAYBOOK.md`: candidate onboarding, fixed-model comparison gates, and receipt shape.
2. `docs/research/harness_mode_contract_2026-10-26.md`: current design direction: the gateway and rig
   prepare model resources; the harness manages agent work within that fixed envelope.
3. `docs/research/harness_candidate_survey_2026-10-26.md`: a preliminary shortlist and the comparison
   needed before treating any candidate as the best fit for the rig.
4. `docs/research/harness_comparison_test_design_2026-10-26.md`: a fixed-model conversation and
   compaction comparison protocol; design only, with no model integration yet.
5. `docs/research/async_tool_completion_contract_2026-10-27.md`: script output, durable completion
   events, and agent wake-up without repeated model polling.
6. `docs/research/harness_research_summary_2026-09-30.md`: the earlier recommendation (DeepSeek Harness fork
   and own as the backbone, Codex as cloud escalation and remote-attach reference, an MCP escape
   hatch), lessons, next steps.
7. `docs/research/deepseek_harness_research_2026-08-14.md`: what DeepSeek Harness does and what stays
   in our own code; its compaction section is the reference for long chats.
8. `docs/lessons_bench_checkpoint.md`: what the bench-checkpoint runs showed about context size,
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
5. **Prepared roster adapter:** accept the gateway's ready model routes and served limits, then expose
   them to the chosen harness as model options or subagents. Verify model identity and readiness; do not
   generate a second offer from the benchmarking registry.
6. **Gateway as dispatcher** (llm-gateway work): per-profile queue, queue depth in status, cancel on
   disconnect.
7. **Later:** durable leader on the rig side with remote attach (Codex `app-server-daemon` design),
   MCP server for the rig, a ledger of outcomes feeding back into the roster.

## Boundaries

The repos keep their own responsibilities. Benchmarking publishes tested model knowledge; the gateway's
existing importer takes in that knowledge and publishes model routes. Gateway and orchestration prepare
the rig and report which routes are actually ready. The harness consumes that prepared roster through a
gateway API. It needs model identity, served context and output limits, tool-call capability, and
availability; it does not need a separate copy of benchmarking's model library.

The harness writes what it learns to `lessons/` (see `lessons/README.md`). Benchmarking copies those
lessons when requested (`scripts/active/collect_lessons.py`). At runtime the harness talks only to the
gateway's inference and roster APIs, not to another repo's files or llama-server ports.

## Rules

- The harness talks to models only through the gateway API, never to llama-server ports or the rig.
- Model routes come from the gateway's prepared roster, never typed into agent code or inferred from
  benchmarking roles. A benchmark model ID used in a test plan is not automatically a ready gateway route.
- This repo is public: no keys, hostnames beyond the 10.0.0.x rig network, or private project notes.
- Keep upstream code out of this repo until the fork exists; record what is used in `UPSTREAM.md`.
