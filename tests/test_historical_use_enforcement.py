"""Actual historical publication must not create prospective content permission."""
from copy import deepcopy
from unittest.mock import patch
import unittest

from runtime import changes, evidence, state
from tests import test_changes as fixtures


class HistoricalUseEnforcementTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ScopedChangesTests(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def stopped_witness(self):
        fixture = self.fixture
        request, scope, context, task, shared = fixture.historical_shared_consumer()
        with evidence._context_database(context, write=True) as db:
            proof = dict(version=1, kind='stopped-writer-reconciliation',
                identity={key:task[key] for key in ('client','session_id','task_id','scope_ref')},
                expected_revision=task['revision'], expected_pins=task['pins'], observed_turn_id=task['turn_id'],
                stopped=True, descendants_stopped=True, attempt_ids=[],
                observation_ref='fixture:stopped', coordinator_ref='fixture:owner')
            reference = evidence._artifact(scope, proof, owner=evidence._artifact_owner(scope, task), db=db)
            retired = deepcopy(task)
            retired.update(state='cancelled', revision=task['revision']+1,
                retirement=dict(proof_digest=reference['digest'], proof=reference,
                    observation_ref='fixture:stopped', coordinator_ref='fixture:owner', previous_revision=task['revision']))
            state._save(db, state._scope_id(scope), retired)
        return request, scope, context, retired, shared, reference


    def test_generic_publisher_cannot_issue_restricted_recovery_body(self):
        fixture = self.fixture
        request, scope, context, task, shared, proof = self.stopped_witness()
        destination_scope = fixture.d4_bookkeeping_scopes[0]
        consumer_task = state.start_task(destination_scope, dict(client='codex', session_id='generic-publisher',
            task_id='generic-publisher', scope_ref='fixture:independent-publisher', mode='read-only', decision_ref='fixture'))['task']
        observed = []
        original = changes._observe_recovery_source
        def observe(*args, **kwargs):
            source = original(*args, **kwargs); observed.append(source); return source
        with patch.object(changes, '_observe_recovery_source', side_effect=observe):
            denied = fixture.run_with_d4_host(request, 'apply')
        self.assertNotEqual(denied['exit_code'], 0, denied)
        content = evidence._canonical_plain(observed[-1].content)
        self.assertIn('use_contract', content)
        owner = evidence._artifact_owner(destination_scope, consumer_task)
        with self.assertRaisesRegex(state.StateError, 'actual recovery owner'):
            evidence._artifact(destination_scope, content, owner=owner)
