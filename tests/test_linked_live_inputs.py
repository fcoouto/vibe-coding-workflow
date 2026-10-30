"""Actual factual-v2 live certificate boundary; no preparation or closure is issued."""

from contextlib import contextmanager
from copy import deepcopy
import sqlite3
import unittest
from unittest.mock import patch

from runtime import changes, evidence, state
from runtime.startup import StartupError
from tests import test_evidence as fixtures


class LinkedLiveInputsTests(unittest.TestCase):
    def test_genuine_live_certificate_closes_reader_rechecks_and_wires_observation(self):
        case = fixtures.LinkedVerificationTests(methodName='runTest')
        case.setUp()
        self.addCleanup(case.doCleanups)
        captured, _, contexts, references = case.no_verifier_stops()
        context, reference = contexts[0], references[0]
        basis = captured['basis']
        item = dict(reference=reference, pins=case.task(case.members[0])['pins'])
        collect = getattr(changes, '_linked_live_certificate_inputs', None)
        with evidence._context_database(context) as db:
            with patch.object(sqlite3, 'connect', side_effect=AssertionError('Collector opened SQLite')):
                inputs = collect(context, db, item, basis) if collect else changes._stopped_certificate_inputs(context, db, item)
                assembly = getattr(changes, '_linked_live_certificate_assembly', changes._stopped_certificate_assembly)(inputs)
                job = next(assembly)
                self.assertEqual(job['kind'], 'linked-basis', 'Live linked inputs still require the complete reader-owning resolver')
        self.assertIsNotNone(inputs)
        for response in (None, False, dict(job={}, result=basis)):
            assembly = changes._linked_live_certificate_assembly(inputs)
            next(assembly)
            with patch.object(sqlite3, 'connect', side_effect=AssertionError('Assembly opened SQLite')):
                with self.assertRaises(StartupError):
                    assembly.send(response)
        assembly = changes._linked_live_certificate_assembly(inputs)
        job = next(assembly)
        for result in (True, dict(basis, delivery_complete=False)):
            attempt = changes._linked_live_certificate_assembly(inputs)
            pending = next(attempt)
            with self.assertRaises(StartupError):
                attempt.send(dict(job=pending, result=result))

        database = evidence._context_database
        active = []
        @contextmanager
        def track(selected, **kwargs):
            with database(selected, **kwargs) as connection:
                active.append(connection)
                try:
                    yield connection
                finally:
                    active.remove(connection)
        resolve = changes._resolve_linked_live_certificate_job
        resolved = []
        def actual(job, *, read_context=None, read_roster=None):
            self.assertFalse(active, 'Member reader remains open at external resolution')
            result = resolve(job, read_context=read_context, read_roster=read_roster)
            self.assertFalse(active)
            resolved.append(result)
            return result
        with evidence._linked_stop_guards(captured['reference'], basis['authorities']):
            with patch.object(evidence, '_context_database', side_effect=track), \
                    patch.object(changes, '_resolve_linked_live_certificate_job', side_effect=actual):
                certificate = evidence._observe_linked_live_certificate(context, item, basis)
            self.assertTrue(resolved)
            with database(context) as db:
                self.assertEqual(certificate, changes._stopped_certificate(context, db, item))
                changes._check_stopped_certificate(context, db, certificate)
            def changed(job, *, read_context=None, read_roster=None):
                result = actual(job, read_context=read_context, read_roster=read_roster)
                with database(context, write=True) as db:
                    db.execute('update checkouts set generation=generation+1 where scope_id=?', (reference['scope_id'],))
                return result
            try:
                with patch.object(evidence, '_context_database', side_effect=track), \
                        patch.object(changes, '_resolve_linked_live_certificate_job', side_effect=changed):
                    with self.assertRaises(StartupError):
                        evidence._observe_linked_live_certificate(context, item, basis)
            finally:
                with database(context, write=True) as db:
                    db.execute('update checkouts set generation=generation-1 where scope_id=?', (reference['scope_id'],))

        class Observed(BaseException):
            pass
        observe = evidence._observe_linked_live_certificate
        reached = []
        def stop_after_certificate(*args, read_context=None, read_roster=None):
            result = observe(*args, read_context=read_context, read_roster=read_roster)
            reached.append(result)
            raise Observed()
        with patch.object(evidence, '_observe_linked_live_certificate', side_effect=stop_after_certificate):
            with self.assertRaises(Observed):
                evidence._observe_linked_preparation(captured['reference'], basis['authorities'])
        reached_reference = reached[0]['reference']
        matches = [(selected_context, member) for selected_context, selected_reference, member
            in zip(contexts, references, case.members) if selected_reference == reached_reference]
        self.assertEqual(len(matches), 1)
        reached_context, reached_member = matches[0]
        reached_item = dict(reference=reached_reference, pins=case.task(reached_member)['pins'])
        with evidence._linked_stop_guards(captured['reference'], basis['authorities']):
            with database(reached_context) as db:
                self.assertEqual(reached[0], changes._stopped_certificate(reached_context, db, reached_item))
        self.assertFalse(case.preparation_receipts(contexts))
