"""D3/D4 freshness for an ignored action target already in the reviewed snapshot."""

import hashlib
import unittest
from unittest.mock import patch

from tests import test_changes
from tests import test_onboarding as d3_tests


class LegacyIgnoredTargetFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.fixture = d3_tests.OnboardingTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.git("rm", "--cached", "-q", "--", "AGENTS.md")
        exclude = self.fixture.repo / ".git" / "info" / "exclude"
        exclude.write_text(exclude.read_text() + "\n/AGENTS.md\n/ignored/\n")
        unrelated = self.fixture.repo / "ignored" / "unrelated.txt"
        unrelated.parent.mkdir()
        unrelated.write_text("not an action target\n")

    def test_recorded_ignored_action_target_stays_fresh_then_edit_invalidates(self):
        f = self.fixture
        f.inspect()
        report = f.module().record_plan(f.directory, f.proposal(1))
        self.assertEqual(report["status"], "ready_for_review", report)
        fingerprints = f.plan()["identity"]["fingerprints"]
        self.assertIn("AGENTS.md", fingerprints)
        self.assertNotIn("ignored/unrelated.txt", fingerprints)

        report = f.inspect()
        self.assertEqual(report["status"], "ready_for_review", report)
        (f.repo / "AGENTS.md").write_text("product rules\ncustom process\n")
        report = f.inspect()
        self.assertEqual(report["status"], "stale", report)
        self.assertTrue(any(row["scope"] == "AGENTS.md" for row in report["blockers"]))

    def test_new_git_visible_file_between_inspect_and_record_stays_stale(self):
        f = self.fixture
        f.inspect()
        (f.repo / "newly-visible.txt").write_text("not an approved action target\n")

        report = f.module().record_plan(f.directory, f.proposal(1))
        self.assertEqual(report["status"], "stale", report)
        self.assertNotIn("newly-visible.txt", f.plan()["identity"]["fingerprints"])

    def test_revising_ignored_target_to_readme_keeps_old_target_freshness(self):
        f = self.fixture
        f.inspect()
        first = f.module().record_plan(f.directory, f.proposal(1))
        self.assertEqual(first["status"], "ready_for_review", first)

        text = "product\nrevised readme\n"
        proposal = f.proposal(f.plan()["revision"])
        proposal["actions"][0].update(target="README.md", section=None,
            before=f.module()._fingerprint(f.repo, "README.md")["sha256"], text=text,
            after=hashlib.sha256(text.encode()).hexdigest(), preservation_exceptions=[])
        revised = f.module().record_plan(f.directory, proposal)
        self.assertEqual(revised["status"], "ready_for_review", revised)
        self.assertIn("AGENTS.md", f.plan()["identity"]["fingerprints"])

        (f.repo / "AGENTS.md").write_text("product rules\ncustom process\n")
        report = f.inspect()
        self.assertEqual(report["status"], "stale", report)
        self.assertTrue(any(row["scope"] == "AGENTS.md" for row in report["blockers"]))


class IgnoredTargetFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_changes.ScopedChangesTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.git("rm", "--cached", "-q", "--", "AGENTS.md")
        exclude = self.fixture.repo / ".git" / "info" / "exclude"
        exclude.write_text(exclude.read_text() + "\n/AGENTS.md\n")

    def request(self):
        f = self.fixture
        request = f.scoped_request()
        snapshot = f.plan()["assessments"]["repositories"][0]["identity"]["snapshot"]
        self.assertEqual(snapshot["fingerprints"]["AGENTS.md"], f.module()._fingerprint(f.repo, "AGENTS.md"))
        return request

    def test_unchanged_ignored_target_applies_resumes_and_restores_original_preimage(self):
        f = self.fixture
        original = (f.repo / "AGENTS.md").read_bytes()
        request = self.request()
        fired = False

        def interrupt(stage):
            nonlocal fired
            if stage == "rename" and not fired:
                fired = True
                raise RuntimeError("fixture interruption")

        with patch.object(f.changes, "_checkpoint", side_effect=interrupt):
            with self.assertRaisesRegex(RuntimeError, "fixture interruption"):
                f.changes._run_scoped(f.directory, request, "apply")
        self.assertEqual((f.repo / "AGENTS.md").read_text(), "product rules\nnew process\n")

        resumed = f.changes._run_scoped(f.directory, request, "resume")
        self.assertEqual(resumed["exit_code"], 0, resumed)
        rolled_back = f.changes._run_scoped(f.directory, request, "rollback")
        self.assertEqual(rolled_back["exit_code"], 0, rolled_back)
        self.assertEqual((f.repo / "AGENTS.md").read_bytes(), original)

    def test_same_sized_ignored_target_edit_after_approval_blocks_before_journal(self):
        f = self.fixture
        request = self.request()
        external = b"product rules\ncustom process\n"
        self.assertEqual(len(external), len((f.repo / "AGENTS.md").read_bytes()))
        (f.repo / "AGENTS.md").write_bytes(external)

        result = f.changes._run_scoped(f.directory, request, "apply")
        self.assertNotEqual(result["exit_code"], 0, result)
        self.assertFalse((f.directory / "transaction.json").exists())
        self.assertEqual((f.repo / "AGENTS.md").read_bytes(), external)

    def test_git_visible_input_edit_after_approval_still_blocks(self):
        f = self.fixture
        request = self.request()
        (f.repo / "README.md").write_text("changed reviewed input\n")

        result = f.changes._run_scoped(f.directory, request, "apply")
        self.assertNotEqual(result["exit_code"], 0, result)
        self.assertFalse((f.directory / "transaction.json").exists())
        self.assertEqual((f.repo / "AGENTS.md").read_text(), "product rules\nlegacy process\n")

    def test_scoped_revision_to_readme_applies_resumes_and_rolls_back_without_old_target_mismatch(self):
        f = self.fixture
        original_a = (f.repo / "AGENTS.md").read_bytes()
        original_b = (f.repo / "README.md").read_bytes()
        f.scoped_request()

        text = "product\nrevised readme\n"
        proposal = f.scoped_proposal()
        action = proposal["assessments"]["repositories"][0]["actions"][0]
        action.update(target="README.md", section=None,
            before=f.module()._fingerprint(f.repo, "README.md")["sha256"], text=text,
            after=hashlib.sha256(text.encode()).hexdigest(), preservation_exceptions=[])
        revised = f.module().record_plan(f.directory, proposal)
        self.assertEqual(revised["status"], "ready_for_review", revised)
        snapshot = f.plan()["assessments"]["repositories"][0]["identity"]["snapshot"]
        self.assertIn("AGENTS.md", snapshot["fingerprints"])

        request = f.scoped_request(existing=True, prepared=True)
        self.assertEqual(request["manifest"]["actions"][0]["effects"][0]["path"], "README.md")
        fired = False

        def interrupt(stage):
            nonlocal fired
            if stage == "rename" and not fired:
                fired = True
                raise RuntimeError("fixture interruption")

        with patch.object(f.changes, "_checkpoint", side_effect=interrupt):
            with self.assertRaisesRegex(RuntimeError, "fixture interruption"):
                f.changes._run_scoped(f.directory, request, "apply")
        self.assertEqual((f.repo / "README.md").read_text(), text)
        self.assertEqual((f.repo / "AGENTS.md").read_bytes(), original_a)

        resumed = f.changes._run_scoped(f.directory, request, "resume")
        self.assertEqual(resumed["exit_code"], 0, resumed)
        rolled_back = f.changes._run_scoped(f.directory, request, "rollback")
        self.assertEqual(rolled_back["exit_code"], 0, rolled_back)
        self.assertEqual((f.repo / "README.md").read_bytes(), original_b)
        self.assertEqual((f.repo / "AGENTS.md").read_bytes(), original_a)
