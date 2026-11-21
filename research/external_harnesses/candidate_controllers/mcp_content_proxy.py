#!/usr/bin/env python3
"""Stdio MCP proxy that makes structured-only tool results visible as text.

The original structuredContent is preserved. Only successful tools/call results
with no content blocks are augmented, so clients that understand structured
results continue to receive them unchanged.
"""

import json
import subprocess
import sys
import threading


def normalize(message, pending):
    if not isinstance(message, dict) or message.get('id') not in pending:
        return message
    result = message.get('result')
    if not isinstance(result, dict) or result.get('isError') or result.get('content'):
        return message
    structured = result.get('structuredContent')
    if structured is None:
        return message
    result['content'] = [{'type': 'text', 'text': json.dumps(structured, ensure_ascii=False)}]
    return message


def main():
    command = sys.argv[1:]
    if command and command[0] == '--':
        command = command[1:]
    if not command:
        raise SystemExit('usage: mcp_content_proxy.py -- SERVER [ARGS...]')
    child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=sys.stderr, text=True, bufsize=1)
    pending = set()
    lock = threading.Lock()

    def relay_results():
        for line in child.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                sys.stdout.write(line)
                sys.stdout.flush()
                continue
            ident = message.get('id') if isinstance(message, dict) else None
            with lock:
                targeted = ident in pending
                if targeted:
                    pending.discard(ident)
            if targeted:
                message = normalize(message, {ident})
            sys.stdout.write(json.dumps(message, ensure_ascii=False) + '\n')
            sys.stdout.flush()

    reader = threading.Thread(target=relay_results, daemon=True)
    reader.start()
    try:
        for line in sys.stdin:
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                request = None
            if isinstance(request, dict) and request.get('method') == 'tools/call':
                with lock:
                    pending.add(request.get('id'))
            child.stdin.write(line)
            child.stdin.flush()
    finally:
        child.stdin.close()
        reader.join(timeout=5)
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=5)


if __name__ == '__main__':
    main()
