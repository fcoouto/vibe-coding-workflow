"""Fresh screening accounting is born only by the real temporary owner producer."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from runtime import evidence, state
from tests import test_project_owner_storage as project_fixtures
from tests import test_review_storage as storage_fixtures


def fresh_screening():
    return dict(version=1, birth="temporary-owner-publication", limit_ms=300000,
                revision=0, charged_ms=0, settled_sequence=0,
                reservation=None, last_receipt=None)


def screening_states():
    ticket = dict(sequence=1, nonce="a" * 32, ceiling_ms=300000)
    fresh = fresh_screening()
    reserved = dict(fresh, revision=1, reservation=ticket)
    settled = dict(fresh, revision=2, charged_ms=300000, settled_sequence=1,
                   last_receipt=dict(ticket=ticket, disposition="charged-full"))
    return fresh, reserved, settled


class ScreeningMetadataTests(unittest.TestCase):
    def setUp(self):
        self.fixture = storage_fixtures.ReviewStorageTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.api = self.fixture.load_api()
        self.fixture.prepare()

    @contextmanager
    def store(self, *, write=False):
        with self.api._machine_guard() as (path, descriptor, parents):
            config = self.api._configuration(path, descriptor)
            context = self.api._ready_context(config, parents)
            with evidence._context_database(context, write=write, durable=write) as db:
                yield config, context, db

    def owner(self):
        result = self.fixture.resolve(self.fixture.repo)
        self.assertTrue(result.get("ok"), result)
        return result

    def row(self, reference):
        with self.store() as (_, _, db):
            return db.execute("select name,digest,owner_key,class,created_at,closed_at,status,bytes,data "
                              "from evidence_metadata where name=?", (reference["name"],)).fetchone()

    @staticmethod
    def changed_row(row, value):
        result = list(row)
        result[2] = ("temporary:" + value["owner"]["id"] if value["owner"]["kind"] == "temporary"
                     else "project:" + value["owner"]["project_id"])
        for index, field in ((3, "class"), (4, "created_at"), (5, "closed_at"), (6, "status"), (7, "bytes")):
            result[index] = value[field]
        result[8] = evidence._raw(value).decode()
        return tuple(result)

    def test_actual_target_publication_birth_preserves_content_identity_and_age(self):
        target_before = self.fixture.tree_snapshot(self.fixture.repo)
        first = self.owner()
        with self.store() as (config, context, db):
            metadata = state._metadata(db, first["reference"]["name"])
            content = evidence._read(None, first["reference"], context=context, db=db)
            provenance = state._metadata(db, config["provenance"]["name"])
            managed = Path(metadata["managed"]["path"]).read_bytes()
        self.assertEqual(metadata.get("screening"), fresh_screening())
        self.assertNotIn("screening", provenance)
        self.assertEqual(content["kind"], "temporary-target-owner")
        self.assertNotIn("screening", content)
        self.assertEqual(metadata["version"], 2)
        self.assertEqual(metadata["owner"], first["owner"])
        self.assertEqual(metadata["created_at"], first["created_at"])
        self.assertEqual(content["created_at"], first["created_at"])
        self.assertEqual(first["reference"]["digest"], hashlib.sha256(managed).hexdigest())
        self.assertEqual(metadata["bytes"], len(managed))
        self.assertEqual(metadata["dependencies"], [])
        private_before = self.fixture.tree_snapshot(self.fixture.private)
        self.assertEqual(self.fixture.resolve(self.fixture.repo / "subset"), first)
        self.assertEqual(self.fixture.tree_snapshot(self.fixture.private), private_before)
        self.assertEqual(self.fixture.tree_snapshot(self.fixture.repo), target_before)

    def test_strict_reader_accepts_only_the_three_exact_states(self):
        row = self.row(self.owner()["reference"])
        original = json.loads(row[8])
        for version in (1, 2):
            for screening in screening_states():
                with self.subTest(version=version, revision=screening["revision"]):
                    value = dict(original, version=version, screening=screening)
                    self.assertEqual(state._metadata_record(self.changed_row(row, value)), value)

    def test_strict_reader_rejects_unknown_boolean_and_inconsistent_screening(self):
        row = self.row(self.owner()["reference"])
        original = json.loads(row[8])
        fresh, reserved, settled = screening_states()
        invalid = [None, {}, [], dict(fresh, extra=True), dict(fresh, version=2),
                   dict(fresh, birth="caller-asserted"), dict(fresh, limit_ms=299999),
                   dict(fresh, revision=3), dict(fresh, charged_ms=1),
                   dict(fresh, settled_sequence=1), dict(fresh, reservation=reserved["reservation"]),
                   dict(reserved, reservation=None), dict(reserved, charged_ms=300000),
                   dict(reserved, last_receipt=settled["last_receipt"]),
                   dict(settled, reservation=reserved["reservation"]),
                   dict(settled, charged_ms=0), dict(settled, settled_sequence=0),
                   dict(settled, last_receipt=None)]
        for field in ("version", "limit_ms", "revision", "charged_ms", "settled_sequence"):
            invalid.append(dict(fresh, **{field: False}))
        for field, value in (("sequence", True), ("sequence", 2), ("nonce", "A" * 32),
                             ("nonce", "a" * 31), ("nonce", "z" * 32),
                             ("ceiling_ms", True), ("ceiling_ms", 1), ("extra", 0)):
            ticket = dict(reserved["reservation"], **{field: value})
            invalid.append(dict(reserved, reservation=ticket))
            invalid.append(dict(settled, last_receipt=dict(ticket=ticket, disposition="charged-full")))
        invalid.extend((dict(settled, last_receipt=dict(ticket=reserved["reservation"], disposition="refunded")),
                        dict(settled, last_receipt=dict(settled["last_receipt"], extra=0))))
        for index, screening in enumerate(invalid):
            with self.subTest(case=index, screening=screening):
                with self.assertRaises(state.StateError):
                    state._metadata_record(self.changed_row(row, dict(original, screening=screening)))

    def test_screening_cannot_be_placed_on_provenance_or_non_anchor_metadata(self):
        owner = self.owner()
        row = self.row(owner["reference"])
        value = dict(json.loads(row[8]), screening=fresh_screening())
        placements = [dict(value, owner=dict(kind="project", project_id="fixture", task=None)),
                      dict(value, targets=[]), dict(value, **{"class": "detail"}),
                      dict(value, closed_at=value["created_at"]),
                      dict(value, status="delete_pending"), dict(value, status="expired"),
                      dict(value, export={"kind": "managed-copy"}),
                      dict(value, dependencies=[dict(kind="artifact", reference=owner["reference"])])]
        with self.store() as (config, _, db):
            provenance_row = db.execute("select name,digest,owner_key,class,created_at,closed_at,status,bytes,data "
                                        "from evidence_metadata where name=?", (config["provenance"]["name"],)).fetchone()
        placements_with_rows = [(row, item) for item in placements]
        placements_with_rows.append((provenance_row, dict(json.loads(provenance_row[8]), screening=fresh_screening())))
        for index, (original, changed) in enumerate(placements_with_rows):
            with self.subTest(case=index):
                with self.assertRaises(state.StateError):
                    state._metadata_record(self.changed_row(original, changed))

    def test_legacy_absence_is_valid_and_real_owner_replay_never_retrofits_it(self):
        first = self.owner()
        row = self.row(first["reference"])
        legacy = json.loads(row[8])
        legacy.pop("screening", None)
        for version in (1, 2):
            value = dict(legacy, version=version)
            self.assertEqual(state._metadata_record(self.changed_row(row, value)), value)
        with self.store(write=True) as (_, _, db):
            db.execute("update evidence_metadata set data=? where name=?", (evidence._raw(legacy).decode(), row[0]))
        before = self.fixture.tree_snapshot(self.fixture.private)
        self.assertEqual(self.owner(), first)
        self.assertEqual(self.fixture.tree_snapshot(self.fixture.private), before)
        self.assertNotIn("screening", json.loads(self.row(first["reference"])[8]))

    def test_real_producer_rejects_duplicate_related_owner_and_generic_content(self):
        first = self.owner()
        with self.store(write=True) as (_, context, db):
            content = evidence._read(None, first["reference"], context=context, db=db)
            duplicate = deepcopy(content)
            duplicate["owner"]["id"] = "b" * 32
            before = list(db.iterdump())
            for candidate in (duplicate, dict(version=1, kind="arbitrary", owner=duplicate["owner"],
                                               created_at=duplicate["created_at"])):
                with self.subTest(kind=candidate["kind"]):
                    with self.assertRaises(state.StateError):
                        self.api._register(context, db, candidate, [content["target"]])
                    self.assertEqual(list(db.iterdump()), before)

    def test_real_producer_requires_acquired_guard_context_not_copied_equal_context(self):
        with self.store() as (config, context, _):
            provenance = deepcopy(config["provenance"])
        observed = self.api._observe_target(self.fixture.repo)
        created_at = state._owner_time()
        content = dict(version=1, kind="temporary-target-owner",
                       owner=dict(kind="temporary", id="c" * 32, created_at=created_at),
                       created_at=created_at, target=observed, provenance=provenance)
        before = self.fixture.tree_snapshot(self.fixture.private)
        for selected in (context, replace(context)):
            with self.subTest(copied=selected is not context):
                with self.assertRaises(state.StateError):
                    with evidence._context_database(selected, write=True, durable=True) as db:
                        self.api._register(selected, db, content, [observed])
        self.assertEqual(self.fixture.tree_snapshot(self.fixture.private), before)

    def test_nonempty_canonical_writer_domain_prevents_actual_owner_birth(self):
        with self.store(write=True) as (_, _, db):
            db.execute("insert into retired_identities values(?,?,?,?)",
                       ("task", "a" * 64, "fixture:unrelated-writer", None))
        before = self.fixture.tree_snapshot(self.fixture.private)
        result = self.fixture.resolve(self.fixture.repo)
        self.assertFalse(result.get("ok"), result)
        self.assertEqual(result.get("status"), "protected", result)
        self.assertEqual(self.fixture.tree_snapshot(self.fixture.private), before)

    def test_post_publication_domain_change_rolls_back_screening_birth(self):
        register = self.api._register
        with self.store() as (_, _, db):
            before = list(db.iterdump())

        def contaminate_after_publication(context, db, *args, **kwargs):
            reference = register(context, db, *args, **kwargs)
            db.execute("insert into retired_identities values(?,?,?,?)",
                       ("task", "a" * 64, "fixture:late-writer", None))
            return reference

        with patch.object(self.api, "_register", side_effect=contaminate_after_publication):
            result = self.fixture.resolve(self.fixture.repo)
        self.assertFalse(result.get("ok"), result)
        self.assertEqual(result.get("status"), "protected", result)
        with self.store() as (_, _, db):
            self.assertEqual(list(db.iterdump()), before)


class UmbrellaScreeningMetadataTests(unittest.TestCase):
    def setUp(self):
        self.fixture = project_fixtures.ProjectOwnerStorageTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.prepare()

    def test_actual_umbrella_anchor_birth_binds_complete_root_and_members(self):
        before = self.fixture.snapshot_targets()
        result = self.fixture.project_owner()
        self.assertTrue(result.get("ok"), result)
        api = self.fixture.api
        with api._machine_guard() as (path, descriptor, parents):
            config = api._configuration(path, descriptor)
            context = api._ready_context(config, parents)
            with evidence._context_database(context) as db:
                metadata = state._metadata(db, result["reference"]["name"])
                content = evidence._read(None, result["reference"], context=context, db=db)
        self.assertEqual(metadata.get("screening"), fresh_screening())
        self.assertEqual(content["kind"], "temporary-project-owner")
        self.assertNotIn("screening", content)
        self.assertEqual(metadata["owner"], result["owner"])
        self.assertEqual(metadata["created_at"], result["created_at"])
        self.assertEqual(metadata["dependencies"], [])
        self.assertEqual({target["path"] for target in metadata["targets"]},
                         {str(self.fixture.project), str(self.fixture.first), str(self.fixture.second)})
        self.assertEqual(self.fixture.snapshot_targets(), before)


class EnrolledScreeningMetadataTests(unittest.TestCase):
    def test_fresh_enrolled_baseline_and_generic_artifact_never_birth_allowance(self):
        fixture = storage_fixtures.EnrolledReviewStorageTests(methodName="runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        api = evidence
        scope = fixture.fixture.scope
        owner = fixture.api.resolve_owner(str(fixture.fixture.fixture.repo))
        self.assertTrue(owner.get("ok"), owner)
        context = api._evidence_context(scope)
        artifact = api._artifact(scope, dict(kind="fixture-generic-screening", screening=fresh_screening()),
                                 owner=api._guidance_artifact_owner(scope))
        with api._context_database(context) as db:
            for reference in (owner["reference"], artifact):
                metadata = state._metadata(db, reference["name"])
                self.assertNotIn("screening", metadata)


if __name__ == "__main__":
    unittest.main()
