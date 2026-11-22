import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from workspace_read_mcp import call
import workspace_read_mcp


class WorkspaceReadMcpTests(unittest.TestCase):
    def test_reads_visible_files_with_bounds_and_finds_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'src').mkdir()
            (root / 'src' / 'module.py').write_text('print("hello")\n')
            (root / '.env').write_text('SECRET=hidden')
            listed = call(root, 'list_workspace_files', {'path': 'src'})
            self.assertEqual(listed['entries'], [{'path': 'src/module.py', 'type': 'file'}])
            self.assertEqual(call(root, 'find_workspace_files', {'name_contains': 'module'})['matches'],
                             ['src/module.py'])
            self.assertEqual(call(root, 'read_workspace_file', {'path': 'src/module.py'})['content'],
                             'print("hello")\n')
            self.assertEqual(call(root, 'search_workspace_text', {'query': 'hello'})['matches'][0]['path'],
                             'src/module.py')
            with self.assertRaises(ValueError):
                call(root, 'read_workspace_file', {'path': '.env'})
            with self.assertRaises(ValueError):
                call(root, 'read_workspace_file', {'path': '../outside.txt'})

    def test_symlink_escape_and_oversized_file_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'workspace'
            root.mkdir()
            outside = Path(temp) / 'outside.txt'
            outside.write_text('private')
            (root / 'linked.txt').symlink_to(outside)
            (root / 'large.txt').write_text('a' * 1_000_001)
            with self.assertRaises(ValueError):
                call(root, 'read_workspace_file', {'path': 'linked.txt'})
            with self.assertRaises(ValueError):
                call(root, 'read_workspace_file', {'path': 'large.txt'})
            self.assertEqual(call(root, 'find_workspace_files', {'name_contains': 'linked'})['matches'], [])

    def test_find_skips_generated_results_and_accepts_subtree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'results').mkdir()
            (root / 'results' / 'old.txt').write_text('generated')
            (root / 'tools').mkdir()
            (root / 'tools' / 'subagent_contract.py').write_text('source')
            found = call(root, 'find_workspace_files', {'name_contains': 'subagent_contract'})
            self.assertEqual(found['matches'], ['tools/subagent_contract.py'])
            self.assertEqual(found['files_scanned'], 1)
            narrowed = call(root, 'find_workspace_files', {
                'name_contains': 'subagent_contract', 'path': 'tools'})
            self.assertEqual(narrowed['matches'], ['tools/subagent_contract.py'])

    def test_targeted_line_reads_and_single_file_search(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / 'large.py'
            target.write_text(''.join(f'line {line}\n' for line in range(1, 301)))
            excerpt = call(root, 'read_workspace_file', {
                'path': 'large.py', 'start_line': 120, 'max_lines': 3, 'max_chars': 1000})
            self.assertEqual(excerpt['content'], 'line 120\nline 121\nline 122\n')
            self.assertEqual((excerpt['start_line'], excerpt['end_line']), (120, 122))
            self.assertTrue(excerpt['requested_range_complete'])
            self.assertTrue(excerpt['more_lines_after'])
            self.assertTrue(excerpt['truncated'])
            found = call(root, 'search_workspace_text', {'path': 'large.py', 'query': 'line 250'})
            self.assertEqual(found['matches'], [
                {'path': 'large.py', 'line': 250, 'preview': 'line 250'}])
            self.assertEqual(found['files_scanned'], 1)

    def test_complete_document_chunks_reconstruct_exact_unicode_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = ('section αβγ\n' * 31) + 'final snowman: ☃\n'
            (root / 'report.md').write_text(content)
            chunks = []
            cursor = 0
            snapshot = None
            while True:
                arguments = {'path': 'report.md', 'cursor': cursor, 'max_chars': 100}
                if snapshot is not None:
                    arguments['snapshot_sha256'] = snapshot
                result = call(root, 'read_workspace_document_chunk', arguments)
                snapshot = result['snapshot_sha256']
                chunks.append(result['content'])
                if result['complete']:
                    self.assertIsNone(result['next_cursor'])
                    break
                cursor = result['next_cursor']
            self.assertEqual(''.join(chunks), content)
            self.assertEqual(result['cursor_end'], result['total_characters'])
            self.assertEqual(result['total_bytes'], len(content.encode('utf-8')))

    def test_complete_document_snapshot_and_cursor_are_enforced(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / 'report.md'
            target.write_text('a' * 250)
            first = call(root, 'read_workspace_document_chunk', {
                'path': 'report.md', 'cursor': 0, 'max_chars': 100})
            with self.assertRaisesRegex(ValueError, 'snapshot_sha256'):
                call(root, 'read_workspace_document_chunk', {
                    'path': 'report.md', 'cursor': first['next_cursor'], 'max_chars': 100})
            target.write_text('b' * 250)
            with self.assertRaisesRegex(ValueError, 'changed'):
                call(root, 'read_workspace_document_chunk', {
                    'path': 'report.md', 'cursor': first['next_cursor'],
                    'snapshot_sha256': first['snapshot_sha256'], 'max_chars': 100})
            with self.assertRaisesRegex(ValueError, 'beyond'):
                call(root, 'read_workspace_document_chunk', {
                    'path': 'report.md', 'cursor': 300,
                    'snapshot_sha256': call(root, 'read_workspace_document_chunk', {
                        'path': 'report.md'})['snapshot_sha256']})

    def test_file_swapped_to_symlink_before_open_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'workspace'
            root.mkdir()
            outside = Path(temp) / 'outside.txt'
            outside.write_text('private')
            target = root / 'file.txt'
            target.write_text('public')
            real_open = os.open
            def swap_before_open(path, flags, *, dir_fd=None):
                if path == 'file.txt':
                    target.unlink()
                    target.symlink_to(outside)
                return real_open(path, flags, dir_fd=dir_fd)
            with patch.object(workspace_read_mcp.os, 'open', side_effect=swap_before_open):
                with self.assertRaises(ValueError):
                    call(root, 'read_workspace_file', {'path': 'file.txt'})

    def test_stdio_mcp_tool_contract(self):
        script = Path(__file__).resolve().parents[1] / 'tools/workspace_read_mcp.py'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'README.md').write_text('A small workspace')
            packets = [
                {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                 'params': {'name': 'read_workspace_file', 'arguments': {'path': 'README.md'}}},
            ]
            proc = subprocess.run([sys.executable, str(script), '--root', str(root)],
                                  input='\n'.join(json.dumps(packet) for packet in packets) + '\n',
                                  text=True, capture_output=True, timeout=5)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        responses = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual([tool['name'] for tool in responses[0]['result']['tools']],
                         ['list_workspace_files', 'find_workspace_files', 'read_workspace_file',
                          'read_workspace_document_chunk', 'search_workspace_text'])
        self.assertEqual(responses[1]['result']['structuredContent']['content'], 'A small workspace')


if __name__ == '__main__':
    unittest.main()
