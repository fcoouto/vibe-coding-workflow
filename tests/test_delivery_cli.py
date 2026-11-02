"""Public delivery controls expose local reads, never owner mutations."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from scripts import workflow
from tests import test_delivery


class DeliveryCLITests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_delivery.DeliveryPlanTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.scope = self.fixture.scope

    def call(self, *arguments):
        output = io.StringIO()
        with patch('sys.argv', ['workflow.py', 'delivery', *arguments, '--cwd', str(self.scope.repository_root)]), \
                patch('runtime.startup.acquire_project_entry', return_value=object()), \
                patch('runtime.startup._entry_scope', return_value=self.scope), contextlib.redirect_stdout(output):
            code = workflow.main()
        return code, json.loads(output.getvalue())

    def test_status_and_pending_are_local_reads(self):
        from runtime.adapters.github_delivery import GitHubDelivery
        with patch.object(GitHubDelivery, 'observe', side_effect=AssertionError('Unexpected provider call')):
            code, status = self.call('status', '--client', 'codex', '--session', 'delivery')
            self.assertEqual(code, 0, status)
            self.assertFalse(status['delivery_complete'])
            code, result = self.call('pending', '--client', 'codex')
            self.assertEqual(code, 0, result)
            self.assertEqual(len(result['records']), 1)
        self.assertNotIn('merge_authorized', status)

    def test_public_cli_does_not_accept_mutation_or_raw_merged_claims(self):
        for action in ('merge', 'reconcile', 'ready', 'checkpoint', 'cleanup'):
            code, result = self.call(action, '--client', 'codex')
            self.assertEqual(code, 1)
            self.assertFalse(result['ok'])
