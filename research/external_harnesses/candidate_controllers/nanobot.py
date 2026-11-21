"""nanobot native MCP controller; no upstream checkout edits."""
import json
import os
import subprocess
import sys
import time
import comparison_short_control as common

def run_nanobot(out, prompt, server, target, system):
    targets = list(target) if isinstance(target, (list, tuple)) else [target]
    if 'command' in server:
        server = {**server, 'command': [sys.executable, str(common.ROOT / 'research/external_harnesses/candidate_controllers/mcp_content_proxy.py'),
                                       '--', *server['command']]}
    config = {
        'providers': {'rig': {'apiKey': 'ready-only-local', 'apiBase': 'http://127.0.0.1:8080/v1',
                              'extraHeaders': {'X-Require-Ready': 'true'}}},
        'modelPresets': {'ready30b': {'provider': 'rig', 'model': common.ROUTE,
                                     'maxTokens': 1536, 'contextWindowTokens': common.CONTEXT, 'temperature': 0.1}},
        'agents': {'defaults': {'modelPreset': 'ready30b', 'idleCompactAfterMinutes': 0,
                                'maxToolIterations': 3}},
        'tools': {'maxSessionMessagesPerMinute': 1000, 'restrictToWorkspace': True,
                  'ssrfWhitelist': ['127.0.0.1/32'],
                  'mcpServers': {server['name']: ({'url': server['url']} if 'url' in server else
                                                   {'command': server['command'][0],
                                                    'args': server['command'][1:]}) | {'enabledTools': targets}}},
    }
    (out / 'config.json').write_text(json.dumps(config, indent=2))
    code = '''import asyncio,json,sys
from pathlib import Path
from nanobot import Nanobot
out=Path(sys.argv[1]); prompt=sys.argv[2]; targets=json.loads(sys.argv[3])
async def main():
 async with Nanobot.from_config(out/'config.json',workspace=out/'workspace') as bot:
  await bot._mcp_provider.connect()
  registry=bot._loop.tools
  names=[d.get('function',{}).get('name') or d.get('name') for d in registry.get_definitions()]
  keep=[n for n in names if n and any(n.endswith('_'+target) for target in targets) and n.startswith('mcp_')]
  for n in names:
   if n and n not in keep: registry.unregister(n)
  (out/'registered_tools.json').write_text(json.dumps({'all':names,'model_facing':keep},indent=2))
  if len(keep)!=len(targets): raise RuntimeError('target tools not uniquely registered: '+str(keep))
  for name in keep:
   tool=registry.get(name); original=tool.execute
   async def logged(_original=original,_name=name,**params):
    with (out/'native_tool_calls.jsonl').open('a') as f: f.write(json.dumps({'type':'call','name':_name,'args':params},default=str)+'\\n')
    value=await _original(**params)
    with (out/'native_tool_calls.jsonl').open('a') as f: f.write(json.dumps({'type':'result','name':_name,'result':str(value)[:100000]},default=str)+'\\n')
    return value
   tool.execute=logged
  result=await asyncio.wait_for(bot.run(prompt,session_key='sdk:matrix'),timeout=115)
  print('RESULT '+json.dumps({'answer':result.content,'stop_reason':result.stop_reason,
   'error':result.error,'tools_used':result.tools_used,'metadata':result.metadata},default=str))
asyncio.run(main())
'''
    (out / 'nanobot_trial.py').write_text(code)
    cmd = ['/home/bryan/harness-runtimes/nanobot-0.3.5/venv/bin/python',
           str(out / 'nanobot_trial.py'), str(out), system + '\n\n' + prompt, json.dumps(targets)]
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=out / 'workspace', timeout=120)
    except subprocess.TimeoutExpired as exc:
        (out / 'timeout.txt').write_text(str(exc))
        return {'answer': '', 'finish_reason': None, 'tool_events': [], 'errors': ['timeout'],
                'exit_code': None, 'duration_seconds': round(time.monotonic()-started, 2)}
    (out / 'events.jsonl').write_text(proc.stdout)
    (out / 'stderr.log').write_text(proc.stderr)
    row = next((json.loads(line[7:]) for line in proc.stdout.splitlines() if line.startswith('RESULT ')), {})
    tool_events = []
    path = out / 'native_tool_calls.jsonl'
    for line in path.read_text().splitlines() if path.exists() else []:
        event = json.loads(line)
        if event['type'] == 'call':
            tool_events.append({'type': 'tool_execution_start', 'tool': event['name'],
                                'args': event.get('args')})
        else:
            tool_events.append({'type': 'tool_execution_end', 'tool': event['name'],
                                'result': event.get('result')})
    return {'answer': row.get('answer', ''), 'finish_reason': row.get('stop_reason'),
            'tool_events': tool_events, 'errors': [row['error']] if row.get('error') else [],
            'exit_code': proc.returncode, 'duration_seconds': round(time.monotonic()-started, 2)}


