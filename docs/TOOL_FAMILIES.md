# Shared tool families

The Harness registry (`tools/tool_registry.json`) is the source of truth for tool identity, purpose, ownership, origin, and current bundle. `category` describes the job (search, local information, delegation, external, diagnostics); `origin` describes whether the capability is a rig tool or reaches another service; `family` is its current toolkit; `source_bundle` preserves where it began. The top-level `bundles` list includes provider toolkits even before their native tools have been audited. These fields do not grant permission. The generated dashboard catalog is a projection, and Gateway still chooses which surfaces a Chat or Coding turn may use.

| Family | Current surfaces | Availability |
| --- | --- | --- |
| `internal` | `rig_search`, `local_agents`, `gateway_reset`, `rig_info`, `workspace_read`, `workspace_git`, `local_rag_fixture`, `local_control`, `private_control` | Eight dashboard surfaces; the RAG fixture is a prototype. Chat and Coding have different allowlists. |
| `google` | `google_workspace` | Shared Gmail, Drive, Docs, and Sheets adapter for the dedicated rig account. Chat and delegated Chat children only; write calls are confirmed, idempotent, and receipted. |
| `daedalmap` | `daedalmap` | External MCP discovery record; no dashboard grant. |
| `deepwiki`, `openai`, `cloudflare` | One documentation surface each | Observed integrations; no dashboard grant. |
| `github` | `github_public` | Public, read-only repository metadata, directory paths, source text, commit history, and revision comparison at pinned commits. Chat only. Local Git inspection remains in `workspace_git` for Coding; it does not access GitHub. |
| `codex`, `claude` | None in the shared registry | Provider adapters own authentication, inference/session handling, and provider-only capabilities. Their built-in tools are not assumed to work for local models. |

## Host control grant

The `local_control` and `private_control` MCP servers execute commands as the Pi service user, including its available sudo and SSH access. A conversation grant exposes the relevant command tool without a separate confirmation for each command. `local_control` has named Pi, rig, and worker targets; `private_control` reaches trusted hosts in the configured private subnet. The host tool now loads named targets, a private CIDR, and the SSH user from `HOST_CONTROL_CONFIG_PATH` or `~/.config/llm-harness/host-control.json`; see `tools/host_control_config.example.json`. A missing or invalid config fails closed. The conversation grant is the intended permission boundary for the trusted local network; commands do not request another approval. Keep remote browser and mobile grants separate, and treat tool output as untrusted data.

## Model-neutral tools

Gateway passes Harness MCP schemas and calls to local models and to its Claude API adapter. Codex dashboard sessions receive the same Harness MCP servers. The model sees the same tool name and argument contract. `google_workspace` is model-neutral even though Google remains its provider family: Qwen, Nemotron, smaller local workers, Codex, and configured API models all use the same operation names and Gateway receipts. `workspace_read` and `workspace_git` provide local discovery, working-tree inspection, commit metadata, historical file reads, and bounded revision comparison only in Coding. Chat gets public GitHub reads and the configured Google account without local workspace access.

Provider tools begin in their source bundle. A provider-specific surface can still be model-neutral: authentication and API execution stay behind Gateway while every model sees one canonical schema. Do not create competing provider and generic names for the same operation. Shell execution, edits, email sending, Drive writes, and GitHub mutations need explicit permission and review contracts; Google writes use required confirmation, request IDs, bounded arguments, and durable Gateway receipts.

For example, `google_workspace.search_mail` is currently a Google-specific read tool. A future `search_email` would live in the shared toolkit, take a provider/account parameter, and preserve `source_bundle: google`. At promotion, stop exporting `search_mail` to models; do not leave both names active. If an existing saved workflow still calls `search_mail`, the bridge may map that old name to `search_email` internally until migration is complete.

Public repository inspection is deliberately in Chat: `inspect_github_repo` resolves a URL to one commit and returns metadata, root paths, and a bounded README preview; directory, filename, file-read, commit, comparison, and file-history tools then inspect that repository using mandatory 40-character commit IDs. These are CPU/network fetches, not a model-generated plan, and they never execute repository code. The model still decides which claims need checking and which files matter. GitHub API responses, commit messages, diffs, and repository text are untrusted task data. The adapter uses unauthenticated public API reads, limits response and text size, and reports truncation. Private repository access and GitHub mutations require separate grants and are not offered here.

The 2026-11-18 Pi smoke used `punkpeye/awesome-mcp-servers` at commit `5fb385c3c56a004eacad6a21cb446205c787926b`. The first implementation resolved metadata and root paths but could not read its large README through GitHub's ordinary JSON content response. The adapter now uses GitHub's bounded raw-content response for larger text files. The smoke then returned a README preview and a requested twelve-line range. This proves the fetch path for that public repository, not the quality of any later model assessment. Future upgrades should preserve the same model-facing names and add deterministic caching, path ranking, and durable fetch receipts if real research runs show they help.

## Promotion path

1. Record an integration candidate with its real owner, origin, family, and observed status. A candidate is not a live tool.
2. Implement the Harness MCP adapter and deterministic contract tests; bound inputs, output, time, and authority.
3. Add it disabled to the registry. Review data movement and Chat/Coding access, then enable the dashboard projection.
4. Import the generated catalog into Gateway and Benchmarking, and test one tool roundtrip for each model family that will use it.
5. Benchmark calling reliability and quality separately from catalog availability. Orchestration only receives model load instructions; it does not own this catalog.
