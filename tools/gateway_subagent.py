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
import re
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ready_roster import fetch_ready_roster
from codex_child import run_codex_child
from child_public_tools import discover_tools
from child_policy import guard_child_run
from harness_core import get_tool_profile
from project_agent import run_agent as run_project_agent

ROOT = Path(__file__).resolve().parents[1]
TOOL_REGISTRY = ROOT / 'tools/tool_registry.json'
SEARCH_SERVER = ROOT / 'mcp_servers/rig_search/mcp_server.py'
WORKSPACE_SERVER = ROOT / 'tools/workspace_read_mcp.py'
WORKSPACE_GIT_SERVER = ROOT / 'tools/workspace_git_mcp.py'
GOOGLE_SERVER = ROOT / 'tools/google_workspace_mcp.py'


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
    if tool_profile not in ('public_research', 'workspace_read', 'workspace_git', 'google_workspace'):
        raise ValueError('unknown child tool profile')
    contract = get_tool_profile(tool_profile)
    if contract.requires_workspace and workspace_root is None:
        raise ValueError(f'{tool_profile} requires a selected workspace root')
    registry = json.loads(TOOL_REGISTRY.read_text())
    if tool_profile == 'public_research':
        server_name = 'rig_search'
        names = ('search_web', 'fetch_page')
        surface = registry['surfaces'][server_name]
        approved = {row['name'] for row in surface['tools'] if row.get('approval') == 'automatic'}
        if surface.get('status') != 'dashboard' or approved != contract.tools:
            raise ValueError('public research tools are not approved in the harness catalog')
        env_file = Path(os.environ.get('RIG_SEARCH_ENV_FILE') or ROOT / '.env').resolve()
        if not SEARCH_SERVER.is_file() or not env_file.is_file():
            raise ValueError('public research MCP server or provider config is unavailable')
    elif tool_profile == 'workspace_read':
        names = ('list_workspace_files', 'find_workspace_files', 'read_workspace_file',
                 'read_workspace_document_chunk', 'search_workspace_text')
        surface = registry['surfaces']['workspace_read']
        approved = {row['name'] for row in surface['tools'] if row.get('approval') == 'automatic'}
        if (surface.get('status') != 'dashboard' or approved != contract.tools or
                workspace_root is None or not workspace_root.is_dir() or
                not WORKSPACE_SERVER.is_file()):
            raise ValueError('workspace read tools or selected root are unavailable')
    elif tool_profile == 'workspace_git':
        names = ('get_workspace_git_status', 'get_workspace_git_log',
                 'get_workspace_git_diff', 'get_workspace_git_commit',
                 'compare_workspace_git_revisions', 'read_workspace_file_at_revision',
                 'get_workspace_file_history')
        surface = registry['surfaces']['workspace_git']
        approved = {row['name'] for row in surface['tools'] if row.get('approval') == 'automatic'}
        if (surface.get('status') != 'dashboard' or approved != contract.tools or
                workspace_root is None or not workspace_root.is_dir() or
                not WORKSPACE_GIT_SERVER.is_file()):
            raise ValueError('workspace Git tools or selected root are unavailable')
    else:
        surface = registry['surfaces']['google_workspace']
        approved = {row['name'] for row in surface['tools'] if row.get('approval') == 'automatic'}
        if (surface.get('status') != 'dashboard' or not approved
                or not approved <= contract.tools or not GOOGLE_SERVER.is_file()):
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
                 'read_workspace_document_chunk', 'search_workspace_text')
        args = [str(WORKSPACE_SERVER), '--root', str(workspace_root)]
    elif tool_profile == 'workspace_git':
        server_name = 'workspace_git'
        names = ('get_workspace_git_status', 'get_workspace_git_log',
                 'get_workspace_git_diff', 'get_workspace_git_commit',
                 'compare_workspace_git_revisions', 'read_workspace_file_at_revision',
                 'get_workspace_file_history')
        args = [str(WORKSPACE_GIT_SERVER), '--root', str(workspace_root)]
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


