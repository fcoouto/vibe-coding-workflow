"""Cap witnesses bind real files and existing SQLite sidecar states."""

from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch


class RetentionCapWitnessBoundaryTests(unittest.TestCase):
    @staticmethod
    def budget():
        return dict(paths=0, bytes=0, deadline=time.monotonic() + 4)

    def test_cap_file_rejects_a_symlinked_parent_without_reading_its_target(self):
        from runtime import evidence
        from runtime.startup import StartupError

        with tempfile.TemporaryDirectory(prefix="cap-witness-") as temporary:
            root = Path(temporary)
            outside = root / "outside"
            outside.mkdir(mode=0o700)
            target = outside / "private.json"
            original = b"private witness target\n"
            target.write_bytes(original)
            target.chmod(0o600)
            link = root / "linked-parent"
            link.symlink_to(outside, target_is_directory=True)
            budget = self.budget()
            deadline = budget["deadline"]

            with self.assertRaises((StartupError, OSError)):
                evidence._cap_input_file(link / target.name, budget)

            self.assertEqual(target.read_bytes(), original)
            self.assertLessEqual(budget["paths"], 4096)
            self.assertLessEqual(budget["bytes"], 8 * 1024 * 1024)
            self.assertEqual(budget["deadline"], deadline)

    def test_cap_file_rejects_same_size_replacement_before_read_and_closes_descriptor(self):
        import hashlib
        import os
        from runtime import evidence, onboarding
        from runtime.startup import StartupError

        with tempfile.TemporaryDirectory(prefix="cap-replacement-") as temporary:
            root = Path(temporary)
            target = root / "control.json"
            replacement = root / "replacement.json"
            original_contents = b"original control contents\n"
            target.write_bytes(original_contents)
            replacement_bytes = b"altered control contents!\n"
            self.assertEqual(len(target.read_bytes()), len(replacement_bytes))
            replacement.write_bytes(replacement_bytes)
            target.chmod(0o600)
            replacement.chmod(0o600)
            replacement_inode = replacement.stat().st_ino
            self.assertNotEqual(target.stat().st_ino, replacement_inode)

            unchanged_budget = self.budget()
            unchanged_deadline = unchanged_budget["deadline"]
            original_stat = evidence._closure_file_stat(target)
            witness = evidence._cap_input_file(target, unchanged_budget)
            self.assertEqual(witness, dict(stat=original_stat,
                                          sha256=hashlib.sha256(original_contents).hexdigest()))
            self.assertEqual(unchanged_budget["bytes"], len(original_contents))
            self.assertEqual(unchanged_budget["paths"], len(target.parts) + 2)
            self.assertEqual(unchanged_budget["deadline"], unchanged_deadline)

            opened = []
            reads = []
            real_open_path = onboarding._open_path
            real_fdopen = evidence.os.fdopen

            class ReadSpy:
                def __init__(self, stream):
                    self.stream = stream

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return self.stream.__exit__(*args)

                def fileno(self):
                    return self.stream.fileno()

                def read(self, size=-1):
                    reads.append(size)
                    return self.stream.read(size)

            def replace_before_open(path, flags):
                os.replace(replacement, target)
                return real_open_path(path, flags)

            def observe_fdopen(descriptor, *args, **kwargs):
                opened.append(descriptor)
                return ReadSpy(real_fdopen(descriptor, *args, **kwargs))

            budget = self.budget()
            deadline = budget["deadline"]
            with patch.object(onboarding, "_open_path", side_effect=replace_before_open), \
                    patch.object(evidence.os, "fdopen", side_effect=observe_fdopen):
                with self.assertRaises(StartupError):
                    evidence._cap_input_file(target, budget)

            self.assertEqual(target.stat().st_ino, replacement_inode)
            self.assertEqual(target.read_bytes(), replacement_bytes)
            self.assertEqual(len(opened), 1)
            self.assertEqual(reads, [], "Replacement bytes were read before the opened inode was rejected")
            self.assertEqual(budget["bytes"], 8 * 1024 * 1024)
            self.assertEqual(budget["deadline"], deadline)
            self.assertLessEqual(budget["paths"], 4096)
            with self.assertRaises(OSError):
                os.fstat(opened[0])

    def test_witnesses_accept_a_real_rollback_journal_without_reading_database_pages(self):
        from runtime import changes, evidence, review_storage, state
        from runtime.startup import PROJECT_FILE
        from tests.test_detail_retention import DetailRetentionTests

        fixture = DetailRetentionTests(methodName="runTest")
        self.addCleanup(fixture.doCleanups)
        umbrella, _, project_context, _, _, _ = fixture.umbrella_cap_fixture()
        result = review_storage.prepare_storage(umbrella.private / "temporary-private")
        self.assertTrue(result.get("ok"), result)

        class ObserveControl:
            def access(inner, **facts):
                self.assertIsNotNone(review_storage._MACHINE_ACQUISITION.get())
                project_context = facts["project_context"]
                temporary_context = facts["temporary_context"]
                config = facts["config"]
                project = facts["project"]
                guarded = sorted({project_context.directory, temporary_context.directory})
                with changes._authority_guards(guarded):
                    self.assertTrue(changes._held_authority_guards(guarded))
                    connection = sqlite3.connect(project_context.database, timeout=0.1)
                    try:
                        self.assertEqual(connection.execute("PRAGMA journal_mode=PERSIST").fetchone()[0], "persist")
                        connection.execute("BEGIN IMMEDIATE")
                        row = connection.execute("SELECT scope_id, generation FROM checkouts LIMIT 1").fetchone()
                        self.assertIsNotNone(row, "Expected the actual enrolled checkout row")
                        original_generation = row[1]
                        connection.execute("UPDATE checkouts SET generation=? WHERE scope_id=?",
                                           (original_generation + 1, row[0]))
                        connection.execute("UPDATE checkouts SET generation=? WHERE scope_id=?",
                                           (original_generation, row[0]))
                        connection.commit()
                    finally:
                        connection.close()

                    journal = Path(str(project_context.database) + "-journal")
                    self.assertTrue(journal.is_file(), "Committed SQLite PERSIST transaction left no rollback journal")
                    state._sidecars(project_context.database)
                    with evidence._context_database(project_context) as db:
                        self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "delete")
                        self.assertEqual(db.execute("SELECT generation FROM checkouts WHERE scope_id=?",
                                                     (row[0],)).fetchone()[0], original_generation)
                    self.assertTrue(journal.is_file(), "Read-only schema validation removed the persisted journal")

                    original_reader = evidence._cap_input_file
                    read_paths = []

                    def observe(path, budget):
                        read_paths.append(Path(path))
                        return original_reader(path, budget)

                    cap_budget = self.budget()
                    with patch.object(evidence, "_cap_input_file", side_effect=observe):
                        witnesses = evidence._cap_input_witnesses(
                            project, config, (project_context, temporary_context), cap_budget)

                    project_file = Path(project["project_root"]) / PROJECT_FILE
                    machine_path = review_storage._MACHINE_ACQUISITION.get()["path"]
                    self.assertEqual(set(read_paths), {project_file, machine_path})
                    self.assertNotIn(project_context.database, read_paths)
                    self.assertIn(str(project_context.database), witnesses["databases"])
                    self.assertIn(str(temporary_context.database), witnesses["databases"])
                    self.assertIsNotNone(witnesses["databases"][str(project_context.database)]["sidecars"]["-journal"])
                    self.assertLessEqual(cap_budget["paths"], 4096)
                    self.assertLess(cap_budget["bytes"], 8 * 1024 * 1024)
                return dict(inspected=True)

        acquisition_budget = dict(paths=0, bytes=0, deadline=time.monotonic() + 15)
        self.assertEqual(review_storage._acquire_enrolled_accounting(
            umbrella.members[0], control=ObserveControl(), budget=acquisition_budget), dict(inspected=True))


if __name__ == "__main__":
    unittest.main()
