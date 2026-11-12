#!/usr/bin/env python3
"""Stdio MCP adapter for one native child agent on a separate ready GPU route."""

import argparse
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

from gateway_subagent import run_child

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--parent-route', default=os.environ.get('SUBAGENT_PARENT_ROUTE'))
parser.add_argument('--receipt-dir', default=os.environ.get('SUBAGENT_RECEIPT_DIR'))
config = parser.parse_args()
if not config.parent_route or not config.receipt_dir:
    parser.error('--parent-route and --receipt-dir are required (or set SUBAGENT_PARENT_ROUTE and SUBAGENT_RECEIPT_DIR)')

TOOL = {'name': 'delegate_task',
        'description': 'Give one bounded task to a separate child agent. The default local route is prepared by the manager; candidate_id may select a shared 35B chat or a Codex Terra/Luna worker. The child cannot delegate further. Verify its answer before relying on it.',
        'inputSchema': {'type': 'object', 'properties': {
            'agent_type': {'type': 'string', 'enum': ['coding', 'research']},
            'task': {'type': 'string', 'minLength': 1, 'maxLength': 4000},
            'candidate_id': {'type': 'string', 'enum': ['qwen35_shared_1060', 'codex_terra', 'codex_luna']}},
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
        if not isinstance(params, dict):
            respond(id, {'isError': True, 'content': [{'type': 'text', 'text': 'invalid delegate_task arguments'}]})
            return
        arguments = params.get('arguments') or {}
        if not isinstance(arguments, dict):
            respond(id, {'isError': True, 'content': [{'type': 'text', 'text': 'invalid delegate_task arguments'}]})
            return
        task = arguments.get('task')
        agent_type = arguments.get('agent_type')
        candidate_id = arguments.get('candidate_id')
        if (params.get('name') != 'delegate_task' or agent_type not in ('coding', 'research')
                or not isinstance(task, str) or not 1 <= len(task) <= 4000
                or candidate_id not in (None, 'qwen35_shared_1060', 'codex_terra', 'codex_luna')
                or set(arguments) - {'agent_type', 'task', 'candidate_id'}):
            respond(id, {'isError': True, 'content': [{'type': 'text', 'text': 'invalid delegate_task arguments'}]})
            return
        try:
            parent = config.parent_route
            root = Path(config.receipt_dir)
            receipt = run_child(parent_id=parent, agent_type=agent_type, prompt=task,
                                out=root / uuid4().hex,
                                gateway=os.environ.get('SUBAGENT_GATEWAY', 'http://127.0.0.1:8080'),
                                candidate_id=candidate_id)
            ok = receipt['exit_code'] == 0 and receipt['roster_stable'] and bool(receipt['answer']) \
                 and receipt.get('released', True) is not False
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
