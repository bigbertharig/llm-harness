"""Contract checks for the Codex local Responses namespace adapter."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from codex_responses_compat import flatten_tools, restore_body


class NamespaceAdapterContract(unittest.TestCase):
    def test_flatten_and_restore_streamed_call(self):
        tools = [
            {'type': 'function', 'name': 'list_mcp_resources', 'parameters': {'type': 'object'}},
            {'type': 'namespace', 'name': 'mcp__marker', 'tools': [
                {'type': 'function', 'name': 'read_marker',
                 'parameters': {'type': 'object', 'properties': {}}}]},
        ]
        flat, mapping = flatten_tools(tools)
        self.assertEqual([item['name'] for item in flat],
                         ['list_mcp_resources', 'mcp__marker__read_marker'])
        self.assertEqual(flat[1]['parameters'], {'type': 'object', 'properties': {}})
        event = {'type': 'response.output_item.done', 'item': {
            'type': 'function_call', 'name': 'mcp__marker__read_marker',
            'arguments': '{}', 'call_id': 'call_1'}}
        body = ('event: response.output_item.done\n' +
                'data: ' + json.dumps(event) + '\n\n' + 'data: [DONE]\n').encode()
        restored, count = restore_body(body, 'text/event-stream', mapping)
        self.assertEqual(count, 1)
        self.assertIn(b'"name": "read_marker"', restored)
        self.assertIn(b'"namespace": "mcp__marker"', restored)
        self.assertIn(b'data: [DONE]', restored)

    def test_flat_name_collision_rejected(self):
        with self.assertRaises(ValueError):
            flatten_tools([
                {'type': 'namespace', 'name': 'mcp__a', 'tools': [
                    {'type': 'function', 'name': 'b'},
                    {'type': 'function', 'name': 'b'}]},
            ])


if __name__ == '__main__':
    unittest.main()
