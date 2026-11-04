"""Replay sanitized Codex tool declarations through the local Responses route."""
import json
from pathlib import Path
import sys
import urllib.request

root = Path(__file__).resolve().parents[1]
trace = root / 'results' / 'codex_tool_trace_full_2026-11-02' / 'gateway_tool_trace.jsonl'
entry = json.loads(trace.read_text().splitlines()[0])
mode = sys.argv[1] if len(sys.argv) > 1 else 'namespace'
tools = ([tool for tool in entry['tools'] if tool.get('name') == 'mcp__marker']
         if mode == 'namespace' else entry['tools'])
if mode == 'flat_all':
    tools = [dict(child, name=f"{tool['name']}__{child['name']}")
             for tool in tools if tool.get('type') == 'namespace'
             for child in tool['tools']] + [
                 tool for tool in tools if tool.get('type') != 'namespace']
payload = {
    'model': 'gpu-rig/coder-30b',
    'input': ('Use only the marker MCP server and its read_marker tool. '
              'Call read_marker exactly once with {} and return only its marker value.'),
    'tools': tools,
    'tool_choice': 'auto',
    'max_output_tokens': 256,
}
request = urllib.request.Request('http://127.0.0.1:8080/v1/responses',
    data=json.dumps(payload).encode(),
    headers={'Content-Type': 'application/json', 'X-Require-Ready': 'true'})
with urllib.request.urlopen(request, timeout=90) as response:
    result = json.load(response)
print(json.dumps({'mode': mode, 'status': result.get('status'),
                  'output': result.get('output'), 'error': result.get('error')}, indent=2))
