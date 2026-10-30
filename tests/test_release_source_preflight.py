"""Real release-owner proof; semantic jobs must outlive only the outer source reader."""
from contextlib import contextmanager
import inspect
import unittest
from unittest.mock import patch


class ReleaseSourcePreflightTests(unittest.TestCase):
    def test_actual_release_owner_closes_outer_reader_before_original_jobs(self):
        from runtime import changes, evidence
        from tests.test_evidence import LinkedVerificationTests, _run_d4_fixture

        # Reopening the source reader around semantic work is the regression this catches.
        case = LinkedVerificationTests(methodName='test_linked_no_verifier_native_history_survives_d4_retirement_and_guidance')
        self.addCleanup(case.doCleanups)
        case.setUp()
        captured, _, contexts, references = case.no_verifier_stops()
        fixture, request = case.recovery_fixtures[0]
        applied = _run_d4_fixture(fixture, request, 'resume')
        self.assertEqual(applied['exit_code'], 0, applied)
        _, original_source = case.recovery_head(fixture, contexts[0])
        prepared = evidence._prepare_linked_closure(evidence._observe_linked_preparation(
            captured['reference'], original_source['authorities']))
        self.assertTrue(prepared['complete'])
        observation = changes._observe_recovery_release(original_source['authorities'], dict(original_source['identity']))
        self.assertIs(observation.provenance, changes._RECOVERY_RELEASE_ISSUER)
        self.assertIsNotNone(observation.release)
        self.assertEqual(len(observation.content['stopped']), 2)
        # Observe the real prior checks; no-verifier does not erase their ledger obligations.
        from runtime import delegation
        census = []
        for certificate in evidence._canonical_plain(observation.content)['stopped']:
            self.assertTrue(certificate['preparation'])
            self.assertEqual(certificate['linked']['version'], 2)
            reference = certificate['reference']
            context = next(c for c in observation.contexts if str(c.database) == reference['authority']['database'])
            with evidence._context_database(context) as db:
                records = [r for r in delegation._ledger(None, db, context=context) if all(
                    r['owner'][key] == reference[key] for key in ('scope_id', 'client', 'session_id', 'task_id'))]
                self.assertEqual(len(records), 1)
                record = records[0]
                self.assertEqual(record['data']['role'], 'check')
                self.assertEqual(record['data']['status'], 'settled')
                self.assertEqual(record['data']['result'], dict(outcome='completed'))
                self.assertIsNotNone(record['data']['lifecycle'])
                reconciliation = evidence._read(None, record['data']['reconciliation'], context=context, db=db)
                self.assertEqual(reconciliation['version'], 2)
                self.assertEqual(reconciliation['proof']['kind'], 'check-writer-reconciliation')
                self.assertIsNotNone(record['data']['observation'])
                self.assertIsNotNone(reconciliation['current_candidate'])
                inputs = changes._linked_live_certificate_inputs(context, db,
                    dict(reference=reference, pins=certificate['pins']), certificate['linked'])
                self.assertIsNotNone(inputs)
                task = evidence._canonical_plain(inputs)['certificate_inputs']['task']
                attempt = next(a for a in task['evidence']['attempts'] if a['id'] == record['id'])
                self.assertEqual(attempt['status'], 'passed')
                assembled = changes._stopped_certificate_from_inputs(evidence._canonical_plain(inputs)['certificate_inputs'])
                bare = {key: value for key, value in certificate.items() if key != 'preparation'}
                self.assertEqual(bare, assembled)
                self.assertEqual(evidence._linked_owned_preparation(context, db, reference)['content']['stopped'], bare)
                self.assertEqual([a['reference']['id'] for a in assembled['assignments']], [record['id']])
                census.append(dict(role=record['data']['role'], status=record['data']['status'],
                    outcome=record['data']['result']['outcome'], reconciliation_version=reconciliation['version']))
        import json
        print(json.dumps(dict(event='actual-release-check-family', members=len(census), assignments=census)), flush=True)
        outer = set()
        original_database = evidence._context_database
        calls = []

        @contextmanager
        def tracked(context, *args, **kwargs):
            caller = inspect.currentframe().f_back
            while caller and caller.f_code.co_filename != changes.__file__:
                caller = caller.f_back
            owned = caller and caller.f_code.co_name in ('_check_recovery_source_global', '_check_release_source_preflight')
            with original_database(context, *args, **kwargs) as db:
                if owned:
                    outer.add(db)
                try:
                    yield db
                finally:
                    if owned:
                        outer.remove(db)

        def semantic(name, original):
            def checked(*args, **kwargs):
                lifetime = getattr(changes._authority_context, 'publication', None)
                if lifetime and lifetime['active'] and lifetime['source'] is observation:
                    self.assertFalse(outer, 'Release semantic job entered with its owned outer source reader open')
                    calls.append(name)
                return original(*args, **kwargs)
            return checked

        original_global = changes._check_recovery_source_global
        class PreflightFinished(BaseException):
            pass
        def preflight(source):
            self.assertIs(source, observation)
            result = original_global(source)
            self.assertFalse(outer)
            self.assertIn('_linked_preparation_read_facts', calls)
            self.assertIn('_resolve_linked_live_certificate_job', calls)
            if getattr(self, '_run_negative_matrix', False):
                self._negative_matrix(original_global, observation, contexts, references, changes, evidence, original_database)
            raise PreflightFinished()

        with patch.object(evidence, '_context_database', side_effect=tracked), \
                patch.object(changes, '_check_recovery_source_global', side_effect=preflight), \
                patch.object(evidence, '_linked_preparation_facts', side_effect=semantic('_linked_preparation_facts', evidence._linked_preparation_facts)), \
                patch.object(evidence, '_linked_preparation_read_facts', side_effect=semantic('_linked_preparation_read_facts', evidence._linked_preparation_read_facts)), \
                patch.object(changes, '_resolve_linked_live_certificate_job', side_effect=semantic('_resolve_linked_live_certificate_job', changes._resolve_linked_live_certificate_job)), \
                self.assertRaises(PreflightFinished):
            changes._register_recovery_release(observation)
        self.assertFalse(getattr(changes._authority_context, 'publication', None))
        for context, reference in zip(contexts, references):
            with original_database(context) as db:
                task = evidence._linked_raw_task(db, reference)
                self.assertIsNotNone(task)
                self.assertIsNone(task['lifecycle']['safe_closed_at'])

    def test_actual_release_owner_rejects_late_changes_and_preserves_fallback(self):
        self._run_negative_matrix = True
        self.test_actual_release_owner_closes_outer_reader_before_original_jobs()

    def _negative_matrix(self, preflight, source, contexts, references, changes, evidence, database):
        import json
        import os
        from pathlib import Path
        from runtime.startup import StartupError
        context, reference = contexts[0], references[0]
        certificate = next(c for c in evidence._canonical_plain(source.content)['stopped'] if c['reference'] == reference)
        with database(context) as db:
            prepared = evidence._linked_owned_preparation(context, db, reference)
        receipt_path = Path(prepared['metadata']['managed']['path'])
        receipt_bytes = receipt_path.read_bytes()
        receipt_mode = receipt_path.stat().st_mode & 0o777
        unknown = context.directory / 'evidence' / 'late-unregistered-preflight-test.json'

        # Failure responses exercise real dispatch; none substitutes successful validation.
        for response in (None, dict(job={}, result={})):
            with self.subTest(response=response), patch.object(evidence, '_resolve_prepared_certificate_job', return_value=response):
                with self.assertRaisesRegex(StartupError, 'unresolved or mismatched'):
                    preflight(source)
        class FullFallbackReached(BaseException):
            pass
        with patch.object(changes, '_release_source_inputs', return_value=None), \
                patch.object(changes, '_check_recovery_source', side_effect=FullFallbackReached), \
                self.assertRaises(FullFallbackReached):
            preflight(source)
        lifetime = changes._d4_publication_lifetime(source)
        with database(context, write=True) as writer:
            lifetime['writer'] = (context, writer)
            try:
                with patch.object(changes, '_check_recovery_source', side_effect=FullFallbackReached), self.assertRaises(FullFallbackReached):
                    preflight(source)
            finally:
                lifetime.pop('writer')

        for kind in ('task-generation', 'assignment-generation', 'receipt', 'physical-membership'):
            restored = []
            mutated = []
            original_check = evidence._check_preparation_inputs
            def mutate_after_inputs(*args, **kwargs):
                result = original_check(*args, **kwargs)
                frame = inspect.currentframe().f_back
                while frame and frame.f_code.co_filename not in (changes.__file__, evidence.__file__):
                    frame = frame.f_back
                if mutated or frame is None or frame.f_code.co_name != '_check_release_source_preflight':
                    return result
                # The original full jobs and last input check finished; the source reader remains closed.
                if kind in ('task-generation', 'assignment-generation'):
                    with database(context, write=True) as db:
                        if kind == 'task-generation':
                            keys = tuple(reference[k] for k in ('scope_id', 'client', 'session_id', 'task_id'))
                            where = 'scope_id=? and client=? and session_id=? and task_id=?'
                            table = 'tasks'
                        else:
                            keys = (certificate['assignments'][0]['reference']['id'],)
                            where = 'id=?'
                            table = 'assignments'
                        raw = db.execute('select data from ' + table + ' where ' + where, keys).fetchone()[0]
                        changed = json.loads(raw)
                        if kind == 'task-generation':
                            changed['reason'] = 'Actual late task input mutation'
                        else:
                            changed['result'] = dict(outcome='failed')
                        db.execute('update ' + table + ' set data=? where ' + where, (json.dumps(changed), *keys))
                    restored.append((table, where, keys, raw))
                elif kind == 'receipt':
                    receipt_path.chmod(0o600)
                    receipt_path.write_bytes(receipt_bytes + b' ')
                    receipt_path.chmod(receipt_mode)
                else:
                    with unknown.open('xb') as stream:
                        stream.write(b'{}')
                    unknown.chmod(0o400)
                mutated.append(True)
                return result
            try:
                with self.subTest(change=kind), patch.object(evidence, '_check_preparation_inputs', side_effect=mutate_after_inputs):
                    if kind.endswith('generation'):
                        with self.assertRaisesRegex(StartupError, 'selected owner generation changed'):
                            preflight(source)
                    else:
                        with self.assertRaises(StartupError):
                            preflight(source)
                self.assertTrue(mutated, 'Late mutation did not reach the post-semantic boundary')
            finally:
                for table, where, keys, raw in restored:
                    with database(context, write=True) as db:
                        db.execute('update ' + table + ' set data=? where ' + where, (raw, *keys))
                if kind == 'receipt' and mutated:
                    receipt_path.chmod(0o600)
                    receipt_path.write_bytes(receipt_bytes)
                    receipt_path.chmod(receipt_mode)
                if kind == 'physical-membership' and unknown.exists():
                    unknown.unlink()
            print(json.dumps(dict(event='release-preflight-negative', change=kind, rejected=True)), flush=True)
