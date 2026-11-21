import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import project_agent


READY = {'object': 'ready_roster', 'version': 1, 'data': [{
    'id': 'gpu-rig/test', 'model': 'test:1b', 'state': 'ready', 'context_length': 8192,
    'output_limit': 512}]}


def packet(text, finish='stop', usage=None):
    return {'choices': [{'message': {'role': 'assistant', 'content': text},
                         'finish_reason': finish}], 'usage': usage or {}}


class ProjectAgentTests(unittest.TestCase):
    def test_tool_free_answer_uses_project_engine_and_ready_output_limit(self):
        seen = []
        def complete(_gateway, _route, _messages, max_tokens, _timeout, _key, _tools):
            seen.append(max_tokens)
            return packet('direct answer', usage={'completion_tokens': 3})
        with patch('project_agent.fetch_ready_roster', return_value=READY):
            result = project_agent.run_agent(
                gateway='http://gateway', route='gpu-rig/test', expected_model='test:1b',
                prompt='answer', agent_type='research', max_tokens=1000, complete=complete)
        self.assertEqual(result['engine'], 'big-bertha-project-agent')
        self.assertEqual(result['answer'], 'direct answer')
        self.assertIsNone(result['error'])
        self.assertEqual(seen, [512])

    def test_executes_allowlisted_tool_then_requires_final_answer(self):
        replies = iter([packet(json.dumps({'name': 'mcp__workspace_read__read_workspace_file',
                                           'arguments': {'path': 'README.md', 'start_line': 1,
                                                         'max_lines': 20}})),
                        packet('README.md says the harness is project-owned.')])
        seen_messages = []
        def complete(_gateway, _route, messages, _max_tokens, _timeout, _key, _tools):
            seen_messages.append(list(messages))
            return next(replies)
        server = {'name': 'workspace_read', 'tools': ['read_workspace_file'],
                  'definitions': [{'name': 'read_workspace_file', 'description': 'Read',
                                   'inputSchema': {'type': 'object'}}],
                  'command': ['fixture']}
        with tempfile.TemporaryDirectory() as temp, \
             patch('project_agent.fetch_ready_roster', return_value=READY), \
             patch('project_agent.call_tool', return_value={
                 'isError': False, 'structuredContent': {'path': 'README.md', 'text': 'owned'}}):
            result = project_agent.run_agent(
                gateway='http://gateway', route='gpu-rig/test', expected_model='test:1b',
                prompt='inspect', agent_type='coding', tool_profile='workspace_read',
                tool_server=server, workspace_root=Path(temp), complete=complete)
        self.assertIsNone(result['error'])
        self.assertEqual(result['tool_calls'], 1)
        self.assertEqual(result['model_steps'], 2)
        self.assertIn('Validated tool results', seen_messages[1][-1]['content'])

    def test_repeated_call_forces_one_tool_free_final_answer(self):
        request = json.dumps({'name': 'mcp__workspace_read__read_workspace_file',
                              'arguments': {'path': 'README.md'}})
        replies = iter([packet(request), packet(request), packet('Final grounded answer.')])
        server = {'name': 'workspace_read', 'tools': ['read_workspace_file'],
                  'definitions': [{'name': 'read_workspace_file', 'description': 'Read',
                                   'inputSchema': {'type': 'object'}}],
                  'command': ['fixture']}
        with tempfile.TemporaryDirectory() as temp, \
             patch('project_agent.fetch_ready_roster', return_value=READY), \
             patch('project_agent.call_tool', return_value={
                 'isError': False, 'structuredContent': {'path': 'README.md'}}):
            result = project_agent.run_agent(
                gateway='http://gateway', route='gpu-rig/test', expected_model='test:1b',
                prompt='inspect', agent_type='coding', tool_profile='workspace_read',
                tool_server=server, workspace_root=Path(temp),
                complete=lambda *_: next(replies))
        self.assertIsNone(result['error'])
        self.assertEqual(result['answer'], 'Final grounded answer.')
        self.assertEqual(result['tool_calls'], 1)
        self.assertEqual(result['model_steps'], 3)

    def test_native_gateway_tool_call_returns_role_tool_evidence(self):
        native = {'choices': [{'message': {'role': 'assistant', 'content': None,
                  'tool_calls': [{'id': 'call_1', 'type': 'function', 'function': {
                      'name': 'mcp__workspace_read__read_workspace_file',
                      'arguments': '{"path":"README.md"}'}}]}, 'finish_reason': 'tool_calls'}]}
        replies = iter([native, packet('Grounded in README.md.')])
        seen = []
        def complete(_gateway, _route, messages, _max_tokens, _timeout, _key, tools):
            seen.append((list(messages), tools))
            return next(replies)
        server = {'name': 'workspace_read', 'tools': ['read_workspace_file'],
                  'definitions': [{'name': 'read_workspace_file', 'description': 'Read',
                                   'inputSchema': {'type': 'object'}}],
                  'command': ['fixture']}
        with tempfile.TemporaryDirectory() as temp, \
             patch('project_agent.fetch_ready_roster', return_value=READY), \
             patch('project_agent.call_tool', return_value={
                 'isError': False, 'structuredContent': {'path': 'README.md'}}):
            result = project_agent.run_agent(
                gateway='http://gateway', route='gpu-rig/test', expected_model='test:1b',
                prompt='inspect', agent_type='coding', tool_profile='workspace_read',
                tool_server=server, workspace_root=Path(temp), complete=complete)
        self.assertIsNone(result['error'])
        self.assertEqual(result['answer'], 'Grounded in README.md.')
        self.assertEqual(seen[0][1][0]['function']['name'],
                         'mcp__workspace_read__read_workspace_file')
        self.assertEqual(seen[1][0][-1]['role'], 'tool')
        self.assertEqual(seen[1][0][-1]['tool_call_id'], 'call_1')

    def test_no_tool_gets_one_format_repair_then_stops(self):
        server = {'name': 'workspace_read', 'tools': ['read_workspace_file'],
                  'definitions': [{'name': 'read_workspace_file', 'description': 'Read',
                                   'inputSchema': {'type': 'object'}}],
                  'command': ['fixture']}
        with tempfile.TemporaryDirectory() as temp, \
             patch('project_agent.fetch_ready_roster', return_value=READY):
            result = project_agent.run_agent(
                gateway='http://gateway', route='gpu-rig/test', expected_model='test:1b',
                prompt='inspect', agent_type='coding', tool_profile='workspace_read',
                tool_server=server, workspace_root=Path(temp),
                complete=lambda *_: packet('I inspected it.'))
        self.assertEqual(result['error'], 'model did not execute an allowed tool')
        self.assertEqual(result['model_steps'], 2)
        self.assertTrue(result['tool_format_repair_attempted'])


if __name__ == '__main__':
    unittest.main()
