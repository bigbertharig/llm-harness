# Harness limits and candidate lessons

This is the active migration register for the project-owned Harness. Candidate
results are evidence for individual mechanisms, not an overall harness ranking.
The six archived implementations remain deletion-safe research references.

## Limit vocabulary

Always name the unit and enforcement layer. A token ceiling is not a character
ceiling, a Python string length is not an encoded byte length, and a client
deadline is not a model-server timeout.

| Limit | Current active value | Unit and enforcement |
|---|---:|---|
| Delegated task | 4,000 | Python characters, MCP request schema |
| Acceptance criteria / verification | 2,000 / 1,000 | Python characters, MCP request schema |
| Requested child output | 4,096 maximum, then clamped by ready route | tokens, project agent and Gateway roster |
| Model steps | 6 | completion calls, project agent |
| Tool calls | 12 ceiling, lowerable per task | executed calls, project agent |
| Compatibility batch | 4 | parsed proposals per turn; preferred prompt path is one call |
| Tool result / total evidence | 32,000 / 80,000 | UTF-8 JSON bytes, child policy |
| MCP response line | 131,072 | Python characters read by the text-mode stdio bridge |
| Child task deadline | 600 maximum | wall-clock seconds, project agent |
| One dispatched tool | 45 maximum inside the remaining task deadline | wall-clock seconds |
| Workspace file | 1,000,000 | filesystem bytes, read-only workspace server |
| Workspace excerpt | 6,000 default; 12,000 maximum | Python characters per call |
| Converted attachment input | 8 MiB | file bytes, attachment converter |
| Converted attachment text | 10,000 | Python characters, attachment converter |

Every project-agent receipt records the requested and effective output-token
limits, ready-route context and output ceilings, prompt sizes, tool budgets,
MCP line bound, deadline, and whether any completion ended at the output limit.
A final `finish_reason=length` is a failed incomplete answer, not success.
The loop permits one tool-free final-format repair with a deterministic
character target; a second truncation is terminal. Workspace tool receipts keep
returned path, line range, completeness, and truncation metadata so a parent can
audit claims of full-file coverage. The receipt also merges overlapping reads
into a per-file contiguous coverage summary and marks full coverage only when a
complete range reaches end-of-file.

Declared values still need boundary probes. Test one below, at, and above each
important boundary; record the exact request, response status, finish reason,
usage, encoded sizes, elapsed time, and whether work continued after the client
deadline. Never infer a server limit solely from a client-side rejection.

## Candidate mechanisms worth retaining

| Candidate | Observed success | Project-owned lesson |
|---|---|---|
| Pi | Strong local MCP results and successful small-model recovery through a strict whole-response text-tool bridge | Keep allowlisted schema validation, one generic format repair, native-versus-bridged receipt labels, and never extract calls from prose. This behavior is already adapted in the project loop. |
| DeepSeek Harness | Explicit `compaction/start`, `summary`, and error-free `end` transactions; tuned blind 30B/32K runs retained nine facts across repeated cycles | Make compaction a durable transaction. Count only complete checkpoints, retain failed attempts, and separate external-memory tests from no-tools retention tests. |
| OpenCode | Six native automatic compactions retained all nine corrected facts across a 32-turn blind extension | Persist bounded summaries and test superseded-value rejection. Do not copy its tool path: matched local MCP results were poor and unstable. |
| Nanobot | Simple isolated SDK sessions and persisted summaries made compaction loss directly inspectable | Preserve intermediate state even on bad outcomes. Do not copy its observed summarizer policy: later summaries dropped all nine facts and the final answer invented values. |
| OpenAI Codex | Durable thread resume, detailed tool/usage events, cache accounting, and a compatibility layer that normalized namespaced MCP declarations | Normalize provider events into one internal vocabulary, retain route/tool identity per turn, and distinguish terminal failure from recovered transport noise. Avoid retrying typed non-transient refusals. |
| Hermes Agent | Rejected an incompatible 32K route before inference, resumed sessions across commands, and retained nine facts after one 65K compression | Add capability preflight before spending inference, persist sessions independently of the client, and keep client deadlines distinct from continuing server work. Do not inherit its fixed 64K floor or unbounded compression latency. |

## Cross-candidate findings already adapted

- Direct protocol baselines gate every model trial; discovery alone is not a tool-use pass.
- Empty text plus valid `structuredContent` must remain model-visible. The active
  loop serializes the structured result instead of treating the call as empty.
- Tool names and schemas are normalized before inference, while execution still
  checks the server-side allowlist and arguments.
- Ready-only model identity, context, output limit, and before/after reservation
  state belong in the receipt.
- Assisted recovery and native success are separate metrics. A repair may improve
  production reliability without rewriting the original native result.
- A correct final answer does not erase a failed tool call, truncated output,
  incomplete compaction, fabricated evidence, or leaked reservation.

## Next ports

1. Add durable compaction transactions and a blind corrected-facts suite to the
   project-owned session layer before choosing a summary policy.
2. Add boundary probes for route output, task/request size, MCP line size, tool
   result bytes, total evidence bytes, and client-versus-server timeout behavior.
3. Normalize completion, tool, retry, compaction, cancellation, and recovery
   events into a versioned event log suitable for dashboard replay.
4. Add typed retry classification so authorization, schema, capacity, and
   not-ready refusals are not retried as transient transport failures.

Primary evidence: `docs/research/harness_suite_coverage_2026-11-02.md`,
`harness_scorecard_2026-10-29.md`, `small_window_compaction_trial_2026-10-28.md`,
`model_harness_context_matrix_2026-11-05.md`, and the individual candidate notes.
