"""Destructive-retention checks use disposable authenticated D4 evidence only."""

import json
import inspect
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from runtime import state
from tests import test_detail_retention as details
from tests import test_evidence as evidence_tests


class RetentionSafetyTests(unittest.TestCase):
    retention_age = details.DetailRetentionTests.retention_age
    fixture = details.DetailRetentionTests.fixture
    closed_output = details.DetailRetentionTests.closed_output
    reviewed_owner = details.DetailRetentionTests.reviewed_owner
    interrupt_unlink = details.DetailRetentionTests.interrupt_unlink

    def eligible(self):
        fixture, clock, review, closed = self.reviewed_owner()
        clock[0] = closed[7]["lifecycle"]["safe_closed_at"] + self.retention_age
        return fixture, clock, review, closed

    def publish_only(self, fixture, closed):
        api, context = fixture.fixture.api, closed[1]
        consumers = api._retention_consumers
        def interrupted(selected, db, owner, releases, recovery):
            if api._retained_for_owner(selected, db, owner) is not None:
                raise RuntimeError("fixture: after retained publication commit")
            return consumers(selected, db, owner, releases, recovery)
        with patch.object(api, "_retention_consumers", side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                api._cleanup_closed_details(context)
        with api._context_database(context) as db:
            return api._retained_for_owner(context, db, closed[2])

    def close_successor(self, fixture, clock, *, retire=True, review=False):
        clock[0] += 10
        identity = fixture.fixture.identity | dict(task_id="retention-next", scope_ref="user:retention-next")
        state.start_task(fixture.scope, identity | dict(mode="editable", decision_ref="user:accepted"))
        fixture.fixture.identity = identity
        fixture.fixture.plan()
        if review:
            fixture.fixture.review()
        task, context, reference, attempt = fixture.stopped()
        api = fixture.fixture.api
        execution = api._read(fixture.scope, attempt["execution"])
        closed = fixture.close(task, context, reference)
        if retire:
            self.assertTrue(api._retire_closed_task(context, reference)["retired"])
        return task, context, reference, attempt, attempt["execution"], execution["output"], closed["lifecycle"]["compact"], closed

    def owner_snapshot(self, api, context, owner):
        with api._context_database(context) as db:
            rows = [row for row in api._evidence_inventory_rows(db) if row["metadata"]["owner"].get("task") == owner]
        return {row["reference"]["name"]:(row["metadata"],
            Path(row["metadata"]["managed"]["path"]).read_bytes() if Path(row["metadata"]["managed"]["path"]).exists() else None)
            for row in rows}

    def test_unretired_successor_inventory_blocks_conversion_intent_and_replay(self):
        for stage in ("original", "published", "pending"):
            with self.subTest(stage=stage):
                fixture, clock = self.fixture()
                first = self.closed_output(fixture)
                api, context = fixture.fixture.api, first[1]
                if stage != "original":
                    clock[0] = first[7]["lifecycle"]["safe_closed_at"] + self.retention_age
                    if stage == "published":
                        self.publish_only(fixture, first)
                    else:
                        path = context.directory / "evidence" / first[5]["name"]
                        with self.interrupt_unlink(path, after=False):
                            with self.assertRaises(RuntimeError):
                                api._cleanup_closed_details(context)
                # Setup B through genuine owners while an existing publication defers cleanup.
                token = api._DIAGNOSTIC_CLEANUP.set(True)
                try:
                    second = self.close_successor(fixture, clock, retire=False)
                finally:
                    api._DIAGNOSTIC_CLEANUP.reset(token)
                original = api._read(fixture.scope, second[6])
                self.assertEqual(api._retirement_content(api._canonical_plain(api._observe_closure((context,), second[2]).facts)), original)
                before = self.owner_snapshot(api, context, first[2])
                clock[0] = max(clock[0], first[7]["lifecycle"]["safe_closed_at"] + self.retention_age)
                report = api._cleanup_closed_details(context)
                self.assertTrue(self.owner_snapshot(api, context, first[2]) == before,
                    "A files or metadata changed while B retained its full inventory")
                self.assertFalse(report["expired"], report)
                self.assertEqual(api._retirement_content(api._canonical_plain(api._observe_closure((context,), second[2]).facts)), original)
                self.assertTrue(api._retire_closed_task(context, second[2])["retired"])

    def test_unretired_linked_preparation_inventory_blocks_ordinary_conversion(self):
        from tests.test_state import canonical_scope
        fixture, clock = self.fixture()
        first = self.closed_output(fixture)
        api, context = fixture.fixture.api, first[1]
        linked = evidence_tests.LinkedVerificationTests(methodName="runTest")
        linked.api = api
        selected = fixture.fixture
        selected.identity = selected.identity | dict(task_id="linked-next", scope_ref="user:linked-next")
        state.start_task(selected.scope, selected.identity | dict(mode="editable", decision_ref="user:accepted"))
        peer = evidence_tests.EvidenceTests(methodName="runTest")
        peer.setUp()
        self.addCleanup(peer.doCleanups)
        peer.scope = canonical_scope(peer.scope)
        state.start_task(peer.scope, peer.identity | dict(mode="editable", decision_ref="user:accepted"))
        linked.current_record(peer)
        linked.members = [selected, peer]
        linked.selected = selected
        linked.establish()
        pointer = linked.verify()["verification"]
        authorities = linked.preparation_stops(pointer)
        self.assertTrue(api._prepare_linked_closure(api._observe_linked_preparation(pointer, authorities))["complete"])
        before = self.owner_snapshot(api, context, first[2])
        clock[0] = first[7]["lifecycle"]["safe_closed_at"] + self.retention_age
        report = api._cleanup_closed_details(context)
        self.assertTrue(self.owner_snapshot(api, context, first[2]) == before)
        self.assertTrue(any("unretired linked preparation retains its inventory" in item["reason"] for item in report["protected"]), report)

    def test_sequential_owner_expiry_authenticates_other_retained_bookkeeping(self):
        fixture, clock = self.fixture()
        first = self.closed_output(fixture)
        api, context = fixture.fixture.api, first[1]
        first_original = api._read(fixture.scope, first[6])
        clock[0] = first[7]["lifecycle"]["safe_closed_at"] + self.retention_age
        self.assertIn(first[6], api._cleanup_closed_details(context)["expired"])
        second = self.close_successor(fixture, clock)
        self.assertEqual(second[1].database, context.database)
        second_original = api._read(fixture.scope, second[6])
        clock[0] = second[7]["lifecycle"]["safe_closed_at"] + self.retention_age
        report = api._cleanup_closed_details(context)
        self.assertIn(second[6], report["expired"], report)
        self.assertIn(second[5], report["expired"], report)
        with api._context_database(context, write=True) as db:
            for closed, original in ((first, first_original), (second, second_original)):
                support = api._retained_for_owner(context, db, closed[2])
                self.assertEqual(support["content"]["numerical"], original["numerical"])
                self.assertEqual(support["content"]["created_at"], original["created_at"])
                self.assertEqual(support["content"]["closed_at"], closed[7]["lifecycle"]["safe_closed_at"])
                with self.assertRaises(state.StateError):
                    api._admit_content_dependencies(context, db, [dict(kind="artifact", reference=closed[5])])
                with self.assertRaises(state.StateError):
                    api._read(None, closed[5], context=context, db=db)
        identity = fixture.fixture.identity | dict(task_id="expired-consumer", scope_ref="user:expired-consumer")
        task = state.start_task(fixture.scope, identity | dict(mode="editable", decision_ref="user:accepted"))["task"]
        owner = api._artifact_owner(fixture.scope, task)
        for reference in (first[5], second[4]):
            with self.assertRaisesRegex(state.StateError, "unavailable or expired"):
                api._artifact(fixture.scope, dict(kind="independent-expired-content", source=reference), owner=owner)

    def test_diagnostic_only_history_allows_later_conversion_only_through_issued_routes(self):
        for independent_execution in (False, True):
            with self.subTest(independent_execution=independent_execution):
                fixture, clock, review, first, consumer = self.protected_brief_owner()
                api, context = fixture.fixture.api, first[1]
                original_first = api._read(fixture.scope, first[6])
                api._artifact(fixture.scope, dict(kind="first-diagnostic-opportunity"), owner=consumer)
                with api._context_database(context) as db:
                    self.assertIsNone(api._retained_for_owner(context, db, first[2]))
                    proof = api._diagnostic_proof(context, db, first[5])
                    self.assertEqual(proof["availability"], "expired")
                    self.assertEqual(proof["compact"], original_first)
                first_after_diagnostic = self.owner_snapshot(api, context, first[2])
                current = state.task_status(fixture.scope, "codex", "parent")["task"]
                identity = fixture.fixture.identity | dict(task_id="retention-next", scope_ref="user:retention-next")
                state.start_task(fixture.scope, identity | dict(mode="editable", decision_ref="user:accepted",
                    replaces=dict(task_id=current["task_id"], expected_revision=current["revision"])))
                second = self.close_successor(fixture, clock, retire=False)
                self.assertEqual(second[1].database, context.database)
                original_second = api._read(fixture.scope, second[6])
                fresh = api._canonical_plain(api._observe_closure((context,), second[2]).facts)
                self.assertEqual(api._retirement_content(fresh), original_second)
                self.assertTrue(api._retire_closed_task(context, second[2])["retired"])
                if independent_execution:
                    # A caller-supplied kind cannot turn this current execution consumer into bookkeeping.
                    api._artifact(fixture.scope, dict(kind="source-import-mandate", source=dict(artifact=first[4])), owner=consumer)
                second_before = self.owner_snapshot(api, context, second[2])
                clock[0] = second[7]["lifecycle"]["safe_closed_at"] + self.retention_age
                report = api._cleanup_closed_details(context)
                self.assertTrue(self.owner_snapshot(api, context, first[2]) == first_after_diagnostic,
                    "Later conversion changed A's protected brief, legacy closure or original diagnostic proof")
                with api._context_database(context) as db:
                    self.assertIsNone(api._retained_for_owner(context, db, first[2]))
                    if independent_execution:
                        after = self.owner_snapshot(api, context, second[2])
                        self.assertEqual({name:value for name,value in after.items() if name != second[5]["name"]},
                            {name:value for name,value in second_before.items() if name != second[5]["name"]})
                        self.assertIsNone(api._retained_for_owner(context, db, second[2]))
                        self.assertNotIn(second[6], report["expired"])
                    else:
                        self.assertIn(second[6], report["expired"], report)
                        retained = api._retained_for_owner(context, db, second[2])
                        self.assertEqual(retained["content"]["numerical"], original_second["numerical"])
                        self.assertEqual(retained["content"]["created_at"], original_second["created_at"])
                        self.assertEqual(retained["content"]["closed_at"], second[7]["lifecycle"]["safe_closed_at"])
                    self.assertEqual(api._read(None, first[6], context=context, db=db), original_first)
                    with self.assertRaises(state.StateError):
                        api._read(None, first[5], context=context, db=db)
                with api._context_database(context, write=True) as db:
                    with self.assertRaisesRegex(state.StateError, "unavailable or expired"):
                        api._admit_content_dependencies(context, db, [dict(kind="artifact", reference=first[5])])
                with self.assertRaisesRegex(state.StateError, "unavailable or expired"):
                    api._artifact(fixture.scope, dict(kind="independent-expired-output", source=first[5]), owner=consumer)

    def protected_brief_owner(self, *, prior_expiry=False):
        if prior_expiry:
            fixture, clock = self.fixture()
            previous = self.closed_output(fixture)
            clock[0] = previous[7]["lifecycle"]["safe_closed_at"] + self.retention_age
            self.assertIn(previous[6], fixture.fixture.api._cleanup_closed_details(previous[1])["expired"])
            closed = self.close_successor(fixture, clock, review=True)
            review = next(attempt for attempt in closed[0]["evidence"]["attempts"] if attempt["kind"] == "review")
        else:
            fixture, clock, review, closed = self.reviewed_owner()
        api = fixture.fixture.api
        identity = fixture.fixture.identity | dict(task_id="brief-consumer", scope_ref="user:brief-consumer")
        task = state.start_task(fixture.scope, identity | dict(mode="editable", decision_ref="user:accepted"))["task"]
        owner = api._artifact_owner(fixture.scope, task)
        api._artifact(fixture.scope, dict(kind="independent-current-brief", source=review["assignment"]), owner=owner)
        clock[0] = closed[7]["lifecycle"]["safe_closed_at"] + self.retention_age
        return fixture, clock, review, closed, owner

    def test_normal_publication_expires_diagnostic_while_brief_stays_required(self):
        for prior_expiry in (False, True):
            with self.subTest(prior_expiry=prior_expiry):
                fixture, clock, review, closed, owner = self.protected_brief_owner(prior_expiry=prior_expiry)
                api, context = fixture.fixture.api, closed[1]
                brief = context.directory / "evidence" / review["assignment"]["name"]
                before = brief.read_bytes()
                api._artifact(fixture.scope, dict(kind="normal-diagnostic-opportunity"), owner=owner)
                self.assertEqual(brief.read_bytes(), before)
                self.assertFalse((context.directory / "evidence" / closed[5]["name"]).exists())
                self.assertTrue((context.directory / "evidence" / closed[6]["name"]).exists())
                with api._context_database(context) as db:
                    self.assertIsNone(api._retained_for_owner(context, db, closed[2]))
                    metadata = state._metadata(db, closed[5]["name"])
                    self.assertEqual(metadata["status"], "expired")
                    self.assertEqual(metadata["closed_at"], closed[7]["lifecycle"]["safe_closed_at"])

    def test_normal_publication_replays_independent_diagnostic_intent_with_required_brief(self):
        for after in (False, True):
            with self.subTest(after=after):
                fixture, clock, review, closed, owner = self.protected_brief_owner()
                api, context = fixture.fixture.api, closed[1]
                brief = context.directory / "evidence" / review["assignment"]["name"]
                before = brief.read_bytes()
                path = context.directory / "evidence" / closed[5]["name"]
                with self.interrupt_unlink(path, after=after):
                    with self.assertRaises(RuntimeError):
                        api._artifact(fixture.scope, dict(kind="normal-diagnostic-interruption"), owner=owner)
                with api._context_database(context) as db:
                    self.assertEqual(state._metadata(db, closed[5]["name"])["status"], "delete_pending")
                    self.assertEqual(state._metadata(db, review["assignment"]["name"])["status"], "live")
                    self.assertIsNone(api._retained_for_owner(context, db, closed[2]))
                api._artifact(fixture.scope, dict(kind="normal-diagnostic-replay"), owner=owner)
                self.assertFalse(path.exists())
                self.assertEqual(brief.read_bytes(), before)

    def test_retained_metadata_cannot_change_its_original_project_owner(self):
        fixture, clock, review, closed = self.eligible()
        api, context = fixture.fixture.api, closed[1]
        support = self.publish_only(fixture, closed)
        metadata = dict(support["metadata"], owner=dict(support["metadata"]["owner"], project_id="foreign-project"))
        with api._context_database(context, write=True) as db:
            db.execute("update evidence_metadata set owner_key=?,data=? where name=?",
                ("project:foreign-project", api._raw(metadata).decode(), support["reference"]["name"]))
        with api._context_database(context) as db:
            with self.assertRaises(state.StateError):
                api._retained_closure_support(context, db, support["reference"])

    def test_duplicate_registered_successor_protects_original_files(self):
        fixture, clock, review, closed = self.eligible()
        api, context = fixture.fixture.api, closed[1]
        support = self.publish_only(fixture, closed)
        original = context.directory / "evidence" / review["assignment"]["name"]
        before = original.read_bytes()
        duplicate = context.directory / "evidence" / ("f" * 32 + ".json")
        duplicate.write_bytes(api._raw(support["content"]))
        duplicate.chmod(0o400)
        metadata = json.loads(api._raw(support["metadata"]))
        metadata["managed"].update(path=str(duplicate), binding=api._binding(duplicate))
        with api._context_database(context, write=True) as db:
            row = list(db.execute("select * from evidence_metadata where name=?", (support["reference"]["name"],)).fetchone())
            row[0], row[8] = duplicate.name, api._raw(metadata).decode()
            db.execute("insert into evidence_metadata values(?,?,?,?,?,?,?,?,?)", row)
        report = api._cleanup_closed_details(context)
        self.assertEqual(original.read_bytes(), before)
        self.assertFalse(report["expired"])
        self.assertTrue(report["protected"] or report["limitations"])

    def test_changed_retained_bytes_protect_original_files(self):
        fixture, clock, review, closed = self.eligible()
        api, context = fixture.fixture.api, closed[1]
        support = self.publish_only(fixture, closed)
        original = context.directory / "evidence" / review["assignment"]["name"]
        before = original.read_bytes()
        retained = context.directory / "evidence" / support["reference"]["name"]
        retained.chmod(0o600)
        retained.write_bytes(api._raw(dict(support["content"], outcome="tampered")))
        retained.chmod(0o400)
        report = api._cleanup_closed_details(context)
        self.assertEqual(original.read_bytes(), before)
        self.assertFalse(report["expired"])
        self.assertTrue(report["protected"] or report["limitations"])

    def test_same_byte_replacement_after_pending_intent_stays_protected(self):
        fixture, clock, review, closed = self.eligible()
        api, context = fixture.fixture.api, closed[1]
        path = context.directory / "evidence" / review["assignment"]["name"]
        with self.interrupt_unlink(path, after=False):
            with self.assertRaises(RuntimeError):
                api._cleanup_closed_details(context)
        replacement = path.parent / "replacement"
        replacement.write_bytes(path.read_bytes())
        replacement.chmod(0o400)
        os.replace(replacement, path)
        before = path.read_bytes()
        report = api._cleanup_closed_details(context)
        self.assertEqual(path.read_bytes(), before)
        self.assertTrue(report["protected"] or report["limitations"])
        with api._context_database(context) as db:
            self.assertEqual(state._metadata(db, path.name)["status"], "delete_pending")

    def test_replaced_evidence_parent_cannot_authorize_replay(self):
        fixture, clock, review, closed = self.eligible()
        api, context = fixture.fixture.api, closed[1]
        path = context.directory / "evidence" / review["assignment"]["name"]
        with self.interrupt_unlink(path, after=False):
            with self.assertRaises(RuntimeError):
                api._cleanup_closed_details(context)
        saved = context.directory / "old-evidence"
        path.parent.rename(saved)
        shutil.copytree(saved, path.parent)
        before = path.read_bytes()
        report = api._cleanup_closed_details(context)
        self.assertEqual(path.read_bytes(), before)
        self.assertTrue(report["protected"] or report["limitations"])
        self.assertFalse(report["expired"])

    def test_parent_swap_after_final_content_read_protects_original_inode(self):
        fixture, clock, review, closed = self.eligible()
        api, context = fixture.fixture.api, closed[1]
        path = context.directory / "evidence" / review["assignment"]["name"]
        before = path.read_bytes()
        read = api._managed_content
        moved = []
        def swap(selected, reference, metadata):
            raw = read(selected, reference, metadata)
            caller = inspect.currentframe().f_back
            while caller is not None and caller.f_code.co_filename.endswith("/unittest/mock.py"):
                caller = caller.f_back
            if caller is not None and caller.f_code.co_name == "_cleanup_closed_details" and reference == review["assignment"] and not moved:
                saved = context.directory / "previous-evidence"
                path.parent.rename(saved)
                shutil.copytree(saved, path.parent)
                moved.append(saved)
            return raw
        with patch.object(api, "_managed_content", side_effect=swap):
            report = api._cleanup_closed_details(context)
        self.assertEqual(len(moved), 1)
        self.assertTrue((moved[0] / path.name).exists(), "parent replacement released original bytes through the old directory")
        self.assertEqual(path.read_bytes(), before)
        self.assertTrue(report["protected"] or report["limitations"])

    def test_independent_current_generic_reference_protects_original_detail(self):
        fixture, clock, review, closed = self.reviewed_owner()
        api, context = fixture.fixture.api, closed[1]
        identity = fixture.fixture.identity | dict(task_id="independent", scope_ref="fixture:independent")
        task = state.start_task(fixture.scope, identity | dict(mode="editable", decision_ref="fixture:accepted"))["task"]
        api._artifact(fixture.scope, dict(kind="unclassified-current-consumer", copied_reference=review["assignment"]),
                      owner=api._artifact_owner(fixture.scope, task))
        clock[0] = closed[7]["lifecycle"]["safe_closed_at"] + self.retention_age
        path = context.directory / "evidence" / review["assignment"]["name"]
        before = path.read_bytes()
        inventory = self.owner_snapshot(api, context, closed[2])
        report = api._cleanup_closed_details(context)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(report["expired"], [closed[5]])
        current = self.owner_snapshot(api, context, closed[2])
        self.assertEqual(current[review["assignment"]["name"]], inventory[review["assignment"]["name"]])
        self.assertEqual(current[closed[6]["name"]], inventory[closed[6]["name"]])
        self.assertTrue({name:value for name,value in current.items() if name != closed[5]["name"]} ==
                        {name:value for name,value in inventory.items() if name != closed[5]["name"]})
        metadata, content = current[closed[5]["name"]]
        self.assertIsNone(content)
        self.assertEqual(metadata["status"], "expired")
        self.assertEqual(metadata["owner"], inventory[closed[5]["name"]][0]["owner"])
        self.assertEqual(metadata["created_at"], inventory[closed[5]["name"]][0]["created_at"])
        self.assertEqual(metadata["closed_at"], closed[7]["lifecycle"]["safe_closed_at"])
        with api._context_database(context) as db:
            self.assertIsNone(api._retained_for_owner(context, db, closed[2]))
        with self.assertRaises(state.StateError):
            api._read(fixture.scope, closed[5])
        self.assertTrue(report["protected"])

    def test_unregistered_orphan_makes_release_coverage_incomplete(self):
        fixture, clock, review, closed = self.eligible()
        api, context = fixture.fixture.api, closed[1]
        orphan = context.directory / "evidence" / ("a" * 32 + ".json")
        orphan.write_text('{"unknown":"fixture"}')
        orphan.chmod(0o400)
        path = context.directory / "evidence" / review["assignment"]["name"]
        before = path.read_bytes()
        report = api._cleanup_closed_details(context)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(report["expired"])
        self.assertFalse(report["project"]["complete"])
        self.assertTrue(report["protected"] or report["limitations"])

    def test_diagnostic_only_api_does_not_claim_pending_brief_ownership(self):
        fixture, clock, review, closed = self.eligible()
        api, context = fixture.fixture.api, closed[1]
        path = context.directory / "evidence" / review["assignment"]["name"]
        with self.interrupt_unlink(path, after=False):
            with self.assertRaises(RuntimeError):
                api._cleanup_closed_details(context)
        before = path.read_bytes()
        report = api._cleanup_diagnostics(context)
        self.assertEqual(path.read_bytes(), before)
        self.assertNotIn(review["assignment"], report["pending"])
        self.assertNotIn(review["assignment"], report["expired"])

    def test_known_physical_accounting_includes_legacy_embedded_detail_without_cap_claim(self):
        fixture, clock, review, closed = self.reviewed_owner()
        api, context = fixture.fixture.api, closed[1]
        with api._context_database(context) as db:
            rows = api._evidence_inventory_rows(db)
        expected = sum(Path(row["metadata"]["managed"]["path"]).stat().st_size for row in rows
            if row["metadata"]["owner"].get("task") == closed[2]
            and (row["metadata"]["class"] == "detail" or row["reference"] == closed[6]))
        total = sum(Path(row["metadata"]["managed"]["path"]).stat().st_size for row in rows)
        with patch.object(api, "_CLOSED_DETAIL_CAP_BYTES", 1):
            report = api._cleanup_closed_details(context)
        self.assertFalse(report["expired"])
        self.assertEqual(report["project"]["closed_detail_bytes"], expected)
        self.assertEqual(report["project"]["physical_bytes"], total)
        self.assertEqual(report["project"]["excess_bytes"], expected - 1)
        self.assertFalse(report["project"]["complete"])
        self.assertIsNone(report["project"]["cap_satisfied"])

    def test_embedded_report_and_assessment_prose_expire_but_findings_survive(self):
        fixture, clock = self.fixture()
        api = fixture.fixture.api
        marker = "fixture-detail-only-report-874291"
        finding = dict(id="retained-finding", severity="medium", scope="general", status="confirmed", location="app.py:1",
                       scenario=marker, evidence=marker, counterevidence=marker)
        assess = api.assess_review
        def with_disposition(scope, request):
            assessment = dict(request["assessment"], dispositions=[dict(finding_id=finding["id"], status="open",
                              reference="fixture:original-disposition")], semantic_coverage=marker)
            return assess(scope, dict(request, assessment=assessment))
        with patch.object(api, "assess_review", side_effect=with_disposition):
            fixture.fixture.review(findings=[finding])
        closed = self.closed_output(fixture)
        context = closed[1]
        clock[0] = closed[7]["lifecycle"]["safe_closed_at"] + self.retention_age
        report = api._cleanup_closed_details(context)
        self.assertFalse(report["protected"], report)
        for path in (context.directory / "evidence").iterdir():
            self.assertNotIn(marker.encode(), path.read_bytes(), path.name)
            self.assertNotIn(b"Qualified in runtime/security review", path.read_bytes(), path.name)
        with api._context_database(context) as db:
            retained = api._retained_for_owner(context, db, closed[2])["content"]
            self.assertEqual(retained["reviews"][0]["findings"], [{key:finding[key]
                for key in ("id","severity","scope","status","location")}])
            self.assertEqual(retained["reviews"][0]["assessments"][0]["assessment"]["dispositions"],
                [dict(finding_id=finding["id"], status="open", reference="fixture:original-disposition")])

    def test_ready_owner_keeps_real_verification_after_detail_expiry(self):
        clock = [1_800_000_000]
        timing = patch.object(state, "_owner_time", side_effect=lambda: clock[0])
        timing.start()
        self.addCleanup(timing.stop)
        fixture = evidence_tests.ReadyClosureTests(methodName="runTest")
        evidence_tests.CanonicalEvidenceTests.setUp(fixture, d4_recovery=True)
        self.addCleanup(fixture.doCleanups)
        task, request = fixture.stopped()
        api = fixture.fixture.api
        context = api._evidence_context(fixture.scope)
        ref = api._canonical_plain(api._artifact_owner(fixture.scope, task).task)
        closed = api.close_task(fixture.scope, fixture.fixture.request(expected_pins=task["pins"]),
                               api._observe_closure((context,), ref))["task"]
        self.assertTrue(api._retire_closed_task(context, ref)["retired"])
        original = api._read(fixture.scope, closed["lifecycle"]["compact"])
        clock[0] = closed["lifecycle"]["safe_closed_at"] + self.retention_age
        report = api._cleanup_closed_details(context)
        self.assertIn(closed["lifecycle"]["compact"], report["expired"], report)
        with api._context_database(context) as db:
            retained = api._retained_for_owner(context, db, ref)["content"]
        self.assertEqual(retained["outcome"], "ready")
        self.assertEqual(retained["numerical"], original["numerical"])
        self.assertEqual(retained["stopped"], original["stopped"])
        self.assertTrue(retained["verifications"])
        self.assertNotIn("blockers", retained["verifications"][0]["result"])

    def test_authentic_linked_history_stays_protected_until_linked_conversion(self):
        clock = [1_800_000_000]
        timing = patch.object(state, "_owner_time", side_effect=lambda: clock[0])
        timing.start()
        self.addCleanup(timing.stop)
        fixture = evidence_tests.LinkedVerificationTests(methodName="runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        from runtime.engine import RuntimeEvent
        for member in fixture.members:
            for kind in ("PreToolUse", "PostToolUse"):
                state.process_event(member.scope, RuntimeEvent(kind, "codex", "parent", member.repo, turn_id="turn",
                    tool_call_id="retention-read", tool_name="read_file", receipt_fingerprint="a" * 64))
        pointer = fixture.verify()["verification"]
        authorities = fixture.preparation_stops(pointer)
        self.assertTrue(fixture.api._prepare_linked_closure(fixture.api._observe_linked_preparation(pointer, authorities))["complete"])
        contexts = tuple(fixture.api._evidence_context(member.scope) for member in fixture.members)
        refs = tuple(fixture.reference(member) for member in fixture.members)
        closed = []
        for index, ref in enumerate(refs):
            closed.append(fixture.api.close_task(fixture.members[index].scope, fixture.linked_closure_request(index),
                fixture.api._observe_closure(contexts, ref))["task"])
        before = [{path.name:path.read_bytes() for path in (context.directory / "evidence").iterdir()}
                  for context in contexts]
        clock[0] = max(task["lifecycle"]["safe_closed_at"] for task in closed) + self.retention_age
        for context, original in zip(contexts, before):
            report = fixture.api._cleanup_closed_details(context)
            self.assertFalse(report["expired"], report)
            self.assertTrue(report["protected"] or report["limitations"])
            self.assertFalse(report["project"]["complete"])
            self.assertEqual({path.name:path.read_bytes() for path in (context.directory / "evidence").iterdir()}, original)
