#!/usr/bin/env python3
"""Read-only MCP view of one explicitly selected coding workspace."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

SKIP_SEARCH_DIRS = {'results', 'node_modules', '__pycache__', 'build', 'dist', 'target'}


TOOLS = [
    {'name': 'list_workspace_files', 'description': 'List one workspace directory, excluding hidden paths and symlinks.',
     'annotations': {'readOnlyHint': True}, 'inputSchema': {'type': 'object', 'properties': {
         'path': {'type': 'string', 'maxLength': 300}, 'max_entries': {'type': 'integer', 'minimum': 1, 'maximum': 100}},
         'additionalProperties': False}},
    {'name': 'find_workspace_files', 'description': 'Find workspace file paths by filename substring, excluding hidden paths and symlinks.',
     'annotations': {'readOnlyHint': True}, 'inputSchema': {'type': 'object', 'properties': {
         'name_contains': {'type': 'string', 'minLength': 1, 'maxLength': 80},
         'path': {'type': 'string', 'maxLength': 300},
         'max_results': {'type': 'integer', 'minimum': 1, 'maximum': 100}},
         'required': ['name_contains'], 'additionalProperties': False}},
    {'name': 'read_workspace_file', 'description': 'Read a requested UTF-8 line range from one workspace file. Search first, then read around matching lines. sha256 is the complete file version token for guarded edits. requested_range_complete=true means the requested range was delivered; do not page adjacent ranges merely because more_lines_after or truncated is true.',
     'annotations': {'readOnlyHint': True}, 'inputSchema': {'type': 'object', 'properties': {
         'path': {'type': 'string', 'minLength': 1, 'maxLength': 300},
         'start_line': {'type': 'integer', 'minimum': 1, 'maximum': 50000},
         'max_lines': {'type': 'integer', 'minimum': 1, 'maximum': 500},
         'max_chars': {'type': 'integer', 'minimum': 100, 'maximum': 12000}},
         'required': ['path'], 'additionalProperties': False}},
    {'name': 'read_workspace_document_chunk', 'description': 'Read the next contiguous UTF-8 character chunk from an immutable workspace document snapshot. For a complete read, start with cursor=0, then use exactly next_cursor and the same snapshot_sha256 until complete=true. Never skip or invent a cursor.',
     'annotations': {'readOnlyHint': True}, 'inputSchema': {'type': 'object', 'properties': {
         'path': {'type': 'string', 'minLength': 1, 'maxLength': 300},
         'cursor': {'type': 'integer', 'minimum': 0, 'maximum': 1000000},
         'snapshot_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
         'max_chars': {'type': 'integer', 'minimum': 100, 'maximum': 12000}},
         'required': ['path'], 'additionalProperties': False}},
    {'name': 'search_workspace_text', 'description': 'Search a visible UTF-8 file or directory for literal text and return matching file paths and line numbers.',
     'annotations': {'readOnlyHint': True}, 'inputSchema': {'type': 'object', 'properties': {
         'query': {'type': 'string', 'minLength': 2, 'maxLength': 100},
         'path': {'type': 'string', 'maxLength': 300}},
         'required': ['query'], 'additionalProperties': False}},
]


def _visible_parts(raw: str) -> tuple[str, ...]:
    if not isinstance(raw, str) or len(raw) > 300 or '\\' in raw:
        raise ValueError('invalid workspace path')
    relative = Path(raw or '.')
    if relative.is_absolute() or any(part == '..' or part.startswith('.') for part in relative.parts):
        raise ValueError('workspace path is not visible')
    return tuple(part for part in relative.parts if part != '.')


@contextmanager
def _open_visible(root: Path, raw: str, *, directory: bool | None):
    """Walk from the selected root with no-follow descriptors, then use the fd."""
    parts = _visible_parts(raw)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for index, part in enumerate(parts):
            flags = os.O_RDONLY | os.O_NOFOLLOW
            if index < len(parts) - 1 or directory is True:
                flags |= os.O_DIRECTORY
            try:
                child = os.open(part, flags, dir_fd=fd)
            except OSError as exc:
                raise ValueError('workspace path is unavailable or not visible') from exc
            os.close(fd)
            fd = child
        if directory is False and not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('workspace text file is unavailable')
        yield fd, Path(*parts).as_posix() if parts else '.'
    finally:
        os.close(fd)


def call(root: Path, name: str, args: dict) -> dict:
    if not isinstance(args, dict):
        raise ValueError('invalid workspace tool arguments')
    if name == 'list_workspace_files':
        if set(args) - {'path', 'max_entries'} or type(args.get('max_entries', 50)) is not int \
                or not 1 <= args.get('max_entries', 50) <= 100:
            raise ValueError('list_workspace_files accepts path and max_entries')
        with _open_visible(root, args.get('path', '.'), directory=True) as (fd, relative):
            entries = []
            with os.scandir(fd) as scan:
                children = sorted(scan, key=lambda item: item.name)
            for child in children:
                if child.name.startswith('.'):
                    continue
                mode = os.stat(child.name, dir_fd=fd, follow_symlinks=False).st_mode
                if stat.S_ISLNK(mode):
                    continue
                kind = 'directory' if stat.S_ISDIR(mode) else 'file'
                entries.append({'path': (Path(relative) / child.name).as_posix(), 'type': kind})
                if len(entries) >= args.get('max_entries', 50):
                    break
            return {'path': relative, 'entries': entries,
                    'truncated': len(entries) == args.get('max_entries', 50)}
    if name == 'find_workspace_files':
        if (set(args) - {'name_contains', 'path', 'max_results'} or
                not isinstance(args.get('name_contains'), str) or
                not 1 <= len(args['name_contains']) <= 80 or
                type(args.get('max_results', 50)) is not int or
                not 1 <= args.get('max_results', 50) <= 100):
            raise ValueError('find_workspace_files requires name_contains and optional path/max_results')
        wanted = args['name_contains'].casefold()
        matches, visited, directories = [], 0, 0
        with _open_visible(root, args.get('path', '.'), directory=True) as (base_fd, relative):
            def walk(fd: int, prefix: Path):
                nonlocal visited, directories
                directories += 1
                with os.scandir(fd) as scan:
                    children = sorted(scan, key=lambda item: item.name)
                for child in children:
                    if child.name.startswith('.'):
                        continue
                    path = prefix / child.name
                    try:
                        mode = os.stat(child.name, dir_fd=fd, follow_symlinks=False).st_mode
                    except OSError:
                        continue
                    if stat.S_ISLNK(mode):
                        continue
                    if stat.S_ISDIR(mode):
                        if child.name in SKIP_SEARCH_DIRS:
                            continue
                        if directories >= 3000 or len(path.parts) > 25:
                            continue
                        try:
                            next_fd = os.open(child.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                              dir_fd=fd)
                        except OSError:
                            continue
                        try:
                            walk(next_fd, path)
                        finally:
                            os.close(next_fd)
                    elif stat.S_ISREG(mode):
                        visited += 1
                        if wanted in child.name.casefold():
                            matches.append(path.as_posix())
                    if len(matches) >= args.get('max_results', 50) or visited >= 3000:
                        return
            walk(base_fd, Path(relative))
            return {'matches': matches, 'files_scanned': visited, 'path': relative,
                    'truncated': len(matches) >= args.get('max_results', 50) or visited >= 3000}
    if name == 'read_workspace_file':
        if (set(args) - {'path', 'start_line', 'max_lines', 'max_chars'} or
                not isinstance(args.get('path'), str) or
                not 1 <= len(args['path']) <= 300 or
                type(args.get('start_line', 1)) is not int or
                not 1 <= args.get('start_line', 1) <= 50000 or
                type(args.get('max_lines', 200)) is not int or
                not 1 <= args.get('max_lines', 200) <= 500 or
                type(args.get('max_chars', 6000)) is not int or
                not 100 <= args.get('max_chars', 6000) <= 12000):
            raise ValueError('read_workspace_file requires path and optional start_line/max_lines/max_chars')
        with _open_visible(root, args['path'], directory=False) as (fd, relative):
            if os.fstat(fd).st_size > 1_000_000:
                raise ValueError('workspace text file is unavailable or too large')
            start_line = args.get('start_line', 1)
            max_lines = args.get('max_lines', 200)
            limit = args.get('max_chars', 6000)
            content, used_chars, end_line = [], 0, start_line - 1
            content_truncated, more_lines_after = False, False
            with os.fdopen(os.dup(fd), 'r', encoding='utf-8') as source:
                for line_number, text in enumerate(source, 1):
                    if line_number < start_line:
                        continue
                    if line_number >= start_line + max_lines:
                        more_lines_after = True
                        break
                    remaining = limit - used_chars
                    if len(text) > remaining:
                        content.append(text[:max(0, remaining)])
                        end_line = line_number
                        content_truncated = True
                        break
                    content.append(text)
                    used_chars += len(text)
                    end_line = line_number
            joined = ''.join(content)
            if '\x00' in joined:
                raise ValueError('binary workspace file is unavailable')
            snapshot_fd = os.dup(fd)
            os.lseek(snapshot_fd, 0, os.SEEK_SET)
            with os.fdopen(snapshot_fd, 'rb') as snapshot_source:
                file_sha256 = hashlib.sha256(snapshot_source.read()).hexdigest()
            return {'path': relative, 'content': joined, 'sha256': file_sha256,
                    'start_line': start_line,
                    'end_line': end_line, 'requested_range_complete': not content_truncated,
                    'more_lines_after': more_lines_after,
                    'truncated': content_truncated or more_lines_after}
    if name == 'read_workspace_document_chunk':
        if (set(args) - {'path', 'cursor', 'snapshot_sha256', 'max_chars'} or
                not isinstance(args.get('path'), str) or
                not 1 <= len(args['path']) <= 300 or
                type(args.get('cursor', 0)) is not int or
                not 0 <= args.get('cursor', 0) <= 1_000_000 or
                (args.get('cursor', 0) > 0 and args.get('snapshot_sha256') is None) or
                (args.get('snapshot_sha256') is not None and
                 (not isinstance(args['snapshot_sha256'], str) or
                  len(args['snapshot_sha256']) != 64 or
                  any(char not in '0123456789abcdef' for char in args['snapshot_sha256']))) or
                type(args.get('max_chars', 12000)) is not int or
                not 100 <= args.get('max_chars', 12000) <= 12000):
            raise ValueError('read_workspace_document_chunk requires path and optional cursor/snapshot_sha256/max_chars')
        with _open_visible(root, args['path'], directory=False) as (fd, relative):
            if os.fstat(fd).st_size > 1_000_000:
                raise ValueError('workspace text file is unavailable or too large')
            with os.fdopen(os.dup(fd), 'rb') as source:
                raw = source.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ValueError('workspace text file is unavailable or too large')
            content = raw.decode('utf-8')
            if '\x00' in content:
                raise ValueError('binary workspace file is unavailable')
            snapshot = hashlib.sha256(raw).hexdigest()
            expected = args.get('snapshot_sha256')
            if expected is not None and expected != snapshot:
                raise ValueError('workspace document changed during complete read')
            cursor = args.get('cursor', 0)
            if cursor > len(content):
                raise ValueError('document cursor is beyond the end of the snapshot')
            end = min(len(content), cursor + args.get('max_chars', 12000))
            complete = end == len(content)
            return {'path': relative, 'snapshot_sha256': snapshot,
                    'total_bytes': len(raw), 'total_characters': len(content),
                    'cursor_start': cursor, 'cursor_end': end,
                    'content': content[cursor:end],
                    'next_cursor': None if complete else end, 'complete': complete}
    if name == 'search_workspace_text':
        if (set(args) - {'query', 'path'} or not isinstance(args.get('query'), str)
                or not 2 <= len(args['query']) <= 100 or '\x00' in args['query']):
            raise ValueError('search_workspace_text requires a bounded literal query')
        matches, scanned = [], 0
        needle = args['query'].casefold()
        with _open_visible(root, args.get('path', '.'), directory=None) as (base_fd, relative):
            def scan_file(file_fd: int, path: Path):
                nonlocal scanned
                if os.fstat(file_fd).st_size > 1_000_000:
                    return
                scanned += 1
                try:
                    with os.fdopen(os.dup(file_fd), 'r', encoding='utf-8') as source:
                        for line_number, text in enumerate(source, 1):
                            if line_number > 5000:
                                break
                            if needle in text.casefold():
                                matches.append({'path': path.as_posix(), 'line': line_number,
                                                'preview': text.strip()[:180]})
                                if len(matches) >= 40:
                                    break
                except (OSError, UnicodeError):
                    pass
            def walk(fd: int, prefix: Path, depth: int):
                nonlocal scanned
                with os.scandir(fd) as scan:
                    names = sorted(entry.name for entry in scan if not entry.name.startswith('.'))
                for child in names:
                    try:
                        info = os.stat(child, dir_fd=fd, follow_symlinks=False)
                    except OSError:
                        continue
                    path = prefix / child
                    if stat.S_ISDIR(info.st_mode) and depth < 20 and child not in SKIP_SEARCH_DIRS:
                        try:
                            next_fd = os.open(child, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                        except OSError:
                            continue
                        try:
                            walk(next_fd, path, depth + 1)
                        finally:
                            os.close(next_fd)
                    elif stat.S_ISREG(info.st_mode) and info.st_size <= 1_000_000:
                        try:
                            file_fd = os.open(child, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
                            try:
                                scan_file(file_fd, path)
                            finally:
                                os.close(file_fd)
                        except (OSError, UnicodeError):
                            pass
                    if len(matches) >= 40 or scanned >= 1000:
                        return
            mode = os.fstat(base_fd).st_mode
            if stat.S_ISREG(mode):
                scan_file(base_fd, Path(relative))
            elif stat.S_ISDIR(mode):
                walk(base_fd, Path(relative), 0)
            else:
                raise ValueError('workspace path must be a text file or directory')
            return {'matches': matches, 'files_scanned': scanned, 'path': relative,
                    'truncated': len(matches) >= 40 or scanned >= 1000}
    raise ValueError('unknown workspace tool')


def handle(root: Path, packet: dict) -> dict | None:
    ident = packet.get('id')
    if ident is None:
        return None
    method = packet.get('method')
    if method == 'initialize':
        result = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}},
                  'serverInfo': {'name': 'workspace-read', 'version': '0.1.0'}}
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
        except (ValueError, OSError, UnicodeError) as exc:
            result = {'content': [{'type': 'text', 'text': str(exc)}], 'isError': True}
    else:
        return {'jsonrpc': '2.0', 'id': ident,
                'error': {'code': -32601, 'message': 'Method not found'}}
    return {'jsonrpc': '2.0', 'id': ident, 'result': result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if not root.is_dir():
        parser.error('workspace root must be a directory')
    for line in sys.stdin:
        try:
            packet = json.loads(line)
            if isinstance(packet, dict):
                reply = handle(root, packet)
                if reply is not None:
                    print(json.dumps(reply), flush=True)
        except ValueError:
            continue


if __name__ == '__main__':
    main()
