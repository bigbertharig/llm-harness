"""Model-independent fallback for a complete JSON MCP tool request in assistant text.

Only tools explicitly exposed to this controller may be called. This module does
not interpret prose, extract JSON snippets, or repair invalid arguments.
"""

import json
import queue
import subprocess
import threading
import time

from jsonschema import Draft202012Validator
import requests


def parse_request(answer, server, targets):
    raw = answer.strip()
    if raw.startswith('```json\n') and raw.endswith('\n```'):
        raw = raw[8:-4].strip()
    elif raw.startswith('<tools>\n') and raw.endswith('\n</tools>'):
        raw = raw[8:-9].strip()
    if len(raw) > 16000:
        return None
    try:
        envelope = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(envelope, dict) or set(envelope) != {'name', 'arguments'}:
        return None
    allowed = {'mcp__' + server['name'] + '__' + name: name for name in targets}
    name = allowed.get(envelope['name']) if isinstance(envelope['name'], str) else None
    if name is None or not isinstance(envelope['arguments'], dict):
        return None
    return name, envelope['arguments']


def _stdio_request(proc, messages, ident, method, params=None, timeout=15):
    packet = {'jsonrpc': '2.0', 'id': ident, 'method': method}
    if params is not None:
        packet['params'] = params
    proc.stdin.write(json.dumps(packet) + '\n')
    proc.stdin.flush()
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f'MCP {method} timed out')
        try:
            item = messages.get(timeout=remaining)
        except queue.Empty as exc:
            raise TimeoutError(f'MCP {method} timed out') from exc
        if item is None:
            raise RuntimeError(f'MCP server exited during {method}: {proc.poll()}')
        if item.get('id') == ident:
            if 'error' in item:
                raise RuntimeError(f'MCP {method} error: {item["error"]}')
            return item.get('result', {})


def call_stdio(server, tool, arguments, timeout=180):
    """Discover, validate, then call one configured stdio MCP tool."""
    if 'command' not in server:
        raise ValueError('text fallback currently requires a configured stdio MCP server')
    proc = subprocess.Popen(server['command'], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, bufsize=1)
    messages = queue.Queue()

    def read_stdout():
        for line in proc.stdout:
            try:
                messages.put(json.loads(line))
            except ValueError:
                continue
        messages.put(None)

    threading.Thread(target=read_stdout, daemon=True).start()
    try:
        _stdio_request(proc, messages, 1, 'initialize', {
            'protocolVersion': '2025-06-18', 'capabilities': {},
            'clientInfo': {'name': 'harness-text-tool-bridge', 'version': '1'}}, timeout=15)
        proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) + '\n')
        proc.stdin.flush()
        listing = _stdio_request(proc, messages, 2, 'tools/list', timeout=15)
        advertised = {item['name']: item for item in listing.get('tools', [])}
        if tool not in server['tools'] or tool not in advertised:
            raise ValueError(f'tool {tool!r} is not both configured and advertised')
        schema = advertised[tool].get('inputSchema')
        if not isinstance(schema, dict):
            raise ValueError(f'tool {tool!r} has no valid input schema')
        Draft202012Validator.check_schema(schema)
        errors = sorted(Draft202012Validator(schema).iter_errors(arguments), key=lambda x: x.json_path)
        if errors:
            raise ValueError('MCP arguments failed advertised schema: ' + errors[0].message)
        result = _stdio_request(proc, messages, 3, 'tools/call',
                                {'name': tool, 'arguments': arguments}, timeout=timeout)
        return result
    finally:
        if proc.poll() is None:
            proc.stdin.close()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.wait(timeout=3)
        proc.stdout.close()


def call_http(server, tool, arguments, timeout=30):
    """Discover, validate, then call one configured Streamable HTTP MCP tool."""
    url = server.get('url', '')
    if not url.startswith(('http://', 'https://')):
        raise ValueError('MCP URL must use HTTP or HTTPS')
    if tool not in server['tools']:
        raise ValueError(f'tool {tool!r} is not configured')
    headers = {'Content-Type': 'application/json',
               'Accept': 'application/json, text/event-stream',
               'MCP-Protocol-Version': '2025-06-18'}
    headers.update(server.get('headers', {}))
    with requests.Session() as session:
        def request(ident, method, params=None):
            packet = {'jsonrpc': '2.0', 'id': ident, 'method': method}
            if params is not None:
                packet['params'] = params
            response = session.post(url, json=packet, headers=headers, timeout=timeout)
            if response.headers.get('mcp-session-id'):
                headers['Mcp-Session-Id'] = response.headers['mcp-session-id']
            response.raise_for_status()
            if 'text/event-stream' in response.headers.get('content-type', ''):
                rows = [json.loads(line[5:].strip()) for line in response.text.splitlines()
                        if line.startswith('data:')]
                matches = [row for row in rows if row.get('id') == ident]
                if not matches:
                    raise RuntimeError(f'MCP {method} returned no matching SSE response')
                body = matches[-1]
            else:
                body = response.json()
            if body.get('id') != ident or 'error' in body or 'result' not in body:
                raise RuntimeError(f'MCP {method} returned an invalid JSON-RPC response')
            return body['result']

        request(1, 'initialize', {'protocolVersion': '2025-06-18',
            'capabilities': {}, 'clientInfo': {'name': 'harness-text-tool-bridge', 'version': '1'}})
        session.post(url, json={'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                     headers=headers, timeout=timeout).raise_for_status()
        listing = request(2, 'tools/list')
        advertised = {item['name']: item for item in listing.get('tools', [])}
        if tool not in advertised:
            raise ValueError(f'tool {tool!r} is not advertised')
        schema = advertised[tool].get('inputSchema')
        if not isinstance(schema, dict):
            raise ValueError(f'tool {tool!r} has no valid input schema')
        Draft202012Validator.check_schema(schema)
        errors = sorted(Draft202012Validator(schema).iter_errors(arguments), key=lambda x: x.json_path)
        if errors:
            raise ValueError('MCP arguments failed advertised schema: ' + errors[0].message)
        return request(3, 'tools/call', {'name': tool, 'arguments': arguments})


def call_tool(server, tool, arguments, timeout=30):
    return (call_http(server, tool, arguments, timeout) if 'url' in server else
            call_stdio(server, tool, arguments, timeout))
