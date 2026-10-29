"""Closed-detail expiry uses real D4 owners and native-review fixture receipts.

The mocked clock and native observations are fixture authority, not client proof.
"""

from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

from runtime import state
from tests import test_diagnostic_cleanup as diagnostics


class DetailRetentionTests(unittest.TestCase):
    retention_age = 7 * 24 * 60 * 60
    fixture = diagnostics.DiagnosticCleanupTests.fixture
    closed_output = diagnostics.DiagnosticCleanupTests.closed_output
    interrupt_unlink = diagnostics.DiagnosticCleanupTests.interrupt_unlink

    def reviewed_owner(self):
        fixture, clock = self.fixture()
        reviewed = fixture.fixture.review()
        task = state.task_status(fixture.scope, "codex", "parent")["task"]
        review = next(attempt for attempt in task["evidence"]["attempts"]
                      if attempt["id"] == reviewed["attempt_id"])
        closed = self.closed_output(fixture)
        return fixture, clock, review, closed

    def normal_use(self, fixture):
        api = fixture.fixture.api
        identity = fixture.fixture.identity | dict(task_id="detail-successor", scope_ref="user:detail-successor")
        task = state.start_task(fixture.scope, identity | dict(mode="editable", decision_ref="user:accepted"))["task"]
        api._artifact(fixture.scope, dict(kind="fixture-normal-detail-opportunity"),
                      owner=api._artifact_owner(fixture.scope, task))
        return identity

    def test_normal_use_expires_review_brief_at_original_seven_day_boundary(self):
        # A diagnostic-only cleaner leaves both the D5 prompt and D6 request text.
        fixture, clock, review, closed = self.reviewed_owner()
        _, context, task_ref, _, _, _, compact_ref, owner = closed
        api = fixture.fixture.api
        brief = review["assignment"]
        path = context.directory / "evidence" / brief["name"]
        original_brief = api._read(fixture.scope, brief)["prompt"].encode()
        compact_before = api._read(fixture.scope, compact_ref)
        original_closed = owner["lifecycle"]["safe_closed_at"]
        with api._context_database(context) as db:
            original_age = state._metadata(db, brief["name"])["created_at"]
            marker_before = state._retired(db, "task", {key: task_ref[key]
                for key in ("scope_id", "client", "session_id", "task_id")})

        clock[0] = original_closed + self.retention_age - 1
        api._cleanup_closed_details(context)
        self.assertTrue(path.exists(), "closed detail expired before its original seven-day boundary")
        clock[0] += 1
        successor = self.normal_use(fixture)
        self.assertFalse(path.exists(), "normal use retained an eligible closed review brief")
        self.assertFalse(any(original_brief in candidate.read_bytes()
                             for candidate in path.parent.iterdir()),
                         "managed evidence still contains the expired brief text")
        with self.assertRaises(state.StateError):
            api._read(fixture.scope, brief)
        with api._context_database(context) as db:
            metadata = state._metadata(db, brief["name"])
            self.assertEqual(metadata["status"], "expired")
            self.assertEqual(metadata["created_at"], original_age)
            self.assertEqual(metadata["closed_at"], original_closed)
            self.assertEqual(state._retired(db, "task", marker_before["identity"]), marker_before)
        with api._context_database(context) as db:
            retained = [api._read(None, row["reference"], context=context, db=db)
                        for row in api._evidence_inventory_rows(db)
                        if row["metadata"]["class"] == "compact" and row["metadata"]["status"] == "live"
                        and row["metadata"]["owner"].get("task") == task_ref]
        self.assertTrue(any(body.get("numerical") == compact_before["numerical"]
                            and body.get("sources") == compact_before["sources"] for body in retained),
                        "expiry discarded authoritative numerical values or original source provenance")

        fixture.fixture.identity = successor
        fixture.fixture.plan()
        next_task, next_context, next_ref, _ = fixture.stopped()
        fixture.close(next_task, next_context, next_ref)
        self.assertTrue(api._retire_closed_task(next_context, next_ref)["retired"])

    def test_normal_use_physically_expires_collected_review_report(self):
        # Retaining only report provenance must not retain the original report file.
        fixture, clock, review, closed = self.reviewed_owner()
        _, context, _, _, _, _, _, owner = closed
        path = context.directory / "evidence" / review["collected"]["name"]
        self.assertTrue(path.exists())
        clock[0] = owner["lifecycle"]["safe_closed_at"] + self.retention_age
        self.normal_use(fixture)
        self.assertFalse(path.exists(), "normal use retained an eligible closed review report")
        with self.assertRaises(state.StateError):
            fixture.fixture.api._read(fixture.scope, review["collected"])

    def test_normal_use_replaces_legacy_compact_copy_before_physical_expiry(self):
        fixture, clock, review, closed = self.reviewed_owner()
        _, context, task_ref, _, _, _, compact_ref, owner = closed
        api = fixture.fixture.api
        original = api._read(fixture.scope, compact_ref)
        clock[0] = owner["lifecycle"]["safe_closed_at"] + self.retention_age
        self.normal_use(fixture)
        legacy = context.directory / "evidence" / compact_ref["name"]
        self.assertFalse(legacy.exists(), "legacy compact still stores the full review report")
        with api._context_database(context) as db:
            successors = [(row, api._read(None, row["reference"], context=context, db=db))
                          for row in api._evidence_inventory_rows(db)
                          if row["metadata"]["class"] == "compact" and row["metadata"]["status"] == "live"
                          and row["metadata"]["owner"].get("task") == task_ref]
        retained = [body for _, body in successors if body.get("kind") == "retained-task-closure"]
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0]["numerical"], original["numerical"])
        self.assertEqual(retained[0]["native_guidance"], original["native_guidance"])
        self.assertNotIn("report", retained[0]["reviews"][0])
        self.assertEqual(retained[0]["created_at"], original["created_at"])
        self.assertEqual(retained[0]["closed_at"], owner["lifecycle"]["safe_closed_at"])
        with self.assertRaises(state.StateError):
            api._read(fixture.scope, compact_ref)

    def test_interrupted_brief_unlink_commits_intent_and_resumes(self):
        # Deletion must be recoverable on either side of the physical unlink.
        for after in (False, True):
            with self.subTest(after=after):
                fixture, clock, review, closed = self.reviewed_owner()
                _, context, _, _, _, _, _, owner = closed
                api = fixture.fixture.api
                path = context.directory / "evidence" / review["assignment"]["name"]
                clock[0] = owner["lifecycle"]["safe_closed_at"] + self.retention_age
                with self.interrupt_unlink(path, after=after):
                    with self.assertRaises(RuntimeError):
                        api._cleanup_closed_details(context)
                self.assertEqual(path.exists(), not after)
                with api._context_database(context) as db:
                    self.assertEqual(state._metadata(db, path.name)["status"], "delete_pending")
                with self.assertRaises(state.StateError):
                    api._read(fixture.scope, review["assignment"])
                api._cleanup_closed_details(context)
                self.assertFalse(path.exists())
                with api._context_database(context) as db:
                    self.assertEqual(state._metadata(db, path.name)["status"], "expired")

    def umbrella_cap_fixture(self):
        from tests import test_enrolled_accounting_integration as accounting
        from tests import test_evidence as evidence_tests
        from runtime.startup import canonical_scope_projection, decode_project_record, _canonical_freeze

        clock = [1_800_000_000]
        timing = patch.object(state, "_owner_time", side_effect=lambda: clock[0])
        timing.start()
        self.addCleanup(timing.stop)
        umbrella = accounting.EnrolledUmbrellaAccountingTests(methodName="runTest")
        umbrella.setUp()
        self.addCleanup(umbrella.doCleanups)
        from runtime import evidence as api
        groups = []
        databases = []
        closed_at = []
        for index, repository in enumerate(umbrella.record["repositories"]):
            checkout = repository["checkouts"][0]
            identity = canonical_scope_projection(decode_project_record(umbrella.record),
                repository_id=repository["repository_id"], checkout_id=checkout["checkout_id"], client="codex")
            scope = replace(umbrella.scope, repository_id=repository["repository_id"],
                checkout_id=checkout["checkout_id"], repository_root=Path(checkout["root"]),
                primary_root=Path(repository["primary_root"]), git_dir=Path(checkout["git_dir"]),
                git_common_dir=Path(repository["git_common_dir"]),
                bindings=_canonical_freeze(repository["binding"] | checkout["binding"]),
                accepted_identity=identity, accepted_scope_digest=api._digest(api._canonical_plain(identity)))
            task_fixture = evidence_tests.EvidenceTests(methodName="runTest")
            task_fixture.root = umbrella.private / ("proofs-" + str(index))
            task_fixture.root.mkdir()
            task_fixture.repo = scope.repository_root
            task_fixture.scope = scope
            task_fixture.api = api
            task_fixture.identity = dict(client="codex", session_id="parent", task_id="cap-" + str(index),
                                         scope_ref="user:cap-" + str(index))
            (scope.repository_root / "app.py").write_text("value = 1\n")
            state.start_task(scope, task_fixture.identity | dict(mode="editable", decision_ref="user:accepted"))
            task_fixture.plan()
            owner_fixture = evidence_tests.AssignedCancelledClosureTests(methodName="runTest")
            owner_fixture.fixture = task_fixture
            owner_fixture.scope = scope
            task, context, ref, _ = owner_fixture.stopped()
            closed = owner_fixture.close(task, context, ref)
            self.assertTrue(api._retire_closed_task(context, ref)["retired"])
            databases.append(context.database)
            closed_at.append(closed["lifecycle"]["safe_closed_at"])
            with api._context_database(context) as db:
                rows = [row for row in api._evidence_inventory_rows(db)
                        if row["metadata"]["class"] == "detail" and row["metadata"]["owner"].get("task") == ref]
            groups.append(rows)
            clock[0] += 10
        totals = [sum(row["metadata"]["bytes"] for row in rows) for rows in groups]
        cap = max(totals) + 1
        self.assertGreater(sum(totals), cap)
        self.assertEqual(len(set(databases)), 1)
        self.assertLess(closed_at[0], closed_at[1])
        self.assertLess(clock[0] - closed_at[0], self.retention_age)
        paths = [[Path(row["metadata"]["managed"]["path"]) for row in rows] for rows in groups]
        self.assertEqual([sum(path.stat().st_size for path in group) for group in paths], totals)
        before = [[path.read_bytes() for path in group] for group in paths]
        return umbrella, api, context, cap, paths, before

    def test_umbrella_repositories_share_one_closed_detail_cap_oldest_first(self):
        # A cap per repository would leave both complete detail groups untouched.
        from runtime import review_storage
        umbrella, api, context, cap, paths, before = self.umbrella_cap_fixture()
        prepared = review_storage.prepare_storage(umbrella.private / "temporary-private")
        self.assertTrue(prepared.get("ok"), prepared)
        self.assertTrue(umbrella.locator.is_file())
        with review_storage._machine_guard() as (path, descriptor, parents):
            config = review_storage._configuration(path, descriptor)
            temporary = review_storage._ready_context(config, parents)
            with api._context_database(temporary) as db:
                self.assertEqual(review_storage._owners(config, temporary, db), [])
        for member in umbrella.members:
            accounting = review_storage.acquire_enrolled_accounting(member)
            self.assertTrue(accounting.get("ok"), accounting)
            self.assertEqual(accounting.get("temporary_history"),
                dict(complete=True, reason="authenticated_no_related_history"))
            self.assertEqual(accounting["authority"], api._canonical_plain(context.authority_set[0]))
        # Scale only the byte threshold; owners, files, closures and accounting are real.
        with patch.object(api, "_CLOSED_DETAIL_CAP_BYTES", cap, create=True):
            api._cleanup_closed_details(context)
        self.assertTrue(any(not path.exists() for path in paths[0]),
                        "shared Project pressure did not release its oldest eligible detail")
        self.assertEqual([path.read_bytes() for path in paths[1]], before[1],
                         "Project cleanup released newer detail before older eligible detail")

    def test_umbrella_cap_without_machine_history_preserves_all_evidence(self):
        from runtime import review_storage
        umbrella, api, context, cap, _, _ = self.umbrella_cap_fixture()
        self.assertFalse(umbrella.locator.exists())
        for member in umbrella.members:
            accounting = review_storage.acquire_enrolled_accounting(member)
            self.assertTrue(accounting.get("ok"), accounting)
            self.assertEqual(accounting.get("temporary_history"),
                dict(complete=False, reason="machine_configuration_absent"))
        def snapshot():
            with api._context_database(context) as db:
                return {row["reference"]["name"]:(row["metadata"],
                    Path(row["metadata"]["managed"]["path"]).read_bytes())
                    for row in api._evidence_inventory_rows(db)}
        before = snapshot()
        with patch.object(api, "_CLOSED_DETAIL_CAP_BYTES", cap, create=True):
            report = api._cleanup_closed_details(context)
        self.assertEqual(snapshot(), before)
        self.assertFalse(report["project"]["complete"])
        self.assertIsNone(report["project"]["cap_satisfied"])
        self.assertFalse(report["expired"])
        self.assertFalse(umbrella.locator.exists())

    def test_issued_retention_preserves_original_age_and_rejects_unissued_owner(self):
        fixture, clock, review, closed = self.reviewed_owner()
        api = fixture.fixture.api
        context, compact = closed[1], closed[6]
        with api._context_database(context) as db:
            facts = api._retention_facts(context, db, compact)
        content = facts["retention"]["content"]
        observation = api._ClosureObservation(api._canonical_freeze(facts), context, api._CLOSURE_ISSUER)
        owner = api._ClosureOwner(api._canonical_freeze(closed[2]), observation,
                                 api._canonical_freeze(content), (), content["created_at"])
        clock[0] += self.retention_age
        with api._context_database(context, write=True, durable=True) as db:
            reference = api._artifact(None, content, context=context, owner=owner, db=db)
        with api._context_database(context) as db:
            support = api._retained_closure_support(context, db, reference)
            self.assertEqual(support["metadata"]["created_at"], closed[7]["lifecycle"]["created_at"])
            self.assertEqual(support["metadata"]["closed_at"], closed[7]["lifecycle"]["safe_closed_at"])
            self.assertEqual(reference["name"], api._retention_name(compact))
        forged = api._ClosureOwner(owner.reference, facts, owner.content, (), owner.created_at)
        with api._context_database(context, write=True) as db:
            with self.assertRaises(state.StateError):
                api._registered_owner(None, context, forged, db)

    def test_reference_shaped_prompt_is_not_a_typed_detail_producer(self):
        from runtime import evidence as api
        with self.assertRaises(state.StateError):
            api._retention_detail_shape(dict(prompt=dict(name="a" * 32 + ".json", digest="b" * 64)))

    def test_expired_diagnostic_converts_without_reconstructing_its_body(self):
        fixture, clock, review, closed = self.reviewed_owner()
        api, context = fixture.fixture.api, closed[1]
        clock[0] = closed[7]["lifecycle"]["safe_closed_at"] + self.retention_age
        report = api._cleanup_diagnostics(context)
        self.assertIn(closed[5], report["expired"], report)
        original = api._read(fixture.scope, closed[6])
        report = api._cleanup_closed_details(context)
        self.assertIn(review["assignment"], report["expired"], report)
        with api._context_database(context) as db:
            proof = api._diagnostic_proof(context, db, closed[5])
            self.assertTrue(proof["retained"])
            self.assertEqual(proof["compact"]["numerical"], original["numerical"])
            routes = api._diagnostic_output_routes(context, db, closed[2])
            self.assertFalse(routes["deletion_authorized"])
        with self.assertRaises(state.StateError):
            api._read(fixture.scope, closed[5])

    def test_publication_rollback_orphan_protects_every_original(self):
        fixture, clock, review, closed = self.reviewed_owner()
        api, context = fixture.fixture.api, closed[1]
        clock[0] = closed[7]["lifecycle"]["safe_closed_at"] + self.retention_age
        publish = api._artifact_registered
        def interrupted(scope, value, selected, owner, db):
            result = publish(scope, value, selected, owner, db)
            if value.get("kind") == "retained-task-closure":
                raise RuntimeError("fixture: before retained publication commit")
            return result
        with patch.object(api, "_artifact_registered", side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                api._cleanup_closed_details(context)
        path = context.directory / "evidence" / review["assignment"]["name"]
        before = path.read_bytes()
        report = api._cleanup_closed_details(context)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(report["expired"])
        self.assertTrue(report["protected"] or report["limitations"])
        with api._context_database(context) as db:
            self.assertIsNone(api._retained_for_owner(context, db, closed[2]))

    def test_committed_publication_resumes_without_legacy_selection_ambiguity(self):
        fixture, clock, review, closed = self.reviewed_owner()
        api, context = fixture.fixture.api, closed[1]
        clock[0] = closed[7]["lifecycle"]["safe_closed_at"] + self.retention_age
        consumers = api._retention_consumers
        def interrupted(selected, db, owner, releases, recovery):
            if api._retained_for_owner(selected, db, owner) is not None:
                raise RuntimeError("fixture: after retained publication commit")
            return consumers(selected, db, owner, releases, recovery)
        with patch.object(api, "_retention_consumers", side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                api._cleanup_closed_details(context)
        with api._context_database(context) as db:
            support = api._retained_for_owner(context, db, closed[2])
            self.assertIsNotNone(support)
            from runtime import delegation
            delegation._closure_guidance(context, db, delegation._ledger(None, db, context=context))
        report = api._cleanup_closed_details(context)
        self.assertIn(review["assignment"], report["expired"], report)

    def test_expired_content_cannot_be_admitted_through_a_retained_receipt(self):
        fixture, clock, review, closed = self.reviewed_owner()
        api, context = fixture.fixture.api, closed[1]
        clock[0] = closed[7]["lifecycle"]["safe_closed_at"] + self.retention_age
        report = api._cleanup_closed_details(context)
        self.assertIn(review["assignment"], report["expired"], report)
        with api._context_database(context, write=True) as db:
            with self.assertRaises(state.StateError):
                api._admit_content_dependencies(context, db, [dict(kind="artifact", reference=review["assignment"])])
        with self.assertRaises(state.StateError):
            api._managed_artifact(fixture.scope, review["assignment"])

    def test_compact_projection_preserves_scoped_finding_recheck_references(self):
        from runtime import evidence as api
        original = {key: None for key in ('identity','pins','accepted_identity','created_at','revision','outcome',
            'coverage','stopped','numerical','sources','native_guidance','scope_guidance','usage')}
        recheck = dict(attempt_id="prior", finding_id="finding", status="resolved", reference="fixture:rechecked-source")
        original.update(workers=[], verifications=[], reviews=[dict(assignment_id="current", status="assessed",
            coverage=["general"], criteria=["works"], assessments=[dict(source=dict(name="a" * 32 + ".json", digest="b" * 64),
            assessment=dict(coverage=["general"], criteria=["works"], dispositions=[], decision_refs=["fixture:accepted"],
                            rechecked_findings=[recheck]))])])
        retained = api._retention_projection(original)
        self.assertEqual(retained["reviews"][0]["assessments"][0]["assessment"].get("rechecked_findings"), [recheck])

    def test_active_review_brief_and_report_remain_physically_protected(self):
        # Elapsed time alone cannot release an unclosed task's detail.
        fixture, clock = self.fixture()
        result = fixture.fixture.review()
        task = state.task_status(fixture.scope, "codex", "parent")["task"]
        attempt = next(row for row in task["evidence"]["attempts"] if row["id"] == result["attempt_id"])
        api = fixture.fixture.api
        context = api._evidence_context(fixture.scope)
        paths = [context.directory / "evidence" / attempt[key]["name"] for key in ("assignment", "collected")]
        original = [path.read_bytes() for path in paths]
        clock[0] += self.retention_age + 1
        api._cleanup_closed_details(context)
        self.assertEqual([path.read_bytes() for path in paths], original)
        for key in ("assignment", "collected"):
            self.assertIsInstance(api._read(fixture.scope, attempt[key]), dict)


if __name__ == "__main__":
    unittest.main()
