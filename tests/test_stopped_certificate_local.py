"""Certificate extraction uses the actual writer; pending jobs grant no authority."""
import copy
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from runtime import changes, evidence, state
from runtime.startup import StartupError
from tests import test_evidence as fixtures


class StoppedCertificateLocalTests(unittest.TestCase):
    def ready(self):
        scenario = fixtures.ReadyClosureTests(methodName='runTest')
        scenario.setUp(); self.addCleanup(scenario.doCleanups)
        task, _ = scenario.stopped()
        context = evidence._evidence_context(scenario.scope)
        reference = evidence._canonical_plain(evidence._artifact_owner(scenario.scope, task).task)
        return scenario, task, context, dict(reference=reference, pins=task['pins'])

    def collect(self, context, db, item):
        self.assertTrue(callable(getattr(changes, '_stopped_certificate_inputs', None)), 'Local certificate seam missing')
        return changes._stopped_certificate_inputs(context, db, item)

    def finish(self, inputs, context):
        assembly = changes._stopped_certificate_assembly(inputs)
        try:
            with patch.object(sqlite3, 'connect', side_effect=AssertionError('Assembly opened SQLite')):
                job = next(assembly)
            while True:
                self.assertEqual(job['kind'], 'ready-candidate')
                response = changes._resolve_stopped_certificate_job(context, job)
                with patch.object(sqlite3, 'connect', side_effect=AssertionError('Assembly opened SQLite')):
                    job = assembly.send(response)
        except StopIteration as completed:
            return completed.value

    def test_actual_uncommitted_proof_and_saved_task_need_no_extra_connection(self):
        scenario = fixtures.ReadyClosureTests(methodName='runTest')
        scenario.setUp(); self.addCleanup(scenario.doCleanups)
        task = scenario.ready()
        with self.assertRaises(StartupError):
            state._retain_ready_stop(scenario.scope, scenario.stop_request(task, descendants_stopped=False))
        request = scenario.stop_request(task)
        context = evidence._evidence_context(scenario.scope)
        original_database = evidence._context_database
        captured = []
        @contextmanager
        def inspect_owner(selected, **kwargs):
            with original_database(selected, **kwargs) as db:
                yield db
                if not kwargs.get('write'): return
                current = state._task(db, state._scope_id(scenario.scope), 'codex', 'parent', 'task')
                reference = current['writer_stop']['proof']
                item = dict(reference=evidence._canonical_plain(evidence._artifact_owner(scenario.scope, current).task), pins=current['pins'])
                with original_database(selected) as reader:
                    self.assertIsNone(state._metadata(reader, reference['name']))
                with patch.object(sqlite3, 'connect', side_effect=AssertionError('Local collector opened SQLite')):
                    inputs = self.collect(selected, db, item)
                    assembly = changes._stopped_certificate_assembly(inputs)
                    job = next(assembly)
                    self.assertEqual(job['kind'], 'ready-candidate')
                    self.assertEqual(job['task']['writer_stop']['proof'], reference)
                self.assertEqual(state._metadata(db, reference['name'])['managed']['sha256'], reference['digest'])
                captured.append((inputs, item))
        with patch.object(evidence, '_context_database', side_effect=inspect_owner):
            stopped = state._retain_ready_stop(scenario.scope, request)['task']
        self.assertEqual(len(captured), 1)
        inputs, item = captured[0]
        actual = self.finish(inputs, context)
        with evidence._context_database(context) as db:
            self.assertEqual(actual, changes._stopped_certificate(context, db, item))
            changes._check_stopped_certificate(context, db, actual)
        self.assertEqual(actual['pins'], task['pins'])
        self.assertEqual(actual['created_at'], stopped['lifecycle']['created_at'])

    def test_missing_mismatched_or_boolean_job_result_cannot_complete(self):
        _, _, context, item = self.ready()
        with evidence._context_database(context) as db: inputs = self.collect(context, db, item)
        for response in (None, False, dict(job={}, result={}), 'wrong'):
            with self.subTest(response=response), patch.object(sqlite3, 'connect', side_effect=AssertionError('Assembly opened SQLite')):
                assembly = changes._stopped_certificate_assembly(inputs); next(assembly)
                with self.assertRaises(StartupError): assembly.send(response)
        assembly = changes._stopped_certificate_assembly(inputs); job = next(assembly)
        with self.assertRaises(StartupError): assembly.send(dict(job=job, result=False))
        with patch.object(evidence, '_ready_stop_candidate', side_effect=StartupError('Freshness must run')):
            with self.assertRaisesRegex(StartupError, 'Freshness must run'): self.finish(inputs, context)
        with patch.object(state, 'runtime_fingerprint', return_value='f' * 64):
            with self.assertRaisesRegex(StartupError, 'Installed ready source pins changed'): self.finish(inputs, context)

    def test_wrong_connection_proof_and_generation_changes_reject(self):
        scenario, task, context, item = self.ready()
        with sqlite3.connect(':memory:') as wrong:
            with self.assertRaises(StartupError): self.collect(context, wrong, item)
        reference = task['writer_stop']['proof']
        path = Path(state._path(scenario.scope).parent) / 'evidence' / reference['name']
        raw = path.read_bytes(); mode = path.stat().st_mode & 0o777
        try:
            path.chmod(0o600); path.write_bytes(b'{}'); path.chmod(mode)
            with evidence._context_database(context) as db:
                with self.assertRaises(StartupError): self.collect(context, db, item)
        finally:
            path.chmod(0o600); path.write_bytes(raw); path.chmod(mode)
        with evidence._context_database(context, write=True) as db:
            db.execute('update checkouts set generation=generation+1')
            with self.assertRaises(StartupError): self.collect(context, db, item)
            db.execute('update checkouts set generation=generation-1')
            self.collect(context, db, item)

    def test_genuine_cancelled_check_certificate_keeps_normal_result(self):
        scenario = fixtures.AssignedCancelledClosureTests(methodName='runTest')
        scenario.setUp(); self.addCleanup(scenario.doCleanups)
        task, context, reference, _ = scenario.stopped()
        item = dict(reference=reference, pins=task['pins'])
        with evidence._context_database(context) as db:
            expected = changes._stopped_certificate(context, db, item)
            with patch.object(sqlite3, 'connect', side_effect=AssertionError('Cancelled collector opened SQLite')):
                inputs = self.collect(context, db, item)
                assembly = changes._stopped_certificate_assembly(inputs)
                with self.assertRaises(StopIteration) as completed: next(assembly)
                self.assertEqual(completed.exception.value, expected)
            changes._check_stopped_certificate(context, db, expected)
        self.assertEqual(expected['assignments'][0]['role'], 'check')
