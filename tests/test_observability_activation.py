"""Activation controls use disposable scopes; no live accounts or native telemetry."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest

from runtime import startup, state
from tests import test_runtime
from tests.test_langfuse import protocol_server, PUBLIC_KEY, SECRET_KEY


PACKAGE = Path(__file__).resolve().parents[1]
SCRIPT = PACKAGE / 'scripts/observability.py'


class ObservabilityActivationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_runtime.RuntimeTests(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.enroll(runtime=self.fixture.runtime())
        self.scope = startup.resolve_project(
            SimpleNamespace(client='codex', cwd=self.fixture.repo), PACKAGE)
        state.start_task(self.scope, dict(client='codex', session_id='session-1',
            task_id='activation-fixture', scope_ref='user:fixture', mode='read-only',
            decision_ref='user:fixture'))

    def snapshot_state(self):
        directory = self.scope.runtime.state_dir
        return {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in directory.rglob('*') if path.is_file()}

    def invoke(self, action, request=None, environment=None, raw=None):
        overrides = environment or {}
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(('LANGFUSE_', 'GIT_'))}
        environment.update(overrides)
        return subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), action,
            '--cwd', str(self.fixture.repo)], input=raw if raw is not None else json.dumps(request or {}).encode(),
            capture_output=True, cwd=self.fixture.repo, env=environment, timeout=25)

    def successful(self, action, request=None, environment=None):
        result = self.invoke(action, request, environment)
        self.assertEqual(result.returncode, 0, result.stdout.decode())
        self.assertEqual(result.stderr, b'')
        return json.loads(result.stdout)

    def test_status_defaults_off_without_creating_configuration_or_changing_core_state(self):
        before = self.snapshot_state()
        result = self.invoke('status')
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        report = json.loads(result.stdout)
        self.assertFalse(report['configured'])
        self.assertIs(report['desired_opt_in'], False)
        self.assertEqual(self.snapshot_state(), before)
        self.assertFalse((self.scope.runtime.state_dir / 'observability').exists())
        self.assertEqual(result.stderr, b'')

    def test_real_cli_configure_verify_probe_disable_and_no_further_export(self):
        before = self.snapshot_state()
        with protocol_server() as server:
            configured = self.successful('configure', dict(expected_revision=0,
                destination=server.url, langfuse_project_id='lf-project'))
            self.assertFalse(configured['desired_opt_in'])
            self.assertEqual(server.requests, [])
            self.successful('status')
            self.assertEqual(server.requests, [])
            enabled = self.successful('enable', dict(expected_revision=1), server.environment)
            self.assertTrue(enabled['desired_opt_in'])
            self.assertEqual(enabled['collection'], 'unavailable')
            self.assertEqual([request['method'] for request in server.requests], ['GET'])
            verified = self.successful('probe', dict(expected_revision=2), server.environment)
            self.assertTrue(verified['probe']['verified'])
            self.assertFalse(verified['native_collection_qualified'])
            self.assertEqual(sum(request['method'] == 'POST' for request in server.requests), 1)
            count = len(server.requests)
            disabled = self.successful('disable', dict(expected_revision=2))
            self.assertFalse(disabled['desired_opt_in'])
            self.assertEqual(len(server.requests), count)
            blocked = self.invoke('probe', dict(expected_revision=3), server.environment)
            self.assertEqual(blocked.returncode, 1)
            self.assertEqual(len(server.requests), count)
            self.assertNotIn(PUBLIC_KEY, blocked.stdout.decode())
            self.assertNotIn(SECRET_KEY, blocked.stdout.decode())
        after = {key: value for key, value in self.snapshot_state().items() if not key.startswith('observability/')}
        self.assertEqual(after, before)

    def test_invalid_cli_input_and_missing_keys_return_only_bounded_errors(self):
        for raw in (b'{"expected_revision":0,"expected_revision":1}', b'[]', b'{' + b' ' * 9000):
            result = self.invoke('enable', raw=raw)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(json.loads(result.stdout)['ok'])
            self.assertEqual(result.stderr, b'')
        self.successful('configure', dict(expected_revision=0, destination='https://cloud.langfuse.com',
            langfuse_project_id='lf-project'))
        result = self.invoke('enable', dict(expected_revision=1))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['error'], 'credentials_unavailable')
        self.assertFalse(self.successful('status')['desired_opt_in'])

    def test_probe_verifies_new_keys_again_and_never_reuses_cached_connection_health(self):
        with protocol_server() as server:
            self.successful('configure', dict(expected_revision=0, destination=server.url,
                langfuse_project_id='lf-project'))
            self.successful('enable', dict(expected_revision=1), server.environment)
            server.projects_status = 401
            result = self.invoke('probe', dict(expected_revision=2), server.environment)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(any(request['method'] == 'POST' for request in server.requests))
            count = len(server.requests)
            status = self.successful('status')
            self.assertTrue(status['desired_opt_in'])
            self.assertEqual(status['connection'], 'not_checked')
            self.assertEqual(len(server.requests), count)


if __name__ == '__main__':
    unittest.main()
