#!/usr/bin/env python3
"""Restartable model-first comparison over existing frozen local harness suites.

Use one ready published route at a time. This first phase deliberately excludes
provider-limited search and Windows-hosted MCP dependencies; those retain their
existing runners and will be added after their direct baselines are healthy.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import time

ROOT = Path('/home/bryan/llm-harness')
RIGCTL = Path('/home/bryan/llm-gateway/tools/rigctl.py')
CANDIDATES = ('pi', 'deepseek', 'nanobot', 'opencode', 'codex', 'hermes')
MODELS = {
    '20b': ('gpt-oss-20b', 'gpt-oss:20b', 65536, None, 131072),
    'single_1060': ('harness-gemma4-e4b-64k', 'gemma-4:e4b', 65536, '2', 131072),
    'dual_1060': ('harness-gemma4-12b-64k', 'gemma-4:12b', 65536, '2,3', 262144),
    '27b': ('chat-27b', 'qwen3.6:27b', 65536, None, 262144),
    '30b': ('coder-30b', 'qwen3-coder:30b-a3b', 32768, '0', 262144),
    '74b': ('harness-74b', 'nemotron-3.5-bolt:74b-a9b', 16384,
            '0,2,3,4,5', 262144),
}
LOCAL_MCP = ('marker_text', 'marker_structured', 'numeric_sum',
             'numeric_product', 'lookup_text', 'lookup_nested')
CASES = [('short', None)] + [('mcp_local', case) for case in LOCAL_MCP] + [
    ('subagent', None), ('web_research', None)]


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, data):
    data['updated_at'] = now()
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def invoke(command, cwd, timeout, log, env=None):
    start = time.monotonic()
    try:
        proc = subprocess.run(command, cwd=cwd, env=env, text=True,
                              capture_output=True, timeout=timeout)
        code, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        code = 124
        stdout = exc.stdout.decode(errors='replace') if isinstance(exc.stdout, bytes) else (exc.stdout or '')
        stderr = exc.stderr.decode(errors='replace') if isinstance(exc.stderr, bytes) else (exc.stderr or '')
        stderr += '\nTIMEOUT\n'
    log.write_text(stdout + '\n--- stderr ---\n' + stderr)
    return {'exit_code': code, 'duration_seconds': round(time.monotonic() - start, 2),
            'log': str(log)}


def command_for(lane, case, candidate, run_id):
    if lane == 'short':
        return ['python3', 'research/external_harnesses/comparison_short_control.py', candidate,
                '--run-id', run_id], 420
    if lane == 'mcp_local':
        return ['python3', 'research/external_harnesses/comparison_mcp_matrix.py', candidate, case,
                '--run-id', run_id], 180
    if lane == 'subagent':
        return ['python3', 'research/external_harnesses/comparison_subagents.py', candidate,
                '--run-id', run_id], 480
    if lane == 'web_research':
        return ['python3', 'research/external_harnesses/comparison_web_research.py', candidate,
                '--run-id', run_id], 300
    raise ValueError(lane)


def main():
    def stop_requested(*_):
        raise RuntimeError('received SIGTERM')

    signal.signal(signal.SIGTERM, stop_requested)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--models', nargs='+', choices=tuple(MODELS),
                        default=list(MODELS))
    args = parser.parse_args()
    output = ROOT / 'results' / args.run_id
    output.mkdir(parents=True, exist_ok=True)
    status_path = output / 'status.json'
    state = json.loads(status_path.read_text()) if status_path.exists() else {
        'run_id': args.run_id, 'started_at': now(), 'state': 'running',
        'model_order': args.models, 'case_count_per_supported_harness': len(CASES),
        'hermes_min_context': 64000, 'rows': {}}
    if state['model_order'] != args.models:
        raise ValueError('resume model order differs from existing run')
    save(status_path, state)
    active_profile = None
    try:
        for key in args.models:
            profile, model, context, gpus, trained_max = MODELS[key]
            model_dir = output / key
            model_dir.mkdir(exist_ok=True)
            model_state = state['rows'].setdefault(key, {
                'profile': profile, 'model': model, 'served_context': context,
                'trained_max': trained_max, 'gpus': gpus, 'cases': {},
                'state': 'pending'})
            pending = [f'{candidate}/{lane}/{case or "one"}'
                       for candidate in CANDIDATES for lane, case in CASES
                       if f'{candidate}/{lane}/{case or "one"}' not in model_state['cases']]
            if not pending:
                continue
            model_state['state'] = 'loading'
            save(status_path, state)
            active_profile = profile
            load = ['python3', str(RIGCTL), 'load', profile]
            if gpus:
                load += ['--gpus', gpus]
            model_state['load'] = invoke(load, RIGCTL.parent.parent, 600,
                                         model_dir / 'load.log')
            save(status_path, state)
            if model_state['load']['exit_code']:
                model_state['state'] = 'load_failed'
                model_state['unload_after_failed_load'] = invoke(
                    ['python3', str(RIGCTL), 'unload', profile],
                    RIGCTL.parent.parent, 120, model_dir / 'failed_load_cleanup.log')
                active_profile = None
                save(status_path, state)
                continue
            model_state['state'] = 'testing'
            save(status_path, state)
            env = os.environ.copy()
            env.update(HARNESS_TEST_ROUTE=f'gpu-rig/{profile}',
                       HARNESS_TEST_MODEL=model, HARNESS_TEST_CONTEXT=str(context))
            try:
                for candidate in CANDIDATES:
                    for lane, case in CASES:
                        row_key = f'{candidate}/{lane}/{case or "one"}'
                        if row_key in model_state['cases']:
                            continue
                        if candidate == 'hermes' and context < 64000:
                            row = {'status': 'incompatible_context',
                                   'required_context': 64000, 'served_context': context}
                        else:
                            command, timeout = command_for(lane, case, candidate,
                                                           f'{args.run_id}_{key}')
                            log = model_dir / (row_key.replace('/', '__') + '.log')
                            row = invoke(command, ROOT, timeout, log, env)
                            row['status'] = 'completed' if row['exit_code'] == 0 else 'failed'
                        row['finished_at'] = now()
                        model_state['cases'][row_key] = row
                        save(status_path, state)
                model_state['state'] = 'complete'
            finally:
                model_state['unload'] = invoke(
                    ['python3', str(RIGCTL), 'unload', profile],
                    RIGCTL.parent.parent, 120, model_dir / 'unload.log')
                active_profile = None
                save(status_path, state)
        state['state'] = 'complete'
        state.pop('error', None)
    except Exception as exc:
        state['state'] = 'failed'
        state['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        if active_profile:
            state['interrupted_unload'] = invoke(
                ['python3', str(RIGCTL), 'unload', active_profile],
                RIGCTL.parent.parent, 120, output / 'interrupted_unload.log')
        state['finished_at'] = now()
        save(status_path, state)
        (output / 'terminal_receipt.json').write_text(json.dumps({
            'run_id': args.run_id, 'state': state['state'],
            'exit_status': 0 if state['state'] == 'complete' else 1,
            'finished_at': state['finished_at'], 'error': state.get('error')}, indent=2) + '\n')
    return 0 if state['state'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
