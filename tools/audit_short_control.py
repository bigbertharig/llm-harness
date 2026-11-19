"""Audit a saved short-control receipt without contacting the gateway or model."""

import argparse
import hashlib
import json
from pathlib import Path


FINISH_REASONS = {"stop", "end_turn", "completed", "process_exit_0"}


def audit(summary_path):
    summary_path = Path(summary_path).resolve()
    run_dir = summary_path.parent
    summary = json.loads(summary_path.read_text())
    fixture = json.loads((run_dir / "fixture.json").read_text())
    before = json.loads((run_dir / "ready_before.json").read_text())
    after = json.loads((run_dir / "ready_after.json").read_text())
    findings = []
    if summary_path.name != "summary.json" or summary.get("run_id") != run_dir.parent.name:
        findings.append("summary path and run_id disagree")
    if summary.get("candidate") != run_dir.name:
        findings.append("summary path and candidate disagree")
    fixture_hash = hashlib.sha256(json.dumps(fixture, sort_keys=True).encode()).hexdigest()
    if summary.get("fixture_sha256") != fixture_hash:
        findings.append("fixture hash mismatch")
    if before != after or summary.get("ready_roster_unchanged") is not True:
        findings.append("ready roster changed or was not recorded unchanged")
    rows = summary.get("rows")
    if not isinstance(rows, list) or len(rows) != 3:
        findings.append("expected exactly three scored turns")
        rows = []
    elif [row.get("turn") for row in rows] != [1, 2, 3]:
        findings.append("turn sequence is not 1, 2, 3")
    current = fixture.get("current")
    old = fixture.get("old")
    if not isinstance(current, list) or not current or not isinstance(old, list):
        findings.append("fixture answer keys are missing")
        current, old = [], []
    if rows:
        if any((row.get("answer") or "").strip() != "ACK" for row in rows[:2]):
            findings.append("early turn did not answer ACK")
        answer = (rows[-1].get("answer") or "").lower()
        if any(not isinstance(value, str) or value.lower() not in answer for value in current):
            findings.append("final answer is missing a current value")
        if any(isinstance(value, str) and value.lower() in answer for value in old):
            findings.append("final answer includes a superseded value")
        if any(row.get("finish_reason") not in FINISH_REASONS for row in rows):
            findings.append("a turn has an incomplete finish")
        if any(row.get("errors") or row.get("exit_code", 0) or row.get("tool_calls", 0) for row in rows):
            findings.append("a turn has an error or unexpected tool call")
    if summary.get("error"):
        findings.append("runner recorded an error")
    stored_pass = summary.get("verdict", {}).get("passed")
    if not isinstance(stored_pass, bool):
        findings.append("runner verdict is missing")
    elif stored_pass != (len(findings) == 0):
        findings.append("runner verdict disagrees with receipt evidence")
    return {
        "audit_passed": not findings,
        "candidate_passed": stored_pass,
        "summary_path": str(summary_path),
        "summary_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
        "fixture_sha256": fixture_hash,
        "findings": findings,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary", type=Path, help="existing results/<run-id>/<candidate>/summary.json")
    args = parser.parse_args()
    result = audit(args.summary)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["audit_passed"] else 1)


if __name__ == "__main__":
    main()