@guard_child_run
def run_child(*, parent_id: str, agent_type: str, prompt: str, out: Path, gateway: str,
              max_tokens: int = 1536, timeout_s: int = 300,
              max_tool_calls: int = 12,
              candidate_id: str | None = None, tool_profile: str = 'none',
              workspace_root: Path | None = None, min_context: int = 4096,
              context_tokens: int | None = None, worker_strategy: str = 'auto') -> dict:
    if max_tokens < 1 or max_tokens > 4096 or timeout_s < 1 or timeout_s > 600:
        raise ValueError('child budget outside allowed bounds')
    if type(max_tool_calls) is not int or not 1 <= max_tool_calls <= 12:
        raise ValueError('max_tool_calls must be between 1 and 12')
    if type(min_context) is not int or not 1 <= min_context <= 262144:
        raise ValueError('minimum context must be between 1 and 262144 tokens')
    if context_tokens is not None and (type(context_tokens) is not int
            or not 16384 <= context_tokens <= 262144 or context_tokens < min_context):
        raise ValueError('requested context must be 16384..262144 and meet the minimum')
    if worker_strategy not in ('auto', 'shared_model', 'separate_model'):
        raise ValueError('unknown worker strategy')
    if tool_profile not in ('none', 'public_research', 'workspace_read', 'workspace_git', 'google_workspace'):
        raise ValueError('unknown child tool profile')
    if tool_profile in ('workspace_read', 'workspace_git'):
        if workspace_root is None:
            raise ValueError(f'{tool_profile} profile requires a selected root')
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
        _child_tools(agent, out, tool_profile, workspace_root)
        tool_bridge = None
        if tool_profile != 'none':
            server_name, server_config = next(iter(json.loads((agent / 'mcp.json').read_text())['mcpServers'].items()))
            tool_bridge = {'name': server_name,
                           'command': [server_config['command'], *server_config['args']],
                           'tools': list(server_config['toolExposure'])}
            tool_bridge['definitions'] = discover_tools(tool_bridge)
        project = run_project_agent(
            gateway=gateway, route=child['route'], expected_model=child['model'],
            prompt=prompt, agent_type=agent_type, tool_profile=tool_profile,
            tool_server=tool_bridge, workspace_root=workspace_root,
            max_tokens=max_tokens, timeout_s=timeout_s,
            max_tool_calls=max_tool_calls,
            cancel_path=out.with_suffix('.cancel'), journal_root=out / 'journal')
        (out / 'project_agent.json').write_text(json.dumps(project, indent=2) + '\n')
        answer, error = project['answer'], project['error']
        if malformed_child_output(answer):
            error = 'shared model produced malformed repetitive output'
        exit_code = 0 if answer and not error else 1
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
                   'engine': project['engine'], 'engine_version': project['engine_version'],
                   'run': project.get('run'),
                   'task_contract_version': project.get('task_contract_version', 1),
                   'limits': project.get('limits'),
                   'tool_mode': 'project_agent' if tool_profile != 'none' else 'none',
                   'tool_calls': project['tool_calls'],
                   'tool_call_summary': project['tool_call_summary'],
                   'file_evidence_coverage': project.get('file_evidence_coverage', []),
                   'tool_budget': project['tool_budget'],
                   'tool_batch_limit': project['tool_batch_limit'],
                   'model_steps': project['model_steps'],
                   'max_model_steps': project['max_model_steps'],
                   'tool_format_repair_attempted': project['tool_format_repair_attempted'],
                   'truncation_repair_attempted': project.get('truncation_repair_attempted', False),
                   'max_tokens': max_tokens, 'timeout_s': timeout_s,
                   'duration_s': project['duration_s'], 'exit_code': exit_code,
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
    parser.add_argument('--max-tool-calls', type=int, default=12)
    parser.add_argument('--tool-profile', choices=['none', 'public_research', 'workspace_read', 'workspace_git'], default='none')
    parser.add_argument('--workspace-root', type=Path)
    parser.add_argument('--min-context', type=int, default=4096)
    parser.add_argument('--worker-strategy', choices=['auto', 'shared_model', 'separate_model'], default='auto')
    parser.add_argument('prompt')
    args = parser.parse_args()
    result = run_child(parent_id=args.parent_route, agent_type=args.agent_type,
                       prompt=args.prompt, out=args.out, gateway=args.gateway,
                       max_tokens=args.max_tokens, timeout_s=args.timeout,
                       max_tool_calls=args.max_tool_calls,
                       candidate_id=args.candidate_id, tool_profile=args.tool_profile,
                       workspace_root=args.workspace_root, min_context=args.min_context,
                       worker_strategy=args.worker_strategy)
    print(json.dumps(result))
    return 0 if result['exit_code'] == 0 and result['roster_stable'] and result['answer'] \
        and not result.get('error') else 1


if __name__ == '__main__':
    sys.exit(main())
