"""Adapt Codex Responses namespaces for the local rig's flat function route."""
from contextlib import contextmanager
import http.server
import json
from pathlib import Path
import threading
import urllib.error
import urllib.request


def flatten_tools(tools):
    flat = []
    mapping = {}
    for item in tools:
        if item.get('type') == 'namespace':
            for child in item.get('tools', []):
                flat_name = f"{item['name']}__{child['name']}"
                if flat_name in mapping:
                    raise ValueError(f'duplicate flattened tool name: {flat_name}')
                mapping[flat_name] = (item['name'], child['name'])
                flat.append({**child, 'name': flat_name})
        else:
            flat.append(item)
    return flat, mapping


def restore_calls(value, mapping):
    count = 0
    if isinstance(value, dict):
        if value.get('type') == 'function_call' and value.get('name') in mapping:
            namespace, name = mapping[value['name']]
            value['name'] = name
            value['namespace'] = namespace
            count += 1
        for child in value.values():
            count += restore_calls(child, mapping)
    elif isinstance(value, list):
        for child in value:
            count += restore_calls(child, mapping)
    return count


def restore_body(body, content_type, mapping):
    if 'event-stream' in content_type:
        lines = []
        restored = 0
        for line in body.decode().splitlines(keepends=True):
            if line.startswith('data: ') and line[6:].strip() != '[DONE]':
                event = json.loads(line[6:])
                restored += restore_calls(event, mapping)
                line = 'data: ' + json.dumps(event) + ('\n' if line.endswith('\n') else '')
            lines.append(line)
        return ''.join(lines).encode(), restored
    try:
        result = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return body, 0
    restored = restore_calls(result, mapping)
    return json.dumps(result).encode(), restored


@contextmanager
def codex_gateway_compat(receipt, upstream='http://127.0.0.1:8080'):
    """Serve an isolated loopback proxy and yield its `/v1` base URL."""
    receipt = Path(receipt)
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get('Content-Length', '0')))
            request = json.loads(raw)
            original = request.get('tools') or []
            request['tools'], mapping = flatten_tools(original)
            headers = {'Content-Type': self.headers.get('Content-Type', 'application/json'),
                       'X-Require-Ready': 'true'}
            if self.headers.get('Accept'):
                headers['Accept'] = self.headers['Accept']
            forwarded = urllib.request.Request(upstream + self.path,
                data=json.dumps(request).encode(), headers=headers)
            try:
                response = urllib.request.urlopen(forwarded, timeout=110)
            except urllib.error.HTTPError as error:
                response = error
            body = response.read()
            content_type = response.headers.get('Content-Type', 'application/json')
            body, restored = restore_body(body, content_type, mapping)
            with receipt.open('a') as output:
                output.write(json.dumps({
                    'path': self.path, 'model': request.get('model'),
                    'flattened_names': sorted(mapping), 'status': response.status,
                    'restored_call_events': restored,
                }) + '\n')
            self.send_response(response.status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1'
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
