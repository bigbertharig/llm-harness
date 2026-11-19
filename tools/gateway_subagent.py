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
import re
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ready_roster import fetch_ready_roster
from subagent_contract import child_system_prompt
from codex_child import run_codex_child
from child_public_tools import parse_request, call_tool
from child_policy import ToolBudget, guard_child_run, validate_request

HOME = Path('/home/bryan')
ROOT = Path(__file__).resolve().parents[1]
NODE = HOME / '.local/opt/node-v24.14.0-linux-arm64/bin/node'
PI_CLI = HOME / 'harness-runtimes/pi-1.4.0/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js'
BASE_MODEL = ROOT / 'tools/comparison_fixtures/pi_models.json'
BASE_SETTINGS = ROOT / 'tools/comparison_fixtures/pi_settings.json'
TOOL_REGISTRY = ROOT / 'tools/tool_registry.json'
SEARCH_SERVER = ROOT / 'mcp_servers/rig_search/mcp_server.py'
WORKSPACE_SERVER = ROOT / 'tools/workspace_read_mcp.py'
GOOGLE_SERVER = ROOT / 'tools/google_workspace_mcp.py'


def _extension_flags(tool_profile: str) -> list[str]:
    """Enable only the built-in MCP loader for the native Google profile."""
    return [] if tool_profile == 'google_workspace' else ['--no-extensions']


def malformed_child_output(text: str) -> bool:
    """Recognize shared-decoder loops before wasting a repair turn."""
    if not isinstance(text, str):
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) >= 12:
        most_common = max(lines.count(line) for line in set(lines))
        if most_common >= 8 and most_common * 2 >= len(lines):
            return True
    compact = re.sub(r'\s+', ' ', text).strip()
    return len(text) >= 400 and len(compact) * 3 < len(text)


def _validate_child_tools(tool_profile: str, workspace_root: Path | None = None) -> None:
    """Fail before route allocation when a requested child tool surface is unavailable."""
    if tool_profile == 'none':
        return
    if tool_profile not in ('public_research', 'workspace_read', 'google_workspace'):
        raise ValueError('unknown child tool profile')
    registry = json.loads(TOOL_REGISTRY.read_text())
    if tool_profile == 'public_research':
        server_name = 'rig_search'
        names = ('search_web', 'fetch_page')
        surface = registry['surfaces'][server_name]
        approved = {row['name'] for row in surface['tools'] if row.get('approval') == 'automatic'}
        if surface.get('status') != 'dashboard' or not set(names) <= approved:
            raise ValueError('public research tools are not approved in the harness catalog')
        env_file = Path(os.environ.get('RIG_SEARCH_ENV_FILE') or ROOT / '.env').resolve()
        if not SEARCH_SERVER.is_file() or not env_file.is_file():
            raise ValueError('public research MCP server or provider config is unavailable')
    elif tool_profile == 'workspace_read':
        names = ('list_workspace_files', 'find_workspace_files', 'read_workspace_file',
                 'search_workspace_text')
        surface = registry['surfaces']['workspace_read']
        approved = {row['name'] for row in surface['tools'] if row.get('approval') == 'automatic'}
        if (surface.get('status') != 'dashboard' or approved != set(names) or
                workspace_root is None or not workspace_root.is_dir() or
                not WORKSPACE_SERVER.is_file()):
            raise ValueError('workspace read tools or selected root are unavailable')
    else:
        surface = registry['surfaces']['google_workspace']
        approved = {row['name'] for row in surface['tools'] if row.get('approval') == 'automatic'}
        if surface.get('status') != 'dashboard' or not approved or not GOOGLE_SERVER.is_file():
            raise ValueError('Google Workspace tools are not approved or unavailable')


