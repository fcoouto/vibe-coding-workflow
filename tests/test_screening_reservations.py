"""Real storage controls for one-use temporary screening reservations."""

import copy
import json
import sqlite3
import shutil
from pathlib import Path
import subprocess
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from unittest.mock import patch

from runtime import evidence, state
from tests import test_project_owner_storage, test_review_storage


PACKAGE = Path(__file__).resolve().parents[1]


class ScreeningReservationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_review_storage.ReviewStorageTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.api = self.fixture.load_api()
        self.fixture.prepare()

    def ordinary(self):
        owner = self.fixture.resolve(self.fixture.repo)
        self.assertTrue(owner.get("ok"), owner)
        return owner, {"target": str(self.fixture.repo)}

    def project(self):
        fixture = test_project_owner_storage.ProjectOwnerStorageTests(methodName="runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.prepare()
        owner = fixture.project_owner()
        self.assertTrue(owner.get("ok"), owner)
        return fixture, owner, {"project_scope": copy.deepcopy(fixture.scope)}

    def state_view(self, selection):
        return self.api.screening_status(copy.deepcopy(selection))

    def assert_identity(self, result, owner):
        for key in ("owner", "reference", "created_at"):
            self.assertEqual(result.get(key), owner.get(key), key)

    def artifact_snapshot(self, owner):
        with self.api._machine_guard() as (path, descriptor, parents):
            config = self.api._configuration(path, descriptor)
            context = self.api._ready_context(config, parents)
            with evidence._context_database(context) as db:
                metadata = state._metadata(db, owner["reference"]["name"])
                metadata.pop("screening", None)
                body = evidence._read(None, owner["reference"], context=context, db=db)
                return metadata, evidence._raw(body), Path(metadata["managed"]["path"]).read_bytes()

    def assert_state(self, result, expected, revision):
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("revision"), revision, result)
        self.assertEqual(result.get("screening", {}).get("revision"), revision, result)
        self.assertEqual(result.get("status"), expected, result)
        self.assertFalse(result.get("admitted"), result)
        self.assertNotIn("deadline_monotonic", result)

    def cli(self, args, request, *, code=None):
        script = (
            "import runpy,sys; from pathlib import Path; from unittest.mock import patch; "
            "from runtime import review_storage; workflow,locator=sys.argv[1:3]; "
            "sys.argv=[workflow,*sys.argv[3:]]; "
            "p=patch.object(review_storage,'_machine_config_path',return_value=Path(locator)); "
            "p.start(); runpy.run_path(workflow,run_name='__main__')"
        )
        command = subprocess.run(
            [sys.executable, "-B", "-c", script, str(PACKAGE / "scripts" / "workflow.py"),
             str(self.fixture.locator), *args], cwd=PACKAGE, input=json.dumps(request),
            capture_output=True, text=True, timeout=15)
        self.assertEqual(command.stderr, "")
        if code is not None:
            self.assertEqual(command.returncode, code, (command.stdout, command.stderr))
        try:
            report = json.loads(command.stdout)
        except json.JSONDecodeError:
            self.fail(f"CLI returned invalid JSON: {command.stdout!r}")
        return command, report

    def test_real_ordinary_and_umbrella_controls_keep_identity_and_scope_continuity(self):
        owner, selection = self.ordinary()
        artifact_before = self.artifact_snapshot(owner)
        targets_before = self.fixture.tree_snapshot(self.fixture.repo)
        plans_before = (self.fixture.tree_snapshot(self.fixture.plan_a), self.fixture.tree_snapshot(self.fixture.plan_b))
        status = self.state_view(selection)
        self.assert_identity(status, owner)
        self.assert_state(status, "available", 0)
        start = time.monotonic()
        reserved = self.api.reserve_screening(copy.deepcopy(selection), 0)
        finished = time.monotonic()
        self.assertTrue(reserved.get("ok"), reserved)
        self.assertTrue(reserved.get("admitted"), reserved)
        self.assertGreaterEqual(reserved.get("deadline_monotonic", 0), start + 300)
        self.assertLessEqual(reserved.get("deadline_monotonic", 0), finished + 300)
        self.assertEqual(reserved.get("revision"), 1, reserved)

        alias = self.fixture.base / "repository-alias"
        alias.symlink_to(self.fixture.repo, target_is_directory=True)
        for target in (self.fixture.repo / "subset", alias):
            replay = self.api.reserve_screening({"target": str(target)}, 0)
            self.assertFalse(replay.get("admitted"), replay)
            self.assertNotIn("deadline_monotonic", replay)
            self.assertEqual((replay.get("owner"), replay.get("reference"), replay.get("created_at")),
                             (owner.get("owner"), owner.get("reference"), owner.get("created_at")))
            self.assertEqual(replay.get("screening"), reserved.get("screening"))
        self.assertEqual(self.artifact_snapshot(owner), artifact_before)
        self.assertEqual(self.fixture.tree_snapshot(self.fixture.repo), targets_before)
        self.assertEqual((self.fixture.tree_snapshot(self.fixture.plan_a), self.fixture.tree_snapshot(self.fixture.plan_b)),
                         plans_before)

        project_fixture, project_owner, project_selection = self.project()
        first = self.api.screening_status(project_selection)
        self.assert_identity(first, project_owner)
        self.assert_state(first, "available", 0)
        project_reserved = self.api.reserve_screening(copy.deepcopy(project_selection), 0)
        self.assertTrue(project_reserved.get("admitted"), project_reserved)
        subset = copy.deepcopy(project_fixture.scope)
        subset["member_checkouts"] = [subset["member_checkouts"][0]]
        subset_result = self.api.screening_status({"project_scope": subset})
        self.assert_identity(subset_result, project_owner)
        self.assertEqual(subset_result.get("screening"), project_reserved.get("screening"))

    def test_status_is_cold_read_only_and_missing_owner_is_not_created(self):
        selection = {"target": str(self.fixture.repo)}
        before = (self.fixture.tree_snapshot(self.fixture.private), self.fixture.tree_snapshot(self.fixture.repo))
        result = self.state_view(selection)
        self.assertFalse(result.get("admitted"), result)
        self.assertNotIn("deadline_monotonic", result)
        self.assertEqual((result.get("screening"), result.get("revision")), (None, None))
        self.assertEqual((self.fixture.tree_snapshot(self.fixture.private), self.fixture.tree_snapshot(self.fixture.repo)), before)
        denied = self.api.reserve_screening(selection, 0)
        self.assertFalse(denied.get("ok"), denied)
        self.assertFalse(denied.get("admitted"), denied)
        self.assertEqual(self.fixture.tree_snapshot(self.fixture.private), before[0])

    def test_api_rejects_ambiguous_or_extended_selection_without_writes(self):
        _, selection = self.ordinary()
        before = self.fixture.tree_snapshot(self.fixture.private)
        invalid = ({**selection, "project_scope": {}}, {**selection, "extra": True},
                   {"target": "relative/path"}, {"project_scope": {}})
        for chosen in invalid:
            with self.subTest(selection=chosen):
                result = self.api.screening_status(chosen)
                self.assertFalse(result.get("ok"), result)
                self.assertFalse(result.get("admitted"), result)
                self.assertNotIn("deadline_monotonic", result)
        self.assertEqual(self.fixture.tree_snapshot(self.fixture.private), before)

    def test_only_one_admission_and_stale_replay_settlement_is_terminal(self):
        owner, selection = self.ordinary()
        first = self.api.reserve_screening(selection, 0)
        self.assertTrue(first.get("admitted"), first)
        ticket = first["screening"]["reservation"]
        for expected in (0, 1):
            repeated = self.api.reserve_screening(selection, expected)
            self.assertFalse(repeated.get("admitted"), repeated)
            self.assertNotIn("deadline_monotonic", repeated)
            self.assertEqual(repeated.get("screening"), first.get("screening"))
        settled = self.api.settle_screening(selection, copy.deepcopy(ticket))
        self.assertTrue(settled.get("ok"), settled)
        self.assertEqual(settled.get("screening"), {
            "version": 1, "birth": "temporary-owner-publication", "limit_ms": 300000,
            "revision": 2, "charged_ms": 300000, "settled_sequence": 1,
            "reservation": None,
            "last_receipt": {"ticket": ticket, "disposition": "charged-full"},
        })
        self.assertFalse(settled.get("admitted"), settled)
        self.assertNotIn("deadline_monotonic", settled)
        replay = self.api.settle_screening(selection, copy.deepcopy(ticket))
        self.assertEqual(replay.get("screening"), settled.get("screening"))
        self.assertFalse(replay.get("admitted"), replay)
        after = self.api.reserve_screening(selection, 2)
        self.assertFalse(after.get("admitted"), after)
        self.assertNotIn("deadline_monotonic", after)
        self.assertEqual(after.get("screening"), settled.get("screening"))
        self.assert_identity(after, owner)

    def test_forged_stale_and_cross_owner_tickets_protect_unchanged_state(self):
        owner, selection = self.ordinary()
        first = self.api.reserve_screening(selection, 0)
        ticket = first["screening"]["reservation"]
        state_before = self.api.screening_status(selection).get("screening")
        artifact_before = self.artifact_snapshot(owner)
        forged = dict(ticket, nonce="0" * 32)
        for bad in (forged, dict(ticket, ceiling_ms=True), dict(ticket, extra="x")):
            result = self.api.settle_screening(selection, bad)
            self.assertFalse(result.get("ok"), result)
            self.assertFalse(result.get("admitted"), result)
            self.assertNotIn("deadline_monotonic", result)
        self.assertEqual(self.api.screening_status(selection).get("screening"), state_before)
        self.assertEqual(self.artifact_snapshot(owner), artifact_before)
        second_repo = self.fixture.base / "second-repository"
        subprocess.run(["git", "clone", "-q", str(self.fixture.repo), str(second_repo)], check=True,
                       capture_output=True)
        other = self.fixture.resolve(second_repo)
        self.assertTrue(other.get("ok"), other)
        crossed = self.api.settle_screening({"target": str(second_repo)}, ticket)
        self.assertFalse(crossed.get("ok"), crossed)
        self.assertFalse(crossed.get("admitted"), crossed)
        self.assertEqual(crossed.get("owner"), other.get("owner"))
        self.assertEqual(self.api.screening_status(selection).get("screening"), state_before)
        self.assertEqual((first.get("owner"), first.get("reference"), first.get("created_at")),
                         (owner.get("owner"), owner.get("reference"), owner.get("created_at")))

    def test_failed_durable_reservation_commit_does_not_admit(self):
        owner, selection = self.ordinary()
        before = self.artifact_snapshot(owner)
        pending_at_commit = []
        connect = sqlite3.connect

        class FailingCommitConnection(sqlite3.Connection):
            def commit(db):
                if db.in_transaction:
                    for (raw,) in db.execute("select data from evidence_metadata"):
                        metadata = json.loads(raw)
                        screening = metadata.get("screening")
                        if screening and screening.get("revision") == 1:
                            pending_at_commit.append(copy.deepcopy(screening))
                            raise sqlite3.OperationalError("fixture commit failure")
                return super().commit()

        def fail_after_screening_update(*args, **kwargs):
            kwargs["factory"] = FailingCommitConnection
            return connect(*args, **kwargs)

        with patch.object(evidence.sqlite3, "connect", side_effect=fail_after_screening_update):
            failed = self.api.reserve_screening(selection, 0)
        self.assertFalse(failed.get("ok"), failed)
        self.assertFalse(failed.get("admitted"), failed)
        self.assertNotIn("deadline_monotonic", failed)
        self.assertEqual(len(pending_at_commit), 1, pending_at_commit)
        self.assertEqual(pending_at_commit[0].get("revision"), 1, pending_at_commit)
        current = self.api.screening_status(selection)
        self.assertEqual(current.get("screening", {}).get("revision"), 0, current)
        self.assertEqual(self.artifact_snapshot(owner), before)
        self.assertEqual(current.get("owner"), owner.get("owner"))

    def test_committed_crash_reopen_keeps_reservation_and_never_renews_deadline(self):
        owner, selection = self.ordinary()
        script = (
            "import os,runpy,sys; from pathlib import Path; from unittest.mock import patch; "
            "from runtime import review_storage; real=review_storage.reserve_screening; "
            "exec('def crash(*a, **k):\\n result=real(*a, **k)\\n os._exit(93)'); "
            "review_storage.reserve_screening=crash; workflow,locator=sys.argv[1:3]; "
            "p=patch.object(review_storage,'_machine_config_path',return_value=Path(locator)); p.start(); "
            "sys.argv=[workflow,'storage','screening','reserve']; runpy.run_path(workflow,run_name='__main__')"
        )
        command = subprocess.run([sys.executable, "-B", "-c", script,
            str(PACKAGE / "scripts" / "workflow.py"), str(self.fixture.locator)], cwd=PACKAGE,
            input=json.dumps({"selection": selection, "expected_revision": 0}), capture_output=True, text=True, timeout=15)
        self.assertEqual(command.returncode, 93, (command.stdout, command.stderr))
        self.assertEqual(command.stdout, "")
        status = self.api.screening_status(selection)
        self.assertEqual(status.get("revision"), 1, status)
        self.assertEqual(status.get("screening", {}).get("reservation", {}).get("sequence"), 1, status)
        self.assertFalse(status.get("admitted"), status)
        repeated = self.api.reserve_screening(selection, 0)
        self.assertFalse(repeated.get("admitted"), repeated)
        self.assertNotIn("deadline_monotonic", repeated)
        self.assertEqual(repeated.get("screening"), status.get("screening"))
        self.assertEqual(repeated.get("owner"), owner.get("owner"))

    def test_real_process_competition_serializes_single_admission_and_cli_is_strict(self):
        _, selection = self.ordinary()
        request = {"selection": selection, "expected_revision": 0}
        commands = []
        for _ in range(2):
            script = (
                "import os,runpy,sys; from pathlib import Path; from unittest.mock import patch; "
                "from runtime import review_storage; workflow,locator=sys.argv[1:3]; "
                "p=patch.object(review_storage,'_machine_config_path',return_value=Path(locator)); p.start(); "
                "os.write(2,b'READY\\n'); "
                "sys.argv=[workflow,'storage','screening','reserve']; runpy.run_path(workflow,run_name='__main__')"
            )
            commands.append(subprocess.Popen([sys.executable, "-B", "-c", script,
                str(PACKAGE / "scripts" / "workflow.py"), str(self.fixture.locator)], cwd=PACKAGE,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        for command in commands:
            self.assertEqual(command.stderr.readline(), "READY\n")
        outputs = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = [pool.submit(command.communicate, json.dumps(request)) for command in commands]
            for command, response in zip(commands, pending):
                out, err = response.result(timeout=20)
                self.assertEqual(command.returncode, 0, (out, err))
                self.assertEqual(err, "")
                outputs.append(json.loads(out))
        self.assertEqual(sum(bool(result.get("admitted")) for result in outputs), 1, outputs)
        self.assertEqual(len({json.dumps(result.get("screening"), sort_keys=True) for result in outputs}), 1, outputs)

        before = self.fixture.tree_snapshot(self.fixture.private)
        for args, payload in ((["storage", "screening", "status"], {"selection": selection, "extra": 1}),
                              (["storage", "screening", "reserve"], {"selection": selection,
                               "expected_revision": True}),
                              (["storage", "screening", "settle"], {"selection": selection,
                               "ticket": {"sequence": 1}, "duration_ms": 0})):
            command, report = self.cli(args, payload, code=1)
            self.assertFalse(report.get("ok"), report)
        self.assertEqual(self.fixture.tree_snapshot(self.fixture.private), before)

    def test_legacy_owner_is_not_retrofitted(self):
        owner, selection = self.ordinary()
        with self.api._machine_guard() as (path, descriptor, parents):
            config = self.api._configuration(path, descriptor)
            context = self.api._ready_context(config, parents)
            with evidence._context_database(context, write=True, durable=True) as db:
                metadata = state._metadata(db, owner["reference"]["name"])
                self.assertIn("screening", metadata)
                metadata.pop("screening")
                db.execute("update evidence_metadata set data=? where name=?",
                           (evidence._raw(metadata).decode(), owner["reference"]["name"]))
        legacy = self.api.screening_status(selection)
        self.assertFalse(legacy.get("ok"), legacy)
        self.assertEqual((legacy.get("screening"), legacy.get("revision")), (None, None))
        self.assertFalse(self.api.reserve_screening(selection, 0).get("admitted"))

    def test_unknown_screening_fields_are_protected(self):
        owner, selection = self.ordinary()
        with self.api._machine_guard() as (path, descriptor, parents):
            config = self.api._configuration(path, descriptor)
            context = self.api._ready_context(config, parents)
            with evidence._context_database(context, write=True, durable=True) as db:
                metadata = state._metadata(db, owner["reference"]["name"])
                metadata["screening"]["unknown"] = True
                db.execute("update evidence_metadata set data=? where name=?",
                           (evidence._raw(metadata).decode(), owner["reference"]["name"]))
        unknown = self.api.screening_status(selection)
        self.assertFalse(unknown.get("ok"), unknown)
        self.assertEqual((unknown.get("screening"), unknown.get("revision")), (None, None))
        self.assertFalse(self.api.reserve_screening(selection, 0).get("admitted"))

    def test_disjoint_owners_keep_independent_screening_allowances(self):
        owner, selection = self.ordinary()
        other_repo = self.fixture.base / "other-owner-repository"
        subprocess.run(["git", "clone", "-q", str(self.fixture.repo), str(other_repo)], check=True,
                       capture_output=True)
        other_owner = self.fixture.resolve(other_repo)
        self.assertTrue(other_owner.get("ok"), other_owner)
        other_selection = {"target": str(other_repo)}
        self.assertNotEqual(owner.get("reference"), other_owner.get("reference"))
        for result, expected_owner in ((self.api.screening_status(selection), owner),
                                       (self.api.screening_status(other_selection), other_owner)):
            self.assert_state(result, "available", 0)
            self.assert_identity(result, expected_owner)
            self.assertEqual(result["screening"]["charged_ms"], 0)
        reserved = self.api.reserve_screening(selection, 0)
        self.assertTrue(reserved.get("admitted"), reserved)
        other_after = self.api.screening_status(other_selection)
        self.assert_state(other_after, "available", 0)
        self.assertEqual(other_after["screening"]["charged_ms"], 0)
        second = self.api.reserve_screening(other_selection, 0)
        self.assertTrue(second.get("admitted"), second)
        self.assertNotEqual(reserved.get("reference"), second.get("reference"))

    def test_scope_replacement_is_protected(self):
        project_fixture, project_owner, project_selection = self.project()
        root = Path(project_fixture.project)
        old = root.with_name(root.name + "-original")
        root.rename(old)
        root.mkdir()
        replacement = self.api.screening_status(project_selection)
        self.assertFalse(replacement.get("ok"), replacement)
        self.assertFalse(replacement.get("admitted"), replacement)
        self.assertEqual(replacement.get("screening"), None)
        root.rmdir()
        old.rename(root)
        self.assertEqual(self.api.screening_status(project_selection).get("owner"), project_owner.get("owner"))

    def test_replaced_machine_configuration_is_protected_without_target_writes(self):
        owner, selection = self.ordinary()
        before = self.fixture.tree_snapshot(self.fixture.repo)
        original = self.fixture.locator.read_bytes()
        try:
            self.fixture.locator.write_bytes(b"{}\n")
            result = self.api.screening_status(selection)
            self.assertFalse(result.get("ok"), result)
            self.assertFalse(result.get("admitted"), result)
            self.assertEqual(result.get("screening"), None)
        finally:
            self.fixture.locator.write_bytes(original)
        self.assertEqual(self.fixture.tree_snapshot(self.fixture.repo), before)
        self.assertEqual(self.api.screening_status(selection).get("owner"), owner.get("owner"))

    def test_enrolled_owner_keeps_original_accounting_without_screening_allowance(self):
        from tests import test_project_owner_enrolled

        enrollment = test_project_owner_enrolled.ProjectOwnerEnrolledTests(methodName="runTest")
        enrolled = enrollment.umbrella()
        self.addCleanup(enrollment.doCleanups)
        scope = enrollment.scope(enrolled.record)
        result = self.api.screening_status({"project_scope": scope})
        self.assertFalse(result.get("admitted"), result)
        self.assertNotIn("deadline_monotonic", result)
        self.assertFalse(result.get("ok"), result)
        self.assertEqual(result.get("screening"), None)
        self.assertEqual(result.get("revision"), None)


@contextmanager
def _fresh_fixture(fixture_type):
    fixture = fixture_type(methodName="runTest")
    fixture.setUp()
    try:
        yield fixture
    finally:
        fixture.doCleanups()


@contextmanager
def _selected_store(api):
    with api._machine_guard() as (path, descriptor, parents):
        config = api._configuration(path, descriptor)
        context = api._ready_context(config, parents)
        with evidence._context_database(context) as db:
            yield context, db


class ScreeningCommitBarrierTests(unittest.TestCase):
    def test_final_commit_callback_rolls_back_late_scope_configuration_and_domain_changes(self):
        for operation in ("reserve", "settle"):
            for change in ("scope", "configuration", "other_table"):
                with self.subTest(operation=operation, change=change), _fresh_fixture(
                        test_project_owner_storage.ProjectOwnerStorageTests) as fixture:
                    fixture.prepare()
                    api = fixture.api
                    owner = fixture.project_owner()
                    self.assertTrue(owner.get("ok"), owner)
                    selection = {"project_scope": copy.deepcopy(fixture.scope)}
                    argument = 0
                    if operation == "settle":
                        reserved = api.reserve_screening(selection, 0)
                        self.assertTrue(reserved.get("admitted"), reserved)
                        argument = reserved["screening"]["reservation"]
                    initial = api.screening_status(selection)
                    self.assertTrue(initial.get("ok"), initial)
                    expected_revision = {"reserve": 1, "settle": 2}[operation]
                    with _selected_store(api) as (context, db):
                        database = context.database
                        original_database = list(db.iterdump())
                        original_metadata = state._metadata(db, owner["reference"]["name"])
                    locator = fixture.storage_fixture.locator
                    original_config = locator.read_bytes()
                    saved_root = fixture.project.with_name("umbrella-before-late-change")
                    pending = []
                    real_database = evidence._context_database

                    @contextmanager
                    def change_after_consumer(context, **options):
                        with real_database(context, **options) as db:
                            yield db
                            # This code runs after the consumer's inline validate,
                            # before the real manager performs before_commit.
                            if options.get("write") and context.database == database:
                                self.assertTrue(db.in_transaction)
                                metadata = state._metadata(db, owner["reference"]["name"])
                                pending.append(copy.deepcopy(metadata["screening"]))
                                self.assertEqual(pending[-1]["revision"], expected_revision)
                                if change == "scope":
                                    fixture.project.rename(saved_root)
                                    fixture.project.mkdir()
                                elif change == "configuration":
                                    locator.write_bytes(b"{}\n")
                                else:
                                    db.execute("insert into retired_identities values(?,?,?,?)",
                                        ("task", "a" * 64, "fixture:late-control-domain", None))

                    try:
                        with patch.object(evidence, "_context_database", side_effect=change_after_consumer):
                            result = getattr(api, operation + "_screening")(selection, argument)
                    finally:
                        # Restore disposable observations only; SQL must roll back itself.
                        if saved_root.exists():
                            shutil.rmtree(fixture.project)
                            saved_root.rename(fixture.project)
                        if change == "configuration":
                            locator.write_bytes(original_config)
                    self.assertEqual(len(pending), 1, pending)
                    self.assertEqual(pending[0]["revision"], expected_revision)
                    self.assertFalse(result.get("ok"), result)
                    self.assertEqual(result.get("status"), "protected", result)
                    self.assertFalse(result.get("admitted"), result)
                    self.assertNotIn("deadline_monotonic", result)
                    for key in ("owner", "reference", "created_at"):
                        self.assertEqual(result.get(key), owner[key], key)
                    with _selected_store(api) as (_, db):
                        self.assertEqual(list(db.iterdump()), original_database)
                        self.assertEqual(state._metadata(db, owner["reference"]["name"]), original_metadata)
                    after = api.screening_status(selection)
                    self.assertTrue(after.get("ok"), after)
                    self.assertEqual(after.get("screening"), initial["screening"])
                    for key in ("owner", "reference", "created_at"):
                        self.assertEqual(after.get(key), owner[key], key)

    def test_replaced_target_preserves_authenticated_history_without_current_owner(self):
        for operation in ("status", "reserve", "settle"):
            with self.subTest(operation=operation), _fresh_fixture(test_review_storage.ReviewStorageTests) as fixture:
                api = fixture.load_api()
                fixture.prepare()
                original = fixture.resolve(fixture.repo)
                self.assertTrue(original.get("ok"), original)
                selection = {"target": str(fixture.repo)}
                argument = 0
                if operation == "settle":
                    reserved = api.reserve_screening(selection, 0)
                    self.assertTrue(reserved.get("admitted"), reserved)
                    argument = reserved["screening"]["reservation"]
                initial = api.screening_status(selection)
                saved = fixture.base / "original-repository"
                fixture.repo.rename(saved)
                fixture.repo.mkdir()
                fixture.git("init", "-q")
                fixture.git("config", "user.email", "replacement@example.invalid")
                fixture.git("config", "user.name", "Replacement")
                (fixture.repo / "replacement.txt").write_text("different repository\n")
                fixture.git("add", ".")
                fixture.git("commit", "-qm", "replacement")
                before = fixture.tree_snapshot(fixture.private)
                try:
                    method = getattr(api, "screening_status" if operation == "status" else operation + "_screening")
                    result = method(selection) if operation == "status" else method(selection, argument)
                    self.assertFalse(result.get("ok"), result)
                    self.assertEqual(result.get("status"), "protected", result)
                    self.assertFalse(result.get("admitted"), result)
                    self.assertNotIn("deadline_monotonic", result)
                    self.assertEqual((result.get("screening"), result.get("revision")), (None, None))
                    identity = {key: original[key] for key in ("owner", "reference", "created_at")}
                    self.assertEqual(result.get("temporary_history"), dict(complete=True, owners=[identity]))
                    for key in identity:
                        self.assertNotIn(key, result)
                    self.assertEqual(fixture.tree_snapshot(fixture.private), before)
                finally:
                    shutil.rmtree(fixture.repo)
                    saved.rename(fixture.repo)
                after = api.screening_status(selection)
                self.assertEqual(after.get("screening"), initial["screening"])
                for key in ("owner", "reference", "created_at"):
                    self.assertEqual(after.get(key), original[key], key)


if __name__ == "__main__":
    unittest.main()
