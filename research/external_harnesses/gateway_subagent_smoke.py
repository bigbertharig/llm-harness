#!/usr/bin/env python3
"""One live parent -> MCP delegate -> manager -> native child smoke receipt."""

import argparse
import json
import os
from pathlib import Path
import sys

os.environ['HARNESS_TEST_ROUTE'] = 'gpu-rig/chat-27b'
os.environ['HARNESS_TEST_MODEL'] = 'qwen3.6:27b'
os.environ['HARNESS_TEST_CONTEXT'] = '65536'

from candidate_controllers.pi import run_pi

ROOT = Path('/home/bryan/llm-harness')
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run-id', required=True)
args = parser.parse_args()
out = ROOT / 'results' / args.run_id
out.mkdir(parents=True, exist_ok=False)
(out / 'workspace').mkdir()
os.environ['SUBAGENT_PARENT_ROUTE'] = 'gpu-rig/chat-27b'
os.environ['SUBAGENT_RECEIPT_DIR'] = str(out / 'children')
server = {'name': 'delegate', 'command': [sys.executable, str(ROOT / 'tools/gateway_subagent_mcp.py')],
          'tools': ['delegate_task']}
result = run_pi(out, 'Ask a coding child agent to compute 7 times 6. Use delegate_task with agent_type coding. Check its answer and report only the number.',
                server=server, target='delegate_task',
                system='You are a parent agent. Use delegate_task once for the requested coding task. Verify the child answer. Return only the number.')
children = sorted((out / 'children').glob('*/summary.json')) if (out / 'children').exists() else []
result['child_receipts'] = [str(path) for path in children]
(out / 'summary.json').write_text(json.dumps(result, indent=2))
print(json.dumps({'answer': result['answer'], 'errors': result['errors'],
                  'exit_code': result['exit_code'], 'child_receipts': result['child_receipts']}))
sys.exit(0 if result['answer'].strip() == '42' and children and not result['errors'] else 1)
