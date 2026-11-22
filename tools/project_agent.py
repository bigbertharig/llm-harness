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
from child_public_tools import MAX_MCP_LINE_CHARS
from ready_roster import fetch_ready_roster
from subagent_contract import CONTRACT_VERSION, child_system_prompt, child_task_envelope
from workspace_read_mcp import TOOLS as WORKSPACE_TOOL_DEFINITIONS
from workspace_git_mcp import TOOLS as WORKSPACE_GIT_TOOL_DEFINITIONS


WORKSPACE_TOOLS = ('list_workspace_files', 'find_workspace_files',
                   'read_workspace_file', 'read_workspace_document_chunk',
                   'search_workspace_text')
WORKSPACE_GIT_TOOLS = ('get_workspace_git_status', 'get_workspace_git_log',
                       'get_workspace_git_diff', 'get_workspace_git_commit',
                       'compare_workspace_git_revisions',
                       'read_workspace_file_at_revision', 'get_workspace_file_history')
ROOT = Path(__file__).resolve().parents[1]
MAX_AGENT_OUTPUT_TOKENS = 4096
MAX_AGENT_TIMEOUT_SECONDS = 600


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


def _tool_instruction(server: dict, max_tool_calls: int) -> str:
    names = ['mcp__' + server['name'] + '__' + name for name in server['tools']]
    return (' TOOL PHASE CONTRACT: Request exactly one tool per turn. The entire response must be '
            'one complete JSON object shaped as {"name":"ALLOWED_NAME","arguments":{...}}. '
            'Do not use Markdown, XML, prose, or a second JSON object in that response. Allowed names: ' +
            json.dumps(names) + f'. The entire assignment permits at most {max_tool_calls} tool call(s). '
            'Never repeat a completed call, invent a tool result, or continue '
            'reading after enough evidence exists. FINAL PHASE CONTRACT: after sufficient results arrive, '
            'answer the assignment in prose and emit no tool request.')


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


def _evidence_metadata(tool: str, evidence) -> dict:
    """Keep bounded provenance fields without duplicating model-visible result content."""
    if not isinstance(evidence, dict):
        return {}
    common = ('path', 'start_line', 'end_line', 'requested_range_complete',
              'more_lines_after', 'truncated', 'files_scanned',
              'snapshot_sha256', 'total_bytes', 'total_characters',
              'cursor_start', 'cursor_end', 'next_cursor', 'complete')
    metadata = {key: evidence[key] for key in common if key in evidence}
    if tool in ('find_workspace_files', 'search_workspace_text'):
        matches = evidence.get('matches')
        if isinstance(matches, list):
            metadata['match_count'] = len(matches)
    return metadata


def _file_evidence_coverage(tool_calls: list[dict]) -> list[dict]:
    """Summarize contiguous line coverage; do not trust model claims of full reads."""
    grouped: dict[str, list[dict]] = {}
    for row in tool_calls:
        if row.get('tool') != 'read_workspace_file' or row.get('is_error'):
            continue
        evidence = row.get('evidence') or {}
        if isinstance(evidence.get('path'), str):
            grouped.setdefault(evidence['path'], []).append(evidence)
    summaries = []
    for path, rows in sorted(grouped.items()):
        cursor = 1
        reached_eof = False
        for row in sorted(rows, key=lambda item: (item.get('start_line', 1), item.get('end_line', 0))):
            start, end = row.get('start_line'), row.get('end_line')
            if type(start) is not int or type(end) is not int or start > cursor:
                continue
            # A character-truncated final line is not fully covered. A later
            # read beginning on that line can complete it.
            covered_end = end if row.get('requested_range_complete') else end - 1
            cursor = max(cursor, covered_end + 1)
            if row.get('requested_range_complete') and row.get('more_lines_after') is False:
                reached_eof = cursor > end
        summaries.append({'path': path, 'start_line': 1, 'through_line': max(0, cursor - 1),
                          'complete_file': reached_eof, 'calls': len(rows)})
    return summaries


def _document_evidence_coverage(tool_calls: list[dict]) -> list[dict]:
    """Prove contiguous character coverage for one immutable document snapshot."""
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in tool_calls:
        if row.get('tool') != 'read_workspace_document_chunk' or row.get('is_error'):
            continue
        evidence = row.get('evidence') or {}
        path, snapshot = evidence.get('path'), evidence.get('snapshot_sha256')
        if isinstance(path, str) and isinstance(snapshot, str):
            grouped.setdefault((path, snapshot), []).append(evidence)
    summaries = []
    for (path, snapshot), rows in sorted(grouped.items()):
        cursor = 0
        total = None
        for row in sorted(rows, key=lambda item: (item.get('cursor_start', 0),
                                                   item.get('cursor_end', 0))):
            if type(row.get('total_characters')) is int:
                total = row['total_characters']
            start, end = row.get('cursor_start'), row.get('cursor_end')
            if type(start) is not int or type(end) is not int or start > cursor or end < start:
                continue
            cursor = max(cursor, end)
        summaries.append({'path': path, 'snapshot_sha256': snapshot,
                          'through_character': cursor, 'total_characters': total,
                          'complete_document': total is not None and cursor == total,
                          'calls': len(rows)})
    return summaries


