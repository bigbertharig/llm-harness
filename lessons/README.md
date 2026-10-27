# Lessons

What the harness learns while it runs, kept here so it carries across sessions and so benchmarking can read
it (benchmarking `scripts/active/collect_lessons.py` copies this folder; nothing here needs benchmarking to
run). Empty until the harness has code.

Planned files, one JSON object per line, append only:

| File | What |
|---|---|
| `sessions.jsonl` | per session: the model and profile used, context reached, compactions, retries, how it ended |
| `tool_calls.jsonl` | per model: tool-call format used (native, text, grammar) and how often calls parsed |

Benchmarking's model knowledge reaches the harness through the gateway's prepared roster. The gateway
imports benchmarking data into its own catalog; the harness reads the live roster through an API and
does not maintain a duplicate model-library import.
