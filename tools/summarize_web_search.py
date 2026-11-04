#!/usr/bin/env python3
"""Summarize the live search lane with provider and harness timings separated."""

import csv
import json
from pathlib import Path
import statistics

import comparison_short_control as common
from search_provider_benchmark import QUERIES


ROOT = common.ROOT
RUNS = {x: 'web_search_2026-11-02_six_v1' for x in ('pi', 'deepseek', 'nanobot', 'opencode', 'codex')}
RUNS['hermes'] = 'web_search_2026-11-02_hermes_65k_v1'
ROWS = []
for candidate, run_id in RUNS.items():
    for case in QUERIES:
        path = ROOT / 'results' / run_id / candidate / case['id'] / 'summary.json'
        data = json.loads(path.read_text())
        metrics = data['metrics']
        row = {'candidate': candidate, 'model_block': 'qwen3.6_27b_65536' if candidate == 'hermes' else 'qwen3_coder_30b_32768',
               'case': case['id'], 'direct_baseline': data['checks']['direct_baseline'],
               'pass': data['passed'], 'native_call': data['checks']['one_exact_search_call'],
               'url_count': metrics['url_count'], 'expected_domain_rank': metrics['expected_domain_rank'],
               'answer_url_from_top_5': data['checks']['answer_url_from_top_5'],
               'backend_latency_seconds': metrics['backend_latency_seconds'],
               'candidate_duration_seconds': metrics['duration_seconds'],
               'rate_limit_signal': metrics['rate_limit_signal'],
               'failed_checks': ';'.join(k for k,v in data['checks'].items() if not v),
               'receipt': str(path.relative_to(ROOT))}
        ROWS.append(row)

ledger = ROOT / 'docs/research/harness_web_search_runs.csv'
with ledger.open('w', newline='') as handle:
    writer = csv.DictWriter(handle, fieldnames=list(ROWS[0]))
    writer.writeheader(); writer.writerows(ROWS)

def median(values):
    return round(statistics.median(values), 3) if values else None

summary = {'profile': 'live_web_search_four_query_v1', 'cases_per_candidate': len(QUERIES),
           'direct_baselines_passed': sum(row['direct_baseline'] for row in ROWS),
           'direct_baselines_total': len(ROWS), 'candidates': {}}
for candidate in RUNS:
    rows = [row for row in ROWS if row['candidate'] == candidate]
    called = [row for row in rows if row['native_call']]
    summary['candidates'][candidate] = {'model_block': rows[0]['model_block'],
        'passed': sum(row['pass'] for row in rows), 'cases': len(rows),
        'native_search_calls': len(called),
        'median_backend_latency_seconds': median([row['backend_latency_seconds'] for row in called if row['backend_latency_seconds'] is not None]),
        'median_candidate_duration_seconds': median([row['candidate_duration_seconds'] for row in rows if row['candidate_duration_seconds'] is not None]),
        'observed_url_counts': sorted(set(row['url_count'] for row in called)),
        'relevant_result_top_5': sum(row['expected_domain_rank'] is not None and row['expected_domain_rank'] <= 5 for row in called),
        'rate_limit_signals': sum(bool(row['rate_limit_signal']) for row in called)}
receipt = ROOT / 'results/web_search_2026-11-02_six_summary.json'
receipt.write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(summary))
print(ledger)
