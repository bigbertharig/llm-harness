#!/usr/bin/env python3
"""Four live search questions: direct MCP gate, then native harness call quality."""

import argparse
import json
import os
from pathlib import Path
import re
import select
import subprocess
import sys
import time
from urllib.parse import urlparse

import comparison_mcp_matrix as matrix
import comparison_short_control as common
import comparison_tool_use as old_drivers
import comparison_extra_candidates as extra_drivers
from candidate_controllers.hermes import run_hermes
from search_provider_benchmark import QUERIES


SERVERS = {'rig_search': common.ROOT / 'mcp_servers/rig_search/mcp_server.py'}
DRIVERS = {'pi': old_drivers.run_pi, 'deepseek': old_drivers.run_deepseek,
           'opencode': old_drivers.run_opencode, 'codex': extra_drivers.run_codex,
           'nanobot': extra_drivers.run_nanobot, 'hermes': run_hermes}


def expected_domain_rank(urls, domains):
    for index, url in enumerate(urls):
        host = (urlparse(url).hostname or '').lower()
        if any(host == domain or host.endswith('.' + domain) for domain in domains):
            return index + 1
    return None


def result_root(run_id, backend):
    base = common.ROOT / 'results' / run_id
    return base / backend


def search_server(backend, receipt):
    command = [sys.executable, str(SERVERS[backend]), str(receipt),
               '--env-file', os.environ.get('RIG_SEARCH_ENV_FILE', str(common.ROOT / '.env')),
               '--providers', os.environ.get('RIG_SEARCH_COMPARE_PROVIDERS', 'searxng')]
    return {'name': 'web_search', 'command': command,
            'tools': ['search_web']}


def baseline_passes(direct, case):
    data = direct.get('structuredContent') or {}
    urls = data.get('unique_urls') or [x.get('url') for x in data.get('results', []) if isinstance(x, dict)]
    return (not direct.get('isError') and len(set(urls)) >= 5 and
            expected_domain_rank(urls, case['domains']) in range(1, 6) and
            not data.get('rate_limit_signal'))


def direct_baseline(server, args, out):
    command = list(server['command'])
    command[2] = str(out / 'baseline_calls.jsonl')
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, bufsize=1)
    def request(index, method, params=None):
        packet = {'jsonrpc': '2.0', 'id': index, 'method': method}
        if params is not None:
            packet['params'] = params
        proc.stdin.write(json.dumps(packet) + '\n'); proc.stdin.flush()
        if not select.select([proc.stdout], [], [], 40)[0]:
            raise TimeoutError(method + ' direct MCP timeout')
        reply = json.loads(proc.stdout.readline())
        if reply.get('id') != index or 'result' not in reply:
            raise RuntimeError('bad direct MCP response: ' + str(reply)[:200])
        return reply['result']
    try:
        init = request(1, 'initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                         'clientInfo': {'name': 'web-search-control', 'version': '1'}})
        proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) + '\n'); proc.stdin.flush()
        tools = request(2, 'tools/list')
        result = request(3, 'tools/call', {'name': 'search_web', 'arguments': args})
    finally:
        proc.stdin.close()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.terminate(); proc.wait(timeout=5)
        proc.stdout.close()
        proc.stderr.close()
    if init.get('protocolVersion') != '2025-06-18' or 'search_web' not in [x.get('name') for x in tools.get('tools', [])]:
        raise RuntimeError('direct search MCP discovery failed')
    return result


