"""Remaining efficiency boundaries over disposable authorities; no native execution."""
from contextlib import contextmanager
import shutil
from types import SimpleNamespace
import time
import unittest
from unittest.mock import patch

from runtime import evidence, resource_admission as host, resource_execution, state, workstreams
from tests import test_resource_execution, test_workstreams


class ResourceEfficiencyTests(unittest.TestCase):
    def setUp(self):
        self.first = self.execution()

    def execution(self):
        fixture = test_resource_execution.ResourceExecutionTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.addCleanup(shutil.rmtree, fixture.directory.parent)
        return fixture

    @contextmanager
    def telemetry(self, probe=None):
        clock = [int(time.time())]
        control = host.control

        def current(directory, action, request, **options):
            return control(directory, action, request, now=clock[0], **options)

        def sample():
            return dict(sampled_at=clock[0], available_memory_bytes=1024 * 1024 * 1024, pressure=False)

        with patch.object(host, 'control', side_effect=current), \
             patch.object(host, 'measure', side_effect=probe or sample) as measured:
            yield clock, measured

    def test_immediate_run_fingerprints_once_at_each_fresh_authority_boundary(self):
        with self.telemetry(), \
             patch.object(state, 'runtime_fingerprint', wraps=state.runtime_fingerprint) as fingerprint, \
             patch.object(resource_execution, '_authority', wraps=resource_execution._authority) as authority:
            result = self.first.call()
        self.assertEqual(result['returncode'], 0)
        self.assertEqual(authority.call_count, 3)
        self.assertEqual(fingerprint.call_count, 3)

    def test_run_uses_locked_request_without_an_unused_status_read(self):
        with self.telemetry(), patch.object(host, 'control', wraps=host.control) as control:
            result = self.first.call()
        self.assertEqual(result['returncode'], 0)
        self.assertEqual([call.args[1] for call in control.call_args_list], ['request'])

    def test_run_still_rejects_corrupt_registry_before_launch(self):
        self.first.directory.mkdir(mode=0o700)
        registry = self.first.directory / 'admission.json'
        registry.write_text('{}')
        registry.chmod(0o600)
        marker = self.first.fixture.fixture.repo / 'must-not-launch'
        with self.assertRaises(state.StateError):
            self.first.call(argv=[self.first.request['argv'][0], '-c',
                'from pathlib import Path; Path(' + repr(str(marker)) + ').touch()'])
        self.assertFalse(marker.exists())

    def test_memory_cache_spans_projects_and_expires_at_the_existing_boundary(self):
        second = self.execution()
        second.directory = self.first.directory
        with self.telemetry() as (clock, measured):
            for fixture, phase, seconds, expected in [
                (self.first, 'a-one', 0, 1), (second, 'b-one', 4, 1), (self.first, 'a-two', 1, 2)
            ]:
                with self.subTest(phase=phase):
                    clock[0] += seconds
                    result = fixture.call(phase_id=phase, capacity_cpu=8)
                    self.assertEqual(result['returncode'], 0)
                    self.assertEqual(measured.call_count, expected)

    def test_shared_memory_pressure_still_blocks_another_project(self):
        second = self.execution()
        second.directory = self.first.directory
        sample = dict(sampled_at=int(time.time()), available_memory_bytes=0, pressure=True)
        with self.telemetry(lambda: sample) as (_, measured):
            self.assertEqual(self.first.call()['reason'], 'host-pressure')
            self.assertEqual(self.first.call('cancel')['state'], 'cancelled')
            result = second.call()
        self.assertEqual(result['reason'], 'host-pressure')
        self.assertFalse(result['admitted'])
        self.assertEqual(measured.call_count, 1)

    def test_shared_telemetry_failure_retains_reservation_capacity(self):
        second = self.execution()
        second.directory = self.first.directory
        with self.telemetry(lambda: (_ for _ in ()).throw(OSError('unavailable'))) as (_, measured):
            first = self.first.call()
            other = second.call()
            full = self.first.call(phase_id='no-capacity')
        self.assertEqual(first['returncode'], 0)
        self.assertIsNotNone(first['warning'])
        self.assertEqual(other['returncode'], 0)
        self.assertIsNotNone(other['warning'])
        self.assertEqual(full['reason'], 'occupied-reservations')
        self.assertEqual(measured.call_count, 1)

    def test_memory_cache_cannot_bypass_checkout_and_demand_specific_disk_checks(self):
        second = self.execution()
        second.directory = self.first.directory

        def disk_usage(path):
            return SimpleNamespace(free=1 if path == self.first.fixture.scope.repository_root else 0)

        with self.telemetry() as (_, measured), \
             patch.object(resource_execution.shutil, 'disk_usage', side_effect=disk_usage) as disk:
            self.assertEqual(self.first.call(phase_id='memory', capacity_cpu=8)['returncode'], 0)
            self.assertEqual(self.first.call(phase_id='disk-a', disk_bytes=1, capacity_cpu=8)['returncode'], 0)
            self.assertEqual(second.call(phase_id='disk-b', disk_bytes=1, capacity_cpu=8)['reason'], 'host-pressure')
            second.call('cancel', phase_id='disk-b', disk_bytes=1, capacity_cpu=8)
            demand = self.first.call(phase_id='disk-demand', disk_bytes=2, capacity_cpu=8)
            self.assertEqual(demand['reason'], 'host-pressure')
            self.assertEqual(self.first.call(phase_id='disk-demand', disk_bytes=2, capacity_cpu=8)['reason'], 'host-pressure')
        self.assertEqual(measured.call_count, 1)
        self.assertEqual(disk.call_count, 4)

    def test_disable_during_wait_is_revalidated_before_a_new_admission(self):
        sample = dict(sampled_at=int(time.time()), available_memory_bytes=0, pressure=True)
        marker = self.first.fixture.fixture.repo / 'must-not-launch'

        def disable(_):
            fixture = self.first.fixture
            fixture.control('disable', fixture.control('status')['revision'])

        with self.telemetry(lambda: sample), patch.object(resource_execution.time, 'sleep', side_effect=disable):
            with self.assertRaises(state.StateError):
                self.first.call(wait_seconds=1, argv=[self.first.request['argv'][0], '-c',
                    'from pathlib import Path; Path(' + repr(str(marker)) + ').touch()'])
        self.assertFalse(marker.exists())
        row = next(iter(host.control(self.first.directory, 'status', {})['reservations'].values()))
        self.assertEqual(row['state'], 'waiting')

    def test_runtime_pin_change_at_launch_retains_the_active_reservation(self):
        authority = resource_execution._authority
        calls = 0
        marker = self.first.fixture.fixture.repo / 'must-not-launch'

        def changed(scope, request, **options):
            nonlocal calls
            calls += 1
            if calls == 3:
                with patch.object(state, 'runtime_fingerprint', return_value='0' * 64):
                    return authority(scope, request, **options)
            return authority(scope, request, **options)

        with self.telemetry(), patch.object(resource_execution, '_authority', side_effect=changed):
            with self.assertRaises(state.StateError):
                self.first.call(argv=[self.first.request['argv'][0], '-c',
                    'from pathlib import Path; Path(' + repr(str(marker)) + ').touch()'])
        self.assertEqual(calls, 3)
        self.assertFalse(marker.exists())
        row = next(iter(host.control(self.first.directory, 'status', {})['reservations'].values()))
        self.assertEqual(row['state'], 'active')

    def test_reconciled_cleanup_survives_disable_and_a_closed_task(self):
        self.first.call()
        fixture = self.first.fixture
        fixture.observe(self.first.prepared)
        proof = fixture.fixture.worker_reconciliation_request(self.first.prepared, outcome='failed')
        fixture.fixture.api.reconcile_assignment(fixture.scope, proof)
        fixture.control('disable', fixture.control('status')['revision'])
        with state._database(fixture.scope, write=True) as db:
            identity = fixture.fixture.identity
            task = state._task(db, state._scope_id(fixture.scope), identity['client'], identity['session_id'], identity['task_id'])
            task['state'] = 'CANCELLED'
            state._save(db, state._scope_id(fixture.scope), task)
        self.assertEqual(self.first.call('release')['state'], 'released')