def run_agent(*, gateway: str, route: str, expected_model: str, prompt: str,
              agent_type: str, tool_profile: str = 'none', tool_server: dict | None = None,
              workspace_root: Path | None = None, max_tokens: int = 1024,
              timeout_s: int = 180, max_tool_calls: int = 12,
              cancel_path: Path | None = None,
              complete=_completion) -> dict:
    """Run a bounded direct loop and return a model-neutral execution receipt."""
    if type(max_tokens) is not int or not 1 <= max_tokens <= MAX_AGENT_OUTPUT_TOKENS:
        raise ValueError(f'max_tokens must be between 1 and {MAX_AGENT_OUTPUT_TOKENS}')
    if type(timeout_s) is not int or not 1 <= timeout_s <= MAX_AGENT_TIMEOUT_SECONDS:
        raise ValueError(f'timeout_s must be between 1 and {MAX_AGENT_TIMEOUT_SECONDS}')
    if type(max_tool_calls) is not int or not 1 <= max_tool_calls <= 12:
        raise ValueError('max_tool_calls must be between 1 and 12')
    if tool_profile == 'none':
        if tool_server is not None:
            raise ValueError('tool-free run cannot have a tool server')
    elif not isinstance(tool_server, dict) or not tool_server.get('tools'):
        raise ValueError('tool profile requires an allowlisted tool server')
    if tool_profile in ('workspace_read', 'workspace_git'):
        if workspace_root is None:
            raise ValueError(f'{tool_profile} requires a workspace root')
        workspace_root = workspace_root.resolve(strict=True)

    roster = fetch_ready_roster(gateway, os.environ.get('LLM_GATEWAY_API_KEY'))
    ready = next((row for row in roster['data'] if row['id'] == route), None)
    if ready is None or ready['model'] != expected_model:
        raise ValueError('requested route/model is not in the ready roster')
    requested_max_tokens = max_tokens
    output_limit = ready.get('output_limit')
    if isinstance(output_limit, int) and output_limit > 0:
        max_tokens = min(max_tokens, output_limit)

    system = child_system_prompt(agent_type, tool_profile)
    if tool_server:
        system += _tool_instruction(tool_server, max_tool_calls)
    advertised_tools = _openai_tools(tool_server)
    messages = [{'role': 'system', 'content': system},
                {'role': 'user', 'content': child_task_envelope(prompt)}]
    budget = ToolBudget(max_tool_calls)
    attempted: set[str] = set()
    tool_calls: list[dict] = []
    steps: list[dict] = []
    repair_attempted = False
    truncation_repair_attempted = False
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
            elif choice.get('finish_reason') == 'length':
                if not truncation_repair_attempted and step_number < MAX_MODEL_STEPS:
                    truncation_repair_attempted = True
                    target_chars = max(200, min(2000, max_tokens * 2))
                    messages.append({'role': 'assistant', 'content': answer})
                    messages.append({'role': 'user', 'content':
                        f'FINAL FORMAT REPAIR: The prior answer was truncated. Rewrite the complete '
                        f'answer in at most {target_chars} characters. Keep only the result, essential '
                        'evidence, actual verification, and limitations. Do not request tools.'})
                    continue
                error = 'model final answer hit the output-token limit'
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
                'TOOL FORMAT REPAIR: Return exactly one complete allowed JSON tool request now. '
                'The entire response must be that single JSON object: no Markdown, XML, prose, or '
                'second request. Do not invent a result.'})
            continue

        evidence_batch = []
        for name, arguments, fingerprint in pending:
            attempted.add(fingerprint)
            try:
                budget.before_call()
                validate_request(tool_profile, name, arguments, workspace_root)
                result = call_tool(tool_server, name, arguments,
                                   timeout=min(45, max(1, remaining - 5)))
                evidence = result.get('structuredContent') or result.get('content') or result
                # MCP commonly mirrors structuredContent as serialized text in
                # content. Charge the normalized evidence delivered to the model
                # once, rather than charging both transport representations.
                budget.record(evidence)
            except Exception as exc:
                error = f'tool call failed: {type(exc).__name__}: {exc}'
                break
            is_error = bool(result.get('isError'))
            tool_calls.append({'tool': name, 'arguments': arguments, 'is_error': is_error,
                               'evidence': _evidence_metadata(name, evidence)})
            evidence_batch.append({'tool': name, 'arguments': arguments, 'result': evidence})
            if is_error:
                tool_errors += 1
                break
            if budget.calls >= budget.max_calls:
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
        budget_exhausted = budget.calls >= budget.max_calls
        finalization = ('TOOL BUDGET EXHAUSTED: Do not request another tool. Use the evidence already '
                        'returned and produce the final answer now. If it is insufficient, state the '
                        'specific limitation instead of requesting more evidence.')
        if native_requests:
            # Shared Gateway routes currently normalize exactly one proposal;
            # general routes may return a bounded batch. Preserve each call ID.
            for row in evidence_batch:
                ident = native_ids[(row['tool'], json.dumps(row['arguments'], sort_keys=True))]
                messages.append({'role': 'tool', 'tool_call_id': ident,
                                 'content': json.dumps(row['result'], ensure_ascii=False)[:24000]})
            if budget_exhausted:
                messages.append({'role': 'user', 'content': finalization})
        else:
            if budget_exhausted:
                feedback += '\n' + finalization
            messages.append({'role': 'user', 'content': feedback})
        if budget_exhausted or step_number >= MAX_MODEL_STEPS - 1:
            tools_enabled = False
    else:
        error = 'model step limit reached'

    if tool_server and not error and not any(not row['is_error'] for row in tool_calls):
        error = 'model did not execute an allowed tool'
    duration = round(time.monotonic() - started, 2)
    return {'engine': 'big-bertha-project-agent', 'engine_version': 1,
            'task_contract_version': CONTRACT_VERSION,
            'route': route, 'model': expected_model, 'tool_profile': tool_profile,
            'limits': {
                'route_context_tokens': ready.get('context_length'),
                'route_output_tokens': output_limit,
                'requested_output_tokens': requested_max_tokens,
                'effective_output_tokens': max_tokens,
                'task_characters': len(prompt),
                'task_bytes': len(prompt.encode('utf-8')),
                'system_prompt_bytes': len(system.encode('utf-8')),
                'user_envelope_bytes': len(messages[1]['content'].encode('utf-8')),
                'output_limit_hit': any(row.get('finish_reason') == 'length' for row in steps),
                'model_steps_max': MAX_MODEL_STEPS,
                'tool_calls_max': budget.max_calls,
                'tool_batch_compatibility_max': MAX_TOOL_BATCH_CALLS,
                'tool_result_bytes_max': budget.receipt()['max_result_bytes'],
                'tool_total_bytes_max': budget.receipt()['max_total_bytes'],
                'mcp_response_line_characters_max': MAX_MCP_LINE_CHARS,
                'task_timeout_seconds': timeout_s,
            },
            'answer': answer, 'error': error, 'duration_s': duration,
            'model_steps': len(steps), 'max_model_steps': MAX_MODEL_STEPS,
            'steps': steps, 'tool_calls': len(tool_calls),
            'tool_call_summary': tool_calls, 'tool_budget': budget.receipt(),
            'file_evidence_coverage': _file_evidence_coverage(tool_calls),
            'document_evidence_coverage': _document_evidence_coverage(tool_calls),
            'tool_batch_limit': MAX_TOOL_BATCH_CALLS,
            'tool_format_repair_attempted': repair_attempted,
            'truncation_repair_attempted': truncation_repair_attempted}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gateway', default='http://127.0.0.1:8080')
    parser.add_argument('--route', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--agent-type', choices=['coding', 'research'], required=True)
    parser.add_argument('--tool-profile', choices=['none', 'workspace_read', 'workspace_git'], default='none')
    parser.add_argument('--workspace-root', type=Path)
    parser.add_argument('--max-tokens', type=int, default=1024)
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--max-tool-calls', type=int, default=12)
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
    elif args.tool_profile == 'workspace_git':
        if args.workspace_root is None:
            parser.error('--workspace-root is required for workspace_git')
        server = {'name': 'workspace_git', 'tools': list(WORKSPACE_GIT_TOOLS),
                  'definitions': WORKSPACE_GIT_TOOL_DEFINITIONS,
                  'command': [os.fspath(Path(os.sys.executable)),
                              os.fspath(ROOT / 'tools/workspace_git_mcp.py'),
                              '--root', os.fspath(args.workspace_root.resolve(strict=True))]}
    receipt = run_agent(gateway=args.gateway, route=args.route, expected_model=args.model,
                        prompt=args.prompt, agent_type=args.agent_type,
                        tool_profile=args.tool_profile, tool_server=server,
                        workspace_root=args.workspace_root, max_tokens=args.max_tokens,
                        timeout_s=args.timeout, max_tool_calls=args.max_tool_calls,
                        cancel_path=args.out.with_suffix('.cancel'))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))
    return 0 if receipt['answer'] and not receipt['error'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
