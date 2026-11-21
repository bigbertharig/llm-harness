"""Hermes native MCP controller on its required, separate 27B/65K route."""

import json
import os
import subprocess
import time
import comparison_short_control as common


HERMES = '/home/bryan/harness-runtimes/hermes/venv314/bin/hermes'


def run_hermes(out, prompt, server, target, system):
    targets = list(target) if isinstance(target, (list, tuple)) else [target]
    route, _, context = common.route_spec('hermes')
    home = out / 'hermes_home'
    home.mkdir()
    connection = (f'    url: {json.dumps(server["url"])}\n' if 'url' in server else
                  f'    command: {json.dumps(server["command"][0])}\n' +
                  '    args:\n' + ''.join(f'      - {json.dumps(x)}\n' for x in server['command'][1:]))
    config = (f'model: {route}\nproviders:\n  rig:\n'
              '    api: http://127.0.0.1:8080/v1\n    transport: chat_completions\n'
              f'    api_key: no-key-required\n    default_model: {route}\n'
              f'    discover_models: false\n    models:\n      {route}:\n'
              f'        context_length: {context}\n    extra_headers:\n      X-Require-Ready: "true"\n'
              'toolsets: []\nskills:\n  enabled: false\nmcp_servers:\n'
              f'  {server["name"]}:\n' + connection +
              f'    enabled: true\n    tools:\n      include: {json.dumps(targets)}\n')
    (home / 'config.yaml').write_text(config)
    env = os.environ.copy()
    env['HERMES_HOME'] = str(home)
    cmd = [HERMES, 'chat', '--provider', 'rig', '--model', route,
           '--format', 'stream-json', '--oneshot', '--query', system + '\n\n' + prompt,
           '--in', str(out / 'workspace'), '--ignore-rules']
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, input='', capture_output=True, text=True,
                              cwd=out / 'workspace', env=env, timeout=120)
    except subprocess.TimeoutExpired as exc:
        (out / 'timeout.txt').write_text(str(exc))
        (out / 'events.jsonl').write_text((exc.stdout or b'').decode(errors='replace') if isinstance(exc.stdout, bytes) else (exc.stdout or ''))
        (out / 'stderr.log').write_text((exc.stderr or b'').decode(errors='replace') if isinstance(exc.stderr, bytes) else (exc.stderr or ''))
        return {'answer': '', 'finish_reason': None, 'tool_events': [], 'errors': ['timeout'],
                'exit_code': None, 'duration_seconds': round(time.monotonic()-started, 2)}
    (out / 'events.jsonl').write_text(proc.stdout)
    (out / 'stderr.log').write_text(proc.stderr)
    records = []
    for line in proc.stdout.splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    result = next((x for x in reversed(records) if x.get('type') == 'result'), {})
    tool_events = []
    target_prefix = 'mcp__' + server['name'] + '__'
    for event in records:
        name = event.get('name', '')
        if not name.startswith(target_prefix):
            continue
        if event.get('type') == 'tool_use':
            tool_events.append({'type': 'tool_execution_start', 'tool': name,
                                'args': event.get('input')})
        elif event.get('type') == 'tool_result':
            tool_events.append({'type': 'tool_execution_end', 'tool': name,
                                'result': event.get('output'), 'isError': event.get('is_error', False)})
    finish = 'completed' if result.get('exit_code') == 0 and proc.returncode == 0 else None
    errors = [x for x in records if x.get('type') == 'error']
    return {'answer': result.get('text', ''), 'finish_reason': finish,
            'tool_events': tool_events, 'errors': errors, 'exit_code': proc.returncode,
            'duration_seconds': round(time.monotonic()-started, 2)}


def run_short_control(out):
    import comparison_short_control as short
    route, _, context = short.route_spec('hermes')
    home = out / 'hermes_home'
    home.mkdir()
    (out / 'workspace').mkdir()
    (home / 'config.yaml').write_text(
        f'model: {route}\nproviders:\n  rig:\n'
        '    api: http://127.0.0.1:8080/v1\n    transport: chat_completions\n'
        f'    api_key: no-key-required\n    default_model: {route}\n'
        f'    discover_models: false\n    models:\n      {route}:\n'
        f'        context_length: {context}\n    extra_headers:\n      X-Require-Ready: "true"\n'
        'platform_toolsets:\n  cli: []\nskills:\n  enabled: false\n')
    env = os.environ.copy()
    env['HERMES_HOME'] = str(home)
    session = None
    rows = []
    for index, prompt in enumerate(short.PROMPTS, 1):
        short.roster_for('hermes')
        command = [HERMES, 'chat', '--provider', 'rig', '--model', route,
                   '--format', 'stream-json', '--oneshot', '--query', prompt,
                   '--in', str(out / 'workspace'), '--ignore-rules']
        if session:
            command += ['--resume', session]
        started = time.monotonic()
        try:
            proc = subprocess.run(command, input='', capture_output=True, text=True,
                                  cwd=out / 'workspace', env=env, timeout=120)
        except subprocess.TimeoutExpired as exc:
            (out / f'turn_{index:02d}.timeout.txt').write_text(str(exc))
            rows.append({'turn': index, 'answer': '', 'finish_reason': None,
                         'errors': ['timeout'], 'tool_calls': 0, 'exit_code': None,
                         'duration_seconds': round(time.monotonic()-started, 2)})
            break
        (out / f'turn_{index:02d}.jsonl').write_text(proc.stdout)
        (out / f'turn_{index:02d}.stderr').write_text(proc.stderr)
        events = []
        for line in proc.stdout.splitlines():
            try: events.append(json.loads(line))
            except json.JSONDecodeError: pass
        result = next((x for x in reversed(events) if x.get('type') == 'result'), {})
        if not session:
            session = result.get('session_id')
        tools = [x for x in events if x.get('type') == 'tool_use']
        errors = [x for x in events if x.get('type') == 'error']
        row = {'turn': index, 'answer': result.get('text', ''),
               'finish_reason': 'completed' if result.get('exit_code') == 0 else None,
               'errors': errors, 'tool_calls': len(tools), 'exit_code': proc.returncode,
               'session': session, 'duration_seconds': round(time.monotonic()-started, 2)}
        rows.append(row)
        (out / 'progress.json').write_text(json.dumps(rows, indent=2))
        print(json.dumps({'candidate': 'hermes', 'turn': index, 'finish': row['finish_reason'],
                          'answer': row['answer'][:100], 'errors': len(errors)}), flush=True)
        if proc.returncode or errors or not session:
            break
    return rows
