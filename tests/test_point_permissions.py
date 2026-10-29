"""Current source permission and final-write rollback regression tests."""
import json
import unittest
from unittest.mock import patch

from runtime import state
from tests import test_foreign_admission


class PointPermissionTests(unittest.TestCase):
    def foreign_fixture(self):
        fixture = test_foreign_admission.ForeignAdmissionTests(methodName='runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    @staticmethod
    def change_record(source, change):
        path = source.scope.authority_path
        record = json.loads(path.read_text())
        change(record)
        path.write_text(json.dumps(record))
        return path.read_bytes()

    def test_fresh_consumption_rechecks_membership_client_and_configuration(self):
        changes = (
            ('membership revoked', lambda row: row['membership'].update(exclude=['.'])),
            ('client suspended', lambda row: row['repositories'][0]['checkouts'][0]['clients'][0]['activation'].update(status='suspended')),
            ('configuration changed', lambda row: row['repositories'][0]['checkouts'][0]['clients'][0]['configuration'].update(policy_digest='0' * 64)),
        )
        for label, change in changes:
            with self.subTest(case=label):
                fixture = self.foreign_fixture()
                source, reference, observations, calls = fixture.source_for(fixture.fixture)
                persisted_record = self.change_record(source, change)
                context = source.api._evidence_context(source.scope)
                original = source.api._source_current_permission
                failures = []

                def trace_permission(selected, binding, **kwargs):
                    try:
                        return original(selected, binding, **kwargs)
                    except state.StateError as error:
                        if selected.directory == context.directory:
                            failures.append(str(error))
                        raise

                with patch.object(source.api, '_source_current_permission', side_effect=trace_permission):
                    with self.assertRaises(state.StateError) as raised:
                        fixture.fixture.verify(observations)

                self.assertTrue(failures and failures[-1].startswith('Current source'))
                self.assertEqual(str(raised.exception), failures[-1])
                self.assertEqual(source.scope.authority_path.read_bytes(), persisted_record)
                self.assertEqual(source.api._source_intents(context, reference['reference']), [])
                self.assertNotIn('linked_verification', fixture.fixture.task(fixture.fixture.selected)['evidence'])
                self.assertEqual(len(calls), 1)

    def test_permission_loss_after_destination_save_rolls_back_aggregate(self):
        fixture = self.foreign_fixture()
        source, reference, observations, calls = fixture.source_for(fixture.fixture)
        source_context = source.api._evidence_context(source.scope)
        destination_context = fixture.fixture.api._evidence_context(fixture.fixture.selected.scope)
        scope_id = state._scope_id(fixture.fixture.selected.scope)
        original_save = state._save
        saved = {}

        def record_aggregate_save(db, selected_scope, task):
            if selected_scope == scope_id and 'linked_verification' in task.get('evidence', {}):
                key = (task['client'], task['session_id'], task['task_id'])
                saved['before'] = state._task(db, selected_scope, *key)
                self.assertNotIn('linked_verification', saved['before']['evidence'])
                result = original_save(db, selected_scope, task)
                saved['db'], saved['key'] = db, key
                saved['after'] = state._task(db, selected_scope, *key)
                return result
            return original_save(db, selected_scope, task)

        original_final = fixture.fixture.api._check_foreign_intent_sources
        final_calls = []
        revocation_reached = []

        def revoke_at_final_check(plan):
            final_calls.append(True)
            if 'after' in saved and not revocation_reached:
                current = state._task(saved['db'], scope_id, *saved['key'])
                self.assertEqual(current, saved['after'])
                self.assertIn('linked_verification', current['evidence'])

                def suspend(record):
                    record['repositories'][0]['checkouts'][0]['clients'][0]['activation']['status'] = 'suspended'

                saved['record'] = self.change_record(source, suspend)
                revocation_reached.append(True)
            return original_final(plan)

        original_permission = source.api._source_current_permission
        permission_failures = []

        def trace_permission(selected, binding, **kwargs):
            try:
                return original_permission(selected, binding, **kwargs)
            except state.StateError as error:
                if selected.directory == source_context.directory:
                    permission_failures.append(str(error))
                raise

        with patch.object(state, '_save', side_effect=record_aggregate_save):
            with patch.object(fixture.fixture.api, '_check_foreign_intent_sources', side_effect=revoke_at_final_check):
                with patch.object(source.api, '_source_current_permission', side_effect=trace_permission):
                    with self.assertRaises(state.StateError) as raised:
                        fixture.fixture.verify(observations)

        self.assertTrue(final_calls)
        self.assertEqual(len(revocation_reached), 1)
        self.assertIn('Current source bookkeeping permission is suspended', permission_failures)
        self.assertEqual(str(raised.exception), permission_failures[-1])
        self.assertEqual(source.scope.authority_path.read_bytes(), saved['record'])
        self.assertEqual(len(source.api._source_intents(source_context, reference['reference'])), 1)
        self.assertEqual(fixture.fixture.task(fixture.fixture.selected), saved['before'])
        self.assertNotIn('linked_verification', fixture.fixture.task(fixture.fixture.selected)['evidence'])
        with fixture.fixture.api._context_database(destination_context) as db:
            self.assertIsNone(state._metadata(db, saved['after']['evidence']['linked_verification']['reference']['name']))
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
