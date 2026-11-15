#!/usr/bin/env python3
"""Stdio MCP adapter for one native child agent on a separate ready GPU route."""

import argparse
import json
import os
from pathlib import Path
import sys
from urllib.request import Request, urlopen
from uuid import uuid4

from gateway_subagent import run_child

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--parent-route', default=os.environ.get('SUBAGENT_PARENT_ROUTE'))
parser.add_argument('--cloud-parent', action='store_true', help='Codex dashboard parent; delegate only to local rigs')
parser.add_argument('--receipt-dir', default=os.environ.get('SUBAGENT_RECEIPT_DIR'))
config = parser.parse_args()
if config.cloud_parent:
    if config.parent_route:
        parser.error('--cloud-parent and --parent-route cannot be combined')
    config.parent_route = 'cloud/codex'
if not config.parent_route or not config.receipt_dir:
    parser.error('--parent-route or --cloud-parent, and --receipt-dir are required')

TOOL = {'name': 'delegate_task',
        'description': 'Give one bounded task to a separate child agent. The default local route is prepared by the manager; candidate_id may select a shared 35B chat or a Codex Terra/Luna worker. The child cannot delegate further. Verify its answer before relying on it.',
        'inputSchema': {'type': 'object', 'properties': {
            'agent_type': {'type': 'string', 'enum': ['coding', 'research']},
            'task': {'type': 'string', 'minLength': 1, 'maxLength': 4000},
            'candidate_id': {'type': 'string', 'enum': ['qwen35_shared_1060', 'codex_terra', 'codex_luna']}},
            'required': ['agent_type', 'task'], 'additionalProperties': False}}
if config.cloud_parent:
    TOOL['description'] = ('Give one bounded coding or research task to a local GPU agent. '
                           'Set candidate_id to qwen35_shared_1060 for an independent chat in the shared 35B model; '
                           'otherwise the manager selects a local model. The manager chooses GPUs. '
                           'The child has no file tools; verify its answer.')
    TOOL['inputSchema']['properties']['candidate_id']['enum'] = ['qwen35_shared_1060']

LIST_TOOL = {'name': 'list_local_agents',
             'description': 'List available research and coding child models. '
                            'Use this before choosing a candidate for a task.',
             'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}}


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
        respond(id, {'tools': [LIST_TOOL, TOOL]})
    elif method == 'tools/call':
        params = packet.get('params') or {}
        if not isinstance(params, dict):
            respond(id, {'isError': True, 'content': [{'type': 'text', 'text': 'invalid delegate_task arguments'}]})
            return
        arguments = params.get('arguments') or {}
        if not isinstance(arguments, dict):
            respond(id, {'isError': True, 'content': [{'type': 'text', 'text': 'invalid delegate_task arguments'}]})
            return
        if params.get('name') == LIST_TOOL['name']:
            if arguments:
                respond(id, {'isError': True, 'content': [{'type': 'text', 'text': 'list_local_agents takes no arguments'}]})
                return
            try:
                headers = {}
                if os.environ.get('LLM_GATEWAY_API_KEY'):
                    headers['Authorization'] = 'Bearer ' + os.environ['LLM_GATEWAY_API_KEY']
                endpoint = ('local-agent-capabilities' if config.cloud_parent else 'subagent-candidates')
                request = Request('http://127.0.0.1:8080/v1/manager/' + endpoint,
                                  headers=headers)
                with urlopen(request, timeout=30) as response:
                    catalog = json.load(response)
                respond(id, {'content': [{'type': 'text', 'text': json.dumps(catalog)}],
                             'structuredContent': catalog})
            except Exception as exc:
                respond(id, {'isError': True, 'content': [{'type': 'text', 'text': f'{type(exc).__name__}: {exc}'}]})
            return
        task = arguments.get('task')
        agent_type = arguments.get('agent_type')
        candidate_id = arguments.get('candidate_id')
        if (params.get('name') != TOOL['name'] or agent_type not in ('coding', 'research')
                or not isinstance(task, str) or not 1 <= len(task) <= 4000
                or candidate_id not in ((None, 'qwen35_shared_1060') if config.cloud_parent else
                                        (None, 'qwen35_shared_1060', 'codex_terra', 'codex_luna'))
                or set(arguments) - set(TOOL['inputSchema']['properties'])):
            respond(id, {'isError': True, 'content': [{'type': 'text', 'text': 'invalid delegate_task arguments'}]})
            return
        try:
            parent = config.parent_route
            root = Path(config.receipt_dir)
            receipt = run_child(parent_id=parent, agent_type=agent_type, prompt=task,
                                out=root / uuid4().hex,
                                gateway=('http://127.0.0.1:8080' if config.cloud_parent else
                                         os.environ.get('SUBAGENT_GATEWAY', 'http://127.0.0.1:8080')),
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
