"""Strict package matching rejects upgrades without rewriting saved provenance."""
from copy import deepcopy
from unittest.mock import patch
import unittest

from runtime import startup, state


class PackageCompatibilityTests(unittest.TestCase):
    def test_exact_package_matches_but_prior_and_mixed_pairs_do_not(self):
        original = dict(policy_digest='bb131d4f891b5e51d0e7803f0b39263b09ae5a7a99d96fd89444fa0871809c1b',
            runtime_digest='9782f25e8c8fde75191a0f80b8cd325a667ac1619b7b7c5f1c053e1004da137a')
        installed = dict(policy_digest='c' * 64, runtime_digest='d' * 64)
        self.assertFalse(startup._package_compatible(original, installed))
        self.assertTrue(startup._package_compatible(installed, installed))
        self.assertFalse(startup._package_compatible(original | dict(runtime_digest='d' * 64), installed))
        self.assertFalse(startup._package_compatible(installed, installed | dict(policy_digest='e' * 64)))

    def test_current_task_rejects_changed_runtime_without_repinning(self):
        from tests.fixture_canonical_birth import fresh_canonical
        _, acquisition, _ = fresh_canonical(self)
        scope = startup._entry_scope(acquisition)
        request = dict(client='codex', session_id='session', task_id='task', scope_ref='user:task')
        task = state.start_task(scope, request | dict(mode='editable', decision_ref='user:accepted'))['task']
        original = deepcopy(task['pins'])
        with patch.object(state, 'runtime_fingerprint', return_value='f' * 64), self.assertRaises(state.StateError):
            state.update_task(scope, request | dict(expected_revision=task['revision'],
                state='WORKING', reason='Continue accepted task', reference='user:accepted'))
        updated = state.task_status(scope, 'codex', 'session')['task']
        self.assertEqual(updated['pins'], original)
        self.assertEqual(updated['accepted_identity'], task['accepted_identity'])
        self.assertEqual(updated['revision'], task['revision'])
