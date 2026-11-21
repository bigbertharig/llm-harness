import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from child_policy import ToolBudget, child_slot, validate_request


class ChildPolicyTests(unittest.TestCase):
    def test_profile_and_private_query_boundary(self):
        validate_request('workspace_read', 'search_workspace_text', {'query': 'class Agent'}, Path('/tmp/work'))
        with self.assertRaises(ValueError):
            validate_request('workspace_read', 'search_web', {'query': 'public'}, Path('/tmp/work'))
        with self.assertRaises(ValueError):
            validate_request('public_research', 'search_web', {'query': 'password=private'}, None)
        with self.assertRaises(ValueError):
            validate_request('public_research', 'search_web', {'query': '/home/bryan/private'}, None)

    def test_workspace_git_profile_is_read_only_and_separate(self):
        validate_request('workspace_git', 'get_workspace_git_log', {'limit': 3}, Path('/tmp/work'))
        validate_request('workspace_git', 'get_workspace_git_diff', {'path': 'README.md'},
                         Path('/tmp/work'))
        with self.assertRaises(ValueError):
            validate_request('workspace_git', 'read_workspace_file', {'path': 'README.md'},
                             Path('/tmp/work'))
        with self.assertRaises(ValueError):
            validate_request('workspace_read', 'get_workspace_git_status', {}, Path('/tmp/work'))

    def test_call_and_result_budgets(self):
        budget = ToolBudget()
        for _ in range(12):
            budget.before_call()
            budget.record({'content': [{'text': 'ok'}]})
        with self.assertRaises(ValueError):
            budget.before_call()
        with self.assertRaises(ValueError):
            ToolBudget().record({'content': 'x' * 33_000})
        self.assertEqual(budget.receipt()['calls'], 12)

    def test_task_specific_tool_call_budget(self):
        budget = ToolBudget(max_calls=2)
        for _ in range(2):
            budget.before_call()
            budget.record({'content': [{'text': 'ok'}]})
        self.assertEqual(budget.receipt()['max_calls'], 2)
        with self.assertRaises(ValueError):
            budget.before_call()

    def test_cross_process_slot_limit(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {
                'SUBAGENT_SLOT_DIR': temp, 'SUBAGENT_MAX_ACTIVE': '1'}):
            with child_slot():
                with self.assertRaises(RuntimeError):
                    with child_slot():
                        pass
            with child_slot():
                pass


if __name__ == '__main__':
    unittest.main()
