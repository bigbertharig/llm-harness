# Strata routes in harness mode

Updated 2026-11-03. This records the current gateway/rig integration and the
boundary a harness should implement. The managed Strata routes have passed
gateway smoke calls, but no candidate harness has completed a Strata-specific
compaction comparison.

## Runtime boundary

- Benchmarking's model_registry.json is the source of tested model and Strata
  pack metadata. The Pi gateway imports it into its own model_catalog.json
  with tools/generate_profiles.py. The gateway plans placement and presents
  a ready route such as gpu-rig/<profile>.
- The rig's llm_orchestration owns the Strata process, model packs, GPU,
  host-memory admission, readiness, stop, and lease. Strata is an inference
  backend; it does not change who owns the conversation.
- The harness reads GET /v1/rig/ready-roster, checks the served model and
  actual context_length, and calls the gateway's POST /v1/chat/completions
  with X-Require-Ready: true. It does not select a Strata memory tier or call
  model-management endpoints. A route can vanish after an unload; recheck
  it before use and handle HTTP 409 as a changed resource offer.

## Context and token accounting

The current Strata ready route advertises tokenizer_path: null. The
gateway's /tokenize endpoint returns HTTP 501 for that route. Existing
llama routes can expose a tokenizer URL, but a harness adapter must treat
that field as optional. For Strata, use a validated matching local tokenizer
if available on the Pi. Until exact counting is available, keep a
conservative input estimate and output reserve below the served context;
compare estimates with returned usage fields where present. Record the
estimate method in compaction receipts. Compact before a request that would
exceed the budget. A generation that stops at its output limit is incomplete
if it has no final answer; compaction cannot extend that same generation.

The existing tools/live_preflight.py records a skipped tokenizer check
when the route has no tokenizer path. This is an API smoke, not proof that
a candidate harness can compact accurately on Strata. A Strata harness
trial still needs near-window, repeated-compaction, and length-stop cases
using the actual ready route and recorded usage.

## Updating Strata

There are three separate updates:

1. A newly validated pack for a currently supported family: stage the
   files on the rig, run a Strata plan and smoke at the intended context,
   record sizes/paths/evidence in benchmarking's model registry, then run
   tools/generate_profiles.py in the Pi gateway. The harness consumes the
   resulting ready route without importing the model library.
2. A new Strata runtime release: stage and test it on the rig first.
   Today llm_orchestration/shared/scripts/rig/rig.py pins the control,
   components, and home paths under strata-v0.2.10; the registry's
   validated_version is descriptive metadata, not a runtime switch or
   enforced version check. Update those rig paths and any changed launch
   flags deliberately, rerun rig/gateway tests and managed smoke, then
   update the registry validation version and import the catalog.
3. A new family or changed API: rig spec_profile currently allows
   qwen and qwen36 only. Expand and validate that admission rule and
   launch arguments; check gateway routing, response fields, usage, and
   harness token accounting before offering it to agents.

This is an importable catalog and a stable harness-facing route, not an
automatic upstream Strata updater. A future Strata release should get a
staged compatibility pass; simply pulling its Git repo does not update the
running rig or establish that old packs, paths, and API behavior still work.
