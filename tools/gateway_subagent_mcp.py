#!/usr/bin/env python3
"""Stdio MCP adapter for one native child agent on a separate ready GPU route."""

import json
import os
from pathlib import Path
import sys
from uuid import uuid4

from gateway_subagent import run_child

TOOL = {'name': 'delegate_task',
        'description': 'Give one bounded task to a separate child agent. The manager prepares a model on another GPU if needed. The child has no delegation tool and returns its answer with a route receipt. Verify the answer before relying on it.',
        'inputSchema': {'type': 'object', 'properties': {
            'agent_type': {'type': 'string', 'enum': ['coding', 'research', 'general']},
            'task': {'type': 'string', 'minLength': 1, 'maxLength': 4000}},
            'required': ['agent_type', 'task'], 'additionalProperties': False}}


def respond(id, result):
    print(json.dumps({'jsonrpc': '2.0', 'id': id, 'result': result}), flush=True)


def handle(packet):
    method, id = packet.get('method'), packet.get('id')
    if id is None:
        return
    if method == 'initialize':
        respond(id, {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}},
                     'serverInfo': {'name': 'gateway-subagent', 'version': '0.1.0'}})
    elif method == 'ping':
        respond(id, {})
    elif method == 'tools/list':
        respond(id, {'tools': [TOOL]})
    elif method == 'tools/call':
        params = packet.get('params') or {}
        task = (params.get('arguments') or {}).get('task')
        agent_type = (params.get('arguments') or {}).get('agent_type')
        if (params.get('name') != 'delegate_task' or agent_type not in ('coding', 'research', 'general')
                or not isinstance(task, str) or not 1 <= len(task) <= 4000):
            respond(id, {'isError': True, 'content': [{'type': 'text', 'text': 'invalid delegate_task arguments'}]})
            return
        try:
            parent = os.environ['SUBAGENT_PARENT_ROUTE']
            root = Path(os.environ['SUBAGENT_RECEIPT_DIR'])
            receipt = run_child(parent_id=parent, agent_type=agent_type, prompt=task,
                                out=root / uuid4().hex,
                                gateway=os.environ.get('SUBAGENT_GATEWAY', 'http://127.0.0.1:8080'))
            ok = receipt['exit_code'] == 0 and receipt['roster_stable'] and bool(receipt['answer'])
            respond(id, {'isError': not ok, 'content': [{'type': 'text', 'text': json.dumps(receipt)}],
                         'structuredContent': receipt})
        except Exception as exc:
            respond(id, {'isError': True, 'content': [{'type': 'text', 'text': f'{type(exc).__name__}: {exc}'}]})
    else:
        print(json.dumps({'jsonrpc': '2.0', 'id': id,
                          'error': {'code': -32601, 'message': 'Method not found'}}), flush=True)


for line in sys.stdin:
    if line.strip():
        try:
            handle(json.loads(line))
        except ValueError:
            pass
