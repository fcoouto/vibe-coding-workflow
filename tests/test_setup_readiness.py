"""Disposable D5/D6 owner tests with controlled native review transport."""

import importlib.util
import time
import unittest
from unittest.mock import patch

from runtime import delegation, evidence, setup_observation, startup, state
from tests import test_evidence, test_staged_admission


class SetupReadinessTests(unittest.TestCase):
    def test_owner_reads_settled_review_and_verification_without_completing_task(self):
        owner = test_staged_admission.GenuineStagedAdmissionTests('runTest')
        self.addCleanup(owner.doCleanups)
        owner.setUp()
        owner.identity['session_id'] = 'parent'
        attempt = owner.journal['qualification_scope']['attempts'][0]
        attempt['task']['session_id'] = 'parent'
        attempt['native_sessions'] = ['parent', 'reviewer']
        scope = owner.acquire(
            operations=('task-start', 'check-run', 'native-review', 'verify-completion'),
            keys=('pre-tool-enforcement', 'post-tool-handling', 'stop-ownership',
                'interrupt-ownership', 'review-readiness'),
            max_attempts=2, max_resource_units=2,
        )
        owner.start(decision_ref='user:accepted')

        d5 = test_evidence.EvidenceTests('runTest')
        self.addCleanup(d5.doCleanups)
        d5.root, d5.repo, d5.scope = owner.fixture.base, owner.fixture.repo, scope
        d5.identity, d5.api = owner.identity, evidence
        d5.git('config', 'user.email', 'fixture@example.invalid')
        d5.git('config', 'user.name', 'Fixture')
        (d5.repo / 'app.py').write_text('value = 1\n')
        d5.git('add', 'app.py')
        d5.git('commit', '-qm', 'public fixture')
        d5.plan()
        check = d5.checked()
        review = d5.review()
        result = d5.verify()
        self.assertTrue(result['qualification_verified'], result['blockers'])
        self.assertFalse(result['verified'])
        self.assertFalse(result['merge_authority'])
        self.assertNotEqual(result['task']['state'], 'DONE')
        review_id = review['attempt']['id']
        request = owner.request(check_attempt_id=check['attempt_id'], review_attempt_id=review_id)

        spec = importlib.util.find_spec('runtime.setup_readiness')
        self.assertIsNotNone(spec, 'The retained owner must expose a typed qualification issuer')
        from runtime import setup_readiness
        with state._database(scope) as db:
            record = delegation._ledger(scope, db, assignment_id=review_id)[0]
            latest = delegation._worker_history(scope, record['data']['observation'], db=db)[0][1]
        native = patch('runtime.adapters.codex.observe_native_review_assignment',
            return_value=dict(receipt=latest['receipt'], result=latest['result']))
        reader = native.start()
        self.addCleanup(native.stop)
        issued = setup_readiness.observe(scope, request)
        reader.assert_called_once_with(scope, review_id, 'turn', 'spawn')
        facts = setup_readiness.evidence(issued, scope)
        self.assertEqual(facts['accepted_scope_digest'], scope.accepted_scope_digest)
        self.assertEqual(facts['attempt_ref'], owner.owner.attempt_ref)
        self.assertEqual(facts['review_attempt_id'], review_id)
        self.assertEqual(facts['check_attempt_id'], check['attempt_id'])
        self.assertEqual(len(facts['observations']), 7)
        self.assertEqual(owner.task(), result['task'])
        original = next(iter(owner.journal['setup_receipts'].values()))
        assessment = startup._canonical_copy(original['assessment'])
        row = next(row for row in assessment['cases'] if row['id'] == 'review-readiness')
        previous = original['source']['observations'].get('review-readiness', [])
        row.update(status='verified', evidence=[*assessment['general_review'], *previous, *facts['observations']])
        source = startup._canonical_plain(scope.qualification['reference'])
        # Simulate a genuine, separately bounded readiness read taking longer
        # than the local D4 file-acquisition window.
        real_clock = time.monotonic
        read_readiness = setup_readiness.evidence
        elapsed = 0

        def observe_readiness(*args):
            nonlocal elapsed
            facts = read_readiness(*args)
            elapsed = 5
            return facts

        with patch.object(time, 'monotonic', side_effect=lambda: real_clock() + elapsed), \
                patch.object(setup_readiness, 'evidence', side_effect=observe_readiness):
            successor = setup_observation.collect_retained_setup(source, original['identity'],
                'review-readiness-successor', assessment, readiness=issued)
        self.assertEqual(setup_observation._issued(successor)['source']['observations']['review-readiness'], [*previous, *facts['observations']])
        config = owner.owner.config
        before = config.read_bytes()

        def observe_then_change_config(*args):
            facts = read_readiness(*args)
            config.write_bytes(before.replace(b'hooks = true', b'hooks = false', 1))
            return facts

        try:
            with patch.object(setup_readiness, 'evidence', side_effect=observe_then_change_config):
                with self.assertRaisesRegex(startup.StartupError, 'observable setup configuration changed'):
                    setup_observation.collect_retained_setup(source, original['identity'],
                        'review-readiness-successor', assessment, readiness=issued)
        finally:
            config.write_bytes(before)
        with self.assertRaises(state.StateError):
            setup_observation.collect_retained_setup(source, original['identity'],
                'review-readiness-successor', assessment, readiness=facts)
        with self.assertRaises(state.StateError):
            setup_readiness.evidence(facts, scope)
        with self.assertRaises(state.StateError):
            setup_readiness.observe(scope, request | dict(review_attempt_id='foreign'))
        with self.assertRaises(state.StateError):
            setup_readiness.observe(scope, request | dict(check_attempt_id='foreign'))
        with patch('runtime.adapters.codex.observe_native_review_assignment',
                return_value=dict(receipt=latest['receipt'] | {'turn_status': 'failed'}, result=None)):
            with self.assertRaisesRegex(state.StateError, 'latest native review'):
                setup_readiness.evidence(issued, scope)
        (d5.repo / 'app.py').write_text('value = 2\n')
        with self.assertRaises(state.StateError):
            setup_readiness.evidence(issued, scope)
