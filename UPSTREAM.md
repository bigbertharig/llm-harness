# Upstream

Reference clones on the Pi, outside this repo. Not forked yet; record the fork commit here when it
happens, and every change pulled in since.

| Project | License | Clone | Commit | Date |
|---|---|---|---|---|
| deepseek-ai/deepseek-harness | MIT | `~/deepseek-harness` | `687f282e86` | 2026-10-17 |
| openai/codex | Apache-2.0 | `~/codex` (partial clone, `--filter=blob:none`) | `7389eebf45` | 2026-10-20 |
| earendil-works/pi | MIT | `~/harness-references/pi` (shallow partial clone) | `6c384aa30f61` | 2026-10-26 |
| anomalyco/opencode | MIT | `~/harness-references/opencode` (shallow partial clone) | `f97f82c96f6e` | 2026-10-26 |
| NousResearch/hermes-agent | MIT | `~/harness-references/hermes-agent` (shallow partial clone) | `e5f2b15300a3` | 2026-10-26 |
| HKUDS/nanobot | MIT | `~/harness-references/nanobot` (shallow partial clone) | `23c4acc21609` | 2026-10-26 |

The research summary reviewed DeepSeek Harness at its 2026-09-29 commit and Codex at its 2026-09-30
commit; the deep dive (2026-08-14) used `47f943859b` (2026-08-13). Check findings against the
current clones before relying on them.

Licensing when code is copied: keep DeepSeek's MIT notice; keep Codex's Apache-2.0 license text and
NOTICE on anything taken from it, and mark changed files.

The four 2026-10-26 checkouts are research references, not installed or run. They were downloaded
as shallow partial clones on a networked workstation and copied to the Pi because the Pi could not
reach GitHub over HTTPS during this session. Current working-tree files are present; older history
and some unneeded blobs are not. Record a new commit here if any reference is refreshed.

Refresh:

```bash
git -C ~/deepseek-harness pull --ff-only
git -C ~/codex pull --ff-only
```
