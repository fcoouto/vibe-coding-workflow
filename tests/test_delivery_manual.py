"""Manual-flow acceptance gaps; all provider execution uses disposable fixtures."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from runtime import delivery, evidence, state
from scripts.delivery_coordinator import DeliveryOperationOwner
from tests import test_delivery_provider_mutations, test_delivery_reconcile


class ManualDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.case = test_delivery_reconcile.ReconcileTests('runTest')
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.fixture, self.scope = self.case.fixture, self.case.scope
        state.update_task(self.scope, self.fixture.request(state='WORKING',
            reason='Accepted manual delivery fixture', reference='fixture:accepted-start'))
        self.transport = test_delivery_provider_mutations.ProviderMutationTests('runTest')
        self.transport.setUp()
        self.transport.pr = self.case.provider.pr
        self.transport.fixture.pr = self.transport.pr
        self.transport.fixture.repo = self.case.provider.repo

    def status(self):
        return delivery.operate(self.scope, 'status', dict(client='codex', session_id='parent'))

    def operate(self, action, *, gate=None):
        request = self.fixture.request(publication_id='pr-0', operation_id='e' * 64)
        owner = DeliveryOperationOwner(dict(action=action, request_digest=evidence._digest(request),
            accepted_scope_digest=self.scope.accepted_scope_digest, reference='fixture:verified-decision'),
            native=self.case.native, repository=self.transport.adapter, gate=gate)
        return owner.run(self.scope, action, request)

    def retained_readiness(self, *, seed=True):
        """Seed the existing consumer fixture, not a production D7 readiness issuer."""
        task = self.status()['task']
        with state._database(self.scope) as db:
            plan = evidence._read(self.scope, task['evidence']['plan'], db=db)
        review = dict(applicability='required', reason='Actual change', independent=True)
        plan.update(nontrivial=True, reviews=dict(general=review, security=review))
        evidence.plan_evidence(self.scope, self.fixture.request(plan=plan,
            change_decision_ref='fixture:accepted-review-change'))
        self.fixture.checked()
        self.fixture.review()
        self.case.reconcile()
        verified = evidence.verify_completion(self.scope, self.fixture.request(purpose='merge-evidence'))
        self.assertTrue(verified['verified'], verified)
        if not seed:
            return
        with state._database(self.scope, write=True) as db:
            task = state._task(db, state._scope_id(self.scope), 'codex', 'parent')
            plan = delivery._read_plan(self.scope, task, db=db)
            publication = plan['publications'][0]
            receipt = dict(version=1, kind='delivery-readiness', binding=delivery._publication_binding(publication),
                local_verification=task['evidence']['verification'])
            publication['candidate']['readiness'] = evidence._artifact(self.scope, receipt,
                owner=evidence._artifact_owner(self.scope, task), db=db)
            task['delivery']['plan'] = evidence._artifact(self.scope, plan,
                owner=evidence._artifact_owner(self.scope, task), db=db)
            task['revision'] += 1
            state._save(db, state._scope_id(self.scope), task)
        self.transport.pr['draft'] = False
        self.transport.labels.add('[READY]')

    def fake_gate(self):
        """Only fixtures substitute the private source class; no production escape."""
        from runtime import repository_gate
        fixture = self

        class FixtureReadiness:
            def __init__(self, request):
                self.action = request['action']
                self.repository = fixture.transport.adapter
                self.local_verification = fixture.status()['task']['evidence']['verification']
                self.active = False

            def __enter__(self):
                self.active = True
                with state._database(fixture.scope, write=True) as db:
                    task = state._task(db, state._scope_id(fixture.scope), 'codex', 'parent')
                    self.reference = evidence._artifact(fixture.scope, dict(kind='fixture-d7-source',
                        action=self.action), owner=evidence._artifact_owner(fixture.scope, task), db=db)
                return self

            def __exit__(self, *error):
                self.active = False

            def recheck(self):
                if not self.active:
                    raise state.StateError('Fixture acquisition expired')

            def finalize(self, publish):
                self.recheck()
                calls = len(fixture.transport.calls)
                with state._database(fixture.scope, write=True) as db:
                    result = publish(db)
                fixture.assertEqual(len(fixture.transport.calls), calls, 'Network inside publication callback')
                return result

        class Gate:
            def acquire_readiness(self, scope, request, binding):
                fixture.assertIs(scope, fixture.scope)
                fixture.assertEqual(binding['pull_request'], 42)
                return FixtureReadiness(request)

        source = patch.object(repository_gate, 'RepositoryReadiness', FixtureReadiness, create=True)
        source.start()
        self.addCleanup(source.stop)
        return Gate()

    def waiting(self):
        self.retained_readiness()
        waiting = self.fixture.verify()
        self.assertEqual(waiting['task']['state'], 'WAITING', waiting)
        return waiting

    def test_caller_pass_flags_cannot_promote_pr_or_mint_readiness(self):
        self.case.reconcile()
        before = self.status()
        with self.assertRaisesRegex(ValueError, 'Qualified repository readiness source is unavailable'):
            self.operate('ready', gate=dict(evidence_valid=True, source_authentication='verified', ready=True))
        self.assertEqual(self.status(), before)
        self.assertEqual(self.transport.calls, [])
        self.assertTrue(self.transport.pr['draft'])

    def test_unavailable_readiness_source_cannot_promote_pr(self):
        self.case.reconcile()
        before = self.status()
        with self.assertRaisesRegex(ValueError, 'Qualified repository readiness source is unavailable'):
            self.operate('ready')
        self.assertEqual(self.status(), before)
        self.assertEqual(self.transport.calls, [])

    def test_ready_retains_exact_private_sources_after_metadata_readback(self):
        from contextlib import contextmanager
        from runtime import delegation, repository_gate
        from tests.test_repository_readiness import RepositoryReadinessTests

        self.retained_readiness(seed=False)
        source_case = RepositoryReadinessTests('runTest')
        source_case.local, source_case.scope = self.fixture, self.scope
        source_case.candidate = evidence.capture_candidate(self.scope,
            evidence._load_plan(self.scope, self.fixture.identity))
        source_case.binding = delivery._publication_binding(self.status()['plan']['publications'][0])
        source = source_case.source()
        source.repository = self.transport.adapter
        source_case.request = self.fixture.request(action='ready', publication_id='pr-0', operation_id='e' * 64)
        metadata, finalize = source.repository.mutate, source.finalize
        observed = dict(metadata=0, publication=0)
        fixture = self

        def assert_held(db):
            task = state._task(db, state._scope_id(self.scope), 'codex', 'parent')
            self.assertEqual(task['evidence']['verification'], observed['verification'])
            proof = evidence._read(self.scope, observed['verification'], db=db)
            self.assertEqual(proof['purpose'], 'merge-evidence')
            self.assertEqual(proof['blockers'], [])
            self.assertEqual(proof['candidate_digest'], source_case.binding['snapshot']['digest'])
            records = {row['id']: row for row in delegation._ledger(self.scope, db)}
            for identity in (proof['barrier_id'], source.operation):
                self.assertEqual(records[identity]['data']['status'], 'prepared')
            return proof['barrier_id']

        def mutate(*args, **kwargs):
            with state._database(self.scope) as db:
                observed['barrier'] = assert_held(db)
            source.remote_effects = 'uncertain'
            observed['metadata'] += 1
            return metadata(*args, **kwargs)

        def finalizing(publish, *, db=None):
            self.assertIsNotNone(db)
            self.assertTrue(db.in_transaction)
            calls = len(self.transport.calls)
            assert_held(db)
            result = finalize(publish, db=db)
            records = {row['id']: row for row in delegation._ledger(self.scope, db)}
            self.assertEqual(records[observed['barrier']]['data']['status'], 'prepared')
            self.assertEqual(records[source.operation]['data']['status'], 'settled')
            self.assertEqual(len(self.transport.calls), calls)
            observed['publication'] += 1
            return result

        source.repository.mutate, source.finalize = mutate, finalizing

        class Gate:
            @contextmanager
            def acquire_readiness(self, scope, request, binding):
                with repository_gate.acquire_readiness(scope, request, binding) as held:
                    fixture.assertIs(type(held), repository_gate.RepositoryReadiness)
                    fixture.assertIs(held.repository, fixture.transport.adapter)
                    fixture.assertFalse(held.withdrawal_only)
                    observed['verification'] = held.local_verification
                    yield held

        with patch.object(repository_gate, '_acquire_qualified_readiness_source', return_value=source):
            result = self.operate('ready', gate=Gate())
        receipt = evidence._read(self.scope, result['plan']['publications'][0]['candidate']['readiness'])
        effect = evidence._read(self.scope, receipt['operation'])
        gate = evidence._read(self.scope, receipt['source'])
        facts = evidence._read(self.scope, gate['source'])
        self.assertEqual(receipt['binding'], source_case.binding)
        self.assertEqual(effect['binding'], receipt['binding'])
        self.assertEqual(effect['source'], receipt['source'])
        self.assertEqual(effect['local_verification'], receipt['local_verification'])
        self.assertEqual(receipt['local_verification'], observed['verification'])
        self.assertEqual(gate['local_verification'], observed['verification'])
        self.assertEqual(gate['binding'], source_case.binding)
        self.assertEqual(gate['dependencies'], source.dependencies)
        self.assertEqual(facts['binding'], source_case.binding)
        self.assertEqual(facts['check_run']['repository_id'], source_case.binding['repository_id'])
        self.assertEqual(facts['outcome'], 'ready')
        self.assertGreater(observed['metadata'], 0)
        self.assertEqual(observed['publication'], 1)
        with state._database(self.scope) as db:
            records = {row['id']: row for row in delegation._ledger(self.scope, db)}
        for identity in (observed['barrier'], source.operation):
            self.assertEqual(records[identity]['data']['status'], 'settled')
            self.assertEqual(records[identity]['data']['result']['outcome'], 'completed')
        self.assertFalse(self.transport.pr['draft'])
        self.assertEqual(self.transport.labels, {'[READY]'})
        self.assertNotEqual(result['task']['state'], 'DONE')
        waiting = self.fixture.verify()
        self.assertEqual(waiting['task']['state'], 'WAITING')
        marker = waiting['task']['delivery']['merge_wait']
        self.assertEqual(marker['verification'], waiting['task']['evidence']['verification'])
        self.case.merged()
        self.case.reconcile('actual-gate-manual-merge')
        settled = self.operate('settle')
        self.assertEqual(settled['task']['state'], 'REVIEW')
        self.assertEqual(self.fixture.verify()['task']['state'], 'DONE')

    def test_reopen_withdraws_remote_readiness_before_acknowledging_edits(self):
        from contextlib import contextmanager
        from runtime import repository_gate
        from tests.test_repository_readiness import RepositoryReadinessTests

        self.retained_readiness()
        original = self.status()
        source_case = RepositoryReadinessTests('runTest')
        source_case.local, source_case.scope = self.fixture, self.scope
        source_case.candidate = evidence.capture_candidate(self.scope,
            evidence._load_plan(self.scope, self.fixture.identity))
        source_case.binding = delivery._publication_binding(original['plan']['publications'][0])
        source = source_case.source(withdrawal=True)
        source.repository = self.transport.adapter
        source_case.request = self.fixture.request(action='ready', publication_id='pr-0', operation_id='e' * 64)
        metadata = source.repository.mutate

        def mutate(*args, **kwargs):
            source.remote_effects = 'uncertain'
            return metadata(*args, **kwargs)

        source.repository.mutate = mutate
        fixture = self

        class Gate:
            @contextmanager
            def acquire_readiness(self, scope, request, binding):
                with repository_gate.acquire_readiness(scope, request, binding) as held:
                    fixture.assertIs(type(held), repository_gate.RepositoryReadiness)
                    fixture.assertTrue(held.withdrawal_only)
                    with fixture.assertRaises(repository_gate.GateError):
                        held.local_verification
                    yield held

        with patch.object(repository_gate, '_acquire_qualified_readiness_source', return_value=source):
            result = self.operate('reopen', gate=Gate())
        self.assertIsNone(result['plan']['publications'][0]['candidate']['readiness'])
        self.assertTrue(self.transport.pr['draft'])
        self.assertEqual(self.transport.labels, {'[BLOCKED]'})
        self.assertNotEqual(result['task']['state'], 'DONE')
        effect = evidence._read(self.scope, result['task']['delivery']['operations'][-1])
        self.assertIsNone(effect['local_verification'])
        self.assertEqual(source.remote_effects, 'uncertain')

    def test_failed_withdrawal_never_acknowledges_reopen(self):
        self.retained_readiness()
        self.transport.failed_undo = True
        with self.assertRaises(ValueError):
            self.operate('reopen', gate=self.fake_gate())
        self.assertFalse(self.transport.pr['draft'])
        self.assertNotEqual(self.status()['task']['state'], 'DONE')

    def test_observed_manual_merge_resolves_only_generated_wait_before_verification(self):
        waiting = self.waiting()
        marker = waiting['task']['delivery']['merge_wait']
        self.case.merged()
        self.case.reconcile('manual-merge')
        result = self.operate('settle')
        conditions = {condition['id']: condition for condition in result['task']['conditions']}
        self.assertEqual(conditions[marker['condition_id']]['status'], 'resolved')
        self.assertEqual(result['task']['state'], 'REVIEW')
        self.assertFalse(any('--method' in argv for argv, _ in self.transport.calls))
        self.assertEqual(self.fixture.verify()['task']['state'], 'DONE')

    def test_observed_merge_does_not_release_explicit_user_pause(self):
        self.waiting()
        self.case.merged()
        self.case.reconcile('manual-merge')
        state.update_task(self.scope, self.fixture.request(state='PAUSED', reason='User paused', reference='user:pause'))
        before = deepcopy(self.status())
        with self.assertRaises(ValueError):
            self.operate('settle')
        self.assertEqual(self.status(), before)
        self.assertEqual(self.transport.calls, [])

    def test_changed_merged_candidate_cannot_release_merge_wait(self):
        self.waiting()
        self.case.merged()
        self.transport.pr['head']['sha'] = 'f' * 40
        self.case.reconcile('changed-merge')
        before = self.status()
        with self.assertRaises(ValueError):
            self.operate('settle')
        self.assertEqual(self.status(), before)
        self.assertEqual(self.transport.calls, [])
