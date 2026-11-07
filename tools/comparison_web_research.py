#!/usr/bin/env python3
"""Frozen two-tool search -> CPU fetch -> cited-answer harness comparison."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

import comparison_mcp_matrix as matrix
import comparison_web_search as web
import comparison_short_control as common

ROOT = common.ROOT
FIXTURE = ROOT / 'tools/fixtures/web_research_mcp.py'
QUERY = 'archive beacon cadence'
ANSWER = '37 minutes'
CANDIDATES = tuple(web.DRIVERS)

def direct_control(server, out):
    proc = subprocess.Popen(server['command'][:-1] + [str(out / 'baseline_calls.jsonl')],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, bufsize=1)
    try:
        init = matrix.request_stdio(proc, 1, 'initialize', {'protocolVersion': '2025-06-18',
            'capabilities': {}, 'clientInfo': {'name': 'web-research-control', 'version': '1'}})
        proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) + '\n')
        proc.stdin.flush()
        listed = matrix.request_stdio(proc, 2, 'tools/list')
        search = matrix.request_stdio(proc, 3, 'tools/call',
                                     {'name': 'search_web', 'arguments': {'query': QUERY}})
        results = search.get('structuredContent', {}).get('results') or []
        url = results[0].get('url') if results else ''
        fetched = matrix.request_stdio(proc, 4, 'tools/call',
                                      {'name': 'fetch_page', 'arguments': {'url': url}})
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate(); proc.wait(timeout=5)
        (out / 'baseline_stderr.log').write_text(proc.stderr.read())
    body = fetched.get('structuredContent') or {}
    checks = {'protocol': init.get('protocolVersion') == '2025-06-18',
              'two_tools': {'search_web', 'fetch_page'} <= {x['name'] for x in listed.get('tools', [])},
              'search_result': len(results) == 2 and url.startswith('http://127.0.0.1:'),
              'answer_absent_from_snippets': all(ANSWER not in x.get('snippet', '') for x in results),
              'cpu_scraper_ok': body.get('cpu_scraper_exit_code') == 0 and body.get('fetch_status') == 'ok',
              'answer_in_page': ANSWER in body.get('page_text', ''),
              'source_url_preserved': body.get('url') == url}
    return {'passed': all(checks.values()), 'checks': checks, 'source_url': url,
            'scraper_exit_code': body.get('cpu_scraper_exit_code')}

def one(candidate, run_id, baseline_only=False):
    out = ROOT / 'results' / run_id / 'research' / candidate
    out.mkdir(parents=True, exist_ok=False)
    (out / 'workspace').mkdir()
    server = {'name': 'web_research',
              'command': [sys.executable, str(FIXTURE), str(out / 'calls.jsonl')],
              'tools': ['search_web', 'fetch_page']}
    fixture_hash = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    before = matrix.candidate_roster(candidate) if not baseline_only else None
    started = time.monotonic()
    baseline = direct_control(server, out)
    (out / 'baseline.json').write_text(json.dumps(baseline, indent=2))
    if baseline_only:
        receipt = {'candidate': candidate, 'baseline_only': True, **baseline,
                   'fixture_sha256': fixture_hash,
                   'duration_seconds': round(time.monotonic() - started, 3)}
        (out / 'summary.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps(receipt), flush=True)
        return receipt
    candidate_result = None
    if baseline['passed']:
        prompt = ('Call web_research search_web exactly once with {"query":"archive beacon cadence"}. '
                  'Then call web_research fetch_page exactly once using the first returned URL. '
                  'The answer is absent from search snippets; read the fetched page text. '
                  'In answer give only the cadence value, such as a number and unit. '
                  'Return JSON only: {"answer":"...","source_url":"..."}.')
        system = ('Use only the web_research MCP tools search_web and fetch_page. '
                  'Ground the answer in fetched page text and cite the fetched URL.')
        candidate_result = web.DRIVERS[candidate](out, prompt, server=server,
                                                  target=['search_web', 'fetch_page'], system=system)
    after = matrix.candidate_roster(candidate)
    logs = web.old_drivers.read_jsonl(out / 'calls.jsonl') if (out / 'calls.jsonl').exists() else []
    calls = [x for x in logs if x.get('method') == 'tools/call']
    tool_results = [x for x in logs if x.get('method') == 'tool/result']
    search = next((x.get('data') or {} for x in tool_results if x.get('tool') == 'search_web'), {})
    fetch = next((x.get('data') or {} for x in tool_results if x.get('tool') == 'fetch_page'), {})
    search_urls = [x.get('url') for x in search.get('results', [])]
    answer_text = (candidate_result or {}).get('answer', '').strip()
    try:
        answer = json.loads(answer_text)
    except json.JSONDecodeError:
        answer = {}
    checks = {'baseline_passed': baseline['passed'], 'roster_unchanged': before == after,
              'search_once': len([x for x in calls if x.get('tool') == 'search_web']) == 1,
              'search_query_exact': any(x.get('tool') == 'search_web' and x.get('arguments') == {'query': QUERY} for x in calls),
              'fetch_once': len([x for x in calls if x.get('tool') == 'fetch_page']) == 1,
              'fetch_first_result': bool(search_urls) and any(x.get('tool') == 'fetch_page' and
                  x.get('arguments') == {'url': search_urls[0]} for x in calls),
              'no_other_tools': len(calls) == 2,
              'page_fetched': fetch.get('fetch_status') == 'ok' and ANSWER in fetch.get('page_text', ''),
              'answer_from_page': bool(re.fullmatch(r'(?:The archive beacon cadence is )?37 minutes\.?',
                                                     str(answer.get('answer', '')).strip(), re.IGNORECASE)),
              'citation_from_fetched_url': answer.get('source_url') == fetch.get('url') and fetch.get('url') in search_urls,
              'json_only': isinstance(answer, dict) and set(answer) == {'answer', 'source_url'},
              'clean_finish': (candidate_result or {}).get('exit_code') == 0 and
                  (candidate_result or {}).get('finish_reason') in ('stop', 'completed', 'process_exit_0') and
                  not (candidate_result or {}).get('errors')}
    if not baseline['passed']:
        checks = {key: value if key == 'baseline_passed' else False for key, value in checks.items()}
    receipt = {'candidate': candidate, 'passed': all(checks.values()), 'checks': checks,
               'fixture_sha256': fixture_hash, 'baseline': baseline,
               'answer': answer_text, 'search_result_count': len(search_urls),
               'fetched_url': fetch.get('url'), 'scraper_exit_code': fetch.get('cpu_scraper_exit_code'),
               'candidate_exit_code': (candidate_result or {}).get('exit_code'),
               'candidate_finish': (candidate_result or {}).get('finish_reason'),
               'duration_seconds': round(time.monotonic() - started, 3)}
    (out / 'summary.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'candidate': candidate, 'passed': receipt['passed'],
                      'failed_checks': [key for key, value in checks.items() if not value],
                      'duration_seconds': receipt['duration_seconds']}), flush=True)
    return receipt

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('candidate', choices=CANDIDATES)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--baseline-only', action='store_true')
    args = parser.parse_args()
    result = one(args.candidate, args.run_id, args.baseline_only)
    raise SystemExit(0 if result['passed'] else 1)

if __name__ == '__main__':
    main()
