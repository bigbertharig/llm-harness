"""Capture only tool declarations from one isolated Codex matrix run."""
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = sys.argv[1] if len(sys.argv) > 1 else 'codex_tool_trace'
TRACE = ROOT / 'results' / RUN_ID / 'gateway_tool_trace.jsonl'
TRACE.parent.mkdir(parents=True, exist_ok=True)

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        request = json.loads(raw)
        declared = request.get('tools') or []
        mapping = {}
        flat = []
        for item in declared:
            if item.get('type') == 'namespace':
                for child in item.get('tools', []):
                    flat_name = f"{item['name']}__{child['name']}"
                    mapping[flat_name] = (item['name'], child['name'])
                    flat.append({**child, 'name': flat_name})
            else:
                flat.append(item)
        request['tools'] = flat
        entry = {
            'path': self.path,
            'model': request.get('model'),
            'tool_choice': request.get('tool_choice'),
            'tools': declared,
        }
        with TRACE.open('a') as output:
            output.write(json.dumps(entry) + '\n')
        headers = {'Content-Type': self.headers.get('Content-Type', 'application/json'),
                   'X-Require-Ready': 'true'}
        if self.headers.get('Accept'):
            headers['Accept'] = self.headers['Accept']
        upstream = urllib.request.Request('http://127.0.0.1:8080' + self.path,
                                          data=json.dumps(request).encode(), headers=headers)
        try:
            response = urllib.request.urlopen(upstream, timeout=110)
        except urllib.error.HTTPError as error:
            response = error
        body = response.read()
        def restore(value):
            if isinstance(value, dict):
                if value.get('type') == 'function_call' and value.get('name') in mapping:
                    namespace, name = mapping[value['name']]
                    value['name'] = name
                    value['namespace'] = namespace
                for child in value.values():
                    restore(child)
            elif isinstance(value, list):
                for child in value:
                    restore(child)
        content_type = response.headers.get('Content-Type', 'application/json')
        if 'event-stream' in content_type:
            lines = []
            for line in body.decode().splitlines(keepends=True):
                if line.startswith('data: ') and line[6:].strip() != '[DONE]':
                    event = json.loads(line[6:])
                    restore(event)
                    ending = '\n' if line.endswith('\n') else ''
                    line = 'data: ' + json.dumps(event) + ending
                lines.append(line)
            body = ''.join(lines).encode()
        else:
            result = json.loads(body)
            restore(result)
            body = json.dumps(result).encode()
        self.send_response(response.status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

server = http.server.ThreadingHTTPServer(('127.0.0.1', 18080), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
env = os.environ.copy()
env['CODEX_GATEWAY_BASE_URL'] = 'http://127.0.0.1:18080/v1'
try:
    command = [sys.executable, str(ROOT / 'tools' / 'comparison_mcp_matrix.py'),
               'codex', 'marker_text', '--run-id', RUN_ID]
    result = subprocess.run(command, cwd=ROOT, env=env, timeout=160)
    print(json.dumps({'matrix_exit_code': result.returncode, 'trace': str(TRACE)}))
finally:
    server.shutdown()
