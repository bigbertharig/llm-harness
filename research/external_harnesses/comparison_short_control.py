#!/usr/bin/env python3
"""Frozen short conversation control for Pi, OpenCode, and DeepSeek.

Run on the Pi. Each invocation uses an isolated directory and an already-ready
gateway route; it never asks the manager to load a model.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
import urllib.request

HOME = Path('/home/bryan')
ROOT = HOME / 'llm-harness'
GATEWAY = 'http://127.0.0.1:8080'
ROUTE = os.environ.get('HARNESS_TEST_ROUTE', 'gpu-rig/coder-30b')
MODEL = os.environ.get('HARNESS_TEST_MODEL', 'qwen3-coder:30b-a3b')
CONTEXT = int(os.environ.get('HARNESS_TEST_CONTEXT', '32768'))
def route_spec(candidate):
    if candidate == 'hermes' and 'HARNESS_TEST_ROUTE' not in os.environ:
        return 'gpu-rig/chat-27b', 'qwen3.6:27b', 65536
    return ROUTE, MODEL, CONTEXT
OUTPUT_CAP = 1536
NODE = HOME / '.local/opt/node-v24.14.0-linux-arm64/bin/node'
PI_CLI = HOME / 'harness-runtimes/pi-1.4.0/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js'
OPENCODE = HOME / 'harness-runtimes/opencode-2.1.4/platform/package/bin/opencode'
DEEPSEEK_CLI = HOME / 'deepseek-harness/apps/cli/lib/bin.js'
FIXTURES = ROOT / 'research/external_harnesses/comparison_fixtures'
SYSTEM = 'You are a concise chat assistant. Follow the user instructions.'
PROMPTS = [
    'Remember these project facts: owner Mira; deadline Friday; codeword amber-birch-17; client Vega; artifact atlas.csv; checksum 7c4e; risk orange; release gate QA-42; budget 18 hours. Reply only ACK.',
    'Corrections: owner Nora; deadline Tuesday; release gate QA-43; budget 12 hours. All other facts remain unchanged. Reply only ACK.',
    'What are the current owner, deadline, codeword, client, artifact, checksum, risk, release gate, and budget? List each value. Do not answer ACK.',
]
CURRENT = ['Nora', 'Tuesday', 'amber-birch-17', 'Vega', 'atlas.csv', '7c4e', 'orange', 'QA-43', '12 hours']
OLD = ['Mira', 'Friday', 'QA-42', '18 hours']


def roster():
    with urllib.request.urlopen(GATEWAY + '/v1/rig/ready-roster', timeout=10) as response:
        data = json.load(response)
    if not any(row.get('id') == ROUTE and row.get('model') == MODEL and
               row.get('state') == 'ready' and row.get('context_length') == CONTEXT
               for row in data.get('data', [])):
        raise RuntimeError('pinned route unavailable or changed')
    return data


def roster_for(candidate):
    route, model, context = route_spec(candidate)
    with urllib.request.urlopen(GATEWAY + '/v1/rig/ready-roster', timeout=10) as response:
        data = json.load(response)
    if not any(row.get('id') == route and row.get('model') == model and
               row.get('state') == 'ready' and row.get('context_length') == context
               for row in data.get('data', [])):
        raise RuntimeError(f'{candidate} pinned route unavailable or changed')
    return data


def score(rows):
    answer = rows[-1].get('answer') or ''
    missing = [value for value in CURRENT if value.lower() not in answer.lower()]
    stale = [value for value in OLD if value.lower() in answer.lower()]
    early = [i + 1 for i, row in enumerate(rows[:2]) if (row.get('answer') or '').strip() != 'ACK']
    incomplete = [i + 1 for i, row in enumerate(rows) if row.get('finish_reason') not in ('stop', 'end_turn', 'completed', 'process_exit_0')]
    failed = [i + 1 for i, row in enumerate(rows)
              if row.get('errors') or row.get('exit_code', 0) or row.get('tool_calls', 0)]
    return {'passed': len(rows) == 3 and not (missing or stale or early or incomplete or failed),
            'missing_current': missing, 'included_old': stale,
            'non_ack_early_turns': early, 'incomplete_turns': incomplete,
            'error_turns': failed}








def main():
    from candidate_controllers.pi import run_short_control as run_pi
    from candidate_controllers.deepseek import run_short_control as run_deepseek
    from candidate_controllers.opencode import run_short_control as run_opencode
    from candidate_controllers.codex import run_short_control as run_codex
    from candidate_controllers.nanobot import run_short_control as run_nanobot
    from candidate_controllers.hermes import run_short_control as run_hermes
    parser = argparse.ArgumentParser()
    parser.add_argument('candidate', choices=['pi', 'opencode', 'deepseek', 'codex', 'nanobot', 'hermes'])
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    out = ROOT / 'results' / args.run_id / args.candidate
    out.mkdir(parents=True, exist_ok=False)
    fixture = {'version': 'short-control-v1', 'system': SYSTEM, 'prompts': PROMPTS,
               'current': CURRENT, 'old': OLD,
               'route': route_spec(args.candidate)[0],
               'model': route_spec(args.candidate)[1],
               'context': route_spec(args.candidate)[2],
               'output_cap': None if args.candidate == 'hermes' else OUTPUT_CAP}
    fixture_bytes = json.dumps(fixture, sort_keys=True).encode()
    (out / 'fixture.json').write_text(json.dumps(fixture, indent=2))
    before = roster_for(args.candidate)
    (out / 'ready_before.json').write_text(json.dumps(before, indent=2))
    started = time.time()
    rows = []
    error = None
    try:
        rows = {'pi': run_pi, 'opencode': run_opencode, 'deepseek': run_deepseek,
                'codex': run_codex, 'nanobot': run_nanobot, 'hermes': run_hermes}[args.candidate](out)
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
    try:
        after = roster_for(args.candidate)
    except Exception as exc:
        after = None
        error = (error + '; ' if error else '') + f'post-roster {type(exc).__name__}: {exc}'
    (out / 'ready_after.json').write_text(json.dumps(after, indent=2))
    verdict = score(rows) if rows and all('answer' in row for row in rows) else {'passed': False, 'reason': 'incomplete run'}
    if before != after:
        verdict['passed'] = False
        verdict['roster_changed'] = True
    if error:
        verdict['passed'] = False
    summary = {'candidate': args.candidate, 'run_id': args.run_id,
               'fixture_sha256': hashlib.sha256(fixture_bytes).hexdigest(),
               'driver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'candidate_version': {'pi': '1.4.0', 'opencode': '2.1.4',
                                     'deepseek': 'source checkout 687f282e86',
                                     'codex': 'codex-cli 0.147.0',
                                     'nanobot': '0.3.5',
                                     'hermes': 'source checkout e5f2b15300a3'}[args.candidate],
               'started_at_unix': started, 'finished_at_unix': time.time(),
               'duration_seconds': round(time.time()-started, 2),
               'ready_roster_unchanged': before == after, 'rows': rows,
               'error': error, 'verdict': verdict}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2))
    print('SUMMARY ' + json.dumps({k: v for k, v in summary.items() if k != 'rows'}), flush=True)
    raise SystemExit(0 if verdict['passed'] else 1)


if __name__ == '__main__':
    main()
