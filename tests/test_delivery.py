"""Delivery adoption is explicit, bounded, and preserves historical decisions."""
from copy import deepcopy
import unittest
from pathlib import Path


def policy(**updates):
    return dict(version=1, merge='manual', separate_worktrees=True, targets=[],
                decision_ref='user:delivery') | updates


class DeliveryPolicyTests(unittest.TestCase):
    def api(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('runtime.delivery'), 'Delivery adoption is missing')
        from runtime import delivery
        return delivery

    def test_defaults_and_task_override(self):
        api = self.api()
        saved = policy()
        original = deepcopy(saved)
        self.assertEqual(api.effective_policy(saved, None), saved)
        override = api.effective_policy(saved, dict(merge='agent', decision_ref='user:this-task'))
        self.assertEqual(override['merge'], 'agent')
        self.assertTrue(override['separate_worktrees'])
        self.assertEqual(saved, original)
        override['targets'].append('untrusted')
        self.assertEqual(saved, original)

    def test_invalid_policy_and_override_are_rejected(self):
        api = self.api()
        for invalid in (policy(version=True), policy(merge='auto'), policy(separate_worktrees=1),
                        policy(decision_ref=''), policy(extra=True), policy(targets=[{}] * 65)):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                api.validate_policy(invalid)
        for invalid in ({'merge': 'agent'}, {'merge': 'agent', 'decision_ref': ''},
                        {'merge': 'agent', 'decision_ref': 'user:1', 'trusted': True}):
            with self.assertRaises(ValueError):
                api.effective_policy(policy(), invalid)

    def test_target_scope_and_duplicates_are_validated(self):
        api = self.api()
        target = dict(provider='github', host='github.com', repository='owner/repo', target='main',
                      merge_method='squash', publication_ref=None, merge_ref=None, remote_cleanup_ref=None)
        self.assertEqual(api.validate_policy(policy(targets=[target]))['targets'], [target])
        for targets in ([target, target], [target | dict(target='--all')],
                        [target | dict(host='github.com/other')], [target | dict(repository='../other')]):
            with self.assertRaises(ValueError):
                api.validate_policy(policy(targets=targets))

    def test_worktree_opt_out_survives_task_override(self):
        result = self.api().effective_policy(policy(separate_worktrees=False),
                                            dict(merge='agent', decision_ref='user:one'))
        self.assertFalse(result['separate_worktrees'])

    def test_read_only_scope_needs_no_delivery_decision(self):
        task = dict(accepted_identity=dict(delivery_policy=policy()), mode='read-only')
        result = self.api().completion_requirements(None, None, task)
        self.assertFalse(result['delivery_required'])
        self.assertTrue(result['delivery_complete'])
        self.assertEqual(result['blockers'], [])

    def test_canonical_projection_binds_policy(self):
        from tests.fixture_canonical_birth import CanonicalBirthFixture
        from runtime import startup, state
        fixture = CanonicalBirthFixture('runTest')
        self.addCleanup(fixture.doCleanups)
        f, request, _, _ = fixture.prepare()
        record = request['manifest']['enrollment']['record']
        original = deepcopy(record)
        repository = record['repositories'][0]
        repository['delivery_policy'] = policy()
        decoded = startup.decode_project_record(record)
        projection = startup._canonical_plain(startup.canonical_scope_projection(decoded,
            repository_id=repository['repository_id'], checkout_id=repository['checkouts'][0]['checkout_id'], client='codex'))
        self.assertEqual(projection['delivery_policy'], policy())
        self.assertEqual(state._accepted_identity(projection)['delivery_policy'], policy())
        self.assertNotEqual(startup._canonical_digest(record), startup._canonical_digest(original))
        repository['delivery_policy'] = policy(merge='invalid')
        with self.assertRaises(ValueError):
            startup.decode_project_record(record)