def run_case(candidate, case, run_id, backend='rig_search'):
    out = result_root(run_id, backend) / candidate / case['id']
    out.mkdir(parents=True, exist_ok=False)
    (out / 'workspace').mkdir()
    args = {'query': case['query'], 'max_results': 10}
    server = search_server(backend, out / 'calls.jsonl')
    prompt = (f'Call the web_search MCP search_web tool exactly once with arguments {json.dumps(args)}. '
              f'From the returned results, choose one URL on {case["domains"][0]} in the first five results. '
              'Return JSON only: {"url":"...","unique_url_count":N}, where N is the count of distinct returned URLs. '
              'Do not use outside search or files.')
    (out / 'fixture.json').write_text(json.dumps({'candidate': candidate, 'backend': backend, 'case': case,
        'arguments': args, 'prompt': prompt, 'route': common.route_spec(candidate)[0],
        'model': common.route_spec(candidate)[1],
        'context': common.route_spec(candidate)[2]}, indent=2))
    before = matrix.candidate_roster(candidate)
    (out / 'ready_before.json').write_text(json.dumps(before, indent=2))
    started = time.monotonic()
    direct = None; candidate_result = None; error = None; baseline_log = None
    try:
        direct = direct_baseline(server, args, out)
        path = out / 'baseline_calls.jsonl'
        baseline_log = path.read_bytes(); path.unlink()
        if baseline_passes(direct, case):
            system = ('Use only the named MCP search tool. Do not use shell, file, or another web tool. '
                      'Call search_web once and ground your answer in its returned URLs.')
            candidate_result = DRIVERS[candidate](out, prompt, server=server, target='search_web', system=system)
        else:
            error = 'direct baseline failed its relevance, URL-yield, or rate-limit gate'
    except Exception as exc:
        error = type(exc).__name__ + ': ' + str(exc)
    if direct is not None:
        (out / 'baseline.json').write_text(json.dumps(direct, indent=2))
    if baseline_log is not None:
        (out / 'baseline_calls.jsonl').write_bytes(baseline_log)
    after = matrix.candidate_roster(candidate)
    (out / 'ready_after.json').write_text(json.dumps(after, indent=2))
    actual = old_drivers.read_jsonl(out / 'calls.jsonl')
    calls = [x for x in actual if x.get('method') == 'tools/call']
    results = [x for x in actual if x.get('method') == 'tool/result']
    actual_result = results[-1] if results else {}
    urls = actual_result.get('urls') or []
    rank = expected_domain_rank(urls, case['domains'])
    answer = (candidate_result or {}).get('answer', '').strip()
    answer_body = re.sub(r'^```(?:json)?\s*|\s*```$', '', answer, flags=re.IGNORECASE).strip()
    try:
        answer_json = json.loads(answer_body)
    except json.JSONDecodeError:
        answer_json = {}
    answer_url = answer_json.get('url') if isinstance(answer_json, dict) else None
    answer_count = answer_json.get('unique_url_count') if isinstance(answer_json, dict) else None
    chosen_rank = urls.index(answer_url) + 1 if answer_url in urls else None
    checks = {
        'direct_baseline': direct is not None and error is None,
        'roster_unchanged': before == after,
        'one_exact_search_call': len(calls) == 1 and calls[0].get('tool') == 'search_web' and calls[0].get('arguments') == args,
        'one_nonempty_result': len(results) == 1 and bool(urls) and not actual_result.get('error'),
        'search_result_relevant_top_5': rank is not None and rank <= 5,
        'answer_url_from_top_5': chosen_rank is not None and chosen_rank <= 5 and
                                   expected_domain_rank([answer_url], case['domains']) == 1,
        'answer_unique_count': answer_count == len(urls),
        'json_payload_present': isinstance(answer_json, dict) and 'url' in answer_json and 'unique_url_count' in answer_json,
        'no_rate_limit_signal': not actual_result.get('rate_limit_signal', False),
        'natural_finish': (candidate_result or {}).get('finish_reason') in ('stop', 'completed', 'process_exit_0'),
        'clean_exit': (candidate_result or {}).get('exit_code') == 0 and not (candidate_result or {}).get('errors'),
    }
    harness_behavior_checks = ('direct_baseline', 'roster_unchanged', 'one_exact_search_call',
                               'one_nonempty_result', 'search_result_relevant_top_5',
                               'answer_url_from_top_5', 'answer_unique_count',
                               'json_payload_present', 'natural_finish', 'clean_exit')
    summary = {'candidate_name': candidate, 'backend': backend, 'case': case['id'],
               'passed': all(checks.values()),
               'harness_behavior_passed': (all(checks[name] for name in harness_behavior_checks)
                                           if candidate_result is not None else None),
               'backend_healthy': checks['direct_baseline'] and checks['no_rate_limit_signal']
                                  and not actual_result.get('degraded', False),
               'checks': checks, 'error': error, 'baseline': {'url_count': len((direct or {}).get('structuredContent', {}).get('unique_urls', [])),
               'expected_domain_rank': expected_domain_rank((direct or {}).get('structuredContent', {}).get('unique_urls', []), case['domains']),
               'backend_latency_seconds': (direct or {}).get('structuredContent', {}).get('backend_latency_seconds')},
               'metrics': {'answer': answer, 'format_exact_json': answer_body == answer,
                             'answer_url': answer_url, 'answer_count': answer_count,
                             'url_count': len(urls), 'expected_domain_rank': rank,
                             'backend_latency_seconds': actual_result.get('backend_latency_seconds'),
                             'rate_limit_signal': actual_result.get('rate_limit_signal'),
                             'duration_seconds': (candidate_result or {}).get('duration_seconds')},
               'total_seconds': round(time.monotonic()-started, 3)}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('candidate', choices=sorted(DRIVERS))
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--case', choices=[x['id'] for x in QUERIES])
    parser.add_argument('--backend', choices=sorted(SERVERS), default='rig_search')
    args = parser.parse_args()
    if args.backend == 'rig_search' and not Path(os.environ.get(
            'RIG_SEARCH_ENV_FILE', str(common.ROOT / '.env'))).is_file():
        parser.error('rig_search requires a private env file')
    cases = [x for x in QUERIES if args.case in (None, x['id'])]
    rows = []
    for case in cases:
        row = run_case(args.candidate, case, args.run_id, backend=args.backend)
        rows.append(row)
        print(json.dumps({'backend': args.backend, 'case': case['id'], 'passed': row['passed'],
                          'harness_behavior_passed': row['harness_behavior_passed'],
                          'backend_healthy': row['backend_healthy'],
                          'failed_checks': [k for k,v in row['checks'].items() if not v],
                          'backend_latency_seconds': row['metrics'].get('backend_latency_seconds'),
                          'candidate_seconds': row['metrics'].get('duration_seconds'),
                          'url_count': row['metrics'].get('url_count'), 'error': row['error']}), flush=True)
    out = result_root(args.run_id, args.backend) / args.candidate / 'batch_summary.json'
    summary = {'candidate': args.candidate, 'backend': args.backend, 'cases': len(rows), 'passed': sum(x['passed'] for x in rows),
               'harness_behavior_passed': sum(x['harness_behavior_passed'] is True for x in rows),
               'harness_not_run': sum(x['harness_behavior_passed'] is None for x in rows),
               'backend_healthy': sum(x['backend_healthy'] for x in rows),
               'direct_baselines_passed': sum(x['checks']['direct_baseline'] for x in rows),
               'total_backend_rate_limit_signals': sum(bool(x['metrics'].get('rate_limit_signal')) for x in rows)}
    out.write_text(json.dumps(summary, indent=2))
    print('SUMMARY ' + json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
