"""Implementation proof and delivery completion have separate meanings."""
import unittest
from unittest.mock import patch

from runtime import delivery, state, title_sync
from tests import test_evidence
from tests.test_delivery import policy


def target():
    return dict(provider='github', host='github.com', repository='owner/repo', target='main',
                merge_method='squash', publication_ref='user:publish', merge_ref=None,
                remote_cleanup_ref=None)


class MergeWaitBindingTests(unittest.TestCase):
    def test_manual_merge_title_uses_latest_applicable_provider_facts(self):
        publication = dict(id='pr', candidate=dict(observation='initial', readiness='receipt'))
        records = dict(initial=dict(observation=dict(draft=False, mergeability=True)),
            receipt=dict(operation='ready', binding='binding'),
            ready=dict(kind='delivery-effect', action='ready', status='completed', binding='binding',
                previous_plan='plan', observation=dict(draft=False, mergeability=False)),
            plan=dict(publications=[dict(id='pr', candidate=dict(observation='initial'))]),
            later=dict(observation=dict(draft=False, mergeability=True)))
        self.assertFalse(delivery._manual_publication_needs_user(publication, records.__getitem__))
        publication['candidate']['observation'] = 'later'
        self.assertTrue(delivery._manual_publication_needs_user(publication, records.__getitem__))

    def test_changed_plan_cannot_reuse_the_old_wait_marker(self):
        reference = lambda char: dict(name=char * 32 + '.json', digest=char * 64)
        condition = dict(id='delivery:merge', kind='blocker', action='task', status='pending',
            reason='Implementation verified; required delivery remains pending', reference='delivery:completion')
        task = dict(state='WAITING', accepted_identity=dict(delivery_policy=policy()), conditions=[condition],
            evidence=dict(verification=reference('a')), delivery=dict(plan=reference('b'), operations=[],
            merge_wait=dict(condition_id=condition['id'], verification=reference('a'), plan=reference('c'))))
        self.assertEqual(delivery.implementation_task(task)['conditions'], [condition])

    def test_generated_wait_preserves_a_resolved_user_condition_with_same_id(self):
        reference = dict(name='a' * 32 + '.json', digest='a' * 64)
        user_condition = dict(id='delivery:merge', kind='decision', action='task', status='resolved',
            reason='User scope', reference='user:scope', resolution_ref='user:chosen')
        task = dict(state='REVIEW', accepted_identity=dict(delivery_policy=policy()), conditions=[user_condition],
            evidence=dict(verification=reference), delivery=dict(plan=reference, operations=[]))
        delivery.apply_completion(task, dict(delivery_complete=False, blockers=[], pending=['pr-0'],
                                            waiting_for_merge=True), True)
        self.assertEqual(task['conditions'][0], user_condition)
        self.assertEqual(task['state'], 'WAITING')
        self.assertEqual(delivery.implementation_task(task)['conditions'], [user_condition])


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_evidence.EvidenceTests('runTest')
        self.fixture._delivery_policy = policy(targets=[target()], separate_worktrees=getattr(self, 'separate_worktrees', True))
        self.fixture._canonical_linked = getattr(self, 'linked', False)
        self.fixture._canonical_peer = getattr(self, 'peer', False)
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.scope = self.fixture.scope

    def delivery_plan(self, count=0, *, required=True):
        publications = [dict(id='pr-' + str(n), **{k: target()[k] for k in
            ('provider', 'host', 'repository', 'target')}, branch='feature-' + str(n),
            candidate=None, pull_request=None, dependencies=[], required=required) for n in range(count)]
        return delivery.operate(self.scope, 'plan', self.fixture.request(plan=dict(version=1,
            decision_ref='user:scope', policy=self.fixture._delivery_policy, workspace=None,
            publications=publications, companions=[])))

    def proof(self):
        self.fixture.ready_proof_fixture()
        return self.fixture.verify()

    def test_missing_delivery_decision_blocks_overall_completion_only(self):
        result = self.proof()
        self.assertTrue(result['implementation_verified'])
        self.assertFalse(result['verified'])
        self.assertFalse(result['delivery_complete'])
        self.assertNotEqual(result['task']['state'], 'DONE')

        self.assertIn('Delivery scope decision is missing', result['blockers'])

    def test_explicit_no_publication_scope_allows_done(self):
        self.delivery_plan()
        result = self.proof()
        self.assertTrue(result['implementation_verified'])
        self.assertTrue(result['delivery_complete'])
        self.assertTrue(result['verified'])
        self.assertEqual(result['task']['state'], 'DONE')

    def test_user_condition_with_delivery_like_id_still_blocks_completion(self):
        self.delivery_plan()
        state.update_task(self.scope, self.fixture.request(state='WORKING', reason='User decision pending',
            reference='user:decision', conditions=[dict(id='delivery:merge', kind='decision', action='task',
            reason='User must choose scope', reference='user:scope')]))
        result = self.proof()
        self.assertFalse(result['verified'])
        self.assertFalse(result['implementation_verified'])
        self.assertNotEqual(result['task']['state'], 'DONE')
        status = self.fixture.api.evidence_status(self.scope, 'codex', 'parent')
        self.assertIn('Task conditions remain unresolved', status['evidence']['blockers'])
        self.assertFalse(status['evidence']['implementation_verified'])

    def test_status_requires_a_current_verification_receipt(self):
        self.delivery_plan()
        self.fixture.ready_proof_fixture()
        status = self.fixture.api.evidence_status(self.scope, 'codex', 'parent')
        self.assertFalse(status['evidence']['implementation_verified'])

    def test_accepted_scope_extension_reopens_done_before_recomputing_progress(self):
        initial = self.delivery_plan()
        old_milestone = dict(id='old-scope', weight=1, accepted=True, reference='user:accepted')
        state.update_task(self.scope, self.fixture.request(state='WORKING', reason='Accepted scope',
            reference='user:accepted', milestones=[old_milestone]))
        completed = self.proof()['task']
        plan = initial['plan'] | dict(decision_ref='user:expanded', publications=[dict(id='new-pr',
            **{k: target()[k] for k in ('provider', 'host', 'repository', 'target')}, branch='new-feature',
            candidate=None, pull_request=None, dependencies=[], required=True)])
        result = delivery.operate(self.scope, 'plan', self.fixture.request(plan=plan,
            previous_plan=completed['delivery']['plan'], change_decision_ref='user:expanded',
            milestones=[old_milestone, dict(id='new-scope', weight=1, accepted=False, reference='user:expanded')]))
        self.assertEqual(result['task']['state'], 'REVIEW')
        self.assertFalse(result['delivery_complete'])
        self.assertIn('new-pr', result['pending'])
        self.assertEqual(title_sync.progress_cells(result['task']), 2)
        self.assertEqual(self.fixture.api._read(self.scope, initial['task']['delivery']['plan']), initial['plan'])
        title = title_sync.format_title('W1', 'P', 'Feature', result['task']['state'], 5)
        self.assertNotIn('▰▰▰▰▰', title)

    def test_scope_revision_preserves_explicit_pause_and_required_deliveries(self):
        initial = self.delivery_plan(1)
        state.update_task(self.scope, self.fixture.request(state='PAUSED', reason='User pause', reference='user:pause'))
        revised = initial['plan'] | dict(decision_ref='user:expanded')
        result = delivery.operate(self.scope, 'plan', self.fixture.request(plan=revised,
            previous_plan=initial['task']['delivery']['plan'], change_decision_ref='user:expanded'))
        self.assertEqual(result['task']['state'], 'PAUSED')
        with self.assertRaises(ValueError):
            delivery.operate(self.scope, 'plan', self.fixture.request(plan=revised | dict(publications=[]),
                previous_plan=result['task']['delivery']['plan'], change_decision_ref='user:expanded'))

    def test_unpublished_required_publications_keep_publication_work_open(self):
        self.delivery_plan(2)
        result = self.proof()
        self.assertTrue(result['implementation_verified'])
        self.assertFalse(result['delivery_complete'])
        self.assertFalse(result['verified'])
        self.assertEqual(result['task']['state'], 'REVIEW')
        conditions = result['task']['conditions']
        self.assertEqual([c['id'] for c in conditions if c['status'] == 'pending'], [])
        title = title_sync.format_title('W1', 'P', 'Feature', result['task']['state'], 4)
        self.assertEqual(title, '\uFFFB▰▰▰▰▱ [W1] P · Feature')
        self.assertNotIn('▰▰▰▰▰', title)
        status = self.fixture.api.evidence_status(self.scope, 'codex', 'parent')
        self.assertFalse(status['evidence']['delivery_complete'])
        self.assertEqual(status['task']['state'], 'REVIEW')
        with state._database(self.scope) as db:
            proof = self.fixture.api._read(self.scope, result['task']['evidence']['verification'], db=db)
        self.assertEqual(proof['blockers'], [])
        self.assertFalse(result['waiting_for_merge'])

    def test_merge_evidence_does_not_require_the_merge_to_have_happened(self):
        self.delivery_plan(1)
        self.fixture.plan()
        self.fixture.checked()
        self.fixture.review()
        result = self.fixture.api.verify_completion(self.scope, self.fixture.request(purpose='merge-evidence'))
        self.assertTrue(result['verified'])
        self.assertTrue(result['implementation_verified'])
        self.assertFalse(result['delivery_complete'])
        self.assertNotEqual(result['task']['state'], 'DONE')


