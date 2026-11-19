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
