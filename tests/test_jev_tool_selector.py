import json
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import jev_tool_selector
import project_agent

READY = {'data': [{'id': 'test', 'model': 'model', 'context_length': 8192, 'output_limit': 512}]}
SERVER = {'name': 'workspace_read', 'tools': ['read_workspace_file', 'search_workspace_text'],
          'definitions': [
              {'name': 'read_workspace_file', 'description': 'Read a file', 'inputSchema': {'type': 'object'}},
              {'name': 'search_workspace_text', 'description': 'Search text', 'inputSchema': {'type': 'object'}}],
          'command': ['fixture']}


def packet(content):
    return {'choices': [{'message': {'role': 'assistant', 'content': content},
                         'finish_reason': 'stop'}], 'usage': {}}


class JevToolSelectorTests(unittest.TestCase):
    def test_api_request_uses_allowed_tools_and_keeps_key_out_of_result(self):
        response = BytesIO(json.dumps({'model': 'jev-1.14.0', 'answers': {'next_tool': {
            'choice': 'read_workspace_file', 'probabilities': {'read_workspace_file': .95}}},
            'usage': {'input_tokens': 10}}).encode())
        with patch.dict('os.environ', {'TYPESAFE_API_KEY': 'secret'}), \
             patch('jev_tool_selector.urlopen', return_value=response) as opened:
            result = jev_tool_selector.select([{'role': 'user', 'content': 'read file'}], SERVER, 5)
        request = opened.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(request.get_header('Authorization'), 'Bearer secret')
        self.assertEqual(set(body['questions']['next_tool']['criteria']),
                         {*SERVER['tools'], 'model_decides'})
        self.assertEqual(result['answer']['choice'], 'read_workspace_file')
        self.assertNotIn('secret', json.dumps(result))

    def test_high_probability_narrows_advertised_tools_and_low_probability_falls_back(self):
        for probability, expected_count in ((.95, 1), (.55, 2)):
            with self.subTest(probability=probability), tempfile.TemporaryDirectory() as temp:
                advertised = []
                replies = iter([packet(json.dumps({'name': 'mcp__workspace_read__read_workspace_file',
                                                   'arguments': {'path': 'README.md'}})),
                                packet('Answer based on the file.')])
                def complete(_gateway, _route, _messages, _tokens, _timeout, _key, tools):
                    advertised.append(tools)
                    return next(replies)
                def choose(_messages, _server, _timeout):
                    return {'model': 'jev-test', 'answer': {'choice': 'read_workspace_file',
                            'probabilities': {'read_workspace_file': probability}}, 'usage': {}}
                with patch('project_agent.fetch_ready_roster', return_value=READY), \
                     patch('project_agent.call_tool', return_value={'isError': False,
                                                                   'structuredContent': {'path': 'README.md'}}):
                    receipt = project_agent.run_agent(
                        gateway='http://gateway', route='test', expected_model='model',
                        prompt='read README', agent_type='coding', tool_profile='workspace_read',
                        tool_server=SERVER, workspace_root=Path(temp), complete=complete,
                        tool_selector=choose)
                self.assertIsNone(receipt['error'])
                self.assertEqual(len(advertised[0]), expected_count)
                self.assertEqual(receipt['tool_selector_receipts'][0]['status'],
                                 'selected' if probability >= .8 else 'fallback')

    def test_selector_failure_uses_ordinary_model_tool_path(self):
        def broken(*_args):
            raise TimeoutError('selector unavailable')
        with tempfile.TemporaryDirectory() as temp, \
             patch('project_agent.fetch_ready_roster', return_value=READY):
            seen = []
            def complete(*args):
                seen.append(args[-1])
                return packet('No tool necessary.')
            receipt = project_agent.run_agent(
                gateway='http://gateway', route='test', expected_model='model',
                prompt='answer', agent_type='coding', tool_profile='workspace_read',
                tool_server=SERVER, workspace_root=Path(temp), complete=complete,
                tool_selector=broken)
        self.assertEqual(len(seen[0]), 2)
        self.assertEqual(receipt['tool_selector_receipts'][0]['error_code'], 'TimeoutError')


if __name__ == '__main__':
    unittest.main()
