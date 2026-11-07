"""codex native MCP controller; no upstream checkout edits."""
import json
import os
import shutil
import subprocess
import time
import comparison_short_control as common


def _prune_transient_plugins(home):
    """Remove only Codex's per-run plugin checkouts from an isolated test home."""
    temporary = home / '.tmp'
    if not temporary.is_dir() or temporary.is_symlink():
        return
    root = home.resolve()
    removed = []
    for path in temporary.iterdir():
        if path.name != 'plugins' and not path.name.startswith('plugins-clone-'):
            continue
        if not path.is_dir() or path.is_symlink() or not path.resolve().is_relative_to(root):
            continue
        shutil.rmtree(path)
        removed.append(path.name)
    if removed:
        (home.parent / 'plugin_cache_cleanup.json').write_text(json.dumps({'removed': removed}))

def _records(raw):
    rows = []
    for line in raw.splitlines():
        try: rows.append(json.loads(line))
        except json.JSONDecodeError: pass
    return rows

def _terminal_errors(records):
    completed = any(row.get('type') == 'turn.completed' for row in records)
    return [row for row in records if row.get('type') == 'turn.failed' or
            (row.get('type') == 'error' and not
             (completed and str(row.get('message', '')).startswith('Reconnecting...')))]

def run_codex(out, prompt, server, target, system):
    from codex_responses_compat import codex_gateway_compat
    with codex_gateway_compat(out / 'gateway_compat.jsonl') as gateway_base_url:
        return _run_codex_with_gateway(out, prompt, server, target, system, gateway_base_url)


def _run_codex_with_gateway(out, prompt, server, target, system, gateway_base_url):
    targets = list(target) if isinstance(target, (list, tuple)) else [target]
    home = out / 'codex_home'
    home.mkdir()
    if 'url' in server:
        mcp = f'url = {json.dumps(server["url"])}\n'
    else:
        mcp = f'command = {json.dumps(server["command"][0])}\nargs = {json.dumps(server["command"][1:])}\n'
    (home / 'config.toml').write_text(
        f'model = {json.dumps(common.ROUTE)}\nmodel_provider = "rig"\nmodel_context_window = {common.CONTEXT}\n'
        'approval_policy = "never"\nsandbox_mode = "read-only"\n'
        '[features]\nshell_tool = false\nunified_exec = false\n'
        f'[model_providers.rig]\nname = "Local rig gateway"\nbase_url = {json.dumps(gateway_base_url)}\n'
        'wire_api = "responses"\nrequires_openai_auth = false\nrequest_max_retries = 0\n'
        'http_headers = { "X-Require-Ready" = "true" }\n'
        f'\n[mcp_servers.{server["name"]}]\n{mcp}enabled_tools = {json.dumps(targets)}\n'
        'default_tools_approval_mode = "approve"\n')
    env = os.environ.copy()
    env['CODEX_HOME'] = str(home)
    cmd = ['codex', 'exec', '--json', '--ignore-rules', '--skip-git-repo-check',
           '--ephemeral', '--model', common.ROUTE, '-C', str(out / 'workspace'),
           system + '\n\n' + prompt]
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, input='', text=True, capture_output=True, env=env,
                              cwd=out / 'workspace', timeout=120)
    except subprocess.TimeoutExpired as exc:
        (out / 'timeout.txt').write_text(str(exc))
        (out / 'events.jsonl').write_text((exc.stdout or b'').decode(errors='replace') if isinstance(exc.stdout, bytes) else (exc.stdout or ''))
        (out / 'stderr.log').write_text((exc.stderr or b'').decode(errors='replace') if isinstance(exc.stderr, bytes) else (exc.stderr or ''))
        return {'answer': '', 'finish_reason': None, 'tool_events': [], 'errors': ['timeout'],
                'exit_code': None, 'duration_seconds': round(time.monotonic()-started, 2)}
    finally:
        _prune_transient_plugins(home)
    (out / 'events.jsonl').write_text(proc.stdout)
    (out / 'stderr.log').write_text(proc.stderr)
    records = _records(proc.stdout)
    tool_events = []
    answers = []
    for event in records:
        item = event.get('item') or {}
        if item.get('type') == 'mcp_tool_call':
            name = item.get('tool') or item.get('name')
            full_name = f'mcp__{item.get("server", server["name"])}__{name}'
            if event.get('type') == 'item.started':
                tool_events.append({'type': 'tool_execution_start', 'tool': full_name,
                                    'args': item.get('arguments')})
            if event.get('type') == 'item.completed':
                tool_events.append({'type': 'tool_execution_end', 'tool': full_name,
                                    'result': item.get('result'), 'status': item.get('status')})
        if event.get('type') == 'item.completed' and item.get('type') == 'agent_message':
            answers.append(item.get('text', ''))
    finish = 'completed' if any(x.get('type') == 'turn.completed' for x in records) else None
    errors = _terminal_errors(records)
    return {'answer': answers[-1] if answers else '', 'finish_reason': finish,
            'tool_events': tool_events, 'errors': errors, 'exit_code': proc.returncode,
            'duration_seconds': round(time.monotonic()-started, 2)}


