"""Portable model-planning import contract checks."""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import sync_model_library as importer  # noqa: E402


class ModelPlanningImportTest(unittest.TestCase):
    def make_source(self, directory: Path) -> Path:
        payload = {
            "schema": "gpu-rig-model-library/1",
            "registry": {"models": {"fixture-model": {"status": "active"}}},
            "resolved_profiles": {"fixture-model": {"default": {
                "runtime": {"ctx_size": 8192}, "good_for": ["coding"]}}},
            "roles": {"roles": {"worker": {"model": "fixture-model", "profile": "default"}}},
            "load_recipes": {"recipes": {}},
            "subagent_catalog": {"candidates": {}},
        }
        digest = hashlib.sha256(json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")).hexdigest()
        path = directory / "export.json"
        path.write_text(json.dumps({"source_sha256": digest, **payload}), encoding="utf-8")
        return path

    def test_projection_contains_planning_identity_not_loaded_state(self):
        with tempfile.TemporaryDirectory() as work:
            projected = importer.projection(self.make_source(Path(work)))
        self.assertEqual(projected["schema"], "harness-model-library/1")
        self.assertTrue(projected["models"])
        self.assertTrue(projected["roles"])
        for model in projected["models"].values():
            self.assertNotIn("ready", model)
            self.assertNotIn("gpu_ids", model)

    def test_modified_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            source = json.loads(self.make_source(root).read_text(encoding="utf-8"))
            source["registry"]["models"].pop(next(iter(source["registry"]["models"])))
            path = root / "tampered.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                importer.load_source(path)


if __name__ == "__main__":
    unittest.main()