def _child_tools(agent: Path, out: Path, tool_profile: str,
                 workspace_root: Path | None = None) -> list[str]:
    """Build a per-child MCP allowlist from the harness's approved inventory."""
    _validate_child_tools(tool_profile, workspace_root)
    if tool_profile == 'none':
        return ['--no-tools', '--no-mcp']
    if tool_profile == 'public_research':
        server_name = 'rig_search'
        names = ('search_web', 'fetch_page')
        env_file = Path(os.environ.get('RIG_SEARCH_ENV_FILE') or ROOT / '.env').resolve()
        args = [str(SEARCH_SERVER), str(out / 'search_events.jsonl'),
                '--env-file', str(env_file), '--endpoint', 'http://127.0.0.1:8888',
                '--providers', 'searxng']
    elif tool_profile == 'workspace_read':
        server_name = 'workspace_read'
        names = ('list_workspace_files', 'find_workspace_files', 'read_workspace_file',
                 'search_workspace_text')
        args = [str(WORKSPACE_SERVER), '--root', str(workspace_root)]
    else:
        server_name = 'google_workspace'
        surface = json.loads(TOOL_REGISTRY.read_text())['surfaces'][server_name]
        names = tuple(row['name'] for row in surface['tools'] if row.get('approval') == 'automatic')
        args = [str(GOOGLE_SERVER)]
    (agent / 'mcp.json').write_text(json.dumps({'mcpServers': {server_name: {
        'command': sys.executable,
        'args': args,
        'exposure': 'hidden',
        'toolExposure': {name: 'direct' for name in names},
    }}}, indent=2))
    # The parent bridge dispatches each validated call and can enforce its cap
    # before execution. Pi's native tool events arrive after dispatch.
    if tool_profile == 'google_workspace':
        # Google operations carry their own strict schemas, explicit write
        # confirmation, idempotency keys, and durable Gateway receipts. Expose
        # that reviewed MCP server natively so every model sees real tools,
        # while keeping Pi's shell and filesystem tools disabled.
        return ['--no-builtin-tools', '--tools', 'mcp__google_workspace__*']
    return ['--no-tools', '--no-mcp']


def resolve_child(gateway: str, parent_id: str, agent_type: str,
                  candidate_id: str | None = None, min_context: int = 4096,
                  context_tokens: int | None = None, worker_strategy: str = 'auto') -> dict:
    body = json.dumps({'parent_route': parent_id, 'agent_type': agent_type,
                       'min_context': min_context,
                       **({'worker_strategy': worker_strategy} if worker_strategy != 'auto' else {}),
                       **({'context_tokens': context_tokens} if context_tokens is not None else {}),
                       **({'candidate_id': candidate_id} if candidate_id else {})}).encode()
    headers = {'Content-Type': 'application/json'}
    if os.environ.get('LLM_GATEWAY_API_KEY'):
        headers['Authorization'] = 'Bearer ' + os.environ['LLM_GATEWAY_API_KEY']
    request = Request(gateway.rstrip('/') + '/v1/manager/agent-routes/resolve',
                      data=body, headers=headers, method='POST')
    try:
        with urlopen(request, timeout=310) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')
        try:
            payload = json.loads(detail)
            error = payload.get('error') if isinstance(payload, dict) else None
            detail = (payload.get('detail') or (error.get('message') if isinstance(error, dict) else None)
                      or payload) if isinstance(payload, dict) else payload
        except (ValueError, AttributeError):
            pass
        raise RuntimeError(f'manager rejected child route ({exc.code}): {detail}') from exc


def release_child(gateway: str, parent_id: str, route: str, *,
                  service_instance_id: str | None = None,
                  reservation_id: str | None = None) -> dict:
    body = json.dumps({'parent_route': parent_id, 'route': route,
                       **({'service_instance_id': service_instance_id}
                          if service_instance_id else {}),
                       **({'reservation_id': reservation_id}
                          if reservation_id else {})}).encode()
    headers = {'Content-Type': 'application/json'}
    if os.environ.get('LLM_GATEWAY_API_KEY'):
        headers['Authorization'] = 'Bearer ' + os.environ['LLM_GATEWAY_API_KEY']
    request = Request(gateway.rstrip('/') + '/v1/manager/agent-routes/release',
                      data=body, headers=headers, method='POST')
    with urlopen(request, timeout=120) as response:
        return json.load(response)


def _validate_ephemeral_admission(child: dict) -> None:
    """Refuse an ephemeral route without Gateway's complete admission receipt."""
    if not child.get('ephemeral'):
        return
    instance = child.get('service_instance_id')
    reservation = child.get('reservation')
    admission = child.get('admission')
    if not isinstance(instance, str) or not instance:
        raise ValueError('ephemeral child has no service instance identity')
    if not isinstance(reservation, dict) or not isinstance(reservation.get('reservation_id'), str):
        raise ValueError('ephemeral child has no reservation identity')
    if reservation.get('service_instance_id') != instance:
        raise ValueError('ephemeral child reservation belongs to another service instance')
    if not isinstance(admission, dict) or admission.get('mode') != 'shared_model' \
            or admission.get('service_instance_id') != instance \
            or admission.get('reservation_id') != reservation['reservation_id']:
        raise ValueError('ephemeral child admission receipt is inconsistent')


