"""Default rollout preserves legacy intent and grants no dispatch authority."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import unittest
from unittest.mock import patch
from runtime import state, workstreams
from runtime.startup import RuntimeSettings
from tests import test_delegation


class WorkstreamsDefaultTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_delegation.AdmissionTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.scope=replace(self.fixture.scope,runtime=RuntimeSettings(2,self.fixture.root/'fresh-default-authority'))
        self.identity=self.fixture.identity|dict(session_id='default-session',task_id='default-task')

    def start(self,**updates):
        return state.start_task(self.scope,self.identity|dict(mode='editable',decision_ref='user:accepted')|updates)

    def status(self):
        return workstreams.control(self.scope,'status',dict(client='codex'))

    def test_new_supported_scope_starts_enabled_without_launch_authority(self):
        self.start()
        result=self.status()
        self.assertTrue(result['enabled'])
        self.assertEqual(result['revision'],1)
        self.assertEqual(result['unresolved_assignments'],0)
        with self.assertRaises(state.StateError):
            workstreams.consume_dispatch(self.scope,self.identity|dict(expected_revision=1,attempt_id='0'*32,workstream_revision=1))

    def test_existing_missing_legacy_preference_stays_off_on_new_task(self):
        self.start()
        # This isolated fixture models old scopes whose disable left no preference.
        workstreams._path(self.scope).unlink(missing_ok=True)
        self.start(session_id='later',task_id='later')
        self.assertFalse(self.status()['enabled'])
        self.assertEqual(self.status()['revision'],0)

    def test_explicit_disable_survives_new_tasks_and_idempotent_controls(self):
        self.start()
        mode=self.status()
        off=workstreams.control(self.scope,'disable',dict(client='codex',expected_revision=mode['revision']))
        self.start(session_id='later',task_id='later')
        self.assertFalse(self.status()['enabled'])
        self.assertEqual(self.status()['revision'],off['revision'])
        again=workstreams.control(self.scope,'disable',dict(client='codex',expected_revision=off['revision']))
        self.assertEqual(again['revision'],off['revision'])

    def test_first_legacy_disable_is_saved_even_if_already_off(self):
        self.start()
        workstreams._path(self.scope).unlink(missing_ok=True)
        off=workstreams.control(self.scope,'disable',dict(client='codex',expected_revision=0))
        self.assertFalse(off['enabled'])
        self.assertEqual(off['revision'],1)
        self.assertTrue(workstreams._path(self.scope).is_file())

    def test_status_without_runtime_is_read_only_and_off(self):
        self.assertFalse(self.status()['enabled'])
        self.assertFalse(self.scope.runtime.state_dir.exists())

    def test_failed_bootstrap_cannot_dispatch(self):
        with patch.object(state,'_save',side_effect=state.StateError('simulated transaction failure')):
            with self.assertRaises(state.StateError):self.start()
        self.assertIsNone(state.task_status(self.scope,'codex',self.identity['session_id'])['task'])
        with self.assertRaises(state.StateError):
            workstreams.consume_dispatch(self.scope,self.identity|dict(expected_revision=1,attempt_id='0'*32,workstream_revision=1))

    def test_concurrent_first_tasks_share_one_default_revision(self):
        # Initialize only storage so concurrent callers exercise first checkout registration.
        with state._database(self.scope,write=True,initialize=True):
            pass
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda n:self.start(session_id='parallel-'+str(n),task_id='parallel-'+str(n)),range(2)))
        self.assertTrue(self.status()['enabled'])
        self.assertEqual(self.status()['revision'],1)

    def test_publication_before_failed_commit_grants_no_task_authority(self):
        with patch.object(state,'_status',side_effect=state.StateError('simulated post-publication failure')):
            with self.assertRaises(state.StateError):self.start()
        self.assertIsNone(state.task_status(self.scope,'codex',self.identity['session_id'])['task'])
        with self.assertRaises(state.StateError):
            workstreams.consume_dispatch(self.scope,self.identity|dict(expected_revision=1,attempt_id='0'*32,workstream_revision=1))
        self.start()
        self.assertTrue(self.status()['enabled'])
        self.assertEqual(self.status()['revision'],1)

    def test_unsupported_client_cannot_seed_mode(self):
        with self.assertRaises(state.StateError):self.start(client='claude-code')
        self.assertFalse(workstreams._path(self.scope).exists())

    def test_unsupported_canonical_scope_does_not_seed_preferences(self):
        self.scope=replace(self.scope,runtime=RuntimeSettings(3,self.fixture.root/'unsupported-authority'))
        with self.assertRaises(state.StateError):self.start()
        self.assertFalse(self.scope.runtime.state_dir.exists())
