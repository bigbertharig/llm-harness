"""Gateway-free engine substitution through the public run boundary."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]

from harness_core.recorder import RunRecorder
from harness_core.run_api import SCHEMA as RUN_SCHEMA
from llm_harness.engine import InProcessEngine, SCHEMA, embedded_run_api, project_agent_engine
import project_agent

PROVIDER = {"schema": "harness-direct-provider/1", "route": "fixture",
            "model": "fixture-model", "context_length": 4096, "output_limit": 512}


def fake_engine(**kwargs):
    assert kwargs["provider"] == PROVIDER
    assert kwargs["gateway"] == "http://127.0.0.1:9999"
    assert kwargs.get("tool_profile", "none") == "none"
    recorder = RunRecorder(kwargs["journal_root"], kwargs["run_id"])
    recorder.emit("run.started", payload={"engine": "fixture"})
    recorder.emit("model.started", model_step_id="m1")
    recorder.emit("model.completed", model_step_id="m1", payload={"finish_reason": "stop"})
    recorder.emit("run.succeeded", payload={"reason": "completed"})
    return {"run": recorder.receipt(), "answer": "fixture answer"}


class EngineAdapterTests(unittest.TestCase):
    def test_alternate_engine_is_gateway_free_and_ordered(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = InProcessEngine(fake_engine, name="fixture", version="1.0")
            api = embedded_run_api(Path(directory), endpoint="http://127.0.0.1:9999",
                                   route="fixture", model="fixture-model",
                                   provider=PROVIDER, engine=engine)
            task = {"schema": RUN_SCHEMA, "request_id": "fixture-run", "prompt": "do work"}
            run_id = api.submit(task)["run_id"]
            self.assertEqual(api.submit(task)["run_id"], run_id)
            api.execute(run_id)
            status = api.status(run_id)
            self.assertEqual(status["state"], "succeeded", status)
            self.assertEqual(status["receipt"]["engine"],
                             {"schema": SCHEMA, "name": "fixture", "version": "1.0"})
            self.assertEqual([event["sequence"] for event in api.events(run_id)["events"]],
                             [0, 1, 2, 3])
            self.assertEqual(api.events(run_id, 2)["events"][0]["sequence"], 3)
            self.assertEqual(status["receipt"]["run"]["run_id"], run_id)
            restarted = embedded_run_api(Path(directory), endpoint="http://127.0.0.1:9999",
                                         route="fixture", model="fixture-model",
                                         provider=PROVIDER, engine=engine)
            self.assertEqual(restarted.status(run_id)["state"], "succeeded")

    def test_engine_version_grants_and_cancellation(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = InProcessEngine(fake_engine, name="fixture", version="1.0")
            with self.assertRaisesRegex(ValueError, "engine contract"):
                engine(engine_contract="harness-engine/2", run_id="x")
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                embedded_run_api(Path(directory), endpoint="http://127.0.0.1:9999",
                                 route="wrong", model="fixture-model", provider=PROVIDER,
                                 engine=engine)
            api = embedded_run_api(Path(directory), endpoint="http://127.0.0.1:9999",
                                   route="fixture", model="fixture-model",
                                   provider=PROVIDER, engine=engine)
            with self.assertRaisesRegex(ValueError, "grant"):
                api.submit({"schema": RUN_SCHEMA, "request_id": "denied",
                            "prompt": "x", "tool_profile": "workspace_git"})
            run_id = api.submit({"schema": RUN_SCHEMA, "request_id": "cancel",
                                 "prompt": "x"})["run_id"]
            self.assertEqual(api.cancel(run_id)["state"], "cancelled")
            api.execute(run_id)
            self.assertEqual(api.events(run_id)["events"], [])

    def test_embedded_project_agent_brokers_workspace_tool(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("Project-owned harness.")
            tool = "mcp__workspace_read__read_workspace_file"
            replies = iter([
                {"choices": [{"message": {"role": "assistant", "content": json.dumps({
                    "name": tool, "arguments": {"path": "README.md"}})},
                    "finish_reason": "stop"}], "usage": {}},
                {"choices": [{"message": {"role": "assistant",
                    "content": "README.md says the harness is project-owned."},
                    "finish_reason": "stop"}], "usage": {}},
            ])
            def complete(*_args):
                return next(replies)
            engine = InProcessEngine(
                lambda **kwargs: project_agent.run_agent(**kwargs, complete=complete),
                name="project-agent-fixture", version="1.0")
            server = {"name": "workspace_read", "tools": ["read_workspace_file"],
                      "definitions": [{"name": "read_workspace_file",
                                       "description": "Read a project file",
                                       "inputSchema": {"type": "object"}}],
                      "command": ["fixture"]}
            api = embedded_run_api(
                root / "state", endpoint="http://127.0.0.1:9999",
                route="fixture", model="fixture-model", provider=PROVIDER,
                engine=engine, tool_servers={"workspace_read": server},
                workspace_root=root)
            run_id = api.submit({"schema": RUN_SCHEMA, "request_id": "tool-run",
                                 "prompt": "Inspect the project",
                                 "tool_profile": "workspace_read"})["run_id"]
            with patch("project_agent.call_tool", return_value={
                "isError": False,
                "structuredContent": {"path": "README.md", "text": "Project-owned harness."}
            }) as broker:
                api.execute(run_id)
            status = api.status(run_id)
            self.assertEqual(status["state"], "succeeded", status)
            broker.assert_called_once()
            self.assertEqual(broker.call_args.args[1], "read_workspace_file")
            self.assertEqual(broker.call_args.args[2], {"path": "README.md"})
            self.assertEqual(status["receipt"]["tool_calls"], 1)
            events = api.events(run_id)["events"]
            self.assertEqual([event["sequence"] for event in events],
                             list(range(len(events))))
            self.assertIn("tool.committed", [event["type"] for event in events])

    def test_project_agent_is_public_in_process_engine(self):
        engine = project_agent_engine()
        self.assertEqual(engine.name, "big-bertha-project-agent")
        self.assertEqual(engine.version, "1.0")


if __name__ == "__main__":
    unittest.main()
