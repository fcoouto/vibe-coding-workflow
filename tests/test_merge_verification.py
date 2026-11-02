"""Held verification uses real local reservations; native observations are fixtures."""
import unittest

from runtime import delegation, evidence, state
from tests import test_evidence


class MergeVerificationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_evidence.EvidenceTests('runTest')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.scope = self.fixture.scope
        self.fixture.plan()
        self.fixture.checked()
        self.fixture.review()

    def acquire(self):
        acquire = getattr(evidence, 'acquire_merge_verification', None)
        self.assertTrue(callable(acquire), 'Merge publication needs a live verification reservation')
        return acquire(self.scope, self.fixture.request(purpose='merge-evidence'))

    def record(self, grant):
        with state._database(self.scope) as db:
            return next(row for row in delegation._ledger(self.scope, db)
                        if row['id'] == grant.barrier_id)

    def test_publication_keeps_actual_reservation_until_local_finalize(self):
        with self.acquire() as grant:
            self.assertEqual(self.record(grant)['data']['status'], 'prepared')
            self.assertFalse(grant.recheck()['merge_authority'])
            with state._database(self.scope) as db:
                task = state._task(db, state._scope_id(self.scope), 'codex', 'parent')
                self.assertEqual(task['evidence']['verification'], grant.verification_ref)
                claims = delegation._claims([dict(kind='path', key=str(self.fixture.repo / 'app.py'), mode='write')])
                with self.assertRaises(state.StateError):
                    delegation._resources_available(self.scope, db, claims, delegation._ledger(self.scope, db))
            seen = []
            def publish(db):
                self.assertTrue(db.in_transaction)
                seen.append(db)
                return grant.record(dict(version=1, kind='fixture-publication',
                    verification=grant.verification_ref), db=db)
            reference = grant.finalize(publish)
            self.assertEqual(len(seen), 1)
            self.assertEqual(evidence._read(self.scope, reference)['kind'], 'fixture-publication')
            with self.assertRaises(state.StateError):
                grant.finalize(publish)
        with state._database(self.scope) as db:
            records = delegation._ledger(self.scope, db)
            self.assertTrue(all(row['data']['status'] == 'settled' for row in records))
        with self.assertRaises(state.StateError):
            grant.recheck()

    def test_uncertain_publication_and_context_close_keep_recovery_owner(self):
        with self.acquire() as grant:
            barrier = grant.barrier_id
            with self.assertRaisesRegex(RuntimeError, 'uncertain publication'):
                grant.finalize(lambda db: (_ for _ in ()).throw(RuntimeError('uncertain publication')))
            self.assertEqual(self.record(grant)['data']['status'], 'prepared')
        with self.assertRaises(state.StateError):
            grant.recheck()
        with state._database(self.scope) as db:
            actual = next(row for row in delegation._ledger(self.scope, db) if row['id'] == barrier)
            self.assertEqual(actual['data']['status'], 'prepared')
            self.assertIsNone(actual['data']['reconciliation'])

    def test_changed_candidate_cannot_reach_publication_callback(self):
        with self.acquire() as grant:
            (self.fixture.repo / 'app.py').write_text('value = 2\n')
            def forbidden(db):
                self.fail('Changed candidate reached publication')
            with self.assertRaises(state.StateError):
                grant.finalize(forbidden)
            self.assertEqual(self.record(grant)['data']['status'], 'prepared')

    def test_ordinary_completion_keeps_settle_on_return(self):
        result = self.fixture.verify()
        self.assertTrue(result['verified'], result)
        with state._database(self.scope) as db:
            records = delegation._ledger(self.scope, db)
        self.assertTrue(records)
        self.assertTrue(all(row['data']['status'] == 'settled' for row in records))


if __name__ == '__main__':
    unittest.main()