def _release_ephemeral(gateway: str, parent_id: str, child: dict) -> dict:
    reservation = child.get('reservation') or {}
    return release_child(gateway, parent_id, child['route'],
                         service_instance_id=child.get('service_instance_id'),
                         reservation_id=reservation.get('reservation_id'))


def _models_config(route: dict, gateway: str, max_tokens: int) -> dict:
    config = json.loads(BASE_MODEL.read_text())
    provider = config['providers']['rig']
    provider['baseUrl'] = gateway.rstrip('/') + '/v1'
    model = provider['models'][0]
    model.update(id=route['route'], name='Prepared child ' + route['model'],
                 contextWindow=route['context_length'], maxTokens=max_tokens)
    return config


@guard_child_run
def run_child(*, parent_id: str, agent_type: str, prompt: str, out: Path, gateway: str,
              max_tokens: int = 1536, timeout_s: int = 300,
              candidate_id: str | None = None, tool_profile: str = 'none',
              workspace_root: Path | None = None, min_context: int = 4096,
              context_tokens: int | None = None, worker_strategy: str = 'auto') -> dict:
    if max_tokens < 1 or max_tokens > 4096 or timeout_s < 1 or timeout_s > 600:
        raise ValueError('child budget outside allowed bounds')
    if type(min_context) is not int or not 1 <= min_context <= 262144:
        raise ValueError('minimum context must be between 1 and 262144 tokens')
    if context_tokens is not None and (type(context_tokens) is not int
            or not 16384 <= context_tokens <= 262144 or context_tokens < min_context):
        raise ValueError('requested context must be 16384..262144 and meet the minimum')
    if worker_strategy not in ('auto', 'shared_model', 'separate_model'):
        raise ValueError('unknown worker strategy')
    if worker_strategy == 'separate_model' and candidate_id is not None:
        raise ValueError('candidate_id cannot be combined with separate_model')
    if tool_profile not in ('none', 'public_research', 'workspace_read', 'google_workspace'):
        raise ValueError('unknown child tool profile')
    if tool_profile == 'workspace_read':
        if workspace_root is None:
            raise ValueError('workspace read profile requires a selected root')
        workspace_root = workspace_root.resolve(strict=True)
        if not workspace_root.is_dir():
            raise ValueError('selected workspace root is not a directory')
    _validate_child_tools(tool_profile, workspace_root)
    out = out.resolve()
    if out.exists():
        raise FileExistsError(out)
    if parent_id == 'cloud/codex' and candidate_id in ('codex_terra', 'codex_luna'):
        raise ValueError('a cloud parent may request only a local child')
    if candidate_id in ('codex_terra', 'codex_luna') and tool_profile != 'none':
        raise ValueError('the selected Codex child does not support this tool profile')
    selected = fetch_ready_roster(gateway, os.environ.get('LLM_GATEWAY_API_KEY'))
    if candidate_id in ('codex_terra', 'codex_luna'):
        parent = next((row for row in selected['data'] if row['id'] == parent_id), None)
        if parent is None:
            raise ValueError('parent route is not ready')
        receipt = run_codex_child(candidate_id=candidate_id, agent_type=agent_type,
                                  prompt=prompt, out=out, gateway=gateway, timeout_s=timeout_s)
        receipt.update(parent_route=parent_id, parent_gpu_ids=parent.get('gpu_ids', []),
                       child_gpu_ids=[], child_route='codex/' + receipt['child_model'],
                       roster_stable=any(row == parent for row in fetch_ready_roster(
                           gateway, os.environ.get('LLM_GATEWAY_API_KEY'))['data']))
        (out / 'summary.json').write_text(json.dumps(receipt, indent=2) + '\n')
        return receipt
    child = resolve_child(gateway, parent_id, agent_type, candidate_id, min_context,
                          context_tokens, worker_strategy)
    released = False
    try:
        _validate_ephemeral_admission(child)
        selected = fetch_ready_roster(gateway, os.environ.get('LLM_GATEWAY_API_KEY'))
        by_id = {row['id']: row for row in selected['data']}
        parent = by_id.get(parent_id)
        if (parent_id != 'cloud/codex' and not parent) or \
                by_id.get(child['route'], {}).get('gpu_ids') != child['gpu_ids']:
            raise ValueError('manager selection differs from ready roster')
        out.mkdir(parents=True)
        agent = out / 'agent'
        agent.mkdir()
        (agent / 'models.json').write_text(json.dumps(_models_config(child, gateway, max_tokens), indent=2))
        (agent / 'settings.json').write_bytes(BASE_SETTINGS.read_bytes())
        (agent / 'auth.json').write_text('{}')
        (agent / 'models-store.json').write_text('{}')
        tool_flags = _child_tools(agent, out, tool_profile, workspace_root)
        workspace = out / 'workspace'
        workspace.mkdir()
        env = os.environ.copy()
        env['PI_CODING_AGENT_DIR'] = str(agent)
        extension_flags = _extension_flags(tool_profile)
        command = [str(NODE), str(PI_CLI), '--mode', 'rpc', '--offline',
                   *tool_flags, *extension_flags, '--no-skills', '--no-prompt-templates',
                   '--no-context-files', '--session-dir', str(out / 'sessions'),
                   '--system-prompt', child_system_prompt(agent_type, tool_profile),
                   '--provider', 'rig', '--model', child['route']]
        started = time.monotonic()
        answer, error = '', None
        native_tool_calls = 0
        bridge_calls = []
        budget = ToolBudget()
        attempted = set()
        repair_attempted = False
        tool_bridge = None
        if tool_profile != 'none':
            server_name, server_config = next(iter(json.loads((agent / 'mcp.json').read_text())['mcpServers'].items()))
            tool_bridge = {'name': server_name,
                           'command': [server_config['command'], *server_config['args']],
                           'tools': list(server_config['toolExposure'])}
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
                    if out.with_suffix('.cancel').exists():
                        error = 'cancelled'
                        break
                    try:
                        event = received.get(timeout=min(0.5, max(0.01, deadline - time.monotonic())))
                    except queue.Empty:
                        continue
                    if event.get('type') == 'tool_execution_start' and tool_profile != 'none' \
                            and native_tool_calls >= 5:
                        error = 'child exceeded its tool-call limit'
                        break
                    if event.get('type') == 'tool_execution_end':
                        native_tool_calls += 1
                    if event.get('type') == 'message_end' and event.get('message', {}).get('role') == 'assistant':
                        answer = ''.join(block.get('text', '') for block in event['message'].get('content', [])
                                         if block.get('type') == 'text')
                        if event['message'].get('stopReason') == 'error':
                            error = event['message'].get('errorMessage') or 'model error'
                    if event.get('type') == 'agent_settled':
                        if malformed_child_output(answer):
                            error = 'shared model produced malformed repetitive output'
                            break
                        if tool_bridge and native_tool_calls == 0:
                            request = parse_request(answer, tool_bridge, tool_bridge['tools'])
                            if request:
                                name, arguments = request
                                fingerprint = json.dumps(request, sort_keys=True)
                                if fingerprint in attempted:
                                    error = 'child repeated or exceeded its tool-call limit'
                                    break
                                attempted.add(fingerprint)
                                try:
                                    budget.before_call()
                                    validate_request(tool_profile, name, arguments, workspace_root)
                                    result = call_tool(tool_bridge, name, arguments,
                                                       timeout=min(45, max(1, deadline - time.monotonic() - 5)))
                                    budget.record(result)
                                except Exception as exc:
                                    error = f'child tool call failed: {type(exc).__name__}: {exc}'
                                    break
                                bridge_calls.append({'tool': name, 'is_error': bool(result.get('isError'))})
                                if result.get('isError'):
                                    if budget.calls >= budget.receipt()['max_calls']:
                                        error = f'child tool returned repeated errors: {name}'
                                        break
                                    feedback = ('MCP tool rejected the arguments for ' + name + ':\n' +
                                                json.dumps(result, ensure_ascii=False)[:3000] +
                                                '\nCorrect the arguments and return one JSON tool request. '
                                                'Do not invent a result.')
                                else:
                                    evidence = result.get('structuredContent') or result.get('content') or result
                                    feedback = ('MCP result for ' + name + ':\n' +
                                                json.dumps(evidence, ensure_ascii=False)[:20000] +
                                                '\nContinue the original task. If another tool is needed, return '
                                                'only a JSON object with name and arguments. Otherwise answer '
                                                'the user with the evidence and paths you used.')
                                proc.stdin.write(json.dumps({'id': f'tool-feedback-{len(bridge_calls)}',
                                                             'type': 'prompt', 'message': feedback}) + '\n')
                                proc.stdin.flush()
                                continue
                            if not bridge_calls and not repair_attempted:
                                repair_attempted = True
                                allowed = ['mcp__' + tool_bridge['name'] + '__' + name
                                           for name in tool_bridge['tools']]
                                correction = ('No allowed MCP tool call ran. If the task needs tool evidence, '
                                              'return exactly one JSON object with keys name and arguments. '
                                              'Use an allowed name and valid arguments: ' +
                                              json.dumps(allowed) + '. '
                                              'Do not invent a tool result.')
                                proc.stdin.write(json.dumps({'id': 'tool-format-repair', 'type': 'prompt',
                                                             'message': correction}) + '\n')
                                proc.stdin.flush()
                                continue
                            if not any(not call['is_error'] for call in bridge_calls):
                                error = 'child did not execute an allowed tool'
                        break
                    if event.get('type') == '_eof':
                        error = 'child process exited before settling'
                        break
                else:
                    error = 'timeout'
            finally:
                if proc.poll() is None:
                    if error == 'cancelled':
                        proc.terminate()
                    else:
                        proc.stdin.close()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.terminate()
                        proc.wait(timeout=5)
        exit_code = proc.returncode
        if tool_profile != 'none' and not error and not native_tool_calls \
                and not any(not call['is_error'] for call in bridge_calls):
            error = 'child did not execute an allowed tool'
        after = fetch_ready_roster(gateway, os.environ.get('LLM_GATEWAY_API_KEY'))
        after_rows = {row['id']: row for row in after['data']}
        stable = ((parent_id == 'cloud/codex' or after_rows.get(parent['id']) == parent) and
                  after_rows.get(child['route']) == by_id[child['route']])
        receipt = {'agent_type': agent_type, 'parent_route': parent_id,
                   'parent_gpu_ids': [] if parent_id == 'cloud/codex' else parent['gpu_ids'],
                   'child_route': child['route'], 'child_gpu_ids': child['gpu_ids'],
                   'child_model': child['model'], 'child_context': child['context_length'],
                   'service_instance_id': child.get('service_instance_id'),
                   'admission': child.get('admission'),
                   'reservation': child.get('reservation'),
                   'tool_profile': tool_profile, 'minimum_context_tokens': min_context,
                   'requested_context_tokens': context_tokens,
                   'requested_worker_strategy': worker_strategy,
                   'tool_mode': 'native' if native_tool_calls else 'text_bridge' if bridge_calls else 'none',
                   'tool_calls': native_tool_calls + len(bridge_calls),
                   'tool_call_summary': bridge_calls,
                   'tool_budget': budget.receipt(),
                   'tool_format_repair_attempted': repair_attempted,
                   'max_tokens': max_tokens, 'timeout_s': timeout_s,
                   'duration_s': round(time.monotonic() - started, 2), 'exit_code': exit_code,
                   'roster_stable': stable, 'answer': answer, 'error': error}
        if child.get('ephemeral'):
            try:
                release_receipt = _release_ephemeral(gateway, parent_id, child)
                receipt['released'] = True
                receipt['release_receipt'] = release_receipt
                released = True
            except Exception as exc:
                receipt['released'] = False
                receipt['error'] = (receipt['error'] or '') + f' child release failed: {type(exc).__name__}: {exc}'
        (out / 'summary.json').write_text(json.dumps(receipt, indent=2))
        return receipt

    except BaseException:
        if child.get('ephemeral') and not released:
            try:
                _release_ephemeral(gateway, parent_id, child)
            except Exception:
                pass
        raise

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent-route', required=True)
    parser.add_argument('--agent-type', required=True, choices=['coding', 'research'])
    parser.add_argument('--candidate-id', help='Optional manager catalog candidate; omit to use the loaded shared model')
    parser.add_argument('--gateway', default='http://127.0.0.1:8080')
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--max-tokens', type=int, default=1536)
    parser.add_argument('--timeout', type=int, default=300)
    parser.add_argument('--tool-profile', choices=['none', 'public_research', 'workspace_read'], default='none')
    parser.add_argument('--workspace-root', type=Path)
    parser.add_argument('--min-context', type=int, default=4096)
    parser.add_argument('--worker-strategy', choices=['auto', 'shared_model', 'separate_model'], default='auto')
    parser.add_argument('prompt')
    args = parser.parse_args()
    result = run_child(parent_id=args.parent_route, agent_type=args.agent_type,
                       prompt=args.prompt, out=args.out, gateway=args.gateway,
                       max_tokens=args.max_tokens, timeout_s=args.timeout,
                       candidate_id=args.candidate_id, tool_profile=args.tool_profile,
                       workspace_root=args.workspace_root, min_context=args.min_context,
                       worker_strategy=args.worker_strategy)
    print(json.dumps(result))
    return 0 if result['exit_code'] == 0 and result['roster_stable'] and result['answer'] \
        and not result.get('error') else 1


if __name__ == '__main__':
    sys.exit(main())
