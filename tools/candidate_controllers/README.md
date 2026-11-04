# Native candidate controllers

Each file owns one harness's isolated configuration, process or SDK call, session behavior, and native-event translation. The shared runners own prompts, direct baselines, answer keys, scoring, and durable receipts:

| Controller | Short chat | MCP and live search | Prepared route |
|---|---|---|---|
| `pi.py` | `run_short_control` | `run_pi` | `coder-30b`, 32K |
| `deepseek.py` | `run_short_control` | `run_deepseek` | `coder-30b`, 32K |
| `opencode.py` | `run_short_control` | `run_opencode` | `coder-30b`, 32K |
| `nanobot.py` | `run_short_control` | `run_nanobot` | `coder-30b`, 32K |
| `codex.py` | `run_short_control` | `run_codex` | `coder-30b`, 32K |
| `hermes.py` | `run_short_control` | `run_hermes` | `chat-27b`, 65K |

Use a fresh `--run-id` for every run. Every controller writes its own home/config and disposable workspace under that run's ignored `results/` directory. The model route must already be ready; controllers send `X-Require-Ready: true` and never call rig management. They do not edit any upstream harness checkout. Runtime dependencies may live in separate virtual environments or package installs under `~/harness-runtimes/`.

To upgrade a harness, update its pinned source/runtime independently, adjust only its controller if the native API changed, then rerun short chat, local marker, remote MCP, and search controls with new run IDs. Preserve old receipts and record the harness version and model block. A new candidate needs a controller implementing `run_short_control(out)` and the MCP signature `run_candidate(out, prompt, server, target, system)`; register it in the shared runners after its direct controls pass.

The current short-chat, six-server MCP, and live-search runners use this boundary. Long compaction, subagents, asynchronous jobs, denial, and restart still need frozen shared fixtures and candidate-specific controller methods; prior candidate-specific research receipts are not a matched six-harness suite.