def run_short_control(out):
    import comparison_short_control as short
    (out / 'workspace').mkdir()
    config = {'providers': {'rig': {'apiKey': 'ready-only-local',
                                   'apiBase': 'http://127.0.0.1:8080/v1',
                                   'extraHeaders': {'X-Require-Ready': 'true'}}},
              'modelPresets': {'ready30b': {'provider': 'rig', 'model': short.ROUTE,
                                           'maxTokens': 1536, 'contextWindowTokens': short.CONTEXT,
                                           'temperature': 0.1}},
              'agents': {'defaults': {'modelPreset': 'ready30b', 'idleCompactAfterMinutes': 0,
                                      'maxToolIterations': 1}},
              'tools': {'maxSessionMessagesPerMinute': 1000, 'restrictToWorkspace': True}}
    (out / 'config.json').write_text(json.dumps(config, indent=2))
    code = '''import asyncio,json,sys,time
from pathlib import Path
from nanobot import Nanobot
out=Path(sys.argv[1]); prompts=json.loads(sys.argv[2])
async def main():
 async with Nanobot.from_config(out/'config.json',workspace=out/'workspace') as bot:
  registry=bot._loop.tools
  names=[d.get('function',{}).get('name') or d.get('name') for d in registry.get_definitions()]
  for name in names:
   if name: registry.unregister(name)
  (out/'registered_tools.json').write_text(json.dumps({'removed':names,'model_facing':[]},indent=2))
  for index,prompt in enumerate(prompts,1):
   started=time.monotonic()
   try:
    result=await asyncio.wait_for(bot.run(prompt,session_key='sdk:short-control'),timeout=85)
    row={'turn':index,'answer':result.content,'finish_reason':result.stop_reason,
         'errors':[result.error] if result.error else [],'tool_calls':len(result.tools_used or []),
         'exit_code':0,'duration_seconds':round(time.monotonic()-started,2)}
   except Exception as exc:
    row={'turn':index,'answer':'','finish_reason':None,'errors':[type(exc).__name__+': '+str(exc)],
         'tool_calls':0,'exit_code':1,'duration_seconds':round(time.monotonic()-started,2)}
   with (out/'native_turns.jsonl').open('a') as f: f.write(json.dumps(row)+'\\n')
   print('TURN '+json.dumps(row),flush=True)
   if row['errors']: break
asyncio.run(main())
'''
    (out / 'short_trial.py').write_text(code)
    command = ['/home/bryan/harness-runtimes/nanobot-0.3.5/venv/bin/python',
               str(out / 'short_trial.py'), str(out), json.dumps(short.PROMPTS)]
    proc = subprocess.run(command, input='', text=True, capture_output=True,
                          cwd=out / 'workspace', timeout=300)
    (out / 'events.jsonl').write_text(proc.stdout)
    (out / 'stderr.log').write_text(proc.stderr)
    rows = [json.loads(x[5:]) for x in proc.stdout.splitlines() if x.startswith('TURN ')]
    if proc.returncode and rows:
        rows[-1]['errors'].append('process exit ' + str(proc.returncode))
        rows[-1]['exit_code'] = proc.returncode
    return rows
