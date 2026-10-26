"""Disposable D4 transactions exercise ownership, durability and recovery."""

import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from tests import test_onboarding as d3_tests
from runtime import onboarding
from runtime.startup import PROJECT_FILE, policy_digest


class ChangesTests(d3_tests.OnboardingTests):
    # Reuse the disposable D3 setup, not its inherited test cases.
    def setUp(self):
        super().setUp()
        from runtime import changes
        self.changes = changes
        self.lock_patch = patch.object(changes, "LOCK_ROOT", self.base / "locks")
        self.lock_patch.start()
        self.addCleanup(self.lock_patch.stop)
        (self.repo / "AGENTS.md").chmod(0o755)
        self.inspect()
        onboarding.record_plan(self.directory, self.proposal(1))

    def fingerprint(self, relative):
        path = self.repo / relative
        if not path.exists():
            return None
        return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "mode": path.stat().st_mode & 0o777}

    def request(self):
        """Representative manifest/request fixture; evidence is disposable test data."""
        plan = self.plan()
        root, git_dir, common = self.changes._checkout(self.repo)
        evidence = {"reference": "fixture:trusted-host-observation", "sha256": "e" * 64}
        manifest = {"schema_version": 1, "transaction_id": "fixture-transaction",
            "plan": {key: plan[key] for key in ("plan_id", "revision", "review_digest", "current_input_digest")},
            "checkout": {"repository_root": str(root), "git_dir": str(git_dir), "git_common_dir": str(common)},
            "pins": {"package_pins": plan["package_pins"], "toolkit_commit": plan["sources"]["declared"]["toolkit"]["commit"],
                     "sources_digest": onboarding._digest(plan["sources"])},
            "authorization_reference": "fixture:user-approval", "approved_scope": [a["id"] for a in plan["actions"]] + ["enrollment"],
            "actions": [{"id": action["id"], "group": "configuration", "resources": ["checkout"],
                "preconditions": [], "effects": [{"path": action["target"], "before": self.fingerprint(action["target"]),
                    "after": {"sha256": action["after"], "mode": 0o644} if action["kind"] == "write" else None}]
                    if action["kind"] in ("write", "delete") else [],
                "recovery": "file-preimages", "execution": {"argv": action["text"], "timeout_seconds": 5,
                    "qualification": evidence, "idempotency": None} if action["kind"] == "command" else None}
                for action in plan["actions"]],
            "enrollment": {"record": {"schema_version": 1, "project_id": "fixture", "clients": ["codex"],
                "repository_root": str(root), "git_common_dir": str(common), "policy_digest": policy_digest(onboarding.PACKAGE)},
                "before": self.fingerprint(PROJECT_FILE), "requires": [a["id"] for a in plan["actions"]],
                "qualification": {"requirements": [row["id"] for row in plan["coverage"]
                    if row["mandatory"] and row["applicability"] == "applicable"], "security_required": True}}}
        return self.bind(manifest)

    def bind(self, manifest):
        return {"schema_version": 1, "manifest": manifest,
            "approval": {"reference": manifest["authorization_reference"],
                "evidence": [{"reference": "fixture:verified-session-approval", "sha256": "a" * 64}],
                "manifest_digest": onboarding._digest(manifest)}}

    def observe(self, request):
        request = copy.deepcopy(request)
        evidence = {"reference": "fixture:trusted-host-observation", "sha256": "e" * 64}
        request["observations"] = {"manifest_digest": request["approval"]["manifest_digest"],
            "input_digest": self.changes.observation_digest(request["manifest"]),
            "qualification": {"requirements": [{"id": key, "evidence": [evidence]}
                for key in request["manifest"]["enrollment"]["qualification"]["requirements"]],
                "general_review": [evidence], "security_review": [evidence]},
            "task_reconciliation": evidence, "prior_compatibility": evidence}
        if (self.directory / "transaction.json").exists():
            request["observations"]["command_reconciliation"] = [dict(id=key, attempt_id=value["command"]["attempt_id"],
                stopped=True, evidence=[evidence]) for key, value in self.journal()["receipts"].items() if "command" in value]
        return request

    def complete(self, request):
        result = self.changes.apply_plan(self.directory, request)
        if result["exit_code"] == 2:
            result = self.changes.resume_plan(self.directory, self.observe(request))
        return result

    def journal(self):
        return json.loads((self.directory / "transaction.json").read_text())

    def replan(self, actions=None, edit=None):
        proposal = self.proposal(self.plan()["revision"])
        if actions is not None:
            proposal["actions"] = actions
            for row in proposal["coverage"]:
                row["actions"] = [action["id"] for action in actions]
        if edit:
            edit(proposal)
        return onboarding.record_plan(self.directory, proposal)

    def existing_enrollment(self, runtime=False, stale=False):
        record = self.request()["manifest"]["enrollment"]["record"]
        if runtime:
            record["runtime"] = {"schema_version": 1, "state_dir": str(self.base / "task-state")}
        if stale:
            record["policy_digest"] = "f" * 64
        (self.repo / PROJECT_FILE.parent).mkdir()
        original = json.dumps(record).encode()
        (self.repo / PROJECT_FILE).write_bytes(original)
        (self.directory / "plan.json").unlink()
        self.inspect()
        onboarding.record_plan(self.directory, self.proposal(1))
        request = self.request()
        if runtime:
            request["manifest"]["enrollment"]["record"]["runtime"] = record["runtime"]
            request = self.bind(request["manifest"])
        return record, original, request

    def command_request(self, script):
        action = self.plan()["actions"][0]
        action.update(id="command", kind="command", target="fixture-command", section=None,
                      before=None, text=[__import__("sys").executable, "-c", script], after=None)
        self.replan([action], lambda p: p["evidence"].append({"id": "command-approval", "kind": "authorization",
            "summary": "disposable command approval", "scope": "checkout", "inputs": [], "reference": "fixture"}))
        request = self.request()
        request["manifest"]["actions"][0]["effects"] = [{"path": "result.txt", "before": None,
            "after": {"sha256": hashlib.sha256(b"result").hexdigest(), "mode": 0o644}}]
        return self.bind(request["manifest"])

    def test_configuration_waits_for_current_qualification_and_returns_digest(self):
        request = self.request()
        stale = self.observe(request)
        result = self.changes.apply_plan(self.directory, request)
        self.assertEqual(result["exit_code"], 2, result)
        self.assertEqual(result["completed"], ["write-rules"])
        self.assertFalse((self.repo / PROJECT_FILE).exists())
        self.assertEqual(result["observation_input_digest"], self.changes.observation_digest(request["manifest"]))
        self.assertEqual(self.changes.resume_plan(self.directory, stale)["exit_code"], 1)
        self.assertEqual(self.changes.resume_plan(self.directory, self.observe(request))["exit_code"], 0)
        self.assertEqual(len(self.journal()["observations"]), 1)

    def test_same_worktree_lock_is_independent_of_plan_directory(self):
        request = self.request()
        other = self.base / "second-plan"
        other.mkdir(mode=0o700)
        for name in ("plan.json", "catalog.md"):
            (other / name).write_bytes((self.directory / name).read_bytes())
            (other / name).chmod(0o600)
        git_dir = Path(request["manifest"]["checkout"]["git_dir"])
        with self.changes._worktree_lock(git_dir):
            result = self.changes.apply_plan(other, request)
            self.assertEqual(result["exit_code"], 1)
            self.assertIn("busy", result["blocked"][0]["reason"])
        self.assertFalse((other / "transaction.json").exists())
        self.assertEqual((self.repo / "AGENTS.md").read_text(), "product rules\nlegacy process\n")

    def test_linked_worktree_has_a_distinct_transaction_lock(self):
        linked = self.base / "linked"
        self.git("worktree", "add", "--detach", str(linked), "HEAD")
        root, git_dir, common = self.changes._checkout(linked)
        self.assertEqual(common, self.changes._checkout(self.repo)[2])
        self.assertNotEqual(git_dir, self.changes._checkout(self.repo)[1])
        with self.changes._worktree_lock(git_dir):
            result = self.changes.apply_plan(self.directory, self.request())
        self.assertEqual(result["exit_code"], 2, result)

    def test_external_edit_during_temp_write_is_preserved(self):
        request = self.request()
        edited = False
        def edit(stage):
            nonlocal edited
            if stage == "temp_fsync" and not edited:
                edited = True
                (self.repo / "AGENTS.md").write_text("external editor\n")
        with patch.object(self.changes, "_checkpoint", side_effect=edit):
            result = self.changes.apply_plan(self.directory, request)
        self.assertEqual(result["exit_code"], 2, result)
        self.assertEqual((self.repo / "AGENTS.md").read_text(), "external editor\n")

    def test_stale_plan_and_unrelated_inputs_reject_before_mutation(self):
        request = self.request()
        (self.repo / "README.md").write_text("unrelated edit")
        self.assertEqual(self.changes.apply_plan(self.directory, request)["exit_code"], 1)
        self.assertFalse((self.directory / "transaction.json").exists())
        self.assertFalse((self.repo / PROJECT_FILE).exists())

    def test_missing_command_contract_stays_pending(self):
        request = self.command_request("from pathlib import Path; Path('result.txt').write_text('result')")
        request["manifest"]["actions"][0]["execution"]["qualification"] = None
        result = self.changes.apply_plan(self.directory, self.bind(request["manifest"]))
        self.assertEqual(result["exit_code"], 2, result)
        self.assertFalse((self.repo / "result.txt").exists())

    def test_uncertain_command_never_blindly_replays(self):
        request = self.command_request("from pathlib import Path; Path('result.txt').write_text('result')")
        with patch.object(self.changes, "_checkpoint", side_effect=lambda s: (_ for _ in ()).throw(RuntimeError("crash")) if s == "command_started" else None):
            with self.assertRaises(RuntimeError):
                self.changes.apply_plan(self.directory, request)
        result = self.changes.resume_plan(self.directory, request)
        self.assertEqual(result["exit_code"], 2, result)
        self.assertFalse((self.repo / "result.txt").exists())
        self.assertIn("uncertain", result["blocked"][0]["reason"])

    def test_command_postimages_reconcile_after_crash(self):
        request = self.command_request("from pathlib import Path; Path('result.txt').write_text('result')")
        with patch.object(self.changes, "_checkpoint", side_effect=lambda s: (_ for _ in ()).throw(RuntimeError("crash")) if s == "command_finished" else None):
            with self.assertRaises(RuntimeError):
                self.changes.apply_plan(self.directory, request)
        result = self.changes.resume_plan(self.directory, self.observe(request))
        self.assertEqual(result["exit_code"], 0, result)
        self.assertEqual(self.changes.rollback_plan(self.directory, request)["exit_code"], 0)
        self.assertFalse((self.repo / "result.txt").exists())

    def test_mixed_write_delete_restores_reverse_dependency_order(self):
        write = self.plan()["actions"][0]
        delete = dict(write, id="delete-readme", dependencies=["write-rules"], kind="delete", target="README.md",
            section=None, before=hashlib.sha256((self.repo / "README.md").read_bytes()).hexdigest(), text=None, after="absent")
        self.replan([write, delete])
        request = self.request()
        self.assertEqual(self.complete(request)["exit_code"], 0)
        self.assertFalse((self.repo / "README.md").exists())
        self.assertEqual(self.changes.rollback_plan(self.directory, request)["exit_code"], 0)
        self.assertEqual((self.repo / "README.md").read_text(), "product\n")

    def test_existing_enrollment_deactivates_first_and_restores_last(self):
        _, original, request = self.existing_enrollment()
        result = self.changes.apply_plan(self.directory, request)
        self.assertEqual(result["exit_code"], 2, result)
        self.assertFalse((self.repo / PROJECT_FILE).exists())
        self.assertEqual(self.changes.resume_plan(self.directory, self.observe(request))["exit_code"], 0)
        result = self.changes.rollback_plan(self.directory, request)
        self.assertEqual(result["exit_code"], 2, result)
        self.assertFalse((self.repo / PROJECT_FILE).exists())
        self.assertEqual((self.repo / "AGENTS.md").read_text(), "product rules\nlegacy process\n")
        self.assertEqual(self.changes.rollback_plan(self.directory, self.observe(request))["exit_code"], 0)
        self.assertEqual((self.repo / PROJECT_FILE).read_bytes(), original)

    def test_stale_prior_enrollment_remains_inactive_after_rollback(self):
        _, _, request = self.existing_enrollment(stale=True)
        self.assertEqual(self.complete(request)["exit_code"], 0)
        self.assertEqual(self.changes.rollback_plan(self.directory, request)["exit_code"], 2)
        result = self.changes.rollback_plan(self.directory, self.observe(request))
        self.assertEqual(result["exit_code"], 2, result)
        self.assertFalse((self.repo / PROJECT_FILE).exists())
        self.assertIn("stale", result["blocked"][0]["reason"])

    def test_external_enrollment_change_blocks_configuration_rollback(self):
        request = self.request()
        self.assertEqual(self.complete(request)["exit_code"], 0)
        (self.repo / PROJECT_FILE).write_text("external enrollment")
        result = self.changes.rollback_plan(self.directory, request)
        self.assertEqual(result["exit_code"], 2, result)
        self.assertEqual((self.repo / PROJECT_FILE).read_text(), "external enrollment")
        self.assertEqual((self.repo / "AGENTS.md").read_text(), "product rules\nnew process\n")

    def test_active_task_writers_preserve_enrollment_and_configuration(self):
        from runtime import state
        record, original, request = self.existing_enrollment(runtime=True)
        scope = self.changes._record(record, self.plan())
        state.start_task(scope, {"client": "codex", "session_id": "fixture", "task_id": "writing",
            "scope_ref": "fixture", "mode": "editable", "decision_ref": "fixture"})
        result = self.changes.apply_plan(self.directory, self.observe(request))
        self.assertEqual(result["exit_code"], 2, result)
        self.assertEqual((self.repo / PROJECT_FILE).read_bytes(), original)
        self.assertEqual((self.repo / "AGENTS.md").read_text(), "product rules\nlegacy process\n")
        self.assertIn("writers", result["blocked"][0]["reason"])

    def test_unresolved_decision_blocks_only_dependent_actions(self):
        write = self.plan()["actions"][0]
        second = dict(write, id="write-readme", target="README.md", before=hashlib.sha256(b"product\n").hexdigest(),
            text="new readme\n", after=hashlib.sha256(b"new readme\n").hexdigest())
        def decision(proposal):
            proposal["actions"][0]["decision_ids"] = ["choice"]
            proposal["decisions"] = [{"id": "choice", "rule": "policy:01-project-scope", "source": "AGENTS.md",
                "scope": "checkout", "options": ["preserve", "replace"], "recommendation": "preserve", "selected": None,
                "disposition": "pending", "provenance": "unanswered fixture choice", "evidence": [],
                "affected_actions": ["write-rules"], "invalidate_on": ["AGENTS.md"], "conflict": True, "mode": "decide"}]
        self.replan([write, second], decision)
        request = self.request()
        result = self.changes.apply_plan(self.directory, request)
        self.assertEqual(result["exit_code"], 2, result)
        self.assertEqual(result["completed"], ["write-readme"])
        self.assertEqual((self.repo / "AGENTS.md").read_text(), "product rules\nlegacy process\n")
        self.assertEqual((self.repo / "README.md").read_text(), "new readme\n")

    def test_process_death_leaves_reconcilable_owned_temporaries(self):
        import sys
        for boundary in ("temp_write", "temp_fsync", "rename", "parent_fsync", "outcome", "state"):
            with self.subTest(boundary=boundary):
                if (self.directory / "transaction.json").exists():
                    self.changes.rollback_plan(self.directory, request)
                    (self.directory / "transaction.json").unlink()
                request = self.request()
                script = ("import json,os,sys; from pathlib import Path; from runtime import changes; "
                    + "changes.LOCK_ROOT=Path(" + repr(str(self.base / "locks")) + "); "
                    + "changes._checkpoint=lambda stage: os._exit(91) if stage==" + repr(boundary) + " else None; "
                    + "changes.apply_plan(" + repr(str(self.directory)) + ",json.load(sys.stdin))")
                child = subprocess.run([sys.executable, "-B", "-c", script], cwd=onboarding.PACKAGE,
                    input=json.dumps(request).encode(), capture_output=True, timeout=10)
                self.assertEqual(child.returncode, 91, child.stderr)
                result = self.changes.resume_plan(self.directory, request)
                if result["exit_code"] == 2:
                    result = self.changes.resume_plan(self.directory, self.observe(request))
                self.assertEqual(result["exit_code"], 0, result)
                self.assertFalse(list(self.repo.glob(".d4-*")))
                self.assertEqual(self.changes.rollback_plan(self.directory, request)["exit_code"], 0)

    def test_generic_enrollment_effect_must_match_final_approved_record(self):
        request = self.request()
        request["manifest"]["actions"][0]["effects"][0]["path"] = str(PROJECT_FILE)
        self.assertEqual(self.changes.apply_plan(self.directory, self.bind(request["manifest"]))["exit_code"], 1)
        self.assertFalse((self.repo / PROJECT_FILE).exists())

    def test_backup_and_target_links_are_rejected(self):
        request = self.request()
        backup = self.directory / "backup-0-0"
        backup.symlink_to(self.repo / "AGENTS.md")
        result = self.changes.apply_plan(self.directory, request)
        self.assertEqual(result["exit_code"], 1, result)
        self.assertEqual((self.repo / "AGENTS.md").read_text(), "product rules\nlegacy process\n")

    def test_unknown_command_effects_and_shared_resources_stay_pending(self):
        request = self.command_request("from pathlib import Path; Path('result.txt').write_text('result')")
        for key, value in (("effects", []), ("resources", ["global"]), ("recovery", "manual")):
            with self.subTest(key=key):
                changed = copy.deepcopy(request["manifest"])
                changed["actions"][0][key] = value
                if (self.directory / "transaction.json").exists():
                    (self.directory / "transaction.json").unlink()
                result = self.changes.apply_plan(self.directory, self.bind(changed))
                self.assertEqual(result["exit_code"], 2, result)
                self.assertFalse((self.repo / "result.txt").exists())

    def test_exact_d3_enrollment_proposal_is_installed_only_last(self):
        record = self.request()["manifest"]["enrollment"]["record"]
        write = self.plan()["actions"][0]
        text = json.dumps(record, indent=2)
        enrollment = dict(write, id="activate-project", dependencies=["write-rules"], target=str(PROJECT_FILE),
            section=None, before="absent", text=text, after=hashlib.sha256(text.encode()).hexdigest())
        self.replan([write, enrollment])
        request = self.request()
        result = self.changes.apply_plan(self.directory, request)
        self.assertEqual(result["exit_code"], 2, result)
        self.assertFalse((self.repo / PROJECT_FILE).exists())
        result = self.changes.resume_plan(self.directory, self.observe(request))
        self.assertEqual(result["exit_code"], 0, result)
        self.assertEqual((self.repo / PROJECT_FILE).read_text(), text)
        self.assertEqual(self.changes.rollback_plan(self.directory, request)["exit_code"], 0)

    def test_owned_command_holds_worktree_lock_without_journal_lock(self):
        request = self.command_request("from pathlib import Path; Path('result.txt').write_text('result')")
        popen = subprocess.Popen
        def launch(*args, **kwargs):
            if args and args[0] == request["manifest"]["actions"][0]["execution"]["argv"]:
                with self.assertRaisesRegex(Exception, "busy"):
                    with self.changes._worktree_lock(Path(request["manifest"]["checkout"]["git_dir"])):
                        pass
                with self.changes._lock(self.directory / ".d4-journal.lock"):
                    pass
            return popen(*args, **kwargs)
        with patch.object(self.changes.subprocess, "Popen", side_effect=launch):
            result = self.changes.apply_plan(self.directory, request)
        self.assertEqual(result["exit_code"], 2, result)
        self.assertEqual((self.repo / "result.txt").read_text(), "result")

    def test_crash_during_prior_enrollment_restore_reconciles_ownership(self):
        _, original, request = self.existing_enrollment()
        self.assertEqual(self.complete(request)["exit_code"], 0)
        self.assertEqual(self.changes.rollback_plan(self.directory, request)["exit_code"], 2)
        request = self.observe(request)
        with patch.object(self.changes, "_checkpoint", side_effect=lambda stage: (_ for _ in ()).throw(RuntimeError("crash")) if stage == "rename" else None):
            with self.assertRaises(RuntimeError):
                self.changes.rollback_plan(self.directory, request)
        self.assertEqual((self.repo / PROJECT_FILE).read_bytes(), original)
        result = self.changes.rollback_plan(self.directory, self.bind(request["manifest"]))
        self.assertEqual(result["exit_code"], 0, result)
        self.assertEqual((self.repo / PROJECT_FILE).read_bytes(), original)

    def test_unapproved_optional_action_does_not_gate_mandatory_enrollment(self):
        write = self.plan()["actions"][0]
        optional = dict(write, id="optional-readme", target="README.md", before=hashlib.sha256(b"product\n").hexdigest(),
            text="optional readme\n", after=hashlib.sha256(b"optional readme\n").hexdigest())
        def coverage(proposal):
            for row in proposal["coverage"]:
                row["actions"] = ["write-rules"] if row["mandatory"] else ["optional-readme"]
        self.replan([write, optional], coverage)
        request = self.request()
        request["manifest"]["approved_scope"] = ["write-rules", "enrollment"]
        request["manifest"]["enrollment"]["requires"] = ["write-rules"]
        request = self.bind(request["manifest"])
        self.assertEqual(self.changes.apply_plan(self.directory, request)["exit_code"], 2)
        result = self.changes.resume_plan(self.directory, self.observe(request))
        self.assertEqual(result["exit_code"], 2, result)
        self.assertTrue((self.repo / PROJECT_FILE).exists())
        self.assertEqual((self.repo / "README.md").read_text(), "product\n")
        self.assertEqual([row["id"] for row in result["blocked"]], ["optional-readme"])

    def test_changed_restored_configuration_keeps_prior_enrollment_inactive(self):
        _, _, request = self.existing_enrollment()
        self.assertEqual(self.complete(request)["exit_code"], 0)
        self.assertEqual(self.changes.rollback_plan(self.directory, request)["exit_code"], 2)
        (self.repo / "AGENTS.md").write_text("user edited restored configuration\n")
        result = self.changes.rollback_plan(self.directory, self.observe(request))
        self.assertEqual(result["exit_code"], 2, result)
        self.assertFalse((self.repo / PROJECT_FILE).exists())
        self.assertEqual((self.repo / "AGENTS.md").read_text(), "user edited restored configuration\n")

    def test_cancelled_reconciled_writer_allows_existing_enrollment_update(self):
        from runtime import state
        record, _, request = self.existing_enrollment(runtime=True)
        scope = self.changes._record(record, self.plan())
        identity = {"client": "codex", "session_id": "fixture", "task_id": "stopped", "scope_ref": "fixture"}
        started = state.start_task(scope, dict(identity, mode="editable", decision_ref="fixture"))
        state.update_task(scope, dict(identity, expected_revision=started["task"]["revision"],
            state="cancelled", reason="writer stopped", reference="fixture:stopped"))
        result = self.changes.apply_plan(self.directory, self.observe(request))
        self.assertEqual(result["exit_code"], 2, result)
        self.assertFalse((self.repo / PROJECT_FILE).exists())
        result = self.changes.resume_plan(self.directory, self.observe(request))
        self.assertEqual(result["exit_code"], 0, result)

    def test_proven_idempotency_contract_permits_uncertain_command_resume(self):
        request = self.command_request("from pathlib import Path; Path('result.txt').write_text('result')")
        request["manifest"]["actions"][0]["execution"]["idempotency"] = {
            "reference": "fixture:coordinator-verified-idempotent-contract", "sha256": "d" * 64}
        request = self.bind(request["manifest"])
        with patch.object(self.changes, "_checkpoint", side_effect=lambda stage: (_ for _ in ()).throw(RuntimeError("crash")) if stage == "command_started" else None):
            with self.assertRaises(RuntimeError):
                self.changes.apply_plan(self.directory, request)
        result = self.changes.resume_plan(self.directory, self.observe(request))
        self.assertEqual(result["exit_code"], 2, result)
        self.assertEqual((self.repo / "result.txt").read_text(), "result")
        self.assertEqual(self.changes.resume_plan(self.directory, self.observe(request))["exit_code"], 0)

    def test_null_evidence_entries_reject_at_all_required_boundaries(self):
        request = self.request()
        invalid = copy.deepcopy(request)
        invalid["approval"]["evidence"] = [None]
        self.assertEqual(self.changes.apply_plan(self.directory, invalid)["exit_code"], 1)
        self.assertFalse((self.directory / "transaction.json").exists())
        self.assertEqual(self.changes.apply_plan(self.directory, request)["exit_code"], 2)
        for field in ("requirements", "general_review", "security_review"):
            with self.subTest(field=field):
                invalid = self.observe(request)
                proof = invalid["observations"]["qualification"]
                if field == "requirements":
                    proof[field][0]["evidence"] = [None]
                else:
                    proof[field] = [None]
                self.assertEqual(self.changes.resume_plan(self.directory, invalid)["exit_code"], 1)
                self.assertFalse((self.repo / PROJECT_FILE).exists())

    def nested_request(self):
        action = dict(self.plan()["actions"][0], target="docs/design/architecture.md", before="absent")
        self.replan([action])
        return self.request()

    def test_nested_write_creates_owned_parents_and_removes_them_on_rollback(self):
        request = self.nested_request()
        self.assertEqual(self.complete(request)["exit_code"], 0)
        self.assertTrue((self.repo / "docs/design/architecture.md").exists())
        self.assertEqual(self.changes.rollback_plan(self.directory, request)["exit_code"], 0)
        self.assertFalse((self.repo / "docs").exists())

    def test_nested_parent_crash_gap_preserves_uncertain_directory(self):
        request = self.nested_request()
        with patch.object(self.changes, "_checkpoint", side_effect=lambda stage: (_ for _ in ()).throw(RuntimeError("crash")) if stage == "directory_created" else None):
            with self.assertRaises(RuntimeError):
                self.changes.apply_plan(self.directory, request)
        result = self.changes.resume_plan(self.directory, request)
        self.assertEqual(result["exit_code"], 2, result)
        result = self.changes.rollback_plan(self.directory, request)
        self.assertEqual(result["exit_code"], 0, result)
        self.assertTrue((self.repo / "docs").is_dir())
        self.assertIn("docs", result["retained_directories"])

    def test_direct_rollback_after_parent_creation_crash_reports_retained_metadata(self):
        request = self.nested_request()
        with patch.object(self.changes, "_checkpoint", side_effect=lambda stage: (_ for _ in ()).throw(RuntimeError("crash")) if stage == "directory_created" else None):
            with self.assertRaises(RuntimeError):
                self.changes.apply_plan(self.directory, request)
        self.assertEqual(self.journal()["directories"]["docs"]["status"], "prepared")
        result = self.changes.rollback_plan(self.directory, request)
        self.assertEqual(result["exit_code"], 0, result)
        self.assertTrue((self.repo / "docs").is_dir())
        self.assertEqual(result["retained_directories"], ["docs"])
        self.assertEqual(self.journal()["directories"]["docs"]["status"], "retained")
        self.assertIsNone(self.journal()["directories"]["docs"]["inode"])

    def test_direct_rollback_records_absent_prepared_parent_as_removed(self):
        request = self.nested_request()
        with patch.object(self.changes, "_checkpoint", side_effect=lambda stage: (_ for _ in ()).throw(RuntimeError("crash")) if stage == "directory_created" else None):
            with self.assertRaises(RuntimeError):
                self.changes.apply_plan(self.directory, request)
        (self.repo / "docs").rmdir()
        result = self.changes.rollback_plan(self.directory, request)
        self.assertEqual(result["exit_code"], 0, result)
        self.assertEqual(result["retained_directories"], [])
        self.assertEqual(self.journal()["directories"]["docs"]["status"], "removed")

    def test_nested_rollback_preserves_preexisting_and_nonempty_directories(self):
        (self.repo / "docs").mkdir()
        request = self.nested_request()
        self.assertEqual(self.complete(request)["exit_code"], 0)
        (self.repo / "docs/design/user.txt").write_text("user content")
        result = self.changes.rollback_plan(self.directory, request)
        self.assertEqual(result["exit_code"], 0, result)
        self.assertTrue((self.repo / "docs").is_dir())
        self.assertEqual((self.repo / "docs/design/user.txt").read_text(), "user content")
        self.assertIn("docs/design", result["retained_directories"])

    def test_prepared_enrollment_resume_rechecks_new_task_writer(self):
        from runtime import state
        record, original, request = self.existing_enrollment(runtime=True)
        replace = self.changes._replace
        def stop_before_deactivation(root, relative, raw, fingerprint, expected, *args):
            if relative == str(PROJECT_FILE) and fingerprint is None:
                raise RuntimeError("crash before deactivation")
            return replace(root, relative, raw, fingerprint, expected, *args)
        with patch.object(self.changes, "_replace", side_effect=stop_before_deactivation):
            with self.assertRaises(RuntimeError):
                self.changes.apply_plan(self.directory, self.observe(request))
        scope = self.changes._record(record, self.plan())
        state.start_task(scope, {"client": "codex", "session_id": "new", "task_id": "writer",
            "scope_ref": "fixture", "mode": "editable", "decision_ref": "fixture"})
        result = self.changes.resume_plan(self.directory, self.observe(request))
        self.assertEqual(result["exit_code"], 2, result)
        self.assertEqual((self.repo / PROJECT_FILE).read_bytes(), original)
        self.assertEqual((self.repo / "AGENTS.md").read_text(), "product rules\nlegacy process\n")

    def test_rollback_rechecks_writer_before_owned_enrollment_deactivation(self):
        from runtime import state
        record, _, request = self.existing_enrollment(runtime=True)
        self.changes.apply_plan(self.directory, self.observe(request))
        self.assertEqual(self.changes.resume_plan(self.directory, self.observe(request))["exit_code"], 0)
        active = (self.repo / PROJECT_FILE).read_bytes()
        scope = self.changes._record(record, self.plan())
        state.start_task(scope, {"client": "codex", "session_id": "new", "task_id": "writer",
            "scope_ref": "fixture", "mode": "editable", "decision_ref": "fixture"})
        result = self.changes.rollback_plan(self.directory, self.observe(request))
        self.assertEqual(result["exit_code"], 2, result)
        self.assertEqual((self.repo / PROJECT_FILE).read_bytes(), active)
        self.assertEqual((self.repo / "AGENTS.md").read_text(), "product rules\nnew process\n")

    def optional_request(self, pending_decision=False):
        write = self.plan()["actions"][0]
        optional = dict(write, id="optional-readme", target="README.md", before=hashlib.sha256(b"product\n").hexdigest(),
            text="optional readme\n", after=hashlib.sha256(b"optional readme\n").hexdigest())
        def coverage(proposal):
            for row in proposal["coverage"]:
                row["actions"] = ["write-rules"] if row["mandatory"] else ["optional-readme"]
                if not row["mandatory"] and not pending_decision:
                    row.update(outcome="blocked", blocker="optional prerequisite", resumption="optional manual step")
            if pending_decision:
                proposal["actions"][1]["decision_ids"] = ["optional-choice"]
                proposal["decisions"] = [{"id": "optional-choice", "rule": "policy:01-project-scope", "source": "README.md",
                    "scope": "checkout", "options": ["preserve", "replace"], "recommendation": "preserve", "selected": None,
                    "disposition": "pending", "provenance": "unanswered optional choice", "evidence": [],
                    "affected_actions": ["optional-readme"], "invalidate_on": ["README.md"], "conflict": True, "mode": "decide"}]
        self.replan([write, optional], coverage)
        request = self.request()
        request["manifest"]["enrollment"]["requires"] = ["write-rules"]
        return self.bind(request["manifest"])

    def test_optional_coverage_blocker_does_not_gate_mandatory_activation(self):
        request = self.optional_request()
        self.assertEqual(self.changes.apply_plan(self.directory, request)["exit_code"], 2)
        result = self.changes.resume_plan(self.directory, self.observe(request))
        self.assertEqual(result["exit_code"], 2, result)
        self.assertTrue((self.repo / PROJECT_FILE).exists())
        self.assertEqual([item["id"] for item in result["blocked"]], ["optional-readme"])

    def test_optional_pending_decision_does_not_gate_mandatory_activation(self):
        request = self.optional_request(pending_decision=True)
        self.assertEqual(self.changes.apply_plan(self.directory, request)["exit_code"], 2)
        result = self.changes.resume_plan(self.directory, self.observe(request))
        self.assertEqual(result["exit_code"], 2, result)
        self.assertTrue((self.repo / PROJECT_FILE).exists())
        self.assertEqual([item["id"] for item in result["blocked"]], ["optional-readme"])

    def test_completed_command_requires_exact_attempt_lifecycle_proof(self):
        request = self.command_request("from pathlib import Path; Path('result.txt').write_text('result')")
        result = self.changes.apply_plan(self.directory, request)
        self.assertEqual(result["exit_code"], 2, result)
        self.assertFalse(result["completed"])
        result = self.changes.resume_plan(self.directory, request)
        self.assertEqual(result["exit_code"], 2, result)
        self.assertIn("lifecycle", str(result["blocked"]))
        self.assertEqual(self.changes.resume_plan(self.directory, self.observe(request))["exit_code"], 0)

    def orphan_command_case(self, descendant_closes_lock):
        import sys
        import time
        child = "from pathlib import Path; import time; Path('started.txt').write_text('started'); time.sleep(1.5); Path('result.txt').write_text('result')"
        program = ("import subprocess,sys,time; subprocess.Popen([sys.executable,'-c'," + repr(child) +
                   "],close_fds=True); time.sleep(0.15)") if descendant_closes_lock else child
        request = self.command_request(program)
        request["manifest"]["actions"][0]["effects"].append({"path": "started.txt", "before": None,
            "after": {"sha256": hashlib.sha256(b"started").hexdigest(), "mode": 0o644}})
        request = self.bind(request["manifest"])
        script = ("import json,sys; from pathlib import Path; from runtime import changes; changes.LOCK_ROOT=Path("
            + repr(str(self.base / "locks")) + "); changes.apply_plan(" + repr(str(self.directory)) + ",json.load(sys.stdin))")
        helper = subprocess.Popen([sys.executable, "-B", "-c", script], cwd=onboarding.PACKAGE,
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            helper.stdin.write(json.dumps(request).encode())
            helper.stdin.close()
            deadline = time.monotonic() + 4
            while not (self.repo / "started.txt").exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue((self.repo / "started.txt").exists())
            helper.kill()
            helper.wait(timeout=2)
            if descendant_closes_lock:
                time.sleep(0.25)
            result = self.changes.rollback_plan(self.directory, request)
            self.assertIn(result["exit_code"], (1, 2), result)
            self.assertFalse((self.repo / "result.txt").exists())
            other = self.base / "another-plan"
            other.mkdir(mode=0o700)
            for name in ("plan.json", "catalog.md"):
                (other / name).write_bytes((self.directory / name).read_bytes())
                (other / name).chmod(0o600)
            result = self.changes.apply_plan(other, request)
            self.assertIn(result["exit_code"], (1, 2), result)
            if descendant_closes_lock:
                self.assertEqual(result["exit_code"], 2, result)
                self.assertIn("owner", str(result["blocked"]))
            while not (self.repo / "result.txt").exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual((self.repo / "result.txt").read_text(), "result")
            time.sleep(0.05)
            result = self.changes.rollback_plan(self.directory, request)
            self.assertEqual(result["exit_code"], 2, result)
            self.assertIn("lifecycle", str(result["blocked"]))
            result = self.changes.rollback_plan(self.directory, self.observe(request))
            self.assertEqual(result["exit_code"], 0, result)
            self.assertFalse((self.repo / "result.txt").exists())
            self.assertFalse((self.repo / "started.txt").exists())
        finally:
            if helper.poll() is None:
                helper.kill()
                helper.wait(timeout=2)

    def test_parent_death_does_not_allow_rollback_while_owned_command_survives(self):
        self.orphan_command_case(descendant_closes_lock=False)

    def test_closed_fd_descendant_keeps_cross_plan_command_owner_blocked(self):
        self.orphan_command_case(descendant_closes_lock=True)

    def test_lifecycle_proof_rejects_missing_evidence_and_wrong_attempt(self):
        request = self.command_request("from pathlib import Path; Path('result.txt').write_text('result')")
        self.assertEqual(self.changes.apply_plan(self.directory, request)["exit_code"], 2)
        observed = self.observe(request)
        observed["observations"]["command_reconciliation"][0]["evidence"] = [None]
        self.assertEqual(self.changes.resume_plan(self.directory, observed)["exit_code"], 1)
        observed = self.observe(request)
        observed["observations"]["command_reconciliation"][0]["attempt_id"] = "0" * 32
        self.assertEqual(self.changes.resume_plan(self.directory, observed)["exit_code"], 2)
        self.assertFalse((self.repo / PROJECT_FILE).exists())
        self.assertEqual(self.changes.resume_plan(self.directory, self.observe(request))["exit_code"], 0)

    def test_apply_enrolls_last_and_safe_rerun_rollback_restores_mode(self):
        (self.repo / "AGENTS.md").chmod(0o755)
        request = self.request()
        result = self.complete(request)
        self.assertEqual(result["exit_code"], 0, result)
        self.assertEqual(result["state"], "applied")
        self.assertEqual((self.repo / "AGENTS.md").read_text(), "product rules\nnew process\n")
        self.assertTrue((self.repo / PROJECT_FILE).exists())
        self.assertEqual(self.changes.apply_plan(self.directory, request)["exit_code"], 0)
        self.assertEqual(self.changes.rollback_plan(self.directory, request)["exit_code"], 0)
        self.assertEqual((self.repo / "AGENTS.md").read_text(), "product rules\nlegacy process\n")
        self.assertEqual((self.repo / "AGENTS.md").stat().st_mode & 0o777, 0o755)
        self.assertFalse((self.repo / PROJECT_FILE).exists())
        self.assertEqual(self.changes.rollback_plan(self.directory, request)["exit_code"], 0)
        self.assertEqual((self.directory / "transaction.json").stat().st_mode & 0o777, 0o600)

    def test_untrusted_d3_authorization_is_insufficient(self):
        request = self.request()
        request["approval"]["evidence"] = []
        result = self.changes.apply_plan(self.directory, request)
        self.assertEqual(result["exit_code"], 2)
        self.assertFalse((self.repo / PROJECT_FILE).exists())
        self.assertEqual((self.repo / "AGENTS.md").read_text(), "product rules\nlegacy process\n")

    def test_bound_manifest_rejects_changed_content(self):
        request = self.request()
        request["manifest"]["actions"][0]["effects"][0]["after"]["mode"] = 0o755
        self.assertEqual(self.changes.apply_plan(self.directory, request)["exit_code"], 1)

    def test_user_edit_is_preserved_during_resume_and_rollback(self):
        request = self.request()
        self.assertEqual(self.complete(request)["exit_code"], 0)
        (self.repo / "AGENTS.md").write_text("user edit\n")
        self.assertEqual(self.changes.resume_plan(self.directory, request)["exit_code"], 2)
        self.assertEqual(self.changes.rollback_plan(self.directory, request)["exit_code"], 2)
        self.assertEqual((self.repo / "AGENTS.md").read_text(), "user edit\n")

    def test_crash_boundaries_reconcile_without_lost_original(self):
        for boundary in ("backup", "prepared", "temp_write", "temp_fsync", "rename", "parent_fsync", "outcome", "state"):
            with self.subTest(boundary=boundary):
                if (self.directory / "transaction.json").exists():
                    self.changes.rollback_plan(self.directory, request)
                    (self.directory / "transaction.json").unlink()
                request = self.request()
                fired = False
                def crash(stage):
                    nonlocal fired
                    if stage == boundary and not fired:
                        fired = True
                        raise RuntimeError("injected crash")
                with patch.object(self.changes, "_checkpoint", side_effect=crash):
                    with self.assertRaises(RuntimeError):
                        self.changes.apply_plan(self.directory, request)
                self.assertTrue(fired)
                result = self.changes.resume_plan(self.directory, request)
                if result["exit_code"] == 2:
                    result = self.changes.resume_plan(self.directory, self.observe(request))
                self.assertEqual(result["exit_code"], 0, result)
                self.assertEqual(self.changes.rollback_plan(self.directory, request)["exit_code"], 0)
                self.assertEqual((self.repo / "AGENTS.md").read_text(), "product rules\nlegacy process\n")


# Inherited D3 tests are already covered by test_onboarding.py.
for _name in list(vars(d3_tests.OnboardingTests)):
    if _name.startswith("test_") and _name not in vars(ChangesTests):
        setattr(ChangesTests, _name, None)
