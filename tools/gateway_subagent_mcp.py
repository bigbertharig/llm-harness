#!/usr/bin/env python3
"""Stdio MCP adapter for one native child agent on a separate ready GPU route."""

import argparse
import json
import os
import signal
from pathlib import Path
import sys
from urllib.request import Request, urlopen
from uuid import uuid4

from gateway_subagent import run_child

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--parent-route', default=os.environ.get('SUBAGENT_PARENT_ROUTE'))
parser.add_argument('--cloud-parent', action='store_true', help='Codex dashboard parent; delegate only to local rigs')
parser.add_argument('--receipt-dir', default=os.environ.get('SUBAGENT_RECEIPT_DIR'))
parser.add_argument('--workspace-root', type=Path,
                    help='Selected coding workspace; enables the read-only workspace tool profile')
parser.add_argument('--coding-only', action='store_true',
                    help='Exclude public research tools from coding sessions')
config = parser.parse_args()
active_child_dir = None


def request_stop(_signum, _frame):
    if active_child_dir is not None:
        active_child_dir.with_suffix('.cancel').touch()


signal.signal(signal.SIGTERM, request_stop)
if config.cloud_parent:
    if config.parent_route:
        parser.error('--cloud-parent and --parent-route cannot be combined')
    config.parent_route = 'cloud/codex'
if not config.parent_route or not config.receipt_dir:
    parser.error('--parent-route or --cloud-parent, and --receipt-dir are required')
if config.workspace_root:
    try:
        config.workspace_root = config.workspace_root.resolve(strict=True)
    except OSError:
        parser.error('selected workspace root is unavailable')
    if not config.workspace_root.is_dir():
        parser.error('selected workspace root must be a directory')

TOOL = {'name': 'delegate_task',
        'description': 'Spawn a bounded child agent for one task. When the parent uses a shared-weight model, the manager attaches another chat of that same loaded model if a worker slot fits. Use list_local_agents to inspect optional candidates. The child cannot delegate further. Verify its answer before relying on it.',
        'inputSchema': {'type': 'object', 'properties': {
            'agent_type': {'type': 'string', 'enum': ['coding', 'research'],
                           'description': 'Choose coding for repository work and research for evidence gathering.'},
            'task': {'type': 'string', 'minLength': 1, 'maxLength': 4000,
                     'description': 'One bounded, self-contained goal. Include relevant paths, constraints, and the desired output.'},
            'acceptance_criteria': {'type': 'string', 'minLength': 1, 'maxLength': 2000,
                                    'description': 'Concrete conditions the child result must satisfy.'},
            'verification': {'type': 'string', 'minLength': 1, 'maxLength': 1000,
                             'description': 'Checks the child should perform or evidence it should return.'},
            'max_tool_calls': {'type': 'integer', 'minimum': 1, 'maximum': 12,
                               'description': 'Maximum tool calls for this task. Use the smallest evidence budget that can complete it.'},
            'candidate_id': {'type': 'string', 'minLength': 1, 'maxLength': 80,
                             'description': 'Optional candidate returned by list_local_agents; omit to use the loaded shared model.'},
            'minimum_context_tokens': {'type': 'integer', 'minimum': 1, 'maximum': 262144,
                                       'description': 'Minimum acceptable context capacity.'},
            'context_tokens': {'type': 'integer', 'minimum': 16384, 'maximum': 262144,
                               'description': 'Requested capacity for a newly attached shared-model chat. Omit to use that candidate\'s default.'},
            'worker_strategy': {'type': 'string',
                                'enum': ['auto', 'shared_model', 'separate_model'],
                                'description': 'auto lets Gateway choose; shared_model requires another context in the loaded model; separate_model requests an independently loaded small model.'},
            'tool_profile': {'type': 'string', 'enum': ['none', 'public_research', 'workspace_read', 'workspace_git', 'google_workspace'],
                             'description': 'Use workspace_read for current repository files, workspace_git for local history and diffs, public_research for public web evidence, or google_workspace for the dedicated rig account.'}},
            'required': ['agent_type', 'task'], 'additionalProperties': False}}
