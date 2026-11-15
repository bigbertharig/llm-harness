#!/usr/bin/env python3
"""Two-tool MCP fixture: search result -> real CPU scraper -> page-only answer."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from web_research_control import FACT, QUERY, Fixture

SCRAPER = Path('/home/bryan/llm_orchestration/shared/plans/shoulders/research_assistant/scripts/scrape_pages.py')
TOOLS = [
    {'name': 'search_fixture_web', 'description': 'Find a relevant page. Snippets omit the answer; fetch the page to answer.',
     'inputSchema': {'type': 'object', 'properties': {'query': {'type': 'string'}},
                     'required': ['query'], 'additionalProperties': False}},
    {'name': 'fetch_fixture_page', 'description': 'Fetch and extract the text of a URL returned by search_fixture_web using the CPU scraper.',
     'inputSchema': {'type': 'object', 'properties': {'url': {'type': 'string'}},
                     'required': ['url'], 'additionalProperties': False}},
]

def reply_data(data, error=False):
    return {'isError': error, 'content': [{'type': 'text', 'text': json.dumps(data)}],
            'structuredContent': data}

def main():
    receipt = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    http = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
    Thread(target=http.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{http.server_port}'
    approved = base + '/article/archive'

    def log(entry):
        if receipt:
            with receipt.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({'at_unix': time.time(), **entry}) + '\n')

    try:
        for line in sys.stdin:
            message = None
            try:
                message = json.loads(line)
                if not isinstance(message, dict) or 'id' not in message:
                    continue
                method = message.get('method')
                if method == 'initialize':
                    result = {'protocolVersion': '2025-06-18',
                              'capabilities': {'tools': {'listChanged': False}},
                              'serverInfo': {'name': 'rig_search-test-profile', 'version': '1'}}
                elif method == 'tools/list':
                    result = {'tools': TOOLS}
                elif method == 'tools/call':
                    params = message.get('params') or {}
                    name, args = params.get('name'), params.get('arguments')
                    log({'method': 'tools/call', 'tool': name, 'arguments': args})
                    if name == 'search_fixture_web' and args == {'query': QUERY}:
                        with urlopen(base + '/search?q=archive%20beacon%20cadence&format=json', timeout=5) as response:
                            packet = json.load(response)
                        data = {'results': [{'url': item['url'], 'title': item['title'],
                                             'snippet': item['content']} for item in packet['results']],
                                'result_count': len(packet['results'])}
                        result = reply_data(data)
                    elif name == 'fetch_fixture_page' and args == {'url': approved}:
                        with tempfile.TemporaryDirectory(prefix='web_research_mcp_') as temp:
                            batch = Path(temp)
                            target = batch / 'results'
                            target.mkdir()
                            (target / 'approved_urls.json').write_text(json.dumps({'items': [{'id': 'source_1', 'url': approved}]}))
                            proc = subprocess.run([sys.executable, str(SCRAPER), '--batch-id', 'fixture',
                                '--batch-path', str(batch), '--rate-limit', '0', '--timeout', '5'],
                                capture_output=True, text=True, timeout=30)
                            scraped_file = target / 'source_1' / 'scraped.json'
                            scraped = json.loads(scraped_file.read_text()) if scraped_file.exists() else {}
                        data = {'url': approved, 'page_text': scraped.get('page_text', ''),
                                'fetch_status': scraped.get('fetch_status', 'failed'),
                                'cpu_scraper_exit_code': proc.returncode}
                        result = reply_data(data, proc.returncode != 0 or data['fetch_status'] != 'ok')
                    else:
                        result = reply_data({'error': 'invalid tool arguments or URL'}, True)
                    log({'method': 'tool/result', 'tool': name, 'data': result.get('structuredContent'),
                         'isError': result.get('isError')})
                elif method == 'ping':
                    result = {}
                else:
                    print(json.dumps({'jsonrpc': '2.0', 'id': message['id'],
                                      'error': {'code': -32601, 'message': 'Method not found'}}), flush=True)
                    continue
                print(json.dumps({'jsonrpc': '2.0', 'id': message['id'], 'result': result}), flush=True)
            except Exception as exc:
                print(json.dumps({'jsonrpc': '2.0', 'id': message.get('id') if isinstance(message, dict) else None,
                                  'error': {'code': -32603, 'message': type(exc).__name__}}), flush=True)
    finally:
        http.shutdown()

if __name__ == '__main__':
    main()
