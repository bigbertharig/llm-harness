#!/usr/bin/env python3
"""Ready-only native MCP tool-use comparison with a recorded local fixture."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import select
import shutil
import subprocess
import threading
import time

import comparison_short_control as common

FIXTURE = common.ROOT / 'tools/fixtures/diagnostics_mcp.mjs'
CONFIGS = common.ROOT / 'tools/comparison_fixtures'
SYSTEM = ('Use only the named local fixture MCP tool. Do not use shell, file, web, '
          'or editing tools. Return only the exact marker from the tool result.')
CASES = {
    'text': ('read_marker', 'Call the local fixture MCP tool read_marker exactly once. Return only its marker.'),
    'structured': ('read_structured_marker',
                   'Call the local fixture MCP tool read_structured_marker exactly once. Return only the marker from its structured result.'),
}


def read_jsonl(path):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return rows


def direct_baseline(out):
    receipt = out / 'baseline_calls.jsonl'
    proc = subprocess.Popen([str(common.NODE), str(FIXTURE), 'marker', str(receipt)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, bufsize=1)
    transcript = []
    try:
        def request(index, method, params=None):
            message = {'jsonrpc': '2.0', 'id': index, 'method': method}
            if params is not None:
                message['params'] = params
            proc.stdin.write(json.dumps(message) + '\n')
            proc.stdin.flush()
            if not select.select([proc.stdout], [], [], 8)[0]:
                raise TimeoutError(f'direct MCP fixture timed out on {method}')
            reply = json.loads(proc.stdout.readline())
            transcript.append({'request': message, 'reply': reply})
            if reply.get('id') != index:
                raise RuntimeError('MCP baseline response ID mismatch')
            return reply.get('result')
        init = request(1, 'initialize', {'protocolVersion': '2025-06-18',
                                        'capabilities': {}, 'clientInfo': {'name': 'harness-test', 'version': '1'}})
        proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) + '\n')
        proc.stdin.flush()
        listed = request(2, 'tools/list')
        text_result = request(3, 'tools/call', {'name': 'read_marker', 'arguments': {}})
        structured_result = request(4, 'tools/call', {'name': 'read_structured_marker', 'arguments': {}})
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=5)
    (out / 'baseline.json').write_text(json.dumps(transcript, indent=2))
    calls = read_jsonl(receipt)
    names = {tool['name'] for tool in listed['tools']}
    valid = (init.get('protocolVersion') == '2025-06-18' and
             names == {'read_marker', 'read_structured_marker'} and
             len([x for x in calls if x.get('method') == 'tools/call']) == 2 and
             bool(text_result.get('content')) and bool(text_result.get('structuredContent')) and
             structured_result.get('content') == [] and bool(structured_result.get('structuredContent')))
    if not valid:
        raise RuntimeError('direct MCP fixture contract failed')
    return {'passed': True, 'tools': sorted(names), 'responses': 4}








from candidate_controllers.pi import run_pi
from candidate_controllers.deepseek import run_deepseek
from candidate_controllers.opencode import run_opencode

def score(out, case, candidate_result, before, after):
    target, _ = CASES[case]
    calls = read_jsonl(out / 'calls.jsonl')
    invoked = [x for x in calls if x.get('method') == 'tools/call']
    results = [x for x in calls if x.get('method') == 'tool/result']
    marker = results[0].get('marker') if len(results) == 1 else None
    event_names = []
    for event in candidate_result.get('tool_events', []):
        part = event.get('part') if isinstance(event.get('part'), dict) else {}
        name = event.get('toolName') or event.get('tool') or event.get('name') or part.get('tool') or part.get('name')
        if name:
            event_names.append(str(name))
    other_names = [name for name in event_names if not (name == target or name.endswith('__' + target)
                                                       or name == 'fixture_' + target)]
    checks = {
        'ready_roster_unchanged': before == after,
        'mcp_initialized': any(x.get('method') == 'initialize' for x in calls),
        'tools_discovered': any(x.get('method') == 'tools/list' for x in calls),
        'one_named_call': len(invoked) == 1 and invoked[0].get('tool') == target,
        'one_result': len(results) == 1 and results[0].get('tool') == target,
        'no_other_named_tools': not other_names,
        'answer_matches_result': bool(marker) and candidate_result['answer'].strip() == marker,
        'natural_finish': candidate_result['finish_reason'] in ('stop', 'completed', 'process_exit_0'),
        'candidate_exited_cleanly': candidate_result['exit_code'] == 0 and not candidate_result['errors'],
    }
    (out / 'calls_summary.json').write_text(json.dumps(calls, indent=2))
    return {'passed': all(checks.values()), 'checks': checks, 'marker': marker,
            'called_tools': [x.get('tool') for x in invoked],
            'candidate_tool_event_names': event_names, 'other_tool_event_names': other_names}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('candidate', choices=['baseline', 'pi', 'opencode', 'deepseek'])
    parser.add_argument('case', choices=sorted(CASES))
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    out = common.ROOT / 'results' / args.run_id / args.candidate / args.case
    out.mkdir(parents=True, exist_ok=False)
    (out / 'workspace').mkdir()
    target, prompt = CASES[args.case]
    fixture = {'version': 'local-mcp-tool-v1', 'case': args.case, 'tool': target,
               'prompt': prompt, 'system': SYSTEM, 'route': common.ROUTE,
               'model': common.MODEL, 'context': common.CONTEXT, 'output_cap': common.OUTPUT_CAP}
    (out / 'fixture.json').write_text(json.dumps(fixture, indent=2))
    if args.candidate == 'baseline':
        baseline = direct_baseline(out)
        (out / 'summary.json').write_text(json.dumps({'candidate': 'baseline',
            'run_id': args.run_id, 'fixture_sha256': hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
            'baseline': baseline}, indent=2))
        print('SUMMARY ' + json.dumps(baseline), flush=True)
        return
    before = common.roster()
    (out / 'ready_before.json').write_text(json.dumps(before, indent=2))
    started = time.time()
    result, error = None, None
    try:
        baseline = direct_baseline(out)
        result = {'pi': run_pi, 'opencode': run_opencode, 'deepseek': run_deepseek}[args.candidate](out, prompt)
    except Exception as exc:
        baseline = None
        error = f'{type(exc).__name__}: {exc}'
    try:
        after = common.roster()
    except Exception as exc:
        after = None
        error = (error + '; ' if error else '') + f'post-roster {type(exc).__name__}: {exc}'
    (out / 'ready_after.json').write_text(json.dumps(after, indent=2))
    verdict = score(out, args.case, result, before, after) if result else {'passed': False, 'reason': 'no candidate result'}
    if error:
        verdict['passed'] = False
    summary = {'candidate': args.candidate, 'case': args.case, 'run_id': args.run_id,
               'fixture_sha256': hashlib.sha256(json.dumps(fixture, sort_keys=True).encode()).hexdigest(),
               'server_sha256': hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
               'driver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'baseline': baseline, 'candidate_result': result, 'error': error, 'verdict': verdict,
               'duration_seconds': round(time.time()-started, 2)}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2))
    print('SUMMARY ' + json.dumps({k: v for k, v in summary.items() if k != 'candidate_result'}), flush=True)
    raise SystemExit(0 if verdict['passed'] else 1)


if __name__ == '__main__':
    main()
