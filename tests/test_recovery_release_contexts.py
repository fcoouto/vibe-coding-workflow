"""Release-history capture must retain the issued authority context identities."""
import hashlib
import json
import unittest

from runtime import evidence, recovery_uses, state
from tests import test_changes


class RecoveryReleaseContextTests(unittest.TestCase):
    def fixture(self):
        fixture = test_changes.ScopedChangesTests(methodName='runTest')
        try:
            fixture.setUp()
        except BaseException:
            if not fixture.doCleanups():
                raise AssertionError('Fixture cleanup failed after setup failure')
            raise

        def cleanup():
            if not fixture.doCleanups():
                raise AssertionError('Fixture cleanup failed')

        self.addCleanup(cleanup)
        self.addCleanup(fixture.tearDown)
        request, scope, task_context, task, _ = fixture.historical_shared_consumer()
        identity_ref = {key: task[key] for key in ('client', 'session_id', 'task_id', 'scope_ref')}
        proof = dict(version=1, kind='stopped-writer-reconciliation', identity=identity_ref,
            expected_revision=task['revision'], expected_pins=task['pins'], observed_turn_id=task['turn_id'],
            stopped=True, descendants_stopped=True, attempt_ids=[], observation_ref='fixture:stopped',
            coordinator_ref='fixture:owner')
        path = fixture.directory / 'release-context-stop.json'
        raw = json.dumps(proof, sort_keys=True).encode()
        path.write_bytes(raw)
        path.chmod(0o600)
        retired = state.retire_task(scope, identity_ref | dict(expected_revision=task['revision'],
            expected_pins=task['pins'], reason='Observed stopped writer and descendants',
            reference='fixture:native-retirement',
            stop_proof=dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest())))['task']
        self.assertEqual(retired['pins'], task['pins'])
        self.assertEqual(retired['state'], 'cancelled')
        applied = fixture.run_with_d4_host(request, 'apply')
        self.assertEqual(applied['exit_code'], 0, applied)
        contexts = tuple(evidence._evidence_context(existing) for existing in fixture.d4_bookkeeping_scopes)
        sources = [fixture.changes._recovery_sources(item)[1] for item in contexts]
        identity = next(body['identity'] for rows in sources for _, body in rows
            if body['identity']['plan_dir'] == str(fixture.directory))
        authorities = tuple(evidence._canonical_plain(item.authority_set[0]) for item in contexts)
        return fixture, request, contexts, authorities, identity, scope, task_context, retired, proof

    def test_annotated_two_authority_release_preserves_issued_contexts(self):
        fixture, request, contexts, authorities, identity, scope, task_context, retired, proof = self.fixture()
        changes = fixture.changes
        prior = {}
        with evidence._context_database(task_context) as db:
            _, proof_raw = evidence._managed_artifact(None, retired['retirement']['proof'],
                context=task_context, db=db)
            self.assertEqual(json.loads(proof_raw), proof)
        for context in contexts:
            _, sources = changes._recovery_sources(context)
            reference, body = next((ref, body) for ref, body in sources if body['identity'] == identity)
            with evidence._context_database(context) as db:
                prior[context.database] = (reference, state._metadata(db, reference['name'])['created_at'],
                    evidence._canonical_plain(body), evidence._recovery_source_history(context, db, reference, identity))

        observation = changes._observe_recovery_release(authorities, identity)
        captured = evidence._canonical_plain(observation.content)
        self.assertEqual(captured['version'], 2)
        self.assertIn('use_contract', captured)
        self.assertEqual(captured['authorities'], sorted(authorities, key=evidence._digest))
        result = evidence._canonical_plain(changes._register_recovery_release(observation))
        self.assertTrue(result['complete'], result)
        self.assertEqual(len(result['replacements']), 2, result)
        self.assertEqual({evidence._digest(row['authority']) for row in result['replacements']},
            {evidence._digest(authority) for authority in authorities})

        for context in contexts:
            _, sources = changes._recovery_sources(context)
            reference, body = next((ref, body) for ref, body in sources if body['identity'] == identity)
            with evidence._context_database(context) as db:
                age = state._metadata(db, reference['name'])['created_at']
                history = evidence._recovery_source_history(context, db, reference, identity)
            old_ref, old_age, old_body, old_history = prior[context.database]
            self.assertEqual(age, old_age)
            self.assertEqual(len(history), 1)
            self.assertEqual(body['previous'], None)
            self.assertEqual(old_history[0], (old_ref, old_body))
            self.assertEqual(body['identity'], identity)
            self.assertEqual(body['version'], 2)
            self.assertIn('use_contract', body)

        task_ref = next(row['reference'] for row in captured['stopped'] if row['reference']['task_id'] == 'historical-consumer')
        inspection = evidence._canonical_plain(changes.inspect_lifecycle_recovery(authorities, (task_ref,)))
        self.assertTrue(inspection['complete'], inspection)
        self.assertEqual(inspection['blockers'], [], inspection)
        self.assertFalse(any(row.get('need') == 'raw' and row.get('reference') == task_ref
            for row in inspection['requirements']))
        with evidence._context_database(task_context) as db:
            actual = state._task(db, state._scope_id(scope), 'codex', 'historical-consumer', 'historical-consumer')
            _, current_proof_raw = evidence._managed_artifact(None, retired['retirement']['proof'],
                context=task_context, db=db)
        self.assertEqual(actual, retired)
        self.assertEqual(current_proof_raw, proof_raw)

    def test_release_history_capture_rejects_equal_valued_fresh_context(self):
        fixture, request, contexts, authorities, identity, _, _, _, _ = self.fixture()
        changes = fixture.changes
        first = changes._observe_recovery_release(authorities, identity)
        second = changes._observe_recovery_release(authorities, identity)
        self.assertEqual([evidence._canonical_plain(c.authority_set[0]) for c in first.contexts],
            [evidence._canonical_plain(c.authority_set[0]) for c in second.contexts])
        self.assertTrue(all(a is not b for a, b in zip(first.contexts, second.contexts)))

        with changes._recovery_release_guards(authorities, identity) as (_, journal, guarded_contexts):
            context = second.contexts[0]
            reader_context = next(item for item in guarded_contexts
                if item.database == context.database)
            _, sources = changes._recovery_sources(reader_context)
            reference, _ = next((ref, body) for ref, body in sources if body['identity'] == identity)
            with evidence._context_database(reader_context) as db, self.assertRaisesRegex(
                    recovery_uses.UseContractError, 'History capture borrowed another context'):
                evidence._recovery_history_inputs(context, db, reference, first, journal['manifest'],
                    recovery_uses.CaptureBudget())


if __name__ == '__main__':
    unittest.main()
