import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
from workspace_coding_mcp import call
from harness_core.run_api import RunAPI, SCHEMA
from project_agent import run_agent
from workspace_coding_mcp import TOOLS
from unittest.mock import patch


class WorkspaceCodingTests(unittest.TestCase):
    def test_versioned_edit_and_configured_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / 'example.txt'
            target.write_text('before\n', encoding='utf-8')
            old_hash = hashlib.sha256(target.read_bytes()).hexdigest()
            result = call(root, {'syntax': [sys.executable, '-c', 'print("ok")']},
                          'replace_workspace_text', {
                              'path': 'example.txt', 'expected_sha256': old_hash,
                              'old_text': 'before', 'new_text': 'after'})
            self.assertEqual(target.read_text(encoding='utf-8'), 'after\n')
            self.assertEqual(result['sha256'], hashlib.sha256(target.read_bytes()).hexdigest())
            with self.assertRaisesRegex(ValueError, 'changed'):
                call(root, {}, 'write_workspace_file', {
                    'path': 'example.txt', 'expected_sha256': old_hash, 'content': 'lost'})
            with self.assertRaisesRegex(ValueError, 'not configured'):
                call(root, {}, 'run_workspace_check', {'name': 'arbitrary'})
            check = call(root, {'syntax': [sys.executable, '-c', 'print("ok")']},
                         'run_workspace_check', {'name': 'syntax'})
            self.assertEqual(check['exit_code'], 0)
            self.assertIn('ok', check['stdout'])

    def test_path_escape_and_symlink_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(ValueError):
                call(root, {}, 'write_workspace_file', {
                    'path': '../escape.txt', 'expected_sha256': None, 'content': 'bad'})
            outside = root.parent / 'outside-file.txt'
            (root / 'link.txt').symlink_to(outside)
            with self.assertRaises((ValueError, OSError)):
                call(root, {}, 'write_workspace_file', {
                    'path': 'link.txt', 'expected_sha256': None, 'content': 'bad'})
            self.assertFalse(outside.exists())


class SelectedRunTests(unittest.TestCase):
    def test_any_ready_route_and_selected_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / 'project'
            project.mkdir()
            observed = []
            def engine(**kwargs):
                observed.append(kwargs)
                return {'run': {'phase': 'succeeded'}, 'answer': 'ok'}
            api = RunAPI(root / 'state', engine, {
                'gateway': 'http://gateway.local', 'allow_ready_routes': True,
                'allowed_workspace_roots': [str(project)],
                'allowed_profiles': ['workspace_coding'],
                'tool_servers': {'workspace_coding': {
                    'name': 'workspace_coding', 'tools': {'write_workspace_file': {}},
                    'command': ['server', '--root', '{workspace_root}']}},
            })
            task = {'schema': SCHEMA, 'request_id': 'first', 'prompt': 'edit',
                    'route': 'gpu-rig/qwen', 'expected_model': 'qwen',
                    'workspace_root': str(project), 'tool_profile': 'workspace_coding'}
            fixed = RunAPI(root / 'fixed', engine, {'route': 'fixed', 'expected_model': 'fixed'})
            with self.assertRaisesRegex(ValueError, 'not configured'):
                fixed.submit(task)
            run = api.submit(task)['run_id']
            api.execute(run)
            self.assertEqual(api.status(run)['state'], 'succeeded')
            self.assertEqual(observed[0]['route'], 'gpu-rig/qwen')
            self.assertEqual(observed[0]['expected_model'], 'qwen')
            self.assertEqual(observed[0]['tool_server']['command'][-1], str(project))
            second = {**task, 'request_id': 'second', 'route': 'gpu-rig/llama',
                      'expected_model': 'llama'}
            api.execute(api.submit(second)['run_id'])
            self.assertEqual([row['route'] for row in observed],
                             ['gpu-rig/qwen', 'gpu-rig/llama'])
            with self.assertRaisesRegex(ValueError, 'not configured'):
                api.submit({**task, 'request_id': 'outside',
                            'workspace_root': str(root)})



class LocalModelCodingLoopTests(unittest.TestCase):
    def test_ready_model_calls_harness_write_tool_and_records_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / 'project'
            project.mkdir()
            calls = []
            def complete(*args):
                calls.append(args)
                if len(calls) == 1:
                    return {'model': 'local-test', 'choices': [{
                        'finish_reason': 'tool_calls',
                        'message': {'content': None, 'tool_calls': [{
                            'id': 'write-1', 'function': {
                                'name': 'mcp__workspace_coding__write_workspace_file',
                                'arguments': '{"path":"created.txt","expected_sha256":null,"content":"hello"}'}}]}}]}
                return {'model': 'local-test', 'choices': [{
                    'finish_reason': 'stop', 'message': {'content': 'Created created.txt'}}]}
            server = {'name': 'workspace_coding',
                      'tools': [item['name'] for item in TOOLS],
                      'definitions': TOOLS,
                      'command': [sys.executable,
                                  str(Path(__file__).parents[1] / 'tools' / 'workspace_coding_mcp.py'),
                                  '--root', '{workspace_root}']}
            api = RunAPI(root / 'state', run_agent, {
                'gateway': 'http://fake-gateway', 'allow_ready_routes': True,
                'allowed_workspace_roots': [str(project)],
                'allowed_profiles': ['workspace_coding'],
                'tool_servers': {'workspace_coding': server}, 'complete': complete})
            task = {'schema': SCHEMA, 'request_id': 'coding-run', 'prompt': 'Create the file',
                    'agent_type': 'coding', 'tool_profile': 'workspace_coding',
                    'route': 'gpu-rig/local-test', 'expected_model': 'local-test',
                    'workspace_root': str(project), 'conversation_id': 'chat1'}
            roster = {'data': [{'id': 'gpu-rig/local-test', 'model': 'local-test',
                                'context_length': 8192, 'output_limit': 1024}]}
            with patch('project_agent.fetch_ready_roster', return_value=roster):
                run_id = api.submit(task)['run_id']
                api.execute(run_id)
            status = api.status(run_id)
            self.assertEqual(status['state'], 'succeeded', status['receipt'])
            self.assertEqual((project / 'created.txt').read_text(), 'hello')
            self.assertIn('Created created.txt', status['receipt']['answer'])
            self.assertEqual(status['receipt']['run']['conversation_id'], 'chat1')
            self.assertTrue(any(event['type'] == 'tool.committed'
                                for event in api.events(run_id)['events']))



if __name__ == '__main__':
    unittest.main()
