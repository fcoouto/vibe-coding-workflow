"""Real D4 umbrella publication precedes the genuine schema3 baseline producer."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime import evidence, onboarding, review_storage, state
from runtime.startup import (AcceptedScope, PROJECT_FILE, RuntimeSettings,
                             _canonical_freeze, _canonical_plain,
                             canonical_scope_projection, decode_project_record)
from tests import test_changes, test_evidence, test_review_storage


class EnrolledUmbrellaAccountingTests(unittest.TestCase):
    def setUp(self):
        self.d4 = test_changes.ScopedChangesTests(methodName="runTest")
        self.d4.setUp()
        self.addCleanup(self.d4.doCleanups)
        private = tempfile.TemporaryDirectory(prefix="vibe-umbrella-accounting-")
        self.addCleanup(private.cleanup)
        self.private = Path(private.name).resolve()
        self.storage = self.private / "project-state"
        self.locator = self.private / "machine" / "machine.json"
        self.locator.parent.mkdir(mode=0o700)
        locator = patch.object(review_storage, "_machine_config_path", return_value=self.locator)
        locator.start()
        self.addCleanup(locator.stop)

        request = self.d4.scoped_request(umbrella=True)
        record = request["manifest"]["enrollment"]["record"]
        self.assertEqual(record["kind"], "umbrella")
        self.assertEqual(len(record["repositories"]), 2)
        for repository in record["repositories"]:
            self.assertEqual(repository["membership"], "joined")
            repository["checkouts"][0]["clients"][0]["configuration"]["runtime"] = dict(
                schema_version=3, state_dir=str(self.storage))
        request["approval"]["manifest_digest"] = onboarding._digest(request["manifest"])
        self.authority = Path(record["project_root"]) / PROJECT_FILE
        self.assertFalse(self.authority.exists())
        self.assertFalse(self.storage.exists())
        published = test_evidence._run_d4_fixture(self.d4, request, "apply")
        self.assertEqual(published["exit_code"], 0, published)
        self.assertEqual(published["activation_status"], "configured")
        self.assertFalse(published["qualified"])
        self.record = json.loads(self.authority.read_text())
        self.assertEqual(self.record, record)
        self.assertFalse(self.storage.exists())

        repository = self.record["repositories"][0]
        checkout = repository["checkouts"][0]
        identity = canonical_scope_projection(decode_project_record(self.record),
            repository_id=repository["repository_id"], checkout_id=checkout["checkout_id"], client="codex")
        # D4RecoveryFixture seam: published configured scope, without native activation.
        self.scope = AcceptedScope(self.record["project_id"], repository["repository_id"], checkout["checkout_id"],
            Path(self.record["project_root"]), self.authority,
            _canonical_freeze(self.d4.changes._scoped_target(Path(self.record["project_root"]), str(PROJECT_FILE))),
            self.record["revision"], Path(checkout["root"]), Path(repository["primary_root"]),
            Path(checkout["git_dir"]), Path(repository["git_common_dir"]),
            _canonical_freeze(repository["binding"] | checkout["binding"]), "codex",
            identity["configuration"]["policy_digest"], identity["configuration"]["runtime_digest"],
            RuntimeSettings(3, self.storage), identity, onboarding._digest(_canonical_plain(identity)),
            _canonical_freeze(dict(kind="trusted-coordinator", **request["approval"]["evidence"][0])))
        state.start_task(self.scope, dict(client="codex", session_id="umbrella", task_id="baseline",
            scope_ref="fixture:published-umbrella", mode="read-only", decision_ref="fixture:internal-scope"))
        context = evidence._evidence_context(self.scope)
        with evidence._context_database(context) as db:
            self.baseline = _canonical_plain(state._source_baseline(None, db, context=context))
            metadata = state._metadata(db, self.baseline["reference"]["name"])
            self.assertEqual(metadata["created_at"], self.baseline["content"]["created_at"])
            self.assertEqual(metadata["owner"], dict(kind="project", project_id=self.record["project_id"], task=None))
        self.assertEqual(self.baseline["content"]["project_id"], self.record["project_id"])
        self.members = [Path(repository["checkouts"][0]["root"]) for repository in self.record["repositories"]]
        self.assertNotEqual(*self.members)

    def snapshot(self):
        return tuple(test_review_storage.ReviewStorageTests.tree_snapshot(root) for root in
            (self.d4.base, self.d4.directory.parent, self.private))

    def test_two_joined_repositories_share_original_project_accounting_without_writes(self):
        before = self.snapshot()
        results = [review_storage.resolve_owner(member) for member in self.members]
        for member, result in zip(self.members, results):
            self.assertTrue(result.get("ok"), result)
            self.assertEqual(result.get("status"), "resolved", result)
            self.assertEqual(result.get("owner"), dict(kind="project", project_id=self.record["project_id"], task=None))
            self.assertEqual(result.get("reference"), self.baseline["reference"])
            self.assertEqual(result.get("authority"), self.baseline["content"]["authority"])
            self.assertEqual(result.get("created_at"), self.baseline["content"]["created_at"])
            self.assertEqual(result.get("age_basis"), "authority_provenance")
            self.assertEqual(result.get("temporary_history"), dict(complete=False, reason="machine_configuration_absent"))
            self.assertEqual(result["checkout"]["root"], str(member))
            self.assertEqual(result["checkout"]["primary_root"], str(member))
            self.assertEqual(result["checkout"]["git_common_dir"], str(member / ".git"))
        self.assertNotEqual(results[0]["checkout"], results[1]["checkout"])
        self.assertNotEqual(results[0]["checkout"]["binding"], results[1]["checkout"]["binding"])
        self.assertFalse(self.locator.exists())
        self.assertEqual(self.snapshot(), before)

    def test_competing_configured_member_or_client_store_protects_without_allocation(self):
        for variant in ("member", "client"):
            with self.subTest(variant=variant):
                record = copy.deepcopy(self.record)
                if variant == "member":
                    entry = record["repositories"][1]["checkouts"][0]["clients"][0]
                else:
                    clients = record["repositories"][0]["checkouts"][0]["clients"]
                    entry = copy.deepcopy(clients[0])
                    entry["client"] = "claude-code"
                    clients.append(entry)
                competing = self.private / ("competing-" + variant)
                entry["configuration"]["runtime"]["state_dir"] = str(competing)
                decode_project_record(record)
                self.authority.write_text(json.dumps(record))
                before = self.snapshot()
                for member in self.members:
                    result = review_storage.resolve_owner(member)
                    self.assertFalse(result.get("ok"), result)
                    self.assertEqual(result.get("status"), "protected", result)
                self.assertFalse(competing.exists())
                self.assertFalse(self.locator.exists())
                self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
