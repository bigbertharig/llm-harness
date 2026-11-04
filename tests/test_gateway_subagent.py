import json
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from gateway_subagent import resolve_child


class GatewaySubagentRequest(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
