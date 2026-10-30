"""Actual historical publication must not create prospective content permission."""
from unittest.mock import patch
import unittest

from runtime import changes, evidence, state
from tests import test_historical_use_activation as activation


class HistoricalUseEnforcementTests(unittest.TestCase):
    def setUp(self):
        self.activation = activation.HistoricalUseActivationTests(methodName='runTest')
        self.activation.setUp()
        self.addCleanup(self.activation.doCleanups)

    def test_generic_publisher_cannot_issue_restricted_recovery_body(self):
        helper = self.activation
        fixture = helper.fixture
        request, scope, context, task, shared, proof = helper.historical()
        destination_scope = helper.destination_scope
        consumer_task = state.start_task(destination_scope, dict(client='codex', session_id='generic-publisher',
            task_id='generic-publisher', scope_ref='fixture:independent-publisher', mode='read-only', decision_ref='fixture'))['task']
        contexts = tuple(evidence._evidence_context(existing) for existing in fixture.d4_bookkeeping_scopes)

        def baseline(current):
            with evidence._context_database(current) as db:
                return evidence._canonical_plain(state._source_baseline(None, db, context=current))

        before = tuple(baseline(current) for current in contexts)
        shared_before = shared.read_bytes()
        with evidence._context_database(context) as db:
            original_proof = evidence._read(None, proof['reference'], context=context, db=db)
        self.assertEqual(task['state'], 'cancelled')
        observed = []
        original = changes._observe_recovery_source

        def observe(*args, **kwargs):
            source = original(*args, **kwargs)
            observed.append(source)
            return source

        from scripts.onboard_coordinator import run_verified_operation
        decision = helper.bookkeeping_decision(request, 'apply', task)
        identity = task['accepted_identity']
        decision['bookkeeping_scope']['subjects'] = [subject for subject in decision['bookkeeping_scope']['subjects']
            if not all(subject[key] == identity[key] for key in ('project_id', 'repository_id', 'checkout_id', 'client'))]
        with patch.object(changes, '_observe_recovery_source', side_effect=observe):
            result = run_verified_operation(decision, fixture.directory, request)

        self.assertNotEqual(result['exit_code'], 0, result)
        self.assertTrue(observed, result)
        content = evidence._canonical_plain(observed[-1].content)
        self.assertIn('use_contract', content)
        self.assertEqual(shared.read_bytes(), shared_before)
        self.assertEqual(tuple(baseline(current) for current in contexts), before)
        with evidence._context_database(context) as db:
            self.assertEqual(state._task(db, state._scope_id(scope), 'codex', 'historical-consumer',
                'historical-consumer'), task)
            self.assertEqual(evidence._read(None, proof['reference'], context=context, db=db), original_proof)

        def allocations(current):
            with evidence._context_database(current) as db:
                metadata = tuple(db.execute('select * from evidence_metadata order by name'))
            folder = current.directory / 'evidence'
            files = tuple(sorted((path.name, path.read_bytes()) for path in folder.iterdir() if path.is_file())) if folder.exists() else ()
            return metadata, files

        before_allocations = tuple(allocations(current) for current in contexts)
        owner = evidence._artifact_owner(destination_scope, consumer_task)
        with self.assertRaisesRegex(state.StateError, 'actual recovery owner'):
            evidence._artifact(destination_scope, content, owner=owner)
        self.assertEqual(tuple(allocations(current) for current in contexts), before_allocations)
