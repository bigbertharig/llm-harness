#!/usr/bin/env python3
"""Six-server, twelve-case ready-only MCP comparison. Raw receipts stay under results/."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import select
import subprocess
import time
import urllib.request

import requests
import comparison_short_control as common
import comparison_tool_use as driver
import comparison_extra_candidates as extra_driver
from candidate_controllers.hermes import run_hermes

ROOT = common.ROOT
MATRIX_SERVER = ROOT / 'tools/fixtures/local_mcp_matrix.mjs'
MARKER_SERVER = ROOT / 'tools/fixtures/local_mcp_marker.mjs'
URLS = {
    'daedalmap': 'https://app.daedalmap.com/mcp/free',
    'deepwiki': 'https://mcp.deepwiki.com/mcp',
    'openai_docs': 'https://developers.openai.com/mcp',
    'cloudflare_docs': 'https://docs.mcp.cloudflare.com/mcp',
    'research_local': 'http://127.0.0.1:17010/mcp/research',
    'geometry_local': 'http://127.0.0.1:17010/mcp/geometry',
}


def candidate_roster(candidate):
    return common.roster_for(candidate)
# Difficulty tags describe the server interface, not candidate quality.
CASES = {
    'marker_text': ('marker', 'read_marker', {}, 'easy', 'text'),
    'marker_structured': ('marker', 'read_structured_marker', {}, 'hard', 'structured-only'),
    'research_packs': ('research_local', 'get_catalog', {'catalog': 'data'}, 'medium', 'text+structured'),
    'research_sources': ('research_local', 'where_is_research_data', {}, 'easy', 'text+structured'),
    'geometry_shape': ('geometry_local', 'get_shape', {'loc_id': 'AUS-ACT-801-01-1001-PLACE-80020', 'include_polygon': False}, 'hard', 'text+structured'),
    'geometry_help': ('geometry_local', 'get_tool_help', {'topic': 'geometry'}, 'medium', 'text+structured'),
    'numeric_sum': ('numeric', 'calculate_sum', {'a': 17, 'b': 28}, 'medium', 'text+structured'),
    'numeric_product': ('numeric', 'calculate_product', {'a': 6, 'b': 7}, 'medium', 'text+structured'),
    'lookup_text': ('lookup', 'get_entry', {'key': 'alpha'}, 'medium', 'text+structured'),
    'lookup_nested': ('lookup', 'get_nested_entry', {'key': 'beta'}, 'hard', 'nested structured-only'),
    'cloudflare_workers': ('cloudflare_docs', 'search_cloudflare_documentation', {'query': 'Workers routes'}, 'medium', 'search text'),
    'cloudflare_durable': ('cloudflare_docs', 'search_cloudflare_documentation', {'query': 'Durable Objects'}, 'medium', 'search text'),
    'cloudflare_workers_any': ('cloudflare_docs', 'search_cloudflare_documentation', {'query': 'Workers routes'}, 'medium', 'large search text'),
    'cloudflare_durable_any': ('cloudflare_docs', 'search_cloudflare_documentation', {'query': 'Durable Objects'}, 'medium', 'large search text'),
    'daedal_family': ('daedalmap', 'get_catalog', {'catalog': 'geometry'}, 'hard', 'structured-only'),
    'daedal_count': ('daedalmap', 'get_catalog', {'catalog': 'geometry'}, 'hard', 'structured-only'),
    'deepwiki_servers': ('deepwiki', 'read_wiki_structure', {'repoName': 'modelcontextprotocol/servers'}, 'medium', 'text+structured'),
    'deepwiki_python': ('deepwiki', 'read_wiki_structure', {'repoName': 'openai/openai-python'}, 'medium', 'text+structured'),
    'openai_streaming': ('openai_docs', 'search_openai_docs', {'query': 'Responses API streaming', 'limit': 1}, 'medium', 'text'),
    'openai_function_calling': ('openai_docs', 'search_openai_docs', {'query': 'function calling tools', 'limit': 1}, 'medium', 'text'),
}


def server_for(case, out):
    name = CASES[case][0]
    if name in URLS:
        return {'name': name, 'url': URLS[name], 'tools': [CASES[case][1]]}
    command = ([str(common.NODE), str(MARKER_SERVER), str(out / 'calls.jsonl')]
               if name == 'marker' else
               [str(common.NODE), str(MATRIX_SERVER), name, str(out / 'calls.jsonl')])
    tools = {'marker': ['read_marker', 'read_structured_marker'],
             'numeric': ['calculate_sum', 'calculate_product'],
             'lookup': ['get_entry', 'get_nested_entry']}[name]
    return {'name': name, 'command': command, 'tools': tools}


def question(case):
    name, tool, args, _, _ = CASES[case]
    if case == 'daedal_family': tail = 'Return only the first family_id in families.'
    elif case == 'daedal_count': tail = 'Return only the number of entries in families.'
    elif name == 'deepwiki': tail = 'Return only the title of section 1 in the returned page outline, without its number.'
    elif name == 'openai_docs': tail = 'Return only the first hit URL.'
    elif case.endswith('_any') and name == 'cloudflare_docs': tail = 'Return only one URL that appears in the search result.'
    elif name == 'cloudflare_docs': tail = 'Return only the URL of the first search result.'
    elif case == 'research_packs': tail = 'Return only the first pack_id in packs.'
    elif case == 'research_sources': tail = 'Return only the source_count.'
    elif case == 'geometry_shape': tail = 'Return only the available count.'
    elif case == 'geometry_help': tail = 'Return only the help_topic.'
    elif name == 'numeric': tail = 'Return only the numeric result.'
    else: tail = 'Return only the receipt marker from the tool result.'
    return (f'Call the {name} MCP tool {tool} exactly once with arguments '
            f'{json.dumps(args, separators=(",", ":"))}. {tail}')


def request_stdio(proc, index, method, params=None):
    message = {'jsonrpc': '2.0', 'id': index, 'method': method}
    if params is not None: message['params'] = params
    proc.stdin.write(json.dumps(message) + '\n'); proc.stdin.flush()
    if not select.select([proc.stdout], [], [], 12)[0]: raise TimeoutError(f'{method} timed out')
    response = json.loads(proc.stdout.readline())
    if response.get('id') != index or 'result' not in response: raise RuntimeError(f'{method} bad response')
    return response['result']


def direct_local(server, tool, args, out):
    proc = subprocess.Popen(server['command'][:-1] + [str(out / 'baseline_calls.jsonl')],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, bufsize=1)
    try:
        init = request_stdio(proc, 1, 'initialize', {'protocolVersion': '2025-06-18',
            'capabilities': {}, 'clientInfo': {'name': 'mcp-matrix', 'version': '1'}})
        proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) + '\n'); proc.stdin.flush()
        listed = request_stdio(proc, 2, 'tools/list')
        result = request_stdio(proc, 3, 'tools/call', {'name': tool, 'arguments': args})
    finally:
        proc.stdin.close()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.terminate(); proc.wait(timeout=5)
    if init.get('protocolVersion') != '2025-06-18' or tool not in [x['name'] for x in listed['tools']] or result.get('isError'):
        raise RuntimeError('local baseline contract failed')
    return {'tools': [x['name'] for x in listed['tools']], 'result': result}


def parse_http(response, method):
    if response.status_code != 200: raise RuntimeError(f'{method} HTTP {response.status_code}: {response.text[:180]}')
    if 'text/event-stream' in response.headers.get('content-type', ''):
        data = [line[5:].strip() for line in response.text.splitlines() if line.startswith('data:')]
        if not data: raise RuntimeError(f'{method} empty SSE')
        packet = json.loads(data[-1])
    else: packet = response.json()
    if packet.get('error') or 'result' not in packet: raise RuntimeError(f'{method} JSON-RPC error: {str(packet)[:180]}')
    return packet['result']


def direct_online(server, tool, args):
    session = requests.Session()
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
               'MCP-Protocol-Version': '2025-06-18'}
    def call(index, method, params=None):
        body = {'jsonrpc': '2.0', 'id': index, 'method': method}
        if params is not None: body['params'] = params
        response = session.post(server['url'], json=body, headers=headers, timeout=30)
        if response.headers.get('mcp-session-id'): headers['Mcp-Session-Id'] = response.headers['mcp-session-id']
        return parse_http(response, method)
    init = call(1, 'initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                 'clientInfo': {'name': 'mcp-matrix', 'version': '1'}})
    session.post(server['url'], json={'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                 headers=headers, timeout=15)
    listed = call(2, 'tools/list')
    result = call(3, 'tools/call', {'name': tool, 'arguments': args})
    return {'protocol': init.get('protocolVersion'), 'tools': [x['name'] for x in listed['tools']], 'result': result}


def expected_value(case, result):
    structured = result.get('structuredContent') or {}
    texts = '\n'.join(x.get('text', '') for x in result.get('content', []) if x.get('type') == 'text')
    if case.startswith('marker_'): return structured.get('marker')
    if case == 'research_packs': return (structured.get('packs') or [{}])[0].get('pack_id')
    if case == 'research_sources': return str(structured.get('source_count')) if structured.get('source_count') is not None else None
    if case == 'geometry_shape': return str(structured.get('available')) if structured.get('available') is not None else None
    if case == 'geometry_help': return structured.get('help_topic')
    if case.startswith('numeric_'): return str(structured.get('value'))
    if case == 'lookup_text': return structured.get('receipt')
    if case == 'lookup_nested': return structured.get('entry', {}).get('receipt')
    if case == 'daedal_family': return structured.get('families', [{}])[0].get('family_id')
    if case == 'daedal_count': return str(len(structured.get('families', [])))
    if case.startswith('deepwiki_'):
        body = texts or str(structured.get('result', ''))
        match = re.search(r'^- 1 (.+?)\s*$', body, re.MULTILINE)
        return match.group(1) if match else None
    if case.startswith('openai_'):
        try:
            body = json.loads(texts)
            if isinstance(body, dict) and body.get('hits'): return body['hits'][0]['url']
        except json.JSONDecodeError: pass
        match = re.search(r'https://[^\s"<>]+', texts)
        return match.group(0).rstrip('.,') if match else None
    if case.startswith('cloudflare_'):
        match = re.search(r'https://[^\s"<>]+', texts or json.dumps(structured))
        return match.group(0).rstrip('.,)') if match else None
    return None


def score(case, server, expected, candidate, out, before, after):
    target = CASES[case][1]
    events = candidate.get('tool_events', [])
    calls, call_args, results = [], [], []
    for event in events:
        part = event.get('part') if isinstance(event.get('part'), dict) else {}
        kind = event.get('type') or part.get('type')
        name = event.get('toolName') or event.get('tool') or part.get('tool') or part.get('name')
        if kind in ('tool_execution_start', 'tool_call') or part.get('type') == 'tool':
            if name:
                calls.append(str(name))
                call_args.append(event.get('args', event.get('input')))
        if kind in ('tool_execution_end', 'tool_result'):
            results.append(event)
        elif kind == 'tool_use' and part.get('state', {}).get('status') == 'completed':
            results.append(event)
    # OpenCode tool parts may include one event per state; retain raw event details in receipt.
    selected = 'mcp__' + server['name'] + '__' + target
    alternate = server['name'] + '_' + target
    nanobot_name = 'mcp_' + server['name'] + '_' + target
    correct_call = len(calls) == 1 and calls[0] in (selected, alternate, nanobot_name)
    if correct_call and isinstance(call_args[0], dict): correct_call &= call_args[0] == CASES[case][2]
    local = 'url' not in server
    if local:
        logged = driver.read_jsonl(out / 'calls.jsonl')
        invoked = [x for x in logged if x.get('method') == 'tools/call']
        correct_call &= len(invoked) == 1 and invoked[0].get('tool') == target
        if invoked and 'arguments' in invoked[0]: correct_call &= invoked[0]['arguments'] == CASES[case][2]
        delivered = [x for x in logged if x.get('method') == 'tool/result']
        if len(delivered) == 1:
            expected = delivered[0].get('marker', delivered[0].get('value'))
    else: logged = []
    payload = {}
    if not local and len(results) == 1:
        event = results[0]
        raw = event.get('result') or (event.get('part') or {}).get('state', {}).get('output')
        if isinstance(raw, dict) and isinstance(raw.get('structuredContent'), dict):
            payload = raw['structuredContent'] if 'content' in raw['structuredContent'] else raw
        elif isinstance(raw, dict): payload = raw
        elif isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                payload = parsed if isinstance(parsed, dict) and ('content' in parsed or 'structuredContent' in parsed) else {'content': [{'type': 'text', 'text': raw}]}
            except json.JSONDecodeError: payload = {'content': [{'type': 'text', 'text': raw}]}
        else: payload = {}
        actual_expected = expected_value(case, payload)
        if actual_expected is not None: expected = actual_expected
    answer = candidate.get('answer', '').strip()
    expected_text = str(expected) if expected is not None else ''
    if expected_text.startswith('https://'):
        answer_values = re.findall(r'https://[^\s"<>]+', answer)
        answer_value_correct = bool(answer_values) and answer_values[0].rstrip('.,)') == expected_text
    elif expected_text.isdigit():
        answer_values = re.findall(r'(?<![A-Za-z0-9])\d+(?![A-Za-z0-9])', answer)
        answer_value_correct = answer_values == [expected_text]
    else:
        answer_value_correct = bool(expected_text) and bool(re.search(
            r'(?<![A-Za-z0-9])' + re.escape(expected_text) + r'(?![A-Za-z0-9])', answer, re.IGNORECASE))
    if case.startswith('marker_'): answer_value_correct = answer == expected_text
    accepted_urls = []
    if case.endswith('_any') and case.startswith('cloudflare_'):
        accepted_urls = sorted(set(x.rstrip('.,)') for x in re.findall(r'https://[^\s"<>]+', json.dumps(payload))))
        answer_urls = re.findall(r'https://[^\s"<>]+', answer)
        answer_value_correct = len(answer_urls) == 1 and answer_urls[0].rstrip('.,)') in accepted_urls
    result_success = len(results) == 1 and not results[0].get('isError') and results[0].get('status') != 'failed'
    checks = {'ready_roster_unchanged': before == after, 'one_target_call': correct_call,
              'tool_result_success': result_success,
              'answer_value_correct': answer_value_correct,
              'natural_finish': candidate.get('finish_reason') in ('stop', 'completed', 'process_exit_0'),
              'clean_exit': candidate.get('exit_code') == 0 and not candidate.get('errors')}
    if local:
        checks['local_discovery'] = any(x.get('method') == 'tools/list' for x in logged)
        checks['one_local_result'] = len([x for x in logged if x.get('method') == 'tool/result']) == 1
    return {'passed': all(checks.values()), 'checks': checks, 'answer': answer, 'expected': expected,
            'format_exact': answer == expected_text,
            'accepted_url_count': len(accepted_urls),
            'event_calls': calls, 'event_call_args': call_args, 'event_results': len(results), 'local_events': len(logged)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('candidate', choices=['baseline', 'pi', 'opencode', 'deepseek', 'codex', 'nanobot', 'hermes'])
    parser.add_argument('case', choices=sorted(CASES))
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    case = args.case
    name, tool, arguments, difficulty, shape = CASES[case]
    out = ROOT / 'results' / args.run_id / args.candidate / case
    out.mkdir(parents=True, exist_ok=False)
    (out / 'workspace').mkdir()
    server = server_for(case, out)
    fixture = {'version': 'mcp-matrix-v1', 'case': case, 'server': name, 'tool': tool,
               'arguments': arguments, 'difficulty': difficulty, 'result_shape': shape,
               'prompt': question(case), 'route': common.route_spec(args.candidate)[0],
               'model': common.route_spec(args.candidate)[1],
               'context': common.route_spec(args.candidate)[2],
               'declared_output_cap': None if args.candidate == 'hermes' else common.OUTPUT_CAP,
               'server_url': server.get('url')}
    (out / 'fixture.json').write_text(json.dumps(fixture, indent=2))
    before = None if args.candidate == 'baseline' else candidate_roster(args.candidate)
    if before is not None: (out / 'ready_before.json').write_text(json.dumps(before, indent=2))
    started = time.monotonic()
    error = None; candidate_result = None; baseline = None; expected = None; baseline_calls_bytes = None
    try:
        baseline = direct_online(server, tool, arguments) if 'url' in server else direct_local(server, tool, arguments, out)
        # Keep the direct answer and call log out of a candidate's readable
        # workspace until its process exits. Codex can otherwise find them
        # with its built-in shell tool despite a prompt forbidding that path.
        baseline_calls_path = out / 'baseline_calls.jsonl'
        if baseline_calls_path.exists():
            baseline_calls_bytes = baseline_calls_path.read_bytes()
            baseline_calls_path.unlink()
        if tool not in baseline['tools'] or baseline['result'].get('isError'):
            raise RuntimeError('direct baseline tool missing or returned isError')
        expected = expected_value(case, baseline['result'])
        if expected is None: raise RuntimeError('baseline answer extractor found no value')
        if args.candidate != 'baseline':
            system = ('Use only the named MCP server and tool. Do not use shell, file, web, or editing tools. '
                      'Call the tool exactly once and return only the requested value from its result.')
            candidate_result = {'pi': driver.run_pi, 'opencode': driver.run_opencode,
                                'deepseek': driver.run_deepseek, 'codex': extra_driver.run_codex,
                                'nanobot': extra_driver.run_nanobot, 'hermes': run_hermes}[args.candidate](
                                    out, question(case), server=server, target=tool, system=system)
    except Exception as exc: error = f'{type(exc).__name__}: {exc}'
    if baseline is not None:
        (out / 'baseline.json').write_text(json.dumps(baseline, indent=2))
    if baseline_calls_bytes is not None:
        (out / 'baseline_calls.jsonl').write_bytes(baseline_calls_bytes)
    after = None
    if args.candidate != 'baseline':
        try: after = candidate_roster(args.candidate)
        except Exception as exc: error = (error + '; ' if error else '') + f'post-roster {exc}'
        (out / 'ready_after.json').write_text(json.dumps(after, indent=2))
    verdict = ({'passed': bool(expected), 'checks': {'direct_contract': bool(expected)}, 'expected': expected}
               if args.candidate == 'baseline' else
               score(case, server, expected, candidate_result, out, before, after) if candidate_result else
               {'passed': False, 'checks': {'candidate_started': False}})
    if error: verdict['passed'] = False
    summary = {'run_id': args.run_id, 'candidate': args.candidate, 'case': case, 'server': name,
               'difficulty': difficulty, 'result_shape': shape, 'fixture_sha256': hashlib.sha256(json.dumps(fixture, sort_keys=True).encode()).hexdigest(),
               'driver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'baseline': {'tools': baseline['tools'], 'expected': expected} if baseline else None,
               'candidate_result': candidate_result, 'verdict': verdict, 'error': error,
               'duration_seconds': round(time.monotonic()-started, 2)}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2))
    print('SUMMARY ' + json.dumps({k: v for k, v in summary.items() if k != 'candidate_result'}), flush=True)
    raise SystemExit(0 if verdict['passed'] else 1)


if __name__ == '__main__': main()
