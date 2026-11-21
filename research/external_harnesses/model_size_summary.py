#!/usr/bin/env python3
"""Reconcile the published-size sweep with the separate Strata large-model trials."""

import json
from pathlib import Path
from statistics import median

ROOT = Path('/home/bryan/llm-harness/results')
SWEEP = ROOT / 'model_size_sweep_20261105'
LARGE_RUNS = [f'model_size_125b_trial_{index:02d}_20261105' for index in range(1, 4)]


def main():
    status_path = SWEEP / 'status.json'
    state = json.loads(status_path.read_text())
    if state['state'] != 'complete':
        raise RuntimeError('background sweep is not complete')
    state.pop('missing_120b', None)
    state['large_model_followup'] = (
        'Qwen3.8 Flash-Next is locally staged and registered: 125B main parameters, '
        '51B N-gram lookup parameters, 6B active per token. Tested separately on Strata.'
    )
    large = next((row for row in state['cases'] if row['size'] == '125b'), None)
    if large is None:
        large = {'size': '125b', 'profile': 'qwen3.8-flash-next-q2-0-g0',
                 'model': 'qwen3.8-flash-next:q2_0', 'context': 8192,
                 'gpus': '0', 'state': 'complete', 'trials': [],
                 'backend': 'strata', 'child_gpu': 1}
        state['cases'].append(large)
    large['trials'] = []
    for run_id in LARGE_RUNS:
        path = ROOT / run_id / 'subagents/pi/summary.json'
        receipt = json.loads(path.read_text())
        large['trials'].append({'run_id': run_id, 'passed': receipt['passed'],
                                'baseline_passed': receipt['baseline']['passed'],
                                'summary': str(path),
                                'duration_seconds': receipt['duration_seconds']})
    status_path.write_text(json.dumps(state, indent=2) + '\n')

    rows = []
    hashes = set()
    for case in state['cases']:
        receipts = [json.loads(Path(trial['summary']).read_text()) for trial in case['trials']]
        hashes.update(receipt['fixture_sha256'] for receipt in receipts)
        rows.append({'size': case['size'], 'model': case['model'],
                     'profile': case['profile'], 'context': case['context'],
                     'gpus': case['gpus'], 'backend': case.get('backend', 'llama'),
                     'trials': len(receipts),
                     'direct_baseline_passes': sum(r['baseline']['passed'] for r in receipts),
                     'native_passes': sum(r['passed'] for r in receipts),
                     'delegation_calls': sum(r['checks'].get('one_delegate_call', False) for r in receipts),
                     'textual_tool_requests': sum(
                         '"mcp__subagent__delegate_task"' in r.get('parent_answer', '')
                         for r in receipts),
                     'median_duration_seconds': round(median(r['duration_seconds'] for r in receipts), 2),
                     'receipt_paths': [str(ROOT / r['run_id'] / 'subagents/pi/summary.json') for r in receipts]})
    if len(hashes) != 1:
        raise RuntimeError('fixture changed during model-size sweep')
    matrix = {'run_id': 'model_size_sweep_20261105', 'candidate': 'pi',
              'fixture_sha256': next(iter(hashes)),
              'note': 'One parent model per size; 125B main plus 51B lookup is not an exact 120B model.',
              'cases': rows}
    (SWEEP / 'matrix.json').write_text(json.dumps(matrix, indent=2) + '\n')
    print(json.dumps({'size_results': [(row['size'], row['native_passes'], row['trials'])
                                        for row in rows], 'fixture_sha256': next(iter(hashes))}))


if __name__ == '__main__':
    main()
