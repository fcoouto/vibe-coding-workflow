"""Genuine ordinary A/B owner, current-demand and managed-byte protection."""
import stat
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime import evidence, state
from tests import test_recovery_release_contexts
from tests.test_ordinary_closure_authorities import ordinary_retired_historical_consumer


def _owner_snapshot(context, reference):
    with evidence._context_database(context) as db:
        return dict(sql=tuple(db.iterdump()),
            task=state._task(db, *(reference[key] for key in ('scope_id', 'client', 'session_id', 'task_id'))),
            metadata=tuple(db.execute('select name,class,created_at,closed_at from evidence_metadata order by name')),
            markers=tuple(db.execute('select kind,identity_digest,data,assignment_id from retired_identities '
                'order by kind,identity_digest')))


def _files(context):
    return {path.name: path.read_bytes() for path in sorted((context.directory / 'evidence').iterdir())}


def _tamper_managed(testcase, context, reference):
    with evidence._context_database(context) as db:
        metadata, raw = evidence._managed_artifact(None, reference, context=context, db=db)
    path = Path(metadata['managed']['path'])
    testcase.assertEqual(path, context.directory / 'evidence' / reference['name'])
    testcase.assertTrue(raw)
    changed = bytes([raw[0] ^ 1]) + raw[1:]
    original_mode = stat.S_IMODE(path.lstat().st_mode)
    try:
        path.chmod(original_mode | stat.S_IWUSR)
        with path.open('r+b') as stream:
            testcase.assertEqual(stream.write(changed[:1]), 1)
    finally:
        path.chmod(original_mode)
    testcase.assertEqual(stat.S_IMODE(path.lstat().st_mode), original_mode)
    testcase.assertEqual(path.read_bytes(), changed)
    return path, changed


