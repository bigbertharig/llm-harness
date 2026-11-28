import hashlib
import subprocess
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
            from workspace_read_mcp import call as read_call
            self.assertEqual(read_call(root, 'read_workspace_file', {'path': 'example.txt'})['sha256'],
                             old_hash)
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

    def test_git_status_and_diff_after_versioned_edit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            target = root / 'example.txt'
            target.write_text('before\n', encoding='utf-8')
            subprocess.run(['git', '-C', str(root), 'add', 'example.txt'], check=True)
            subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test',
                            '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'base'], check=True)
            old_hash = hashlib.sha256(target.read_bytes()).hexdigest()
            call(root, {}, 'replace_workspace_text', {
                'path': 'example.txt', 'expected_sha256': old_hash,
                'old_text': 'before', 'new_text': 'after'})
            status = call(root, {}, 'get_workspace_git_status', {})
            diff = call(root, {}, 'get_workspace_git_diff', {'path': 'example.txt'})
            self.assertIn('example.txt', status['output'])
            self.assertIn('+after', diff['output'])
            self.assertIn('-before', diff['output'])

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


    def test_continuation_is_durable_and_scoped_to_conversation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / 'project'
            project.mkdir()
            observed = []
            def engine(**kwargs):
                observed.append(kwargs)
                return {'run': {'phase': 'succeeded'}, 'answer': 'answer-' + kwargs['prompt']}
            config = {'gateway': 'http://gateway.local', 'allow_ready_routes': True,
                      'allowed_workspace_roots': [str(project)], 'allowed_profiles': ['none']}
            state = root / 'state'
            api = RunAPI(state, engine, config)
            base = {'schema': SCHEMA, 'route': 'gpu-rig/local', 'expected_model': 'local',
                    'workspace_root': str(project), 'conversation_id': 'chat-one',
                    'tool_profile': 'none'}
            first = api.submit({**base, 'request_id': 'turn-one', 'prompt': 'first'})['run_id']
            api.execute(first)
            restarted = RunAPI(state, engine, config)
            second_task = {**base, 'request_id': 'turn-two', 'prompt': 'second',
                           'parent_run_id': first}
            second = restarted.submit(second_task)['run_id']
            restarted.execute(second)
            self.assertEqual(observed[-1]['prior_turns'],
                             [{'prompt': 'first', 'answer': 'answer-first'}])
            with self.assertRaisesRegex(ValueError, 'another conversation'):
                restarted.submit({**second_task, 'request_id': 'wrong-owner',
                                  'conversation_id': 'chat-two'})
            with self.assertRaisesRegex(ValueError, 'completed successful'):
                restarted.submit({**second_task, 'request_id': 'missing-parent',
                                  'parent_run_id': 'missing'})

    def test_continuation_keeps_entire_completed_chat(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            observed = []
            def engine(**kwargs):
                observed.append(kwargs)
                return {'run': {'phase': 'succeeded'}, 'answer': 'answer-' + kwargs['prompt']}
            api = RunAPI(root / 'state', engine,
                         {'gateway': 'http://gateway.local', 'allow_ready_routes': True,
                          'allowed_profiles': ['none']})
            parent = None
            for index in range(6):
                task = {'schema': SCHEMA, 'request_id': f'turn-{index}',
                        'conversation_id': 'long-chat', 'route': 'gpu-rig/local',
                        'expected_model': 'local', 'tool_profile': 'none',
                        'prompt': f'fact-{index}'}
                if parent:
                    task['parent_run_id'] = parent
                parent = api.submit(task)['run_id']
                api.execute(parent)
            self.assertEqual([turn['prompt'] for turn in observed[-1]['prior_turns']],
                             ['fact-0', 'fact-1', 'fact-2', 'fact-3', 'fact-4'])

    def test_model_receives_prior_exchange_before_current_task(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calls = []
            def complete(*args):
                calls.append(args)
                return {'model': 'local-test', 'choices': [{
                    'finish_reason': 'stop', 'message': {'content': 'done'}}]}
            roster = {'data': [{'id': 'gpu-rig/local-test', 'model': 'local-test',
                                'context_length': 8192, 'output_limit': 1024}]}
            with patch('project_agent.fetch_ready_roster', return_value=roster):
                receipt = run_agent(
                    gateway='http://fake', route='gpu-rig/local-test',
                    expected_model='local-test', prompt='current', agent_type='coding',
                    tool_profile='none', journal_root=root,
                    prior_turns=[{'prompt': 'previous', 'answer': 'earlier result'}],
                    complete=complete)
            messages = calls[0][2]
            self.assertEqual([row['role'] for row in messages[:4]],
                             ['system', 'user', 'assistant', 'user'])
            self.assertEqual(messages[1]['content'], 'previous')
            self.assertEqual(messages[2]['content'], 'earlier result')
            self.assertIn('current', messages[3]['content'])
            self.assertEqual(receipt['prior_turns_used'], 1)


    def test_model_receives_oldest_turn_after_six_exchanges(self):
        with tempfile.TemporaryDirectory() as temporary:
            calls = []
            def complete(*args):
                calls.append(args)
                return {'model': 'local-test', 'choices': [{
                    'finish_reason': 'stop', 'message': {'content': 'done'}}]}
            roster = {'data': [{'id': 'gpu-rig/local-test', 'model': 'local-test',
                                'context_length': 8192, 'output_limit': 1024}]}
            turns = [{'prompt': f'fact-{index}', 'answer': f'answer-{index}'}
                     for index in range(6)]
            with patch('project_agent.fetch_ready_roster', return_value=roster):
                receipt = run_agent(
                    gateway='http://fake', route='gpu-rig/local-test',
                    expected_model='local-test', prompt='recall fact-0',
                    agent_type='coding', tool_profile='none',
                    journal_root=Path(temporary), prior_turns=turns,
                    complete=complete)
            messages = calls[0][2]
            self.assertEqual(messages[1]['content'], 'fact-0')
            self.assertEqual(messages[-2]['content'], 'answer-5')
            self.assertEqual(receipt['prior_turns_used'], 6)

    def test_context_overflow_fails_without_silently_dropping_turns(self):
        with tempfile.TemporaryDirectory() as temporary:
            roster = {'data': [{'id': 'gpu-rig/local-test', 'model': 'local-test',
                                'context_length': 8192, 'output_limit': 1024}]}
            with patch('project_agent.fetch_ready_roster', return_value=roster):
                with self.assertRaisesRegex(ValueError, 'conversation exceeds'):
                    run_agent(
                        gateway='http://fake', route='gpu-rig/local-test',
                        expected_model='local-test', prompt='current',
                        agent_type='coding', tool_profile='none',
                        journal_root=Path(temporary),
                        prior_turns=[{'prompt': 'old fact: ' + 'x' * 10000,
                                      'answer': 'acknowledged'}],
                        complete=lambda *args: self.fail('provider must not be called'))



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
