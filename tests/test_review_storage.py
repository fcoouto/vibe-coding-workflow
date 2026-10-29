"""Temporary review storage proofs use only disposable private paths and Git repos."""

from concurrent.futures import ThreadPoolExecutor
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


PACKAGE = Path(__file__).resolve().parents[1]


class ReviewStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vibe-review-storage-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.repo = self.base / "repository"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "Fixture")
        (self.repo / "tracked.txt").write_text("unchanged\n")
        (self.repo / "subset").mkdir()
        (self.repo / "subset" / "file.txt").write_text("subset\n")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.private = self.base / "private-data"
        self.plan_a = self.base / "plan-a"
        self.plan_b = self.base / "plan-b"
        self.plan_a.mkdir()
        self.plan_b.mkdir()
        (self.plan_a / "plan.json").write_text("plan a\n")
        (self.plan_b / "plan.json").write_text("plan b\n")
        self.locator = self.base / "machine" / "machine.json"
        self.locator.parent.mkdir(mode=0o700, parents=True)
        self.api = None
        self.locator_patch = None

    def load_api(self):
        if self.api is None:
            self.api = importlib.import_module("runtime.review_storage")
            self.locator_patch = patch.object(self.api, "_machine_config_path", return_value=self.locator)
            self.locator_patch.start()
            self.addCleanup(self.locator_patch.stop)
        return self.api

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], stderr=subprocess.DEVNULL).decode().strip()

    @staticmethod
    def tree_snapshot(root):
        """Capture disposable tree names, modes, directory times, links and file bytes."""
        root = Path(root)
        if not root.exists():
            return None
        snapshot = []
        for path in sorted(root.rglob("*")):
            info = path.lstat()
            rel = str(path.relative_to(root))
            if path.is_symlink():
                body = os.readlink(path)
            elif path.is_file():
                body = path.read_bytes()
            else:
                body = None
            snapshot.append((rel, info.st_mode, info.st_mtime_ns, body))
        return tuple(snapshot)

    def prepare(self, path=None):
        result = self.load_api().prepare_storage(path or self.private)
        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("status"), "ready", result)
        return result

    def resolve(self, target):
        result = self.load_api().resolve_owner(str(target))
        self.assertIsInstance(result, dict)
        return result

    def test_unconfigured_status_and_lookup_are_read_only_and_pending(self):
        before = (self.tree_snapshot(self.base), self.private.exists(), self.locator.exists())
        status = self.load_api().storage_status()
        owner = self.resolve(self.repo)
        self.assertIsInstance(status, dict)
        self.assertFalse(status.get("ok"))
        self.assertEqual(status.get("status"), "storage_pending", status)
        self.assertFalse(owner.get("ok"))
        self.assertEqual(owner.get("status"), "storage_pending", owner)
        self.assertEqual((self.tree_snapshot(self.base), self.private.exists(), self.locator.exists()), before)

    def test_prepare_reopen_is_idempotent_and_different_choice_is_protected(self):
        first = self.prepare()
        self.assertTrue((self.private / "review-evidence" / "runtime.sqlite3").is_file())
        chosen = self.tree_snapshot(self.private)
        locator = self.locator.read_bytes()

        self.api = importlib.reload(self.api)
        self.locator_patch.stop()
        self.locator_patch = patch.object(self.api, "_machine_config_path", return_value=self.locator)
        self.locator_patch.start()
        self.addCleanup(self.locator_patch.stop)
        replay = self.prepare(self.private)
        self.assertEqual(replay.get("private_data_dir"), first.get("private_data_dir"))
        self.assertEqual(self.tree_snapshot(self.private), chosen)
        self.assertEqual(self.locator.read_bytes(), locator)

        other = self.base / "other-private-data"
        protected = self.api.prepare_storage(other)
        self.assertFalse(protected.get("ok"), protected)
        self.assertEqual(protected.get("status"), "protected", protected)
        self.assertEqual(self.tree_snapshot(self.private), chosen)
        self.assertFalse(other.exists())

    def test_new_machine_ancestor_entries_are_fsynced_before_authority_initialization(self):
        api = self.load_api()
        from runtime import state

        fresh = self.base / "fresh-machine-root"
        locator = fresh / ".config" / "vibe-coding-workflow" / "machine.json"
        required_parent_syncs = (self.base, fresh, fresh / ".config")
        required_before_initialize = set((*required_parent_syncs, locator.parent))
        seen = []
        before_initialize = []
        real_fsync = os.fsync
        real_initialize = state._initialize

        def record_fsync(descriptor):
            info = os.fstat(descriptor)
            for candidate in (*required_parent_syncs, locator.parent):
                try:
                    current = candidate.stat()
                except FileNotFoundError:
                    continue
                if (info.st_dev, info.st_ino) == (current.st_dev, current.st_ino):
                    seen.append(candidate)
            return real_fsync(descriptor)

        def record_initialize(*args, **kwargs):
            before_initialize.append(set(seen))
            return real_initialize(*args, **kwargs)

        with patch.object(api, "_machine_config_path", return_value=locator), \
             patch.object(api.os, "fsync", side_effect=record_fsync), \
             patch.object(state, "_initialize", side_effect=record_initialize):
            result = api.prepare_storage(self.private)

        self.assertTrue(result.get("ok"), result)
        self.assertEqual(len(before_initialize), 1, before_initialize)
        self.assertTrue(required_before_initialize.issubset(before_initialize[0]), before_initialize)

    def test_machine_parent_fsync_failure_prevents_authority_initialization(self):
        api = self.load_api()
        from runtime import state

        fresh = self.base / "fsync-failure-machine-root"
        locator = fresh / ".config" / "vibe-coding-workflow" / "machine.json"
        base_info = self.base.stat()
        real_fsync = os.fsync
        real_initialize = state._initialize
        initialized = []

        def fail_parent_fsync(descriptor):
            info = os.fstat(descriptor)
            if (info.st_dev, info.st_ino) == (base_info.st_dev, base_info.st_ino):
                raise OSError("fixture parent fsync failure")
            return real_fsync(descriptor)

        def record_initialize(*args, **kwargs):
            initialized.append(True)
            return real_initialize(*args, **kwargs)

        with patch.object(api, "_machine_config_path", return_value=locator), \
             patch.object(api.os, "fsync", side_effect=fail_parent_fsync), \
             patch.object(state, "_initialize", side_effect=record_initialize):
            result = api.prepare_storage(self.private)

        self.assertFalse(result.get("ok"), result)
        self.assertEqual(result.get("status"), "protected", result)
        self.assertFalse(initialized, initialized)
        self.assertFalse((self.private / "review-evidence" / "runtime.sqlite3").exists())

    def test_client_discovery_roots_are_rejected_before_mutation_with_sibling_control(self):
        api = self.load_api()
        for client_path in (Path(".agents/skills"), Path(".codex/skills"), Path(".claude/skills"),
                            Path(".codex/agents"), Path(".claude/agents"), Path(".claude/commands"),
                            Path(".cursor/rules")):
            with self.subTest(client_path=client_path):
                home_name = "home-" + "-".join(part.lstrip(".") for part in client_path.parts)
                home = self.base / home_name
                home.mkdir(mode=0o700)
                locator = home / ".config" / "vibe-coding-workflow" / "machine.json"
                selected = home / client_path / "review-data"
                before = self.tree_snapshot(home)
                with patch.object(api, "_machine_config_path", return_value=locator), \
                     patch.object(Path, "home", return_value=home):
                    result = api.prepare_storage(selected)
                self.assertFalse(result.get("ok"), result)
                self.assertEqual(result.get("status"), "protected", result)
                self.assertEqual(self.tree_snapshot(home), before)
                self.assertFalse(locator.exists())
                self.assertFalse(selected.exists())

        home = self.base / "home-valid-sibling"
        home.mkdir(mode=0o700)
        locator = home / ".config" / "vibe-coding-workflow" / "machine.json"
        sibling = home / ".local" / "share" / "vibe-coding-workflow"
        with patch.object(api, "_machine_config_path", return_value=locator), \
             patch.object(Path, "home", return_value=home):
            valid = api.prepare_storage(sibling)
        self.assertTrue(valid.get("ok"), valid)
        self.assertEqual(valid.get("status"), "ready", valid)

    def test_cyclic_target_is_protected_through_api_and_workflow_main(self):
        api = self.load_api()
        home = self.base / "cyclic-target-home"
        home.mkdir(mode=0o700)
        locator = home / ".config" / "vibe-coding-workflow" / "machine.json"
        target = self.repo / "cycle-a"
        target.symlink_to("cycle-b")
        (self.repo / "cycle-b").symlink_to("cycle-a")
        environment = os.environ.copy()
        environment["HOME"] = str(home)

        with patch.object(api, "_machine_config_path", return_value=locator):
            prepared = api.prepare_storage(self.private)
            self.assertTrue(prepared.get("ok"), prepared)
            before = self.tree_snapshot(self.private)
            direct_error = None
            try:
                direct = api.resolve_owner(target)
            except RuntimeError as error:
                direct_error = str(error)
                direct = None
            command = subprocess.run([sys.executable, "-B", str(PACKAGE / "scripts" / "workflow.py"),
                                      "storage", "owner", "--cwd", str(target)], cwd=PACKAGE, env=environment,
                                     capture_output=True, text=True, timeout=10)

        try:
            cli_report = json.loads(command.stdout)
        except json.JSONDecodeError:
            cli_report = None
        self.assertIsNone(direct_error, direct_error)
        self.assertIsInstance(direct, dict)
        self.assertFalse(direct.get("ok"), direct)
        self.assertEqual(direct.get("status"), "protected", direct)
        self.assertIsInstance(direct.get("reason"), str, direct)
        self.assertLessEqual(len(direct.get("reason", "")), 256, direct)
        self.assertEqual(command.returncode, 1, (command.returncode, command.stderr, command.stdout))
        self.assertEqual(command.stderr, "")
        self.assertEqual(cli_report, direct)
        self.assertEqual(self.tree_snapshot(self.private), before)

    def test_root_subset_and_symlink_alias_replay_same_owner_without_writes(self):
        self.prepare()
        repo_before = self.tree_snapshot(self.repo)
        plans_before = (self.tree_snapshot(self.plan_a), self.tree_snapshot(self.plan_b))

        first = self.resolve(self.repo)
        self.assertTrue(first.get("ok"), first)
        self.assertEqual(first.get("owner", {}).get("kind"), "temporary", first)
        self.assertTrue(first.get("reference"), first)
        self.assertTrue(first.get("created_at"), first)
        after_first = self.tree_snapshot(self.private)

        alias = self.base / "repository-alias"
        alias.symlink_to(self.repo, target_is_directory=True)
        subset = self.repo / "subset"
        replay_subset = self.resolve(subset)
        replay_alias = self.resolve(alias)
        self.assertEqual((replay_subset.get("owner"), replay_subset.get("reference"), replay_subset.get("created_at")),
                         (first.get("owner"), first.get("reference"), first.get("created_at")))
        self.assertEqual((replay_alias.get("owner"), replay_alias.get("reference"), replay_alias.get("created_at")),
                         (first.get("owner"), first.get("reference"), first.get("created_at")))
        self.assertEqual(self.tree_snapshot(self.private), after_first)
        self.assertEqual(self.tree_snapshot(self.repo), repo_before)
        self.assertEqual((self.tree_snapshot(self.plan_a), self.tree_snapshot(self.plan_b)), plans_before)

    def test_replacing_subset_file_reuses_original_owner_without_writes(self):
        self.prepare()
        first = self.resolve(self.repo)
        self.assertTrue(first.get("ok"), first)
        file = self.repo / "subset" / "file.txt"
        replacement = file.with_suffix(".new")
        replacement.write_text("updated content\n")
        replacement.replace(file)
        before = self.tree_snapshot(self.private)

        replay = self.resolve(file)
        self.assertEqual((replay.get("owner"), replay.get("reference"), replay.get("created_at")),
                         (first.get("owner"), first.get("reference"), first.get("created_at")))
        self.assertEqual(self.tree_snapshot(self.private), before)

    def test_repository_moved_and_replaced_at_old_path_is_protected(self):
        self.prepare()
        first = self.resolve(self.repo)
        self.assertTrue(first.get("ok"), first)
        moved = self.base / "moved-original-repository"
        self.repo.rename(moved)
        before = self.tree_snapshot(self.private)
        moved_result = self.resolve(moved)
        self.assertFalse(moved_result.get("ok"), moved_result)
        self.assertEqual(moved_result.get("status"), "protected", moved_result)
        self.assertEqual(self.tree_snapshot(self.private), before)

        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "replacement@example.invalid")
        self.git("config", "user.name", "Replacement")
        (self.repo / "replacement.txt").write_text("different repository\n")
        self.git("add", ".")
        self.git("commit", "-qm", "replacement")

        result = self.resolve(self.repo)
        self.assertFalse(result.get("ok"), result)
        self.assertEqual(result.get("status"), "protected", result)
        self.assertEqual(self.tree_snapshot(self.private), before)

    def test_concurrent_first_resolution_creates_one_owner(self):
        self.prepare()
        targets = [self.repo, self.repo / "subset", self.repo]
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(self.resolve, targets, timeout=15))
        self.assertTrue(all(result.get("ok") for result in results), results)
        identities = {(result.get("owner", {}).get("id"),
                       json.dumps(result.get("reference"), sort_keys=True, separators=(",", ":")),
                       result.get("created_at"))
                      for result in results}
        self.assertEqual(len(identities), 1, results)

    def test_separate_clone_does_not_reuse_original_repository_owner(self):
        self.prepare()
        original = self.resolve(self.repo)
        clone = self.base / "separate-clone"
        subprocess.check_call(["git", "clone", "-q", str(self.repo), str(clone)], stderr=subprocess.DEVNULL)
        copied = self.resolve(clone)
        self.assertTrue(copied.get("ok"), copied)
        self.assertEqual(copied.get("owner", {}).get("kind"), "temporary", copied)
        self.assertNotEqual(copied.get("owner", {}).get("id"), original.get("owner", {}).get("id"), copied)
        self.assertNotEqual(copied.get("reference"), original.get("reference"), copied)

    def test_nested_repository_overlap_is_protected_without_allocation(self):
        self.prepare()
        parent = self.resolve(self.repo)
        self.assertTrue(parent.get("ok"), parent)
        before = self.tree_snapshot(self.private)
        nested = self.repo / "subset" / "nested-repository"
        nested.mkdir()
        subprocess.check_call(["git", "init", "-q", str(nested)], stderr=subprocess.DEVNULL)
        nested_result = self.resolve(nested)
        self.assertFalse(nested_result.get("ok"), nested_result)
        self.assertEqual(nested_result.get("status"), "protected", nested_result)
        self.assertEqual(self.tree_snapshot(self.private), before)

    def test_linked_worktree_does_not_receive_temporary_owner(self):
        self.prepare()
        linked = self.base / "linked-worktree"
        self.git("worktree", "add", "--detach", str(linked))
        before = self.tree_snapshot(self.private)
        result = self.resolve(linked)
        self.assertFalse(result.get("ok"), result)
        self.assertEqual(result.get("status"), "protected", result)
        self.assertEqual(self.tree_snapshot(self.private), before)

    def test_deleted_authority_database_is_protected_without_recreation(self):
        self.prepare()
        database = self.private / "review-evidence" / "runtime.sqlite3"
        original = database.read_bytes()
        database.unlink()
        missing = self.resolve(self.repo)
        self.assertFalse(missing.get("ok"), missing)
        self.assertFalse(database.exists())
        self.assertEqual(missing.get("status"), "protected", missing)

    def test_replaced_authority_database_is_protected(self):
        self.prepare()
        database = self.private / "review-evidence" / "runtime.sqlite3"
        original = database.read_bytes()
        replacement = database.with_suffix(".replacement")
        replacement.write_bytes(original)
        replacement.replace(database)
        protected = self.resolve(self.repo)
        self.assertFalse(protected.get("ok"), protected)
        self.assertEqual(protected.get("status"), "protected", protected)
        self.assertEqual(database.read_bytes(), original)

    def test_replaced_selected_storage_parent_is_protected(self):
        import shutil
        self.prepare()
        first = self.resolve(self.repo)
        self.assertTrue(first.get("ok"), first)
        selected_parent = self.private / "review-evidence"
        displaced_parent = self.base / "displaced-review-evidence"
        selected_parent.rename(displaced_parent)
        shutil.copytree(displaced_parent, selected_parent)
        before = self.tree_snapshot(self.private)

        result = self.resolve(self.repo)
        self.assertFalse(result.get("ok"), result)
        self.assertEqual(result.get("status"), "protected", result)
        self.assertEqual(self.tree_snapshot(self.private), before)

    def test_preexisting_unowned_schema_three_authority_is_not_adopted(self):
        from runtime import evidence, state
        self.private.mkdir(mode=0o700)
        directory = self.private / "review-evidence"
        directory.mkdir(mode=0o700)
        creation = state._initialize(directory / "runtime.sqlite3", version=3,
                                     expected_directory=evidence._binding(directory))
        os.close(creation.descriptor)
        before = self.tree_snapshot(self.private)

        result = self.load_api().prepare_storage(self.private)
        self.assertFalse(result.get("ok"), result)
        self.assertEqual(result.get("status"), "protected", result)
        self.assertEqual(self.tree_snapshot(self.private), before)
        status = self.api.storage_status()
        self.assertFalse(status.get("ok"), status)
        self.assertNotEqual(status.get("status"), "ready", status)

    def test_owner_replay_survives_a_fresh_process_reopen(self):
        api = self.load_api()
        home = self.base / "fresh-process-home"
        home.mkdir(mode=0o700)
        locator = home / ".config" / "vibe-coding-workflow" / "machine.json"
        environment = os.environ.copy()
        environment["HOME"] = str(home)
        script = "from runtime import review_storage; import json,sys; print(json.dumps(review_storage.resolve_owner(sys.argv[1]), sort_keys=True))"

        with patch.object(api, "_machine_config_path", return_value=locator):
            self.assertTrue(api.prepare_storage(self.private).get("ok"))
            first = api.resolve_owner(self.repo)
            self.assertTrue(first.get("ok"), first)
            before = self.tree_snapshot(self.private)
            process = subprocess.run([sys.executable, "-B", "-c", script, str(self.repo)], cwd=PACKAGE,
                                     env=environment, capture_output=True, text=True, timeout=10)

        self.assertEqual(process.returncode, 0, (process.stderr, process.stdout))
        self.assertEqual(process.stderr, "")
        replay = json.loads(process.stdout)
        self.assertEqual(replay, first)
        self.assertEqual(self.tree_snapshot(self.private), before)

    def test_interrupted_initialization_is_preserved_without_automatic_retry(self):
        self.load_api()
        from runtime import state
        with patch.object(state, "_initialize", side_effect=OSError("fixture interruption")):
            first = self.api.prepare_storage(self.private)
        self.assertFalse(first.get("ok"), first)
        self.assertEqual(first.get("status"), "protected", first)
        after_interruption = self.tree_snapshot(self.base)
        replay = self.api.prepare_storage(self.private)
        self.assertFalse(replay.get("ok"), replay)
        self.assertEqual(replay.get("status"), "protected", replay)
        self.assertEqual(self.tree_snapshot(self.base), after_interruption)

    def test_entire_selected_directory_deletion_stays_pending_or_protected(self):
        import shutil
        self.prepare()
        chosen = self.tree_snapshot(self.private)
        self.assertIsNotNone(chosen)
        shutil.rmtree(self.private)
        result = self.resolve(self.repo)
        self.assertFalse(result.get("ok"), result)
        self.assertEqual(result.get("status"), "protected", result)
        self.assertFalse(self.private.exists())


