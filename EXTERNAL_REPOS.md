# External repositories

The [four-repo map](README.md#where-it-sits) explains our internal boundaries.
This page identifies outside projects used as a build base, evaluated as
references, or integrated through the gateway. Last checked: 2026-11-15.

| Upstream | Relationship | Checkout / detail |
|---|---|---|
| [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) | Planned fork and build base; candidate controller under test | `~/deepseek-harness`; exact reviewed revision in [UPSTREAM.md](UPSTREAM.md). |
| [openai/codex](https://github.com/openai/codex) | Reference design for agent sessions and remote attach, not the local build base | `~/codex`; [UPSTREAM.md](UPSTREAM.md). |
| [earendil-works/pi](https://github.com/earendil-works/pi), [anomalyco/opencode](https://github.com/anomalyco/opencode), [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent), [HKUDS/nanobot](https://github.com/HKUDS/nanobot) | Candidate and design references; research checkouts, not deployed runtimes | `~/harness-references/`; revisions and limitations in [UPSTREAM.md](UPSTREAM.md). |
| [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp), [Niko1221/Strata](https://github.com/Niko1221/Strata) | Model runtimes reached through llm-gateway; the harness consumes their advertised API and does not install them | Runtime ownership: [llm-gateway](https://github.com/bigbertharig/llm-gateway/blob/main/EXTERNAL_REPOS.md). Strata API observations: [integration note](docs/research/strata_harness_integration_2026-11-03.md). |
| [searxng/searxng](https://github.com/searxng/searxng) | Local search service consumed by `rig_search`; not the harness build base | [rig_search README](mcp_servers/rig_search/README.md). |

The existing [UPSTREAM.md](UPSTREAM.md) is the revision ledger for harness
research clones; update it when those clones move. The Strata source checkout
is tracked with the runtime owners, not as a harness fork.

## Checking for updates

The source links above are the upstream projects. A local checkout or release
pin is a snapshot, not an automatic update. For a checkout, run
`git -C PATH status --short --branch`, then `git -C PATH fetch origin` and
`git -C PATH log --oneline HEAD..origin/BRANCH` (replace PATH and BRANCH from
the table or the checkout's `git branch -r`). Review release notes and changes
before changing a deployed binary, model recipe, or benchmark baseline. Record
the new source revision and the validation receipt here when adopting it.
