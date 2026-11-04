#!/usr/bin/env python3
"""Live web-search MCP using llm_orchestration's current CPU search helper."""

import json
from pathlib import Path
import sys
import time

LIB = Path('/home/bryan/llm_orchestration/shared/plans/shoulders/research_assistant/scripts/lib')
sys.path.insert(0, str(LIB))
from web_common import ddg_search  # noqa: E402

receipt = Path(sys.argv[1])


def write(entry):
    with receipt.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps({'at_unix': time.time(), **entry}) + '\n')


def respond(index, result=None, error=None):
    packet = {'jsonrpc': '2.0', 'id': index}
    packet['error' if error else 'result'] = error or result
    sys.stdout.write(json.dumps(packet) + '\n')
    sys.stdout.flush()


TOOLS = [{'name': 'search_web',
          'description': 'Search the current web and return up to max_results URLs with titles and snippets. Use exact query and max_results arguments.',
          'inputSchema': {'type': 'object', 'properties': {
              'query': {'type': 'string', 'minLength': 3},
              'max_results': {'type': 'integer', 'minimum': 1, 'maximum': 10}},
              'required': ['query', 'max_results'], 'additionalProperties': False}}]


for line in sys.stdin:
    if not line.strip():
        continue
    try:
        message = json.loads(line)
        method = message.get('method')
        index = message.get('id')
        params = message.get('params') or {}
        if method == 'notifications/initialized':
            write({'method': method})
            continue
        write({'method': method, **({'tool': params.get('name'), 'arguments': params.get('arguments')}
                                  if method == 'tools/call' else {})})
        if index is None:
            continue
        if method == 'initialize':
            respond(index, {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {'listChanged': False}},
                            'serverInfo': {'name': 'harness-web-search', 'version': '1.0.0'}})
        elif method == 'tools/list':
            respond(index, {'tools': TOOLS})
        elif method == 'ping':
            respond(index, {})
        elif method == 'tools/call':
            args = params.get('arguments') or {}
            if params.get('name') != 'search_web' or not isinstance(args.get('query'), str) or not isinstance(args.get('max_results'), int) or not 1 <= args['max_results'] <= 10:
                respond(index, {'isError': True, 'content': [{'type': 'text', 'text': 'invalid search_web arguments'}]})
                continue
            started = time.monotonic()
            logs = []
            try:
                raw = ddg_search(args['query'], max_results=args['max_results'],
                                 rate_limit_seconds=0, timeout_seconds=20, log=logs.append)
                results = [{'url': x.get('href') or x.get('url'), 'title': x.get('title', ''),
                            'snippet': x.get('body') or x.get('content', '')} for x in raw]
                results = [x for x in results if x['url']]
                unique_urls = list(dict.fromkeys(x['url'] for x in results))
                elapsed = round(time.monotonic()-started, 3)
                signal = any('429' in x or 'rate limit' in x.lower() or 'thrott' in x.lower() for x in logs)
                data = {'query': args['query'], 'results': results, 'unique_urls': unique_urls,
                        'result_count': len(results), 'unique_url_count': len(unique_urls),
                        'backend_latency_seconds': elapsed, 'rate_limit_signal': signal}
                write({'method': 'tool/result', 'tool': 'search_web', 'arguments': args,
                       'result_count': len(results), 'unique_url_count': len(unique_urls),
                       'urls': unique_urls, 'backend_latency_seconds': elapsed,
                       'rate_limit_signal': signal, 'logs': logs[-5:]})
                respond(index, {'isError': not bool(results),
                                'content': [{'type': 'text', 'text': json.dumps(data)}],
                                'structuredContent': data})
            except Exception as exc:
                write({'method': 'tool/result', 'tool': 'search_web', 'arguments': args,
                       'error': type(exc).__name__ + ': ' + str(exc)})
                respond(index, {'isError': True, 'content': [{'type': 'text', 'text': type(exc).__name__ + ': ' + str(exc)}]})
        else:
            respond(index, error={'code': -32601, 'message': 'Method not found'})
    except Exception as exc:
        print(type(exc).__name__ + ': ' + str(exc), file=sys.stderr, flush=True)
