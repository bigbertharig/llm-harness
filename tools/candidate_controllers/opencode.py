"""opencode native MCP controller; no upstream checkout edits."""
import json
import os
import queue
import shutil
import subprocess
import threading
import time
import comparison_short_control as common
FIXTURE = common.ROOT / "tools/fixtures/local_mcp_marker.mjs"
CONFIGS = common.ROOT / "tools/comparison_fixtures"
SYSTEM = ("Use only the named local fixture MCP tool. Do not use shell, file, web, "
          "or editing tools. Return only the exact marker from the tool result.")

def configure_route(config):
    model = config['providers']['rig']['models']['coder30b']
    model['modelID'] = common.ROUTE
    model['name'] = 'Ready ' + common.MODEL
    model['limit']['context'] = common.CONTEXT
    return config

def run_opencode(out, prompt, server=None, target=None, system=None):
    server = server or {'name': 'fixture', 'command': [str(common.NODE), str(FIXTURE), str(out / 'calls.jsonl')],
                        'tools': ['read_marker', 'read_structured_marker']}
    system = system or SYSTEM
    config = configure_route(json.loads((CONFIGS / 'opencode_config.json').read_text()))
    config['providers']['rig']['settings']['baseURL'] = os.environ.get(
        'OPENCODE_GATEWAY_BASE_URL', config['providers']['rig']['settings']['baseURL'])
    config['providers']['rig']['models']['coder30b']['capabilities']['tools'] = True
    config['agents'] = {'mcpprobe': {
        'description': 'Only the selected MCP tool', 'mode': 'primary', 'system': system,
        'permissions': [
            {'action': action, 'resource': '*', 'effect': 'deny'}
            for action in ('read', 'edit', 'write', 'glob', 'grep', 'shell', 'subagent',
                           'skill', 'question', 'webfetch', 'websearch')
        ] + [
            {'action': server['name'] + '_' + name, 'resource': '*', 'effect': 'allow'}
            for name in server['tools']],
    }}
    connection = ({'type': 'remote', 'url': server['url']} if 'url' in server else
                  {'type': 'local', 'command': server['command']})
    config['mcp'] = {'servers': {server['name']: {**connection, 'enabled': True, 'codemode': False}}}
    (out / 'config.json').write_text(json.dumps(config, indent=2))
    env = os.environ.copy()
    env['OPENCODE_CONFIG'] = str(out / 'config.json')
    env['XDG_DATA_HOME'] = str(out / 'data')
    env['XDG_CONFIG_HOME'] = str(out / 'config_home')
    cmd = [str(common.OPENCODE), 'run', '--standalone', '--print-logs', '--log-level', 'debug',
           '--model', 'rig/coder30b',
           '--agent', 'mcpprobe', '--format', 'json', prompt]
    started = time.monotonic()
    try:
        result = subprocess.run(cmd, cwd=out / 'workspace', env=env, input='',
                                text=True, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired as exc:
        (out / 'timeout.txt').write_text(str(exc))
        return {'answer': '', 'finish_reason': None, 'tool_events': [],
                'errors': ['timeout'], 'exit_code': None, 'duration_seconds': round(time.monotonic()-started, 2)}
    (out / 'events.jsonl').write_text(result.stdout)
    (out / 'stderr.log').write_text(result.stderr)
    (out / 'controller_exit.json').write_text(json.dumps({'exit_code': result.returncode}))
    records = []
    for line in result.stdout.splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    texts = [x.get('part', {}).get('text', '') for x in records if x.get('type') == 'text']
    finishes = [x for x in records if x.get('type') == 'step_finish']
    tool_events = [x for x in records if 'tool' in str(x.get('type', '')).lower()
                   or 'tool' in str(x.get('part', {}).get('type', '')).lower()]
    errors = [x for x in records if 'error' in str(x.get('type', '')).lower()]
    finish = finishes[-1].get('part', {}).get('reason') if finishes else None
    if result.returncode == 0 and texts and (not finishes or records.index(finishes[-1]) < max(
            i for i, item in enumerate(records) if item.get('type') == 'text')):
        finish = 'process_exit_0'
    return {'answer': '\n'.join(texts), 'finish_reason': finish, 'tool_events': tool_events,
            'errors': errors, 'exit_code': result.returncode,
            'duration_seconds': round(time.monotonic()-started, 2)}


def run_short_control(out):
    from comparison_short_control import HOME, ROOT, GATEWAY, ROUTE, MODEL, CONTEXT, OUTPUT_CAP, NODE, PI_CLI, OPENCODE, DEEPSEEK_CLI, FIXTURES, SYSTEM, PROMPTS, CURRENT, OLD, roster
    config = configure_route(json.loads((FIXTURES / 'opencode_config.json').read_text()))
    config['agents']['chatprobe']['system'] = SYSTEM
    (out / 'config.json').write_text(json.dumps(config, indent=2))
    (out / 'workspace').mkdir()
    env = os.environ.copy()
    env['OPENCODE_CONFIG'] = str(out / 'config.json')
    env['XDG_DATA_HOME'] = str(out / 'data')
    env['XDG_CONFIG_HOME'] = str(out / 'config_home')
    session = None
    rows = []
    for index, prompt in enumerate(PROMPTS, 1):
        roster()
        cmd = [str(OPENCODE), 'run', '--standalone', '--model', 'rig/coder30b',
               '--agent', 'chatprobe', '--format', 'json']
        if session:
            cmd += ['--session', session]
        cmd.append(prompt)
        started = time.monotonic()
        try:
            result = subprocess.run(cmd, cwd=out / 'workspace', env=env, input='',
                                    capture_output=True, text=True, timeout=90)
        except subprocess.TimeoutExpired as error:
            (out / f'turn_{index:02d}.timeout.txt').write_text(str(error))
            rows.append({'turn': index, 'error': 'timeout', 'duration_seconds': round(time.monotonic()-started, 2)})
            break
        (out / f'turn_{index:02d}.jsonl').write_text(result.stdout)
        (out / f'turn_{index:02d}.stderr').write_text(result.stderr)
        records = []
        for line in result.stdout.splitlines():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        ids = [record.get('sessionID') for record in records if record.get('sessionID')]
        if ids and not session:
            session = ids[0]
        texts = [record.get('part', {}).get('text', '') for record in records if record.get('type') == 'text']
        finishes = [record for record in records if record.get('type') == 'step_finish']
        finish = (finishes[-1].get('part', {}).get('reason') if finishes else
                  'process_exit_0' if result.returncode == 0 else None)
        errors = [record for record in records if 'error' in str(record.get('type', '')).lower()]
        tools = [record for record in records if 'tool' in str(record.get('type', '')).lower()
                 or 'tool' in str(record.get('part', {}).get('type', '')).lower()]
        rows.append({'turn': index, 'exit_code': result.returncode, 'session': session,
                     'answer': '\n'.join(texts), 'finish_reason': finish,
                     'finish_evidence': 'event' if finishes else 'CLI exit only',
                     'errors': errors, 'tool_calls': len(tools),
                     'duration_seconds': round(time.monotonic()-started, 2)})
        (out / 'progress.json').write_text(json.dumps(rows, indent=2))
        print(json.dumps({'candidate': 'opencode', 'turn': index, 'exit': result.returncode,
                          'finish': finish, 'answer': rows[-1]['answer'][:100]}), flush=True)
        if result.returncode or errors or not session:
            break
    return rows