class EnrolledReviewStorageTests(unittest.TestCase):
    def setUp(self):
        from tests.test_evidence import CanonicalEvidenceTests
        self.fixture = CanonicalEvidenceTests(methodName="runTest")
        self.fixture.setUp(d4_recovery=True)
        self.addCleanup(self.fixture.doCleanups)
        self.base = self.fixture.fixture.root
        self.api = importlib.import_module("runtime.review_storage")
        self.locator = self.base / "machine" / "machine.json"
        self.locator.parent.mkdir(mode=0o700, parents=True)
        self.locator_patch = patch.object(self.api, "_machine_config_path", return_value=self.locator)
        self.locator_patch.start()
        self.addCleanup(self.locator_patch.stop)

    def test_genuinely_enrolled_repository_keeps_project_authority(self):
        result = self.api.prepare_storage(self.base / "temporary-private")
        self.assertTrue(result.get("ok"), result)
        self.fixture.fixture.checked()
        temporary_storage = self.base / "temporary-private"
        project_storage = self.fixture.scope.runtime.state_dir
        project_record = self.fixture.fixture.repo / ".vibe-coding-workflow" / "project.json"
        self.assertTrue(project_storage.is_dir(), project_storage)
        self.assertTrue(project_record.is_file(), project_record)
        before_temporary_storage = ReviewStorageTests.tree_snapshot(temporary_storage)
        before_project_storage = ReviewStorageTests.tree_snapshot(project_storage)
        self.assertTrue(before_temporary_storage, temporary_storage)
        self.assertTrue(before_project_storage, project_storage)
        before_project_record = project_record.read_bytes()
        owner = self.api.resolve_owner(str(self.fixture.fixture.repo))
        self.assertFalse(owner.get("ok"), owner)
        self.assertEqual(owner.get("status"), "protected", owner)
        self.assertEqual(ReviewStorageTests.tree_snapshot(temporary_storage), before_temporary_storage)
        self.assertEqual(ReviewStorageTests.tree_snapshot(project_storage), before_project_storage)
        self.assertEqual(project_record.read_bytes(), before_project_record)
