# Project-owned Harness direction

The Big Bertha Harness is the model-use implementation we are building. The six
tested external harnesses (Pi, DeepSeek Harness, OpenCode, Nanobot, OpenAI Codex,
and Hermes Agent) are reference implementations and comparison lanes. Passing a
trial does not make one of them the dashboard's engine. The [coverage register](research/harness_suite_coverage_2026-11-02.md) records what each has actually
demonstrated.

## How a feature enters the Harness

1. Name the behavior and its failure cases. Use the candidate trials to find
   examples, then define a model-neutral contract at the Gateway route and tool
   boundary. Keep provider-specific authentication and inference adapters thin.
2. Implement the shared behavior here. A tool belongs to one owning family in
   the registry; when a provider tool becomes generic, promote it to the shared
   family instead of maintaining competing public tools with the same job.
3. Test the deterministic tool or session contract first. Then run matched
   model trials for answer quality, token use, recovery, and latency. Preserve
   the candidate and project-owned receipts so the upgrade can be compared.
4. Expose the reviewed contract to Gateway Chat or Coding according to its
   permissions. Gateway keeps conversations and grants; Harness owns tool
   execution and model interaction; Orchestration owns physical admission.

The first feature lanes are tool discovery/permission checks, durable turn and
tool events, context accounting and compaction, delegation, bounded retries,
and interrupted-turn recovery. The existing MCP catalog and adapters are the
starting implementation, not a requirement to fork an external project.

## Tool suites and future work plans

Shoulders and arms are reusable advanced tool suites: predictable collection,
transformation, validation, and receipt steps with typed inputs and bounded
effects. A GitHub analyzer can pin a commit and collect files deterministically
before a model judges them. The Gateway may later compose these steps into a
work graph, assign the least costly capable model for each remaining judgment,
and retain evidence and retries. That is the direction for future plans;
Orchestration's Markdown brain/worker queue remains a separate legacy path.

The Harness does not choose GPUs, reserve context capacity, or schedule a plan.
It receives a ready route, tool grant, and task envelope, then produces turn,
tool, and completion receipts that Gateway can use to coordinate the next step.
