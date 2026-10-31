"""Focused source for real D4 recovery-release predecessor receipt tests."""

import unittest
from unittest.mock import patch

from runtime import evidence, state
from tests.test_changes import ScopedChangesTests


class RecoveryReleaseReceiptTests(unittest.TestCase):
    def setUp(self):
        class ReceiptFixture(ScopedChangesTests):
            def d4_bookkeeping_request(self, *, umbrella=False, state_root=None,
                    initialize_checkout=True):
                return super().d4_bookkeeping_request(umbrella=umbrella, state_root=state_root,
                    initialize_checkout=False if umbrella else initialize_checkout)

        self.fixture = ReceiptFixture(methodName='runTest')
        try:
            self.fixture.setUp()
        except BaseException:
            if not self.fixture.doCleanups():
                raise AssertionError('Fixture cleanup failed after setup failure')
            raise

        def cleanup():
            if not self.fixture.doCleanups():
                raise AssertionError('Fixture cleanup failed')

        self.addCleanup(cleanup)

    def heads(self, contexts, identity):
        result = {}
        for context in contexts:
            with evidence._context_database(context) as db:
                rows = [row['reference'] for row in state._source_baseline(None, db, context=context)['dependencies']
                    if row['reference']['identity'] == identity]
                self.assertEqual(len(rows), 1)
                head = evidence._canonical_plain(rows[0]['artifact'])
                body = evidence._canonical_plain(evidence._read(None, head, context=context, db=db))
                metadata = evidence._canonical_plain(state._metadata(db, head['name']))
            result[str(context.database)] = dict(context=context, authority=evidence._canonical_plain(context.authority_set[0]),
                head=head, body=body, metadata=metadata)
        return result

    def release(self, contexts, identity):
        authorities = tuple(authority for context in contexts for authority in context.authority_set)
        return authorities, self.fixture.changes._register_recovery_release(
            self.fixture.changes._observe_recovery_release(authorities, identity))

    def stopped_task(self, suffix):
        scope = self.fixture.release_fixture_scope
        identity = dict(client='codex', session_id='receipt-session-' + suffix,
            task_id='task-' + suffix, scope_ref='request:' + suffix)
        state.start_task(scope, identity | dict(mode='editable', decision_ref='user:' + suffix))
        _, certificate = self.fixture.stop_assignment_fixture(scope, identity)
        return certificate['reference']

    def assert_receipt(self, current, previous):
        self.assertNotEqual(current['head'], previous['head'])
        receipt = dict(authority=previous['authority'], artifact=previous['head'],
            identity=previous['body']['identity'], journal_sha256=previous['body']['journal']['sha256'])
        self.assertIn(receipt, current['body']['supersedes'])
        for inherited in previous['body']['supersedes']:
            self.assertIn(inherited, current['body']['supersedes'])

    def assert_readable_unchanged(self, previous):
        context = previous['context']
        with evidence._context_database(context) as db:
            body = evidence._canonical_plain(evidence._read(None, previous['head'], context=context, db=db))
            metadata = evidence._canonical_plain(state._metadata(db, previous['head']['name']))
        self.assertEqual(body, previous['body'])
        self.assertEqual(metadata, previous['metadata'])

    def test_genuine_v2_replacements_receipt_exact_predecessor_and_noop_is_stable(self):
        fixture = self.fixture
        request, context, _, identity, _ = fixture.recovery_release_fixture()
        contexts = (context,)
        authorities, first = self.release(contexts, identity)
        self.assertTrue(first['complete'], first)

        replacements = []
        for suffix in ('two', 'three'):
            task_ref = self.stopped_task(suffix)
            resumed = fixture.run_with_d4_host(request, 'resume')
            self.assertEqual(resumed['exit_code'], 0, resumed)
            predecessor = self.heads(contexts, identity)[str(context.database)]
            self.assertEqual(predecessor['body']['version'], 2)
            self.assertIn(task_ref, [row['reference'] for row in predecessor['body']['tasks']])
            observed_authorities, result = self.release(contexts, identity)
            self.assertEqual(observed_authorities, authorities)
            self.assertTrue(result['complete'], result)
            current = self.heads(contexts, identity)[str(context.database)]
            self.assertEqual(current['body']['version'], 2)
            self.assert_receipt(current, predecessor)
            self.assertNotIn(task_ref, [row['reference'] for row in current['body']['tasks']])
            self.assertIn(task_ref, [row['reference'] for row in current['body']['stopped']])
            self.assertEqual(current['metadata']['created_at'], predecessor['metadata']['created_at'])
            self.assert_readable_unchanged(predecessor)
            replacements.append((predecessor, result['replacements']))

        prior = self.heads(contexts, identity)
        for _ in range(2):
            _, replay = self.release(contexts, identity)
            self.assertTrue(replay['complete'], replay)
            self.assertEqual(replay['replacements'], replacements[-1][1])
            current = self.heads(contexts, identity)
            self.assertEqual(current, prior)

    def test_mixed_store_retry_preserves_committed_head_and_receipts(self):
        fixture = self.fixture
        request, _, _, identity, _ = fixture.recovery_release_fixture(umbrella=True)
        contexts = fixture.release_fixture_contexts
        self.assertEqual(len({str(context.database) for context in contexts}), 2)
        authorities = tuple(authority for context in contexts for authority in context.authority_set)
        initial = fixture.changes._register_recovery_release(
            fixture.changes._observe_recovery_release(authorities, identity))
        self.assertTrue(initial['complete'], initial)

        task_ref = self.stopped_task('two')
        resumed = fixture.run_with_d4_host(request, 'resume')
        self.assertEqual(resumed['exit_code'], 0, resumed)
        before = self.heads(contexts, identity)
        self.assertTrue(all(row['body']['version'] == 2 for row in before.values()))
        self.assertTrue(all(task_ref in [item['reference'] for item in row['body']['tasks']] for row in before.values()))

        original_register = evidence._register_recovery_source
        seen, failed = [], set()

        def fail_second_store(scope, db, source, *, context=None):
            key = str(context.database)
            if key not in seen:
                seen.append(key)
            if len(seen) == 2 and key == seen[1] and key not in failed:
                failed.add(key)
                raise OSError('fixture second-store fault')
            return original_register(scope, db, source, context=context)

        observation = fixture.changes._observe_recovery_release(authorities, identity)
        with patch.object(evidence, '_register_recovery_source', side_effect=fail_second_store):
            partial = fixture.changes._register_recovery_release(observation)
        self.assertFalse(partial['complete'], partial)
        self.assertEqual(len(partial['replacements']), 1)
        self.assertEqual(len(failed), 1)
        after_partial = self.heads(contexts, identity)
        committed_key = next(key for key in before if after_partial[key]['head'] != before[key]['head'])
        laggard_key = next(key for key in before if key != committed_key)
        committed = after_partial[committed_key]
        self.assert_receipt(committed, before[committed_key])
        self.assertEqual(after_partial[laggard_key], before[laggard_key])

        inspection = fixture.changes.inspect_lifecycle_recovery(authorities, ())
        self.assertTrue(inspection['complete'], inspection)
        raw = [row for row in inspection['requirements'] if row['kind'] == 'task' and row['reference'] == task_ref and row['need'] == 'raw']
        identity_only = [row for row in inspection['requirements'] if row['kind'] == 'task' and row['reference'] == task_ref and row['need'] == 'identity']
        self.assertTrue(raw, inspection)
        self.assertTrue(identity_only, inspection)

        retry = fixture.changes._register_recovery_release(
            fixture.changes._observe_recovery_release(authorities, identity))
        self.assertTrue(retry['complete'], retry)
        after_retry = self.heads(contexts, identity)
        self.assertEqual(after_retry[committed_key], committed)
        self.assertNotEqual(after_retry[laggard_key]['head'], before[laggard_key]['head'])
        self.assert_receipt(after_retry[laggard_key], before[laggard_key])
        self.assertFalse(any(row['kind'] == 'task' and row['reference'] == task_ref and row['need'] == 'raw'
            for row in fixture.changes.inspect_lifecycle_recovery(authorities, ())['requirements']))
        for _ in range(2):
            _, replay = self.release(contexts, identity)
            self.assertTrue(replay['complete'], replay)
            self.assertEqual(replay['replacements'], retry['replacements'])
            self.assertEqual(self.heads(contexts, identity), after_retry)


if __name__ == '__main__':
    unittest.main()
