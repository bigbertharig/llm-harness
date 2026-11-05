#!/usr/bin/env python3
"""One frozen parent -> managed child delegation case for six native harnesses."""

import argparse
import hashlib
import json
from pathlib import Path
import select
import subprocess
import sys
import time

import comparison_mcp_matrix as matrix
import comparison_short_control as common
import comparison_web_search as web
from subagent_contract import canonical_integer_answer, canonical_final_line

ROOT = common.ROOT
FIXTURE = ROOT / 'tools/fixtures/subagent_mcp.py'
CONTRACT = ROOT / 'tools/subagent_contract.py'
TASK = 'Solve the private arithmetic check and return the result.'
PROMPT = ('Call the subagent MCP tool delegate_task exactly once with agent_type coding and '
          'task "Solve the private arithmetic check and return the result." '
          'The tool response reveals the child question. Verify the child answer against that question, '
          'then reply with only the verified decimal answer.')
SYSTEM = ('You are a parent agent. Use only the subagent delegate_task MCP tool. '
          'Create one child, inspect its route and answer, verify the arithmetic, and reply with the number only.')
CANDIDATES = tuple(web.DRIVERS)


def read_log(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def direct_control(server, out):
    command = server['command'][:-2] + [str(out / 'baseline_children'), str(out / 'baseline_calls.jsonl')]
    proc = subprocess.Popen(command,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, bufsize=1)
    try:
        init = matrix.request_stdio(proc, 1, 'initialize', {'protocolVersion': '2025-06-18',
            'capabilities': {}, 'clientInfo': {'name': 'subagent-control', 'version': '1'}})
        proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) + '\n')
        proc.stdin.flush()
        listed = matrix.request_stdio(proc, 2, 'tools/list')
        proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
            'params': {'name': 'delegate_task', 'arguments': {'agent_type': 'coding', 'task': TASK}}}) + '\n')
        proc.stdin.flush()
        if not select.select([proc.stdout], [], [], 320)[0]:
            raise TimeoutError('managed child baseline did not return within readiness deadline')
        response = json.loads(proc.stdout.readline())
        if response.get('id') != 3:
            raise RuntimeError(f'unexpected baseline response id: {response.get("id")}')
        result = response.get('result') or {}
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=5)
        (out / 'baseline_stderr.log').write_text(proc.stderr.read())
    body = result.get('structuredContent') or {}
    checks = {'protocol': init.get('protocolVersion') == '2025-06-18',
              'tool_exposed': {x['name'] for x in listed.get('tools', [])} == {'delegate_task'},
              'no_tool_error': not result.get('isError'),
              'hidden_question_answered': body.get('question') == 'What is 7 multiplied by 6? Return only the decimal number.'
                  and body.get('child_answer') == '42',
              'disjoint_gpus': bool(body.get('parent_gpu_ids')) and bool(body.get('child_gpu_ids'))
                  and set(body['parent_gpu_ids']).isdisjoint(body['child_gpu_ids']),
              'child_clean': body.get('child_exit_code') == 0 and body.get('roster_stable') is True}
    return {'passed': all(checks.values()), 'checks': checks,
            'child_route': body.get('child_route'), 'child_answer': body.get('child_answer')}


