"""Actual managed before receipts with synthetic Native discovery; no native execution."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from runtime import delegation, evidence, setup_observation, state
from runtime.engine import RuntimeEvent
from tests import test_delegation as native_fixtures
from tests import test_evidence as evidence_fixtures
from tests import test_staged_admission as staged_fixtures


class QualificationBeforeTests(TestCase):
    def setUp(self):
        self.owned = staged_fixtures.GenuineStagedAdmissionTests('runTest')
        self.addCleanup(self.owned.doCleanups)
        self.owned.setUp()
        self.repo = self.owned.fixture.repo
        (self.repo / 'app.py').write_text('value = 1\n')

    def prepare_native(self, *, probe=None):
        original = self.owned.journal['qualification_scope']['attempts'][0]
        if probe is not None:
            original['probe'] = probe
        self.scope = self.owned.acquire(operations=('task-start', 'task-patch', 'native-worker'),
            keys=('pre-tool-enforcement', 'post-tool-handling', 'stop-ownership', 'interrupt-ownership'),
            max_attempts=2, max_resource_units=8)
        self.owned.start()
        native = native_fixtures.AdmissionTests('runTest')
        self.native = native
        native.scope, native.identity = self.scope, self.owned.identity
        native.api, native.repo, native.root = delegation, self.repo, self.owned.fixture.base
        proxy = SimpleNamespace(api=evidence, scope=self.scope, request=native.request)
        evidence_fixtures.EvidenceTests.plan(proxy, decision_ref='user:qualification')
        native.catalog = dict(version=1, client_surface='codex-cli', native_version='0.163.0',
            parent_session_id=native.identity['session_id'], originator='fixture-cli',
            parent_model_provider='native-provider',
            catalog=[dict(model='new-native-model', supported_efforts=['low', 'high'], default_effort='low')],
            dispatch_controls=dict(spawn=True, explicit_model=True, explicit_effort=True, fork_turns_none=True),
            capability_digest='a' * 64, limitations=['Synthetic discovery; no native execution'])
        native.cache_request = dict(client_surface='codex-cli', applicability=dict(
            client_version='0.163.0', capability_fingerprint='a' * 64))
        claim = delegation.claim_guidance(self.scope, native.cache_request | dict(trigger=dict(kind='routine', id='before-fixture')))
        guidance = dict(schema_version=1, client_surface='codex-cli', checked_at='2026-01-01T00:00:00Z',
            applicability=native.cache_request['applicability'], sources=[dict(id='official',
                url='https://example.org/official', sha256='b' * 64)], recommendations=[dict(id='bounded',
                work='Bounded code work', risk='Local concurrency-sensitive work', models=[],
                conditions=['Coordinator verifies capability'], limitations=['Advice only'], source_ids=['official'])])
        delegation.record_guidance(self.scope, native.cache_request | dict(token=claim['token'],
            generation=claim['generation'], coordinator_ref='fixture:verified', guidance=guidance))
        discovery = patch('runtime.adapters.codex.discover_native_workers',
            side_effect=lambda scope, controls: deepcopy(native.catalog))
        discovery.start()
        self.addCleanup(discovery.stop)
        native.plan()
        return native

    def record(self, attempt_id):
        with state._database(self.scope) as db:
            return next(row for row in delegation._ledger(self.scope, db, task=self.owned.identity)
                if row['id'] == attempt_id)

    def test_qualification_before_matches_actual_final_writer_and_replays_unchanged(self):
        native = self.prepare_native()
        expected = {}
        insert = delegation._insert_assignment
        def inspect(db, scope, task, record):
            expected.update(revision=task['revision'], generation=db.execute(
                'select generation from checkouts where scope_id=?', (state._scope_id(scope),)).fetchone()[0],
                receipt_watermark=db.execute('select coalesce(max(rowid),0) from receipts').fetchone()[0])
            return insert(db, scope, task, record)
        request = native.prepare_request()
        with patch.object(delegation, '_insert_assignment', side_effect=inspect):
            prepared = delegation.prepare_assignment(self.scope, request)
        record = self.record(prepared['attempt_id'])
        self.assertIn('qualification_before', record['body'])
        reference = record['body']['qualification_before']
        with state._database(self.scope) as db:
            before = evidence._read(self.scope, reference, db=db)
            metadata = state._metadata(db, reference['name'])
        self.assertEqual(set(before), {'version', 'kind', 'assignment_id', 'identity', 'pins', 'revision',
            'generation', 'receipt_watermark', 'candidate', 'plan', 'probe'})
        self.assertEqual(before['kind'], 'qualification-native-before')
        self.assertEqual(before['version'], 1)
        self.assertEqual(before['assignment_id'], prepared['attempt_id'])
        self.assertNotEqual(before['assignment_id'], self.owned.owner.attempt_ref['reference'])
        self.assertEqual(before['identity'], record['owner'])
        self.assertEqual(before['pins'], record['body']['pins'])
        self.assertEqual({key:before[key] for key in expected}, expected)
        self.assertEqual(before['revision'] + 1, record['data']['revision'])
        self.assertEqual(before['candidate'], record['data']['candidate'])
        self.assertEqual(before['plan'], record['body']['plan'])
        self.assertIsNone(before['probe'])
        self.assertIsNotNone(metadata)
        self.assertTrue(all(dict(kind='artifact', reference=before[key]) in metadata['dependencies']
            for key in ('candidate', 'plan')))
        references = []
        with state._database(self.scope) as db:
            delegation._ledger(self.scope, db, task=self.owned.identity, artifact_refs=references)
        self.assertIn(reference, references)
        self.assertNotIn('qualification_before', record['data'])
        replay = delegation.prepare_assignment(self.scope, request)
        self.assertFalse(replay['launch_admitted'])
        self.assertEqual(self.record(prepared['attempt_id'])['body']['qualification_before'], reference)
        self.assertEqual(evidence._read(self.scope, reference), before)

    def test_post_tool_receipt_is_newer_than_before_and_duplicate_does_not_advance(self):
        native = self.prepare_native()
        state.update_task(self.scope, native.request(state='WORKING', reason='Observe bounded receipt',
            reference='user:qualification'))
        event = RuntimeEvent('PreToolUse', 'codex', native.identity['session_id'], self.repo,
            'before-turn', 'before-call', 'apply_patch', False, 'before-fingerprint')
        self.assertEqual(state.process_event(self.scope, event).action, 'pass')
        prepared = native.prepare()
        record = self.record(prepared['attempt_id'])
        self.assertIn('qualification_before', record['body'])
        before = evidence._read(self.scope, record['body']['qualification_before'])
        post = RuntimeEvent('PostToolUse', 'codex', native.identity['session_id'], self.repo,
            'before-turn', 'fresh-call', 'apply_patch', False, 'fresh-fingerprint')
        state.process_event(self.scope, post)
        with state._database(self.scope) as db:
            fresh = db.execute('select rowid from receipts where scope_id=? and client=? and session_id=? '
                'and turn_id=? and tool_call_id=? and kind=?', (state._scope_id(self.scope), 'codex',
                native.identity['session_id'], post.turn_id, post.tool_call_id, 'PostToolUse')).fetchone()[0]
            generation = db.execute('select generation from checkouts where scope_id=?',
                (state._scope_id(self.scope),)).fetchone()[0]
        self.assertGreater(fresh, before['receipt_watermark'])
        self.assertEqual(generation, before['generation'] + 1)
        state.process_event(self.scope, post)
        with state._database(self.scope) as db:
            self.assertEqual(db.execute('select coalesce(max(rowid),0) from receipts').fetchone()[0], fresh)
            self.assertEqual(db.execute('select generation from checkouts where scope_id=?',
                (state._scope_id(self.scope),)).fetchone()[0], generation)
        self.assertEqual(evidence._read(self.scope, record['body']['qualification_before']), before)

    def test_original_public_probe_is_captured_with_independent_readback(self):
        raw = (self.repo / 'app.py').read_bytes()
        descriptor = dict(canary=str(self.repo / 'app.py'), before_sha256=hashlib.sha256(raw).hexdigest(),
            patch='*** Begin Patch\n*** Update File: app.py\n@@\n-value = 1\n+value = 2\n*** End Patch')
        native = self.prepare_native(probe=descriptor)
        prepared = native.prepare()
        record = self.record(prepared['attempt_id'])
        before = evidence._read(self.scope, record['body']['qualification_before'])
        self.assertEqual(before['probe']['descriptor'], descriptor)
        fact = before['probe']['before']
        self.assertEqual(set(fact), {'canary', 'target', 'readback'})
        self.assertEqual(fact['canary'], descriptor['canary'])
        self.assertEqual(fact['readback'], raw.decode())
        self.assertEqual(fact['target']['fingerprint']['sha256'], descriptor['before_sha256'])
        physical = (self.repo / 'app.py').stat()
        self.assertEqual(fact['target']['binding'], dict(device=physical.st_dev, inode=physical.st_ino))

    def test_probe_hash_mismatch_cannot_publish_an_assignment(self):
        descriptor = dict(canary=str(self.repo / 'app.py'), before_sha256='0' * 64,
            patch='*** Begin Patch\n*** Update File: app.py\n@@\n-value = 1\n+value = 2\n*** End Patch')
        native = self.prepare_native(probe=descriptor)
        with self.assertRaisesRegex(state.StateError, 'Original qualification public probe changed'):
            native.prepare()
        with state._database(self.scope) as db:
            self.assertEqual(delegation._ledger(self.scope, db, task=self.owned.identity), [])


class OrdinaryBeforeShapeTests(TestCase):
    def test_ordinary_assignment_does_not_gain_before_body_or_ledger_fields(self):
        native = native_fixtures.AdmissionTests('runTest')
        self.addCleanup(native.doCleanups)
        native.setUp()
        native.plan()
        prepared = native.prepare()
        with state._database(native.scope) as db:
            record = next(row for row in delegation._ledger(native.scope, db) if row['id'] == prepared['attempt_id'])
        self.assertNotIn('qualification_before', record['body'])
        self.assertNotIn('qualification_before', record['data'])
        self.assertNotIn('qualification_before', json.loads(prepared['prompt'])['assignment'])


class TaskStartCapabilityModeTests(TestCase):
    def test_read_only_start_uses_pre_but_editable_start_also_requires_post(self):
        from tests.test_state import StateTests
        fixture = StateTests('runTest')
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        required = setup_observation.require_capability
        calls = []
        def pre_only(scope, keys, **kwargs):
            calls.append(tuple(keys))
            if 'post-tool-handling' in keys:
                raise state.StateError('post capability unavailable')
            return required(scope, keys, **kwargs)
        with patch.object(setup_observation, 'require_capability', side_effect=pre_only):
            started = fixture.start(mode='read-only')
            self.assertEqual(started['task']['mode'], 'read-only')
            self.assertEqual(calls, [('pre-tool-enforcement',)])
            with self.assertRaisesRegex(state.StateError, 'post capability unavailable'):
                state.start_task(fixture.scope, fixture.request | dict(session_id='editing'))
        self.assertEqual(calls[-1], ('pre-tool-enforcement', 'post-tool-handling'))