if config.cloud_parent:
    TOOL['description'] = ('Spawn one bounded coding or research agent on the loaded shared model when available. '
                           'The manager attaches a new chat and chooses its GPU. Use list_local_agents before '
                           'requesting a specific candidate_id; omit it to use the loaded shared model. '
                           'Set tool_profile=public_research to give the child public search and page fetch; '
                           'Set tool_profile=google_workspace for the generic Gmail, Drive, Docs, and Sheets tools; '
                           'Set tool_profile=workspace_read to let the child list and read only the selected '
                           'coding workspace, or workspace_git for bounded read-only local Git evidence. '
                           'Otherwise it has no tools. Verify its answer.')
else:
    TOOL['inputSchema']['properties'].pop('candidate_id')
    TOOL['description'] = ('Use only when the user asks to spawn or delegate to an agent. '
                           'Spawn one bounded child chat of the already-loaded shared model. '
                           'The manager chooses an available worker; no model candidate or GPU selection is needed.')
if not config.workspace_root:
    TOOL['inputSchema']['properties']['tool_profile']['enum'] = ['none', 'public_research', 'google_workspace']
if config.coding_only:
    TOOL['inputSchema']['properties']['tool_profile']['enum'] = ['none', 'workspace_read', 'workspace_git']
    TOOL['description'] = ('Give one bounded coding or research task to a local GPU child. '
                           'The child may read and search only the selected workspace with '
                           'tool_profile=workspace_read or inspect local history with workspace_git; '
                           'no public web tools are available. '
                           'The manager selects the model route and GPUs. Verify its answer.')

