from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from harness_core import (EVENT_SCHEMA_VERSION, EVENT_TYPES, InvalidTransition, RunState,
                          ScriptedProvider, ScriptedProviderError,
                          decide_terminal, make_event, reduce_event, reduce_events)


def events(run_id, specifications):
    return [make_event(run_id=run_id, sequence=sequence, event_type=event_type,
                       payload=payload, **links)
            for sequence, (event_type, links, payload) in enumerate(specifications)]


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
    assert set(event["properties"]["type"]["enum"]) == EVENT_TYPES
    assert run["properties"]["schema_version"]["const"] == "harness-run/v1"


def test_reducer_accepts_complete_tool_lifecycle_without_mutating_prior_states():
    run_id = "run-tool"
    journal = events(run_id, [
        ("run.started", {}, {}),
        ("model.started", {"model_step_id": "model-1"}, {}),
        ("model.completed", {"model_step_id": "model-1"}, {"finish_reason": "tool_calls"}),
        ("tool.proposed", {"tool_call_id": "tool-1"}, {"name": "read_file"}),
        ("tool.validated", {"tool_call_id": "tool-1"}, {}),
        ("tool.approved", {"tool_call_id": "tool-1", "approval_id": "approval-1"}, {}),
        ("tool.executing", {"tool_call_id": "tool-1"}, {}),
        ("tool.committed", {"tool_call_id": "tool-1"}, {"argument_digest": "abc"}),
        ("tool.result_persisted", {"tool_call_id": "tool-1"}, {"artifact": "result-1"}),
        ("tool.result_delivered", {"tool_call_id": "tool-1"}, {}),
        ("model.started", {"model_step_id": "model-2"}, {}),
        ("model.completed", {"model_step_id": "model-2"}, {"finish_reason": "stop"}),
        ("run.succeeded", {}, {"reason": "completed"}),
    ])
    initial = RunState(run_id)
    started = reduce_event(initial, journal[0])
    final = reduce_events(run_id, journal)
    assert initial.phase == "new" and initial.next_sequence == 0
    assert started.phase == "running" and started.next_sequence == 1
    assert final.phase == "succeeded" and final.terminal_reason == "completed"
    assert final.tools[0].state == "result_delivered"
    assert final.completed_model_steps == ("model-1", "model-2")


def test_reducer_requires_repair_after_truncation_and_rejects_false_success():
    run_id = "run-truncated"
    prefix = events(run_id, [
        ("run.started", {}, {}),
        ("model.started", {"model_step_id": "model-1"}, {}),
        ("model.truncated", {"model_step_id": "model-1"}, {"finish_reason": "length"}),
    ])
    state = reduce_events(run_id, prefix)
    false_success = make_event(run_id=run_id, sequence=3, event_type="run.succeeded",
                               payload={"reason": "looks complete"})
    try:
        reduce_event(state, false_success)
    except InvalidTransition as exc:
        assert "complete model response" in str(exc)
    else:
        raise AssertionError("truncated output was accepted as success")

    repaired = [
        make_event(run_id=run_id, sequence=3, event_type="retry.scheduled", payload={}),
        make_event(run_id=run_id, sequence=4, event_type="retry.started", payload={}),
        make_event(run_id=run_id, sequence=5, event_type="model.started",
                   model_step_id="model-2", payload={}),
        make_event(run_id=run_id, sequence=6, event_type="model.completed",
                   model_step_id="model-2", payload={"finish_reason": "stop"}),
        make_event(run_id=run_id, sequence=7, event_type="run.succeeded",
                   payload={"reason": "repaired"}),
    ]
    for event in repaired:
        state = reduce_event(state, event)
    assert state.phase == "succeeded" and state.needs_repair is False


def test_reducer_rejects_gaps_wrong_links_and_illegal_tool_order():
    started_event = make_event(run_id="run-invalid", sequence=0, event_type="run.started")
    state = reduce_event(RunState("run-invalid"), started_event)
    duplicate_identity = {**started_event, "sequence": 1, "type": "input.queued"}
    cases = [
        make_event(run_id="run-invalid", sequence=2, event_type="model.started",
                   model_step_id="model-1"),
        make_event(run_id="another-run", sequence=1, event_type="model.started",
                   model_step_id="model-1"),
        make_event(run_id="run-invalid", sequence=1, event_type="tool.committed",
                   tool_call_id="missing"),
        duplicate_identity,
        {**make_event(run_id="run-invalid", sequence=1, event_type="input.queued"),
         "provider_private_state": "must stay in adapter"},
    ]
    for event in cases:
        try:
            reduce_event(state, event)
        except InvalidTransition:
            pass
        else:
            raise AssertionError("malformed event was accepted")


def test_scripted_provider_replays_payload_errors_and_malformed_shapes_exactly():
    script = ScriptedProvider([
        {"kind": "response", "payload": {"answer": "partial", "finish_reason": "length"}},
        {"kind": "error", "code": "transport_lost", "message": "reply lost", "retryable": True},
        {"kind": "response", "payload": {"unexpected": ["provider", "shape"]}},
    ])
    request = {"messages": [{"role": "user", "content": "test"}], "tools": []}
    first = script.complete(request)
    first["answer"] = "changed by caller"
    request["messages"][0]["content"] = "changed after call"
    assert script.requests[0]["messages"][0]["content"] == "test"
    assert first["finish_reason"] == "length"
    try:
        script.complete({"messages": []})
    except ScriptedProviderError as exc:
        assert exc.code == "transport_lost" and exc.retryable and str(exc) == "reply lost"
    else:
        raise AssertionError("scripted provider error was not raised")
    assert script.complete({"messages": []}) == {"unexpected": ["provider", "shape"]}
    script.assert_consumed()
    try:
        script.complete({})
    except AssertionError as exc:
        assert "unexpected request" in str(exc)
    else:
        raise AssertionError("extra provider request was accepted")
