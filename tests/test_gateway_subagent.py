import json
import sys
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from gateway_subagent import resolve_child
from subagent_contract import canonical_integer_answer, canonical_final_line, child_system_prompt


class GatewaySubagentRequest(unittest.TestCase):
    def test_typed_prompt_and_numeric_normalization(self):
        self.assertIn('coding child agent', child_system_prompt('coding'))
        self.assertIn('research child agent', child_system_prompt('research'))
        self.assertEqual(canonical_integer_answer('42.0'), '42')
        self.assertEqual(canonical_integer_answer('42'), '42')
        self.assertIsNone(canonical_integer_answer('41.5'))
        self.assertIsNone(canonical_integer_answer('The answer is 42'))
        self.assertEqual(canonical_final_line('Checked 7 times 6.\n\n42'), '42')

    def test_harness_sends_capability_without_gpu_or_model(self):
        class Reply:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass
            def read(self):
                return b'{"route":"gpu-rig/coder-7b","gpu_ids":[2]}'

        with patch('gateway_subagent.urlopen', return_value=Reply()) as call:
            result = resolve_child('http://127.0.0.1:8080', 'gpu-rig/chat-27b', 'coding')
        request = call.call_args.args[0]
        self.assertEqual(json.loads(request.data), {
            'parent_route': 'gpu-rig/chat-27b', 'agent_type': 'coding'})
        self.assertEqual(result['route'], 'gpu-rig/coder-7b')

    def test_mcp_launch_arguments_expose_simple_tool(self):
        server = Path(__file__).resolve().parents[1] / 'tools/gateway_subagent_mcp.py'
        with tempfile.TemporaryDirectory() as temp:
            packet = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}) + '\n'
            proc = subprocess.run([sys.executable, str(server), '--parent-route', 'gpu-rig/parent',
                                   '--receipt-dir', temp], input=packet, text=True,
                                  capture_output=True, timeout=5)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        tools = json.loads(proc.stdout)['result']['tools']
        self.assertEqual([tool['name'] for tool in tools], ['delegate_task'])
        self.assertEqual(set(tools[0]['inputSchema']['properties']), {'agent_type', 'task'})
        self.assertEqual(tools[0]['inputSchema']['properties']['agent_type']['enum'],
                         ['coding', 'research'])


if __name__ == '__main__':
    unittest.main()
