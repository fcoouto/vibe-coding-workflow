"""Disposable managed guidance inputs; synthetic native fixtures are not client proof."""

from contextlib import ExitStack
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from runtime import changes, delegation, evidence, state
from tests import test_delegation as workers, test_evidence as facts


class ClosureGuidanceInputsTests(unittest.TestCase):
    def ordinary(self, *, retired=False):
        case = workers.AssignedClosureGuidanceTests(methodName="runTest")
        case.setUp()
        self.addCleanup(case.doCleanups)
        if retired:
            _, _, context, _ = case.successor_after_retirement("both")
        else:
            case.fixture.prepare()
            context = evidence._evidence_context(case.fixture.scope)
        return case, context

    def local_only(self):
        stack = ExitStack()
        for module, name in ((evidence, "_context_database"), (evidence, "_bookkeeping_record"),
                (evidence, "_retained_for_owner"), (evidence, "_linked_retained_component"),
                (changes, "_check_stopped_certificate")):
            stack.enter_context(patch.object(module, name, side_effect=AssertionError("Nonlocal guidance input: " + name)))
        return stack

    def finish(self, context, db, inputs):
        assembly = delegation._closure_guidance_assembly(inputs)
        try:
            job = next(assembly)
            while True:
                job = assembly.send(delegation._resolve_closure_guidance_job(context, db, job))
        except StopIteration as done:
            return done.value

    def test_actual_linked_inputs_do_not_open_peer_and_wrapper_still_completes(self):
        case = facts.LinkedVerificationTests(methodName="runTest")
        case.setUp()
        self.addCleanup(case.doCleanups)
        pointer = case.verify()["verification"]
        authorities = case.preparation_stops(pointer)
        self.assertTrue(evidence._prepare_linked_closure(evidence._observe_linked_preparation(pointer, authorities))["complete"])
        contexts = tuple(evidence._evidence_context(member.scope) for member in case.members)
        refs = tuple(case.reference(member) for member in case.members)
        for index, reference in enumerate(refs):
            evidence.close_task(case.members[index].scope, case.linked_closure_request(index),
                evidence._observe_closure(contexts, reference))
        for context, reference in zip(contexts, refs):
            self.assertTrue(evidence._retire_closed_task(context, reference)["retired"])
        context = contexts[0]
        with evidence._context_database(context, write=True) as db:
            records = delegation._ledger(None, db, context=context)
            baseline = delegation._closure_guidance(context, db, records)
            extractor = getattr(delegation, "_closure_guidance_inputs", delegation._closure_guidance)
            with patch.object(evidence, "_context_database", side_effect=AssertionError("Second connection")):
                inputs = extractor(context, db, records)
            self.assertEqual(self.finish(context, db, inputs), baseline)
            assembly = delegation._closure_guidance_assembly(inputs)
            job = next(assembly)
            with self.assertRaisesRegex(state.StateError, "Unresolved guidance"):
                assembly.send(None)
            corrupted = deepcopy(inputs)
            for index, row in enumerate(corrupted["rows"]):
                reference = dict(name=row[0], digest=row[1])
                key = evidence._raw(reference).decode()
                if corrupted["bodies"].get(key, {}).get("kind") == "linked-closure-preparation":
                    wrong = dict(reference, name="f" * 32 + ".json")
                    corrupted["bodies"][evidence._raw(wrong).decode()] = corrupted["bodies"][key]
                    corrupted["rows"][index] = (wrong["name"], *row[1:])
                    break
            with self.assertRaises((state.StateError, KeyError, StopIteration)):
                self.finish(context, db, corrupted)
            preparation = next(row for row in inputs["rows"] if inputs["bodies"].get(
                evidence._raw(dict(name=row[0], digest=row[1])).decode(), {}).get("kind") == "linked-closure-preparation")
            db.execute("savepoint wrong_preparation_pointer")
            db.execute("update evidence_metadata set name=? where name=?", ("f" * 32 + ".json", preparation[0]))
            with self.local_only(), self.assertRaises(state.StateError):
                delegation._closure_guidance_inputs(context, db, records)
            db.execute("rollback to wrong_preparation_pointer")
            db.execute("release wrong_preparation_pointer")

    def test_local_native_cache_and_full_ordinary_wrapper_match(self):
        case, context = self.ordinary()
        with evidence._context_database(context) as db:
            records = delegation._ledger(None, db, context=context)
            baseline = delegation._closure_guidance(context, db, records)
            with self.local_only():
                inputs = delegation._closure_guidance_inputs(context, db, records)
            self.assertEqual(self.finish(context, db, inputs), baseline)
            self.assertTrue(baseline["native"])
            self.assertEqual(len(baseline["files"]), 2)
            self.assertEqual(delegation._closure_guidance(context, db, records), baseline)
            assembly = delegation._closure_guidance_assembly(inputs)
            job = next(assembly)
            with self.assertRaisesRegex(state.StateError, "Unresolved guidance"):
                assembly.send(dict(job=job | dict(kind="wrong-job"), result=True))

    def historical_only_without_cache(self):
        case = workers.AssignedClosureGuidanceTests(methodName="runTest")
        case.setUp()
        self.addCleanup(case.doCleanups)
        task, context, reference = case.stop_current_task()
        closed = evidence.close_task(case.fixture.scope, case.fixture.request(expected_pins=task["pins"]),
            evidence._observe_closure((context,), reference))["task"]
        compact = evidence._read(case.fixture.scope, closed["lifecycle"]["compact"])
        self.assertTrue(compact["scope_guidance"])
        self.assertFalse(compact["native_guidance"])
        self.assertFalse(compact["stopped"]["assignments"])
        self.assertTrue(evidence._retire_closed_task(context, reference)["retired"])
        surface = case.fixture.cache_request["client_surface"]
        for suffix in (".json", ".control.json"):
            (context.directory / "model-guidance" / (surface + suffix)).unlink()
        return case, context, reference, closed["lifecycle"]["compact"]

    def test_retired_non_native_history_without_cache_keeps_old_empty_surface_result(self):
        _, context, reference, compact = self.historical_only_without_cache()
        def managed_snapshot(db):
            return [(row, (context.directory / "evidence" / row["reference"]["name"]).read_bytes())
                    for row in evidence._evidence_inventory_rows(db)]
        with evidence._context_database(context) as db:
            before = managed_snapshot(db)
            marker = state._retired(db, "task", {key:reference[key] for key in ("scope_id", "client", "session_id", "task_id")})
            records = delegation._ledger(None, db, context=context)
            self.assertFalse(records)
            with self.local_only():
                inputs = delegation._closure_guidance_inputs(context, db, records)
            self.assertIsNone(inputs["cache"]["folder"])
            resolve = delegation._resolve_closure_guidance_job
            jobs = []
            def observed(*args):
                jobs.append(args[-1]["kind"])
                return resolve(*args)
            with patch.object(delegation, "_resolve_closure_guidance_job", side_effect=observed):
                result = delegation._closure_guidance(context, db, records)
            self.assertIn("stopped-certificate", jobs)
            self.assertEqual(result["references"], [])
            self.assertEqual(result["sources"], [])
            self.assertEqual(result["native"], [])
            self.assertEqual(result["files"], {})
            self.assertIsNone(result["folder"])
            self.assertEqual(result["retained"], [dict(reference=compact, identity=reference, marker=marker, assignments=[])])
            self.assertEqual(self.finish(context, db, inputs), result)
            self.assertEqual(managed_snapshot(db), before)

    def test_retired_native_sources_keep_ages_and_complete_stop_jobs(self):
        _, context = self.ordinary(retired=True)
        with evidence._context_database(context) as db:
            records = delegation._ledger(None, db, context=context)
            baseline = delegation._closure_guidance(context, db, records)
            with self.local_only():
                inputs = delegation._closure_guidance_inputs(context, db, records)
            self.assertEqual(self.finish(context, db, inputs), baseline)
            self.assertTrue(baseline["retained"])
            self.assertGreaterEqual(len(baseline["sources"]), 3)

    def test_owner_native_correspondence_and_cache_corruption_reject(self):
        case, context = self.ordinary()
        with evidence._context_database(context) as db:
            records = delegation._ledger(None, db, context=context)
            with self.local_only():
                inputs = delegation._closure_guidance_inputs(context, db, records)
            bad = deepcopy(inputs)
            native = next(record for record in bad["records"] if record["data"]["role"] in delegation.NATIVE_ROLES)
            native["body"]["guidance"]["checked_at"] = "2020-01-01T00:00:00Z"
            with self.assertRaises(state.StateError):
                self.finish(context, db, bad)
            bad = deepcopy(inputs)
            source = next(value for value in bad["metadata"].values() if value["owner"]["task"] is None and value["class"] == "detail")
            source["owner"]["task"] = dict(task_id="wrong-owner")
            with self.assertRaises(state.StateError):
                self.finish(context, db, bad)
        path = context.directory / "model-guidance" / (case.fixture.cache_request["client_surface"] + ".control.json")
        control = json.loads(path.read_bytes())
        control["last_attempt"]["key"] = "f" * 64
        path.write_text(json.dumps(control))
        with evidence._context_database(context) as db, self.local_only(), self.assertRaises(state.StateError):
            delegation._closure_guidance_inputs(context, db, records)

    def test_actual_managed_guidance_owner_corruption_rejects(self):
        case, context = self.ordinary()
        with evidence._context_database(context, write=True) as db:
            records = delegation._ledger(None, db, context=context)
            reference = records[0]["body"]["guidance"]["snapshot_ref"]
            metadata = state._metadata(db, reference["name"])
            task = state._task(db, state._scope_id(case.fixture.scope), "codex", "parent")
            metadata["owner"]["task"] = evidence._canonical_plain(evidence._artifact_owner(case.fixture.scope, task).task)
            db.execute("savepoint wrong_source_owner")
            db.execute("update evidence_metadata set data=? where name=?", (json.dumps(metadata), reference["name"]))
            with self.local_only():
                inputs = delegation._closure_guidance_inputs(context, db, records)
            with self.assertRaisesRegex(state.StateError, "scope ownership"):
                self.finish(context, db, inputs)
            db.execute("rollback to wrong_source_owner")
            db.execute("release wrong_source_owner")

    def test_cache_change_during_complete_validation_cannot_return_stale_inputs(self):
        case, context = self.ordinary()
        path = context.directory / "model-guidance" / (case.fixture.cache_request["client_surface"] + ".control.json")
        resolve = delegation._resolve_closure_guidance_job
        changed = []
        def mutate(*args):
            result = resolve(*args)
            if not changed:
                control = json.loads(path.read_bytes())
                control["last_attempt"]["key"] = "f" * 64
                path.write_text(json.dumps(control))
                changed.append(True)
            return result
        with evidence._context_database(context) as db:
            records = delegation._ledger(None, db, context=context)
            with patch.object(delegation, "_resolve_closure_guidance_job", side_effect=mutate):
                with self.assertRaises(state.StateError):
                    delegation._closure_guidance(context, db, records)
