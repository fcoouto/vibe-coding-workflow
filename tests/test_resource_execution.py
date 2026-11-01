"""Owned heavy-command integration; fixtures are not native client qualification."""
import importlib
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from tests import test_workstreams


class ResourceExecutionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_workstreams.WorkstreamsTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.prepared = self.fixture.prepare()
        self.directory = Path(tempfile.mkdtemp()).resolve() / 'host'
        self.request = self.fixture.fixture.request(attempt_id=self.prepared['attempt_id'],
            workstream_revision=self.fixture.control('status')['revision'], phase_id='unit-check',
            cpu=1, memory_bytes=1024, capacity_cpu=2, capacity_memory_bytes=1024*1024,
            argv=[sys.executable, '-c', 'print("verified")'], wait_seconds=0)

    def call(self, action='run', **updates):
        api=importlib.import_module('runtime.resource_execution')
        return api.operate(self.fixture.scope, self.directory, action, self.request | updates)

    def test_owned_command_runs_once_and_retains_until_reconciliation(self):
        result=self.call()
        self.assertEqual(result['returncode'],0)
        self.assertIn('verified',result['stdout'])
        self.assertFalse(result['released'])
        with self.assertRaises(ValueError):
            self.call()
        self.fixture.observe(self.prepared)
        fixture=self.fixture.fixture
        proof=fixture.worker_reconciliation_request(self.prepared,outcome='failed')
        fixture.api.reconcile_assignment(fixture.scope,proof)
        released=self.call('release')
        self.assertEqual(released['state'],'released')

    def test_disabled_mode_never_launches(self):
        self.fixture.control('disable',self.fixture.control('status')['revision'])
        with self.assertRaises(ValueError): self.call()
        self.assertFalse(self.directory.exists())

    def test_timeout_retains_reservation(self):
        result=self.call(argv=[sys.executable,'-c','import time;time.sleep(1)'], timeout_seconds=0.05)
        self.assertTrue(result['uncertain'])
        self.assertFalse(result['released'])

    def test_telemetry_failure_does_not_block_command(self):
        with patch('runtime.resource_admission.measure',side_effect=OSError('probe unavailable')):
            result=self.call()
        self.assertEqual(result['returncode'],0)
        self.assertFalse(result['released'])

    def test_disk_shortage_still_blocks_when_memory_probe_fails(self):
        from types import SimpleNamespace
        with patch('runtime.resource_admission.measure', side_effect=OSError('memory unavailable')), \
             patch('runtime.resource_execution.shutil.disk_usage', return_value=SimpleNamespace(free=0)) as disk, \
             patch('runtime.resource_execution.subprocess.Popen') as launch:
            result = self.call(disk_bytes=1_000_000)
        self.assertEqual(result['state'], 'waiting')
        self.assertEqual(result['reason'], 'host-pressure')
        disk.assert_called_once()
        launch.assert_not_called()

    def test_disk_probe_failure_preserves_known_memory_pressure(self):
        import time
        sample = dict(sampled_at=int(time.time()), available_memory_bytes=0, pressure=True)
        with patch('runtime.resource_admission.measure', return_value=sample), \
             patch('runtime.resource_execution.shutil.disk_usage', side_effect=OSError('disk unavailable')), \
             patch('runtime.resource_execution.subprocess.Popen') as launch:
            result = self.call(disk_bytes=1_000_000)
        self.assertEqual(result['state'], 'waiting')
        self.assertEqual(result['reason'], 'host-pressure')
        launch.assert_not_called()

    def test_disk_probe_failure_warns_and_persists_status(self):
        with patch('runtime.resource_execution.shutil.disk_usage', side_effect=OSError('disk unavailable')):
            result = self.call(disk_bytes=1_000_000)
        self.assertEqual(result['returncode'], 0)
        self.assertIn('Disk telemetry unavailable', result['warning'])
        saved = next(iter(self.call('status')['reservations'].values()))
        self.assertEqual(saved['last_status']['warning'], result['warning'])

    def test_unavailable_measurements_still_admit_within_reservations(self):
        with patch('runtime.resource_admission.measure', side_effect=OSError('memory unavailable')), \
             patch('runtime.resource_execution.shutil.disk_usage', side_effect=OSError('disk unavailable')):
            result = self.call(disk_bytes=1_000_000)
        self.assertEqual(result['returncode'], 0)
        self.assertIn('Host telemetry unavailable', result['warning'])
        self.assertIn('Disk telemetry unavailable', result['warning'])

    def test_actual_cli_dispatches_owned_foreground_command(self):
        import io
        import json
        from contextlib import redirect_stdout
        from types import SimpleNamespace
        from scripts import workflow
        output=io.StringIO()
        with patch('sys.argv',['workflow.py','delegation','workstreams','resource-run','--cwd',str(self.fixture.fixture.repo)]), \
             patch('sys.stdin',SimpleNamespace(buffer=io.BytesIO(json.dumps(self.request).encode()))), \
             patch('runtime.startup.resolve_project',return_value=self.fixture.scope), \
             patch('runtime.resource_execution.host_directory',return_value=self.directory), redirect_stdout(output):
            code=workflow.control_main()
        self.assertEqual(code,0,output.getvalue())
        result=json.loads(output.getvalue())
        self.assertEqual(result['returncode'],0,result)
        self.assertFalse(result['released'])

    def test_declared_persistent_service_retains_and_status_is_bound(self):
        result=self.call()
        self.assertFalse(result['released'])
        status=self.call('status')
        self.assertEqual(len(status['reservations']),1)
        self.assertEqual(next(iter(status['reservations'].values()))['state'],'active')
        with self.assertRaises(ValueError): self.call('release')

    def test_wait_can_be_cancelled_after_disable(self):
        import time
        sample=dict(sampled_at=int(time.time()),available_memory_bytes=1024,pressure=True)
        with patch('runtime.resource_admission.measure',return_value=sample):
            result=self.call()
        self.assertFalse(result['admitted'])
        self.fixture.control('disable',self.fixture.control('status')['revision'])
        result=self.call('cancel')
        self.assertEqual(result['state'],'cancelled')

    def test_toggle_cannot_duplicate_original_phase(self):
        self.call()
        self.fixture.control('disable',self.fixture.control('status')['revision'])
        enabled=self.fixture.enable()
        with self.assertRaises(ValueError):
            self.call(workstream_revision=enabled['revision'])

    def test_invalid_disk_demand_is_not_a_telemetry_failure(self):
        with self.assertRaises(ValueError): self.call(disk_bytes=-1)
        self.assertFalse(self.directory.exists())

    def test_detached_descendant_does_not_release_capacity(self):
        command='import subprocess,sys; p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(0.2)"], start_new_session=True); print(p.pid)'
        result=self.call(argv=[sys.executable,'-c',command])
        self.assertFalse(result['released'])
        self.assertTrue(result['uncertain'])

    def test_admitted_review_can_execute_after_disable(self):
        from tests import test_delegation
        from runtime import resource_execution, workstreams
        stage=test_delegation.Stage4NativeReviewTests('runTest')
        stage.setUp()
        self.addCleanup(stage.doCleanups)
        stage.plan(stage.review_plan())
        enabled=workstreams.control(stage.scope,'enable',dict(client='codex',
            expected_revision=workstreams.control(stage.scope,'status',dict(client='codex'))['revision']))
        prepared=stage.prepared()
        disabled=workstreams.control(stage.scope,'disable',dict(client='codex',expected_revision=enabled['revision']))
        request=stage.request(**{k:v for k,v in self.request.items() if k not in stage.identity},
            )
        request.update(attempt_id=prepared['attempt_id'],workstream_revision=disabled['revision'])
        result=resource_execution.operate(stage.scope,self.directory,'run',request)
        self.assertEqual(result['returncode'],0)
