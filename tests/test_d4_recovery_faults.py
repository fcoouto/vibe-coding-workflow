"""D4 partial durable recovery publication and retry tests."""
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch

from runtime import evidence, state
from tests import test_changes


class D4RecoveryFaultTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_changes.ScopedChangesTests(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_partial_peer_commit_resumes_with_original_age_and_complete_heads(self):
        changes = self.fixture.changes
        request, contexts = self.fixture.d4_bookkeeping_request(umbrella=True)
        self.assertEqual(len(contexts), 2)
        before_effects = {a['id']: changes._fingerprint(Path(a['owner']['root']), a['effects'][0]['path'])
            for a in request['manifest']['actions']}
        before_baselines = {}
        for context in contexts:
            with evidence._context_database(context) as db:
                before_baselines[str(context.database)] = evidence._canonical_plain(state._source_baseline(None, db, context=context))
        issued = []

        class Host:
            def acquire_d4_bookkeeping(self, facts, issue):
                grant = issue(facts)
                issued.append(grant)
                return grant

        original_register = evidence._register_recovery_source
        calls, durable = [], {}

        def fail_after_second_store_write(scope, db, source, *, context=None):
            reference = original_register(scope, db, source, context=context)
            if not durable:
                if not calls:
                    calls.append(context)
                    return reference
                if context.database != calls[0].database:
                    first = calls[0]
                    with evidence._context_database(first) as reader:
                        baseline = evidence._canonical_plain(state._source_baseline(None, reader, context=first))
                        edges = [row for row in baseline['dependencies']
                            if row['reference']['identity'] == evidence._canonical_plain(source.content)['identity']]
                        self.assertEqual(len(edges), 1)
                        head = edges[0]['reference']['artifact']
                        body = evidence._read(None, head, context=first, db=reader)
                        metadata = state._metadata(reader, head['name'])
                        self.assertEqual(body['identity'], evidence._canonical_plain(source.content)['identity'])
                        self.assertEqual(metadata['created_at'], source.created_at)
                        durable.update(context=first, identity=body['identity'], head=head,
                            body=evidence._canonical_plain(body), age=metadata['created_at'])
                    calls.append(context)
                    raise changes.StartupError('fixture failure at second peer registration')
            return reference

        with changes._bootstrap_d4_host(Host(), issuer=changes._D4_HOST_BOOTSTRAP_ISSUER) as host:
            with patch.object(evidence, '_register_recovery_source', side_effect=fail_after_second_store_write):
                failed = changes._run_scoped(self.fixture.directory, request, 'apply', host=host)
        self.assertEqual(failed['exit_code'], 2, failed)
        self.assertEqual(len(issued), 1)
        self.assertTrue(any('second peer registration' in item['reason'] for item in failed['blocked']), failed)
        self.assertEqual(len(calls), 2)
        self.assertIn('head', durable)
        for action in request['manifest']['actions']:
            self.assertEqual(changes._fingerprint(Path(action['owner']['root']), action['effects'][0]['path']), before_effects[action['id']])
        authority_rows = [evidence._canonical_plain(c.authority_set[0]) for c in contexts]
        authority_markers = changes._authority_locations([c.directory for c in contexts])
        root = Path(request['manifest']['enrollment']['record']['project_root'])
        canonical_marker = Path(changes.LOCK_ROOT) / ('canonical-' + hashlib.sha256(
            ('destination:' + str(root / changes.PROJECT_FILE)).encode()).hexdigest() + '.lock')
        for marker in [*authority_markers, canonical_marker]:
            self.assertIsNotNone(changes._authority_owner(marker), str(marker))
        inspection = changes.inspect_lifecycle_recovery(authority_rows, ())
        self.assertFalse(inspection['complete'], inspection)
        self.assertTrue(any(row.get('reason') == 'active_or_uncertain_operation' for row in inspection['blockers']), inspection)
        for context in contexts:
            if context.database != durable['context'].database:
                with evidence._context_database(context) as db:
                    self.assertEqual(evidence._canonical_plain(state._source_baseline(None, db, context=context)),
                        before_baselines[str(context.database)])

        with changes._bootstrap_d4_host(Host(), issuer=changes._D4_HOST_BOOTSTRAP_ISSUER) as host:
            resumed = changes._run_scoped(self.fixture.directory, request, 'resume', host=host)
        self.assertEqual(resumed['exit_code'], 0, resumed)
        self.assertGreaterEqual(len(issued), 2)
        self.assertEqual(len({id(grant.acquisition) for grant in issued}), len(issued))
        final_bodies, final_histories = [], {}
        for context in contexts:
            with evidence._context_database(context) as db:
                baseline = evidence._canonical_plain(state._source_baseline(None, db, context=context))
                edges = [row for row in baseline['dependencies']
                    if row['reference']['identity'] == durable['identity']]
                self.assertEqual(len(edges), 1)
                head = edges[0]['reference']['artifact']
                body = evidence._canonical_plain(evidence._read(None, head, context=context, db=db))
                self.assertEqual(body['identity'], durable['identity'])
                self.assertEqual(state._metadata(db, head['name'])['created_at'], durable['age'])
                history = evidence._recovery_source_history(context, db, head, durable['identity'])
                references = [reference for reference, _ in history]
                self.assertEqual(len(references), len({evidence._raw(reference) for reference in references}))
                for reference, prior in history:
                    self.assertEqual(prior['identity'], durable['identity'])
                    self.assertEqual(state._metadata(db, reference['name'])['created_at'], durable['age'])
                final_histories[str(context.database)] = [(dict(reference), dict(prior)) for reference, prior in history]
                final_bodies.append(body)
        common_bodies = []
        for body in final_bodies:
            common = dict(body)
            common.pop('previous')
            common_bodies.append(common)
        self.assertEqual(common_bodies[0], common_bodies[1])
        first_history = final_histories[str(durable['context'].database)]
        retained = next((body for reference, body in first_history if reference == durable['head']), None)
        self.assertEqual(retained, durable['body'])
        self.assertEqual(len({body['identity']['transaction_id'] for body in final_bodies}), 1)
        for marker in [*authority_markers, canonical_marker]:
            self.assertIsNone(changes._authority_owner(marker), str(marker))

    def test_actual_taskless_guidance_release_keeps_nonempty_independent_support(self):
        request, path, guidance, context, project = self.fixture.d4_reachable_taskless_guidance()
        with evidence._context_database(context) as db:
            original_guidance = state._metadata(db, guidance['name'])
        self.assertEqual(original_guidance['owner'], dict(kind='project', project_id=project, task=None))
        facts = []

        class Host:
            def acquire_d4_bookkeeping(self, acquired, issue):
                facts.append(evidence._canonical_plain(acquired))
                return issue(acquired)

        with self.fixture.changes._bootstrap_d4_host(
                Host(), issuer=self.fixture.changes._D4_HOST_BOOTSTRAP_ISSUER) as host:
            applied = self.fixture.changes._run_scoped(self.fixture.directory, request, 'apply', host=host)
        self.assertEqual(applied['exit_code'], 0, applied)
        self.assertTrue(path.exists())
        self.assertEqual(len(facts), 2)
        identity = facts[0]['identity']
        authority = evidence._canonical_plain(context.authority_set[0])
        with evidence._context_database(context) as db:
            baseline = evidence._canonical_plain(state._source_baseline(None, db, context=context))
            edge = next(row for row in baseline['dependencies'] if row['reference']['identity'] == identity)
            original_head = edge['reference']['artifact']
            source_body = evidence._canonical_plain(evidence._read(None, original_head, context=context, db=db))
            self.assertTrue(source_body['tasks'])
            self.assertTrue(source_body['assignments'])
            self.assertIn(dict(authority=authority, artifact=guidance), source_body['artifacts'])
            self.assertIn(dict(kind='artifact', reference=dict(authority=authority, artifact=guidance)),
                state._metadata(db, original_head['name'])['dependencies'])
            original_age = state._metadata(db, original_head['name'])['created_at']

        released = self.fixture.changes._observe_recovery_release(context.authority_set, identity)
        release_content = evidence._canonical_plain(released.content)
        self.assertTrue(release_content['stopped'])
        self.assertTrue(release_content['stopped'][0]['assignments'])
        self.assertEqual(release_content['stopped'][0]['assignments'][0]['reconciliation']['outcome'], 'cancelled')
        self.assertIn(dict(authority=authority, artifact=guidance), release_content['artifacts'])
        result = self.fixture.changes._register_recovery_release(released)
        self.assertTrue(result['complete'], result)
        self.assertEqual(len(result['replacements']), 1)
        with evidence._context_database(context) as db:
            baseline = evidence._canonical_plain(state._source_baseline(None, db, context=context))
            edge = next(row for row in baseline['dependencies'] if row['reference']['identity'] == identity)
            replacement = edge['reference']['artifact']
            body = evidence._canonical_plain(evidence._read(None, replacement, context=context, db=db))
            metadata = state._metadata(db, replacement['name'])
            self.assertNotEqual(replacement, original_head)
            self.assertEqual(metadata['created_at'], original_age)
            self.assertTrue(body['stopped'])
            self.assertEqual(body['stopped'][0]['assignments'][0]['reconciliation']['outcome'], 'cancelled')
            self.assertIn(dict(authority=authority, artifact=guidance), body['artifacts'])
            self.assertIn(dict(kind='artifact', reference=dict(authority=authority, artifact=guidance)), metadata['dependencies'])
            retained = state._metadata(db, guidance['name'])
            self.assertEqual(retained['owner'], original_guidance['owner'])
            self.assertEqual(retained['created_at'], original_guidance['created_at'])
        root = Path(request['manifest']['enrollment']['record']['project_root'])
        canonical_marker = Path(self.fixture.changes.LOCK_ROOT) / ('canonical-' + hashlib.sha256(
            ('destination:' + str(root / self.fixture.changes.PROJECT_FILE)).encode()).hexdigest() + '.lock')
        for marker in [*self.fixture.changes._authority_locations([context.directory]), canonical_marker]:
            self.assertIsNone(self.fixture.changes._authority_owner(marker), str(marker))


if __name__ == '__main__':
    unittest.main()
