"""Uniform task states preserve evidence and edit boundaries."""
import unittest
from contextlib import closing
from tests import test_state


class CanonicalTaskStatusTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_state.StateTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_new_task_triage_then_ready_then_working(self):
        self.assertEqual(self.fixture.start()['task']['state'],'TRIAGE')
        for status in ('READY','WORKING','REVIEW','WORKING'):
            self.assertEqual(self.fixture.update(state=status)['task']['state'],status)

    def test_done_cannot_be_declared_by_task_update(self):
        self.fixture.start()
        with self.assertRaises(ValueError):self.fixture.update(state='DONE')

    def test_waiting_blocked_and_paused_require_explicit_resolution(self):
        self.fixture.start()
        for status in ('WAITING','BLOCKED','PAUSED'):
            self.fixture.update(state=status)
            with self.assertRaises(ValueError): self.fixture.update(state='WORKING')
            self.assertEqual(self.fixture.update(state='WORKING',resolution_ref='user:resume')['task']['state'],'WORKING')

    def test_cancelled_is_terminal(self):
        self.fixture.start()
        self.fixture.update(state='CANCELLED')
        with self.assertRaises(ValueError): self.fixture.update(state='WORKING',resolution_ref='user:resume')

    def test_milestones_are_validated_and_update_with_task_revision(self):
        initial=self.fixture.start()['task']
        values=[dict(id='design',weight=2,accepted=True,reference='user:design-approved'),
                dict(id='delivery',weight=3,accepted=False,reference='plan:delivery')]
        result=self.fixture.update(milestones=values)['task']
        self.assertEqual(result['milestones'],values)
        self.assertEqual(result['revision'],initial['revision']+1)
        for invalid in ([values[0],values[0]], [values[0]|dict(weight=0)],
                        [values[0]|dict(weight=True)], [values[0]|dict(accepted='yes')],
                        [values[0]|dict(reference='')], [values[0]|dict(id='bad\n')],
                        [values[0]|dict(weight=1000001)], [values[0]|dict(extra='unsupported')],
                        [values[0]|dict(id=str(i)) for i in range(65)]):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                self.fixture.update(milestones=invalid)
        self.assertEqual(self.fixture.status()['task']['milestones'],values)

    def test_legacy_task_remains_unchanged_and_requires_explicit_migration(self):
        import json
        import sqlite3
        self.fixture.start()
        path=self.fixture.scope.runtime.state_dir/'runtime.sqlite3'
        with closing(sqlite3.connect(path)) as db, db:
            raw=db.execute('SELECT data FROM tasks').fetchone()[0]
            old=json.loads(raw)
            old['state']='ready'
            legacy=json.dumps(old)
            db.execute('UPDATE tasks SET data=?',(legacy,))
        with self.assertRaisesRegex(ValueError,'migration'):
            self.fixture.status()
        with self.assertRaisesRegex(ValueError,'migration'):
            self.fixture.start(session_id='other-session',task_id='other-task')
        with closing(sqlite3.connect(path)) as db, db:
            self.assertEqual(db.execute('SELECT data FROM tasks').fetchone()[0],legacy)

    def test_version_specific_historical_reader_does_not_authorize_relabel_or_repin(self):
        import json
        import sqlite3
        api=self.fixture.api()
        self.fixture.start()
        path=self.fixture.scope.runtime.state_dir/'runtime.sqlite3'
        with closing(sqlite3.connect(path)) as db, db:
            old=json.loads(db.execute('SELECT data FROM tasks').fetchone()[0])
            old.update(state='cancelled')
            old['pins']['runtime_digest']='f'*64
            raw=json.dumps(old)
            db.execute('UPDATE tasks SET data=?',(raw,))
        with api._database(self.fixture.scope,write=True) as db:
            task=api._task(db,api._scope_id(self.fixture.scope),'codex','session',historical=True)
            self.assertEqual(task['state'],'cancelled')
            with self.assertRaisesRegex(ValueError,'migration'):
                api._compatible(self.fixture.scope,task)
            with self.assertRaises(ValueError):api._save(db,api._scope_id(self.fixture.scope),task)
            relabeled=task|dict(state='CANCELLED',pins=api._pins(self.fixture.scope))
            with self.assertRaises(ValueError):api._save(db,api._scope_id(self.fixture.scope),relabeled)
        with closing(sqlite3.connect(path)) as db, db:
            self.assertEqual(db.execute('SELECT data FROM tasks').fetchone()[0],raw)

    def test_missing_or_null_state_prevents_new_session_in_corrupt_authority(self):
        import json
        import sqlite3
        self.fixture.start()
        path = self.fixture.scope.runtime.state_dir / 'runtime.sqlite3'
        with closing(sqlite3.connect(path)) as db, db:
            original = json.loads(db.execute('SELECT data FROM tasks').fetchone()[0])
        for value in ('missing', None):
            corrupt = dict(original)
            if value == 'missing':
                del corrupt['state']
            else:
                corrupt['state'] = None
            raw = json.dumps(corrupt)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('UPDATE tasks SET data=?', (raw,))
            with self.assertRaises(ValueError):
                self.fixture.start(session_id='other-session', task_id='other-task')
            with closing(sqlite3.connect(path)) as db, db:
                self.assertEqual(db.execute('SELECT data FROM tasks').fetchall(), [(raw,)])

    def test_retained_incompatible_pins_prevent_cross_session_admission(self):
        import json
        import sqlite3
        self.fixture.start()
        path = self.fixture.scope.runtime.state_dir / 'runtime.sqlite3'
        with closing(sqlite3.connect(path)) as db:
            original = json.loads(db.execute('SELECT data FROM tasks').fetchone()[0])
        for pins in (original['pins'] | dict(runtime_digest='f'*64), original['pins'] | dict(schema_version=1),
                     original['pins'] | dict(policy_digest='older-policy')):
            old = original | dict(pins=pins)
            raw = json.dumps(old)
            with closing(sqlite3.connect(path)) as db, db:db.execute('UPDATE tasks SET data=?', (raw,))
            with self.assertRaisesRegex(ValueError, 'migration'):
                self.fixture.start(session_id='other-session', task_id='other-task')
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT data FROM tasks').fetchall(), [(raw,)])

    def test_wait_states_block_verification_and_model_free_dispatch_without_side_effects(self):
        from tests.test_evidence import EvidenceTests
        from runtime import state, delegation
        fixture = EvidenceTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.plan()
        for status in ('WAITING', 'BLOCKED', 'PAUSED'):
            state.update_task(fixture.scope, fixture.request(state=status, reason='Waiting for resolution', reference='user:hold'))
            files = {str(p):p.read_bytes() for p in fixture.scope.runtime.state_dir.rglob('*') if p.is_file()}
            with self.assertRaisesRegex(ValueError, 'Resolve the task status'):
                fixture.api.verify_completion(fixture.scope, fixture.request(purpose='completion'))
            operation = fixture.request(dispatch_id='blocked-dispatch', claims=[dict(kind='path',key=str(fixture.repo),mode='read')],
                operation=dict(id='blocked-dispatch',kind='coordinator-work'),reason='Observe only',
                ownership_ref='user:scope',stop_conditions=['Return after observation'])
            with self.assertRaisesRegex(ValueError, 'Task cannot reserve'):
                delegation._reserve_operation(fixture.scope, operation, role='coordinator')
            self.assertEqual({str(p):p.read_bytes() for p in fixture.scope.runtime.state_dir.rglob('*') if p.is_file()}, files)
            state.update_task(fixture.scope, fixture.request(state='WORKING',reason='Resume accepted task',
                reference='user:resume',resolution_ref='user:resolved'))

    def test_schema_two_d4_reads_original_cancelled_stop_without_changing_authority(self):
        import hashlib
        import json
        import sqlite3
        from unittest.mock import patch
        from runtime import changes
        api = self.fixture.api()
        with patch.object(api, 'runtime_fingerprint', return_value='f'*64):
            task = self.fixture.start()['task']
            identity = {key:task[key] for key in ('client','session_id','task_id','scope_ref')}
            proof = dict(version=1,kind='stopped-writer-reconciliation',identity=identity,
                expected_revision=task['revision'],expected_pins=task['pins'],observed_turn_id=task['turn_id'],
                stopped=True,descendants_stopped=True,attempt_ids=[],observation_ref='fixture:stopped',coordinator_ref='fixture:checked')
            raw = json.dumps(proof).encode();path = self.fixture.base/'historical-stop.json'
            path.write_bytes(raw);path.chmod(0o400)
            retired = api.retire_task(self.fixture.scope,identity|dict(expected_revision=task['revision'],expected_pins=task['pins'],
                reason='Original owner stopped',reference='fixture:owner',stop_proof=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest())))['task']
        database = self.fixture.scope.runtime.state_dir/'runtime.sqlite3'
        retired['state'] = 'cancelled'
        with closing(sqlite3.connect(database)) as db,db:db.execute('UPDATE tasks SET data=?',(json.dumps(retired),))
        before = {str(p):p.read_bytes() for p in database.parent.rglob('*') if p.is_file()}
        changes._writers({}, {}, dict(task_reconciliation=True), scope=self.fixture.scope)
        self.assertEqual({str(p):p.read_bytes() for p in database.parent.rglob('*') if p.is_file()}, before)

    def test_historical_cancelled_flag_does_not_clear_unresolved_check_claims(self):
        import json
        import sqlite3
        from unittest.mock import patch
        from tests.test_evidence import EvidenceTests
        from runtime import changes,state,evidence
        with patch.object(state,'runtime_fingerprint',return_value='f'*64):
            fixture = EvidenceTests('runTest');fixture.setUp()
            self.addCleanup(fixture.doCleanups)
            fixture.plan()
            evidence._reserve_check(fixture.scope,evidence._check_request(fixture.request(check_id='unit')))
            state.update_task(fixture.scope,fixture.request(state='CANCELLED',reason='Cancelled while held',reference='fixture:cancel'))
        database = fixture.scope.runtime.state_dir/'runtime.sqlite3'
        with closing(sqlite3.connect(database)) as db,db:
            old = json.loads(db.execute('SELECT data FROM tasks').fetchone()[0]);old['state'] = 'cancelled'
            db.execute('UPDATE tasks SET data=?',(json.dumps(old),))
        before = {str(p):p.read_bytes() for p in database.parent.rglob('*') if p.is_file()}
        with self.assertRaises(changes.Pending):changes._writers({}, {},dict(task_reconciliation=True),scope=fixture.scope)
        self.assertEqual({str(p):p.read_bytes() for p in database.parent.rglob('*') if p.is_file()}, before)
