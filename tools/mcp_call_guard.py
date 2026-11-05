"""Per-turn HTTP MCP call guard shared by candidate harness controllers.

The guard passes MCP discovery through unchanged. It bounds only tools/call,
so clients can initialize and list tools as often as their protocol requires.
"""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class CallBudget:
    def __init__(self, max_calls=5, max_identical=2, max_consecutive_errors=2):
        self.max_calls = max_calls
        self.max_identical = max_identical
        self.max_consecutive_errors = max_consecutive_errors
        self.calls = 0
        self.fingerprints = {}
        self.consecutive_errors = 0
        self.failing_tool = None
        self.events = []
        self.lock = threading.Lock()

    def before(self, params):
        key = json.dumps([params.get('name'), params.get('arguments', {})], sort_keys=True)
        with self.lock:
            reason = None
            if self.calls >= self.max_calls:
                reason = 'tool call budget exhausted; use the evidence already returned and finish'
            elif self.fingerprints.get(key, 0) >= self.max_identical:
                reason = 'this identical tool request was already tried twice; change the query or finish'
            elif (self.consecutive_errors >= self.max_consecutive_errors
                  and self.failing_tool == params.get('name')):
                reason = 'two consecutive failures from this tool; use a different tool or finish'
            if reason:
                self.events.append({'action': 'blocked', 'reason': reason,
                                    'tool': params.get('name')})
                return reason, None
            self.calls += 1
            self.fingerprints[key] = self.fingerprints.get(key, 0) + 1
            event = {'action': 'forwarded', 'tool': params.get('name')}
            self.events.append(event)
            return None, event

    def after(self, event, failed):
        with self.lock:
            if failed:
                self.consecutive_errors = (self.consecutive_errors + 1
                                           if self.failing_tool == event['tool'] else 1)
                self.failing_tool = event['tool']
            else:
                self.consecutive_errors = 0
                self.failing_tool = None
            event['failed'] = bool(failed)

    def receipt(self):
        with self.lock:
            return {'max_calls': self.max_calls, 'max_identical': self.max_identical,
                    'max_consecutive_errors': self.max_consecutive_errors,
                    'forwarded_calls': self.calls, 'events': list(self.events)}


def _failed(content_type, body, status):
    if status >= 400:
        return True
    try:
        if 'text/event-stream' in content_type:
            packets = [json.loads(line[5:].strip()) for line in body.decode().splitlines()
                       if line.startswith('data:')]
            return any('error' in packet or packet.get('result', {}).get('isError')
                       for packet in packets)
        packet = json.loads(body)
        return 'error' in packet or bool(packet.get('result', {}).get('isError'))
    except (ValueError, UnicodeDecodeError, AttributeError):
        return True


@contextmanager
def guarded_mcp(upstream_url, *, max_calls=5, max_identical=2,
                max_consecutive_errors=2):
    """Yield a loopback URL and budget receipt object for one candidate turn."""
    budget = CallBudget(max_calls, max_identical, max_consecutive_errors)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            length = int(self.headers.get('Content-Length', '0'))
            body = self.rfile.read(length)
            try:
                packet = json.loads(body)
            except ValueError:
                packet = {}
            is_call = isinstance(packet, dict) and packet.get('method') == 'tools/call'
            event = None
            if is_call:
                reason, event = budget.before(packet.get('params') or {})
                if reason:
                    reply = {'jsonrpc': '2.0', 'id': packet.get('id'),
                             'result': {'content': [{'type': 'text', 'text': reason}],
                                        'isError': True}}
                    data = json.dumps(reply).encode()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
            headers = {key: value for key, value in self.headers.items()
                       if key.lower() not in ('host', 'content-length', 'connection')}
            request = Request(upstream_url, data=body, headers=headers, method='POST')
            try:
                response = urlopen(request, timeout=180)
            except HTTPError as exc:
                response = exc
            except Exception:
                if is_call:
                    budget.after(event, True)
                self.send_error(502, 'upstream MCP unavailable')
                return
            with response:
                data = response.read()
                status = response.status
                content_type = response.headers.get('Content-Type', 'application/json')
                if is_call:
                    budget.after(event, _failed(content_type, data, status))
                self.send_response(status)
                for key in ('Content-Type', 'Mcp-Session-Id', 'MCP-Protocol-Version'):
                    if response.headers.get(key):
                        self.send_header(key, response.headers[key])
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/mcp', budget
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
