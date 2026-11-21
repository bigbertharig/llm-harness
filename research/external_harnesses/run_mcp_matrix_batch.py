#!/usr/bin/env python3
"""Run the frozen six-server MCP matrix and retain every case receipt."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

import comparison_mcp_matrix as matrix

ACTIVE_CASES = [
    'marker_text', 'marker_structured',
    'research_packs', 'research_sources',
    'geometry_shape', 'geometry_help',
    'deepwiki_servers', 'deepwiki_python',
    'openai_streaming', 'openai_function_calling',
    'cloudflare_workers_any', 'cloudflare_durable_any',
]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('candidate', choices=['pi', 'deepseek', 'opencode', 'codex', 'nanobot', 'hermes'])
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--cases', nargs='*', choices=ACTIVE_CASES, default=ACTIVE_CASES)
    args = parser.parse_args()
    batch = matrix.ROOT / 'results' / args.run_id / args.candidate
    batch.mkdir(parents=True, exist_ok=False)
    rows = []
    for case in args.cases:
        started = time.time()
        cmd = [sys.executable, str(matrix.ROOT / 'research/external_harnesses/comparison_mcp_matrix.py'),
               args.candidate, case, '--run-id', args.run_id]
        proc = subprocess.run(cmd, text=True, capture_output=True)
        # The child creates the case directory; retain a batch-level terminal receipt too.
        summary_path = batch / case / 'summary.json'
        if summary_path.exists():
            summary = json.loads(summary_path.read_text())
            verdict = summary['verdict']
            row = {'case': case, 'server': summary['server'], 'passed': verdict['passed'],
                   'exit_code': proc.returncode, 'error': summary.get('error'),
                   'failed_checks': [k for k, v in verdict.get('checks', {}).items() if not v],
                   'duration_seconds': summary['duration_seconds'], 'receipt': str(summary_path.relative_to(matrix.ROOT))}
        else:
            row = {'case': case, 'passed': False, 'exit_code': proc.returncode,
                   'error': proc.stderr[-500:], 'duration_seconds': round(time.time()-started, 2)}
        rows.append(row)
        (batch / 'batch_progress.json').write_text(json.dumps(rows, indent=2))
        print(json.dumps(row), flush=True)
        if case.startswith('cloudflare_'): time.sleep(2)
    result = {'candidate': args.candidate, 'run_id': args.run_id, 'cases': len(rows),
              'passed': sum(bool(x['passed']) for x in rows), 'rows': rows,
              'finished_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    (batch / 'batch_summary.json').write_text(json.dumps(result, indent=2))
    print('BATCH_SUMMARY ' + json.dumps({k: v for k, v in result.items() if k != 'rows'}), flush=True)
    return 0

if __name__ == '__main__': raise SystemExit(main())
