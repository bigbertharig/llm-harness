# Harness suite catalog

`tools/suite_catalog.json` is a small index of the project-owned test entry points.
It does not select an external harness or start a model. `python3 tools/suite_catalog.py`
lists the offline suite and live lanes; `--check` verifies that their paths still
exist. The existing [test playbook](HARNESS_TEST_PLAYBOOK.md) defines comparison
gates, fixtures, and receipt requirements. The [suite coverage register]
(research/harness_suite_coverage_2026-11-02.md) records which lanes were actually
run and what their receipts established.

Run `python3 -m pytest -q tests` for deterministic contract tests. Live lanes
need an externally prepared ready route and unique run IDs. Check
each runner's `--help` and the playbook before a live run. Keep its raw receipt
under the local ignored `results/` tree and summarize the result in the owning
research note. A successful catalog check only means the named files exist;
it says nothing about model readiness or candidate behavior.

Add a lane to this catalog when it exercises the project-owned Harness through a
reusable runner and documented receipt contract. External-harness comparisons
are archived under `research/external_harnesses/` and intentionally excluded.

## Archived candidate receipt audit

`PYTHONPATH=tools:research/external_harnesses python3 research/external_harnesses/audit_short_control.py results/RUN_ID/CANDIDATE/summary.json`
reads one existing short-control receipt and prints a JSON audit with the
absolute summary path and its SHA-256. It does not contact the gateway. The
audit passes only when the receipt path matches its run and candidate IDs, the
saved fixture hash matches the runner's hash, before/after ready rosters match,
the three turns are ordered, early replies are `ACK`, the final reply contains
all current facts and no superseded facts, all turns finish successfully with
no errors or tool calls, and the runner's recorded verdict agrees. A failed
audit exits 1 and lists findings. The underlying `summary.json`, `fixture.json`,
and roster snapshots remain the durable evidence; the audit output identifies
the exact summary bytes it checked. This check verifies a saved short-control
receipt, not a new candidate result or a fresh gateway preflight.