def one(candidate, run_id, baseline_only=False):
    out = ROOT / 'results' / run_id / 'subagents' / candidate
    out.mkdir(parents=True, exist_ok=False)
    (out / 'workspace').mkdir()
    parent_route = 'gpu-rig/chat-27b' if candidate == 'hermes' else common.ROUTE
    server = {'name': 'subagent', 'command': [sys.executable, str(FIXTURE), parent_route,
              str(out / 'children'), str(out / 'calls.jsonl')],
              'tools': ['delegate_task']}
    started = time.monotonic()
    try:
        baseline = direct_control(server, out)
    except Exception as exc:
        baseline = {'passed': False, 'checks': {}, 'error': f'{type(exc).__name__}: {exc}'}
    (out / 'baseline.json').write_text(json.dumps(baseline, indent=2) + '\n')
    if baseline_only:
        receipt = {'candidate': candidate, 'baseline_only': True, **baseline}
        (out / 'summary.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps({'candidate': candidate, 'baseline_passed': baseline['passed']}), flush=True)
        return receipt
    if not baseline['passed']:
        receipt = {'candidate': candidate, 'run_id': run_id, 'passed': False,
                   'baseline': baseline, 'native_withheld': True,
                   'fixture_sha256': hashlib.sha256(FIXTURE.read_bytes() + CONTRACT.read_bytes()).hexdigest(),
                   'duration_seconds': round(time.monotonic() - started, 2)}
        (out / 'summary.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps({'candidate': candidate, 'passed': False,
                          'baseline_error': baseline.get('error', 'check failed')}), flush=True)
        return receipt
    before = matrix.candidate_roster(candidate)
    try:
        result = web.DRIVERS[candidate](out, PROMPT, server=server, target='delegate_task', system=SYSTEM)
    except Exception as exc:
        result = {'answer': '', 'exit_code': None, 'finish_reason': None,
                  'errors': [f'{type(exc).__name__}: {exc}']}
    try:
        after = matrix.candidate_roster(candidate)
    except Exception as exc:
        after = {'error': f'{type(exc).__name__}: {exc}'}
    logs = read_log(out / 'calls.jsonl')
    calls = [row for row in logs if row.get('method') == 'tools/call']
    tool_result = next((row for row in logs if row.get('method') == 'tool/result'), {})
    data = tool_result.get('data') or {}
    children = sorted((out / 'children').glob('*/summary.json')) if (out / 'children').exists() else []
    child = json.loads(children[0].read_text()) if len(children) == 1 else {}
    answer = (result.get('answer') or '').strip()
    checks = {'baseline_passed': baseline['passed'], 'roster_unchanged': before == after,
              'one_delegate_call': len(calls) == 1 and calls[0].get('tool') == 'delegate_task',
              'requested_coding': len(calls) == 1 and calls[0].get('arguments', {}).get('agent_type') == 'coding',
              'task_supplied': len(calls) == 1 and bool(calls[0].get('arguments', {}).get('task')),
              'one_child_receipt': len(children) == 1,
              'child_answer_42': canonical_integer_answer(child.get('answer', '')) == '42'
                  and data.get('child_answer') == '42',
              'disjoint_gpus': bool(child.get('parent_gpu_ids')) and bool(child.get('child_gpu_ids'))
                  and set(child['parent_gpu_ids']).isdisjoint(child['child_gpu_ids']),
              'child_clean': child.get('exit_code') == 0 and child.get('roster_stable') is True
                  and not tool_result.get('isError'),
              'parent_verified_answer': canonical_final_line(answer) == '42',
              'parent_clean': result.get('exit_code') == 0 and not result.get('errors')
                  and result.get('finish_reason') in ('stop', 'completed', 'process_exit_0')}
    receipt = {'candidate': candidate, 'run_id': run_id, 'passed': all(checks.values()),
               'checks': checks, 'fixture_sha256': hashlib.sha256(FIXTURE.read_bytes() + CONTRACT.read_bytes()).hexdigest(),
               'baseline': baseline, 'parent_route': parent_route, 'child_route': child.get('child_route'),
               'parent_answer': answer, 'parent_finish': result.get('finish_reason'),
               'parent_format_exact': canonical_integer_answer(answer) == '42',
               'parent_exit_code': result.get('exit_code'), 'parent_errors': result.get('errors'),
               'tool_mode': result.get('tool_mode', 'native' if calls else 'none'),
               'bridge_calls': result.get('bridge_calls', []),
               'child_receipts': [str(path) for path in children],
               'duration_seconds': round(time.monotonic() - started, 2)}
    (out / 'summary.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'candidate': candidate, 'passed': receipt['passed'],
                      'failed_checks': [key for key, value in checks.items() if not value],
                      'duration_seconds': receipt['duration_seconds']}), flush=True)
    return receipt


def aggregate(run_id):
    root = ROOT / 'results' / run_id / 'subagents'
    receipts = {candidate: json.loads((root / candidate / 'summary.json').read_text())
                for candidate in CANDIDATES if (root / candidate / 'summary.json').exists()}
    missing = sorted(set(CANDIDATES) - set(receipts))
    hashes = {row.get('fixture_sha256') for row in receipts.values()}
    result = {'run_id': run_id, 'suite_passed': not missing and len(hashes) == 1 and
              all(row.get('passed') and row.get('baseline', {}).get('passed') for row in receipts.values()),
              'missing_candidates': missing,
              'fixture_sha256': next(iter(hashes)) if len(hashes) == 1 else None,
              'candidates': {name: {'passed': row.get('passed', False),
                  'baseline_passed': row.get('baseline', {}).get('passed', False),
                  'parent_route': row.get('parent_route'), 'child_route': row.get('child_route'),
                  'parent_format_exact': row.get('parent_format_exact'),
                  'failed_checks': [key for key, ok in row.get('checks', {}).items() if not ok],
                  'duration_seconds': row.get('duration_seconds')}
                  for name, row in receipts.items()}}
    (root / 'matrix.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'suite_passed': result['suite_passed'],
                      'candidate_passes': sum(bool(row.get('passed')) for row in receipts.values()),
                      'fixture_sha256': result['fixture_sha256']}), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate', choices=(*CANDIDATES, 'summary'))
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--baseline-only', action='store_true')
    args = parser.parse_args()
    result = aggregate(args.run_id) if args.candidate == 'summary' else one(args.candidate, args.run_id, args.baseline_only)
    raise SystemExit(0 if result.get('suite_passed', result.get('passed')) else 1)


if __name__ == '__main__':
    main()
