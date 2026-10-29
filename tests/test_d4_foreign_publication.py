"""Unresolved cross-authority check ownership conservatively blocks D4 mutation."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from runtime import delegation, evidence, state
from runtime.startup import RuntimeSettings, _canonical_freeze, canonical_scope_projection, decode_project_record
from tests import test_changes, test_evidence, test_startup
from tests.test_state import canonical_scope


class D4ForeignPublicationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_changes.ScopedChangesTests(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_unresolved_foreign_check_blocks_writes_before_host_or_publication(self):
        fixture = self.fixture
        changes = fixture.changes
        request, contexts = fixture.d4_bookkeeping_request(umbrella=True)
        destination, origin = contexts
        self.assertNotEqual(destination.database, origin.database)
        self.assertNotEqual(destination.database_binding, origin.database_binding)

        source = test_evidence.EvidenceTests(methodName='runTest')
        source.setUp()
        self.addCleanup(source.doCleanups)
        source.scope = canonical_scope(replace(source.scope, project_id='foreign-body-project',
            runtime=RuntimeSettings(2, fixture.base / 'd4-bookkeeping-1')),
            repository_id='foreign-body-repository', checkout_id='foreign-body-checkout')
        self.assertEqual(source.scope.runtime.state_dir, origin.directory)
        self.assertFalse(source.repo.is_relative_to(Path(request['manifest']['enrollment']['record']['project_root'])))
        current, authority_path = test_startup.CanonicalAcquisitionTests.record(SimpleNamespace(
            repo=source.repo, base=source.root, assertIsNone=self.assertIsNone))
        identity = evidence._canonical_plain(source.scope.accepted_identity)
        current['project_id'] = identity['project_id']
        repository = current['repositories'][0]
        repository['repository_id'] = identity['repository_id']
        checkout = repository['checkouts'][0]
        checkout['checkout_id'] = identity['checkout_id']
        checkout['clients'][0]['configuration'].update(identity['configuration'])
        authority_path.write_text(json.dumps(current))
        authority_bytes = authority_path.read_bytes()
        self.assertEqual(evidence._canonical_plain(canonical_scope_projection(decode_project_record(current),
            repository_id=identity['repository_id'], checkout_id=identity['checkout_id'], client='codex')), identity)
        state.start_task(source.scope, source.identity | dict(mode='read-only', decision_ref='fixture:accepted-source'))
        source.plan(decision_ref='fixture:accepted-source')
        reserved = evidence._reserve_check(source.scope, evidence._check_request(source.request(check_id='unit')))
        self.assertEqual(reserved['attempt']['status'], 'reserved')
        with evidence._context_database(origin) as db:
            record = next(row for row in delegation._ledger(None, db, context=origin)
                if row['id'] == reserved['attempt_id'])
            self.assertEqual(record['data']['status'], 'prepared')
            self.assertEqual(record['data']['role'], 'check')
            self.assertTrue(all(Path(claim['path']).is_relative_to(source.repo) for claim in record['data']['claims']))
            body_ref = record['data']['assignment']
            original, raw = evidence._managed_artifact(None, body_ref, context=origin, db=db)
            original_body = json.loads(raw)
            source_authority = evidence._canonical_plain(origin.authority_set[0])
            destination_authority = evidence._canonical_plain(destination.authority_set[0])
            self.assertEqual(original['owner']['project_id'], source.scope.project_id)
            self.assertIsNotNone(original['owner']['task'])
            self.assertEqual(original['owner']['task']['authority'], source_authority)
            self.assertEqual(evidence._reverse_source_authorities(origin, db, original), [source_authority])
            self.assertEqual(evidence._source_intents(origin, body_ref, db=db), [])
        baselines = {}
        for context in contexts:
            with evidence._context_database(context) as db:
                baseline = state._source_baseline(None, db, context=context)
                self.assertEqual(baseline['content']['source_contract'], 2)
                self.assertEqual(baseline['dependencies'], ())
                baselines[str(context.database)] = evidence._canonical_plain(baseline)

        before_effects = {action['id']: changes._fingerprint(Path(action['owner']['root']), action['effects'][0]['path'])
            for action in request['manifest']['actions']}
        registrations = []
        acquired = []
        real_register = evidence._register_recovery_source

        def observe_registration(scope, db, observation, *, context=None):
            registrations.append(context.database)
            return real_register(scope, db, observation, context=context)

        class Host:
            def acquire_d4_bookkeeping(self, facts, issue):
                acquired.append(evidence._canonical_plain(facts))
                return issue(facts)

        with changes._bootstrap_d4_host(Host(), issuer=changes._D4_HOST_BOOTSTRAP_ISSUER) as host:
            with patch.object(evidence, '_register_recovery_source', side_effect=observe_registration):
                result = changes._run_scoped(fixture.directory, request, 'apply', host=host)
        self.assertEqual(result['exit_code'], 2, result)
        self.assertTrue(any(item['reason'] == 'Affected foreign or uncertain assignment remains unreconciled'
            for item in result['blocked']), result)
        self.assertEqual(acquired, [])
        self.assertEqual(registrations, [])
        for action in request['manifest']['actions']:
            self.assertEqual(changes._fingerprint(Path(action['owner']['root']), action['effects'][0]['path']), before_effects[action['id']])
        for context in contexts:
            with evidence._context_database(context) as db:
                self.assertEqual(evidence._canonical_plain(state._source_baseline(None, db, context=context)), baselines[str(context.database)])
        with evidence._context_database(origin) as db:
            retained, raw = evidence._managed_artifact(None, body_ref, context=origin, db=db)
            self.assertEqual(retained, original)
            self.assertEqual(json.loads(raw), original_body)
            self.assertNotIn(destination_authority, evidence._reverse_source_authorities(origin, db, retained))
            record = next(row for row in delegation._ledger(None, db, context=origin) if row['id'] == reserved['attempt_id'])
            self.assertEqual(record['data']['status'], 'prepared')
        self.assertEqual(authority_path.read_bytes(), authority_bytes)
        markers = changes._authority_locations([context.directory for context in contexts])
        root = Path(request['manifest']['enrollment']['record']['project_root'])
        markers.append(Path(changes.LOCK_ROOT) / ('canonical-' + hashlib.sha256(
            ('destination:' + str(root / changes.PROJECT_FILE)).encode()).hexdigest() + '.lock'))
        self.assertTrue(markers)
        for marker in markers:
            self.assertIsNone(changes._authority_owner(marker), str(marker))

    def test_stopped_umbrella_member_first_publishes_body_before_peer_reverse_edge(self):
        fixture = self.fixture
        changes = fixture.changes
        request, contexts = fixture.d4_bookkeeping_request(umbrella=True)
        destination, origin = contexts
        proposal = request['manifest']['enrollment']['record']
        repository = proposal['repositories'][1]
        checkout = repository['checkouts'][0]
        projection = evidence._canonical_plain(canonical_scope_projection(decode_project_record(proposal),
            repository_id=repository['repository_id'], checkout_id=checkout['checkout_id'], client='codex'))
        self.assertTrue(projection['membership']['included'])
        self.assertNotEqual(destination.database_binding, origin.database_binding)
        baselines = {}
        for context in contexts:
            with evidence._context_database(context) as db:
                self.assertEqual(db.execute('select count(*) from checkouts').fetchone()[0], 0)
                baselines[str(context.database)] = evidence._canonical_plain(state._source_baseline(None, db, context=context))
                self.assertEqual(baselines[str(context.database)]['dependencies'], [])
        # Internal synthetic accepted-scope fixture; the proposal grants no public/native activation.
        scope = replace(fixture.d4_bookkeeping_scopes[1], project_root=Path(projection['project_root']),
            authority_path=Path(projection['project_root']) / changes.PROJECT_FILE,
            authority_target=_canonical_freeze(request['manifest']['enrollment']['before']['target']),
            authority_revision=proposal['revision'], accepted_identity=_canonical_freeze(projection),
            accepted_scope_digest=state._digest(projection))
        self.assertEqual(scope.runtime.state_dir, origin.directory)
        self.assertEqual(scope.project_root, fixture.base)
        self.assertEqual(evidence._canonical_plain(scope.bindings), projection['bindings'])
        self.assertEqual(scope.qualification_provenance['reference'], 'fixture:synthetic')
        owner = dict(client='codex', session_id='stopped-b', task_id='stopped-b', scope_ref='fixture:stopped-member-b')
        state.start_task(scope, owner | dict(mode='editable', decision_ref='fixture:member-b-decision'))
        with state._database(scope) as db:
            stored = state.json_object(db.execute('select physical_identity from checkouts where scope_id=?',
                (state._scope_id(scope),)).fetchone()[0])
            self.assertEqual(stored, state._physical_identity(projection))
        prepared = delegation.reserve_coordinator(scope, owner | dict(expected_revision=1, dispatch_id='member-b-operation',
            claims=[dict(kind='path', key=str(scope.repository_root / 'AGENTS.md'), mode='write')],
            operation=dict(id='member-b-operation', kind='coordinator-work'), reason='Local member B observation',
            ownership_ref='fixture:member-b-owner', stop_conditions=['Stop after local observation']))
        with state._database(scope) as db:
            task = state._task(db, state._scope_id(scope), owner['client'], owner['session_id'], owner['task_id'])
            record = next(row for row in delegation._ledger(scope, db) if row['id'] == prepared['attempt_id'])
        facts = dict(operation_id='member-b-operation', operation_digest=record['body']['operation']['digest'],
            claims_digest=evidence._digest(record['data']['claims']))
        body_ref = evidence._artifact(scope, dict(facts, observation='Genuine local member B evidence'),
            owner=evidence._artifact_owner(scope, task))
        proof = dict(version=2, kind='coordinator-operation-reconciliation', identity=owner, expected_pins=task['pins'],
            expected_revision=task['revision'], scope_id=record['owner']['scope_id'], attempt_id=record['id'],
            dispatch_id=record['owner']['dispatch_id'], assignment_digest=record['data']['assignment']['digest'],
            decision_ref=task['decision_ref'], operation_evidence=body_ref, resource_observations=body_ref,
            operation_stopped=True, operation_descendants_stopped=True, observation_ref='fixture:member-b-observation',
            coordinator_ref='fixture:independent-member-b-owner', **facts)
        proof_path = fixture.directory / 'member-b-operation-proof.json'
        raw = json.dumps(proof).encode(); proof_path.write_bytes(raw); proof_path.chmod(0o600)
        delegation.reconcile_assignment(scope, owner | dict(expected_revision=task['revision'], attempt_id=record['id'],
            host_proof=dict(path=str(proof_path), sha256=hashlib.sha256(raw).hexdigest()), assessment=dict(outcome='cancelled',
                changed_paths=[], result_assessment='Actual reserved operation stopped before effects',
                partial_change_assessment='No remaining effects', evidence=['fixture:member-b-inspection'], coordinator_ref='fixture:owner')))
        task = state.task_status(scope, owner['client'], owner['session_id'])['task']
        stop = dict(version=1, kind='stopped-writer-reconciliation', identity=owner, expected_revision=task['revision'],
            expected_pins=task['pins'], observed_turn_id=task['turn_id'], stopped=True, descendants_stopped=True,
            attempt_ids=[], observation_ref='fixture:member-b-task-stopped', coordinator_ref='fixture:independent-owner')
        stop_path = fixture.directory / 'member-b-task-stop.json'
        raw = json.dumps(stop).encode(); stop_path.write_bytes(raw); stop_path.chmod(0o600)
        stopped = state.retire_task(scope, owner | dict(expected_revision=task['revision'], expected_pins=task['pins'],
            reason='Stopped member B', reference='fixture:member-b-retired',
            stop_proof=dict(path=str(stop_path), sha256=hashlib.sha256(raw).hexdigest())))['task']
        self.assertEqual(stopped['state'], 'cancelled')
        source_authority = evidence._canonical_plain(origin.authority_set[0])
        destination_authority = evidence._canonical_plain(destination.authority_set[0])
        qualified = dict(authority=source_authority, artifact=body_ref)
        with evidence._context_database(origin) as db:
            self.assertTrue(all(row['data']['status'] == 'settled' for row in delegation._ledger(None, db, context=origin)))
            original, raw = evidence._managed_artifact(None, body_ref, context=origin, db=db)
            original_body = json.loads(raw)
            self.assertEqual(original['owner']['task']['authority'], source_authority)
            self.assertEqual(original['owner']['project_id'], projection['project_id'])
            self.assertEqual(evidence._reverse_source_authorities(origin, db, original), [source_authority])
            self.assertEqual(evidence._source_intents(origin, body_ref, db=db), [])
        acquired = []; first = []; real_register = evidence._register_recovery_source

        def observe_first(actual_scope, db, observation, *, context=None):
            if context.database == destination.database and observation.content['journal']['state'] == 'prepared':
                self.assertTrue(changes._held_authority_guards(c.directory for c in contexts))
                self.assertIn(qualified, evidence._canonical_plain(observation.content)['artifacts'])
                self.assertTrue(any(row['id'] == prepared['attempt_id'] for row in observation.content['assignments']))
                with evidence._context_database(origin) as reader:
                    baseline = state._source_baseline(None, reader, context=origin)
                    self.assertEqual(evidence._canonical_plain(baseline), baselines[str(origin.database)])
                    self.assertNotIn(destination_authority, evidence._reverse_source_authorities(origin, reader, original))
                first.append(observation.created_at)
            return real_register(actual_scope, db, observation, context=context)

        class Host:
            def acquire_d4_bookkeeping(self, granted, issue):
                acquired.append(evidence._canonical_plain(granted))
                return issue(granted)

        with changes._bootstrap_d4_host(Host(), issuer=changes._D4_HOST_BOOTSTRAP_ISSUER) as host:
            with patch.object(evidence, '_register_recovery_source', side_effect=observe_first):
                result = changes._run_scoped(fixture.directory, request, 'apply', host=host)
        self.assertEqual(result['exit_code'], 0, result)
        self.assertEqual(len(first), 1)
        self.assertEqual([row['journal']['state'] for row in acquired], ['prepared', 'applied'])
        for row in acquired:
            self.assertTrue(any(item['reference'] == qualified and item['metadata'] == original for item in row['permissions']['sources']))
            self.assertIn({key: projection[key] for key in ('project_id', 'repository_id', 'checkout_id', 'client')}, row['permissions']['subjects'])
        for context in contexts:
            with evidence._context_database(context) as db:
                baseline = evidence._canonical_plain(state._source_baseline(None, db, context=context))
                self.assertEqual(len(baseline['dependencies']), 1)
                head = baseline['dependencies'][0]['reference']['artifact']
                body = evidence._read(None, head, context=context, db=db); metadata = state._metadata(db, head['name'])
                self.assertEqual(body['journal']['state'], 'applied'); self.assertIn(qualified, body['artifacts'])
                self.assertIn(dict(kind='artifact', reference=qualified), metadata['dependencies'])
                self.assertEqual(metadata['created_at'], first[0])
                self.assertTrue(any(item['id'] == prepared['attempt_id'] and item['authority'] == source_authority for item in body['assignments']))
        with evidence._context_database(origin) as db:
            retained, raw = evidence._managed_artifact(None, body_ref, context=origin, db=db)
            self.assertEqual(retained, original); self.assertEqual(json.loads(raw), original_body)
            self.assertEqual(state._task(db, state._scope_id(scope), owner['client'], owner['session_id'])['pins'], stopped['pins'])
            self.assertIn(destination_authority, evidence._reverse_source_authorities(origin, db, retained))
        markers = changes._authority_locations([c.directory for c in contexts])
        root = Path(proposal['project_root'])
        markers.append(Path(changes.LOCK_ROOT) / ('canonical-' + hashlib.sha256(
            ('destination:' + str(root / changes.PROJECT_FILE)).encode()).hexdigest() + '.lock'))
        for marker in markers:self.assertIsNone(changes._authority_owner(marker), str(marker))
