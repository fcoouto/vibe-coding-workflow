"""Deterministic recovery policy; no provider outage or native send is simulated as real."""
import importlib
import json
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch


class ParentRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime.parent_recovery'), 'Parent recovery runtime missing')
        self.api = importlib.import_module('runtime.parent_recovery')
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name).resolve() / 'monitor'
        self.parent = dict(thread_id='parent-one', cwd='/fixture', identity=dict(client='codex',
            session_id='parent-one', task_id='task', scope_ref='scope'), pins={'runtime':'original'}, deadline=9000, workstream_revision=1)

    def call(self, action, now=1000, **request):
        return self.api.control(self.directory, action, request, now=now)

    def register(self, parent=None, now=1000):
        return self.call('register', now, parent=parent or self.parent)

    def observe(self, now, **updates):
        observation=dict(thread_status='idle', turn_status='failed', turn_id='failure-one',
            error_code='serverOverloaded', will_retry=False, authority='eligible')
        return self.call('observe', now, thread_id='parent-one', observation=observation | updates)

    def test_default_status_creates_nothing_and_first_parent_requests_schedule(self):
        self.assertEqual(self.call('status')['wanted'], 'absent')
        self.assertFalse(self.directory.exists())
        self.assertEqual(self.register()['wanted'], 'present')

    def test_shared_schedule_and_final_withdrawal_delete(self):
        self.register()
        op=self.call('schedule', observed='absent')
        self.assertEqual(op['operation'], 'create')
        self.call('record-schedule', token=op['token'], result='created', schedule_id='shared')
        self.register(self.parent | dict(thread_id='parent-two', identity=self.parent['identity'] | dict(session_id='parent-two')))
        self.call('withdraw', thread_id='parent-one')
        self.assertEqual(self.call('schedule', observed='active', schedule_id='shared')['operation'], 'none')
        self.call('withdraw', thread_id='parent-two')
        self.assertEqual(self.call('schedule', observed='active', schedule_id='shared')['operation'], 'delete')

    def test_activation_during_delete_requires_recreation_after_ack(self):
        self.register(); create=self.call('schedule', observed='absent')
        self.call('record-schedule', token=create['token'], result='created', schedule_id='shared')
        self.call('withdraw', thread_id='parent-one')
        delete=self.call('schedule', observed='active', schedule_id='shared')
        self.call('reactivate', thread_id='parent-one')
        self.assertEqual(self.call('schedule', observed='active', schedule_id='shared')['operation'], 'pending')
        self.assertEqual(self.call('record-schedule', token=delete['token'], result='deleted', schedule_id='shared')['wanted'], 'present')
        self.assertEqual(self.call('schedule', observed='absent')['operation'], 'create')

    def test_manual_pause_and_deletion_never_recreate(self):
        self.register(); create=self.call('schedule', observed='absent')
        self.call('record-schedule', token=create['token'], result='created', schedule_id='shared')
        self.assertEqual(self.call('schedule', observed='paused', schedule_id='shared')['operation'], 'none')
        self.assertTrue(self.call('status')['suspended'])
        self.assertEqual(self.call('schedule', observed='absent')['operation'], 'none')
        self.register()
        self.assertTrue(self.call('status')['suspended'])

    def test_human_reactivation_after_confirmed_deletion_can_create_again(self):
        self.register(); create=self.call('schedule', observed='absent')
        self.call('record-schedule', token=create['token'], result='created', schedule_id='shared')
        self.call('schedule', observed='absent')
        self.call('reactivate', thread_id='parent-one', schedule_absent=True)
        self.assertEqual(self.call('schedule', observed='absent')['operation'], 'create')

    def test_corrupt_eligibility_never_authorizes_delivery(self):
        import json
        self.register()
        path=self.directory / 'monitor.json'
        data=json.loads(path.read_text())
        data['parents']['parent-one']['eligible']='yes'
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            self.observe(1060)

    def test_fixed_window_duplicate_intents_and_lost_ack(self):
        self.register(); self.observe(1000)
        self.assertFalse(self.observe(1059)['send'])
        ready=self.observe(1060)
        self.assertTrue(ready['send'])
        self.assertFalse(self.observe(1120)['send'])
        self.call('record-send', 1120, thread_id='parent-one', token=ready['token'], result='uncertain')
        self.assertFalse(self.observe(1180)['send'])
        resumed=self.observe(1240, thread_status='active', turn_status='inProgress', turn_id='new-turn')
        self.assertFalse(resumed['send'])
        self.assertEqual(self.observe(1300, turn_id='second-failure')['deadline'], 4600)
        self.assertFalse(self.observe(4600, turn_id='third-failure')['send'])
        self.assertEqual(self.call('status')['wanted'], 'absent')

    def test_full_hour_has_fixed_opportunities_without_backoff_or_reset(self):
        self.register(); self.observe(1000, will_retry=None)
        for minute in range(1, 60):
            now=1000 + minute * 60
            result=self.observe(now, turn_id='failed-' + str(minute), will_retry=None)
            self.assertTrue(result['send'], minute)
            self.assertEqual(result['deadline'], 4600)
            self.call('record-send', now, thread_id='parent-one', token=result['token'], result='sent')
            self.observe(now + 1, turn_id='running-' + str(minute), thread_status='active', turn_status='inProgress')
        self.assertFalse(self.observe(4600, turn_id='last-failure')['send'])

    def test_delayed_old_turn_cannot_erase_consumed_source_turn(self):
        self.register(); self.observe(1000, turn_id='A')
        a=self.observe(1060, turn_id='A')
        self.call('record-send', 1060, thread_id='parent-one', token=a['token'], result='uncertain')
        b=self.observe(1120, turn_id='B')
        self.assertTrue(b['send'])
        self.call('record-send', 1120, thread_id='parent-one', token=b['token'], result='uncertain')
        self.observe(1180, turn_id='A')
        self.assertFalse(self.observe(1240, turn_id='B')['send'])

    def test_departed_registration_accepts_a_different_current_assignment(self):
        self.register(); self.call('withdraw', thread_id='parent-one')
        new=self.parent | dict(identity=self.parent['identity'] | dict(task_id='next-task'))
        self.assertEqual(self.register(new)['wanted'], 'present')
        self.assertEqual(self.call('status')['parents']['parent-one']['parent']['identity']['task_id'], 'next-task')

    def test_expired_inactive_history_is_archived_across_many_serial_tasks(self):
        for index in range(250):
            now = 1000 + index * 10
            identity = 'parent-' + str(index)
            parent = self.parent | dict(thread_id=identity, deadline=now + 5,
                identity=self.parent['identity'] | dict(session_id=identity))
            self.register(parent, now)
            self.call('withdraw', now + 1, thread_id=identity)
        self.call('schedule', 3500, observed='absent')
        self.assertEqual(self.call('status')['parents'], {})
        archives = list(self.directory.glob('history-*.json'))
        self.assertEqual(len(archives), 250)
        first = next(json.loads(p.read_text())['registration'] for p in archives
            if json.loads(p.read_text())['registration']['parent']['thread_id'] == 'parent-0')
        self.assertFalse(first['eligible'])
        with self.assertRaisesRegex(ValueError, 'expired'):
            self.register(first['parent'], 3501)
        with self.assertRaisesRegex(ValueError, 'not registered'):
            self.call('reactivate', 3501, thread_id='parent-0')

    def test_archival_retry_after_registry_commit_failure_preserves_one_audit(self):
        self.register(self.parent | dict(deadline=1005))
        self.call('withdraw', 1001, thread_id='parent-one')
        path = self.directory / 'monitor.json'
        before = path.read_bytes()
        original = self.api.d6._atomic
        def commit(target, value, guard=None):
            if target == path:
                raise OSError('Interrupted registry commit')
            return original(target, value, guard)
        with patch.object(self.api.d6, '_atomic', side_effect=commit):
            with self.assertRaisesRegex(OSError, 'Interrupted'):
                self.call('schedule', 1010, observed='absent')
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(list(self.directory.glob('history-*.json'))), 1)
        self.call('schedule', 1010, observed='absent')
        self.assertEqual(self.call('status')['parents'], {})
        self.assertEqual(len(list(self.directory.glob('history-*.json'))), 1)

    def test_archival_rejects_an_unsafe_existing_audit(self):
        from runtime import evidence
        self.register(self.parent | dict(deadline=1005))
        self.call('withdraw', 1001, thread_id='parent-one')
        record = self.call('status')['parents']['parent-one']
        value = dict(version=1, registration=record)
        outside = self.directory.parent / 'outside.json'
        outside.write_text('unchanged')
        audit = self.directory / ('history-' + evidence._digest(value) + '.json')
        audit.symlink_to(outside)
        with self.assertRaises(ValueError):
            self.call('schedule', 1010, observed='absent')
        self.assertEqual(outside.read_text(), 'unchanged')
        self.assertIn('parent-one', self.call('status')['parents'])

    def test_archival_retains_unexpired_episode_history_and_uncertain_delivery(self):
        self.register(); self.observe(1000)
        ready = self.observe(1060)
        self.call('record-send', 1060, thread_id='parent-one', token=ready['token'], result='uncertain')
        self.call('withdraw', 1060, thread_id='parent-one')
        before = self.call('status')['parents']['parent-one']
        self.call('schedule', 1100, observed='absent')
        self.assertEqual(self.call('status')['parents']['parent-one'], before)
        self.call('schedule', 9001, observed='absent')
        self.assertEqual(self.call('status')['parents']['parent-one'], before)
        self.assertEqual(list(self.directory.glob('history-*.json')), [])
        self.directory = self.directory.parent / 'replacement-history'
        self.register(); self.call('withdraw', thread_id='parent-one')
        next_parent = self.parent | dict(identity=self.parent['identity'] | dict(task_id='next-task'), deadline=10000)
        self.register(next_parent)
        self.call('withdraw', thread_id='parent-one')
        self.call('schedule', 9001, observed='absent')
        self.assertEqual(len(list(self.directory.glob('history-*.json'))), 1)
        self.assertEqual(self.call('status')['parents']['parent-one']['parent'], next_parent)

    def test_unreported_shutdown_can_be_suspended_without_deadline_reset(self):
        self.register(); self.observe(1000)
        self.call('suspend')
        self.assertFalse(self.observe(1060)['send'])
        self.call('reactivate', 1100, thread_id='parent-one')
        self.assertEqual(self.observe(1160)['deadline'], 4600)

    def test_native_retry_status_does_not_gate_idle_capacity_recovery(self):
        for index, will_retry in enumerate((None, True, False)):
            with self.subTest(will_retry=will_retry):
                self.directory = self.directory.parent / ('retry-state-' + str(index))
                self.register()
                self.assertFalse(self.observe(1000, will_retry=will_retry)['send'])
                self.assertFalse(self.observe(1059, will_retry=will_retry)['send'])
                ready = self.observe(1060, will_retry=will_retry)
                self.assertTrue(ready['send'])
                self.assertEqual(ready['deadline'], 4600)
                self.assertFalse(self.observe(1120, will_retry=will_retry)['send'])

    def test_active_unknown_or_noncapacity_parent_suppresses_when_retry_is_due(self):
        self.register()
        self.observe(1000, will_retry=None)
        for fields in (dict(thread_status='active'), dict(thread_status='unknown'),
                       dict(authority='unknown'), dict(turn_status='inProgress'),
                       dict(turn_status='interrupted'), dict(error_code=None),
                       dict(error_code='responseStreamDisconnected')):
            self.assertFalse(self.observe(1060, will_retry=None, **fields)['send'])

    def test_account_limit_removes_parent_and_human_reactivation_preserves_deadline(self):
        self.register(); self.observe(1000)
        self.observe(1060, error_code='usageLimitExceeded')
        self.assertEqual(self.call('status')['wanted'], 'absent')
        self.register(now=2000)
        self.assertEqual(self.call('status')['wanted'], 'absent')
        self.call('reactivate', 2000, thread_id='parent-one')
        self.assertEqual(self.observe(2060)['deadline'], 4600)

    def test_concurrent_schedule_claims_have_one_owner(self):
        self.register()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:self.call('schedule', observed='absent'), range(4)))
        self.assertEqual(sum(r['operation']=='create' for r in results), 1)

    def test_clock_rollback_and_unknown_authority_keep_membership_without_sending(self):
        self.register(); self.observe(1100)
        self.assertFalse(self.observe(1000)['send'])
        self.assertFalse(self.observe(1160, authority='unknown')['send'])
        self.assertEqual(self.call('status')['wanted'], 'present')

    def test_symlink_directory_rejected(self):
        self.directory.symlink_to(self.directory.parent, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)):
            self.register()

    def test_registration_checks_real_task_mode_and_original_deadline(self):
        from runtime import workstreams
        from tests.test_delegation import AdmissionTests
        fixture = AdmissionTests(methodName='runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        plan = fixture.plan_value()
        fixture.plan(plan)
        # This case starts with a legacy, never-enabled checkout.
        workstreams._path(fixture.scope).unlink(missing_ok=True)
        request = fixture.request(workstream_revision=1)
        with self.assertRaises(Exception):
            self.api.register(fixture.scope, self.directory, request)
        self.assertFalse(self.directory.exists())
        workstreams.control(fixture.scope, 'enable', dict(client='codex', expected_revision=0))
        result = self.api.register(fixture.scope, self.directory, request)
        saved = result['parents'][fixture.identity['session_id']]['parent']
        self.assertEqual(saved['deadline'], plan['limits']['deadline'])
        self.assertEqual(saved['identity'], fixture.identity)

    def test_current_binding_and_mode_generation_are_required(self):
        from runtime import state, workstreams
        from tests.test_delegation import AdmissionTests
        from unittest.mock import patch
        import time
        fixture=AdmissionTests(methodName='runTest'); fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.plan()
        workstreams.control(fixture.scope, 'enable', dict(client='codex',
            expected_revision=workstreams.control(fixture.scope,'status',dict(client='codex'))['revision']))
        request=fixture.request(workstream_revision=1)
        self.api.register(fixture.scope, self.directory, request)
        thread=fixture.identity['session_id']; now=int(time.time())
        observation=dict(thread_status='idle',turn_status='failed',turn_id='failed',error_code='serverOverloaded',will_retry=False)
        with patch('runtime.startup.resolve_project',return_value=fixture.scope):
            self.api.observe(self.directory,dict(thread_id=thread,observation=observation),state.PACKAGE)
            workstreams.control(fixture.scope,'disable',dict(client='codex',expected_revision=1))
            workstreams.control(fixture.scope,'enable',dict(client='codex',expected_revision=2))
            with patch('runtime.parent_recovery.time.time',return_value=now+60):
                self.assertFalse(self.api.observe(self.directory,dict(thread_id=thread,observation=observation),state.PACKAGE)['send'])
            self.assertFalse(self.call('status')['parents'][thread]['eligible'])
            self.api.reactivate(self.directory,dict(thread_id=thread),state.PACKAGE)
        old=state.task_status(fixture.scope,'codex',thread)['task']
        state.start_task(fixture.scope,fixture.identity | dict(task_id='replacement',mode='editable',decision_ref='user:new',
            replaces=dict(task_id=old['task_id'],expected_revision=old['revision'])))
        with patch('runtime.startup.resolve_project',return_value=fixture.scope), patch('runtime.parent_recovery.time.time',return_value=now+120):
            self.assertFalse(self.api.observe(self.directory,dict(thread_id=thread,observation=observation),state.PACKAGE)['send'])
        with self.assertRaises(Exception):
            self.api.register(fixture.scope,self.directory,fixture.identity | dict(expected_revision=old['revision']+1,workstream_revision=3))
