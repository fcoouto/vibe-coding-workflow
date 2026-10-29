"""End-to-end checks for host-issued D4 rollback authority."""

import unittest
from pathlib import Path

from runtime.startup import PROJECT_FILE
from tests import test_changes


class D4RollbackAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_changes.ScopedChangesTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.request, self.contexts = self.fixture.d4_bookkeeping_request()
        self.grants = []
        self.facts = []

        class Host:
            def acquire_d4_bookkeeping(owner, acquired, issue):
                self.facts.append(acquired)
                grant = issue(acquired)
                self.grants.append(grant)
                return grant

        self.host_owner = Host()

    def test_actual_owned_apply_rollback_restores_original_preimages(self):
        f = self.fixture
        project_file = f.repo / PROJECT_FILE
        self.assertFalse(project_file.exists())
        with f.changes._bootstrap_d4_host(
            self.host_owner, issuer=f.changes._D4_HOST_BOOTSTRAP_ISSUER
        ) as host:
            applied = f.changes._run_scoped(f.directory, self.request, "apply", host=host)
            self.assertEqual(applied["exit_code"], 0, applied)
            self.assertTrue(project_file.exists())
            rolled_back = f.changes._run_scoped(f.directory, self.request, "rollback", host=host)

        self.assertEqual(rolled_back["exit_code"], 0, rolled_back)
        self.assertFalse(project_file.exists())
        for action in self.request["manifest"]["actions"]:
            for effect in action["effects"]:
                self.assertEqual(
                    f.changes._fingerprint(
                        Path(action["owner"]["root"]), effect["path"]
                    ),
                    effect["before"],
                )
        self.assertTrue(self.grants)
        self.assertEqual(len({id(grant.acquisition) for grant in self.grants}), len(self.grants))
        for context in self.contexts:
            self.assertTrue(all(
                f.changes._authority_owner(location) is None
                for location in f.changes._authority_locations([context.directory])
            ))
            recovery = f.changes.inspect_lifecycle_recovery(context.authority_set, ())
            self.assertTrue(recovery["complete"], recovery)

    def test_actual_rollback_refuses_same_bytes_external_project_replacement(self):
        f = self.fixture
        project_file = f.repo / PROJECT_FILE
        with f.changes._bootstrap_d4_host(
            self.host_owner, issuer=f.changes._D4_HOST_BOOTSTRAP_ISSUER
        ) as host:
            applied = f.changes._run_scoped(f.directory, self.request, "apply", host=host)
            self.assertEqual(applied["exit_code"], 0, applied)
            installed = project_file.read_bytes()
            mode = project_file.stat().st_mode & 0o777
            installed_inode = project_file.stat().st_ino
            replacement = project_file.with_name("external-project-replacement")
            replacement.write_bytes(installed)
            replacement.chmod(mode)
            replacement.replace(project_file)
            replacement_inode = project_file.stat().st_ino
            self.assertNotEqual(replacement_inode, installed_inode)
            blocked = f.changes._run_scoped(f.directory, self.request, "rollback", host=host)

        self.assertNotEqual(blocked["exit_code"], 0, blocked)
        self.assertIn("authority changed outside its owned transition", str(blocked))
        self.assertEqual(project_file.read_bytes(), installed)
        self.assertEqual(project_file.stat().st_ino, replacement_inode)
