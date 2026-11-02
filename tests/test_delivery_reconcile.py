"""Qualified fixture reads record merge facts without manufacturing local proof."""
import unittest

from runtime import delivery, evidence, state
from scripts.delivery_coordinator import DeliveryOperationOwner
from tests import test_delivery_completion, test_github_delivery


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.case = test_delivery_completion.CompletionTests('runTest')
        self.case.peer = getattr(self, 'peer', False)
        self.case.linked = not self.case.peer
        self.case.separate_worktrees = not self.case.peer
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.fixture, self.scope = self.case.fixture, self.case.scope
        self.case.delivery_plan(1, required=getattr(self, 'required', True))
        self.provider = test_github_delivery.GitHubDeliveryTests('runTest')
        self.provider.setUp()
        self.provider.pr['head']['ref'] = 'feature-0'
        self.fixture.git('checkout', '-b', 'feature-0')
        self.fixture.git('add', '--', 'AGENTS.md')
        self.fixture.git('commit', '-qm', 'fixture accepted instructions')
        self.provider.pr['head']['sha'] = self.fixture.git('rev-parse', 'HEAD')
        outer = self

        class Native:
            def observe_worktree(self, root):
                return dict(root=str(root), owner='codex', attachment='fixture:native-attachment', reference='fixture:observed')

            def observe_publication(self, scope, publication, number):
                return dict(host='github.com', repository='owner/repo', repository_id=123, pull_request=number,
                    branch='feature-0', target='main', head=outer.provider.pr['head']['sha'],
                    reference='fixture:independently-observed-PR-ownership')

        self.native = Native()
        request = self.fixture.request(operation_id='workspace')
        self.owner('bind-worktree', request).run(self.scope, 'bind-worktree', request)
        self.fixture.ready_proof_fixture()

    def owner(self, action, request):
        return DeliveryOperationOwner(dict(action=action, request_digest=evidence._digest(request),
            accepted_scope_digest=self.scope.accepted_scope_digest, reference='fixture:verified-host-decision'),
            native=self.native, repository=self.provider.adapter(), gate=None)

    def reconcile(self, identity='observe-1', **updates):
        request = self.fixture.request(operation_id=identity, publication_id='pr-0', pull_request=42, **updates)
        return self.owner('reconcile', request).run(self.scope, 'reconcile', request)

    def merged(self):
        self.provider.pr.update(state='closed', draft=False, merged=True,
            merged_at='2026-11-02T12:00:00Z', merge_commit_sha='c' * 40)

    def test_manual_merge_observation_is_factual_and_never_merges_or_declares_done(self):
        opened = self.reconcile()
        self.assertFalse(opened['delivery_complete'])
        waiting = self.fixture.verify()
        self.assertEqual(waiting['task']['state'], 'REVIEW')
        proof = waiting['task']['evidence']['verification']
        self.merged()
        result = self.reconcile('observe-2')
        self.assertTrue(result['delivery_complete'])
        self.assertEqual(result['task']['state'], 'REVIEW')
        self.assertEqual(result['task']['evidence']['verification'], proof)
        self.assertTrue(all(argv[1] == 'api' for argv, _ in self.provider.calls))

    def test_exact_replay_does_not_repeat_observation_or_allow_changed_inputs(self):
        request = self.fixture.request(operation_id='observe-1', publication_id='pr-0', pull_request=42)
        owner = self.owner('reconcile', request)
        first = owner.run(self.scope, 'reconcile', request)
        count = len(self.provider.calls)
        replay = owner.run(self.scope, 'reconcile', request)
        self.assertEqual(first['task']['revision'], replay['task']['revision'])
        self.assertEqual(count, len(self.provider.calls))
        changed = request | dict(pull_request=43)
        with self.assertRaisesRegex(ValueError, 'reused'):
            self.owner('reconcile', changed).run(self.scope, 'reconcile', changed)

    def test_changed_merged_head_does_not_satisfy_the_sealed_candidate(self):
        self.reconcile()
        self.merged()
        self.provider.pr['head']['sha'] = 'e' * 40
        result = self.reconcile('observe-2')
        self.assertFalse(result['delivery_complete'])
        self.assertTrue(result['blockers'])

    def test_closed_unmerged_is_pending_with_a_disposition_needed(self):
        self.provider.pr.update(state='closed')
        result = self.reconcile()
        self.assertFalse(result['delivery_complete'])
        self.assertIn('Required PR was closed without merge: pr-0', result['blockers'])

    def test_replaced_repository_identity_cannot_deliver_the_original_scope(self):
        self.reconcile()
        self.provider.repo['id'] = 999
        self.merged()
        result = self.reconcile('observe-2')
        self.assertFalse(result['delivery_complete'])
        self.assertTrue(result['blockers'])

    def test_observed_merge_does_not_manufacture_missing_readiness_provenance(self):
        self.reconcile()
        self.fixture.verify()
        self.merged()
        self.reconcile('observe-2')
        result = self.fixture.verify()
        self.assertTrue(result['implementation_verified'])
        self.assertTrue(result['delivery_complete'])
        self.assertFalse(result['verified'])
        self.assertNotEqual(result['task']['state'], 'DONE')

    def test_uncommitted_local_contents_cannot_be_sealed_as_the_remote_candidate(self):
        (self.fixture.repo / 'app.py').write_text('unpublished = True\n')
        before = delivery.operate(self.scope, 'status', dict(client='codex', session_id='parent'))['plan']
        with self.assertRaisesRegex(ValueError, 'uncommitted'):
            self.reconcile()
        self.assertEqual(delivery.operate(self.scope, 'status', dict(client='codex', session_id='parent'))['plan'], before)


