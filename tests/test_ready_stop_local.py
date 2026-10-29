"""Ready-stop leaf checks use actual local transactions and retain linked jobs."""

import copy
import sqlite3
import unittest
from unittest.mock import patch

from runtime import state
from runtime.startup import StartupError
from tests import test_evidence as fixtures


class ReadyStopLocalTests(unittest.TestCase):
    def seam(self):
        self.assertTrue(callable(getattr(state, '_ready_stop_local', None)),
            'Ready-stop local extraction seam is missing')
        return state._ready_stop_local

    def ready_fixture(self):
        scenario = fixtures.ReadyClosureTests(methodName='runTest')
        scenario.setUp()
        self.addCleanup(scenario.doCleanups)
        task, _ = scenario.stopped()
        return scenario, task

    def test_local_proof_reads_actual_uncommitted_managed_row_without_new_connection(self):
        local = self.seam()
        scenario, task = self.ready_fixture()
        api = scenario.fixture.api
        context = api._evidence_context(scenario.scope)
        proof = api._read(scenario.scope, task['writer_stop']['proof'])
        with api._context_database(context, write=True) as db:
            reference = api._artifact(scenario.scope, proof,
                owner=api._artifact_owner(scenario.scope, task), db=db)
            changed = copy.deepcopy(task)
            changed['writer_stop']['proof'] = reference
            with api._context_database(context) as reader:
                self.assertIsNone(state._metadata(reader, reference['name']))
            with patch.object(sqlite3, 'connect', side_effect=AssertionError('Local check opened SQLite')):
                result = local(context, db, changed)
            self.assertEqual(result['proof'], proof)
            self.assertEqual(result['bindings'], state._ready_stop_bindings(context, db, changed))
            self.assertIsNone(result['linked'])
            self.assertEqual(state._metadata(db, reference['name'])['managed']['sha256'], reference['digest'])

    def test_local_invalid_proof_and_uncommitted_generation_change_reject(self):
        local = self.seam()
        scenario, task = self.ready_fixture()
        api = scenario.fixture.api
        context = api._evidence_context(scenario.scope)
        proof = api._read(scenario.scope, task['writer_stop']['proof'])
        with api._context_database(context, write=True) as db:
            invalid = dict(proof, descendants_stopped=False)
            reference = api._artifact(scenario.scope, invalid,
                owner=api._artifact_owner(scenario.scope, task), db=db)
            changed = copy.deepcopy(task)
            changed['writer_stop']['proof'] = reference
            with patch.object(sqlite3, 'connect', side_effect=AssertionError('Local check opened SQLite')):
                with self.assertRaises(StartupError):
                    local(context, db, changed)
                db.execute('update checkouts set generation=generation+1')
                with self.assertRaises(StartupError):
                    local(context, db, task)
                db.execute('update checkouts set generation=generation-1')
                self.assertEqual(local(context, db, task)['proof'], proof)

    def test_linked_local_result_keeps_actual_basis_job_and_wrapper_still_discharges_it(self):
        local = self.seam()
        scenario = fixtures.LinkedVerificationTests(methodName='runTest')
        scenario.setUp()
        self.addCleanup(scenario.doCleanups)
        pointer = scenario.verify()['verification']
        fixture = scenario.selected
        task = state._retain_ready_stop(fixture.scope, scenario.stop_request(fixture, pointer))['task']
        api = scenario.api
        context = api._evidence_context(fixture.scope)
        with api._context_database(context) as db:
            basis = api._read(None, task['writer_stop']['linked'], context=context, db=db)
            with patch.object(sqlite3, 'connect', side_effect=AssertionError('Local check opened SQLite')):
                result = local(context, db, task)
            self.assertEqual(result['linked'], dict(reference=api._linked_basis_root(basis),
                authorities=basis['authorities'], expected=basis))
            self.assertEqual(result['proof']['linked_digest'], api._digest(basis))
            with patch.object(api, '_linked_stopped_basis', side_effect=RuntimeError('Complete linked job required')):
                with self.assertRaisesRegex(RuntimeError, 'Complete linked job required'):
                    state._ready_stop(context, db, task)
            self.assertEqual(state._ready_stop(context, db, task), result['proof'])