class LinkedCompletionTests(unittest.TestCase):
    def linked(self):
        from tests import test_canonical_composition as canonical
        linked = canonical.CanonicalLinkedLifecycleTests('runTest')
        linked.api = test_evidence.importlib.import_module('runtime.evidence')
        linked.members = []
        for number in range(2):
            case = CompletionTests('runTest')
            case.setUp()
            self.addCleanup(case.doCleanups)
            case.delivery_plan(number)
            linked.members.append(case.fixture)
        linked.selected = linked.members[0]
        linked.establish()
        return linked

    def test_required_child_delivery_does_not_complete_parent_acceptance(self):
        linked = self.linked()
        result = linked.verify()
        self.assertTrue(result['implementation_verified'], result)
        self.assertFalse(result['verified'], result)
        self.assertFalse(result['delivery_complete'], result)
        self.assertEqual(result['task']['state'], 'REVIEW')
        self.assertNotEqual(linked.task(linked.members[1])['state'], 'DONE')

    def test_factual_lifecycle_cannot_release_pending_publication(self):
        linked = self.linked()
        for member in linked.members:
            linked.api._verify_member(member.scope, member.request(purpose='completion'), linked=True)
        result = linked.api._acquire_linked_basis(linked.selected.scope,
            linked.selected.request(purpose='completion'), linked.observations())
        self.assertFalse(result['basis']['delivery_complete'], result)
