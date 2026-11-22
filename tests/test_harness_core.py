from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from harness_core import EVENT_SCHEMA_VERSION, decide_terminal, make_event


def test_terminal_policy_never_accepts_empty_or_truncated_output():
    assert decide_terminal(answer="", finish_reason="stop",
                           repair_attempted=False, can_repair=True).action == "fail"
    assert decide_terminal(answer="partial", finish_reason="length",
                           repair_attempted=False, can_repair=True).action == "repair"
    assert decide_terminal(answer="partial", finish_reason="length",
                           repair_attempted=True, can_repair=True).action == "fail"
    assert decide_terminal(answer="done", finish_reason="stop",
                           repair_attempted=False, can_repair=True).action == "succeed"


def test_canonical_event_has_ordered_identity_and_rejects_unknown_types():
    event = make_event(run_id="run-1", sequence=3, event_type="tool.committed",
                       tool_call_id="call-1", payload={"digest": "abc"})
    assert event["schema_version"] == EVENT_SCHEMA_VERSION
    assert event["sequence"] == 3 and event["tool_call_id"] == "call-1"
    assert event["occurred_at"].endswith("+00:00")

    try:
        make_event(run_id="run-1", sequence=4, event_type="provider.magic")
    except ValueError as exc:
        assert "unknown harness event type" in str(exc)
    else:
        raise AssertionError("unknown event type was accepted")


def test_versioned_json_schemas_are_present_and_parseable():
    import json
    root = Path(__file__).resolve().parents[1]
    event = json.loads((root / "schemas/harness-event-v1.schema.json").read_text())
    run = json.loads((root / "schemas/harness-run-v1.schema.json").read_text())
    assert event["properties"]["schema_version"]["const"] == "harness-event/v1"
    assert run["properties"]["schema_version"]["const"] == "harness-run/v1"
