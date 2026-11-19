import base64
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import github_public_mcp as github


SHA = 'a' * 40


def test_public_repo_inspection_and_pinned_file_reads(monkeypatch):
    calls = []
    content = {'type': 'file', 'path': 'README.md', 'sha': 'b' * 40, 'encoding': 'base64',
               'size': 12, 'content': base64.b64encode(b'hello\nworld\n').decode()}

    def fake_request(path):
        calls.append(path)
        if path == '/repos/example/project':
            return {'private': False, 'html_url': 'https://github.com/example/project',
                    'description': 'sample', 'default_branch': 'main', 'archived': False}
        if path == '/repos/example/project/commits/main':
            return {'sha': SHA}
        if path == f'/repos/example/project/contents?ref={SHA}':
            return [{'path': 'README.md', 'type': 'file', 'size': 12},
                    {'path': 'src', 'type': 'dir'}]
        if path == f'/repos/example/project/contents/README.md?ref={SHA}':
            return content
        if path == f'/repos/example/project/contents/src?ref={SHA}':
            return [{'path': 'src/main.py', 'type': 'file', 'size': 8}]
        if path == f'/repos/example/project/git/trees/{SHA}?recursive=1':
            return {'tree': [{'type': 'blob', 'path': 'README.md'},
                             {'type': 'blob', 'path': 'src/main.py'}], 'truncated': False}
        raise AssertionError(path)

    monkeypatch.setattr(github, '_request', fake_request)
    info = github.call('inspect_github_repo', {'repository': 'https://github.com/example/project'})
    assert info['revision'] == SHA
    assert info['readme_preview']['content'] == 'hello\nworld\n'
    listed = github.call('list_github_directory', {'repository': 'example/project', 'revision': SHA, 'path': 'src'})
    assert listed['entries'][0]['path'] == 'src/main.py'
    found = github.call('find_github_files', {'repository': 'example/project', 'revision': SHA,
                                              'name_contains': 'main'})
    assert found['matches'] == ['src/main.py']
    read = github.call('read_github_file', {'repository': 'example/project', 'revision': SHA,
                                            'path': 'README.md', 'start_line': 2, 'max_lines': 1})
    assert read['content'] == 'world\n'
    assert all(path.startswith('/repos/example/project/') or path == '/repos/example/project' for path in calls)


@pytest.mark.parametrize('repository', [
    'http://github.com/example/project', 'https://evil.example/example/project',
    'https://github.com@example.org/example/project', 'example/project/extra',
    'https://github.com/example/project?token=secret', '../project',
])
def test_repository_input_rejects_non_github_or_extra_paths(repository):
    with pytest.raises(ValueError):
        github._repository(repository)


def test_invalid_revision_and_path_are_rejected_before_network(monkeypatch):
    monkeypatch.setattr(github, '_request', lambda path: (_ for _ in ()).throw(AssertionError(path)))
    with pytest.raises(ValueError):
        github.call('read_github_file', {'repository': 'example/project', 'revision': 'main', 'path': 'README.md'})
    with pytest.raises(ValueError):
        github.call('read_github_file', {'repository': 'example/project', 'revision': SHA, 'path': '../README.md'})
    assert [tool['name'] for tool in github.handle({'id': 1, 'method': 'tools/list'})['result']['tools']] == [
        'inspect_github_repo', 'list_github_directory', 'find_github_files', 'read_github_file']


def test_large_public_readme_uses_bounded_raw_media(monkeypatch):
    metadata = {'type': 'file', 'path': 'README.md', 'size': 1_500_000,
                'encoding': 'none', 'sha': 'b' * 40, 'content': ''}
    monkeypatch.setattr(github, '_request_raw', lambda path: b'heading\nbody\n')
    read = github._text(metadata, base='/repos/example/project', revision=SHA,
                        start_line=2, max_lines=1)
    assert read['content'] == 'body\n'
