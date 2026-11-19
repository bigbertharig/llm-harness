"""The suite catalog points at the existing runners and offline tests."""

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("suite_catalog", ROOT / "tools/suite_catalog.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SuiteCatalogTests(unittest.TestCase):
    def test_references_existing_lanes(self):
        catalog = json.loads((ROOT / "tools/suite_catalog.json").read_text())
        self.assertEqual(MODULE.validate(catalog, ROOT), [])

    def test_rejects_missing_runner(self):
        catalog = json.loads((ROOT / "tools/suite_catalog.json").read_text())
        catalog["live_lanes"][0]["runner"] = "tools/missing_runner.py"
        self.assertTrue(any("missing runner" in error for error in MODULE.validate(catalog, ROOT)))
