"""Reviewed reader compatibility preserves provenance without accepting unknown packages."""
from copy import deepcopy
from unittest.mock import patch
import unittest

from runtime import startup, state


class PackageCompatibilityTests(unittest.TestCase):
    def test_supported_pair_and_exact_package_are_compatible_but_mixed_pins_are_not(self):
        original = dict(policy_digest='a' * 64, runtime_digest='b' * 64)
        installed = dict(policy_digest='c' * 64, runtime_digest='d' * 64)
        with patch.object(startup, 'COMPATIBLE_PACKAGE_PINS', {(original['policy_digest'], original['runtime_digest'])}, create=True):
            self.assertTrue(startup._package_compatible(original, installed))
            self.assertTrue(startup._package_compatible(installed, installed))
            self.assertFalse(startup._package_compatible(original | dict(runtime_digest='d' * 64), installed))

    def test_current_task_survives_reviewed_runtime_update_without_repinning(self):
        from tests.fixture_canonical_birth import fresh_canonical
        _, acquisition, _ = fresh_canonical(self)
        scope = startup._entry_scope(acquisition)
        request = dict(client='codex', session_id='session', task_id='task', scope_ref='user:task')
        task = state.start_task(scope, request | dict(mode='editable', decision_ref='user:accepted'))['task']
        original = deepcopy(task['pins'])
        with patch.object(startup, 'COMPATIBLE_PACKAGE_PINS', {(original['policy_digest'], original['runtime_digest'])}, create=True), \
                patch.object(state, 'runtime_fingerprint', return_value='f' * 64):
            updated = state.update_task(scope, request | dict(expected_revision=task['revision'],
                state='WORKING', reason='Continue accepted task', reference='user:accepted'))['task']
        self.assertEqual(updated['pins'], original)
        self.assertEqual(updated['accepted_identity'], task['accepted_identity'])
