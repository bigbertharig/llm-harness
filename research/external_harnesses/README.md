# Optional external-harness research archive

This directory contains the isolated adapters, comparison runners, fixtures,
and focused tests for Pi, DeepSeek Harness, OpenCode, Nanobot, OpenAI Codex, and
Hermes Agent. They are retained as research references, not as Big Bertha's
runtime.

The whole directory is deletion-safe. Runtime source under `tools/` and
`mcp_servers/`, plus the default `tests/`, may not import it or depend on one of
its paths. The normal `python3 -m pytest` run does not collect these tests. Big
Bertha's active model loop is `tools/project_agent.py`.

These scripts preserve their historical result formats. To run one from the
repository root, make both the product tools and this directory importable:

```bash
PYTHONPATH=tools:research/external_harnesses \
  python3 research/external_harnesses/comparison_short_control.py pi --run-id UNIQUE_ID
```

Candidate-specific dependencies remain isolated from the project virtual
environment; see `candidate_controllers/requirements.txt`. Archived tests can
be run explicitly with:

```bash
PYTHONPATH=tools:research/external_harnesses \
  python3 -m pytest -q research/external_harnesses/tests
```

The archive is not part of release validation. If a useful behavior is adopted,
implement it in the project-owned runtime and add deterministic tests there.
