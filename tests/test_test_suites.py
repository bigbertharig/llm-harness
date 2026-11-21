"""Named test suites stay valid and cover every Harness test module."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests" / "suites.json"
PREFIXES = ("tests/", "mcp_servers/rig_search/tests/")


def test_named_suites_reference_existing_unique_test_modules():
    suites = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert suites
    for name, details in suites.items():
        assert name.isidentifier()
        assert isinstance(details.get("purpose"), str) and details["purpose"]
        tests = details.get("tests")
        assert isinstance(tests, list) and tests
        assert len(tests) == len(set(tests))
        for selector in tests:
            assert selector.startswith(PREFIXES) and ".." not in selector
            assert selector.endswith(".py") and (ROOT / selector).is_file()


def test_every_harness_test_module_belongs_to_a_named_suite():
    suites = json.loads(MANIFEST.read_text(encoding="utf-8"))
    covered = {selector for details in suites.values() for selector in details["tests"]}
    roots = (ROOT / "tests", ROOT / "mcp_servers" / "rig_search" / "tests")
    present = {path.relative_to(ROOT).as_posix() for directory in roots
               for path in directory.glob("test_*.py")}
    assert covered == present
