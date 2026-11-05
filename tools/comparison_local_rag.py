#!/usr/bin/env python3
"""Frozen local Chroma MCP comparison across six isolated harness controllers."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import quote
from urllib.request import urlopen

import comparison_mcp_matrix as matrix
import comparison_short_control as common
from comparison_web_search import DRIVERS
from mcp_call_guard import guarded_mcp

ROOT = common.ROOT
CORPUS = ROOT / 'results/local_rag_fixture/rag_corpus_v1.json'
SERVICE = 'http://127.0.0.1:17021'
CASES = {
    'batch_heater': {
        'question': 'Why must simple batch solar water heaters be drained during winter in cold climates?',
        'expected_id': 'builditsolar:d9d0c8106c91d87010956c2c613d40a8',
        'fact_patterns': [r'freez'], 'source': None},
    'water_wheel': {
        'question': 'What stopped the undershoot water wheel from performing well?',
        'expected_id': 'builditsolar:06d54b7b338a3c91a617d31f72b37f4e',
        'fact_patterns': [r'stream', r'froze|frozen|freez'], 'source': None},
    'annular_eclipse': {
        'question': 'Why does the Moon fail to cover the Sun completely in an annular solar eclipse?',
        'expected_id': 'wiki_top_100:a43a2fafe35604dcbac8bc1fe906c394',
        'fact_patterns': [r'moon', r'far away|far from|distance|distant'], 'source': None},
    'filtered_total_eclipse': {
        'question': 'Search only wiki_top_100: what covers the Sun during a total solar eclipse?',
        'expected_id': 'wiki_top_100:a43a2fafe35604dcbac8bc1fe906c394',
        'fact_patterns': [r'moon'], 'source': 'wiki_top_100'},
}


def service_calls(run_key):
    with urlopen(SERVICE + '/calls?run=' + quote(run_key), timeout=10) as response:
        return json.load(response)['calls']


def one(candidate, case_id, run_id):
    case = CASES[case_id]
    out = ROOT / 'results' / run_id / 'local_rag' / candidate / case_id
    out.mkdir(parents=True, exist_ok=False)
    (out / 'workspace').mkdir()
    corpus = json.loads(CORPUS.read_text(encoding='utf-8'))
    corpus_sha = corpus['corpus_sha256']
    baseline_key = f'{run_id}-{candidate}-{case_id}-baseline'
    candidate_key = f'{run_id}-{candidate}-{case_id}-candidate'
    server = {'name': 'local_rag', 'url': SERVICE + '/mcp?run=' + quote(candidate_key),
              'tools': ['search_passages']}
    baseline_server = {**server, 'url': SERVICE + '/mcp?run=' + quote(baseline_key)}
    baseline_args = {'query': case['question'], 'limit': 3}
    if case['source']:
        baseline_args['source'] = case['source']
    prompt = ('Use the local_rag MCP search_passages tool to find evidence for this question: '
              + case['question'] + ' Answer in one line: short factual answer | exact passage ID '
              'returned by the tool. Cite only a retrieved passage. Do not use outside knowledge.')
    system = ('Use only the local_rag MCP search_passages tool. Search the local corpus, '
              'inspect the returned passage, and ground your final answer in it. '
              'If the user names a source, pass that source filter in the tool call.')
    fixture = {'version': 'local-rag-v3', 'case': case_id, 'question': case['question'],
               'source_filter': case['source'], 'expected_id': case['expected_id'],
               'corpus_sha256': corpus_sha, 'embedding_model': corpus['embedding_model'],
               'max_search_calls': 4, 'fact_patterns': case['fact_patterns'],
               'prompt': prompt, 'system': system}
    fixture_sha = hashlib.sha256(json.dumps(fixture, sort_keys=True).encode()).hexdigest()
    started = time.monotonic()
    baseline, result, before, after, error = None, None, None, None, None
    budget = None
    baseline_ok = False
    try:
        baseline = matrix.direct_online(baseline_server, 'search_passages', baseline_args)
        data = baseline['result'].get('structuredContent') or {}
        ids = [x.get('id') for x in data.get('results', [])]
        baseline_ok = (baseline['protocol'] == '2025-06-18' and
                       'search_passages' in baseline['tools'] and
                       not baseline['result'].get('isError') and
                       ids and ids[0] == case['expected_id'] and
                       data.get('corpus_sha256') == corpus_sha and
                       (not case['source'] or all(x.get('source') == case['source']
                                                   for x in data.get('results', []))))
        if baseline_ok and candidate != 'baseline':
            before = matrix.candidate_roster(candidate)
            with guarded_mcp(server['url']) as (guard_url, budget):
                result = DRIVERS[candidate](out, prompt,
                                            server={**server, 'url': guard_url},
                                            target='search_passages', system=system)
            after = matrix.candidate_roster(candidate)
        elif not baseline_ok:
            error = 'direct retrieval baseline failed'
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
    if baseline is not None:
        (out / 'baseline.json').write_text(json.dumps(baseline, indent=2) + '\n')
    guard_receipt = budget.receipt() if budget else None
    if guard_receipt is not None:
        (out / 'mcp_call_guard.json').write_text(json.dumps(guard_receipt, indent=2) + '\n')
    try:
        calls = service_calls(candidate_key)
    except Exception as exc:
        calls = []
        error = (error + '; ' if error else '') + f'call receipt: {type(exc).__name__}: {exc}'
    answer = (result or {}).get('answer', '').strip()
    expected_id = case['expected_id']
    retrieved_ids = list(dict.fromkeys(ident for call in calls for ident in call.get('ids', [])))
    answer_facts = answer.split('|')[0].lower()
    checks = {'baseline_passed': baseline_ok,
              'roster_unchanged': before == after if candidate != 'baseline' else True,
              'bounded_search_calls': 1 <= len(calls) <= 4,
              'expected_passage_retrieved': any(expected_id in call.get('ids', [])[:3]
                                                 for call in calls),
              'source_filter_used': (not case['source'] or
                                     (bool(calls) and all(call.get('arguments', {}).get('source') == case['source']
                                                          for call in calls))),
              'exact_citation_from_result': expected_id in answer and expected_id in retrieved_ids,
              'grounded_fact': all(re.search(pattern, answer_facts, re.I)
                                   for pattern in case['fact_patterns']),
              'parent_clean': bool(result and result.get('exit_code') == 0 and
                                   not result.get('errors') and
                                   result.get('finish_reason') in ('stop', 'completed', 'process_exit_0'))}
    if candidate == 'baseline':
        checks = {'baseline_passed': baseline_ok}
    receipt = {'run_id': run_id, 'candidate': candidate, 'case': case_id,
               'score_version': 2,
               'fixture_sha256': fixture_sha, 'corpus_sha256': corpus_sha,
               'route': 'gpu-rig/chat-27b' if candidate == 'hermes' else common.ROUTE,
               'model': 'qwen3.6:27b' if candidate == 'hermes' else common.MODEL,
               'context': 65536 if candidate == 'hermes' else common.CONTEXT,
               'passed': all(checks.values()) and not error, 'checks': checks,
               'tool_mode': (result or {}).get('tool_mode'),
               'parent_answer': answer, 'parent_duration_seconds': (result or {}).get('duration_seconds'),
               'search_call_count': len(calls),
               'retrieval_duration_ms': round(sum(call.get('duration_ms', 0) for call in calls), 1),
               'retrieved_ids': retrieved_ids,
               'call_arguments': [call.get('arguments') for call in calls],
               'mcp_call_guard': guard_receipt,
               'one_line_format': len(answer.splitlines()) == 1 and '|' in answer,
               'error': error, 'duration_seconds': round(time.monotonic()-started, 2)}
    (out / 'summary.json').write_text(json.dumps(receipt, indent=2) + '\n')
    (out / 'fixture.json').write_text(json.dumps(fixture, indent=2) + '\n')
    print(json.dumps({'candidate': candidate, 'case': case_id, 'passed': receipt['passed'],
                      'failed_checks': [key for key, ok in checks.items() if not ok],
                      'tool_mode': receipt['tool_mode'], 'error': error,
                      'duration_seconds': receipt['duration_seconds']}), flush=True)
    return receipt


def aggregate(run_id):
    root = ROOT / 'results' / run_id / 'local_rag'
    rows = [json.loads(path.read_text()) for path in root.glob('*/*/summary.json')]
    summary = {'run_id': run_id, 'cases': len(rows), 'passed': sum(x['passed'] for x in rows),
               'failed': len(rows)-sum(x['passed'] for x in rows),
               'by_candidate': {name: {'passed': sum(x['passed'] for x in rows if x['candidate'] == name),
                                      'total': sum(x['candidate'] == name for x in rows)}
                                for name in sorted({x['candidate'] for x in rows})}}
    (root / 'matrix.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary), flush=True)
    return summary


def rescore_existing(run_id):
    """Write a separate corrected verdict; keep original model receipts untouched."""
    root = ROOT / 'results' / run_id / 'local_rag'
    rows = [json.loads(path.read_text()) for path in root.glob('*/*/summary.json')]
    corrected = []
    for row in rows:
        checks = dict(row['checks'])
        answer_facts = row.get('parent_answer', '').split('|')[0]
        checks['grounded_fact'] = all(re.search(pattern, answer_facts, re.I)
                                      for pattern in CASES[row['case']]['fact_patterns'])
        corrected.append({'candidate': row['candidate'], 'case': row['case'],
                          'original_passed': row['passed'],
                          'corrected_passed': all(checks.values()) and not row.get('error'),
                          'changed_checks': {key: value for key, value in checks.items()
                                             if value != row['checks'].get(key)}})
    summary = {'run_id': run_id, 'score_version': 2,
               'original_passes': sum(row['original_passed'] for row in corrected),
               'corrected_passes': sum(row['corrected_passed'] for row in corrected),
               'total': len(corrected), 'rows': corrected}
    (root / 'adjudication_v2.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({key: value for key, value in summary.items() if key != 'rows'}), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate', choices=(*DRIVERS, 'baseline', 'summary', 'rescore'))
    parser.add_argument('--case', choices=(*CASES, 'all'), default='all')
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    if args.candidate == 'summary':
        summary = aggregate(args.run_id)
        raise SystemExit(0 if summary['failed'] == 0 else 1)
    if args.candidate == 'rescore':
        rescore_existing(args.run_id)
        return
    cases = CASES if args.case == 'all' else [args.case]
    receipts = [one(args.candidate, case, args.run_id) for case in cases]
    raise SystemExit(0 if all(x['passed'] for x in receipts) else 1)


if __name__ == '__main__':
    main()
