#!/usr/bin/env python3
"""Frozen delegation fixture: one child computes a question hidden until tool result."""

import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gateway_subagent import run_child
from subagent_contract import canonical_integer_answer

QUESTION = 'What is 7 multiplied by 6? Return only the decimal number.'
ANSWER = '42'
TOOL = {'name': 'delegate_task',
        'description': 'Ask a coding child agent to answer a private arithmetic check. The child question is revealed with its result so the parent can verify the answer. The manager chooses and prepares its GPU route.',
        'inputSchema': {'type': 'object', 'properties': {
            'agent_type': {'type': 'string', 'enum': ['coding']},
            'task': {'type': 'string', 'minLength': 1, 'maxLength': 300}},
            'required': ['agent_type', 'task'], 'additionalProperties': False}}


def main():
    parent_route = sys.argv[1]
    receipt_dir = Path(sys.argv[2])
    log_path = Path(sys.argv[3])
    def log(entry):
        with log_path.open('a') as stream:
            stream.write(json.dumps({'at_unix': time.time(), **entry}) + '\n')
    for line in sys.stdin:
        try:
            packet = json.loads(line)
        except ValueError:
            continue
        if 'id' not in packet:
            continue
        method, ident = packet.get('method'), packet['id']
        if method == 'initialize':
            result = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}},
                      'serverInfo': {'name': 'subagent-comparison', 'version': '1'}}
        elif method == 'tools/list':
            result = {'tools': [TOOL]}
        elif method == 'ping':
            result = {}
        elif method == 'tools/call':
            params = packet.get('params') or {}
            args = params.get('arguments') or {}
            log({'method': method, 'tool': params.get('name'), 'arguments': args})
            if (params.get('name') != 'delegate_task' or args.get('agent_type') != 'coding'
                    or not isinstance(args.get('task'), str) or not 1 <= len(args['task']) <= 300):
                data, failed = {'error': 'invalid delegate_task arguments'}, True
            else:
                try:
                    receipt = run_child(parent_id=parent_route,
                        agent_type='coding', prompt=args['task'] + '\n' + QUESTION,
                        out=receipt_dir / uuid4().hex,
                        gateway=os.environ.get('SUBAGENT_GATEWAY', 'http://127.0.0.1:8080'),
                        max_tokens=96, timeout_s=90)
                    canonical = canonical_integer_answer(receipt['answer'])
                    data = {'question': QUESTION, 'child_answer': canonical,
                            'child_raw_answer': receipt['answer'],
                            'parent_gpu_ids': receipt['parent_gpu_ids'],
                            'child_gpu_ids': receipt['child_gpu_ids'],
                            'child_route': receipt['child_route'],
                            'child_exit_code': receipt['exit_code'],
                            'roster_stable': receipt['roster_stable']}
                    failed = receipt['exit_code'] != 0 or not receipt['roster_stable'] or canonical != ANSWER
                except Exception as exc:
                    data, failed = {'error': f'{type(exc).__name__}: {exc}'}, True
            log({'method': 'tool/result', 'tool': 'delegate_task', 'data': data, 'isError': failed})
            result = {'isError': failed, 'content': [{'type': 'text', 'text': json.dumps(data)}],
                      'structuredContent': data}
        else:
            print(json.dumps({'jsonrpc': '2.0', 'id': ident,
                              'error': {'code': -32601, 'message': 'Method not found'}}), flush=True)
            continue
        print(json.dumps({'jsonrpc': '2.0', 'id': ident, 'result': result}), flush=True)


if __name__ == '__main__':
    main()