class OrdinaryClosureProtectionTests(unittest.TestCase):
    def _prepared_case(self, *, release=True):
        (fixture, request, contexts, authorities, source_identity, scope, task_context,
         stopped_task, proof) = test_recovery_release_contexts.RecoveryReleaseContextTests.fixture(self)
        owner = next(context for context in contexts if context.database == task_context.database)
        peer = next(context for context in contexts if context is not owner)
        _, sources = fixture.changes._recovery_sources(owner)
        source_ref, source = next((reference, body) for reference, body in sources
            if body['identity'] == source_identity)
        source_task = next(row for row in source['tasks']
            if all(row['reference'][key] == stopped_task[key] for key in ('client', 'session_id', 'task_id'))
            and row['reference']['authority'] == evidence._canonical_plain(owner.authority_set[0]))
        reference = source_task['reference']
        with evidence._context_database(owner) as db:
            certificate = fixture.changes._stopped_certificate(owner, db, source_task)
        self.assertEqual(certificate['proof'], proof)
        self.assertEqual(certificate['retirement'], stopped_task['retirement'])
        self.assertIsNone(stopped_task['lifecycle']['safe_closed_at'])
        if release:
            observation = fixture.changes._observe_recovery_release(authorities, source_identity)
            captured = evidence._canonical_plain(observation.content)
            self.assertIn(certificate, captured['stopped'])
            released = evidence._canonical_plain(fixture.changes._register_recovery_release(observation))
            self.assertTrue(released['complete'], released)
            _, sources = fixture.changes._recovery_sources(owner)
            source_ref, source = next((reference, body) for reference, body in sources
                if body['identity'] == source_identity)
            self.assertIn(certificate, source['stopped'])
        inspection = evidence._canonical_plain(fixture.changes.inspect_lifecycle_recovery(authorities, (reference,)))
        self.assertTrue(inspection['complete'], inspection)
        self.assertEqual(inspection['blockers'], [], inspection)
        self.assertEqual(inspection['discovered_authorities'], [], inspection)
        self.assertEqual(sorted(inspection['authorities'], key=evidence._digest),
            sorted(authorities, key=evidence._digest))
        if release:
            self.assertFalse(any(row['kind'] == 'task' and row['reference'] == reference and row['need'] == 'raw'
                for row in inspection['requirements']), inspection)
        close_request = {key: stopped_task[key] for key in ('client', 'session_id', 'task_id', 'scope_ref')}
        close_request.update(expected_revision=stopped_task['revision'], expected_pins=stopped_task['pins'])
        return dict(fixture=fixture, request=request, contexts=contexts, authorities=authorities, scope=scope,
            owner=owner, peer=peer, reference=reference, stopped_task=stopped_task, proof=proof,
            certificate=certificate, source_identity=source_identity, source_ref=source_ref, source=source,
            inspection=inspection, close_request=close_request)

    def _assert_unchanged(self, context, reference, before, files):
        self.assertEqual(_owner_snapshot(context, reference), before,
            'Rejection changed raw task, SQL, metadata, closure dates or retirement markers')
        self.assertEqual(_files(context), files, 'Rejection changed managed files or created a compact')

    def _managed_failure_trace(self, context, reference, failures):
        original = evidence._managed_content

        def checked(selected, actual, metadata):
            try:
                return original(selected, actual, metadata)
            except state.StateError as error:
                if selected.database == context.database and actual == reference:
                    failures.append(str(error))
                raise

        return patch.object(evidence, '_managed_content', new=checked)

    def test_genuine_peer_task_reaches_unsupported_owner_guard(self):
        case = self._prepared_case()
        peer_scope = next(scope for scope in case['fixture'].historical_accepted_scopes
            if scope.runtime.state_dir == case['peer'].directory)
        started = state.start_task(peer_scope, dict(client=peer_scope.client,
            session_id='ordinary-peer-owner', task_id='ordinary-peer-owner', scope_ref='fixture:ordinary-peer-owner',
            mode='read-only', decision_ref='fixture:accepted-peer-owner'))
        self.assertTrue(started['ok'], started)
        self.assertEqual(started['task']['state'], 'planned')
        self.assertEqual(started['task']['accepted_identity'], evidence._canonical_plain(peer_scope.accepted_identity))
        with evidence._context_database(case['peer']) as db:
            self.assertEqual(state._task(db, state._scope_id(peer_scope), peer_scope.client,
                'ordinary-peer-owner', 'ordinary-peer-owner'), started['task'])
            peer_before = tuple(db.iterdump())
        before = _owner_snapshot(case['owner'], case['reference'])
        files, peer_files = _files(case['owner']), _files(case['peer'])
        with self.assertRaisesRegex(state.StateError, '^Ordinary closure peer has unsupported owner history$'):
            evidence._observe_closure((case['owner'],), case['reference'])
        self._assert_unchanged(case['owner'], case['reference'], before, files)
        self.assertIsNone(before['task']['lifecycle']['safe_closed_at'])
        with evidence._context_database(case['peer']) as db:
            self.assertEqual(tuple(db.iterdump()), peer_before, 'Rejection changed the genuine peer task')
        self.assertEqual(_files(case['peer']), peer_files)

    def test_independent_current_source_retains_real_raw_task_demand(self):
        case = self._prepared_case(release=False)
        root = dict(authority=evidence._canonical_plain(case['owner'].authority_set[0]),
            identity=case['source_identity'], source_artifact=case['source_ref'])
        self.assertIn(root, case['inspection']['roots'])
        self.assertIn(dict(root=root, owner=dict(authority=root['authority'], artifact=case['source_ref']),
            kind='task', reference=case['reference'], need='raw'), case['inspection']['requirements'])
        self.assertTrue(any(row['reference'] == case['reference'] for row in case['source']['tasks']))
        with evidence._context_database(case['owner']) as db:
            self.assertEqual(case['fixture'].changes._stopped_certificate(case['owner'], db,
                next(row for row in case['source']['tasks'] if row['reference'] == case['reference'])),
                case['certificate'])
        before = _owner_snapshot(case['owner'], case['reference'])
        files = _files(case['owner'])
        with self.assertRaisesRegex(state.StateError,
                '^An independent current consumer still requires the raw task body$'):
            evidence._observe_closure((case['owner'],), case['reference'])
        self._assert_unchanged(case['owner'], case['reference'], before, files)
        self.assertIsNone(before['task']['lifecycle']['safe_closed_at'])

    def test_real_new_owner_invalidates_issued_closure_observation(self):
        case = self._prepared_case()
        issued = evidence._observe_closure((case['owner'],), case['reference'])
        self.assertEqual(evidence._issued_closure(case['owner'], issued)['task_ref'], case['reference'])
        started = state.start_task(case['scope'], dict(client=case['scope'].client,
            session_id='ordinary-new-owner', task_id='ordinary-new-owner', scope_ref='fixture:ordinary-new-owner',
            mode='read-only', decision_ref='fixture:accepted-new-owner'))
        self.assertTrue(started['ok'], started)
        self.assertEqual(started['task']['state'], 'planned')
        with evidence._context_database(case['owner']) as db:
            self.assertEqual(state._task(db, state._scope_id(case['scope']), case['scope'].client,
                'ordinary-new-owner', 'ordinary-new-owner'), started['task'])
        before = _owner_snapshot(case['owner'], case['reference'])
        files = _files(case['owner'])
        with self.assertRaisesRegex(state.StateError, '^Closure owner observation is stale or caller supplied$'):
            evidence.close_task(case['scope'], case['close_request'], issued)
        self._assert_unchanged(case['owner'], case['reference'], before, files)
        self.assertIsNone(before['task']['lifecycle']['safe_closed_at'])

    def test_original_stop_artifact_tamper_prevents_observation(self):
        case = self._prepared_case()
        reference = case['stopped_task']['retirement']['proof']
        with evidence._context_database(case['owner']) as db:
            self.assertEqual(evidence._read(None, reference, context=case['owner'], db=db), case['proof'])
        path, changed = _tamper_managed(self, case['owner'], reference)
        before = _owner_snapshot(case['owner'], case['reference'])
        files = _files(case['owner'])
        failures = []
        with self._managed_failure_trace(case['owner'], reference, failures):
            with self.assertRaisesRegex(state.StateError, '^Evidence artifact unavailable, unsafe or corrupt$'):
                evidence._observe_closure((case['owner'],), case['reference'])
        self.assertTrue(failures, 'The actual original stop artifact validator was not reached')
        self.assertEqual(set(failures), {'Artifact physical ownership changed'})
        self._assert_unchanged(case['owner'], case['reference'], before, files)
        self.assertIsNone(before['task']['lifecycle']['safe_closed_at'])
        self.assertEqual(path.read_bytes(), changed, 'The deliberate stop tamper must remain test input')

    def test_retained_compact_tamper_prevents_real_retirement(self):
        captured = {}
        original = evidence._retire_closed_task

        def retire(context, reference):
            self.assertFalse(captured, 'Only the genuine first retirement is intercepted')
            task = _owner_snapshot(context, reference)['task']
            self.assertIsNotNone(task['lifecycle']['safe_closed_at'])
            compact = task['lifecycle']['compact']
            with evidence._context_database(context) as db:
                body = evidence._read(None, compact, context=context, db=db)
                self.assertEqual(body['kind'], 'task-closure')
                self.assertEqual(body['identity'], reference)
                self.assertEqual(body['stopped']['retirement'], task['retirement'])
            path, changed = _tamper_managed(self, context, compact)
            captured.update(context=context, reference=reference, compact=compact, path=path, changed=changed,
                before=_owner_snapshot(context, reference), files=_files(context), failures=[])
            with self._managed_failure_trace(context, compact, captured['failures']):
                return original(context, reference)

        with patch.object(evidence, '_retire_closed_task', new=retire):
            with self.assertRaisesRegex(state.StateError, '^Evidence artifact unavailable, unsafe or corrupt$'):
                ordinary_retired_historical_consumer(self)
        self.assertTrue(captured, 'The genuine close/replay path never reached actual retirement')
        self.assertEqual(captured['failures'], ['Artifact physical ownership changed'])
        self._assert_unchanged(captured['context'], captured['reference'], captured['before'], captured['files'])
        self.assertEqual(captured['before']['task']['lifecycle']['compact'], captured['compact'])
        self.assertEqual(captured['path'].read_bytes(), captured['changed'],
            'The deliberate compact tamper must remain test input')


if __name__ == '__main__':
    unittest.main()
