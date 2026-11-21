"""The product Harness must not depend on optional external-harness research."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ROOTS = (ROOT / "tools", ROOT / "mcp_servers")
FORBIDDEN = (
    "candidate_controllers",
    "research/external_harnesses",
    "comparison_short_control",
    "comparison_mcp_matrix",
    "comparison_subagents",
)


def test_product_sources_do_not_reference_external_harness_archive():
    findings = []
    for directory in PRODUCT_ROOTS:
        for path in directory.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".json", ".mjs"}:
                continue
            text = path.read_text(encoding="utf-8")
            for marker in FORBIDDEN:
                if marker in text:
                    findings.append(f"{path.relative_to(ROOT)}: {marker}")
    assert findings == []


def test_default_test_tree_does_not_reference_external_harness_archive():
    findings = []
    for path in (ROOT / "tests").glob("test_*.py"):
        if path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8")
        for marker in FORBIDDEN:
            if marker in text:
                findings.append(f"{path.relative_to(ROOT)}: {marker}")
    assert findings == []