class SurvivingAuthorityTests(unittest.TestCase):
    def test_optional_open_pr_stays_visible_and_protected_after_own_completion(self):
        fixture = ReconcileTests('runTest')
        fixture.required = False
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.reconcile()
        completed = fixture.fixture.verify()['task']
        self.assertEqual(completed['state'], 'DONE')
        inventory = delivery.pending(fixture.scope)
        self.assertEqual(len(inventory['records']), 1)
        self.assertFalse(inventory['records'][0]['retention_complete'])
        self.assertFalse(inventory['records'][0]['delivery_required'])
        self.assertIn('pr-0', inventory['records'][0]['retention_pending'])

    def test_removed_original_checkout_keeps_factual_observation_and_sealed_proof(self):
        import shutil
        fixture = ReconcileTests('runTest')
        fixture.peer = True
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        initial = fixture.reconcile()
        original = state._canonical_plain(evidence._artifact_owner(fixture.scope, initial['task']).task)
        survivor = fixture.fixture.peer_scope
        identity = dict(client='codex', session_id='observer', task_id='observe', scope_ref='user:observe')
        producer = state.start_task(survivor, identity | dict(mode='editable', decision_ref='user:observe'))['task']
        proof = initial['task']['evidence'].copy()
        shutil.rmtree(fixture.scope.repository_root)
        fixture.merged()
        request = identity | dict(expected_revision=producer['revision'], original=original,
            target_revision=initial['task']['revision'], publication_id='pr-0', operation_id='surviving-observer')
        owner = DeliveryOperationOwner(dict(action='reconcile', request_digest=evidence._digest(request),
            accepted_scope_digest=survivor.accepted_scope_digest, reference='fixture:verified-surviving-owner'),
            native=None, repository=fixture.provider.adapter(), gate=None)
        result = owner.run(survivor, 'reconcile', request)
        self.assertTrue(result['observation']['merged'])
        self.assertTrue(result['delivery_complete'])
        self.assertNotEqual(result['task']['state'], 'DONE')
        self.assertEqual(result['task']['evidence'], proof)
        self.assertFalse(fixture.scope.repository_root.exists())
