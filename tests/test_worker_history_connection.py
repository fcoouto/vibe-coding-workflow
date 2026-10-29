"""Actual SQLite writer visibility; native observations are disposable fixture facts."""

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from runtime import delegation, evidence, state
from tests import test_evidence as evidence_tests


class WorkerHistoryConnectionTests(unittest.TestCase):
    def setUp(self):
        fixture = evidence_tests.CanonicalEvidenceTests(methodName="runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture.fixture
        self.scope = fixture.scope
        self.fixture.plan()
        self.fixture.review()
        self.context = evidence._evidence_context(self.scope)
        with evidence._context_database(self.context) as db:
            self.task = state._task(db, state._scope_id(self.scope), "codex", "parent")
            self.records = delegation._ledger(None, db, context=self.context)
        self.attempt = next(item for item in self.task["evidence"]["attempts"] if item["kind"] == "review")
        self.record = next(item for item in self.records if item["id"] == self.attempt["id"])
        self.owner = evidence._artifact_owner(self.scope, self.task)
        self.original = evidence._read(self.scope, self.record["data"]["observation"])
        self.collected = evidence._read(self.scope, self.attempt["collected"])

    def publish(self, db, body):
        return evidence._artifact(self.scope, body, owner=self.owner, db=db)

    def writer_chain(self, db):
        # Re-register actual native fixture facts, with genuine new managed rows on this writer.
        incoming = evidence._read(self.scope, self.original["incoming"])
        previous = self.publish(db, self.original | dict(incoming=self.publish(db, incoming)))
        head = self.publish(db, self.original | dict(incoming=self.publish(db, incoming),
            previous=previous, revision=self.original["revision"] + 1))
        record = deepcopy(self.record)
        record["data"]["observation"] = head
        attempt = deepcopy(self.attempt)
        attempt["collected"] = self.publish(db, self.collected)
        return head, previous, record, attempt

    def no_second_connection(self):
        return patch.object(evidence, "_context_database", side_effect=AssertionError("Opened a second connection"))

    def test_writer_reads_uncommitted_observed_incoming_previous_and_collection(self):
        with evidence._context_database(self.context, write=True) as db:
            head, previous, record, attempt = self.writer_chain(db)
            for reference in (head, previous, attempt["collected"]):
                self.assertTrue(Path(state._metadata(db, reference["name"])["managed"]["path"]).is_file())
                with evidence._context_database(self.context) as reader:
                    self.assertIsNone(state._metadata(reader, reference["name"]))
                with self.assertRaises(state.StateError):
                    evidence._read(None, reference, context=self.context)
            with self.assertRaises(state.StateError):
                delegation._worker_history(None, head, context=self.context)
            with self.no_second_connection():
                history = delegation._worker_history(None, head, context=self.context, db=db)
                self.assertEqual([reference for reference, _ in history], [head, previous])
                self.assertTrue(evidence._review_quality_matches(None, attempt, record, context=self.context, db=db))

    def test_preloaded_collection_still_uses_writer_for_history(self):
        with evidence._context_database(self.context, write=True) as db:
            _, _, record, attempt = self.writer_chain(db)
            with self.no_second_connection():
                self.assertTrue(evidence._review_quality_matches(None, attempt, record, self.collected,
                    context=self.context, db=db))

    def test_closure_projection_uses_writer_for_review_and_worker_history(self):
        with evidence._context_database(self.context, write=True) as db:
            head, _, record, attempt = self.writer_chain(db)
            task = deepcopy(self.task)
            task["evidence"]["attempts"] = [attempt]
            records = [record if item["id"] == record["id"] else item for item in self.records]
            with self.no_second_connection():
                result = evidence._closure_assignment_projection(self.context, db, task, records)
            self.assertEqual(result["reviews"][0]["report"], self.collected["report"])
            self.assertEqual(result["workers"][0]["observations"][0]["source"], head)

    def test_writer_chain_corruption_and_bound_still_reject(self):
        with evidence._context_database(self.context, write=True) as db:
            head, previous, _, _ = self.writer_chain(db)
            with self.no_second_connection():
                with patch.object(delegation, "MAX_OBSERVATIONS", 1):
                    with self.assertRaisesRegex(state.StateError, "history bound"):
                        delegation._worker_history(None, head, context=self.context, db=db)
            invalid = self.publish(db, self.original | dict(version=2))
            with self.no_second_connection(), self.assertRaisesRegex(state.StateError, "incompatible"):
                delegation._worker_history(None, invalid, context=self.context, db=db)
            incoming = evidence._read(None, previous, context=self.context, db=db)["incoming"]
            for reference in (previous, incoming):
                with self.subTest(missing=reference):
                    path = Path(state._metadata(db, reference["name"])["managed"]["path"])
                    db.execute("savepoint missing_history")
                    db.execute("delete from evidence_metadata where name=?", (reference["name"],))
                    self.assertTrue(path.is_file(), "Physical bytes cannot replace missing managed metadata")
                    with self.no_second_connection(), self.assertRaises(state.StateError):
                        delegation._worker_history(None, head, context=self.context, db=db)
                    db.execute("rollback to missing_history")
                    db.execute("release missing_history")

    def test_writer_review_requires_exact_latest_receipt_and_report(self):
        with evidence._context_database(self.context, write=True) as db:
            _, _, record, attempt = self.writer_chain(db)
            for field in ("reviewer_id", "review_turn_id", "report_item_id", "report_digest",
                          "parent_turn_id", "spawn_item_id", "task_name", "agent_path", "native_version",
                          "parent_session_id", "assignment_digest", "candidate_digest", "requested_model", "requested_effort"):
                with self.subTest(receipt=field):
                    bad = deepcopy(self.collected)
                    bad["receipt"][field] = "different"
                    selected = attempt | dict(collected=self.publish(db, bad))
                    with self.no_second_connection():
                        self.assertFalse(evidence._review_quality_matches(None, selected, record,
                            context=self.context, db=db))
            bad = deepcopy(self.collected)
            bad["report"]["limitations"] = ["Different actual report"]
            selected = attempt | dict(collected=self.publish(db, bad))
            with self.no_second_connection():
                self.assertFalse(evidence._review_quality_matches(None, selected, record, context=self.context, db=db))
            for field, value in (("status", "uncertain"), ("error", "failed"), ("conflict", record["data"]["observation"])):
                selected_record = deepcopy(record)
                selected_record["data"]["observation"] = self.publish(db, self.original | {field:value})
                with self.subTest(observation=field), self.no_second_connection():
                    self.assertFalse(evidence._review_quality_matches(None, attempt, selected_record,
                        context=self.context, db=db))

    def test_omitted_db_preserves_scope_and_context_behavior(self):
        reference = self.record["data"]["observation"]
        history = delegation._worker_history(self.scope, reference)
        self.assertEqual(delegation._worker_history(None, reference, context=self.context), history)
        self.assertTrue(evidence._review_quality_matches(self.scope, self.attempt, self.record))
        self.assertTrue(evidence._review_quality_matches(None, self.attempt, self.record, context=self.context))
        with evidence._context_database(self.context) as db, self.no_second_connection():
            self.assertEqual(delegation._worker_history(None, reference, context=self.context, db=db), history)
            self.assertEqual(delegation._worker_history(self.scope, reference, db=db), history)
            self.assertTrue(evidence._review_quality_matches(None, self.attempt, self.record, context=self.context, db=db))
            self.assertTrue(evidence._review_quality_matches(self.scope, self.attempt, self.record, db=db))
