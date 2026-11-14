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

`target` accepts one MCP tool name or an exact list of names. The two-tool research fixture passes `['search_web', 'fetch_page']`; each controller limits native exposure to those tools where its harness supports a tool allowlist. OpenCode must leave its `execute` action available in this installed build for direct MCP tools to reach the model, while denying other named built-in actions. The shared runner verifies actual tool calls and order through the MCP receipt; connection or discovery alone is not a pass.

The current short-chat, six-server MCP, live-search, and two-tool research runners use this boundary. Long compaction, subagents, asynchronous jobs, denial, and restart still need frozen shared fixtures and candidate-specific controller methods; prior candidate-specific research receipts are not a matched six-harness suite.

The subagent adapter is `tools/gateway_subagent_mcp.py`, backed by `tools/gateway_subagent.py`. Its model-facing tool accepts `agent_type` (`coding` or `research`) and `task`; the controller supplies the parent route and receipt directory when launching the MCP server. The gateway manager decides which model and GPU to prepare and returns a ready route. The adapter runs a separate native child process with no delegation tool and keeps a per-child receipt. The direct parent MCP smoke is `tools/gateway_subagent_smoke.py`.

For a Codex dashboard cloud parent, launch the same adapter with `--cloud-parent --receipt-dir DIR`.
It advertises `delegate_local_task` with only `agent_type` and `task`, then requests a local route
from the gateway using `parent_route: cloud/codex`. The child still has no file tools. The dashboard
registers this server through its optional Codex app-server MCP configuration; a live round trip
remains to be verified after deployment.

For isolated harnesses, pass `--parent-route` and `--receipt-dir` in the MCP server launch command. This avoids dependence on how each harness forwards its process environment; the environment variables above remain available for direct use. The matched one-child comparison is `python3 tools/comparison_subagents.py CANDIDATE --run-id ID`, followed by `python3 tools/comparison_subagents.py summary --run-id ID` after all six candidates. The shared fixture is `tools/fixtures/subagent_mcp.py`, and the combined receipt is `results/ID/subagents/matrix.json`. Each candidate uses its own controller and a fresh result directory; a direct child baseline must pass before that candidate's native run.
