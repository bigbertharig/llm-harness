#!/usr/bin/env python3
"""Cycle published parent model sizes through the existing Pi subagent fixture."""

import json
import os
from pathlib import Path
import subprocess
import time
from datetime import datetime, timezone

HARNESS = Path('/home/bryan/llm-harness')
GATEWAY = Path('/home/bryan/llm-gateway')
RIGCTL = GATEWAY / 'tools/rigctl.py'
ROOT = HARNESS / 'results/model_size_sweep_20261105'
CASES = [
    ('7b', 'harness-7b', 'qwen2.5-coder:7b', 16384, '0'),
    ('14b', 'harness-14b', 'qwen2.5-coder:14b', 16384, '0'),
    ('30b', 'coder-30b', 'qwen3-coder:30b-a3b', 32768, '0'),
    ('74b', 'harness-74b', 'nemotron-3.5-bolt:74b-a9b', 16384, '0,2,3,4,5'),
]


def now():
    return datetime.now(timezone.utc).isoformat()


def save(state):
    state['updated_at'] = now()
    pending = ROOT / 'status.json.tmp'
    pending.write_text(json.dumps(state, indent=2) + '\n')
    pending.replace(ROOT / 'status.json')


def command(args, cwd, timeout, log, env=None):
    start = time.monotonic()
    try:
        result = subprocess.run(args, cwd=cwd, env=env, text=True,
                                capture_output=True, timeout=timeout)
        code, stdout, stderr = result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as exc:
        code = 124
        stdout = exc.stdout.decode(errors='replace') if isinstance(exc.stdout, bytes) else (exc.stdout or '')
        stderr = exc.stderr.decode(errors='replace') if isinstance(exc.stderr, bytes) else (exc.stderr or '')
        stderr += '\nTIMEOUT\n'
    log.write_text(stdout + '\n--- stderr ---\n' + stderr)
    return {'exit_code': code, 'duration_seconds': round(time.monotonic()-start, 2),
            'log': str(log)}


def rigctl(*args, timeout=300, log):
    return command(['python3', str(RIGCTL), *args], GATEWAY, timeout, log)


def main():
    ROOT.mkdir(parents=True, exist_ok=False)
    state = {'started_at': now(), 'state': 'running', 'cases': [],
             'large_model_followup': 'An exact 120B profile is not registered; test the locally staged Qwen3.8 Flash-Next 125B Strata model separately.'}
    save(state)
    try:
        for size, profile, model, context, gpus in CASES:
            row = {'size': size, 'profile': profile, 'model': model,
                   'context': context, 'gpus': gpus, 'trials': [], 'state': 'loading'}
            state['cases'].append(row)
            save(state)
            if size == '7b':
                row['load'] = {'preloaded': True}
            else:
                row['load'] = rigctl('load', profile, '--gpus', gpus,
                                     timeout=300, log=ROOT / f'{size}_load.log')
            if row['load'].get('exit_code', 0) != 0:
                row['state'] = 'load_failed'
                save(state)
                continue
            row['state'] = 'testing'
            save(state)
            try:
                for trial in range(1, 4):
                    run_id = f'model_size_{size}_trial_{trial:02d}_20261105'
                    env = os.environ.copy()
                    env.update(HARNESS_TEST_ROUTE='gpu-rig/' + profile,
                               HARNESS_TEST_MODEL=model, HARNESS_TEST_CONTEXT=str(context))
                    result = command(['python3', 'research/external_harnesses/comparison_subagents.py', 'pi',
                                      '--run-id', run_id], HARNESS, 450,
                                     ROOT / f'{size}_trial_{trial:02d}.log', env)
                    result['run_id'] = run_id
                    summary = HARNESS / 'results' / run_id / 'subagents/pi/summary.json'
                    if summary.is_file():
                        receipt = json.loads(summary.read_text())
                        result['passed'] = receipt.get('passed')
                        result['baseline_passed'] = receipt.get('baseline', {}).get('passed')
                        result['failed_checks'] = [k for k, v in receipt.get('checks', {}).items() if not v]
                        result['summary'] = str(summary)
                    row['trials'].append(result)
                    save(state)
                row['state'] = 'complete'
            finally:
                row['unload'] = rigctl('unload', profile, timeout=90,
                                       log=ROOT / f'{size}_unload.log')
                save(state)
        state['state'] = 'complete'
    except Exception as exc:
        state['state'] = 'failed'
        state['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        state['child_unload'] = rigctl('unload', 'coder-7b', timeout=90,
                                        log=ROOT / 'child_unload.log')
        state['finished_at'] = now()
        save(state)
    return 0 if state['state'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
