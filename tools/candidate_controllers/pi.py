"""pi native MCP controller; no upstream checkout edits."""
import json
import hashlib
import os
import queue
import shutil
import subprocess
import threading
import time
import comparison_short_control as common
from candidate_controllers.text_tool_bridge import parse_request, call_tool
FIXTURE = common.ROOT / "tools/fixtures/local_mcp_marker.mjs"
CONFIGS = common.ROOT / "tools/comparison_fixtures"
SYSTEM = ("Use only the named local fixture MCP tool. Do not use shell, file, web, "
          "or editing tools. Return only the exact marker from the tool result.")
LOCAL_HELP_SERVERS = {'research_local', 'geometry_local'}


def help_spec_for(server, targets):
    if 'help' in server:
        return server['help']
    if server['name'] in LOCAL_HELP_SERVERS and len(targets) == 1 and targets[0] != 'get_tool_help':
        return {'name': 'get_tool_help', 'arguments': {'tool_name': targets[0]}}
    return None


def write_models(path):
    config = json.loads((CONFIGS / 'pi_models.json').read_text())
    model = config['providers']['rig']['models'][0]
    model['id'] = common.ROUTE
    model['name'] = 'Ready ' + common.MODEL
    model['contextWindow'] = common.CONTEXT
    path.write_text(json.dumps(config, indent=2))

def run_pi(out, prompt, server=None, target=None, system=None):
    target = target or ('read_structured_marker' if 'read_structured_marker' in prompt else 'read_marker')
    targets = list(target) if isinstance(target, (list, tuple)) else [target]
    server = server or {'name': 'fixture', 'command': [str(common.NODE), str(FIXTURE), str(out / 'calls.jsonl')],
                        'tools': ['read_marker', 'read_structured_marker']}
    system = system or SYSTEM
    help_spec = help_spec_for(server, targets)
    if help_spec:
        if not isinstance(help_spec, dict) or not isinstance(help_spec.get('name'), str) \
                or not isinstance(help_spec.get('arguments'), dict):
            raise ValueError('server help must specify a tool name and explicit arguments')
        help_server = {**server, 'tools': list(set(server['tools']) | {help_spec['name']})}
        guidance = call_tool(help_server, help_spec['name'], help_spec['arguments'], timeout=20)
        if guidance.get('isError'):
            raise RuntimeError('configured MCP help tool returned an error')
        (out / 'tool_guidance.json').write_text(json.dumps(guidance, indent=2) + '\n')
        system += ('\nMCP server usage guidance obtained before this turn:\n'
                   + json.dumps(guidance, ensure_ascii=False)[:6000])
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
           '--tools', ','.join('mcp__' + server['name'] + '__' + name for name in targets),
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
        bridge_calls = []
        attempted = set()
        repair_attempted = False
        started = time.monotonic()
        try:
            proc.stdin.write(json.dumps({'id': 'tool-turn', 'type': 'prompt', 'message': prompt}) + '\n')
            proc.stdin.flush()
            deadline = time.monotonic() + 360
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
                    request = parse_request(answer, server, targets) if not tool_events else None
                    if not request:
                        if not tool_events and not bridge_calls and not repair_attempted:
                            repair_attempted = True
                            allowed = ['mcp__' + server['name'] + '__' + name for name in targets]
                            correction = ('No MCP tool call was executed. The user requested a tool result. '
                                          'Do not assume or invent a result. If a tool is needed, reply with '
                                          'exactly one JSON object with keys "name" and "arguments". '
                                          'Use an advertised tool name and its input schema. Allowed names: '
                                          + json.dumps(allowed) + '. No prose or example result.')
                            proc.stdin.write(json.dumps({'id': 'tool-format-repair', 'type': 'prompt',
                                                         'message': correction}) + '\n')
                            proc.stdin.flush()
                            continue
                        break
                    tool, arguments = request
                    fingerprint = json.dumps(request, sort_keys=True)
                    if fingerprint in attempted or len(bridge_calls) >= 2:
                        errors.append('text tool fallback repeated a request or exceeded its call limit')
                        break
                    attempted.add(fingerprint)
                    try:
                        result = call_tool(server, tool, arguments,
                                            timeout=min(180, max(1, deadline-time.monotonic()-10)))
                    except Exception as exc:
                        errors.append(f'text tool fallback: {type(exc).__name__}: {exc}')
                        break
                    bridge_calls.append({'tool': tool,
                                         'argument_keys': sorted(arguments),
                                         'arguments_sha256': hashlib.sha256(json.dumps(
                                             arguments, sort_keys=True).encode()).hexdigest(),
                                         'is_error': bool(result.get('isError'))})
                    feedback = ('MCP tool result for ' + 'mcp__' + server['name'] + '__' + tool + ':\n'
                                + json.dumps(result, ensure_ascii=False) + '\n'
                                + 'Continue the original task using this result. Follow the '
                                  'original user request for the final answer format exactly; '
                                  'do not add explanation unless requested.')
                    proc.stdin.write(json.dumps({'id': f'tool-feedback-{len(bridge_calls)}',
                                                 'type': 'prompt', 'message': feedback}) + '\n')
                    proc.stdin.flush()
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
    (out / 'text_tool_bridge.json').write_text(json.dumps(bridge_calls, indent=2) + '\n')
    return {'answer': answer, 'finish_reason': finish, 'tool_events': tool_events,
            'tool_mode': 'text_bridge' if bridge_calls else ('native' if tool_events else 'none'),
            'bridge_calls': bridge_calls,
            'format_repair_attempted': repair_attempted,
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
