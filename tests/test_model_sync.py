"""Portable model-planning import contract checks."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import sync_model_library as importer  # noqa: E402


class ModelPlanningImportTest(unittest.TestCase):
    def test_projection_contains_planning_identity_not_loaded_state(self):
        projected = importer.projection(importer.DEFAULT_SOURCE)
        self.assertEqual(projected["schema"], "harness-model-library/1")
        self.assertTrue(projected["models"])
        self.assertTrue(projected["roles"])
        for model in projected["models"].values():
            self.assertNotIn("ready", model)
            self.assertNotIn("gpu_ids", model)

    def test_modified_source_is_rejected(self):
        source = json.loads(importer.DEFAULT_SOURCE.read_text(encoding="utf-8"))
        source["registry"]["models"].pop(next(iter(source["registry"]["models"])))
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / "export.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                importer.load_source(path)


if __name__ == "__main__":
    unittest.main()
