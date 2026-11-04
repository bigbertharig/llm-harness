"""pi native MCP controller; no upstream checkout edits."""
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


def write_models(path):
    config = json.loads((CONFIGS / 'pi_models.json').read_text())
    model = config['providers']['rig']['models'][0]
    model['id'] = common.ROUTE
    model['name'] = 'Ready ' + common.MODEL
    model['contextWindow'] = common.CONTEXT
    path.write_text(json.dumps(config, indent=2))

def run_pi(out, prompt, server=None, target=None, system=None):
    target = target or ('read_structured_marker' if 'read_structured_marker' in prompt else 'read_marker')
    server = server or {'name': 'fixture', 'command': [str(common.NODE), str(FIXTURE), str(out / 'calls.jsonl')],
                        'tools': ['read_marker', 'read_structured_marker']}
    system = system or SYSTEM
    agent = out / 'agent'
    agent.mkdir()
    write_models(agent / 'models.json')
    shutil.copy2(CONFIGS / 'pi_settings.json', agent / 'settings.json')
    (agent / 'auth.json').write_text('{}')
    (agent / 'models-store.json').write_text('{}')
    connection = ({'url': server['url']} if 'url' in server else
                  {'command': server['command'][0], 'args': server['command'][1:]})
    (agent / 'mcp.json').write_text(json.dumps({'mcpServers': {server['name']: {**connection,
        'exposure': 'hidden',
        'toolExposure': {name: 'direct' for name in server['tools']},
        'description': 'MCP tools for the harness comparison',
    }}}, indent=2))
    env = os.environ.copy()
    env['PI_CODING_AGENT_DIR'] = str(agent)
    cmd = [str(common.NODE), str(common.PI_CLI), '--mode', 'rpc',
           '--tools', 'mcp__' + server['name'] + '__' + target,
           '--no-skills', '--no-prompt-templates', '--no-context-files',
           '--system-prompt', system, '--session-dir', str(out / 'sessions'),
           '--provider', 'rig', '--model', common.ROUTE]
    with (out / 'events.jsonl').open('w') as events, (out / 'stderr.log').open('w') as stderr:
        proc = subprocess.Popen(cmd, cwd=out / 'workspace', env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=stderr, text=True, bufsize=1)
        received = queue.Queue()
        def reader():
            for line in proc.stdout:
                events.write(line)
                events.flush()
                try:
                    received.put(json.loads(line))
                except json.JSONDecodeError:
                    pass
            received.put({'type': '_eof'})
        threading.Thread(target=reader, daemon=True).start()
        answer, finish, tool_events, errors = '', None, [], []
        started = time.monotonic()
        try:
            proc.stdin.write(json.dumps({'id': 'tool-turn', 'type': 'prompt', 'message': prompt}) + '\n')
            proc.stdin.flush()
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                try:
                    item = received.get(timeout=deadline-time.monotonic())
                except queue.Empty:
                    errors.append('timeout')
                    break
                kind = item.get('type', '')
                if kind == '_eof':
                    errors.append(f'process exited {proc.poll()}')
                    break
                if 'tool' in kind.lower():
                    tool_events.append(item)
                if kind == 'message_end' and item.get('message', {}).get('role') == 'assistant':
                    message = item['message']
                    answer = ''.join(block.get('text', '') for block in message.get('content', [])
                                     if block.get('type') == 'text')
                    finish = message.get('stopReason')
                if kind == 'agent_settled':
                    break
            else:
                errors.append('timeout')
        finally:
            if proc.poll() is None:
                proc.stdin.close()
                try:
                    proc.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    proc.wait(timeout=5)
    return {'answer': answer, 'finish_reason': finish, 'tool_events': tool_events,
            'errors': errors, 'exit_code': proc.returncode,
            'duration_seconds': round(time.monotonic()-started, 2)}


def run_short_control(out):
    from comparison_short_control import HOME, ROOT, GATEWAY, ROUTE, MODEL, CONTEXT, OUTPUT_CAP, NODE, PI_CLI, OPENCODE, DEEPSEEK_CLI, FIXTURES, SYSTEM, PROMPTS, CURRENT, OLD, roster
    agent = out / 'agent'
    agent.mkdir()
    write_models(agent / 'models.json')
    shutil.copy2(FIXTURES / 'pi_settings.json', agent / 'settings.json')
    (agent / 'auth.json').write_text('{}')
    (agent / 'models-store.json').write_text('{}')
    (out / 'workspace').mkdir()
    env = os.environ.copy()
    env['PI_CODING_AGENT_DIR'] = str(agent)
    cmd = [str(NODE), str(PI_CLI), '--mode', 'rpc', '--no-tools', '--no-extensions',
           '--no-skills', '--no-prompt-templates', '--no-mcp', '--no-context-files',
           '--system-prompt', SYSTEM, '--session-dir', str(out / 'sessions'),
           '--provider', 'rig', '--model', ROUTE]
    rows = []
    with (out / 'events.jsonl').open('w') as event_file, (out / 'stderr.log').open('w') as stderr:
        proc = subprocess.Popen(cmd, cwd=out / 'workspace', env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=stderr, text=True, bufsize=1)
        received = queue.Queue()

        def reader():
            for line in proc.stdout:
                event_file.write(line)
                event_file.flush()
                try:
                    received.put(json.loads(line))
                except json.JSONDecodeError:
                    pass
            received.put({'type': '_eof'})
        threading.Thread(target=reader, daemon=True).start()
        try:
            for index, prompt in enumerate(PROMPTS, 1):
                roster()
                started = time.monotonic()
                proc.stdin.write(json.dumps({'id': f'turn-{index}', 'type': 'prompt', 'message': prompt}) + '\n')
                proc.stdin.flush()
                row = {'turn': index, 'answer': None, 'finish_reason': None, 'errors': [], 'tool_calls': 0}
                deadline = time.monotonic() + 90
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        row['errors'].append('timeout')
                        break
                    try:
                        record = received.get(timeout=remaining)
                    except queue.Empty:
                        row['errors'].append('timeout')
                        break
                    kind = record.get('type')
                    if kind == '_eof':
                        row['errors'].append(f'process exited {proc.poll()}')
                        break
                    if kind and 'tool' in kind.lower():
                        row['tool_calls'] += 1
                    if kind == 'message_end' and record.get('message', {}).get('role') == 'assistant':
                        message = record['message']
                        row['answer'] = ''.join(block.get('text', '') for block in message.get('content', [])
                                             if block.get('type') == 'text')
                        row['finish_reason'] = message.get('stopReason')
                    if kind == 'agent_settled':
                        break
                row['duration_seconds'] = round(time.monotonic()-started, 2)
                rows.append(row)
                (out / 'progress.json').write_text(json.dumps(rows, indent=2))
                print(json.dumps({'candidate': 'pi', 'turn': index, 'finish': row['finish_reason'],
                                  'answer': (row['answer'] or '')[:100], 'errors': row['errors']}), flush=True)
                if row['errors']:
                    break
        finally:
            if proc.poll() is None:
                proc.stdin.close()
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    proc.wait(timeout=5)
    return rows
