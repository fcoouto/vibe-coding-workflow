"""Saved consent is local, checkout-bound and separate from connection health."""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from runtime import changes, startup, state
from tests.openrouter_fixtures import PACKAGE, enroll


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((PACKAGE / 'runtime/openrouter_settings.py').exists(), 'saved OpenRouter controls must exist')
        self.settings = importlib.import_module('runtime.openrouter_settings')
        self.tmp = tempfile.TemporaryDirectory(prefix='openrouter management ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / 'repo'
        self.scope = enroll(self.repo, self.root / 'state')
        self.locks = self.root / 'locks'
        guard = patch.object(changes, 'LOCK_ROOT', self.locks)
        guard.start()
        self.addCleanup(guard.stop)
        self.exe = self.root / 'opencode'
        self.exe.write_text('#!/bin/sh\nexit 0\n')
        self.exe.chmod(0o700)
        self.auth = self.root / 'auth'
        self.auth.mkdir(mode=0o700)
        self.request = dict(expected_revision=0, routes=['proposals', 'workers'],
                            opencode=str(self.exe), auth_data=str(self.auth))
        self.path = self.scope.runtime.state_dir / 'openrouter' / (state._scope_id(self.scope) + '.json')

    def snapshot(self):
        return {str(path.relative_to(self.root)): (path.stat().st_mode,
            path.read_bytes() if path.is_file() else None) for path in self.root.rglob('*')}

    def configured(self):
        return self.settings.configure(self.repo, self.request)

    def enabled(self):
        result = self.configured()
        return self.settings.enable(self.repo, dict(expected_revision=result['revision'], consent_version=2))

    def legacy_worker_consent(self):
        self.configured()
        record = json.loads(self.path.read_text())
        record.update(version=1, revision=2, enabled=True)
        self.path.write_text(json.dumps(record))

    def test_legacy_worker_consent_is_readable_but_cannot_admit(self):
        self.legacy_worker_consent()
        before = self.snapshot()
        with self.assertRaises(self.settings.SettingsError):
            with self.settings.admission(self.repo, 'workers'): self.fail('legacy consent admitted')
        report = self.settings.status(self.repo)
        self.assertTrue(report['enabled'])
        self.assertTrue(report.get('enablement_renewal_required'))
        self.assertEqual(report.get('worker_capability'), 'renewal_required')
        self.assertEqual(report['execution_qualification'], 'not_checked')
        with self.settings.admission(self.repo, 'proposals'):
            pass
        self.assertEqual(self.snapshot(), before)

    def test_enable_requires_explicit_worker_consent(self):
        report = self.configured()
        before = self.path.read_bytes()
        with self.assertRaises(self.settings.SettingsError):
            self.settings.enable(self.repo, {'expected_revision': report['revision']})
        self.assertEqual(self.path.read_bytes(), before)

    def test_enable_explicitly_renews_legacy_consent_once(self):
        self.legacy_worker_consent()
        sentinel = Path(self.settings.status(self.repo)['proposal_store'])
        sentinel.write_text('existing task history')
        try:
            report = self.settings.enable(self.repo, dict(expected_revision=2, consent_version=2))
        except self.settings.SettingsError as error:
            self.fail(f'Explicit renewal must be accepted: {error}')
        self.assertEqual(report['revision'], 3)
        self.assertEqual(report.get('consent_version'), 2)
        self.assertEqual(report.get('worker_capability'), 'worktree_edit_and_test')
        self.assertFalse(report.get('enablement_renewal_required'))
        self.assertEqual(sentinel.read_text(), 'existing task history')
        self.assertEqual(report['opencode'], str(self.exe))
        self.assertEqual(report['auth_data'], str(self.auth))
        self.assertEqual(self.settings.enable(self.repo, dict(expected_revision=3, consent_version=2)), report)
        with self.assertRaises(self.settings.SettingsError):
            with self.settings.admission(self.repo, 'workers', revision=2): self.fail('stale preparation admitted')
        with self.settings.admission(self.repo, 'workers', revision=3) as admitted:
            self.assertEqual(admitted['consent_version'], 2)
        self.assertFalse(self.settings.disable(self.repo, dict(expected_revision=3))['enabled'])

    def test_worker_consent_version_rejects_wrong_types_without_mutation(self):
        self.legacy_worker_consent()
        before = self.path.read_bytes()
        for value in (True, '2', 2.0, 1, None):
            with self.subTest(value=value), self.assertRaises(self.settings.SettingsError):
                self.settings.enable(self.repo, dict(expected_revision=2, consent_version=value))
            self.assertEqual(self.path.read_bytes(), before)

    def test_legacy_proposal_only_enable_remains_independent(self):
        self.settings.configure(self.repo, dict(expected_revision=0, routes=['proposals'], opencode=None, auth_data=None))
        record = json.loads(self.path.read_text())
        record['version'] = 1
        self.path.write_text(json.dumps(record))
        report = self.settings.enable(self.repo, dict(expected_revision=1))
        self.assertTrue(report['enabled'])
        with self.settings.admission(self.repo, 'proposals'):
            pass
        self.assertFalse(report.get('enablement_renewal_required'))

    def test_unknown_control_cannot_disable_saved_consent(self):
        self.legacy_worker_consent()
        before = self.path.read_bytes()
        with self.assertRaises(self.settings.SettingsError):
            self.settings.operate(self.repo, 'unknown', dict(expected_revision=2))
        self.assertEqual(self.path.read_bytes(), before)

    def test_default_status_is_off_without_writes_or_client_execution(self):
        before = self.snapshot()
        report = self.settings.status(self.repo)
        self.assertFalse(report['configured'])
        self.assertFalse(report['enabled'])
        self.assertEqual(report['revision'], 0)
        self.assertEqual(report['control_scope'], 'checkout')
        self.assertEqual(report['connection'], 'not_checked')
        self.assertFalse(self.locks.exists())
        self.assertEqual(self.snapshot(), before)

    def test_configure_is_private_off_and_does_not_mutate_native_state(self):
        database = self.scope.runtime.state_dir / 'runtime.sqlite3'
        before = database.read_bytes()
        report = self.configured()
        self.assertFalse(report['enabled'])
        self.assertEqual(report['revision'], 1)
        self.assertEqual(report['routes'], ['proposals', 'workers'])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(database.read_bytes(), before)

    def test_saved_enable_disable_and_stale_revisions(self):
        self.enabled()
        self.assertTrue(self.settings.status(self.repo)['enabled'])
        raw = self.path.read_bytes()
        for request in ({'expected_revision': 1}, {'expected_revision': True},
                        {'expected_revision': 2, 'api_key': 'SECRET'}):
            with self.subTest(request=request), self.assertRaises(self.settings.SettingsError):
                self.settings.disable(self.repo, request)
            self.assertEqual(self.path.read_bytes(), raw)
        off = self.settings.disable(self.repo, dict(expected_revision=2))
        self.assertFalse(off['enabled'])
        self.assertEqual(off['revision'], 3)
        self.assertEqual(self.settings.disable(self.repo, dict(expected_revision=3)), off)
        self.assertTrue(self.settings.enable(self.repo, dict(expected_revision=3))['enabled'])

    def test_status_does_not_read_credentials_or_invoke_the_configured_runtime(self):
        self.enabled()
        secret = self.auth / 'credential-sentinel'
        secret.write_text('SECRET_MUST_NOT_BE_READ')
        before = self.snapshot()
        original = os.open
        def opened(path, *args, **kwargs):
            if str(path) == str(secret): raise AssertionError('credential read')
            return original(path, *args, **kwargs)
        launch = subprocess.Popen
        def spawned(command, *args, **kwargs):
            self.assertEqual(Path(command[0]).name, 'git', 'status may only resolve local Git scope')
            return launch(command, *args, **kwargs)
        with patch('os.open', side_effect=opened), patch('subprocess.Popen', side_effect=spawned):
            report = self.settings.status(self.repo)
        self.assertTrue(report['enabled'])
        self.assertEqual(report['connection'], 'not_checked')
        self.assertNotIn('SECRET', json.dumps(report))
        self.assertEqual(self.snapshot(), before)

    def test_missing_or_replaced_authority_cannot_bootstrap_or_repin(self):
        self.enabled()
        old = self.path.read_bytes()
        database = self.scope.runtime.state_dir / 'runtime.sqlite3'
        saved = database.with_suffix('.saved')
        database.rename(saved)
        with self.assertRaises(self.settings.SettingsError): self.settings.status(self.repo)
        self.assertFalse(database.exists())
        database.write_bytes(saved.read_bytes())
        database.chmod(0o600)
        with self.assertRaises(self.settings.SettingsError): self.settings.status(self.repo)
        self.assertEqual(self.path.read_bytes(), old)

    def test_benign_enrollment_and_database_updates_preserve_consent(self):
        self.enabled()
        enrollment = self.repo / startup.PROJECT_FILE
        record = json.loads(enrollment.read_text())
        record['source_revision'] = 'benign-update'
        enrollment.write_text(json.dumps(record))
        state.start_task(self.scope, dict(client='codex', session_id='other-session', task_id='other-task',
            scope_ref='test:scope', mode='read-only', decision_ref='test:scope'))
        self.assertTrue(self.settings.status(self.repo)['enabled'])
        self.assertEqual(self.settings.status(self.repo)['revision'], 2)

    def test_copied_settings_do_not_enable_another_enrolled_checkout(self):
        self.enabled()
        other = self.root / 'other'
        other_scope = enroll(other, self.root / 'other-state')
        folder = other_scope.runtime.state_dir / 'openrouter'
        folder.mkdir(mode=0o700)
        copied = folder / (state._scope_id(other_scope) + '.json')
        copied.write_bytes(self.path.read_bytes())
        copied.chmod(0o600)
        with self.assertRaises(self.settings.SettingsError): self.settings.status(other)
        self.assertTrue(self.settings.status(self.repo)['enabled'])

    def test_symlink_and_hardlink_settings_are_rejected(self):
        self.configured()
        saved = self.path.with_suffix('.saved')
        self.path.rename(saved)
        self.path.symlink_to(saved)
        with self.assertRaises(self.settings.SettingsError): self.settings.status(self.repo)
        self.path.unlink()
        os.link(saved, self.path)
        with self.assertRaises(self.settings.SettingsError): self.settings.status(self.repo)

    def test_missing_private_work_directory_is_unavailable_and_blocks_admission(self):
        report = self.enabled()
        data = Path(report['proposal_store']).parent
        data.rmdir()
        report = self.settings.status(self.repo)
        self.assertTrue(report['enabled'])
        self.assertEqual(report['local_configuration'], 'unavailable')
        self.assertFalse(data.exists())
        with self.assertRaises(self.settings.SettingsError):
            with self.settings.admission(self.repo, 'proposals'): self.fail('must not admit')

    def test_replaced_namespace_and_unselected_route_are_rejected(self):
        self.settings.configure(self.repo, dict(expected_revision=0, routes=['proposals'], opencode=None, auth_data=None))
        self.settings.enable(self.repo, dict(expected_revision=1))
        with self.assertRaisesRegex(self.settings.SettingsError, 'openrouter_route_disabled'):
            with self.settings.admission(self.repo, 'workers'): self.fail('must not admit')
        original = self.path.parent
        retired = original.with_name('retired')
        original.rename(retired)
        original.mkdir(mode=0o700)
        copied = original / self.path.name
        copied.write_bytes((retired / self.path.name).read_bytes())
        copied.chmod(0o600)
        with self.assertRaises(self.settings.SettingsError): self.settings.status(self.repo)

    def test_reconfiguration_requires_disabled_and_explicit_valid_routes(self):
        self.enabled()
        with self.assertRaises(self.settings.SettingsError):
            self.settings.configure(self.repo, dict(self.request, expected_revision=2))
        self.settings.disable(self.repo, dict(expected_revision=2))
        for routes in ([], ['workers', 'workers'], ['native'], ['workers', 'write']):
            with self.subTest(routes=routes), self.assertRaises(self.settings.SettingsError):
                self.settings.configure(self.repo, dict(self.request, expected_revision=3, routes=routes))
        report = self.settings.configure(self.repo, dict(expected_revision=3, routes=['proposals'], opencode=None, auth_data=None))
        self.assertFalse(report['enabled'])
        self.assertEqual(report['routes'], ['proposals'])

    def test_isolated_cli_persists_controls_without_project_imports(self):
        script = PACKAGE / 'scripts/openrouter.py'
        self.assertTrue(script.exists(), 'management CLI must exist')
        configured = self.configured()
        result = subprocess.run([sys.executable, '-I', '-B', str(script), 'enable', '--cwd', str(self.repo)],
            input=json.dumps({'expected_revision': configured['revision'], 'consent_version': 2}), text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['enabled'])
        result = subprocess.run([sys.executable, '-I', '-B', str(script), 'status', '--cwd', str(self.repo)],
            input='', text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['enabled'])


if __name__ == '__main__': unittest.main()