LIST_TOOL = {'name': 'list_local_agents',
             'description': 'List available research and coding child models when the user asks to inspect them. '
                            'Local shared-model chats delegate to their own loaded model automatically.',
             'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}}

SWAP_TOOL = {'name': 'swap_local_agent_model',
             'description': ('Explicitly replace the currently loaded shared local-agent model. '
                             'Use only when the user directly asks to swap models; ordinary '
                             'delegation must never evict a different model implicitly.'),
             'inputSchema': {'type': 'object', 'properties': {
                 'candidate_id': {'type': 'string', 'minLength': 1, 'maxLength': 80},
                 'expected_candidate_id': {'type': 'string', 'minLength': 1, 'maxLength': 80},
                 'expected_instance_id': {'type': 'string', 'minLength': 1, 'maxLength': 100},
                 'confirmation': {'type': 'string', 'enum': ['swap local agent model']}},
                 'required': ['candidate_id', 'expected_candidate_id', 'expected_instance_id',
                              'confirmation'], 'additionalProperties': False}}


def advertised_tools():
    return [LIST_TOOL, *([SWAP_TOOL] if config.cloud_parent else []), TOOL]


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
        respond(id, {'tools': advertised_tools()})
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
        if params.get('name') == SWAP_TOOL['name']:
            if (not config.cloud_parent or set(arguments) != {
                    'candidate_id', 'expected_candidate_id', 'expected_instance_id', 'confirmation'}
                    or arguments.get('confirmation') != 'swap local agent model'
                    or not all(isinstance(arguments.get(key), str) and arguments[key]
                               for key in ('candidate_id', 'expected_candidate_id',
                                           'expected_instance_id'))):
                respond(id, {'isError': True, 'content': [{'type': 'text',
                        'text': 'invalid swap_local_agent_model arguments'}]})
                return
            try:
                headers = {'Content-Type': 'application/json'}
                if os.environ.get('LLM_GATEWAY_API_KEY'):
                    headers['Authorization'] = 'Bearer ' + os.environ['LLM_GATEWAY_API_KEY']
                body = {key: arguments[key] for key in (
                    'candidate_id', 'expected_candidate_id', 'expected_instance_id')}
                request = Request('http://127.0.0.1:8080/v1/manager/local-agent-model/swap',
                                  data=json.dumps(body).encode(), headers=headers, method='POST')
                with urlopen(request, timeout=300) as response:
                    result = json.load(response)
                respond(id, {'content': [{'type': 'text', 'text': json.dumps(result)}],
                             'structuredContent': result})
            except Exception as exc:
                respond(id, {'isError': True, 'content': [{'type': 'text',
                        'text': f'{type(exc).__name__}: {exc}'}]})
            return
        task = arguments.get('task')
        acceptance_criteria = arguments.get('acceptance_criteria')
        verification = arguments.get('verification')
        max_tool_calls = arguments.get('max_tool_calls', 12)
        agent_type = arguments.get('agent_type')
        candidate_id = arguments.get('candidate_id')
        min_context = arguments.get('minimum_context_tokens', 4096)
        context_tokens = arguments.get('context_tokens')
        worker_strategy = arguments.get('worker_strategy', 'auto')
        tool_profile = arguments.get('tool_profile', 'none')
        if (params.get('name') != TOOL['name'] or agent_type not in ('coding', 'research')
                or not isinstance(task, str) or not 1 <= len(task) <= 4000
                or (acceptance_criteria is not None and (not isinstance(acceptance_criteria, str)
                    or not 1 <= len(acceptance_criteria) <= 2000))
                or (verification is not None and (not isinstance(verification, str)
                    or not 1 <= len(verification) <= 1000))
                or type(max_tool_calls) is not int or not 1 <= max_tool_calls <= 12
                or (candidate_id is not None and (not isinstance(candidate_id, str)
                    or not 1 <= len(candidate_id) <= 80))
                or type(min_context) is not int or not 1 <= min_context <= 262144
                or (context_tokens is not None and (type(context_tokens) is not int
                    or not 16384 <= context_tokens <= 262144 or context_tokens < min_context))
                or worker_strategy not in ('auto', 'shared_model', 'separate_model')
                or (config.cloud_parent and candidate_id in ('codex_terra', 'codex_luna'))
                or tool_profile not in TOOL['inputSchema']['properties']['tool_profile']['enum']
                or (candidate_id in ('codex_terra', 'codex_luna') and tool_profile != 'none')
                or set(arguments) - set(TOOL['inputSchema']['properties'])):
            respond(id, {'isError': True, 'content': [{'type': 'text', 'text': 'invalid delegate_task arguments'}]})
            return
        try:
            global active_child_dir
            parent = config.parent_route
            root = Path(config.receipt_dir)
            assigned_task = task
            if acceptance_criteria:
                assigned_task += '\n\nAcceptance criteria:\n' + acceptance_criteria
            if verification:
                assigned_task += '\n\nVerification:\n' + verification
            gateway = ('http://127.0.0.1:8080' if config.cloud_parent else
                       os.environ.get('SUBAGENT_GATEWAY', 'http://127.0.0.1:8080'))
            def execute_once():
                global active_child_dir
                child_id = uuid4().hex
                active_child_dir = root / child_id
                result = run_child(parent_id=parent, agent_type=agent_type, prompt=assigned_task,
                                   out=active_child_dir, gateway=gateway,
                                   max_tool_calls=max_tool_calls,
                                   candidate_id=candidate_id, tool_profile=tool_profile,
                                   workspace_root=config.workspace_root, min_context=min_context,
                                   context_tokens=context_tokens, worker_strategy=worker_strategy)
                result['receipt_id'] = child_id
                (active_child_dir / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
                return result
            receipt = execute_once()
            if receipt.get('error') == 'shared model produced malformed repetitive output':
                first_id = receipt['receipt_id']
                receipt = execute_once()
                receipt['retry'] = {'attempted': True, 'first_receipt_id': first_id,
                                    'first_error': 'shared model produced malformed repetitive output'}
                (active_child_dir / 'summary.json').write_text(json.dumps(receipt, indent=2) + '\n')
            ok = receipt['exit_code'] == 0 and receipt['roster_stable'] and bool(receipt['answer']) \
                 and not receipt.get('error') \
                 and receipt.get('released', True) is not False
            respond(id, {'isError': not ok, 'content': [{'type': 'text', 'text': json.dumps(receipt)}],
                         'structuredContent': receipt})
        except Exception as exc:
            respond(id, {'isError': True, 'content': [{'type': 'text', 'text': f'{type(exc).__name__}: {exc}'}]})
        finally:
            active_child_dir = None
    else:
        print(json.dumps({'jsonrpc': '2.0', 'id': id,
                          'error': {'code': -32601, 'message': 'Method not found'}}), flush=True)


for line in sys.stdin:
    if line.strip():
        try:
            handle(json.loads(line))
        except ValueError:
            pass
