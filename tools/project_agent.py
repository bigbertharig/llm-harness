#!/usr/bin/env python3
"""Project-owned bounded model/tool loop for one already-ready Gateway route."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from child_policy import (MAX_MODEL_STEPS, MAX_TOOL_BATCH_CALLS, MAX_TOOL_ERRORS,
                          ToolBudget, validate_request)
from child_public_tools import call_tool, parse_requests
from ready_roster import fetch_ready_roster
from subagent_contract import child_system_prompt
from workspace_read_mcp import TOOLS as WORKSPACE_TOOL_DEFINITIONS


WORKSPACE_TOOLS = ('list_workspace_files', 'find_workspace_files',
                   'read_workspace_file', 'search_workspace_text')
ROOT = Path(__file__).resolve().parents[1]


class AgentLoopError(RuntimeError):
    """A bounded agent contract failed."""


def _completion(gateway: str, route: str, messages: list[dict], max_tokens: int,
                timeout: float, api_key: str | None = None,
                tools: list[dict] | None = None) -> dict:
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json',
               'X-Require-Ready': 'true'}
    if api_key:
        headers['Authorization'] = 'Bearer ' + api_key
    body = {'model': route, 'messages': messages, 'max_tokens': max_tokens,
            'temperature': 0}
    if tools:
        body['tools'] = tools
    body = json.dumps(body).encode()
    request = Request(gateway.rstrip('/') + '/v1/chat/completions', data=body,
                      headers=headers, method='POST')
    try:
        with urlopen(request, timeout=max(1, timeout)) as response:
            packet = json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')
        raise AgentLoopError(f'Gateway completion failed ({exc.code}): {detail[:1000]}') from exc
    choices = packet.get('choices') if isinstance(packet, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise AgentLoopError('Gateway completion returned no choice')
    return packet


def _message_text(packet: dict) -> str:
    content = packet['choices'][0].get('message', {}).get('content')
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ''.join(row.get('text', '') for row in content if isinstance(row, dict))
    return ''


def _tool_instruction(server: dict) -> str:
    names = ['mcp__' + server['name'] + '__' + name for name in server['tools']]
    return (' When tool evidence is needed, respond with only one JSON object shaped as '
            '{"name":"ALLOWED_NAME","arguments":{...}}. Allowed names: ' +
            json.dumps(names) + '. You may request at most ' + str(MAX_TOOL_BATCH_CALLS) +
            ' independent calls in a leading XML batch. Never repeat a completed call, invent a '
            'tool result, or continue reading after enough evidence exists. After results arrive, '
            'answer the original task instead of replaying the tool plan.')


def _openai_tools(server: dict | None) -> list[dict]:
    if not server:
        return []
    allowed = set(server['tools'])
    definitions = server.get('definitions') or []
    by_name = {row.get('name'): row for row in definitions if isinstance(row, dict)}
    if set(by_name) != allowed:
        raise ValueError('tool definitions must exactly match the tool allowlist')
    return [{'type': 'function', 'function': {
        'name': 'mcp__' + server['name'] + '__' + name,
        'description': by_name[name].get('description', ''),
        'parameters': by_name[name].get('inputSchema', {'type': 'object'}),
    }} for name in server['tools']]


def _native_requests(packet: dict, server: dict) -> list[tuple[str, dict, str]]:
    message = packet['choices'][0].get('message') or {}
    rows = message.get('tool_calls') or []
    if not isinstance(rows, list):
        return []
    allowed = {'mcp__' + server['name'] + '__' + name: name for name in server['tools']}
    requests = []
    for row in rows[:MAX_TOOL_BATCH_CALLS]:
        function = row.get('function') if isinstance(row, dict) else None
        if not isinstance(function, dict) or function.get('name') not in allowed:
            raise AgentLoopError('model requested a tool outside the allowlist')
        try:
            arguments = json.loads(function.get('arguments') or '{}')
        except ValueError as exc:
            raise AgentLoopError('model returned invalid native tool arguments') from exc
        if not isinstance(arguments, dict):
            raise AgentLoopError('model returned non-object native tool arguments')
        ident = row.get('id')
        if not isinstance(ident, str) or not ident:
            raise AgentLoopError('model returned a native tool call without an ID')
        requests.append((allowed[function['name']], arguments, ident))
    return requests


def run_agent(*, gateway: str, route: str, expected_model: str, prompt: str,
              agent_type: str, tool_profile: str = 'none', tool_server: dict | None = None,
              workspace_root: Path | None = None, max_tokens: int = 1024,
              timeout_s: int = 180, cancel_path: Path | None = None,
              complete=_completion) -> dict:
    """Run a bounded direct loop and return a model-neutral execution receipt."""
    if type(max_tokens) is not int or not 1 <= max_tokens <= 4096:
        raise ValueError('max_tokens must be between 1 and 4096')
    if type(timeout_s) is not int or not 1 <= timeout_s <= 600:
        raise ValueError('timeout_s must be between 1 and 600')
    if tool_profile == 'none':
        if tool_server is not None:
            raise ValueError('tool-free run cannot have a tool server')
    elif not isinstance(tool_server, dict) or not tool_server.get('tools'):
        raise ValueError('tool profile requires an allowlisted tool server')
    if tool_profile == 'workspace_read':
        if workspace_root is None:
            raise ValueError('workspace_read requires a workspace root')
        workspace_root = workspace_root.resolve(strict=True)

    roster = fetch_ready_roster(gateway, os.environ.get('LLM_GATEWAY_API_KEY'))
    ready = next((row for row in roster['data'] if row['id'] == route), None)
    if ready is None or ready['model'] != expected_model:
        raise ValueError('requested route/model is not in the ready roster')
    output_limit = ready.get('output_limit')
    if isinstance(output_limit, int) and output_limit > 0:
        max_tokens = min(max_tokens, output_limit)

    system = child_system_prompt(agent_type, tool_profile)
    if tool_server:
        system += _tool_instruction(tool_server)
    advertised_tools = _openai_tools(tool_server)
    messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}]
    budget = ToolBudget()
    attempted: set[str] = set()
    tool_calls: list[dict] = []
    steps: list[dict] = []
    repair_attempted = False
    tool_errors = 0
    tools_enabled = bool(tool_server)
    answer = ''
    error = None
    started = time.monotonic()

    for step_number in range(1, MAX_MODEL_STEPS + 1):
        if cancel_path and cancel_path.exists():
            error = 'cancelled'
            break
        remaining = timeout_s - (time.monotonic() - started)
        if remaining <= 0:
            error = 'timeout'
            break
        try:
            packet = complete(gateway, route, messages, max_tokens, remaining,
                              os.environ.get('LLM_GATEWAY_API_KEY'),
                              advertised_tools if tools_enabled else [])
        except Exception as exc:
            error = f'{type(exc).__name__}: {exc}'
            break
        answer = _message_text(packet).strip()
        choice = packet['choices'][0]
        usage = packet.get('usage') if isinstance(packet.get('usage'), dict) else {}
        step = {'step': step_number, 'finish_reason': choice.get('finish_reason'),
                'answer_bytes': len(answer.encode('utf-8')), 'usage': usage}
        steps.append(step)

        if not tool_server or not tools_enabled:
            if not answer:
                error = 'model returned an empty answer'
            break

        try:
            native_requests = _native_requests(packet, tool_server)
        except AgentLoopError as exc:
            error = str(exc)
            break
        requests = [(name, arguments) for name, arguments, _ident in native_requests]
        if not requests:
            requests = parse_requests(answer, tool_server, tool_server['tools'],
                                      max_calls=MAX_TOOL_BATCH_CALLS)
        native_ids = {(name, json.dumps(arguments, sort_keys=True)): ident
                      for name, arguments, ident in native_requests}
        pending = []
        for name, arguments in requests:
            fingerprint = json.dumps((name, arguments), sort_keys=True)
            if fingerprint not in attempted:
                pending.append((name, arguments, fingerprint))
        if requests and not pending:
            if any(not row['is_error'] for row in tool_calls) and step_number < MAX_MODEL_STEPS:
                tools_enabled = False
                messages.append(packet['choices'][0]['message'] if native_requests else
                                {'role': 'assistant', 'content': answer})
                messages.append({'role': 'user', 'content':
                    'That tool request was already completed. No more tools are available. '
                    'Answer the original task now using only the evidence already returned.'})
                continue
            error = 'model repeated completed tool calls'
            break
        if not pending:
            if any(not row['is_error'] for row in tool_calls):
                if not answer:
                    error = 'model returned no final answer after tool evidence'
                break
            if repair_attempted:
                error = 'model did not execute an allowed tool'
                break
            repair_attempted = True
            messages.append({'role': 'assistant', 'content': answer})
            messages.append({'role': 'user', 'content':
                'No allowed tool call ran. Return exactly one allowed JSON tool request now. '
                'Do not explain it and do not invent a result.'})
            continue

        evidence_batch = []
        for name, arguments, fingerprint in pending:
            attempted.add(fingerprint)
            try:
                budget.before_call()
                validate_request(tool_profile, name, arguments, workspace_root)
                result = call_tool(tool_server, name, arguments,
                                   timeout=min(45, max(1, remaining - 5)))
                budget.record(result)
            except Exception as exc:
                error = f'tool call failed: {type(exc).__name__}: {exc}'
                break
            is_error = bool(result.get('isError'))
            tool_calls.append({'tool': name, 'arguments': arguments, 'is_error': is_error})
            evidence = result.get('structuredContent') or result.get('content') or result
            evidence_batch.append({'tool': name, 'arguments': arguments, 'result': evidence})
            if is_error:
                tool_errors += 1
                break
        step['tool_calls'] = len(evidence_batch)
        if error:
            break
        if tool_errors >= MAX_TOOL_ERRORS:
            error = 'tool error limit reached'
            break
        if native_requests:
            messages.append(packet['choices'][0]['message'])
        else:
            messages.append({'role': 'assistant', 'content': answer})
        if evidence_batch[-1]['result'] and tool_calls[-1]['is_error']:
            feedback = ('The tool rejected the request. Correct only that request if essential; '
                        'otherwise report the limitation. Tool result:\n' +
                        json.dumps(evidence_batch[-1], ensure_ascii=False)[:4000])
        else:
            feedback = ('Validated tool results:\n' +
                        json.dumps(evidence_batch, ensure_ascii=False)[:24000] +
                        '\nAnswer the original task now if this is sufficient. Request only essential '
                        'additional evidence and never repeat a completed call.')
        if native_requests:
            # Shared Gateway routes currently normalize exactly one proposal;
            # general routes may return a bounded batch. Preserve each call ID.
            for row in evidence_batch:
                ident = native_ids[(row['tool'], json.dumps(row['arguments'], sort_keys=True))]
                messages.append({'role': 'tool', 'tool_call_id': ident,
                                 'content': json.dumps(row['result'], ensure_ascii=False)[:24000]})
        else:
            messages.append({'role': 'user', 'content': feedback})
        if step_number >= MAX_MODEL_STEPS - 1:
            tools_enabled = False
    else:
        error = 'model step limit reached'

    if tool_server and not error and not any(not row['is_error'] for row in tool_calls):
        error = 'model did not execute an allowed tool'
    duration = round(time.monotonic() - started, 2)
    return {'engine': 'big-bertha-project-agent', 'engine_version': 1,
            'route': route, 'model': expected_model, 'tool_profile': tool_profile,
            'answer': answer, 'error': error, 'duration_s': duration,
            'model_steps': len(steps), 'max_model_steps': MAX_MODEL_STEPS,
            'steps': steps, 'tool_calls': len(tool_calls),
            'tool_call_summary': tool_calls, 'tool_budget': budget.receipt(),
            'tool_batch_limit': MAX_TOOL_BATCH_CALLS,
            'tool_format_repair_attempted': repair_attempted}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gateway', default='http://127.0.0.1:8080')
    parser.add_argument('--route', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--agent-type', choices=['coding', 'research'], required=True)
    parser.add_argument('--tool-profile', choices=['none', 'workspace_read'], default='none')
    parser.add_argument('--workspace-root', type=Path)
    parser.add_argument('--max-tokens', type=int, default=1024)
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('prompt')
    args = parser.parse_args()
    server = None
    if args.tool_profile == 'workspace_read':
        if args.workspace_root is None:
            parser.error('--workspace-root is required for workspace_read')
        server = {'name': 'workspace_read', 'tools': list(WORKSPACE_TOOLS),
                  'definitions': WORKSPACE_TOOL_DEFINITIONS,
                  'command': [os.fspath(Path(os.sys.executable)),
                              os.fspath(ROOT / 'tools/workspace_read_mcp.py'),
                              '--root', os.fspath(args.workspace_root.resolve(strict=True))]}
    receipt = run_agent(gateway=args.gateway, route=args.route, expected_model=args.model,
                        prompt=args.prompt, agent_type=args.agent_type,
                        tool_profile=args.tool_profile, tool_server=server,
                        workspace_root=args.workspace_root, max_tokens=args.max_tokens,
                        timeout_s=args.timeout, cancel_path=args.out.with_suffix('.cancel'))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))
    return 0 if receipt['answer'] and not receipt['error'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