class DeliveryPlanTests(unittest.TestCase):
    def setUp(self):
        from tests.fixture_canonical_birth import CanonicalBirthFixture
        from runtime import state
        self.fixture = CanonicalBirthFixture('runTest')
        self.addCleanup(self.fixture.doCleanups)
        prepared = self.fixture.prepare(delivery_policy=policy(), linked=getattr(self, 'linked', False))
        self.fixture.assert_applied_configured(prepared, self.fixture.invoke(prepared))
        f = prepared[0]
        from runtime import startup
        _, acquisition, _ = self.fixture.qualify_members(f, Path(prepared[1]['manifest']['enrollment']['record']['project_root']) / startup.PROJECT_FILE)
        self.scope = acquisition.resolution.scope
        self.identity = dict(client='codex', session_id='delivery', task_id='task', scope_ref='user:feature')
        state.start_task(self.scope, self.identity | dict(mode='editable', decision_ref='user:scope'))

    def request(self, **extra):
        from runtime import state
        task = state.task_status(self.scope, 'codex', 'delivery')['task']
        return self.identity | dict(expected_revision=task['revision']) | extra

    def plan(self, **updates):
        return dict(version=1, decision_ref='user:scope', policy=policy(), workspace=None,
                    publications=[], companions=[]) | updates

    def test_plan_is_persisted_and_bound_to_adopted_policy(self):
        from runtime import delivery
        result = delivery.operate(self.scope, 'plan', self.request(plan=self.plan()))
        self.assertEqual(result['plan'], self.plan())
        status = delivery.operate(self.scope, 'status', dict(client='codex', session_id='delivery'))
        self.assertEqual(status['plan'], self.plan())
        with self.assertRaises(ValueError):
            delivery.operate(self.scope, 'plan', self.request(plan=self.plan(policy=policy(merge='agent'))))

    def test_no_publication_decision_requires_explicit_plan(self):
        from runtime import delivery, state
        with state._database(self.scope) as db:
            task = state._task(db, state._scope_id(self.scope), 'codex', 'delivery')
            self.assertTrue(delivery.completion_requirements(self.scope, db, task)['blockers'])
        delivery.operate(self.scope, 'plan', self.request(plan=self.plan()))
        with state._database(self.scope) as db:
            task = state._task(db, state._scope_id(self.scope), 'codex', 'delivery')
            result = delivery.completion_requirements(self.scope, db, task)
            self.assertEqual(result['blockers'], [])
            self.assertTrue(result['delivery_complete'])

    def test_embedded_policy_cannot_use_boolean_integer_equality(self):
        from runtime import delivery
        for invalid in (policy(version=True), policy(separate_worktrees=1)):
            with self.subTest(policy=invalid), self.assertRaises(ValueError):
                delivery.operate(self.scope, 'plan', self.request(plan=self.plan(policy=invalid)))

    def test_policy_edit_cannot_repin_a_bound_task(self):
        import json
        from runtime import state
        path = state._path(self.scope)
        original = path.read_bytes()
        record = json.loads(self.scope.authority_path.read_bytes())
        record['repositories'][0]['delivery_policy']['merge'] = 'agent'
        self.scope.authority_path.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            state.task_status(self.scope, 'codex', 'delivery')
        self.assertEqual(path.read_bytes(), original)


class DeliveryAdoptionRecoveryTests(unittest.TestCase):
    def test_interrupted_adoption_retains_policy_and_allocation(self):
        from unittest.mock import patch
        from tests.fixture_canonical_birth import CanonicalBirthFixture
        from runtime import changes
        from scripts.onboard_coordinator import run_verified_operation
        fixture = CanonicalBirthFixture('runTest')
        self.addCleanup(fixture.doCleanups)
        selected = policy(separate_worktrees=False)
        prepared = fixture.prepare(delivery_policy=selected)
        f, request, decision, _ = prepared

        def interrupt(stage):
            if stage == 'birth-before-commit':
                raise RuntimeError('synthetic interruption')

        with patch.object(changes, '_checkpoint', side_effect=interrupt), self.assertRaises(RuntimeError):
            fixture.invoke(prepared)
        journal = changes._load_journal(f.directory)
        allocation = deepcopy(journal['birth']['allocation'])
        self.assertEqual(journal['manifest']['enrollment']['record']['repositories'][0]['delivery_policy'], selected)
        recovery = deepcopy(decision)
        recovery['operation'] = 'resume'
        recovery['creation']['resume'] = dict(intent_digest=journal['birth']['intent_digest'],
                                            allocation=allocation, baseline=None, certificate_digest=None)
        result = run_verified_operation(recovery, f.directory, request)
        self.assertNotEqual(result['exit_code'], 0)
        retained = changes._load_journal(f.directory)
        self.assertEqual(retained['birth']['allocation'], allocation)
        self.assertEqual(retained['manifest']['enrollment']['record']['repositories'][0]['delivery_policy'], selected)
