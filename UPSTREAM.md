# Upstream

Reference clones on the Pi, outside this repo. Not forked yet; record the fork commit here when it
happens, and every change pulled in since.

| Project | License | Clone | Commit | Date |
|---|---|---|---|---|
| deepseek-ai/deepseek-harness | MIT | `~/deepseek-harness` | `687f282e86` | 2026-10-17 |
| openai/codex | Apache-2.0 | `~/codex` (partial clone, `--filter=blob:none`) | `7389eebf45` | 2026-10-20 |

The research summary reviewed DeepSeek Harness at its 2026-09-29 commit and Codex at its 2026-09-30
commit; the deep dive (2026-08-14) used `47f943859b` (2026-08-13). Check findings against the
current clones before relying on them.

Licensing when code is copied: keep DeepSeek's MIT notice; keep Codex's Apache-2.0 license text and
NOTICE on anything taken from it, and mark changed files.

Refresh:

```bash
git -C ~/deepseek-harness pull --ff-only
git -C ~/codex pull --ff-only
```