class ContinuationProjectionTests(unittest.TestCase):
    def test_only_consumption_returns_the_exact_large_stored_prompt(self):
        fixture = test_workstreams.WorkstreamsTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        prepared = fixture.prepare()
        fixture.observe(prepared)
        prompt = 'Fix café and 漢字; preserve 🐍 and e\u0301. ' * 600
        intent = workstreams.prepare_continuation(fixture.scope, fixture.continuation(prepared, prompt=prompt))
        self.assertNotIn('prompt', intent)
        self.assertFalse(intent['send_admitted'])
        self.assertEqual(intent['remaining_continuations'], 2)
        reference = fixture.fixture.raw_assignment(prepared['attempt_id'])['workstream_continuation']
        stored = evidence._read(fixture.scope, reference)
        self.assertEqual(stored['prompt'], prompt)
        request = fixture.fixture.request(attempt_id=prepared['attempt_id'],
            workstream_revision=fixture.control('status')['revision'], token=intent['token'])
        consumed = workstreams.consume_continuation(fixture.scope, request)
        self.assertTrue(consumed['send_admitted'])
        self.assertEqual(consumed['prompt'], prompt)
        self.assertEqual(consumed['worker_id'], intent['worker_id'])
        self.assertEqual(consumed['token'], intent['token'])
        delivered = workstreams.record_continuation(fixture.scope, fixture.fixture.request(
            attempt_id=prepared['attempt_id'], token=intent['token'], delivery='sent', delivery_ref='fixture:exact'))
        self.assertNotIn('prompt', delivered)
        self.assertEqual(delivered['delivery'], 'sent')
        self.assertEqual(evidence._read(fixture.scope, reference), stored)
        current = fixture.fixture.raw_assignment(prepared['attempt_id'])['workstream_continuation']
        self.assertEqual(evidence._read(fixture.scope, current)['prompt'], prompt)
