#!/usr/bin/env python3
"""Run one bounded Pi child agent on a different prepared gateway GPU route.

The manager prepares both routes. This client only reads the ready roster and
starts a separate native agent session. It never calls model-management APIs.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from urllib.request import Request, urlopen

from ready_roster import fetch_ready_roster

HOME = Path('/home/bryan')
NODE = HOME / '.local/opt/node-v24.14.0-linux-arm64/bin/node'
PI_CLI = HOME / 'harness-runtimes/pi-1.4.0/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js'
BASE_MODEL = HOME / 'llm-harness/tools/comparison_fixtures/pi_models.json'
BASE_SETTINGS = HOME / 'llm-harness/tools/comparison_fixtures/pi_settings.json'


def resolve_child(gateway: str, parent_id: str, agent_type: str) -> dict:
    body = json.dumps({'parent_route': parent_id, 'agent_type': agent_type}).encode()
    headers = {'Content-Type': 'application/json'}
    if os.environ.get('LLM_GATEWAY_API_KEY'):
        headers['Authorization'] = 'Bearer ' + os.environ['LLM_GATEWAY_API_KEY']
    request = Request(gateway.rstrip('/') + '/v1/manager/agent-routes/resolve',
                      data=body, headers=headers, method='POST')
    with urlopen(request, timeout=310) as response:
        return json.load(response)


def _models_config(route: dict, gateway: str, max_tokens: int) -> dict:
    config = json.loads(BASE_MODEL.read_text())
    provider = config['providers']['rig']
    provider['baseUrl'] = gateway.rstrip('/') + '/v1'
    model = provider['models'][0]
    model.update(id=route['route'], name='Prepared child ' + route['model'],
                 contextWindow=route['context_length'], maxTokens=max_tokens)
    return config


def run_child(*, parent_id: str, agent_type: str, prompt: str, out: Path, gateway: str,
              max_tokens: int = 512, timeout_s: int = 120) -> dict:
    if max_tokens < 1 or max_tokens > 2048 or timeout_s < 1 or timeout_s > 600:
        raise ValueError('child budget outside allowed bounds')
    out = out.resolve()
    if out.exists():
        raise FileExistsError(out)
    child = resolve_child(gateway, parent_id, agent_type)
    selected = fetch_ready_roster(gateway, os.environ.get('LLM_GATEWAY_API_KEY'))
    by_id = {row['id']: row for row in selected['data']}
    parent = by_id.get(parent_id)
    if not parent or by_id.get(child['route'], {}).get('gpu_ids') != child['gpu_ids']:
        raise ValueError('manager selection differs from ready roster')
    out.mkdir(parents=True)
    agent = out / 'agent'
    agent.mkdir()
    (agent / 'models.json').write_text(json.dumps(_models_config(child, gateway, max_tokens), indent=2))
    (agent / 'settings.json').write_bytes(BASE_SETTINGS.read_bytes())
    (agent / 'auth.json').write_text('{}')
    (agent / 'models-store.json').write_text('{}')
    workspace = out / 'workspace'
    workspace.mkdir()
    env = os.environ.copy()
    env['PI_CODING_AGENT_DIR'] = str(agent)
    command = [str(NODE), str(PI_CLI), '--mode', 'rpc', '--offline',
               '--no-tools', '--no-extensions', '--no-skills', '--no-prompt-templates',
               '--no-mcp', '--no-context-files', '--session-dir', str(out / 'sessions'),
               '--system-prompt', 'You are a bounded child agent. Complete only the assigned task and give a concise result.',
               '--provider', 'rig', '--model', child['route']]
    started = time.monotonic()
    answer, error = '', None
    with (out / 'events.jsonl').open('w') as events, (out / 'stderr.log').open('w') as stderr:
        proc = subprocess.Popen(command, cwd=workspace, env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=stderr, text=True, bufsize=1)
        received = queue.Queue()
        def reader():
            for line in proc.stdout:
                events.write(line)
                events.flush()
                try:
                    received.put(json.loads(line))
                except ValueError:
                    pass
            received.put({'type': '_eof'})
        threading.Thread(target=reader, daemon=True).start()
        try:
            proc.stdin.write(json.dumps({'id': 'child-task', 'type': 'prompt', 'message': prompt}) + '\n')
            proc.stdin.flush()
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                try:
                    event = received.get(timeout=max(0.01, deadline - time.monotonic()))
                except queue.Empty:
                    error = 'timeout'
                    break
                if event.get('type') == 'message_end' and event.get('message', {}).get('role') == 'assistant':
                    answer = ''.join(block.get('text', '') for block in event['message'].get('content', [])
                                     if block.get('type') == 'text')
                if event.get('type') == 'agent_settled':
                    break
                if event.get('type') == '_eof':
                    error = 'child process exited before settling'
                    break
            else:
                error = 'timeout'
        finally:
            if proc.poll() is None:
                proc.stdin.close()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    proc.wait(timeout=5)
    exit_code = proc.returncode
    after = fetch_ready_roster(gateway, os.environ.get('LLM_GATEWAY_API_KEY'))
    after_rows = {row['id']: row for row in after['data']}
    stable = (after_rows.get(parent['id']) == parent and
              after_rows.get(child['route']) == by_id[child['route']])
    receipt = {'agent_type': agent_type, 'parent_route': parent_id, 'parent_gpu_ids': parent['gpu_ids'],
               'child_route': child['route'], 'child_gpu_ids': child['gpu_ids'],
               'child_model': child['model'], 'child_context': child['context_length'],
               'max_tokens': max_tokens, 'timeout_s': timeout_s,
               'duration_s': round(time.monotonic() - started, 2), 'exit_code': exit_code,
               'roster_stable': stable, 'answer': answer, 'error': error}
    (out / 'summary.json').write_text(json.dumps(receipt, indent=2))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent-route', required=True)
    parser.add_argument('--agent-type', required=True, choices=['coding', 'research'])
    parser.add_argument('--gateway', default='http://127.0.0.1:8080')
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--max-tokens', type=int, default=512)
    parser.add_argument('--timeout', type=int, default=120)
    parser.add_argument('prompt')
    args = parser.parse_args()
    result = run_child(parent_id=args.parent_route, agent_type=args.agent_type,
                       prompt=args.prompt, out=args.out, gateway=args.gateway,
                       max_tokens=args.max_tokens, timeout_s=args.timeout)
    print(json.dumps(result))
    return 0 if result['exit_code'] == 0 and result['roster_stable'] and result['answer'] else 1


if __name__ == '__main__':
    sys.exit(main())
