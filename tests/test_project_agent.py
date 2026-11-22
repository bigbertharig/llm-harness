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
    def test_strict_task_envelope_and_one_call_contract_reach_model(self):
        seen = []
        request = json.dumps({'name': 'mcp__workspace_read__read_workspace_file',
                              'arguments': {'path': 'README.md'}})
        replies = iter([packet(request), packet('Result. Evidence: README.md. Verification: read.')])
        server = {'name': 'workspace_read', 'tools': ['read_workspace_file'],
                  'definitions': [{'name': 'read_workspace_file', 'description': 'Read',
                                   'inputSchema': {'type': 'object'}}],
                  'command': ['fixture']}
        def complete(_gateway, _route, messages, _max_tokens, _timeout, _key, _tools):
            seen.append(list(messages))
            return next(replies)
        with tempfile.TemporaryDirectory() as temp, \
             patch('project_agent.fetch_ready_roster', return_value=READY), \
             patch('project_agent.call_tool', return_value={
                 'isError': False, 'structuredContent': {'path': 'README.md'}}):
            result = project_agent.run_agent(
                gateway='http://gateway', route='gpu-rig/test', expected_model='test:1b',
                prompt='inspect ownership', agent_type='coding', tool_profile='workspace_read',
                tool_server=server, workspace_root=Path(temp), complete=complete)
        self.assertEqual(result['task_contract_version'], 2)
        self.assertIn('Request exactly one tool per turn', seen[0][0]['content'])
        self.assertIn('ASSIGNMENT (contract v2)', seen[0][1]['content'])
        self.assertIn('Do not claim an edit, test, command, or verification', seen[0][1]['content'])

    def test_task_tool_budget_forces_final_synthesis(self):
        calls = [
            json.dumps({'name': 'mcp__workspace_read__read_workspace_file',
                        'arguments': {'path': 'README.md', 'start_line': line}})
            for line in (1, 50)]
        replies = iter([packet(calls[0]), packet(calls[1]), packet('Enough evidence.')])
        advertised = []
        seen = []
        server = {'name': 'workspace_read', 'tools': ['read_workspace_file'],
                  'definitions': [{'name': 'read_workspace_file', 'description': 'Read',
                                   'inputSchema': {'type': 'object'}}], 'command': ['fixture']}
        def complete(_gateway, _route, messages, _max_tokens, _timeout, _key, tools):
            advertised.append(tools)
            seen.append(list(messages))
            return next(replies)
        with tempfile.TemporaryDirectory() as temp, \
             patch('project_agent.fetch_ready_roster', return_value=READY), \
             patch('project_agent.call_tool', return_value={
                 'isError': False, 'structuredContent': {'path': 'README.md'}}):
            result = project_agent.run_agent(
                gateway='http://gateway', route='gpu-rig/test', expected_model='test:1b',
                prompt='inspect', agent_type='coding', tool_profile='workspace_read',
                tool_server=server, workspace_root=Path(temp), max_tool_calls=2,
                complete=complete)
        self.assertIsNone(result['error'])
        self.assertEqual(result['tool_calls'], 2)
        self.assertEqual(result['tool_budget']['max_calls'], 2)
        self.assertEqual(advertised[-1], [])
        self.assertIn('TOOL BUDGET EXHAUSTED', seen[-1][-1]['content'])

    def test_tool_budget_counts_normalized_evidence_once(self):
        request = json.dumps({'name': 'mcp__workspace_read__read_workspace_file',
                              'arguments': {'path': 'README.md'}})
        replies = iter([packet(request), packet('Evidence read.')])
        evidence = {'path': 'README.md', 'content': 'x' * 1000}
        server = {'name': 'workspace_read', 'tools': ['read_workspace_file'],
                  'definitions': [{'name': 'read_workspace_file', 'description': 'Read',
                                   'inputSchema': {'type': 'object'}}],
                  'command': ['fixture']}
        with tempfile.TemporaryDirectory() as temp, \
             patch('project_agent.fetch_ready_roster', return_value=READY), \
             patch('project_agent.call_tool', return_value={
                 'isError': False,
                 'content': [{'type': 'text', 'text': json.dumps(evidence)}],
                 'structuredContent': evidence}):
            result = project_agent.run_agent(
                gateway='http://gateway', route='gpu-rig/test', expected_model='test:1b',
                prompt='inspect', agent_type='research', tool_profile='workspace_read',
                tool_server=server, workspace_root=Path(temp), complete=lambda *_: next(replies))

        expected = len(json.dumps(evidence, ensure_ascii=False).encode('utf-8'))
        self.assertEqual(result['tool_budget']['result_bytes'], expected)
        self.assertIsNone(result['error'])

    def test_workspace_git_prompt_and_policy_stay_separate_from_file_reads(self):
        server = {'name': 'workspace_git', 'tools': ['get_workspace_git_log'],
                  'definitions': [{'name': 'get_workspace_git_log', 'description': 'Log',
                                   'inputSchema': {'type': 'object'}}],
                  'command': ['fixture']}
        replies = iter([
            packet('{"name":"mcp__workspace_git__get_workspace_git_log",'
                   '"arguments":{"limit":2}}'),
            packet('The latest two commits are A and B.'),
        ])
        with tempfile.TemporaryDirectory() as temp, \
             patch('project_agent.fetch_ready_roster', return_value=READY), \
             patch('project_agent.call_tool', return_value={
                 'isError': False, 'structuredContent': {'commits': ['A', 'B']}}):
            result = project_agent.run_agent(
                gateway='http://gateway', route='gpu-rig/test', expected_model='test:1b',
                prompt='inspect history', agent_type='coding', tool_profile='workspace_git',
                tool_server=server, workspace_root=Path(temp), complete=lambda *_: next(replies))
        self.assertIsNone(result['error'])
        self.assertEqual(result['tool_call_summary'][0]['tool'], 'get_workspace_git_log')
        self.assertEqual(result['answer'], 'The latest two commits are A and B.')

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
        self.assertEqual(result['limits']['requested_output_tokens'], 1000)
        self.assertEqual(result['limits']['effective_output_tokens'], 512)
        self.assertEqual(result['limits']['route_output_tokens'], 512)
        self.assertFalse(result['limits']['output_limit_hit'])
        self.assertEqual(result['limits']['mcp_response_line_characters_max'], 131072)
        self.assertEqual(result['limits']['tool_result_bytes_max'], 32000)

    def test_truncated_final_answer_is_not_reported_as_success(self):
        replies = iter([packet('partial answer', finish='length'),
                        packet('complete concise answer')])
        with patch('project_agent.fetch_ready_roster', return_value=READY):
            result = project_agent.run_agent(
                gateway='http://gateway', route='gpu-rig/test', expected_model='test:1b',
                prompt='answer', agent_type='research',
                complete=lambda *_: next(replies))
        self.assertIsNone(result['error'])
        self.assertEqual(result['answer'], 'complete concise answer')
        self.assertTrue(result['limits']['output_limit_hit'])
        self.assertTrue(result['truncation_repair_attempted'])

    def test_second_truncated_final_answer_is_a_failure(self):
        with patch('project_agent.fetch_ready_roster', return_value=READY):
            result = project_agent.run_agent(
                gateway='http://gateway', route='gpu-rig/test', expected_model='test:1b',
                prompt='answer', agent_type='research',
                complete=lambda *_: packet('partial answer', finish='length'))
        self.assertEqual(result['error'], 'model final answer hit the output-token limit')
        self.assertEqual(result['model_steps'], 2)

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

    def test_tool_receipt_keeps_bounded_file_evidence_metadata(self):
        replies = iter([packet(json.dumps({
            'name': 'mcp__workspace_read__read_workspace_file',
            'arguments': {'path': 'README.md', 'start_line': 1, 'max_lines': 20}})),
                        packet('Grounded answer.')])
        server = {'name': 'workspace_read', 'tools': ['read_workspace_file'],
                  'definitions': [{'name': 'read_workspace_file', 'description': 'Read',
                                   'inputSchema': {'type': 'object'}}], 'command': ['fixture']}
        with tempfile.TemporaryDirectory() as temp, \
             patch('project_agent.fetch_ready_roster', return_value=READY), \
             patch('project_agent.call_tool', return_value={'isError': False,
                 'structuredContent': {'path': 'README.md', 'content': 'text',
                     'start_line': 1, 'end_line': 20, 'requested_range_complete': True,
                     'more_lines_after': True, 'truncated': True}}):
            result = project_agent.run_agent(
                gateway='http://gateway', route='gpu-rig/test', expected_model='test:1b',
                prompt='inspect', agent_type='coding', tool_profile='workspace_read',
                tool_server=server, workspace_root=Path(temp),
                complete=lambda *_: next(replies))
        evidence = result['tool_call_summary'][0]['evidence']
        self.assertEqual((evidence['path'], evidence['start_line'], evidence['end_line']),
                         ('README.md', 1, 20))
        self.assertTrue(evidence['more_lines_after'])
        self.assertEqual(result['file_evidence_coverage'], [{
            'path': 'README.md', 'start_line': 1, 'through_line': 20,
            'complete_file': False, 'calls': 1}])

    def test_file_coverage_merges_character_truncated_overlap(self):
        calls = [
            {'tool': 'read_workspace_file', 'is_error': False, 'evidence': {
                'path': 'doc.md', 'start_line': 1, 'end_line': 10,
                'requested_range_complete': False, 'more_lines_after': False}},
            {'tool': 'read_workspace_file', 'is_error': False, 'evidence': {
                'path': 'doc.md', 'start_line': 10, 'end_line': 15,
                'requested_range_complete': True, 'more_lines_after': False}},
        ]
        self.assertEqual(project_agent._file_evidence_coverage(calls), [{
            'path': 'doc.md', 'start_line': 1, 'through_line': 15,
            'complete_file': True, 'calls': 2}])

    def test_document_coverage_requires_one_contiguous_snapshot(self):
        calls = [
            {'tool': 'read_workspace_document_chunk', 'is_error': False, 'evidence': {
                'path': 'doc.md', 'snapshot_sha256': 'a' * 64,
                'cursor_start': 0, 'cursor_end': 100, 'total_characters': 250}},
            {'tool': 'read_workspace_document_chunk', 'is_error': False, 'evidence': {
                'path': 'doc.md', 'snapshot_sha256': 'a' * 64,
                'cursor_start': 100, 'cursor_end': 250, 'total_characters': 250,
                'complete': True}},
            {'tool': 'read_workspace_document_chunk', 'is_error': False, 'evidence': {
                'path': 'doc.md', 'snapshot_sha256': 'b' * 64,
                'cursor_start': 100, 'cursor_end': 250, 'total_characters': 250,
                'complete': True}},
        ]
        self.assertEqual(project_agent._document_evidence_coverage(calls), [
            {'path': 'doc.md', 'snapshot_sha256': 'a' * 64,
             'through_character': 250, 'total_characters': 250,
             'complete_document': True, 'calls': 2},
            {'path': 'doc.md', 'snapshot_sha256': 'b' * 64,
             'through_character': 0, 'total_characters': 250,
             'complete_document': False, 'calls': 1},
        ])

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
