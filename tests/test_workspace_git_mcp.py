import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from workspace_git_mcp import call, handle


def _git(root, *args):
    subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)


def test_git_inspection_is_bounded_and_scoped(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    _git(root, 'init', '-q')
    _git(root, 'config', 'user.name', 'Test')
    _git(root, 'config', 'user.email', 'test@example.invalid')
    (root / 'README.md').write_text('first\n')
    _git(root, 'add', 'README.md')
    _git(root, 'commit', '-qm', 'initial')
    (root / 'README.md').write_text('second\n')
    (root / '.env').write_text('SECRET=hidden\n')
    assert 'README.md' in call(root, 'get_workspace_git_status', {})['output']
    assert 'initial' in call(root, 'get_workspace_git_log', {'limit': 1})['output']
    assert '+second' in call(root, 'get_workspace_git_diff', {'path': 'README.md'})['output']
    head = call(root, 'get_workspace_git_commit', {})
    assert head['subject'] == 'initial' and head['changes'] == ['A\tREADME.md']
    historical = call(root, 'read_workspace_file_at_revision', {
        'revision': head['revision'], 'path': 'README.md', 'max_lines': 1})
    assert historical['content'] == 'first\n'
    history = call(root, 'get_workspace_file_history', {'path': 'README.md'})
    assert history['commits'][0]['revision'] == head['revision']
    (root / 'README.md').write_text('second\n')
    _git(root, 'add', 'README.md')
    _git(root, 'commit', '-qm', 'second')
    second = call(root, 'get_workspace_git_commit', {})
    comparison = call(root, 'compare_workspace_git_revisions', {
        'base': head['revision'], 'head': second['revision'], 'path': 'README.md'})
    assert '-first' in comparison['output'] and '+second' in comparison['output']
    with pytest.raises(ValueError):
        call(root, 'get_workspace_git_diff', {'path': '.env'})
    with pytest.raises(ValueError):
        call(root, 'get_workspace_git_diff', {'path': '../README.md'})
    with pytest.raises(ValueError):
        call(root / '.git', 'get_workspace_git_status', {})
    with pytest.raises(ValueError):
        call(root, 'get_workspace_git_commit', {'revision': '--all'})
    with pytest.raises(ValueError):
        call(root, 'read_workspace_file_at_revision', {
            'revision': 'HEAD', 'path': '../README.md'})
    (root / 'binary.dat').write_bytes(b'\xff\x00')
    _git(root, 'add', 'binary.dat')
    _git(root, 'commit', '-qm', 'binary')
    with pytest.raises(ValueError, match='UTF-8'):
        call(root, 'read_workspace_file_at_revision', {
            'revision': 'HEAD', 'path': 'binary.dat'})


def test_mcp_list_and_bad_call(tmp_path):
    listing = handle(tmp_path, {'id': 1, 'method': 'tools/list'})
    assert [tool['name'] for tool in listing['result']['tools']] == [
        'get_workspace_git_status', 'get_workspace_git_log', 'get_workspace_git_diff',
        'get_workspace_git_commit', 'compare_workspace_git_revisions',
        'read_workspace_file_at_revision', 'get_workspace_file_history']
    bad = handle(tmp_path, {'id': 2, 'method': 'tools/call',
                            'params': {'name': 'get_workspace_git_diff', 'arguments': {'path': '.env'}}})
    assert bad['result']['isError']