def run_short_control(out):
    import comparison_short_control as short
    home = out / 'codex_home'
    home.mkdir()
    (out / 'workspace').mkdir()
    (home / 'config.toml').write_text(
        f'model = {json.dumps(short.ROUTE)}\nmodel_provider = "rig"\nmodel_context_window = {short.CONTEXT}\n'
        'approval_policy = "never"\nsandbox_mode = "read-only"\n'
        '[features]\nshell_tool = false\nunified_exec = false\n'
        '[model_providers.rig]\nname = "Local rig gateway"\n'
        'base_url = "http://127.0.0.1:8080/v1"\nwire_api = "responses"\n'
        'requires_openai_auth = false\nrequest_max_retries = 0\n'
        'http_headers = { "X-Require-Ready" = "true" }\n')
    env = os.environ.copy()
    env['CODEX_HOME'] = str(home)
    session = None
    rows = []
    for index, prompt in enumerate(short.PROMPTS, 1):
        short.roster()
        command = (['codex', 'exec', 'resume', '--json', '--ignore-rules',
                    '--skip-git-repo-check', '--model', short.ROUTE, session, prompt]
                   if session else
                   ['codex', 'exec', '--json', '--ignore-rules', '--skip-git-repo-check',
                    '--model', short.ROUTE, '-C', str(out / 'workspace'), prompt])
        started = time.monotonic()
        try:
            proc = subprocess.run(command, input='', text=True, capture_output=True,
                                  cwd=out / 'workspace', env=env, timeout=90)
        except subprocess.TimeoutExpired as exc:
            (out / f'turn_{index:02d}.timeout.txt').write_text(str(exc))
            rows.append({'turn': index, 'answer': '', 'finish_reason': None,
                         'errors': ['timeout'], 'tool_calls': 0, 'exit_code': None,
                         'duration_seconds': round(time.monotonic()-started, 2)})
            break
        (out / f'turn_{index:02d}.jsonl').write_text(proc.stdout)
        (out / f'turn_{index:02d}.stderr').write_text(proc.stderr)
        events = _records(proc.stdout)
        if not session:
            session = next((x.get('thread_id') for x in events if x.get('type') == 'thread.started'), None)
        texts = [x.get('item', {}).get('text', '') for x in events
                 if x.get('type') == 'item.completed' and x.get('item', {}).get('type') == 'agent_message']
        tools = [x for x in events if x.get('type') == 'item.started' and
                 str(x.get('item', {}).get('type', '')).endswith('_tool_call')]
        errors = _terminal_errors(events)
        row = {'turn': index, 'answer': texts[-1] if texts else '',
               'finish_reason': 'completed' if any(x.get('type') == 'turn.completed' for x in events) else None,
               'errors': errors, 'tool_calls': len(tools), 'exit_code': proc.returncode,
               'session': session, 'duration_seconds': round(time.monotonic()-started, 2)}
        rows.append(row)
        (out / 'progress.json').write_text(json.dumps(rows, indent=2))
        print(json.dumps({'candidate': 'codex', 'turn': index, 'finish': row['finish_reason'],
                          'answer': row['answer'][:100], 'errors': len(errors)}), flush=True)
        if proc.returncode or errors or not session:
            break
    _prune_transient_plugins(home)
    return rows
