"""Local recovery comparisons and real legacy host publication; activation gates stay closed."""

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from runtime import evidence, recovery_uses, state
from tests import test_changes, test_d4_recovery_faults, test_d4_historical_witness


class RecoveryUseInputsTests(unittest.TestCase):
    def comparison_authority(self, index=0):
        directory = "/legacy/" + str(index).zfill(4) + "/" + "a" * 1000
        value = dict(directory=directory, database=directory + "/runtime.sqlite3",
            directory_binding=dict(device=1, inode=2), database_binding=dict(device=1, inode=3))
        recovery_uses._authority(value)
        return value

    def comparison_source(self, index, authorities, previous=None):
        reference = dict(name=format(index, "032x") + ".json", digest=format(index, "064x"))
        identity = dict(plan_dir="/legacy-plan", transaction_id="legacy", manifest_digest="a" * 64)
        body = dict(version=1, kind="d4-recovery-source", identity=identity,
            journal=dict(sha256=format(index, "064x"), observed_at=1, state="interrupted"),
            authorities=authorities, tasks=[], assignments=[], artifacts=[], previous=previous)
        evidence._recovery_source_shape(body, identity)
        return dict(reference=reference, content=body)

    def test_legacy_comparison_aggregate_exceeds_contract_limit_without_becoming_contract(self):
        # Representative validated pure inputs, not a stored owner or runtime qualification.
        authority = self.comparison_authority()
        history = []
        for index in range(1, 2001):
            history.append(self.comparison_source(index, [authority], history[-1]["reference"] if history else None))
        inputs = dict(authority=authority, history=history, jobs=[])
        projected = evidence._recovery_admission_projection(inputs)
        rows = projected["legacy_routes"]
        self.assertEqual(len(rows), 2000)
        self.assertGreater(len(recovery_uses.key(rows).encode()), recovery_uses.MAX_BYTES)
        self.assertLess(max(len(recovery_uses.key(item["content"]).encode()) for item in history), recovery_uses.MAX_BYTES)
        self.assertEqual(rows, sorted(rows, key=recovery_uses.key))
        repeated = dict(inputs, history=list(reversed(history)) + [history[0]])
        self.assertEqual(evidence._recovery_admission_projection(repeated), projected)
        with self.assertRaisesRegex(recovery_uses.UseContractError, "byte bound"):
            recovery_uses.build([], [], rows)
        restricted = deepcopy(history[0])
        restricted["content"]["use_contract"] = dict(version=1, roots=[], edges=[], legacy_routes=[])
        restricted_projection = evidence._recovery_admission_projection(dict(inputs, history=[restricted]))
        self.assertEqual(restricted_projection['legacy_routes'], [])
        self.assertEqual(restricted_projection['restricted_routes'][0]['use_contract'], restricted['content']['use_contract'])
        self.assertEqual(restricted_projection['restricted_routes'][0]['origin']['artifact'], restricted['reference'])
        mixed = deepcopy(history[0])
        other = self.comparison_authority(1)
        mixed["content"]["authorities"] = [other, authority, authority]
        small = evidence._recovery_admission_projection(dict(inputs, history=[history[1], mixed, mixed]))["legacy_routes"]
        self.assertEqual(len(small), 2)
        self.assertEqual(small, sorted(small, key=recovery_uses.key))
        row = next(row for row in small if row["origin"]["artifact"] == mixed["reference"])
        self.assertEqual(row["origin"], dict(authority=authority, artifact=mixed["reference"],
            identity=mixed["content"]["identity"], journal_sha256=mixed["content"]["journal"]["sha256"]))
        self.assertEqual(row["destinations"], sorted([authority, other], key=recovery_uses.key))
        conflict = deepcopy(mixed)
        conflict["content"]["authorities"] = [authority]
        with self.assertRaisesRegex(recovery_uses.UseContractError, "Conflicting legacy"):
            evidence._recovery_admission_projection(dict(inputs, history=[mixed, conflict]))

    def test_one_legacy_origin_comparison_can_exceed_limit_of_its_valid_source(self):
        template = self.comparison_source(1, [])
        entry_bytes = len(recovery_uses.key(self.comparison_authority()).encode()) + 1
        count = (recovery_uses.MAX_BYTES - len(recovery_uses.key(template["content"]).encode()) - 10) // entry_bytes
        self.assertLessEqual(count, recovery_uses.MAX_ROWS)
        authorities = [self.comparison_authority(index) for index in range(count)]
        item = self.comparison_source(1, authorities)
        remaining = recovery_uses.MAX_BYTES - len(recovery_uses.key(item["content"]).encode()) - 10
        self.assertGreater(remaining, 0)
        self.assertLess(remaining, 4096)
        item["content"]["identity"]["plan_dir"] += "p" * remaining
        evidence._recovery_source_shape(item["content"], item["content"]["identity"])
        self.assertLessEqual(len(recovery_uses.key(item["content"]).encode()), recovery_uses.MAX_BYTES)
        result = evidence._recovery_admission_projection(dict(authority=authorities[0], history=[item], jobs=[]))
        self.assertGreater(len(recovery_uses.key(result["legacy_routes"][0]).encode()), recovery_uses.MAX_BYTES)
        with self.assertRaisesRegex(recovery_uses.UseContractError, "byte bound"):
            recovery_uses.build([], [], result["legacy_routes"])
        invalid = deepcopy(item)
        invalid["content"]["journal"]["sha256"] = "bad"
        with self.assertRaises(recovery_uses.UseContractError):
            evidence._recovery_admission_projection(dict(authority=authorities[0], history=[invalid], jobs=[]))

    def fixture(self):
        case = test_changes.ScopedChangesTests(methodName="runTest")
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.addCleanup(case.tearDown)
        return case

    def test_real_host_freezes_projection_and_replays_same_writer_registration(self):
        case = self.fixture()
        request, contexts = case.d4_bookkeeping_request()
        changes = case.changes
        facts = []
        replayed = []
        class Host:
            def acquire_d4_bookkeeping(self, acquired, issue):
                facts.append(evidence._canonical_plain(acquired))
                return issue(acquired)
        register = evidence._register_recovery_source
        def replay(*args, **kwargs):
            first = register(*args, **kwargs)
            context, db, source = kwargs["context"], args[1], args[2]
            identity = evidence._canonical_plain(source.content)["identity"]
            with patch.object(evidence, "_context_database", side_effect=AssertionError("second connection")):
                inputs = evidence._recovery_use_inputs(context, db, evidence._canonical_plain(first), identity)
            self.assertEqual(inputs["history"][0]["reference"], evidence._canonical_plain(first))
            second = register(*args, **kwargs)
            self.assertEqual(first, second)
            replayed.append(True)
            return first
        with changes._bootstrap_d4_host(Host(), issuer=changes._D4_HOST_BOOTSTRAP_ISSUER) as host:
            with patch.object(evidence, "_register_recovery_source", side_effect=replay):
                result = changes._run_scoped(case.directory, request, "apply", host=host)
        self.assertEqual(result["exit_code"], 0, result)
        self.assertTrue(replayed)
        for acquired in facts:
            projections = acquired["registration_projections"]
            self.assertEqual(set(projections), {str(contexts[0].database)})
            projection = projections[str(contexts[0].database)]
            self.assertEqual(projection["source"], acquired["source"])
            self.assertEqual(projection["created_at"], acquired["created_at"])
            self.assertNotIn("use_contract", projection["content"])

    def test_local_inputs_use_actual_connection_and_preserve_partial_peer_heads(self):
        case = test_d4_recovery_faults.D4RecoveryFaultTests(methodName="runTest")
        case.setUp()
        self.addCleanup(case.doCleanups)
        captured = []
        observe = case.fixture.changes._observe_recovery_source
        def actual(*args, **kwargs):
            source = observe(*args, **kwargs)
            captured.append(source)
            return source
        with patch.object(case.fixture.changes, "_observe_recovery_source", side_effect=actual):
            case.test_partial_peer_commit_resumes_with_original_age_and_complete_heads()
        source = captured[-1]
        identity = evidence._canonical_plain(source.content)["identity"]
        observed_inputs = []
        for context in source.contexts:
            with evidence._context_database(context, write=True) as db:
                baseline = evidence._canonical_plain(state._source_baseline(None, db, context=context))
                head = next(edge["reference"]["artifact"] for edge in baseline["dependencies"] if edge["reference"]["identity"] == identity)
                with patch.object(evidence, "_context_database", side_effect=AssertionError("second connection")), \
                        patch.object(case.fixture.changes, "_check_stopped_certificate", side_effect=AssertionError("whole stop validator")):
                    inputs = evidence._recovery_use_inputs(context, db, head, identity)
                observed_inputs.append(inputs)
                self.assertEqual(inputs["baseline"], baseline)
                self.assertEqual(inputs["history"][0]["reference"], head)
                comparison = evidence._recovery_admission_projection(inputs)
                self.assertTrue(comparison["legacy_routes"])
                self.assertNotIn("admitted", comparison)
                altered = deepcopy(inputs)
                altered["reference"] = baseline["reference"]
                with self.assertRaises(state.StateError):
                    evidence._recovery_registration_projection(evidence._canonical_plain(source.content), source.created_at, altered)

        self.assertNotEqual(observed_inputs[0]["reference"], observed_inputs[1]["reference"])
        swapped = deepcopy(observed_inputs[0])
        swapped["reference"] = observed_inputs[1]["reference"]
        swapped["history"] = deepcopy(observed_inputs[1]["history"])
        with self.assertRaisesRegex(state.StateError, "original head changed"):
            evidence._recovery_registration_projection(evidence._canonical_plain(source.content), source.created_at, swapped)

    def test_approved_projection_tampering_fails_before_registration(self):
        for field in ("previous", "source", "created_at", "content", "baseline"):
            with self.subTest(field=field):
                case = self.fixture()
                request, contexts = case.d4_bookkeeping_request()
                changes = case.changes
                called = []; grants = []
                before_effects = {(action['owner']['root'], effect['path']):changes._fingerprint(Path(action['owner']['root']), effect['path'])
                    for action in request['manifest']['actions'] for effect in action['effects']}
                before_baselines = []
                for context in contexts:
                    with evidence._context_database(context) as db:
                        before_baselines.append(evidence._canonical_plain(state._source_baseline(None, db, context=context)))
                register = evidence._register_recovery_source
                def corrupt(*args, **kwargs):
                    lifetime = changes._authority_context.publication
                    table = lifetime["registration_projections"]
                    entry = table[str(kwargs["context"].database)]
                    if field == "created_at":entry[field] += 1
                    elif field == "previous":entry[field] = entry["inputs"]["baseline"]["reference"]
                    elif field == "baseline":entry["inputs"]["baseline"]["dependencies"] = [] if entry["inputs"]["baseline"]["dependencies"] else [dict(kind="task")]
                    else:entry[field]["journal"]["observed_at"] += 1
                    called.append(True)
                    return register(*args, **kwargs)
                class Host:
                    def acquire_d4_bookkeeping(self, acquired, issue):
                        grant = issue(acquired); grants.append(grant); return grant
                with changes._bootstrap_d4_host(Host(), issuer=changes._D4_HOST_BOOTSTRAP_ISSUER) as host:
                    with patch.object(evidence, "_register_recovery_source", side_effect=corrupt):
                        result = changes._run_scoped(case.directory, request, "apply", host=host)
                self.assertTrue(called, result)
                self.assertNotEqual(result["exit_code"], 0, result)
                self.assertEqual(result['state'], 'blocked')
                self.assertEqual(result['blocked'], [dict(id='transaction', reason='Recovery registration inputs differ from actual approved acquisition')])
                journal = changes._load_journal(case.directory)
                self.assertEqual(journal['plan']['revision'], request['manifest']['plan']['revision'])
                self.assertEqual(journal['manifest_digest'], request['approval']['manifest_digest'])
                self.assertEqual(journal['receipts'], {})
                self.assertIsNone(journal['enrollment'])
                self.assertEqual(len(grants), 1)
                with self.assertRaises(changes.StartupError): changes._check_d4_grant(grants[0])
                for context, baseline in zip(contexts, before_baselines):
                    with evidence._context_database(context) as db:
                        self.assertEqual(evidence._canonical_plain(state._source_baseline(None, db, context=context)), baseline)
                for (root, path), fingerprint in before_effects.items():
                    self.assertEqual(changes._fingerprint(Path(root), path), fingerprint)

    def test_shape_acceptance_does_not_authorize_recovery_storage(self):
        case = self.fixture()
        request, contexts = case.d4_bookkeeping_request()
        captured = []
        observe = case.changes._observe_recovery_source
        def actual(*args, **kwargs):
            source = observe(*args, **kwargs);captured.append(source);return source
        with patch.object(case.changes, "_observe_recovery_source", side_effect=actual):
            result = case.run_with_d4_host(request, "apply")
        self.assertEqual(result["exit_code"], 0, result)
        body = evidence._canonical_plain(captured[0].content)
        body["use_contract"] = dict(version=1, roots=[], edges=[], legacy_routes=[])
        self.assertEqual(evidence._recovery_source_shape(body,body['identity']),body)
        malformed=deepcopy(body);malformed['use_contract']['version']=2
        with self.assertRaises(state.StateError):evidence._recovery_source_shape(malformed,body['identity'])
        with evidence._context_database(contexts[0]) as db:
            with self.assertRaises(state.StateError):evidence._artifact(None,body,context=contexts[0],db=db)

    def test_real_cut_returns_pending_certificates_without_peer_validation(self):
        case = self.fixture()
        _, context, _, identity, _ = case.recovery_release_fixture()
        observation = case.changes._observe_recovery_release(context.authority_set, identity)
        self.assertTrue(case.changes._register_recovery_release(observation)["complete"])
        with evidence._context_database(context) as db:
            baseline = state._source_baseline(None, db, context=context)
            head = evidence._canonical_plain(baseline["dependencies"][0]["reference"]["artifact"])
            with patch.object(evidence, "_context_database", side_effect=AssertionError("second connection")), \
                    patch.object(case.changes, "_check_stopped_certificate", side_effect=AssertionError("whole stop validator")):
                inputs = evidence._recovery_use_inputs(context, db, head, identity)
            self.assertEqual(inputs["history"][0]["content"]["version"], 2)
            self.assertTrue(inputs["jobs"])
            self.assertTrue(all(job["kind"] == "stopped-certificate" for job in inputs["jobs"]))

    def test_genuine_observation_comparisons_keep_restrictions_without_accepting_storage(self):
        case = test_d4_historical_witness.HistoricalWitnessTests(methodName="runTest")
        case.setUp()
        self.addCleanup(case.doCleanups)
        _,_,_,_,_,_,captured=case.observe_before_storage()
        source = captured[-1]
        content = evidence._canonical_plain(source.content)
        proof_authority = next(root["proof"]["authority"] for root in content["use_contract"]["roots"] if root["purpose"] == "historical-stop")
        context = next(context for context in source.contexts if evidence._canonical_plain(context.authority_set[0]) == proof_authority)
        other = next(context for context in source.contexts if evidence._canonical_plain(context.authority_set[0]) != proof_authority)
        with evidence._context_database(other) as db:
            baseline=state._source_baseline(None,db,context=other)
            heads=[edge['reference']['artifact'] for edge in evidence._canonical_plain(baseline)['dependencies'] if edge['reference']['identity']==content['identity']]
            pending = evidence._recovery_use_inputs(other, db, heads[0] if heads else None, content["identity"], content=content)
            self.assertTrue(any(job["kind"] == "managed-source" for job in pending["jobs"]))
            with self.assertRaisesRegex(state.StateError, "external managed inputs"):
                evidence._recovery_registration_projection(content, source.created_at, pending)
        with evidence._context_database(context) as db:
            baseline=state._source_baseline(None,db,context=context)
            heads=[edge['reference']['artifact'] for edge in evidence._canonical_plain(baseline)['dependencies'] if edge['reference']['identity']==content['identity']]
            inputs = evidence._recovery_use_inputs(context, db, heads[0] if heads else None, content["identity"], content=content)
            projected = evidence._recovery_registration_projection(content, source.created_at, inputs)
            self.assertEqual(projected["content"]["use_contract"], content["use_contract"])
            missing = deepcopy(content)
            missing["use_contract"]["edges"] = []
            with self.assertRaisesRegex(state.StateError, "coverage"):
                evidence._recovery_registration_projection(missing, source.created_at, inputs)
            self.assertEqual(evidence._recovery_source_shape(projected['content'],content['identity']),projected['content'])
            with self.assertRaises(state.StateError):
                evidence._artifact(None,projected['content'],context=context,db=db)

    def test_actual_owned_overlay_corruption_blocks_commit_and_effects(self):
        case = self.fixture()
        request, contexts = case.d4_bookkeeping_request()
        changes = case.changes
        effects = {action["id"]:changes._fingerprint(Path(action["owner"]["root"]), action["effects"][0]["path"])
                   for action in request["manifest"]["actions"]}
        register = evidence._register_recovery_source
        def corrupt(*args, **kwargs):
            reference = register(*args, **kwargs)
            db, context = args[1], kwargs["context"]
            baseline = state._source_baseline(None, db, context=context)
            metadata = state._metadata(db, baseline["reference"]["name"])
            metadata["dependencies"] = []
            import json
            db.execute("update evidence_metadata set data=? where name=?", (json.dumps(metadata), baseline["reference"]["name"]))
            return reference
        class Host:
            def acquire_d4_bookkeeping(self, acquired, issue):return issue(acquired)
        with changes._bootstrap_d4_host(Host(), issuer=changes._D4_HOST_BOOTSTRAP_ISSUER) as host:
            with patch.object(evidence, "_register_recovery_source", side_effect=corrupt):
                result = changes._run_scoped(case.directory, request, "apply", host=host)
        self.assertNotEqual(result["exit_code"], 0, result)
        self.assertIn("baseline", str(result).lower())
        for action in request["manifest"]["actions"]:
            self.assertEqual(changes._fingerprint(Path(action["owner"]["root"]), action["effects"][0]["path"]), effects[action["id"]])

    def test_restricted_comparison_preserves_exact_independent_legacy_origins(self):
        authority = self.comparison_authority()
        destination = self.comparison_authority(1)
        old = self.comparison_source(1, [authority, destination])
        origin = dict(authority=authority, artifact=old['reference'], identity=old['content']['identity'],
            journal_sha256=old['content']['journal']['sha256'])
        legacy = recovery_uses.legacy_projection(origin, old['content'])
        restricted = self.comparison_source(2, [authority, destination, self.comparison_authority(2)])
        restricted['content']['use_contract'] = recovery_uses.build([], [], [legacy])
        for history in ([old, restricted], [restricted, old], [restricted]):
            result = evidence._recovery_admission_projection(dict(authority=authority, history=history, jobs=[]))
            self.assertEqual(result['legacy_routes'], [legacy])
            self.assertEqual(len(result['restricted_routes']), 1)
            self.assertNotIn(self.comparison_authority(2), result['legacy_routes'][0]['destinations'])
        changed = deepcopy(restricted)
        changed['content']['use_contract']['legacy_routes'][0]['destinations'] = [authority]
        with self.assertRaisesRegex(recovery_uses.UseContractError, 'Conflicting legacy'):
            evidence._recovery_admission_projection(dict(authority=authority, history=[old, changed], jobs=[]))

    def test_comparison_rejects_one_origin_as_both_legacy_and_restricted(self):
        authority = self.comparison_authority()
        old = self.comparison_source(1, [authority])
        restricted = deepcopy(old)
        restricted['content']['use_contract'] = recovery_uses.build([], [])
        for history in ([old, restricted], [restricted, old]):
            with self.assertRaisesRegex(recovery_uses.UseContractError, 'origin.*legacy.*restricted'):
                evidence._recovery_admission_projection(dict(authority=authority, history=history, jobs=[]))
