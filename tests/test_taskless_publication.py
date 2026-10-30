"""Taskless publication uses genuine grants, local writers and durable peer boundaries."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from runtime import changes, evidence, state
from runtime.startup import StartupError, PROJECT_FILE
from tests import test_changes as fixtures


class TasklessPublicationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ScopedChangesTests(methodName='runTest')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)

    def test_actual_writer_overlay_is_visible_and_readers_cannot_issue(self):
        fixture = self.fixture
        request, contexts = fixture.d4_bookkeeping_request(umbrella=True)
        original = evidence._register_recovery_source
        writers = []; acquired = []
        def register(scope, db, source, *, context=None):
            reference = original(scope, db, source, context=context)
            lifetime = changes._authority_context.publication
            self.assertIs(lifetime['writer'][0], context); self.assertIs(lifetime['writer'][1], db)
            self.assertTrue(changes._taskless_publication(source, lifetime))
            self.assertFalse(source.content['tasks']); self.assertFalse(source.content['assignments'])
            with evidence._context_database(context) as reader:
                self.assertIsNone(state._metadata(reader, reference['name']))
                with self.assertRaisesRegex(StartupError, 'actual supplied writer'):
                    changes._check_d4_publication(source, context, reader)
            with patch.object(sqlite3, 'connect', side_effect=AssertionError('Writer checkpoint opened SQLite')):
                self.assertIs(changes._check_d4_publication(source, context, db), lifetime)
                evidence._check_recovery_registration(context, db, source)
            writers.append(reference); acquired.append(lifetime)
            return reference
        with patch.object(evidence, '_register_recovery_source', side_effect=register):
            result = fixture.run_with_d4_host(request, 'apply')
        self.assertEqual(result['exit_code'], 0, result)
        self.assertEqual(len(writers), 4)
        self.assertTrue(any(chain['history'] for lifetime in acquired
            for chains in lifetime['local_chain_inputs'].values() for chain in chains))
        self.assertTrue(all(lifetime['writer'] is None and not lifetime['active'] for lifetime in acquired))
        self.assertTrue(changes.inspect_lifecycle_recovery(contexts[0].authority_set, ())['complete'])

    def test_late_peer_failure_retains_first_link_and_markers_then_reacquires(self):
        fixture = self.fixture
        request, contexts = fixture.d4_bookkeeping_request(umbrella=True)
        original_database = evidence._context_database
        original_register = evidence._register_recovery_source
        calls = []; damaged = []; grants = []
        before = {(action['owner']['root'], effect['path']): changes._fingerprint(Path(action['owner']['root']), effect['path'])
            for action in request['manifest']['actions'] for effect in action['effects']}
        def register(*args, **kwargs):
            reference = original_register(*args, **kwargs)
            calls.append((kwargs['context'], reference)); return reference
        @contextmanager
        def database(context, **kwargs):
            with original_database(context, **kwargs) as db: yield db
            if not kwargs.get('durable') or damaged: return
            # The first real writer has committed; damage an existing peer baseline, never invent rows.
            peer = next(other for other in contexts if other.database != context.database)
            with original_database(peer, write=True) as db:
                baseline = state._source_baseline(None, db, context=peer)
                reference = evidence._canonical_plain(baseline['reference'])
                metadata = state._metadata(db, reference['name'])
                changed = dict(metadata, status='expired')
                db.execute('update evidence_metadata set status=?,data=? where name=?',
                    ('expired', evidence._raw(changed).decode(), reference['name']))
            damaged.append((peer, reference, metadata))
        class Host:
            def acquire_d4_bookkeeping(self, facts, issue):
                grant = issue(facts); grants.append(grant); return grant
        with changes._bootstrap_d4_host(Host(), issuer=changes._D4_HOST_BOOTSTRAP_ISSUER) as host:
            with patch.object(evidence, '_context_database', side_effect=database), patch.object(evidence, '_register_recovery_source', side_effect=register):
                failed = changes._run_scoped(fixture.directory, request, 'apply', host=host)
            self.assertNotEqual(failed['exit_code'], 0, failed)
            self.assertEqual(len(calls), 1)
            first, first_reference = calls[0]
            with original_database(first) as db:
                first_age = state._metadata(db, first_reference['name'])['created_at']
                baseline = state._source_baseline(None, db, context=first)
                self.assertEqual(evidence._canonical_plain(baseline['dependencies'][0]['reference']['artifact']), first_reference)
            markers = changes._authority_locations(c.directory for c in contexts)
            root = Path(request['manifest']['enrollment']['record']['project_root'])
            canonical = changes.LOCK_ROOT / ('canonical-' + hashlib.sha256(('destination:' + str(root / PROJECT_FILE)).encode()).hexdigest() + '.lock')
            self.assertTrue(all(changes._authority_owner(location) is not None for location in [canonical, *markers]))
            for (root, path), fingerprint in before.items(): self.assertEqual(changes._fingerprint(Path(root), path), fingerprint)
            peer, reference, metadata = damaged[0]
            with original_database(peer, write=True) as db:
                db.execute('update evidence_metadata set status=?,data=? where name=?',
                    (metadata['status'], evidence._raw(metadata).decode(), reference['name']))
            resumed = changes._run_scoped(fixture.directory, request, 'resume', host=host)
            self.assertEqual(resumed['exit_code'], 0, resumed)
            self.assertGreaterEqual(len(grants), 3)
            self.assertIsNot(grants[0].acquisition, grants[1].acquisition)
            final = []
            for context in contexts:
                with original_database(context) as db:
                    baseline = state._source_baseline(None, db, context=context)
                    ref = evidence._canonical_plain(baseline['dependencies'][0]['reference']['artifact'])
                    self.assertEqual(state._metadata(db, ref['name'])['created_at'], first_age)
                    final.append(ref)
            replay = changes._run_scoped(fixture.directory, request, 'resume', host=host)
            self.assertEqual(replay['exit_code'], 0, replay)
            for context, reference in zip(contexts, final):
                with original_database(context) as db:
                    baseline = state._source_baseline(None, db, context=context)
                    self.assertEqual(evidence._canonical_plain(baseline['dependencies'][0]['reference']['artifact']), reference)
            self.assertTrue(all(changes._authority_owner(location) is None for location in [canonical, *markers]))

    def test_original_grant_chain_comparisons_cannot_be_replaced(self):
        fixture = self.fixture
        request, _ = fixture.d4_bookkeeping_request(umbrella=True)
        original = evidence._register_recovery_source
        def replace(scope, db, source, *, context=None):
            lifetime = changes._authority_context.publication
            self.assertTrue(lifetime['local_chain_inputs'])
            lifetime['local_chain_inputs'] = {}
            return original(scope, db, source, context=context)
        with patch.object(evidence, '_register_recovery_source', side_effect=replace):
            result = fixture.run_with_d4_host(request, 'apply')
        self.assertNotEqual(result['exit_code'], 0, result)
        self.assertIn('actual approved acquisition', str(result))

    def test_mutable_overlay_comparison_cannot_authorize_dropping_its_real_link(self):
        fixture = self.fixture
        request, _ = fixture.d4_bookkeeping_request(umbrella=True)
        original = evidence._register_recovery_source
        mutations = []
        def drop(scope, db, source, *, context=None):
            reference = original(scope, db, source, context=context)
            if not mutations:
                lifetime = changes._authority_context.publication
                registration = lifetime['registrations'][str(context.database)]
                baseline = state._source_baseline(None, db, context=context)
                metadata = state._metadata(db, baseline['reference']['name'])
                metadata['dependencies'] = []
                db.execute('update evidence_metadata set data=? where name=?',
                    (evidence._raw(metadata).decode(), baseline['reference']['name']))
                registration['expected']['dependencies'] = []
                mutations.append(reference)
            return reference
        with patch.object(evidence, '_register_recovery_source', side_effect=drop):
            result = fixture.run_with_d4_host(request, 'apply')
        self.assertEqual(len(mutations), 1)
        self.assertNotEqual(result['exit_code'], 0, result)
        self.assertIn('owned overlay', str(result))

    def test_genuine_v2_release_keeps_rollback_on_original_validation_path(self):
        fixture = self.fixture
        request, contexts = fixture.d4_bookkeeping_request(umbrella=True)
        self.assertEqual(fixture.run_with_d4_host(request, 'apply')['exit_code'], 0)
        _, sources = changes._recovery_sources(contexts[0])
        identity = sources[0][1]['identity']
        authorities = [evidence._canonical_plain(context.authority_set[0]) for context in contexts]
        released = changes._register_recovery_release(changes._observe_recovery_release(authorities, identity))
        self.assertTrue(released['complete'], released)
        original = changes._check_d4_publication
        observed = []
        def check(source, context, db):
            lifetime = changes._authority_context.publication
            observed.append((source.content['version'], changes._taskless_publication(source, lifetime)))
            return original(source, context, db)
        with patch.object(changes, '_check_d4_publication', side_effect=check):
            rolled = fixture.run_with_d4_host(request, 'rollback')
        self.assertEqual(rolled['exit_code'], 0, rolled)
        self.assertTrue(observed)
        self.assertTrue(all(version == 2 and not local for version, local in observed))

    def final_batch_file_change(self, kind):
        fixture = self.fixture
        request, contexts = fixture.d4_bookkeeping_request(umbrella=True)
        original_database = evidence._context_database
        original_register = evidence._register_recovery_source
        writes = []; mutation = []; grants = []; durable = []
        def register(scope, db, source, *, context=None):
            result = original_register(scope, db, source, context=context)
            if source.content['journal']['state'] == 'applied': writes.append((context, result))
            return result
        @contextmanager
        def database(context, **kwargs):
            lifetime = getattr(changes._authority_context, 'publication', None)
            if kwargs.get('durable') and lifetime['journal']['state'] == 'applied': durable.append(context)
            with original_database(context, **kwargs) as db: yield db
            lifetime = getattr(changes._authority_context, 'publication', None)
            if not kwargs.get('durable') or mutation or lifetime['journal']['state'] != 'applied': return
            journal = lifetime['journal']
            action = next(action for action in journal['manifest']['actions']
                if action['effects'] and journal['receipts'][action['id']]['files'][0]['backup'])
            receipt = journal['receipts'][action['id']]['files'][0]
            target = (Path(action['owner']['root']) / action['effects'][0]['path'] if kind == 'effect'
                else fixture.directory / receipt['backup'])
            raw = target.read_bytes(); mode = target.stat().st_mode & 0o777
            journal_raw = (fixture.directory / 'transaction.json').read_bytes()
            project_file = Path(request['manifest']['enrollment']['record']['project_root']) / PROJECT_FILE
            project_raw = project_file.read_bytes()
            with original_database(context) as db:
                baseline = state._source_baseline(None, db, context=context)
            target.chmod(0o600); target.write_bytes(b'late external file change'); target.chmod(mode)
            self.assertEqual((fixture.directory / 'transaction.json').read_bytes(), journal_raw)
            self.assertEqual(project_file.read_bytes(), project_raw)
            with original_database(context) as db:
                self.assertEqual(state._source_baseline(None, db, context=context), baseline)
            mutation.append((target, raw, mode, journal_raw, project_file))
        class Host:
            def acquire_d4_bookkeeping(self, facts, issue):
                grant = issue(facts); grants.append(grant); return grant
        with changes._bootstrap_d4_host(Host(), issuer=changes._D4_HOST_BOOTSTRAP_ISSUER) as host:
            with patch.object(evidence, '_context_database', side_effect=database), patch.object(evidence, '_register_recovery_source', side_effect=register):
                failed = changes._run_scoped(fixture.directory, request, 'apply', host=host)
            self.assertNotEqual(failed['exit_code'], 0, failed)
            self.assertEqual(len(writes), 1)
            self.assertEqual(len(durable), 1)
            self.assertEqual(len(mutation), 1)
            self.assertIn('effect bytes or physical ownership changed' if kind == 'effect' else 'backup integrity failed', str(failed))
            first, reference = writes[0]
            with original_database(first) as db:
                metadata = state._metadata(db, reference['name'])
                self.assertIsNotNone(metadata)
                first_age = metadata['created_at']
                baseline = state._source_baseline(None, db, context=first)
                self.assertEqual(evidence._canonical_plain(baseline['dependencies'][0]['reference']['artifact']), reference)
            markers = changes._authority_locations(c.directory for c in contexts)
            root = Path(request['manifest']['enrollment']['record']['project_root'])
            canonical = changes.LOCK_ROOT / ('canonical-' + hashlib.sha256(('destination:' + str(root / PROJECT_FILE)).encode()).hexdigest() + '.lock')
            self.assertTrue(all(changes._authority_owner(location) is not None for location in [canonical, *markers]))
            target, raw, mode, journal_raw, project_file = mutation[0]
            self.assertEqual(target.read_bytes(), b'late external file change')
            self.assertEqual(json.loads(journal_raw)['state'], 'applied')
            self.assertEqual(failed['state'], 'blocked')
            self.assertEqual(project_file.read_text(), json.dumps(request['manifest']['enrollment']['record'], sort_keys=True) + '\n')
            target.chmod(0o600); target.write_bytes(raw); target.chmod(mode)
            resumed = changes._run_scoped(fixture.directory, request, 'resume', host=host)
            self.assertEqual(resumed['exit_code'], 0, resumed)
            self.assertGreaterEqual(len(grants), 3)
            self.assertIsNot(grants[-1].acquisition, grants[-2].acquisition)
            for context in contexts:
                with original_database(context) as db:
                    baseline = state._source_baseline(None, db, context=context)
                    current = baseline['dependencies'][0]['reference']['artifact']
                    self.assertEqual(state._metadata(db, current['name'])['created_at'], first_age)
            self.assertTrue(all(changes._authority_owner(location) is None for location in [canonical, *markers]))

    def test_final_batch_effect_change_after_first_commit_blocks_settlement(self):
        self.final_batch_file_change('effect')

    def test_final_batch_backup_change_after_first_commit_blocks_settlement(self):
        self.final_batch_file_change('backup')

    def test_file_checkpoint_accepts_durable_forward_and_restore_phases(self):
        fixture = self.fixture
        request, _ = fixture.d4_bookkeeping_request(umbrella=True)
        original_replace = changes._scoped_replace
        original_check = changes._check_operation_files
        phases = set(); restored = []; checked = []
        def check(path, journal):
            original_check(path, journal)
            phases.update(receipt['status'] for receipt in journal['receipts'].values())
            checked.append(not journal['receipts'])
            for receipt in journal['receipts'].values():
                for file in receipt['files']:
                    restore = file.get('restore')
                    if restore and restore['result_binding'] and restore['result_binding'] != file['before_binding']:
                        restored.append(restore['result_binding'])
        def replace(path, root, relative, raw, before, after, receipt, journal):
            check(path, journal)
            original_replace(path, root, relative, raw, before, after, receipt, journal)
            check(path, journal)
        def checkpoint(stage):
            if stage in ('prepared', 'scoped_temp_recorded', 'outcome'):
                check(fixture.directory, changes._load_journal(fixture.directory))
        with patch.object(changes, '_scoped_replace', side_effect=replace), patch.object(changes, '_checkpoint', side_effect=checkpoint), patch.object(changes, '_check_operation_files', side_effect=check):
            applied = fixture.run_with_d4_host(request, 'apply')
            self.assertEqual(applied['exit_code'], 0, applied)
            journal = changes._load_journal(fixture.directory)
            action = next(action for action in journal['manifest']['actions'] if action['effects'][0]['before'])
            target = Path(action['owner']['root']) / action['effects'][0]['path']
            held = target.with_name(target.name + '.checkpoint-original')
            raw = target.read_bytes(); mode = target.stat().st_mode & 0o777
            target.rename(held)
            try:
                target.write_bytes(raw); target.chmod(mode)
                with self.assertRaisesRegex(StartupError, 'physical ownership changed'):
                    original_check(fixture.directory, journal)
            finally:
                target.unlink(); held.rename(target)
            rolled = fixture.run_with_d4_host(request, 'rollback')
            self.assertEqual(rolled['exit_code'], 0, rolled)
        self.assertIn(True, checked)
        self.assertEqual(phases, {'prepared', 'completed', 'rolled_back'})
        self.assertTrue(restored)

    def test_explicit_canonical_action_uses_enrollment_receipts_and_recovery(self):
        fixture = self.fixture
        request, contexts = fixture.d4_bookkeeping_request(umbrella=True)
        record = deepcopy(request['manifest']['enrollment']['record'])
        proposal = fixture.scoped_proposal()
        assessment = proposal['assessments']['project']
        original = assessment['actions'][0]
        text = json.dumps(record, indent=2)
        canonical = dict(original, id='enroll-project', target=str(PROJECT_FILE), section=None,
            dependencies=[fixtures.onboarding._qualified(assessment['owner'], original['id'])],
            before='absent', text=text, after=hashlib.sha256(text.encode()).hexdigest())
        assessment['actions'].append(canonical)
        fixtures.onboarding.record_plan(fixture.directory, proposal)
        request = fixture.scoped_request(umbrella=True, prepared=True)
        request['manifest']['enrollment']['record'] = record
        request['approval']['manifest_digest'] = fixtures.onboarding._digest(request['manifest'])
        action_id = fixtures.onboarding._qualified(assessment['owner'], canonical['id'])
        self.assertIn(action_id, request['manifest']['approved_scope'])
        applied = fixture.run_with_d4_host(request, 'apply')
        self.assertEqual(applied['exit_code'], 0, applied)
        journal = changes._load_journal(fixture.directory)
        self.assertNotIn(action_id, journal['receipts'])
        self.assertEqual(journal['enrollment']['postimages'][-1]['phase'], 'final')
        target = Path(record['project_root']) / PROJECT_FILE
        self.assertEqual(json.loads(target.read_bytes()), record)
        self.assertNotEqual(target.read_text(), text)
        held = target.with_name(target.name + '.approved-original')
        raw = target.read_bytes(); mode = target.stat().st_mode & 0o777
        target.rename(held)
        try:
            target.write_bytes(raw); target.chmod(mode)
            tampered_inode = target.stat().st_ino
            denied = fixture.run_with_d4_host(request, 'resume')
            self.assertNotEqual(denied['exit_code'], 0, denied)
            self.assertIn('Project authority changed outside its owned transition', str(denied))
            self.assertEqual(target.stat().st_ino, tampered_inode)
        finally:
            target.unlink(); held.rename(target)
        resumed = fixture.run_with_d4_host(request, 'resume')
        self.assertEqual(resumed['exit_code'], 0, resumed)
        rolled = fixture.run_with_d4_host(request, 'rollback')
        self.assertEqual(rolled['exit_code'], 0, rolled)
        self.assertFalse(target.exists())
        for context in contexts:
            self.assertIsNone(changes._authority_owner(changes._authority_locations([context.directory])[0]))
