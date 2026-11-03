"""Ordinary edits need guidance, not optional managed task authority."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from runtime import startup, state
from runtime.engine import RuntimeEvent, evaluate
from tests import test_runtime as runtime_fixtures
from tests import test_file_configuration as file_fixtures


class MinimalDefaultTests(unittest.TestCase):
    def runtime_fixture(self):
        fixture = runtime_fixtures.RuntimeTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def test_ordinary_patch_has_no_task_prerequisite(self):
        fixture = self.runtime_fixture()
        event = RuntimeEvent('PreToolUse', 'codex', 'ordinary', fixture.repo,
                             turn_id='turn', tool_call_id='call', tool_name='apply_patch')
        result, _ = evaluate(event, dict(task=None, turn=None, receipt=None))
        self.assertEqual(result.action, 'pass')
        fixture.enroll(runtime=fixture.runtime(), policy_digest='stale')
        output = fixture.invoke()
        self.assertNotIn('permissionDecision', str(output))
        self.assertFalse((fixture.base / 'state').exists())

    def test_broken_git_outside_enrollment_does_not_veto_patch(self):
        fixture = self.runtime_fixture()
        import shutil
        shutil.rmtree(fixture.repo / '.git')
        (fixture.repo / '.git').write_text('gitdir: /missing-minimal-default\n')
        self.assertNotIn('permissionDecision', str(fixture.invoke()))

    def test_file_configuration_supplies_guidance_without_managed_authority(self):
        owner = file_fixtures.FileConfigurationTests('runTest')
        self.addCleanup(owner.doCleanups)
        fixture, request = owner.configuration()
        self.assertEqual(owner.operate(fixture, request, 'apply')['exit_code'], 0)
        event = SimpleNamespace(client='codex', cwd=fixture.repo, session_id='ordinary')
        qualifier = lambda *_: (_ for _ in ()).throw(AssertionError('Optional qualification was read'))
        with patch('runtime.state.runtime_fingerprint', side_effect=AssertionError('Optional runtime was read')):
            acquired = startup.acquire_project_entry(event, state.PACKAGE, managed=False, qualifier=qualifier)
        scope = startup._entry_scope(acquired, managed=False)
        self.assertIsInstance(scope, startup.ProjectScope)
        self.assertIsNone(scope.runtime)
        context = startup.orient(event, state.PACKAGE, acquisition=acquired)
        for path in (state.PACKAGE / 'clients/codex.md', state.PACKAGE / 'policies/00-index.md',
                     fixture.repo / startup.PROJECT_FILE):
            self.assertIn(json.dumps(str(path)), context)
        self.assertLessEqual(len(context.split()), 150)
        self.assertNotIn('runtime.sqlite3', context)
        with self.assertRaises(startup.RuntimeScopeError):
            startup._entry_scope(acquired)
        self.assertFalse(any(fixture.base.rglob('runtime.sqlite3')))

    def test_unbound_runtime_patch_passes_but_selected_managed_task_still_guards(self):
        fixture = self.runtime_fixture()
        fixture.canonical()
        event = RuntimeEvent('PreToolUse', 'codex', 'session-1', fixture.repo,
                             turn_id='turn', tool_call_id='call', tool_name='apply_patch')
        self.assertEqual(state.process_event(fixture.scope, event).action, 'pass')
        state.start_task(fixture.scope, dict(client='codex', session_id='session-1', task_id='selected',
            scope_ref='user:selected', mode='editable', decision_ref='user:approved'))
        self.assertEqual(state.process_event(fixture.scope, event).action, 'deny')

    def test_broken_qualification_preserves_startup_guidance_and_managed_control_rejection(self):
        fixture = self.runtime_fixture()
        fixture.canonical()
        fixture.test_acquisition.write_text(json.dumps(dict(observation={})))
        output = fixture.invoke('SessionStart', dict(hook_event_name='SessionStart',
            session_id='session-1', source='startup', cwd=str(fixture.repo)))
        self.assertIn('Load only triggered policies', str(output))
        self.assertNotIn('runtime.sqlite3', str(output))
        self.assertNotIn('permissionDecision', str(fixture.invoke()))
        code, report = fixture.task_cli('start', dict(client='codex', session_id='session-1',
            task_id='unqualified', scope_ref='user:task', mode='editable', decision_ref='user:approved'))
        self.assertEqual(code, 1, report)
        self.assertFalse(report['ok'])

    def test_stale_qualification_preserves_selected_managed_patch_enforcement(self):
        fixture = self.runtime_fixture()
        fixture.canonical()
        state.start_task(fixture.scope, dict(client='codex', session_id='session-1', task_id='selected',
            scope_ref='user:selected', mode='editable', decision_ref='user:approved'))
        fixture.test_acquisition.write_text(json.dumps(dict(observation={})))
        output = fixture.invoke()
        self.assertEqual((output or {}).get('hookSpecificOutput', {}).get('permissionDecision'), 'deny')

    def test_foreign_known_writer_protects_ordinary_patch(self):
        fixture = self.runtime_fixture()
        fixture.canonical()
        state.start_task(fixture.scope, dict(client='codex', session_id='foreign', task_id='writer',
            scope_ref='user:writer', mode='editable', decision_ref='user:approved'))
        self.assertEqual((fixture.invoke() or {}).get('hookSpecificOutput', {}).get('permissionDecision'), 'deny')

    def test_unreadable_optional_state_does_not_establish_native_enforcement(self):
        fixture = self.runtime_fixture()
        fixture.canonical()
        database = fixture.scope.runtime.state_dir / 'runtime.sqlite3'
        database.chmod(0o644)
        self.assertNotIn('permissionDecision', str(fixture.invoke()))
        code, report = fixture.task_cli('status', None, '--client', 'codex', '--session', 'session-1')
        self.assertEqual(code, 1, report)
        self.assertFalse(report['ok'])

    def test_assignment_claims_block_only_actual_overlap(self):
        import sqlite3
        from contextlib import closing
        from runtime import delegation
        fixture = self.runtime_fixture()
        other = fixture.base / 'unrelated'
        other.mkdir()
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('create table tasks(scope_id,client,session_id,task_id,data)')
            db.execute('create table checkouts(scope_id,repository_root)')
            db.execute('create table assignments(id,data)')
            db.execute('insert into assignments values(?,?)', ('selected-assignment', '{"status":"prepared"}'))
            for path, blocked in ((other, False), (fixture.repo, True)):
                with self.subTest(path=path):
                    claim = delegation._claims([dict(kind='path', key=str(path), mode='write')])
                    with patch('runtime.delegation._ledger', return_value=[dict(data=dict(claims=claim))]):
                        reason = state._unbound_patch_conflict(db, fixture.repo, None)
                    self.assertEqual(reason is not None, blocked)

    def test_known_writer_survives_later_authority_observation_failure(self):
        from contextlib import contextmanager
        fixture = self.runtime_fixture()
        fixture.canonical()
        state.start_task(fixture.scope, dict(client='codex', session_id='foreign', task_id='writer',
            scope_ref='user:writer', mode='editable', decision_ref='user:approved'))
        original_database = state._database
        @contextmanager
        def changed_after_read(*args, **kwargs):
            with original_database(*args, **kwargs) as db:
                yield db
                raise state.StateError('Authority changed after the known writer was observed')
        event = RuntimeEvent('PreToolUse', 'codex', 'ordinary', fixture.repo, tool_name='apply_patch')
        with patch('runtime.state._database', changed_after_read), \
                patch('runtime.state.retained_patch_guard', return_value=None):
            self.assertEqual(state.process_event(fixture.scope, event).action, 'deny')

    def test_configured_activation_preserves_known_writer_and_file_only_patch_passes(self):
        fixture = self.runtime_fixture()
        fixture.canonical()
        state.start_task(fixture.scope, dict(client='codex', session_id='session-1', task_id='selected',
            scope_ref='user:selected', mode='editable', decision_ref='user:approved'))
        path = fixture.scope.authority_path
        record = json.loads(path.read_bytes())
        activation = record['repositories'][0]['checkouts'][0]['clients'][0]['activation']
        activation.update(status='configured', qualification='pending', qualification_binding=None,
                          accepted_scope_digest=None)
        path.write_text(json.dumps(record))
        fixture.test_acquisition.write_text(json.dumps(dict(observation=None)))
        for session in ('session-1', 'ordinary'):
            with self.subTest(session=session):
                output = fixture.invoke(payload=fixture.payload | dict(session_id=session))
                self.assertEqual((output or {}).get('hookSpecificOutput', {}).get('permissionDecision'), 'deny')
        ordinary = self.runtime_fixture()
        ordinary.canonical()
        path = ordinary.scope.authority_path
        record = json.loads(path.read_bytes())
        entry = record['repositories'][0]['checkouts'][0]['clients'][0]
        entry['configuration']['runtime'] = None
        entry['activation'].update(status='configured', qualification='pending', qualification_binding=None,
                                   accepted_scope_digest=None)
        path.write_text(json.dumps(record))
        self.assertNotIn('permissionDecision', str(ordinary.invoke()))

    def test_hook_database_respects_expired_and_remaining_deadline(self):
        import time
        import sqlite3
        fixture = self.runtime_fixture()
        fixture.canonical()
        event = RuntimeEvent('PreToolUse', 'codex', 'ordinary', fixture.repo, tool_name='Bash')
        with patch('runtime.state.sqlite3.connect', wraps=sqlite3.connect) as connect:
            state.process_event(fixture.scope, event, deadline=time.monotonic() - 1)
            self.assertEqual(connect.call_count, 0)
        original_schema = state._schema
        observed = []
        def inspect_remaining_timeout(db, *args, **kwargs):
            observed.append(db.execute('pragma busy_timeout').fetchone()[0])
            return original_schema(db, *args, **kwargs)
        with patch('runtime.state.time.monotonic', return_value=100), \
                patch('runtime.state.sqlite3.connect', wraps=sqlite3.connect) as connect, \
                patch('runtime.state._schema', inspect_remaining_timeout):
            state.process_event(fixture.scope, event, deadline=100.005)
            self.assertTrue(observed)
            self.assertLessEqual(max(observed), 5)
            self.assertLessEqual(connect.call_args.kwargs['timeout'], 0.0051)
