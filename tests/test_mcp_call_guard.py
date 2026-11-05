import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import unittest
from urllib.request import Request, urlopen

from mcp_call_guard import guarded_mcp


def post(url, method, ident, params=None):
    body = {'jsonrpc': '2.0', 'id': ident, 'method': method}
    if params is not None:
        body['params'] = params
    request = Request(url, data=json.dumps(body).encode(),
                      headers={'Content-Type': 'application/json'}, method='POST')
    with urlopen(request, timeout=5) as response:
        return json.load(response)


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.upstream_calls = []
        calls = self.upstream_calls

        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                packet = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                calls.append(packet)
                result = {'content': [{'type': 'text', 'text': 'ok'}]}
                if packet.get('params', {}).get('arguments', {}).get('query') == 'bad':
                    result['isError'] = True
                data = json.dumps({'jsonrpc': '2.0', 'id': packet['id'],
                                   'result': result}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}/mcp'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_identical_calls_and_total_budget(self):
        with guarded_mcp(self.url, max_calls=5) as (url, budget):
            post(url, 'tools/list', 1)
            for index in range(3):
                reply = post(url, 'tools/call', index + 2,
                             {'name': 'search', 'arguments': {'query': 'same'}})
                self.assertEqual(bool(reply['result'].get('isError')), index == 2)
            for index in range(3):
                reply = post(url, 'tools/call', index + 5,
                             {'name': 'search', 'arguments': {'query': f'new-{index}'}})
                self.assertFalse(reply['result'].get('isError', False))
            blocked = post(url, 'tools/call', 8,
                           {'name': 'search', 'arguments': {'query': 'sixth'}})
            self.assertTrue(blocked['result']['isError'])
            self.assertEqual(budget.receipt()['forwarded_calls'], 5)
        self.assertEqual(sum(x['method'] == 'tools/call' for x in self.upstream_calls), 5)

    def test_consecutive_errors_stop_spiral(self):
        with guarded_mcp(self.url) as (url, budget):
            for index in range(2):
                self.assertTrue(post(url, 'tools/call', index + 1,
                                    {'name': 'search', 'arguments': {'query': 'bad'}})
                                ['result']['isError'])
            blocked = post(url, 'tools/call', 3,
                           {'name': 'search', 'arguments': {'query': 'another'}})
            self.assertTrue(blocked['result']['isError'])
            alternative = post(url, 'tools/call', 4,
                               {'name': 'other_tool', 'arguments': {'query': 'new'}})
            self.assertFalse(alternative['result'].get('isError', False))
            self.assertEqual(budget.receipt()['forwarded_calls'], 3)


if __name__ == '__main__':
    unittest.main()
