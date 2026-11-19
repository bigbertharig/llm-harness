# Shared tool families

The Harness registry (`tools/tool_registry.json`) is the source of truth for tool identity, purpose, ownership, origin, and current bundle. `category` describes the job (search, local information, delegation, external, diagnostics); `origin` describes whether the capability is a rig tool or reaches another service; `family` is its current toolkit; `source_bundle` preserves where it began. The top-level `bundles` list includes provider toolkits even before their native tools have been audited. These fields do not grant permission. The generated dashboard catalog is a projection, and Gateway still chooses which surfaces a Chat or Coding turn may use.

| Family | Current surfaces | Availability |
| --- | --- | --- |
| `internal` | `rig_search`, `local_agents`, `gateway_reset`, `rig_info`, `workspace_read`, `workspace_git`, `local_rag_fixture`, `local_control`, `private_control` | Eight dashboard surfaces; the RAG fixture is a prototype. Chat and Coding have different allowlists. |
| `google` | `google_workspace` | Shared read-only Gmail and Drive adapter; disabled until the dedicated account completes OAuth. Chat only. |
| `daedalmap` | `daedalmap` | External MCP discovery record; no dashboard grant. |
| `deepwiki`, `openai`, `cloudflare` | One documentation surface each | Observed integrations; no dashboard grant. |
| `github` | `github_public` | Public, read-only repository metadata, directory paths, source text, and filename lookup at a pinned commit. Chat only. Local Git inspection remains in `workspace_git` for Coding; it does not access GitHub. |
| `codex`, `claude` | None in the shared registry | Provider adapters own authentication, inference/session handling, and provider-only capabilities. Their built-in tools are not assumed to work for local models. |

## Model-neutral tools

Gateway passes Harness MCP schemas and calls to local models and to its Claude API adapter. Codex dashboard sessions receive the same Harness MCP servers. The model sees the same tool name and argument contract. `workspace_read` and `workspace_git` are the first provider-neutral replacements for basic local file discovery/read and Git status/log/diff. Their access is limited to the selected Coding workspace. Chat gets public GitHub repository reads through `github_public`, without local workspace access. The local Git adapter accepts no arbitrary command, limits output, and only allows a per-file diff for a visible tracked path.

Provider tools begin in their source bundle. When a capability can be expressed as a bounded Harness operation with the same semantics for every model, move its canonical entry to `internal` and retain its original `source_bundle` for provenance. The provider copy is removed from model-facing exposure in the same change. A temporary compatibility alias may exist only for an existing caller and must resolve to the canonical implementation; it is never advertised beside the new tool. This prevents two competing search, email, or file tools from appearing to a model. Keep provider-specific tools for authentication, session recovery, and features that truly require that provider. Shell execution, edits, email sending, Drive writes, and GitHub mutations need separate permission and review contracts; none are implied by this inventory.

For example, `google_workspace.search_mail` is currently a Google-specific read tool. A future `search_email` would live in the shared toolkit, take a provider/account parameter, and preserve `source_bundle: google`. At promotion, stop exporting `search_mail` to models; do not leave both names active. If an existing saved workflow still calls `search_mail`, the bridge may map that old name to `search_email` internally until migration is complete.

Public repository inspection is deliberately in Chat: `inspect_github_repo` resolves a URL to one commit and returns metadata, root paths, and a bounded README preview; `list_github_directory`, `find_github_files`, and `read_github_file` then inspect selected paths at that same commit. These are CPU/network fetches, not a model-generated plan, and they never execute repository code. The model still decides which claims need checking and which files matter. GitHub API responses and repository text are untrusted task data. The adapter uses unauthenticated public API reads, limits response and text size, and reports truncation. Private repository access and GitHub mutations require separate grants and are not offered here.

The 2026-11-18 Pi smoke used `punkpeye/awesome-mcp-servers` at commit `5fb385c3c56a004eacad6a21cb446205c787926b`. The first implementation resolved metadata and root paths but could not read its large README through GitHub's ordinary JSON content response. The adapter now uses GitHub's bounded raw-content response for larger text files. The smoke then returned a README preview and a requested twelve-line range. This proves the fetch path for that public repository, not the quality of any later model assessment. Future upgrades should preserve the same model-facing names and add deterministic caching, path ranking, and durable fetch receipts if real research runs show they help.

## Promotion path

1. Record an integration candidate with its real owner, origin, family, and observed status. A candidate is not a live tool.
2. Implement the Harness MCP adapter and deterministic contract tests; bound inputs, output, time, and authority.
3. Add it disabled to the registry. Review data movement and Chat/Coding access, then enable the dashboard projection.
4. Import the generated catalog into Gateway and Benchmarking, and test one tool roundtrip for each model family that will use it.
5. Benchmark calling reliability and quality separately from catalog availability. Orchestration only receives model load instructions; it does not own this catalog.
