"""Small stdlib bridge for public MCP tools used by bounded local children."""

import json
import queue
import re
import subprocess
import threading
import time


def parse_request(answer, server, targets):
    raw = answer.strip()
    if raw.startswith('```json\n') and raw.endswith('\n```'):
        raw = raw[8:-4].strip()
    if len(raw) > 16000:
        return None
    try:
        packet = json.loads(raw)
    except (TypeError, ValueError):
        # Some local models emit conventional function syntax instead of the
        # requested JSON envelope. Accept it only when the entire response is
        # one or more allowlisted calls, then execute the first and feed its
        # result back before considering another call.
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        calls = []
        for line in lines:
            match = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*)\s*\((\{.*\})\)\s*;?', line)
            if not match:
                return None
            try:
                arguments = json.loads(match.group(2))
            except ValueError:
                return None
            if not isinstance(arguments, dict):
                return None
            calls.append((match.group(1), arguments))
        if not calls:
            return None
        allowed_names = {'mcp__' + server['name'] + '__' + name: name for name in targets}
        normalized = [(allowed_names.get(name) or (name if name in targets else None), arguments)
                      for name, arguments in calls]
        return normalized[0] if all(name for name, _ in normalized) else None
    if not isinstance(packet, dict):
        return None
    allowed = {'mcp__' + server['name'] + '__' + name: name for name in targets}
    if set(packet) in ({'name', 'arguments'}, {'tool', 'arguments'}):
        raw_name, arguments = packet.get('name', packet.get('tool')), packet['arguments']
    elif len(packet) == 1:
        raw_name, arguments = next(iter(packet.items()))
    else:
        return None
    if not isinstance(raw_name, str) or not isinstance(arguments, dict):
        return None
    name = allowed.get(raw_name) or (raw_name if raw_name in targets else None)
    return (name, arguments) if name else None


def call_tool(server, tool, arguments, timeout=30):
    """Discover and call one allowlisted stdio tool; the MCP server validates arguments."""
    if tool not in server['tools'] or not isinstance(arguments, dict):
        raise ValueError('public tool is not allowed')
    proc = subprocess.Popen(server['command'], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, bufsize=1)
    received = queue.Queue()

    def reader():
        while line := proc.stdout.readline(131073):
            if len(line) > 131072 or not line.endswith('\n'):
                received.put(RuntimeError('public MCP response exceeded its line limit'))
                break
            try:
                received.put(json.loads(line))
            except ValueError:
                continue
        received.put(None)

    threading.Thread(target=reader, daemon=True).start()
    deadline = time.monotonic() + timeout

    def request(ident, method, params=None):
        packet = {'jsonrpc': '2.0', 'id': ident, 'method': method}
        if params is not None:
            packet['params'] = params
        proc.stdin.write(json.dumps(packet) + '\n')
        proc.stdin.flush()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('public MCP tool timed out')
            try:
                reply = received.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError('public MCP tool timed out') from exc
            if reply is None:
                raise RuntimeError('public MCP server exited')
            if isinstance(reply, Exception):
                raise reply
            if reply.get('id') == ident:
                if 'error' in reply:
                    raise RuntimeError('public MCP server returned an error')
                return reply.get('result') or {}

    try:
        request(1, 'initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                  'clientInfo': {'name': 'harness-child-bridge', 'version': '1'}})
        proc.stdin.write(json.dumps({'jsonrpc': '2.0',
                                     'method': 'notifications/initialized'}) + '\n')
        proc.stdin.flush()
        listed = request(2, 'tools/list')
        if tool not in {entry.get('name') for entry in listed.get('tools', [])
                        if isinstance(entry, dict)}:
            raise ValueError('public tool is not advertised by its MCP server')
        return request(3, 'tools/call', {'name': tool, 'arguments': arguments})
    finally:
        if proc.poll() is None:
            proc.stdin.close()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.wait(timeout=3)
        proc.stdout.close()
