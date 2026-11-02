"""Current project-entry authority; synthetic owner proof is software-only."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime import openrouter_settings as settings, startup
from tests.openrouter_fixtures import PACKAGE, _ACTUAL_ACQUIRE, enroll


class EntryScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.scope = enroll(self)
        self.repo = self.scope.repository_root

    def test_resolves_real_current_canonical_acquisition(self):
        try:
            resolved = settings.resolve(self.repo)
        except startup.StartupError:
            resolved = None
        self.assertIsNotNone(resolved, 'OpenRouter must consume actual current canonical acquisition')
        self.assertEqual(resolved, self.scope)

    def test_status_without_a_production_qualifier_fails_closed(self):
        with patch.object(startup, 'acquire_project_entry', _ACTUAL_ACQUIRE):
            with self.assertRaises(startup.StartupError):
                settings.resolve(self.repo)

    def test_outside_and_legacy_scopes_are_refused(self):
        outside = Path(self.tmp.name) / 'outside'
        outside.mkdir()
        with self.assertRaises(startup.StartupError):
            settings.resolve(outside)
        path = self.repo / startup.PROJECT_FILE
        path.write_text(json.dumps(dict(schema_version=1, project_id='legacy',
            repository_root=str(self.repo), git_common_dir=str(self.scope.git_common_dir),
            clients=['codex'], policy_digest=startup.policy_digest(PACKAGE),
            runtime=dict(schema_version=2, state_dir=str(self.scope.runtime.state_dir)))))
        with self.assertRaises(startup.StartupError):
            settings.resolve(self.repo)

    def test_configured_and_changed_authority_are_refused(self):
        path = self.repo / startup.PROJECT_FILE
        original = path.read_bytes()
        record = json.loads(original)
        record['repositories'][0]['checkouts'][0]['clients'][0]['activation']['status'] = 'configured'
        path.write_text(json.dumps(record))
        with self.assertRaises(startup.StartupError):
            settings.resolve(self.repo)
        path.write_bytes(original)
        with self.assertRaises(startup.StartupError):
            with settings.guard(self.repo) as owner:
                path.write_text('{}')
                owner.check()


if __name__ == '__main__':
    unittest.main()
