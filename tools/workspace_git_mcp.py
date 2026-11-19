#!/usr/bin/env python3
"""Bounded, read-only Git inspection for one selected Coding workspace."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


TOOLS = [
    {'name': 'get_workspace_git_status', 'description': 'Summarize tracked and untracked changes in the selected workspace.',
     'annotations': {'readOnlyHint': True}, 'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}},
    {'name': 'get_workspace_git_log', 'description': 'Show recent commit subjects in the selected workspace.',
     'annotations': {'readOnlyHint': True}, 'inputSchema': {'type': 'object', 'properties': {
         'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20}}, 'additionalProperties': False}},
    {'name': 'get_workspace_git_diff', 'description': 'Read a bounded diff for one visible tracked file in the selected workspace.',
     'annotations': {'readOnlyHint': True}, 'inputSchema': {'type': 'object', 'properties': {
         'path': {'type': 'string', 'minLength': 1, 'maxLength': 300},
         'staged': {'type': 'boolean'}}, 'required': ['path'], 'additionalProperties': False}},
]


def _run(root: Path, args: list[str], *, limit: int = 12000) -> dict:
    command = ['git', '--no-pager', '-c', 'core.quotePath=false', '-c', 'core.fsmonitor=false', '-c', 'diff.external=',
               '-c', 'core.pager=cat', '-C', str(root), *args]
    try:
        env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        env['GIT_OPTIONAL_LOCKS'] = '0'
        proc = subprocess.run(command, capture_output=True, text=True, timeout=8,
                              encoding='utf-8', errors='replace', env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('Git inspection is unavailable') from exc
    if proc.returncode:
        raise ValueError('Git inspection failed: ' + proc.stderr[:300].strip())
    output = proc.stdout
    return {'output': output[:limit], 'truncated': len(output) > limit}


def _visible_path(raw: str) -> str:
    if not isinstance(raw, str) or not 1 <= len(raw) <= 300 or '\\' in raw:
        raise ValueError('invalid workspace path')
    path = Path(raw)
    if path.is_absolute() or any(part in ('', '..') or part.startswith('.') for part in path.parts):
        raise ValueError('workspace path is not visible')
    return path.as_posix()


def call(root: Path, name: str, args: dict) -> dict:
    if not isinstance(args, dict):
        raise ValueError('invalid Git tool arguments')
    root = root.resolve(strict=True)
    top = _run(root, ['rev-parse', '--show-toplevel'], limit=200)['output'].strip()
    if Path(top).resolve() != root:
        raise ValueError('selected workspace must be a Git repository root')
    if name == 'get_workspace_git_status':
        if args:
            raise ValueError('status accepts no arguments')
        return _run(root, ['status', '--short', '--untracked-files=normal'], limit=6000)
    if name == 'get_workspace_git_log':
        if set(args) - {'limit'} or type(args.get('limit', 8)) is not int or not 1 <= args.get('limit', 8) <= 20:
            raise ValueError('limit must be 1–20')
        return _run(root, ['log', f'-{args.get("limit", 8)}', '--format=%h %s'], limit=4000)
    if name == 'get_workspace_git_diff':
        if set(args) - {'path', 'staged'} or type(args.get('staged', False)) is not bool:
            raise ValueError('diff requires path and optional staged flag')
        path = _visible_path(args.get('path'))
        tracked = _run(root, ['ls-files', '--error-unmatch', '--', path], limit=500)['output'].strip()
        if tracked != path:
            raise ValueError('diff requires one visible tracked file')
        return {'path': path, **_run(root, ['diff', '--no-ext-diff', '--no-textconv', '--unified=3',
                                             *(['--cached'] if args.get('staged', False) else []),
                                             '--', path])}
    raise ValueError('unknown Git tool')


def handle(root: Path, packet: dict) -> dict | None:
    ident = packet.get('id')
    if ident is None:
        return None
    method = packet.get('method')
    if method == 'initialize':
        result = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}},
                  'serverInfo': {'name': 'workspace-git', 'version': '0.1.0'}}
    elif method == 'tools/list':
        result = {'tools': TOOLS}
    elif method == 'ping':
        result = {}
    elif method == 'tools/call':
        params = packet.get('params') or {}
        try:
            data = call(root, params.get('name'), params.get('arguments') or {})
            result = {'content': [{'type': 'text', 'text': json.dumps(data)}],
                      'structuredContent': data, 'isError': False}
        except (ValueError, OSError) as exc:
            result = {'content': [{'type': 'text', 'text': str(exc)}], 'isError': True}
    else:
        return {'jsonrpc': '2.0', 'id': ident, 'error': {'code': -32601, 'message': 'Method not found'}}
    return {'jsonrpc': '2.0', 'id': ident, 'result': result}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    root = parser.parse_args().root.resolve(strict=True)
    for line in sys.stdin:
        try:
            packet = json.loads(line)
            if isinstance(packet, dict):
                response = handle(root, packet)
                if response is not None:
                    print(json.dumps(response), flush=True)
        except ValueError:
            continue


if __name__ == '__main__':
    main()
