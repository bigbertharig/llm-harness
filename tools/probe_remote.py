import json
import requests
import sys

url = sys.argv[1]
headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
           'MCP-Protocol-Version': '2025-06-18'}
session = requests.Session()
for index, method, params in [(1, 'initialize', {'protocolVersion': '2025-06-18',
        'capabilities': {}, 'clientInfo': {'name': 'mcp-matrix-probe', 'version': '1'}}),
        (2, 'tools/list', None)]:
    body = {'jsonrpc': '2.0', 'id': index, 'method': method}
    if params is not None: body['params'] = params
    response = session.post(url, json=body, headers=headers, timeout=20)
    if response.headers.get('mcp-session-id'): headers['Mcp-Session-Id'] = response.headers['mcp-session-id']
    print(method, response.status_code, response.headers.get('content-type'), response.text[:300] if response.status_code != 200 else '')
    if response.status_code != 200: break
    if 'text/event-stream' in response.headers.get('content-type', ''):
        data = [line[5:].strip() for line in response.text.splitlines() if line.startswith('data:')]
        packet = json.loads(data[-1])
    else: packet = response.json()
    if method == 'tools/list':
        for tool in packet.get('result', {}).get('tools', []):
            print(tool.get('name'), json.dumps(tool.get('inputSchema', {}))[:250])
