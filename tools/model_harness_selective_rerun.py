#!/usr/bin/env python3
"""Checkpointed model-first rerun of controller paths changed after core matrix v1."""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import signal

from model_harness_matrix import ROOT, RIGCTL, MODELS, LOCAL_MCP, command_for, invoke, now, save

MODEL_ORDER = ('20b', 'single_1060', 'dual_1060', '27b', '30b', '74b')
CHANGED_FILES = (
    'tools/candidate_controllers/mcp_content_proxy.py',
    'tools/candidate_controllers/deepseek.py',
    'tools/candidate_controllers/nanobot.py',
    'tools/candidate_controllers/opencode.py',
    'tools/candidate_controllers/hermes.py',
    'tools/candidate_controllers/codex.py',
)


def selected(context):
    rows = []
    for candidate in ('deepseek', 'nanobot'):
        rows.extend((candidate, 'mcp_local', case) for case in ('marker_structured', 'lookup_nested'))
    rows.extend(('opencode', 'mcp_local', case) for case in LOCAL_MCP)
    rows.extend((('opencode', 'subagent', None), ('opencode', 'web_research', None)))
    if context >= 64000:
        rows.append(('hermes', 'short', None))
    return rows


def case_key(candidate, lane, case):
    return f'{candidate}/{lane}/{case or "one"}'


def main():
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(RuntimeError('received SIGTERM')))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    output = ROOT / 'results' / args.run_id
    output.mkdir(parents=True, exist_ok=True)
    status_path = output / 'status.json'
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in CHANGED_FILES}
    state = json.loads(status_path.read_text()) if status_path.exists() else {
        'run_id': args.run_id, 'baseline_run_id': 'model_harness_core_20261105_v1',
        'started_at': now(), 'state': 'running', 'model_order': MODEL_ORDER,
        'changed_file_sha256': hashes, 'rows': {}}
    if tuple(state['model_order']) != MODEL_ORDER or state['changed_file_sha256'] != hashes:
        raise ValueError('resume inputs differ from saved matrix')
    state['state'] = 'running'
    state.pop('error', None)
    save(status_path, state)
    active_profile = None
    try:
        for key in MODEL_ORDER:
            profile, model, context, gpus, trained_max = MODELS[key]
            cases = selected(context)
            model_dir = output / key
            model_dir.mkdir(exist_ok=True)
            row = state['rows'].setdefault(key, {
                'profile': profile, 'model': model, 'served_context': context,
                'trained_max': trained_max, 'gpus': gpus,
                'selected_cases': [case_key(*item) for item in cases],
                'cases': {}, 'state': 'pending'})
            if all(case_key(*item) in row['cases'] for item in cases):
                continue
            row['state'] = 'loading'
            save(status_path, state)
            active_profile = profile
            command = ['python3', str(RIGCTL), 'load', profile]
            if gpus:
                command += ['--gpus', gpus]
            row['load'] = invoke(command, RIGCTL.parent.parent, 600, model_dir / 'load.log')
            save(status_path, state)
            if row['load']['exit_code']:
                row['state'] = 'load_failed'
                row['unload'] = invoke(['python3', str(RIGCTL), 'unload', profile],
                                       RIGCTL.parent.parent, 120, model_dir / 'load_cleanup.log')
                active_profile = None
                save(status_path, state)
                continue
            row['state'] = 'testing'
            save(status_path, state)
            env = os.environ.copy()
            env.update(HARNESS_TEST_ROUTE=f'gpu-rig/{profile}',
                       HARNESS_TEST_MODEL=model, HARNESS_TEST_CONTEXT=str(context))
            try:
                for candidate, lane, case in cases:
                    name = case_key(candidate, lane, case)
                    if name in row['cases']:
                        continue
                    command, timeout = command_for(lane, case, candidate, f'{args.run_id}_{key}')
                    result = invoke(command, ROOT, timeout,
                                    model_dir / (name.replace('/', '__') + '.log'), env)
                    result['status'] = 'completed' if result['exit_code'] == 0 else 'failed'
                    result['finished_at'] = now()
                    row['cases'][name] = result
                    save(status_path, state)
                row['state'] = 'complete'
            finally:
                row['unload'] = invoke(['python3', str(RIGCTL), 'unload', profile],
                                       RIGCTL.parent.parent, 120, model_dir / 'unload.log')
                active_profile = None
                save(status_path, state)
        state['state'] = 'complete'
    except Exception as exc:
        state['state'] = 'failed'
        state['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        if active_profile:
            state['interrupted_unload'] = invoke(['python3', str(RIGCTL), 'unload', active_profile],
                                                 RIGCTL.parent.parent, 120, output / 'interrupted_unload.log')
        state['finished_at'] = now()
        counts = Counter(case['status'] for row in state['rows'].values() for case in row['cases'].values())
        state['counts'] = dict(counts)
        save(status_path, state)
        (output / 'terminal_receipt.json').write_text(json.dumps({
            'run_id': args.run_id, 'state': state['state'],
            'exit_status': 0 if state['state'] == 'complete' else 1,
            'finished_at': state['finished_at'], 'counts': dict(counts),
            'error': state.get('error')}, indent=2) + '\n')
    return 0 if state['state'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
