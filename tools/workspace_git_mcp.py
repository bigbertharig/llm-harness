#!/usr/bin/env python3
"""Bounded, read-only Git inspection for one selected Coding workspace."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


REVISION = re.compile(r'^(?:HEAD|[0-9a-fA-F]{7,40})$')
MAX_FILE_BYTES = 1_000_000


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
    {'name': 'get_workspace_git_commit', 'description': 'Inspect one local commit by HEAD or a 7–40 character hexadecimal commit ID.',
     'annotations': {'readOnlyHint': True}, 'inputSchema': {'type': 'object', 'properties': {
         'revision': {'type': 'string', 'minLength': 4, 'maxLength': 40}},
         'additionalProperties': False}},
    {'name': 'compare_workspace_git_revisions', 'description': 'Compare two resolved local commits. Without path, return bounded changed paths; with path, return that file diff.',
     'annotations': {'readOnlyHint': True}, 'inputSchema': {'type': 'object', 'properties': {
         'base': {'type': 'string', 'minLength': 4, 'maxLength': 40},
         'head': {'type': 'string', 'minLength': 4, 'maxLength': 40},
         'path': {'type': 'string', 'minLength': 1, 'maxLength': 300}},
         'required': ['base', 'head'], 'additionalProperties': False}},
    {'name': 'read_workspace_file_at_revision', 'description': 'Read a bounded UTF-8 line range from one visible file at a resolved local commit without checkout.',
     'annotations': {'readOnlyHint': True}, 'inputSchema': {'type': 'object', 'properties': {
         'revision': {'type': 'string', 'minLength': 4, 'maxLength': 40},
         'path': {'type': 'string', 'minLength': 1, 'maxLength': 300},
         'start_line': {'type': 'integer', 'minimum': 1, 'maximum': 50000},
         'max_lines': {'type': 'integer', 'minimum': 1, 'maximum': 300}},
         'required': ['revision', 'path'], 'additionalProperties': False}},
    {'name': 'get_workspace_file_history', 'description': 'List bounded commits that changed one visible local file.',
     'annotations': {'readOnlyHint': True}, 'inputSchema': {'type': 'object', 'properties': {
         'path': {'type': 'string', 'minLength': 1, 'maxLength': 300},
         'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20}},
         'required': ['path'], 'additionalProperties': False}},
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


def _run_raw(root: Path, args: list[str], *, limit: int) -> bytes:
    command = ['git', '--no-pager', '-c', 'core.quotePath=false', '-c', 'core.fsmonitor=false',
               '-c', 'diff.external=', '-c', 'core.pager=cat', '-C', str(root), *args]
    try:
        env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        env['GIT_OPTIONAL_LOCKS'] = '0'
        proc = subprocess.run(command, capture_output=True, timeout=8, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('Git inspection is unavailable') from exc
    if proc.returncode:
        raise ValueError('Git inspection failed: ' + proc.stderr[:300].decode('utf-8', 'replace').strip())
    if len(proc.stdout) > limit:
        raise ValueError('historical file is too large to inspect safely')
    return proc.stdout


def _visible_path(raw: str) -> str:
    if not isinstance(raw, str) or not 1 <= len(raw) <= 300 or '\\' in raw:
        raise ValueError('invalid workspace path')
    path = Path(raw)
    if path.is_absolute() or any(part in ('', '..') or part.startswith('.') for part in path.parts):
        raise ValueError('workspace path is not visible')
    return path.as_posix()


def _revision(root: Path, raw: str) -> str:
    if not isinstance(raw, str) or not REVISION.fullmatch(raw):
        raise ValueError('revision must be HEAD or a 7–40 character hexadecimal commit ID')
    resolved = _run(root, ['rev-parse', '--verify', '--end-of-options', raw + '^{commit}'],
                    limit=100)['output'].strip().lower()
    if not re.fullmatch(r'[0-9a-f]{40}', resolved):
        raise ValueError('revision did not resolve to one commit')
    return resolved


def _line_range(root: Path, revision: str, path: str, start: int, count: int) -> dict:
    object_name = revision + ':' + path
    size_text = _run(root, ['cat-file', '-s', object_name], limit=40)['output'].strip()
    if not size_text.isdigit() or int(size_text) > MAX_FILE_BYTES:
        raise ValueError('historical file is too large to inspect safely')
    raw = _run_raw(root, ['cat-file', 'blob', object_name], limit=MAX_FILE_BYTES)
    try:
        content = raw.decode('utf-8')
    except UnicodeError as exc:
        raise ValueError('historical file is not UTF-8 text') from exc
    if '\x00' in content:
        raise ValueError('historical file is not UTF-8 text')
    lines = content.splitlines(keepends=True)
    selected = ''.join(lines[start - 1:start - 1 + count])
    return {'path': path, 'revision': revision, 'start_line': start,
            'end_line': min(len(lines), start + count - 1), 'total_lines': len(lines),
            'content': selected[:12000],
            'truncated': len(selected) > 12000 or start - 1 + count < len(lines)}


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
        return _run(root, ['log', f'-{args.get("limit", 8)}', '--format=%H %s'], limit=5000)
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
    if name == 'get_workspace_git_commit':
        if set(args) - {'revision'}:
            raise ValueError('commit accepts only revision')
        revision = _revision(root, args.get('revision', 'HEAD'))
        metadata = _run(root, ['show', '-s', '--format=%H%x09%P%x09%an%x09%aI%x09%s', revision],
                        limit=5000)['output'].rstrip('\n').split('\t', 4)
        changes = _run(root, ['diff-tree', '--no-commit-id', '--name-status', '-r', '-M',
                              '--root', revision], limit=12000)
        rows = [line for line in changes['output'].splitlines() if line]
        return {'revision': metadata[0], 'parents': metadata[1].split() if metadata[1] else [],
                'author': metadata[2], 'authored_at': metadata[3], 'subject': metadata[4],
                'changes': rows[:200], 'truncated': changes['truncated'] or len(rows) > 200}
    if name == 'compare_workspace_git_revisions':
        if set(args) - {'base', 'head', 'path'}:
            raise ValueError('compare accepts base, head, and optional path')
        base, head = _revision(root, args.get('base')), _revision(root, args.get('head'))
        if 'path' in args:
            path = _visible_path(args['path'])
            result = _run(root, ['diff', '--no-ext-diff', '--no-textconv', '--unified=3',
                                 base, head, '--', path], limit=12000)
            return {'base': base, 'head': head, 'path': path, **result}
        result = _run(root, ['diff', '--name-status', '-M', base, head], limit=12000)
        rows = [line for line in result['output'].splitlines() if line]
        return {'base': base, 'head': head, 'changes': rows[:200],
                'truncated': result['truncated'] or len(rows) > 200}
    if name == 'read_workspace_file_at_revision':
        if set(args) - {'revision', 'path', 'start_line', 'max_lines'}:
            raise ValueError('historical read accepts revision, path, start_line, and max_lines')
        revision, path = _revision(root, args.get('revision')), _visible_path(args.get('path'))
        start, count = args.get('start_line', 1), args.get('max_lines', 160)
        if type(start) is not int or not 1 <= start <= 50000 or type(count) is not int or not 1 <= count <= 300:
            raise ValueError('invalid historical line range')
        return _line_range(root, revision, path, start, count)
    if name == 'get_workspace_file_history':
        if set(args) - {'path', 'limit'}:
            raise ValueError('history accepts path and optional limit')
        path, limit = _visible_path(args.get('path')), args.get('limit', 8)
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError('limit must be 1–20')
        result = _run(root, ['log', '--follow', f'-{limit}', '--format=%H%x09%aI%x09%s',
                             '--', path], limit=8000)
        commits = []
        for line in result['output'].splitlines():
            fields = line.split('\t', 2)
            if len(fields) == 3:
                commits.append({'revision': fields[0], 'authored_at': fields[1], 'subject': fields[2]})
        return {'path': path, 'commits': commits, 'truncated': result['truncated']}
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
