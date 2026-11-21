"""Offline checks for the saved short-control receipt audit."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ARCHIVE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("audit_short_control", ARCHIVE / "audit_short_control.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ShortControlAuditTests(unittest.TestCase):
    def write_receipt(self, root):
        run = root / "results" / "run-1" / "candidate-a"
        run.mkdir(parents=True)
        fixture = {"current": ["Nora", "Tuesday"], "old": ["Mira", "Friday"]}
        (run / "fixture.json").write_text(json.dumps(fixture))
        for name in ("ready_before.json", "ready_after.json"):
            (run / name).write_text(json.dumps({"data": [{"id": "route-a"}]}))
        import hashlib
        summary = {
            "run_id": "run-1", "candidate": "candidate-a",
            "fixture_sha256": hashlib.sha256(json.dumps(fixture, sort_keys=True).encode()).hexdigest(),
            "ready_roster_unchanged": True, "error": None,
            "rows": [
                {"turn": 1, "answer": "ACK", "finish_reason": "stop", "errors": [], "tool_calls": 0},
                {"turn": 2, "answer": "ACK", "finish_reason": "stop", "errors": [], "tool_calls": 0},
                {"turn": 3, "answer": "Nora Tuesday", "finish_reason": "stop", "errors": [], "tool_calls": 0},
            ],
            "verdict": {"passed": True},
        }
        path = run / "summary.json"
        path.write_text(json.dumps(summary))
        return path

    def test_valid_saved_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.write_receipt(Path(temp))
            result = MODULE.audit(path)
            self.assertTrue(result["audit_passed"])
            self.assertEqual(result["summary_path"], str(path.resolve()))
            self.assertEqual(len(result["summary_sha256"]), 64)

    def test_detects_fixture_and_roster_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.write_receipt(Path(temp))
            (path.parent / "fixture.json").write_text(json.dumps({"current": ["Mira"], "old": []}))
            (path.parent / "ready_after.json").write_text(json.dumps({"data": []}))
            result = MODULE.audit(path)
            self.assertFalse(result["audit_passed"])
            self.assertIn("fixture hash mismatch", result["findings"])
            self.assertIn("ready roster changed or was not recorded unchanged", result["findings"])

    def test_rejects_stored_pass_without_scored_answer(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.write_receipt(Path(temp))
            summary = json.loads(path.read_text())
            summary["rows"][2]["answer"] = "Mira Friday"
            path.write_text(json.dumps(summary))
            result = MODULE.audit(path)
            self.assertFalse(result["audit_passed"])
            self.assertIn("runner verdict disagrees with receipt evidence", result["findings"])
