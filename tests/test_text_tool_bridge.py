import json
from pathlib import Path
import tempfile
import unittest
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from candidate_controllers.text_tool_bridge import call_http, call_stdio, parse_request
from candidate_controllers.pi import help_spec_for


ROOT = Path(__file__).resolve().parents[1]


class TextToolBridgeTest(unittest.TestCase):
    def test_known_local_servers_request_exact_tool_help(self):
        for name in ('research_local', 'geometry_local'):
            self.assertEqual(help_spec_for({'name': name}, ['get_catalog']),
                             {'name': 'get_tool_help', 'arguments': {'tool_name': 'get_catalog'}})
        self.assertIsNone(help_spec_for({'name': 'other'}, ['get_catalog']))
        self.assertIsNone(help_spec_for({'name': 'geometry_local'}, ['get_tool_help']))

    def test_only_whole_configured_json_request_is_accepted(self):
        server = {'name': 'subagent', 'tools': ['delegate_task']}
        good = json.dumps({'name': 'mcp__subagent__delegate_task',
                           'arguments': {'agent_type': 'coding', 'task': 'x'}})
        self.assertEqual(parse_request(good, server, ['delegate_task']),
                         ('delegate_task', {'agent_type': 'coding', 'task': 'x'}))
        self.assertEqual(parse_request('<tools>\n' + good + '\n</tools>', server, ['delegate_task']),
                         ('delegate_task', {'agent_type': 'coding', 'task': 'x'}))
        self.assertIsNone(parse_request('Please call ' + good, server, ['delegate_task']))
        self.assertIsNone(parse_request(good.replace('subagent', 'other'), server, ['delegate_task']))
        self.assertIsNone(parse_request(good.replace('delegate_task', 'other'), server, ['delegate_task']))

    def test_advertised_schema_blocks_bad_arguments_before_call(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / 'calls.jsonl'
            server = {'name': 'marker', 'command': ['node',
                      str(ROOT / 'tools/fixtures/local_mcp_marker.mjs'), str(log)],
                      'tools': ['read_marker']}
            with self.assertRaises(ValueError):
                call_stdio(server, 'read_marker', {'unadvertised': 'x'})
            if log.exists():
                self.assertFalse(any('tools/call' in line for line in log.read_text().splitlines()))

    def test_valid_request_calls_advertised_tool(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / 'calls.jsonl'
            server = {'name': 'marker', 'command': ['node',
                      str(ROOT / 'tools/fixtures/local_mcp_marker.mjs'), str(log)],
                      'tools': ['read_marker']}
            result = call_stdio(server, 'read_marker', {})
            self.assertFalse(result['isError'])
            self.assertTrue(result['structuredContent']['marker'].startswith('MCP-TEXT-'))
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(sum(row['method'] == 'tools/call' for row in calls), 1)

    def test_http_transport_discovers_and_validates_before_call(self):
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_POST(self):
                length = int(self.headers['Content-Length'])
                packet = json.loads(self.rfile.read(length))
                method = packet['method']
                calls.append(method)
                if method == 'notifications/initialized':
                    self.send_response(202)
                    self.end_headers()
                    return
                result = ({'protocolVersion': '2025-06-18', 'capabilities': {}}
                          if method == 'initialize' else
                          {'tools': [{'name': 'lookup', 'inputSchema': {'type': 'object',
                              'properties': {'key': {'type': 'string'}}, 'required': ['key'],
                              'additionalProperties': False}}]}
                          if method == 'tools/list' else
                          {'isError': False, 'structuredContent': {'value': 'ok'}})
                body = json.dumps({'jsonrpc': '2.0', 'id': packet['id'], 'result': result}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            server = {'name': 'lookup', 'url': f'http://127.0.0.1:{http.server_port}/mcp',
                      'tools': ['lookup']}
            with self.assertRaises(ValueError):
                call_http(server, 'lookup', {'bad': 'x'})
            self.assertNotIn('tools/call', calls)
            self.assertEqual(call_http(server, 'lookup', {'key': 'a'})['structuredContent']['value'], 'ok')
            self.assertEqual(calls.count('tools/call'), 1)
        finally:
            http.shutdown()
            http.server_close()


if __name__ == '__main__':
    unittest.main()
