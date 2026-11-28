"""Workspace-bound coding MCP tools with versioned edits and configured checks."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from uuid import uuid4
from workspace_read_mcp import TOOLS as READ_TOOLS, call as read_call, _visible_parts

EDIT_TOOLS = [
    {'name': 'replace_workspace_text',
     'description': 'Replace one exact occurrence in a UTF-8 workspace file after checking its SHA-256.',
     'inputSchema': {'type': 'object', 'properties': {
         'path': {'type': 'string', 'minLength': 1, 'maxLength': 300},
         'expected_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
         'old_text': {'type': 'string', 'minLength': 1, 'maxLength': 20000},
         'new_text': {'type': 'string', 'maxLength': 20000}},
         'required': ['path', 'expected_sha256', 'old_text', 'new_text'],
         'additionalProperties': False}},
    {'name': 'write_workspace_file',
     'description': 'Create or replace a UTF-8 workspace file. Pass the old SHA-256 to replace; pass null only to create.',
     'inputSchema': {'type': 'object', 'properties': {
         'path': {'type': 'string', 'minLength': 1, 'maxLength': 300},
         'expected_sha256': {'type': ['string', 'null'], 'pattern': '^[0-9a-f]{64}$'},
         'content': {'type': 'string', 'maxLength': 100000}},
         'required': ['path', 'expected_sha256', 'content'],
         'additionalProperties': False}},
    {'name': 'run_workspace_check',
     'description': 'Run one operator-configured check in the selected workspace by name.',
     'inputSchema': {'type': 'object', 'properties': {
         'name': {'type': 'string', 'minLength': 1, 'maxLength': 60}},
         'required': ['name'], 'additionalProperties': False}},
]
TOOLS = READ_TOOLS + EDIT_TOOLS


def parent_fd(root, raw):
    parts = _visible_parts(raw)
    if not parts:
        raise ValueError('a file path is required')
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd, parts[-1]
    except BaseException:
        os.close(fd)
        raise


def old_content(fd, name):
    try:
        target = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(target)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1_000_000:
            raise ValueError('workspace file is unavailable or too large')
        with os.fdopen(target, 'rb', closefd=False) as stream:
            return stream.read(1_000_001)
    finally:
        os.close(target)


def write_file(root, raw, expected, content):
    if not isinstance(content, str) or len(content) > 100000:
        raise ValueError('invalid UTF-8 content')
    if expected is not None and (not isinstance(expected, str) or
                                 re.fullmatch(r'[0-9a-f]{64}', expected) is None):
        raise ValueError('invalid expected hash')
    data = content.encode('utf-8')
    fd, name = parent_fd(root, raw)
    temp = '.harness-' + uuid4().hex
    try:
        prior = old_content(fd, name)
        if (prior is None) != (expected is None):
            raise ValueError('file existence changed; inspect and retry')
        if prior is not None and hashlib.sha256(prior).hexdigest() != expected:
            raise ValueError('file changed; inspect and retry')
        target = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        try:
            with os.fdopen(target, 'wb', closefd=False) as stream:
                stream.write(data)
                stream.flush()
                os.fsync(target)
        finally:
            os.close(target)
        # Recheck immediately before replace; another writer may have changed the file.
        if old_content(fd, name) != prior:
            raise ValueError('file changed while writing; inspect and retry')
        os.replace(temp, name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
        return {'path': raw, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
    finally:
        try:
            os.unlink(temp, dir_fd=fd)
        except FileNotFoundError:
            pass
        os.close(fd)


def call(root, checks, name, args):
    if name in {item['name'] for item in READ_TOOLS}:
        return read_call(root, name, args)
    if not isinstance(args, dict):
        raise ValueError('invalid arguments')
    if name == 'write_workspace_file':
        if set(args) != {'path', 'expected_sha256', 'content'}:
            raise ValueError('invalid write arguments')
        return write_file(root, args['path'], args['expected_sha256'], args['content'])
    if name == 'replace_workspace_text':
        if set(args) != {'path', 'expected_sha256', 'old_text', 'new_text'}:
            raise ValueError('invalid replace arguments')
        fd, filename = parent_fd(root, args['path'])
        try:
            original = old_content(fd, filename)
        finally:
            os.close(fd)
        if original is None:
            raise ValueError('file is unavailable')
        if hashlib.sha256(original).hexdigest() != args['expected_sha256']:
            raise ValueError('file changed; inspect and retry')
        text = original.decode('utf-8')
        old = args['old_text']
        if not isinstance(old, str) or not old or text.count(old) != 1:
            raise ValueError('old text must occur exactly once')
        return write_file(root, args['path'], args['expected_sha256'],
                          text.replace(old, args['new_text'], 1))
    if name == 'run_workspace_check':
        if set(args) != {'name'} or args['name'] not in checks:
            raise ValueError('check is not configured')
        clean_env = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG', 'VIRTUAL_ENV')
                     if key in os.environ}
        result = subprocess.run(checks[args['name']], cwd=root, env=clean_env,
                                shell=False, capture_output=True, text=True,
                                errors='replace', timeout=120, check=False)
        return {'name': args['name'], 'exit_code': result.returncode,
                'stdout': result.stdout[-12000:], 'stderr': result.stderr[-4000:]}
    raise ValueError('unknown workspace coding tool')


def handle(root, checks, packet):
    ident = packet.get('id')
    if ident is None:
        return None
    method = packet.get('method')
    if method == 'initialize':
        result = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}},
                  'serverInfo': {'name': 'workspace-coding', 'version': '0.1.0'}}
    elif method == 'tools/list':
        result = {'tools': TOOLS}
    elif method == 'ping':
        result = {}
    elif method == 'tools/call':
        params = packet.get('params') or {}
        try:
            data = call(root, checks, params.get('name'), params.get('arguments') or {})
            result = {'content': [{'type': 'text', 'text': json.dumps(data)}],
                      'structuredContent': data, 'isError': False}
        except (TypeError, ValueError, OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
            result = {'content': [{'type': 'text', 'text': str(exc)}], 'isError': True}
    else:
        return {'jsonrpc': '2.0', 'id': ident,
                'error': {'code': -32601, 'message': 'Method not found'}}
    return {'jsonrpc': '2.0', 'id': ident, 'result': result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--checks', type=Path)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if not root.is_dir():
        parser.error('workspace root must be a directory')
    checks = json.loads(args.checks.read_text()) if args.checks else {}
    if not isinstance(checks, dict) or any(
            not isinstance(name, str) or not isinstance(argv, list) or not argv or
            any(not isinstance(item, str) for item in argv)
            for name, argv in checks.items()):
        parser.error('checks must map names to nonempty argv arrays')
    for line in sys.stdin:
        try:
            packet = json.loads(line)
            if isinstance(packet, dict):
                reply = handle(root, checks, packet)
                if reply is not None:
                    print(json.dumps(reply), flush=True)
        except ValueError:
            continue


if __name__ == '__main__':
    main()
