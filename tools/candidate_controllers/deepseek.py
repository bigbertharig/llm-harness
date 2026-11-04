"""deepseek native MCP controller; no upstream checkout edits."""
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

def run_deepseek(out, prompt, server=None, target=None, system=None):
    server = server or {'name': 'fixture', 'command': [str(common.NODE), str(FIXTURE), str(out / 'calls.jsonl')],
                        'tools': ['read_marker', 'read_structured_marker']}
    shutil.copy2(CONFIGS / 'deepseek_route.patch.yml', out / 'route.patch.yml')
    shutil.copy2(CONFIGS / 'deepseek_no_tools.patch.yml', out / 'no-tools.patch.yml')
    (out / 'home').mkdir()
    transport = (f"        transport: streamable-http\n        url: {server['url']}\n" if 'url' in server else
                 '        transport: stdio\n' + f"        command: {server['command'][0]}\n" +
                 '        args: ' + json.dumps(server['command'][1:]) + '\n')
    mcp_patch = ('- insert:\n    - id: mcp-comparison-fixture\n'
                 "      name: '@deepseek-ai/dsh-mcp-client'\n"
                 f"      config:\n        serverName: {server['name']}\n" + transport +
                 '        failOnStartupError: true\n        reconnect:\n          enabled: false\n')
    (out / 'mcp.patch.yml').write_text(mcp_patch)
    env = os.environ.copy()
    env['PATH'] = str(common.NODE.parent) + ':' + str(common.HOME / 'deepseek-harness/node_modules/.bin') + ':' + env['PATH']
    env['DSH_HOME'] = str(out / 'home')
    env['DSH_GATEWAY_DUMMY_KEY'] = 'local-only'
    cmd = [str(common.NODE), str(common.DEEPSEEK_CLI), '--profile', 'headless',
           '--patch', str(out / 'route.patch.yml'), '--patch', str(out / 'no-tools.patch.yml'),
           '--patch', str(out / 'mcp.patch.yml'), '--json', '-']
    started = time.monotonic()
    try:
        result = subprocess.run(cmd, input=prompt, text=True, capture_output=True,
                                cwd=out / 'workspace', env=env, timeout=120)
    except subprocess.TimeoutExpired as exc:
        (out / 'timeout.txt').write_text(str(exc))
        return {'answer': '', 'finish_reason': None, 'tool_events': [],
                'errors': ['timeout'], 'exit_code': None, 'duration_seconds': round(time.monotonic()-started, 2)}
    (out / 'events.jsonl').write_text(result.stdout)
    (out / 'stderr.log').write_text(result.stderr)
    records = []
    for line in result.stdout.splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    answer = next((x.get('text', '') for x in reversed(records) if x.get('type') == 'final'), '')
    reason = next((x.get('reason') for x in records if x.get('type') == 'status'
                   and x.get('phase') == 'turn_end'), None)
    finish = reason.get('kind') if isinstance(reason, dict) else reason
    tool_events = [x for x in records if x.get('type') in ('tool_call', 'tool_result')]
    errors = [x for x in records if x.get('type') == 'error']
    return {'answer': answer, 'finish_reason': finish, 'tool_events': tool_events,
            'errors': errors, 'exit_code': result.returncode,
            'duration_seconds': round(time.monotonic()-started, 2)}


def run_short_control(out):
    from comparison_short_control import HOME, ROOT, GATEWAY, ROUTE, MODEL, CONTEXT, OUTPUT_CAP, NODE, PI_CLI, OPENCODE, DEEPSEEK_CLI, FIXTURES, SYSTEM, PROMPTS, CURRENT, OLD, roster
    shutil.copy2(FIXTURES / 'deepseek_route.patch.yml', out / 'route.patch.yml')
    shutil.copy2(FIXTURES / 'deepseek_no_tools.patch.yml', out / 'no-tools.patch.yml')
    (out / 'home').mkdir()
    (out / 'workspace').mkdir()
    env = os.environ.copy()
    env['PATH'] = str(NODE.parent) + ':' + str(HOME / 'deepseek-harness/node_modules/.bin') + ':' + env['PATH']
    env['DSH_HOME'] = str(out / 'home')
    env['DSH_GATEWAY_DUMMY_KEY'] = 'local-only'
    base = [str(NODE), str(DEEPSEEK_CLI), '--profile', 'headless',
            '--patch', str(out / 'route.patch.yml'), '--patch', str(out / 'no-tools.patch.yml')]
    session = None
    rows = []
    for index, prompt in enumerate(PROMPTS, 1):
        roster()
        command = base + (['--session-id', session] if session else []) + ['--json', '-']
        started = time.monotonic()
        try:
            result = subprocess.run(command, input=prompt, text=True, capture_output=True,
                                    cwd=out / 'workspace', env=env, timeout=90)
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
        if not session:
            session = next((record.get('sessionId') for record in records if record.get('type') == 'session'), None)
        answer = next((record.get('text', '') for record in reversed(records) if record.get('type') == 'final'), '')
        finish = next((record.get('reason') for record in records
                       if record.get('type') == 'status' and record.get('phase') == 'turn_end'), None)
        if isinstance(finish, dict):
            finish = finish.get('kind')
        errors = [record for record in records if record.get('type') in ('error', 'tool_call')]
        rows.append({'turn': index, 'exit_code': result.returncode, 'session': session,
                     'answer': answer, 'finish_reason': finish, 'errors': errors,
                     'tool_calls': sum(record.get('type') == 'tool_call' for record in records),
                     'duration_seconds': round(time.monotonic()-started, 2)})
        (out / 'progress.json').write_text(json.dumps(rows, indent=2))
        print(json.dumps({'candidate': 'deepseek', 'turn': index, 'exit': result.returncode,
                          'finish': finish, 'answer': answer[:100]}), flush=True)
        if result.returncode or errors or not session:
            break
    return rows
