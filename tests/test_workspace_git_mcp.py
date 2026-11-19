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
    with pytest.raises(ValueError):
        call(root, 'get_workspace_git_diff', {'path': '.env'})
    with pytest.raises(ValueError):
        call(root, 'get_workspace_git_diff', {'path': '../README.md'})
    with pytest.raises(ValueError):
        call(root / '.git', 'get_workspace_git_status', {})


def test_mcp_list_and_bad_call(tmp_path):
    listing = handle(tmp_path, {'id': 1, 'method': 'tools/list'})
    assert [tool['name'] for tool in listing['result']['tools']] == [
        'get_workspace_git_status', 'get_workspace_git_log', 'get_workspace_git_diff']
    bad = handle(tmp_path, {'id': 2, 'method': 'tools/call',
                            'params': {'name': 'get_workspace_git_diff', 'arguments': {'path': '.env'}}})
    assert bad['result']['isError']
