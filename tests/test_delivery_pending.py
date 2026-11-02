"""Pending inventory is bounded, local and independent of checkout scans."""
import unittest

from runtime import delivery, state
from tests import test_delivery


class PendingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_delivery.DeliveryPlanTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.scope = self.fixture.scope

    def test_pages_known_tasks_without_mutation_or_silent_exhaustion(self):
        for number in range(34):
            state.start_task(self.scope, dict(client='codex', session_id='session-' + str(number),
                task_id='task', scope_ref='user:task', mode='editable', decision_ref='user:accepted'))
        database = state._path(self.scope)
        before = database.read_bytes()
        first = delivery.pending(self.scope)
        self.assertLessEqual(len(first['records']), 32)
        self.assertIsNotNone(first['cursor'])
        second = delivery.pending(self.scope, cursor=first['cursor'])
        self.assertIsNone(second['cursor'])
        records = first['records'] + second['records']
        self.assertEqual(len(records), 35)
        self.assertEqual(len({(r['scope_id'], r['client'], r['session_id'], r['task_id']) for r in records}), 35)
        self.assertTrue(all(r['blockers'] for r in records))
        self.assertEqual(database.read_bytes(), before)
        self.assertEqual(first['coverage'], 'known retained tasks in this authority')

    def test_invalid_bounds_and_cursor_fail_explicitly(self):
        for limit in (True, 0, 33, '32'):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                delivery.pending(self.scope, limit=limit)
        for cursor in ('', 'not a cursor', '{}'):
            with self.subTest(cursor=cursor), self.assertRaises(ValueError):
                delivery.pending(self.scope, cursor=cursor)

    def test_explicit_no_delivery_decision_is_not_listed_as_pending(self):
        delivery.operate(self.scope, 'plan', self.fixture.request(plan=self.fixture.plan()))
        result = delivery.pending(self.scope)
        self.assertEqual(result['records'], [])
        self.assertIsNone(result['cursor'])

    def test_inventory_survives_a_client_removed_checkout(self):
        import shutil
        from pathlib import Path
        from runtime import startup
        from tests.fixture_canonical_birth import CanonicalBirthFixture
        host = CanonicalBirthFixture('runTest')
        self.addCleanup(host.doCleanups)
        prepared = host.prepare(peer=True, delivery_policy=test_delivery.policy())
        host.assert_applied_configured(prepared, host.invoke(prepared))
        fixture = prepared[0]
        authority = Path(prepared[1]['manifest']['enrollment']['record']['project_root']) / startup.PROJECT_FILE
        host.qualify_members(fixture, authority)
        scopes = [member.resolution.scope for member in fixture.member_acquisitions.values()]
        self.assertEqual(len(scopes), 2)
        for number, scope in enumerate(scopes):
            state.start_task(scope, dict(client='codex', session_id='peer-' + str(number), task_id='task',
                scope_ref='user:peer', mode='editable', decision_ref='user:accepted'))
        shutil.rmtree(scopes[1].repository_root)
        result = delivery.pending(scopes[0])
        self.assertEqual({row['session_id'] for row in result['records']}, {'peer-0', 'peer-1'})
