#!/usr/bin/env python3
"""Project-owned bounded model/tool loop for one already-ready Gateway route."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from child_policy import (MAX_FINALIZATION_STEPS, MAX_MODEL_STEPS, MAX_TOOL_BATCH_CALLS, MAX_TOOL_ERRORS,
                          ToolBudget, validate_request)
from harness_core import (DocumentDriverError, MCPResultError, RunRecorder, admit_evidence,
                          MAX_PROVIDER_RETRIES, ProviderFailure, cancellable_backoff,
                          decide_provider_retry,
                          decide_terminal, get_tool_profile, next_document_request,
                          normalize_mcp_result, prepare_evidence, render_evidence)
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
    body = {'model': route, 'messages': messages, 'max_tokens': max_tokens}
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
        raw_retry_after = exc.headers.get('Retry-After') if exc.headers else None
        try:
            retry_after = float(raw_retry_after) if raw_retry_after is not None else None
        except (TypeError, ValueError):
            retry_after = None
        raise ProviderFailure(str(exc.code),
                              f'Gateway completion failed ({exc.code}): {detail[:1000]}',
                              exc.code in {429, 500, 502, 503}, retry_after) from exc
    except (URLError, TimeoutError) as exc:
        raise ProviderFailure('transport', f'Gateway completion transport failed: {exc}',
                              True) from exc
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
    return (f' TOOL PHASE CONTRACT: Prefer native function calls and request at most '
            f'{MAX_TOOL_BATCH_CALLS} independent native tools in one turn. If native calls are unavailable, '
            'the entire response must be one complete JSON object shaped as '
            '{"name":"ALLOWED_NAME","arguments":{...}}. Do not use Markdown, XML, prose, or a '
            'second JSON object in that fallback response. Allowed names: ' +
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
              conversation_id: str | None = None,
              cancel_path: Path | None = None,
              evidence_blocks: list[dict] | None = None,
              journal_root: Path | None = None,
              retry_wait=time.sleep,
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
    profile_contract = get_tool_profile(tool_profile) if tool_profile != 'none' else None
    if profile_contract and set(tool_server['tools']) - profile_contract.tools:
        raise ValueError('tool server exceeds the selected profile')
    if profile_contract and profile_contract.requires_workspace:
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
    external_messages, external_provenance = prepare_evidence(evidence_blocks)
    messages = [{'role': 'system', 'content': system},
                {'role': 'user', 'content': child_task_envelope(prompt)},
                *external_messages]
    recorder = RunRecorder(journal_root, conversation_id=conversation_id)
    recorder.emit('run.started', payload={'engine': 'big-bertha-project-agent'})
    budget = ToolBudget(max_tool_calls)
    attempted: set[str] = set()
    tool_calls: list[dict] = []
    steps: list[dict] = []
    model_calls: list[dict] = []
    repair_attempted = False
    truncation_repair_attempted = False
    tool_errors = 0
    tools_enabled = bool(tool_server)
    answer = ''
    error = None
    started = time.monotonic()
    # A requested tool budget must also be reachable across sequential model
    # turns. Keep the hard ceiling, then reserve two tool-free terminal turns:
    # one normal synthesis and one bounded truncation repair.
    max_tool_steps = min(max_tool_calls, MAX_MODEL_STEPS) if tool_server else 1
    max_model_steps = max_tool_steps + MAX_FINALIZATION_STEPS
    max_model_attempts = max_model_steps + MAX_PROVIDER_RETRIES
    provider_retries = 0

    def digest_request(name: str, arguments: dict) -> str:
        normalized = json.dumps({'name': name, 'arguments': arguments}, sort_keys=True,
                                separators=(',', ':')).encode('utf-8')
        return hashlib.sha256(normalized).hexdigest()

    def apply_terminal_policy(step_number: int, finish_reason: str | None) -> str:
        nonlocal error, tools_enabled, truncation_repair_attempted
        decision = decide_terminal(answer=answer, finish_reason=finish_reason,
                                   repair_attempted=truncation_repair_attempted,
                                   can_repair=step_number < max_model_steps)
        if decision.action == "repair":
            recorder.emit('retry.scheduled', payload={'reason': decision.reason})
            recorder.emit('retry.started', payload={})
            truncation_repair_attempted = True
            tools_enabled = False
            target_chars = max(200, min(2000, max_tokens * 2))
            messages.append({'role': 'assistant', 'content': answer})
            messages.append({'role': 'user', 'content':
                f'FINAL FORMAT REPAIR: The prior answer was truncated. Rewrite the complete '
                f'answer in at most {target_chars} characters. Keep only the result, essential '
                'evidence, actual verification, and limitations. Do not request tools.'})
        elif decision.action == "fail":
            error = decision.reason
        return decision.action

    for step_number in range(1, max_model_attempts + 1):
        if cancel_path and cancel_path.exists():
            error = 'cancelled'
            break
        remaining = timeout_s - (time.monotonic() - started)
        if remaining <= 0:
            error = 'timeout'
            break
        model_step_id = f'model-{step_number}'
        recorder.emit('model.started', model_step_id=model_step_id,
                      payload={'route': route})
        model_started = time.monotonic()
        try:
            completion_args = (gateway, route, messages, max_tokens, remaining,
                               os.environ.get('LLM_GATEWAY_API_KEY'),
                               advertised_tools if tools_enabled else [])
            packet = complete(*completion_args)
        except Exception as exc:
            failure = {'attempt': step_number, 'finish_reason': 'provider_error',
                       'answer_bytes': 0, 'usage': {}, 'requested_route': route,
                       'served_model': None,
                       'served_provider': None,
                       'provider_request_id': None,
                       'latency_ms': max(0, round((time.monotonic() - model_started) * 1000)),
                       'error_code': str(getattr(exc, 'code', type(exc).__name__)),
                       'retryable': getattr(exc, 'retryable', False) is True}
            model_calls.append(failure)
            recorder.emit('model.failed', model_step_id=model_step_id,
                          payload={'finish_reason': 'provider_error',
                                   'error_code': failure['error_code']})
            remaining_after = timeout_s - (time.monotonic() - started)
            decision = decide_provider_retry(exc, provider_retries, remaining_after)
            if decision.action == 'retry':
                recorder.emit('retry.scheduled', payload={
                    'reason': decision.reason, 'delay_s': decision.delay_s})
                continued = cancellable_backoff(
                    decision.delay_s,
                    lambda: bool(cancel_path and cancel_path.exists()), retry_wait)
                if not continued:
                    error = 'cancelled'
                    break
                recorder.emit('retry.started', payload={'attempt': provider_retries + 1})
                provider_retries += 1
                continue
            if decision.action == 'exhaust':
                recorder.emit('retry.exhausted', payload={'reason': decision.reason})
            error = ('timeout' if decision.action == 'timeout'
                     else f'{type(exc).__name__}: {exc}')
            break
        answer = _message_text(packet).strip()
        choice = packet['choices'][0]
        usage = packet.get('usage') if isinstance(packet.get('usage'), dict) else {}
        logical_step = len(steps) + 1
        step = {'step': logical_step, 'attempt': step_number,
                'finish_reason': choice.get('finish_reason'),
                'answer_bytes': len(answer.encode('utf-8')), 'usage': usage,
                'requested_route': route,
                'served_model': packet.get('model') or expected_model,
                'served_provider': packet.get('provider') or ready.get('provider'),
                'provider_request_id': packet.get('id'),
                'latency_ms': max(0, round((time.monotonic() - model_started) * 1000))}
        steps.append(step)
        model_calls.append(step)

        if not tool_server or not tools_enabled:
            model_event = ('model.truncated' if choice.get('finish_reason') == 'length'
                           else 'model.completed')
            recorder.emit(model_event, model_step_id=model_step_id,
                          payload={'finish_reason': choice.get('finish_reason')})
            if apply_terminal_policy(logical_step, choice.get('finish_reason')) == 'repair':
                continue
            break

        try:
            native_requests = _native_requests(packet, tool_server)
        except AgentLoopError as exc:
            error = str(exc)
            recorder.emit('model.failed', model_step_id=model_step_id,
                          payload={'finish_reason': 'invalid_tool_request'})
            break
        requests = [(name, arguments) for name, arguments, _ident in native_requests]
        if not requests:
            requests = parse_requests(answer, tool_server, tool_server['tools'],
                                      max_calls=MAX_TOOL_BATCH_CALLS)
        native_ids = {(name, json.dumps(arguments, sort_keys=True)): ident
                      for name, arguments, ident in native_requests}
        canonical_finish = 'tool_calls' if requests else choice.get('finish_reason')
        model_event = ('model.truncated' if not requests and canonical_finish == 'length'
                       else 'model.completed')
        recorder.emit(model_event, model_step_id=model_step_id,
                      payload={'finish_reason': canonical_finish})
        pending = []
        for name, arguments in requests:
            fingerprint = json.dumps((name, arguments), sort_keys=True)
            if fingerprint not in attempted:
                pending.append((name, arguments, fingerprint,
                                native_ids.get((name, json.dumps(arguments, sort_keys=True)))))
        if requests and not pending:
            for request_index, (name, arguments) in enumerate(requests, 1):
                call_id = (native_ids.get((name, json.dumps(arguments, sort_keys=True)))
                           or f'tool-{step_number}-{request_index}')
                recorder.emit('tool.proposed', tool_call_id=call_id,
                              payload={'name': name,
                                       'argument_digest': digest_request(name, arguments)})
                recorder.emit('tool.failed', tool_call_id=call_id,
                              payload={'reason': 'duplicate request'})
            if any(not row['is_error'] for row in tool_calls) and logical_step < max_model_steps:
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
                if apply_terminal_policy(logical_step, choice.get('finish_reason')) == 'repair':
                    continue
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
        post_delivery_error = None
        for request_index, (name, arguments, fingerprint, delivery_id) in enumerate(pending, 1):
            attempted.add(fingerprint)
            candidate_id = delivery_id
            call_id = (candidate_id if candidate_id and not any(
                row.identifier == candidate_id for row in recorder.state.tools)
                else f'tool-{step_number}-{request_index}')
            argument_digest = digest_request(name, arguments)
            recorder.emit('tool.proposed', tool_call_id=call_id,
                          payload={'name': name, 'argument_digest': argument_digest})
            try:
                budget.before_call()
                validate_request(tool_profile, name, arguments, workspace_root)
                recorder.emit('tool.validated', tool_call_id=call_id, payload={})
                recorder.emit('tool.approved', tool_call_id=call_id,
                              approval_id=f'profile-{tool_profile}',
                              payload={'grant': tool_profile})
            except Exception as exc:
                error = f'tool call failed: {type(exc).__name__}: {exc}'
                recorder.emit('tool.failed', tool_call_id=call_id,
                              payload={'reason': type(exc).__name__})
                break
            recorder.emit('tool.executing', tool_call_id=call_id, payload={})
            try:
                result = call_tool(tool_server, name, arguments,
                                   timeout=min(45, max(1, remaining - 5)))
            except Exception as exc:
                error = f'tool call failed: {type(exc).__name__}: {exc}'
                recorder.emit('tool.uncertain', tool_call_id=call_id,
                              payload={'reason': type(exc).__name__})
                break
            receipt_ref = f'mcp:{tool_server["name"]}:{call_id}'
            recorder.emit('tool.committed', tool_call_id=call_id,
                          payload={'argument_digest': argument_digest,
                                   'receipt_ref': receipt_ref})
            try:
                normalized = normalize_mcp_result(result)
                evidence = normalized.evidence
                driver_evidence = normalized.driver_evidence
                result_shape = normalized.shape
                is_error = normalized.is_error
            except MCPResultError as exc:
                evidence = driver_evidence = {
                    'harness_error': 'tool returned an invalid MCP result',
                    'detail': str(exc)}
                result_shape = 'invalid'
                is_error = True
            artifact_ref = recorder.persist_result(call_id, evidence)
            recorder.emit('tool.result_persisted', tool_call_id=call_id,
                          payload={'artifact_ref': artifact_ref})
            try:
                # MCP commonly mirrors structuredContent as serialized text in
                # content. Charge the normalized evidence delivered to the model
                # once, rather than charging both transport representations.
                budget.record(evidence)
            except Exception as exc:
                is_error = True
                evidence = {'harness_error': 'tool result exceeded the evidence budget',
                            'detail': f'{type(exc).__name__}: {exc}'}
            tool_calls.append({'tool': name, 'arguments': arguments, 'is_error': is_error,
                               'result_shape': result_shape,
                               'evidence': _evidence_metadata(name, driver_evidence)})
            admitted = admit_evidence({'source': profile_contract.evidence_source,
                                       'origin': f'{tool_server["name"]}/{name}/{call_id}',
                                       'content': evidence})
            tool_calls[-1]['provenance'] = admitted.metadata()
            evidence_batch.append({'tool': name, 'arguments': arguments, 'result': evidence,
                                   '_call_id': call_id, '_delivery_id': delivery_id,
                                   '_rendered': render_evidence(admitted)})
            if is_error:
                tool_errors += 1
                break
            try:
                followup = next_document_request(name, arguments, driver_evidence,
                                                 budget.calls, budget.max_calls)
            except DocumentDriverError as exc:
                post_delivery_error = str(exc)
                break
            if followup is not None:
                followup_fingerprint = json.dumps((name, followup), sort_keys=True)
                if followup_fingerprint in attempted:
                    post_delivery_error = 'complete-document driver made no cursor progress'
                    break
                pending.append((name, followup, followup_fingerprint, delivery_id))
            if budget.calls >= budget.max_calls:
                break
        step['tool_calls'] = len(evidence_batch)
        if error:
            break
        if native_requests:
            messages.append(packet['choices'][0]['message'])
        else:
            messages.append({'role': 'assistant', 'content': answer})
        if evidence_batch[-1]['result'] and tool_calls[-1]['is_error']:
            feedback = ('The tool rejected the request. Correct only that request if essential; '
                        'otherwise report the limitation. Tool result:\n' +
                        evidence_batch[-1]['_rendered'][:4000])
        else:
            feedback = ('Validated tool results:\n' +
                        '\n'.join(row['_rendered'] for row in evidence_batch)[:160000] +
                        '\nAnswer the original task now if this is sufficient. Request only essential '
                        'additional evidence and never repeat a completed call.')
        budget_exhausted = budget.calls >= budget.max_calls
        finalization = ('TOOL BUDGET EXHAUSTED: Do not request another tool. Use the evidence already '
                        'returned and produce the final answer now. If it is insufficient, state the '
                        'specific limitation instead of requesting more evidence.')
        finalization_grace = ('FINALIZATION STEP: The bounded tool phase is complete. Do not request '
                              'another tool. Answer the original task now from the evidence already '
                              'returned, and state any remaining limitation explicitly.')
        if native_requests:
            # Shared Gateway routes currently normalize exactly one proposal;
            # general routes may return a bounded batch. Preserve each call ID.
            delivery_groups = {}
            for row in evidence_batch:
                delivery_groups.setdefault(row['_delivery_id'] or row['_call_id'], []).append(row)
            for ident, rows in delivery_groups.items():
                messages.append({'role': 'tool', 'tool_call_id': ident,
                                 'content': '\n'.join(row['_rendered'] for row in rows)[:160000]})
            for row in evidence_batch:
                recorder.emit('tool.result_delivered', tool_call_id=row['_call_id'], payload={})
            if budget_exhausted or logical_step >= max_tool_steps:
                messages.append({'role': 'user', 'content':
                                 finalization if budget_exhausted else finalization_grace})
        else:
            if budget_exhausted or logical_step >= max_tool_steps:
                feedback += '\n' + (finalization if budget_exhausted else finalization_grace)
            messages.append({'role': 'user', 'content': feedback})
            for row in evidence_batch:
                recorder.emit('tool.result_delivered', tool_call_id=row['_call_id'], payload={})
        if tool_errors >= MAX_TOOL_ERRORS:
            error = 'tool error limit reached'
            break
        if post_delivery_error:
            error = post_delivery_error
            break
        if budget_exhausted or logical_step >= max_tool_steps:
            tools_enabled = False
    else:
        error = 'model step limit reached'

    if tool_server and not error and not any(not row['is_error'] for row in tool_calls):
        error = 'model did not execute an allowed tool'
    if recorder.state.phase == 'running':
        if error == 'cancelled':
            recorder.emit('run.cancelled', payload={'reason': error})
        elif error == 'timeout':
            recorder.emit('run.timed_out', payload={'reason': error})
        elif error:
            recorder.emit('run.failed', payload={'reason': error})
        else:
            recorder.emit('run.succeeded', payload={'reason': 'completed'})
    duration = round(time.monotonic() - started, 2)
    return {'engine': 'big-bertha-project-agent', 'engine_version': 2,
            'task_contract_version': CONTRACT_VERSION,
            'route': route, 'model': expected_model, 'tool_profile': tool_profile,
            'generation_settings_source': 'runtime_profile',
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
                'model_tool_steps_max': max_tool_steps,
                'model_finalization_steps_max': MAX_FINALIZATION_STEPS,
                'model_steps_max': max_model_steps,
                'model_attempts_max': max_model_attempts,
                'provider_retries_max': MAX_PROVIDER_RETRIES,
                'provider_retries_used': provider_retries,
                'tool_calls_max': budget.max_calls,
                'tool_batch_compatibility_max': MAX_TOOL_BATCH_CALLS,
                'tool_result_bytes_max': budget.receipt()['max_result_bytes'],
                'tool_total_bytes_max': budget.receipt()['max_total_bytes'],
                'mcp_response_line_characters_max': MAX_MCP_LINE_CHARS,
                'task_timeout_seconds': timeout_s,
            },
            'answer': answer, 'error': error, 'duration_s': duration,
            'run': recorder.receipt(), 'evidence_provenance': external_provenance,
            'model_steps': len(steps), 'model_attempts': len(model_calls),
            'max_model_steps': max_model_steps,
            'model_call_receipts': model_calls,
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
                        cancel_path=args.out.with_suffix('.cancel'),
                        journal_root=args.out.parent / (args.out.stem + '-journal'))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))
    return 0 if receipt['answer'] and not receipt['error'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
