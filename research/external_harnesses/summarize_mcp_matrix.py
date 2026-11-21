#!/usr/bin/env python3
"""Build the six-candidate MCP case ledger; keep Hermes's model block separate."""
import csv
import json

import comparison_mcp_matrix as matrix


ROOT = matrix.ROOT
V1 = 'mcp_matrix_2026-11-02_full_v1'
V2 = 'mcp_matrix_2026-11-02_refined_v2'
RUNS = {
    'nanobot': 'mcp_matrix_2026-11-02_extra_v1',
    'codex': 'mcp_matrix_2026-11-02_codex_mcp_only_v2',
    'hermes': 'mcp_matrix_2026-11-02_hermes_65k_v1',
}
CASES = [
    'marker_text', 'marker_structured', 'research_packs', 'research_sources',
    'geometry_shape', 'geometry_help', 'deepwiki_servers', 'deepwiki_python',
    'openai_streaming', 'openai_function_calling', 'cloudflare_workers_any',
    'cloudflare_durable_any',
]
CANDIDATES_30B = ['pi', 'deepseek', 'opencode', 'nanobot', 'codex']
CANDIDATES = CANDIDATES_30B + ['hermes']


rows = []
for case in CASES:
    summaries = {}
    run_ids = {}
    for candidate in CANDIDATES:
        run_id = RUNS.get(candidate) or (V2 if case.endswith('_any') else V1)
        run_ids[candidate] = run_id
        path = ROOT / 'results' / run_id / candidate / case / 'summary.json'
        summaries[candidate] = json.loads(path.read_text())
    if not all(summaries[x].get('baseline') for x in CANDIDATES):
        raise RuntimeError('direct baseline missing for ' + case)
    name, tool, args, difficulty, shape = matrix.CASES[case]
    passed = {x: bool(summaries[x]['verdict']['passed']) for x in CANDIDATES}
    row = {'case': case, 'server': name, 'tool': tool, 'difficulty': difficulty,
           'result_shape': shape, 'direct_baseline': 'Pass',
           'comparison_included': 'Yes: direct baseline passed',
           'all_30b_failed': 'Yes' if not any(passed[x] for x in CANDIDATES_30B) else 'No',
           'all_six_failed': 'Yes' if not any(passed.values()) else 'No'}
    for candidate in CANDIDATES:
        row[candidate] = 'Pass' if passed[candidate] else 'Fail'
        row[candidate + '_failed_checks'] = ';'.join(k for k, value in summaries[candidate]['verdict'].get('checks', {}).items() if not value)
        row[candidate + '_receipt'] = f'results/{run_ids[candidate]}/{candidate}/{case}/summary.json'
    rows.append(row)

ledger = ROOT / 'docs/research/harness_mcp_matrix_runs.csv'
with ledger.open('w', newline='') as handle:
    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
    writer.writeheader(); writer.writerows(rows)

summary = {'profile': 'mcp_six_server_twelve_case_v2', 'cases': len(rows),
           'direct_baselines_passed': len(rows),
           'model_blocks': {
               'qwen3_coder_30b_32768': {x: sum(row[x] == 'Pass' for row in rows) for x in CANDIDATES_30B},
               'qwen3_6_27b_65536': {'hermes': sum(row['hermes'] == 'Pass' for row in rows)},
           },
           'all_30b_failed_cases': [x['case'] for x in rows if x['all_30b_failed'] == 'Yes'],
           'all_six_failed_cases': [x['case'] for x in rows if x['all_six_failed'] == 'Yes'],
           'strict_cloudflare_receipts': f'results/{V1}/',
           'daedal_public_baseline_error': 'coverage_catalog_unconfigured'}
receipt = ROOT / 'results/mcp_matrix_2026-11-02_matrix_summary_v2.json'
receipt.write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(summary))
print(ledger)
