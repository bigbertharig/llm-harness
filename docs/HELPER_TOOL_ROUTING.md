# Preferred helpers for bounded tool tasks

The harness owns task definitions, allowed tools, child prompts, limits, and
results. Gateway owns current model offers, capacity, loading, and physical
placement. Benchmarking owns evidence that a candidate can finish a task.
The controlling chat keeps responsibility for checking the result.

`tools/tool_helper_policy.json` is the initial policy registry. Each task
names an agent role, an existing child tool profile, the exact allowed tool
names, a ranked list of benchmark-approved candidate IDs, and a direct-tool
fallback. `tools/tool_helper_policy.py` validates that every allowed tool is
approved in the harness tool registry and chooses among current Gateway
offers. It does not assign GPUs or grant a tool beyond the selected profile.

The first tasks are `workspace_lookup` and `public_source_lookup`. Their
preferred lists are deliberately empty until a model passes task-specific
tests, so selection currently returns `direct_tools`. A candidate is promoted
by adding its Gateway candidate ID and durable benchmark receipt to the
ranked list. The same task can later prefer a smaller, faster model without
changing the parent chat or hardware topology. A loaded candidate with no
worker slot is skipped; cold loading requires an explicit per-task policy.

Benchmark each candidate on fixed requests with known answer evidence, tool
trace validity, latency, token use, context depth, and failure recovery. The
test set should include unsuccessful searches and adversarial source text.
Promote the least costly candidate that meets the task's pass criteria and
retain the direct fallback. Raw `git status`, file reads, and exact searches
remain deterministic tool operations; use a helper when interpretation or
multi-step selection adds value. Google mail and Drive are outside these
initial task profiles and require their own authenticated provider boundary.

This module is a routing contract for future dashboard dispatch. It does not
silently intercept existing MCP calls. Integrate the selector with the
existing `delegate_task` surface after the first candidate has a benchmark
receipt and an end-to-end test confirms fallback and receipt presentation.
