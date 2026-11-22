import json
import sys
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import gateway_subagent
from gateway_subagent import malformed_child_output, resolve_child, run_child
from child_public_tools import (call_tool as call_public_tool, parse_request as parse_public_request,
                                parse_requests as parse_public_requests)
from subagent_contract import canonical_integer_answer, canonical_final_line, child_system_prompt


class GatewaySubagentRequest(unittest.TestCase):
    def test_repetitive_shared_output_is_rejected(self):
        self.assertTrue(malformed_child_output('<cwd>\n/tmp/work\n</cwd>\n' + '</cwd>\n' * 20))
        self.assertFalse(malformed_child_output('Inspected routes.py and found one fixed-context route.'))

    def test_public_tool_bridge_accepts_only_exact_allowlisted_requests(self):
        server = {'name': 'rig_search', 'tools': ['search_web', 'fetch_page']}
        request = {'name': 'mcp__rig_search__search_web', 'arguments': {'query': 'Python docs'}}
        self.assertEqual(parse_public_request(json.dumps(request), server, server['tools']),
                         ('search_web', {'query': 'Python docs'}))
        self.assertEqual(parse_public_request(json.dumps({'tool': 'search_web',
                                                         'arguments': {'query': 'Python docs'}}),
                                              server, server['tools']),
                         ('search_web', {'query': 'Python docs'}))
        self.assertEqual(parse_public_request(json.dumps({'search_web': {'query': 'Python docs'}}),
                                              server, server['tools']),
                         ('search_web', {'query': 'Python docs'}))
        self.assertIsNone(parse_public_request('Search the web: ' + json.dumps(request),
                                               server, server['tools']))
        self.assertIsNone(parse_public_request(json.dumps({'name': 'mcp__rig_search__delete',
                                                           'arguments': {}}), server, server['tools']))

    def test_tool_bridge_accepts_bounded_function_syntax_from_local_models(self):
        server = {'name': 'workspace_read', 'tools': ['search_workspace_text', 'read_workspace_file']}
        calls = ('search_workspace_text({"query":"main agent"})\n'
                 'read_workspace_file({"path":"README.md","start_line":1,"max_lines":40})')
        self.assertEqual(parse_public_request(calls, server, server['tools']),
                         ('search_workspace_text', {'query': 'main agent'}))
        self.assertIsNone(parse_public_request(
            'search_workspace_text({"query":"ok"})\ndelete_file({"path":"README.md"})',
            server, server['tools']))

    def test_tool_bridge_accepts_bounded_json_sequence_from_local_models(self):
        server = {'name': 'workspace_read', 'tools': ['read_workspace_file']}
        calls = ('{"name":"mcp__workspace_read__read_workspace_file",'
                 '"arguments":{"path":"README.md"}}\n\n'
                 '{"name":"mcp__workspace_read__read_workspace_file",'
                 '"arguments":{"path":"docs/OWN_HARNESS_DIRECTION.md"}}')
        self.assertEqual(parse_public_requests(calls, server, server['tools']), [
            ('read_workspace_file', {'path': 'README.md'}),
            ('read_workspace_file', {'path': 'docs/OWN_HARNESS_DIRECTION.md'})])
        self.assertEqual(len(parse_public_requests('\n'.join([calls] * 4),
                                                   server, server['tools'])), 4)
        self.assertEqual(parse_public_requests(calls + '\nnot prose', server, server['tools']), [])

    def test_tool_bridge_accepts_one_strict_allowlisted_xml_call(self):
        server = {'name': 'workspace_read', 'tools': ['search_workspace_text', 'read_workspace_file']}
        calls = ('<read_workspace_file>\n<path>ARCHITECTURE.md</path>\n'
                 '<start_line>1</start_line>\n<max_lines>200</max_lines>\n</read_workspace_file>\n'
                 '<search_workspace_text><query>proposed</query></search_workspace_text>')
        self.assertEqual(parse_public_request(calls, server, server['tools']),
                         ('read_workspace_file', {'path': 'ARCHITECTURE.md',
                          'start_line': 1, 'max_lines': 200}))
        self.assertEqual(parse_public_requests(calls, server, server['tools']), [
            ('read_workspace_file', {'path': 'ARCHITECTURE.md', 'start_line': 1, 'max_lines': 200}),
            ('search_workspace_text', {'query': 'proposed'})])
        repeated = ''.join('<read_workspace_file><path>README.md</path></read_workspace_file>'
                           for _ in range(8))
        self.assertEqual(len(parse_public_requests(repeated, server, server['tools'])), 4)
        self.assertIsNone(parse_public_request(
            '<delete_file><path>README.md</path></delete_file>', server, server['tools']))
        self.assertIsNone(parse_public_request(
            'Please <read_workspace_file><path>README.md</path></read_workspace_file>',
            server, server['tools']))
        self.assertIsNone(parse_public_request(
            '<read_workspace_file><path><b>README.md</b></path></read_workspace_file>',
            server, server['tools']))

    def test_public_tool_bridge_discovers_and_calls_stdio_server(self):
        fixture = Path(__file__).resolve().parents[1] / 'tools/fixtures/diagnostics_mcp.mjs'
        with tempfile.TemporaryDirectory() as temp:
            server = {'name': 'fixture', 'tools': ['read_marker'],
                      'command': ['node', str(fixture), 'marker', str(Path(temp) / 'calls.jsonl')]}
            result = call_public_tool(server, 'read_marker', {}, timeout=10)
        self.assertFalse(result.get('isError'))
        self.assertTrue(result.get('structuredContent') or result.get('content'))

    def test_typed_prompt_and_numeric_normalization(self):
        self.assertIn('coding child agent', child_system_prompt('coding'))
        self.assertIn('research child agent', child_system_prompt('research'))
        self.assertIn('search_web', child_system_prompt('research', 'public_research'))
        self.assertIn('model-independent google_workspace',
                      child_system_prompt('research', 'google_workspace'))
        self.assertIn('no tools', child_system_prompt('research'))
        self.assertEqual(canonical_integer_answer('42.0'), '42')
        self.assertEqual(canonical_integer_answer('42'), '42')
        self.assertIsNone(canonical_integer_answer('41.5'))
        self.assertIsNone(canonical_integer_answer('The answer is 42'))
        self.assertEqual(canonical_final_line('Checked 7 times 6.\n\n42'), '42')

    def test_harness_sends_capability_without_gpu_or_model(self):
        class Reply:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass
            def read(self):
                return b'{"route":"gpu-rig/coder-7b","gpu_ids":[2]}'

        with patch('gateway_subagent.urlopen', return_value=Reply()) as call:
            result = resolve_child('http://127.0.0.1:8080', 'gpu-rig/chat-27b', 'coding')
        request = call.call_args.args[0]
        self.assertEqual(json.loads(request.data), {
            'parent_route': 'gpu-rig/chat-27b', 'agent_type': 'coding', 'min_context': 4096})
        self.assertEqual(result['route'], 'gpu-rig/coder-7b')

    def test_cloud_parent_requests_local_child_by_capability(self):
        class Reply:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass
            def read(self):
                return b'{"route":"gpu-rig/coder-7b","gpu_ids":[2]}'

        with patch('gateway_subagent.urlopen', return_value=Reply()) as call:
            resolve_child('http://127.0.0.1:8080', 'cloud/codex', 'coding')
        self.assertEqual(json.loads(call.call_args.args[0].data), {
            'parent_route': 'cloud/codex', 'agent_type': 'coding', 'min_context': 4096})

    def test_public_research_profile_uses_only_approved_harness_search_tools(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            agent = root / 'agent'
            agent.mkdir()
            registry = root / 'registry.json'
            registry.write_text(json.dumps({'surfaces': {'rig_search': {
                'status': 'dashboard', 'tools': [
                    {'name': 'search_web', 'approval': 'automatic'},
                    {'name': 'fetch_page', 'approval': 'automatic'}]}}}))
            server = root / 'search.py'
            server.write_text('')
            env_file = root / '.env'
            env_file.write_text('')
            with patch.object(gateway_subagent, 'TOOL_REGISTRY', registry), \
                 patch.object(gateway_subagent, 'SEARCH_SERVER', server), \
                 patch.dict('os.environ', {'RIG_SEARCH_ENV_FILE': str(env_file)}):
                flags = gateway_subagent._child_tools(agent, root, 'public_research')
                assert flags == ['--no-tools', '--no-mcp']
                config = json.loads((agent / 'mcp.json').read_text())['mcpServers']['rig_search']
                assert config['toolExposure'] == {'search_web': 'direct', 'fetch_page': 'direct'}
                assert config['args'][-2:] == ['--providers', 'searxng']
                assert gateway_subagent._child_tools(agent, root, 'none') == ['--no-tools', '--no-mcp']
                registry.write_text(json.dumps({'surfaces': {'rig_search': {
                    'status': 'dashboard', 'tools': [
                        {'name': 'search_web', 'approval': 'automatic'},
                        {'name': 'fetch_page', 'approval': 'disabled'}]}}}))
                with self.assertRaisesRegex(ValueError, 'not approved'):
                    gateway_subagent._child_tools(agent, root, 'public_research')

    def test_workspace_read_profile_is_bound_to_selected_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            agent = root / 'agent'
            agent.mkdir()
            workspace = root / 'workspace'
            workspace.mkdir()
            registry = root / 'registry.json'
            registry.write_text(json.dumps({'surfaces': {'workspace_read': {
                'status': 'dashboard', 'tools': [
                    {'name': 'list_workspace_files', 'approval': 'automatic'},
                    {'name': 'find_workspace_files', 'approval': 'automatic'},
                    {'name': 'read_workspace_file', 'approval': 'automatic'},
                    {'name': 'read_workspace_document_chunk', 'approval': 'automatic'},
                    {'name': 'search_workspace_text', 'approval': 'automatic'}]}}}))
            server = root / 'workspace_read_mcp.py'
            server.write_text('')
            with patch.object(gateway_subagent, 'TOOL_REGISTRY', registry), \
                 patch.object(gateway_subagent, 'WORKSPACE_SERVER', server):
                flags = gateway_subagent._child_tools(agent, root, 'workspace_read', workspace)
            self.assertEqual(flags, ['--no-tools', '--no-mcp'])
            config = json.loads((agent / 'mcp.json').read_text())['mcpServers']['workspace_read']
            self.assertEqual(config['args'], [str(server), '--root', str(workspace)])
            with self.assertRaisesRegex(ValueError, 'selected root'):
                run_child(parent_id='cloud/codex', agent_type='coding', prompt='review',
                          out=root / 'child', gateway='http://127.0.0.1:8080',
                          tool_profile='workspace_read')

    def test_workspace_git_profile_is_bound_to_selected_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            agent = root / 'agent'
            agent.mkdir()
            workspace = root / 'workspace'
            workspace.mkdir()
            names = ('get_workspace_git_status', 'get_workspace_git_log',
                     'get_workspace_git_diff', 'get_workspace_git_commit',
                     'compare_workspace_git_revisions', 'read_workspace_file_at_revision',
                     'get_workspace_file_history')
            registry = root / 'registry.json'
            registry.write_text(json.dumps({'surfaces': {'workspace_git': {
                'status': 'dashboard',
                'tools': [{'name': name, 'approval': 'automatic'} for name in names]}}}))
            server = root / 'workspace_git_mcp.py'
            server.write_text('')
            with patch.object(gateway_subagent, 'TOOL_REGISTRY', registry), \
                 patch.object(gateway_subagent, 'WORKSPACE_GIT_SERVER', server):
                flags = gateway_subagent._child_tools(agent, root, 'workspace_git', workspace)
            self.assertEqual(flags, ['--no-tools', '--no-mcp'])
            config = json.loads((agent / 'mcp.json').read_text())['mcpServers']['workspace_git']
            self.assertEqual(config['args'], [str(server), '--root', str(workspace)])
            self.assertEqual(set(config['toolExposure']), set(names))

    def test_google_profile_uses_same_catalog_for_any_local_model(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            agent = root / 'agent'
            agent.mkdir()
            registry = root / 'registry.json'
            registry.write_text(json.dumps({'surfaces': {'google_workspace': {
                'status': 'dashboard', 'tools': [
                    {'name': 'search_mail', 'approval': 'automatic'},
                    {'name': 'send_email', 'approval': 'automatic'}]}}}))
            server = root / 'google_workspace_mcp.py'
            server.write_text('')
            with patch.object(gateway_subagent, 'TOOL_REGISTRY', registry), \
                 patch.object(gateway_subagent, 'GOOGLE_SERVER', server):
                flags = gateway_subagent._child_tools(agent, root, 'google_workspace')
            self.assertEqual(flags, ['--no-builtin-tools', '--tools',
                                     'mcp__google_workspace__*'])
            config = json.loads((agent / 'mcp.json').read_text())['mcpServers']['google_workspace']
            self.assertEqual(config['args'], [str(server)])
            self.assertEqual(config['toolExposure'], {
                'search_mail': 'direct', 'send_email': 'direct'})

    def test_cloud_parent_can_request_shared_35b_without_gpu_selection(self):
        class Reply:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass
            def read(self):
                return b'{"route":"gpu-rig/shared-35b-child-test","gpu_ids":[3]}'

        with patch('gateway_subagent.urlopen', return_value=Reply()) as call:
            resolve_child('http://127.0.0.1:8080', 'cloud/codex', 'research',
                          'qwen35_shared_1060')
        self.assertEqual(json.loads(call.call_args.args[0].data), {
            'parent_route': 'cloud/codex', 'agent_type': 'research',
            'candidate_id': 'qwen35_shared_1060', 'min_context': 4096})

    def test_cloud_parent_can_request_named_separate_model_candidate(self):
        class Reply:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass
            def read(self):
                return b'{"route":"gpu-rig/small","gpu_ids":[2]}'

        with patch('gateway_subagent.urlopen', return_value=Reply()) as call:
            resolve_child('http://127.0.0.1:8080', 'cloud/codex', 'coding',
                          'small_worker', worker_strategy='separate_model')
        self.assertEqual(json.loads(call.call_args.args[0].data), {
            'parent_route': 'cloud/codex', 'agent_type': 'coding',
            'candidate_id': 'small_worker', 'min_context': 4096,
            'worker_strategy': 'separate_model'})

    def test_cloud_parent_child_receipt_does_not_require_local_parent_roster(self):
        reservation = {'context_capacity': 8192, 'placement': {'gpus': [2]},
                       'reserved_mib': 1400, 'reservation_scope': 'gpu_exclusive'}
        child = {'route': 'gpu-rig/coder-7b', 'gpu_ids': [2],
                 'model': 'qwen2.5-coder:7b', 'context_length': 8192,
                 'service_instance_id': 'worker-load-1', 'reservation': reservation,
                 'admission': {'mode': 'shared_model', 'reservation': reservation}}
        ready = {'id': child['route'], 'gpu_ids': [2], 'model': child['model']}
        project = {'engine': 'big-bertha-project-agent', 'engine_version': 1,
                   'answer': 'Review complete', 'error': None, 'duration_s': 0.1,
                   'tool_calls': 0, 'tool_call_summary': [],
                   'tool_budget': {'calls': 0}, 'tool_batch_limit': 4,
                   'model_steps': 1, 'max_model_steps': 6,
                   'tool_format_repair_attempted': False}

        with tempfile.TemporaryDirectory() as temp, \
             patch('gateway_subagent.fetch_ready_roster', side_effect=[
                 {'data': []}, {'data': [ready]}, {'data': [ready]}]), \
             patch('gateway_subagent.resolve_child', return_value=child), \
             patch('gateway_subagent.run_project_agent', return_value=project):
            receipt = run_child(parent_id='cloud/codex', agent_type='coding',
                                prompt='Review this design', out=Path(temp) / 'child',
                                gateway='http://127.0.0.1:8080')
        self.assertTrue(receipt['roster_stable'])
        self.assertEqual(receipt['parent_gpu_ids'], [])
        self.assertEqual(receipt['answer'], 'Review complete')
        self.assertEqual(receipt['service_instance_id'], 'worker-load-1')
        self.assertEqual(receipt['reservation']['context_capacity'], 8192)
        self.assertEqual(receipt['admission']['mode'], 'shared_model')

    def test_public_child_text_tool_request_is_executed_and_recorded(self):
        child = {'route': 'gpu-rig/child', 'gpu_ids': [2],
                 'model': 'test-model', 'context_length': 8192}
        ready = {'id': child['route'], 'gpu_ids': [2], 'model': child['model']}
        project = {'engine': 'big-bertha-project-agent', 'engine_version': 1,
                   'answer': 'Found an official source.', 'error': None, 'duration_s': 0.2,
                   'tool_calls': 1,
                   'tool_call_summary': [{'tool': 'search_web', 'is_error': False}],
                   'tool_budget': {'calls': 1}, 'tool_batch_limit': 4,
                   'model_steps': 2, 'max_model_steps': 6,
                   'tool_format_repair_attempted': False}
        def configure(agent, out, profile, workspace_root):
            (agent / 'mcp.json').write_text(json.dumps({'mcpServers': {'rig_search': {
                'command': sys.executable, 'args': ['search_server.py'],
                'toolExposure': {'search_web': 'direct', 'fetch_page': 'direct'}}}}))
            return ['--tools', 'mcp__rig_search__search_web']
        with tempfile.TemporaryDirectory() as temp, \
             patch('gateway_subagent.fetch_ready_roster', side_effect=[
                 {'data': []}, {'data': [ready]}, {'data': [ready]}]), \
             patch('gateway_subagent.resolve_child', return_value=child), \
             patch('gateway_subagent._child_tools', side_effect=configure), \
             patch('gateway_subagent.discover_tools', return_value=[
                 {'name': 'search_web', 'inputSchema': {'type': 'object'}},
                 {'name': 'fetch_page', 'inputSchema': {'type': 'object'}}]), \
             patch('gateway_subagent.run_project_agent', return_value=project) as run:
            receipt = run_child(parent_id='cloud/codex', agent_type='research',
                                prompt='Find the docs', out=Path(temp) / 'child',
                                gateway='http://127.0.0.1:8080', tool_profile='public_research')
        self.assertEqual(receipt['tool_mode'], 'project_agent')
        self.assertEqual(receipt['tool_calls'], 1)
        self.assertEqual(receipt['answer'], 'Found an official source.')
        self.assertIsNone(receipt['error'])
        self.assertEqual(run.call_args.kwargs['tool_server']['tools'], ['search_web', 'fetch_page'])
        self.assertEqual(len(run.call_args.kwargs['tool_server']['definitions']), 2)
        self.assertEqual(run.call_args.kwargs['journal_root'], Path(temp) / 'child' / 'journal')

    def test_ephemeral_child_is_released_when_post_attach_roster_fails(self):
        parent = {'id': 'gpu-rig/shared-35b-main', 'model': 'qwen3.6:35b-a3b-xl',
                  'state': 'ready', 'context_length': 262144, 'gpu_ids': [0]}
        child = {'route': 'gpu-rig/shared-35b-child-test', 'gpu_ids': [2],
                 'model': parent['model'], 'context_length': 262144, 'ephemeral': True,
                 'service_instance_id': 'load-1',
                 'reservation': {'reservation_id': 'reserve-1',
                                 'service_instance_id': 'load-1'},
                 'admission': {'mode': 'shared_model', 'service_instance_id': 'load-1',
                               'reservation_id': 'reserve-1'}}
        with tempfile.TemporaryDirectory() as temp, \
             patch('gateway_subagent.fetch_ready_roster', side_effect=[
                 {'object': 'ready_roster', 'version': 1, 'data': [parent]},
                 {'object': 'ready_roster', 'version': 1, 'data': [parent]}]), \
             patch('gateway_subagent.resolve_child', return_value=child), \
             patch('gateway_subagent.release_child') as release:
            with self.assertRaisesRegex(ValueError, 'ready roster'):
                run_child(parent_id=parent['id'], agent_type='coding', prompt='check',
                          out=Path(temp) / 'child', gateway='http://127.0.0.1:8080')
        release.assert_called_once_with(
            'http://127.0.0.1:8080', parent['id'], child['route'],
            service_instance_id='load-1', reservation_id='reserve-1')

    def test_ephemeral_child_requires_a_consistent_admission_receipt(self):
        child = {'route': 'gpu-rig/shared-35b-child-test', 'gpu_ids': [2],
                 'model': 'qwen3.6:35b-a3b-xl', 'context_length': 32768,
                 'ephemeral': True, 'service_instance_id': 'load-1',
                 'reservation': {'reservation_id': 'reserve-1',
                                 'service_instance_id': 'different-load'},
                 'admission': {'mode': 'shared_model', 'service_instance_id': 'load-1',
                               'reservation_id': 'reserve-1'}}
        with tempfile.TemporaryDirectory() as temp, \
             patch('gateway_subagent.fetch_ready_roster', return_value={'data': []}), \
             patch('gateway_subagent.resolve_child', return_value=child), \
             patch('gateway_subagent.release_child') as release:
            with self.assertRaisesRegex(ValueError, 'another service instance'):
                run_child(parent_id='cloud/codex', agent_type='coding', prompt='check',
                          out=Path(temp) / 'child', gateway='http://127.0.0.1:8080')
        release.assert_called_once_with(
            'http://127.0.0.1:8080', 'cloud/codex', child['route'],
            service_instance_id='load-1', reservation_id='reserve-1')

    def test_mcp_launch_arguments_expose_simple_tool(self):
        server = Path(__file__).resolve().parents[1] / 'tools/gateway_subagent_mcp.py'
        with tempfile.TemporaryDirectory() as temp:
            packet = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}) + '\n'
            proc = subprocess.run([sys.executable, str(server), '--parent-route', 'gpu-rig/parent',
                                   '--receipt-dir', temp], input=packet, text=True,
                                  capture_output=True, timeout=5)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        tools = json.loads(proc.stdout)['result']['tools']
        self.assertEqual([tool['name'] for tool in tools], ['list_local_agents', 'delegate_task'])
        self.assertEqual(set(tools[1]['inputSchema']['properties']),
                         {'agent_type', 'task', 'acceptance_criteria', 'verification',
                          'minimum_context_tokens', 'context_tokens', 'worker_strategy',
                          'tool_profile', 'max_tool_calls'})
        self.assertEqual(tools[1]['inputSchema']['properties']['agent_type']['enum'],
                         ['coding', 'research'])

    def test_cloud_parent_mcp_exposes_local_only_tool(self):
        server = Path(__file__).resolve().parents[1] / 'tools/gateway_subagent_mcp.py'
        with tempfile.TemporaryDirectory() as temp:
            packet = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}) + '\n'
            proc = subprocess.run([sys.executable, str(server), '--cloud-parent',
                                   '--receipt-dir', temp], input=packet, text=True,
                                  capture_output=True, timeout=5)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        tools = json.loads(proc.stdout)['result']['tools']
        self.assertEqual([row['name'] for row in tools],
                         ['list_local_agents', 'swap_local_agent_model', 'delegate_task'])
        self.assertEqual(tools[1]['inputSchema']['properties']['confirmation']['enum'],
                         ['swap local agent model'])
        tool = tools[2]
        self.assertEqual(tool['name'], 'delegate_task')
        self.assertEqual(set(tool['inputSchema']['properties']),
                         {'agent_type', 'task', 'acceptance_criteria', 'verification',
                          'candidate_id', 'minimum_context_tokens', 'context_tokens',
                          'worker_strategy', 'tool_profile', 'max_tool_calls'})
        self.assertEqual(tool['inputSchema']['properties']['candidate_id']['maxLength'], 80)
        self.assertIn('loaded shared model', tool['description'])
        self.assertEqual(tool['inputSchema']['properties']['tool_profile']['enum'],
                         ['none', 'public_research', 'google_workspace'])

    def test_cloud_parent_with_workspace_exposes_read_profile(self):
        server = Path(__file__).resolve().parents[1] / 'tools/gateway_subagent_mcp.py'
        with tempfile.TemporaryDirectory() as temp:
            packet = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}) + '\n'
            proc = subprocess.run([sys.executable, str(server), '--cloud-parent',
                                   '--receipt-dir', temp, '--workspace-root', temp],
                                  input=packet, text=True, capture_output=True, timeout=5)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        tools = json.loads(proc.stdout)['result']['tools']
        self.assertIn('workspace_read', tools[2]['inputSchema']['properties']['tool_profile']['enum'])
        self.assertIn('workspace_git', tools[2]['inputSchema']['properties']['tool_profile']['enum'])

    def test_cloud_model_swap_requires_explicit_confirmation(self):
        server = Path(__file__).resolve().parents[1] / 'tools/gateway_subagent_mcp.py'
        with tempfile.TemporaryDirectory() as temp:
            packet = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                'params': {'name': 'swap_local_agent_model', 'arguments': {
                    'candidate_id': 'qwen35_shared_1060',
                    'expected_candidate_id': 'nemotron74_shared_1060',
                    'expected_instance_id': 'load-1', 'confirmation': 'yes'}}}) + '\n'
            proc = subprocess.run([sys.executable, str(server), '--cloud-parent',
                                   '--receipt-dir', temp], input=packet, text=True,
                                  capture_output=True, timeout=5)
        result = json.loads(proc.stdout)['result']
        self.assertTrue(result['isError'])
        self.assertIn('invalid swap_local_agent_model arguments', result['content'][0]['text'])


if __name__ == '__main__':
    unittest.main()
