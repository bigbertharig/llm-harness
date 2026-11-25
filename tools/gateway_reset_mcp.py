#!/usr/bin/env python3
"""MCP wrapper for Gateway's authenticated restart operation."""
import argparse
import json
import os
import sys
from urllib.request import Request, urlopen


def schedule(args, arguments):
    if arguments.get('confirmation') not in ('restart gateway', 'restart pi-gateway'):
        raise ValueError('confirmation must be exactly "restart pi-gateway"')
    token = os.environ.get('LLM_GATEWAY_API_KEY')
    if not token:
        raise ValueError('LLM_GATEWAY_API_KEY is required for restart operations')
    if not isinstance(arguments.get('request_id'), str) or not arguments['request_id']:
        raise ValueError('request_id is required; reuse it to reconcile an interrupted call')
    packet = {'schema': 'gateway-reset/1', 'request_id': arguments['request_id'],
              'conversation_id': args.conversation_id,
              'confirmation': arguments.get('confirmation'), 'recovery_note': arguments.get('recovery_note')}
    request = Request(args.gateway.rstrip('/') + '/v1/operations/restart',
                      data=json.dumps(packet).encode(), method='POST',
                      headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
    with urlopen(request, timeout=20) as response:
        value = json.load(response)
    if not isinstance(value, dict) or value.get('schema') != 'gateway-reset/1':
        raise ValueError('unsupported Gateway reset receipt')
    return value


def serve(args) -> int:
    tool = {"name": "restart_gateway_and_resume",
        "description": ("Restart the configured Gateway service and automatically continue this saved Codex conversation. "
                        "Use only when the user explicitly asks for a gateway restart. The request is durable "
                        "and recovery runs outside the service being restarted."),
        "inputSchema": {"type": "object", "properties": {
            "confirmation": {"type": "string", "enum": ["restart gateway", "restart pi-gateway"]},
            "recovery_note": {"type": "string", "minLength": 1, "maxLength": 1000},
            "request_id": {"type": "string", "pattern": "^[A-Za-z0-9]{1,64}$", "description": "Reuse the same ID when reconciling an interrupted request."}},
            "required": ["confirmation", "recovery_note", "request_id"], "additionalProperties": False}}
    for line in sys.stdin:
        try:
            packet = json.loads(line)
            request_id, method = packet.get("id"), packet.get("method")
            if request_id is None:
                continue
            if method == "initialize":
                result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "gateway-reset", "version": "0.1.0"}}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": [tool]}
            elif method == "tools/call" and (packet.get("params") or {}).get("name") == tool["name"]:
                try:
                    value = schedule(args, (packet.get("params") or {}).get("arguments") or {})
                    result = {"content": [{"type": "text", "text": json.dumps(value)}],
                              "structuredContent": value}
                except Exception as exc:
                    result = {"isError": True, "content": [{"type": "text",
                              "text": f"{type(exc).__name__}: {exc}"}]}
            else:
                result = {"isError": True, "content": [{"type": "text", "text": "unsupported request"}]}
            print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}), flush=True)
        except (ValueError, TypeError):
            continue
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--conversation-id', required=True)
    parser.add_argument('--gateway', default=os.getenv('LLM_GATEWAY_URL', 'http://127.0.0.1:8080'))
    return serve(parser.parse_args())

if __name__ == '__main__':
    raise SystemExit(main())
