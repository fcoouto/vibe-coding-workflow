"""D5 proofs use disposable Git repositories and explicit mocked native observations."""
from dataclasses import replace
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from runtime import state
from runtime.startup import ProjectScope, RuntimeSettings, policy_digest


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='vibe-evidence-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Fixture')
        (self.repo / 'app.py').write_text('value = 1\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')
        self.scope = ProjectScope('fixture', self.repo, self.repo / '.git', policy_digest(state.PACKAGE), RuntimeSettings(2, self.root / 'state'))
        self.identity = dict(client='codex', session_id='parent', task_id='task', scope_ref='user:task')
        state.start_task(self.scope, self.identity | dict(mode='editable', decision_ref='user:accepted'))
        self.api = importlib.import_module('runtime.evidence')
        from runtime import changes
        guard_patch = patch.object(changes, 'LOCK_ROOT', self.root / 'authority-guards')
        guard_patch.start()
        self.addCleanup(guard_patch.stop)

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], stderr=subprocess.DEVNULL).decode().strip()

    def request(self, **fields):
        return self.identity | dict(expected_revision=state.task_status(self.scope, 'codex', 'parent')['task']['revision']) | fields

    def plan(self, **updates):
        review = dict(applicability='required', reason='Actual change', independent=True)
        plan = dict(version=1, decision_ref='user:accepted', criteria=[dict(id='works', checks=['unit'], behavior=False)],
            checks=[dict(id='unit', argv=[sys.executable, '-c', 'pass'], cwd='.', timeout=3,
                env={'PATH': os.defpath}, effects=dict(kind='read-only', inspection_ref='code:inspected', network=False,
                    production=False, publish=False, migrations=False), baseline=dict(status='passed', reference='baseline:1'),
                dependencies=['app.py'])], reviews={'general': review, 'security': review},
            security_impact=dict(status='assessed', reason='Local runtime boundary', reference='code:impact'),
            base='HEAD', comparison='endpoint', nontrivial=True, instructions=[], exclusions=[], review_limit=3)
        return self.api.plan_evidence(self.scope, self.request(plan=plan | updates))

    def reconcile(self, result, **proof_updates):
        # Synthetic fixture host observations are explicit; they do not qualify real native execution.
        attempt = result['attempt']
        request = self.request(attempt_id=attempt['id'])
        task = state.task_status(self.scope, 'codex', 'parent')['task']
        plan = self.api._load_plan(self.scope, self.identity)
        proof = dict(version=1, kind='check-writer-reconciliation', identity=self.identity.copy(), expected_pins=task['pins'],
            expected_revision=task['revision'], scope_id=state._scope_id(self.scope), attempt_id=attempt['id'],
            candidate_digest=attempt['candidate_digest'], current_candidate_digest=self.api._digest(self.api.capture_candidate(self.scope, plan)),
            plan_digest=attempt['plan_digest'], execution_digest=attempt.get('execution', {}).get('digest'),
            stopped=True, descendants_stopped=True, observation_ref='fixture:explicit-host-lifecycle-observation',
            coordinator_ref='fixture:independently-checked') | proof_updates
        if 'ledger_assignment_digest' in attempt:
            from runtime import delegation
            with state._database(self.scope) as db:
                row = next(r for r in delegation._ledger(self.scope, db) if r['id'] == attempt['id'])
            proof = proof | dict(version=2, dispatch_id=row['owner']['dispatch_id'],
                assignment_digest=attempt['ledger_assignment_digest'], claims_digest=attempt['ledger_claims_digest']) | proof_updates
        raw = json.dumps(proof).encode()
        path = self.root / (attempt['id'] + '-host-' + str(time.time_ns()) + '.json')
        path.write_bytes(raw)
        path.chmod(0o400)
        return self.api.reconcile_check(self.scope, request | dict(host_proof=dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest())))

    def check(self):
        return self.api.run_check(self.scope, self.request(check_id='unit'))

    def checked(self):
        result = self.check()
        if result['attempt'].get('process_started') and result['attempt'].get('observed_status') != 'uncertain':
            result = self.reconcile(result)
        return result

    def native_review_request(self, *, coverage, criteria, assignment):
        from runtime import delegation
        if not hasattr(self, 'native_review_catalog'):
            self.native_review_catalog = dict(version=1, client_surface='codex-cli', native_version='0.163.0',
                parent_session_id='parent', originator='fixture-cli', parent_model_provider='native-provider',
                catalog=[dict(model='fixture-review-model', supported_efforts=['high'], default_effort='high')],
                dispatch_controls=dict(spawn=True, explicit_model=True, explicit_effort=True, fork_turns_none=True),
                capability_digest='a' * 64, limitations=['Synthetic native fixture; no actual native call'])
            self.native_review_cache = dict(client_surface='codex-cli', applicability=dict(client_version='0.163.0', capability_fingerprint='a' * 64))
            claim = delegation.claim_guidance(self.scope, self.native_review_cache | dict(trigger=dict(kind='routine', id='fixture-review')))
            if claim.get('token'):
                guidance = dict(schema_version=1, client_surface='codex-cli', checked_at='2026-01-01T00:00:00Z',
                    applicability=self.native_review_cache['applicability'], sources=[dict(id='official',
                        url='https://example.org/official', sha256='b' * 64)], recommendations=[dict(id='review-fixture',
                        work='Fixture native review', risk='Read-only fixture', models=[], conditions=['Independent review'],
                        limitations=['Synthetic catalog'], source_ids=['official'])])
                delegation.record_guidance(self.scope, self.native_review_cache | dict(token=claim['token'],
                    generation=claim['generation'], coordinator_ref='fixture:verified', guidance=guidance))
            discover = patch('runtime.adapters.codex.discover_native_workers', return_value=self.native_review_catalog)
            discover.start(); self.addCleanup(discover.stop)
        with state._database(self.scope) as db:
            task = state._task(db, state._scope_id(self.scope), 'codex', 'parent')
        if 'delegation' not in task:
            plan = self.coordinator_resource_plan([dict(id='review', role='review', claims=[dict(kind='path',
                key=str(self.repo), mode='read')], dependencies=[], max_attempts=3)])
            plan['limits'].update(max_attempts=3, max_resource_units=3, max_parallel_workers=3, host_capacity=3)
            delegation.plan_delegation(self.scope, self.request(plan=plan))
        with state._database(self.scope) as db:
            records = [r for r in delegation._ledger(self.scope, db) if r['owner']['session_id'] == 'parent' and
                r['owner']['task_id'] == self.identity['task_id'] and r['data']['role'] == 'review']
        guide = delegation.guidance_status(self.scope, self.native_review_cache)
        request = self.request(coverage=coverage, criteria=criteria, assignment=assignment, job_id='review',
            dispatch_id='review-' + str(len(records)), resource_units=1,
            selection=dict(model='fixture-review-model', effort='high', rationale='Explicit qualified fixture model',
                profile_ids=['review-fixture'], mode='explicit'),
            control_observation={key:self.native_review_catalog[key] for key in ('version', 'client_surface',
                'native_version', 'parent_session_id', 'dispatch_controls')},
            discovery_expectation={key:self.native_review_catalog[key] for key in ('client_surface', 'native_version',
                'parent_session_id', 'parent_model_provider', 'capability_digest')},
            guidance={key:guide[key] for key in ('snapshot_ref', 'snapshot_digest', 'checked_at', 'freshness')})
        if records:
            previous = max(records, key=lambda r:r['data']['revision'])
            request.update(retry_of=previous['id'], diagnostic=dict(prior_attempt_id=previous['id'],
                cause='Review after previous independently settled round', change='Fresh bounded review',
                evidence=['fixture:diagnosis-' + previous['id']]))
        return request

    def reconcile_review(self, prepared):
        from runtime import delegation
        task = state.task_status(self.scope, 'codex', 'parent')['task']
        with state._database(self.scope) as db:
            row = next(r for r in delegation._ledger(self.scope, db) if r['id'] == prepared['attempt_id'])
        data, binding = row['data'], row['data']['binding']
        receipt = self.api._read(self.scope, data['observation'])['receipt']
        native = {key:binding[key] for key in ('client_surface', 'native_version', 'parent_session_id', 'task_name')}
        native.update({key:receipt[key] for key in ('parent_turn_id', 'spawn_item_id', 'worker_id', 'worker_turn_id', 'result_item_id')})
        proof = dict(version=2, kind='assignment-writer-reconciliation', identity=self.identity.copy(), expected_pins=task['pins'],
            expected_revision=task['revision'], scope_id=state._scope_id(self.scope), attempt_id=row['id'],
            dispatch_id=row['owner']['dispatch_id'], assignment_digest=data['assignment']['digest'], claims_digest=self.api._digest(data['claims']),
            candidate_digest=data['candidate']['digest'], current_candidate_digest=self.api._digest(self.api.capture_candidate(self.scope,
                self.api._read(self.scope, row['body']['review']['d5_plan']))), d6_plan_digest=data['plan_digest'],
            observation_digest=data['observation']['digest'], result_digest=receipt['result_digest'], native_identity=native,
            launch_state='observed', stopped=True, descendants_stopped=True, observation_ref='fixture:host-lifecycle-checked',
            coordinator_ref='fixture:independent-host-inspection')
        raw=json.dumps(proof).encode(); path=self.root/('review-proof-'+row['id']+'.json');path.write_bytes(raw);path.chmod(0o400)
        return delegation.reconcile_assignment(self.scope, self.request(attempt_id=row['id'], host_proof=dict(path=str(path),
            sha256=hashlib.sha256(raw).hexdigest()), assessment=dict(outcome='completed', changed_paths=[],
            result_assessment='Fixture report independently checked', partial_change_assessment='No candidate/shared-resource effects',
            evidence=['fixture:effect-inspection'], coordinator_ref='fixture:independent-assessment')))

    def review(self, findings=None, coverage=None):
        from runtime import delegation
        coverage = coverage or ['general', 'security']
        request = self.native_review_request(coverage=coverage, criteria=['works'],
            assignment='Review read-only; inspect app.py and callers. Return the bound report.')
        prepared = self.api.prepare_review(self.scope, request)
        attempt = prepared['attempt_id']
        binding = delegation.prepared_native_review_assignment(self.scope, attempt)
        # Native receipts do not echo the internal historical runtime locator metadata.
        binding = {key:value for key,value in binding.items() if key not in {'pins','accepted_identity','scope_id'}}
        report = dict(version=1, attempt_id=attempt, assignment_digest=prepared['assignment_digest'],
            candidate_digest=prepared['candidate_digest'], coverage=coverage, findings=findings or [], limitations=[])
        raw = json.dumps(report)
        actual = dict(version=2, mechanism='codex-native-agent-path', **binding, agent_path='/root/'+binding['task_name'],
            originator='codex_exec', parent_model_provider=None, worker_model_provider=None, parent_turn_id='turn', spawn_item_id='spawn',
            worker_id='reviewer', worker_turn_id='child-turn', result_item_id='final', turn_status='completed', checkout=str(self.repo),
            configured_model='fixture-review-model', configured_effort='high', spawn_observed_model='fixture-review-model',
            spawn_observed_effort='high', execution_model=None, execution_effort=None, descendants_stopped=False,
            prompt_delivery='unverified', result_digest=hashlib.sha256(raw.encode()).hexdigest())
        with patch('runtime.adapters.codex.observe_native_review_assignment', return_value=dict(receipt=actual,result=raw)):
            delegation.observe_assignment(self.scope, self.request(attempt_id=attempt,parent_turn_id='turn',spawn_item_id='spawn'))
        receipt = dict(version=1, mechanism='codex-native-agent-path', native_version='0.163.0', parent_session_id='parent',
            parent_turn_id='turn', spawn_item_id='spawn', reviewer_id='reviewer', review_turn_id='child-turn',
            report_item_id='final', assignment_digest=prepared['assignment_digest'], candidate_digest=prepared['candidate_digest'],
            report_digest=actual['result_digest'], requested_model='fixture-review-model', requested_effort='high',
            task_name=binding['task_name'],agent_path=actual['agent_path'])
        with patch('runtime.adapters.codex.collect_native_review', return_value={'receipt': receipt, 'report': report}, create=True):
            self.api.collect_review(self.scope, self.request(attempt_id=attempt, parent_turn_id='turn', spawn_item_id='spawn'))
        assessed = self.api.assess_review(self.scope, self.request(attempt_id=attempt, assessment=dict(coverage=coverage,
            criteria=['works'], qualification='Qualified in runtime/security review', independence='Different observed native child',
            semantic_coverage='Inspected requirements, code and failure paths', dispositions=[], decision_refs=['user:accepted'])))
        self.reconcile_review(prepared)
        return assessed

    def verify(self, **fields):
        return self.api.verify_completion(self.scope, self.request(purpose='completion', **fields))

    def ready_proof_fixture(self):
        reviews = {name:dict(applicability='inapplicable', reason='Trivial model-free fixture', independent=False)
            for name in ('general', 'security')}
        self.plan(nontrivial=False, reviews=reviews)
        self.checked()

    def readiness_owner(self, session='other-parent', claims=None, *, scope=None, identity=None, dispatch='operation-1'):
        scope = scope or self.scope
        identity = identity or self.identity | dict(session_id=session, task_id=session + '-task')
        with state._database(scope) as db:
            task = state._task(db, state._scope_id(scope), identity['client'], identity['session_id'])
        if task is None:
            state.start_task(scope, identity | dict(mode='editable', decision_ref='user:accepted'))
            with state._database(scope) as db:
                task = state._task(db, state._scope_id(scope), identity['client'], identity['session_id'])
        return identity | dict(expected_revision=task['revision'], dispatch_id=dispatch,
            claims=claims or [dict(kind='path', key=str(self.repo / 'app.py'), mode='write')],
            operation=dict(id=dispatch, kind='coordinator-work'), reason='Explicit fixture work',
            ownership_ref='fixture:independent-owner', stop_conditions=['Stop after fixture operation'])

    def test_writer_first_prevents_verification_without_model_guidance(self):
        from runtime import delegation
        self.ready_proof_fixture()
        writer = delegation._reserve_operation(self.scope, self.readiness_owner(), role='coordinator')
        with patch.object(delegation, 'guidance_status', side_effect=AssertionError('model-free verify queried guidance')):
            result = self.verify()
        self.assertFalse(result['verified'])
        self.assertNotEqual(result['task']['state'], 'ready')
        with state._database(self.scope) as db:
            self.assertEqual(next(r for r in delegation._ledger(self.scope, db) if r['id'] == writer['attempt_id'])['data']['status'], 'prepared')
        self.assertNotIn('delegation', result['task'])

    def test_verification_barrier_prevents_writer_during_capture(self):
        from runtime import delegation
        self.ready_proof_fixture()
        writer = self.readiness_owner()
        original = self.api.capture_candidate
        attempts = []
        def capture(scope, plan):
            if not attempts:
                attempts.append(True)
                with self.assertRaises(state.StateError):
                    delegation._reserve_operation(scope, writer, role='coordinator')
            return original(scope, plan)
        with patch.object(self.api, 'capture_candidate', side_effect=capture):
            result = self.verify()
        self.assertTrue(result['verified'])
        with state._database(self.scope) as db:
            records = [r for r in delegation._ledger(self.scope, db) if r['data']['role'] == 'coordinator']
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['data']['status'], 'settled')
        operation = self.api._read(self.scope, records[0]['body']['operation'])
        self.assertEqual(operation['kind'], 'completion-verification')
        self.assertTrue(all(c['mode'] == 'read' for c in records[0]['data']['claims']))
        self.assertEqual(records[0]['data']['resource_units'], 0)
        self.assertIsNone(records[0]['data']['binding'])
        verification = self.api._read(self.scope, result['task']['evidence']['verification'])
        self.assertEqual(verification['resource_closure'], records[0]['data']['claims'])

    def test_reservation_atomically_invalidates_foreign_ready_once_and_replay_is_noop(self):
        from runtime import delegation
        self.ready_proof_fixture()
        ready = self.verify()['task']
        writer = self.readiness_owner()
        first = delegation._reserve_operation(self.scope, writer, role='coordinator')
        with state._database(self.scope) as db:
            current = state._task(db, state._scope_id(self.scope), 'codex', 'parent')
        self.assertEqual(current['state'], 'verifying')
        self.assertEqual(current['revision'], ready['revision'] + 1)
        self.assertTrue(delegation._reserve_operation(self.scope, writer, role='coordinator')['replayed'])
        failed = self.readiness_owner(session='third-parent')
        with self.assertRaises(state.StateError):
            delegation._reserve_operation(self.scope, failed, role='coordinator')
        with state._database(self.scope) as db:
            self.assertEqual(state._task(db, state._scope_id(self.scope), 'codex', 'parent'), current)
            owner = state._task(db, state._scope_id(self.scope), 'codex', 'other-parent')
        self.assertEqual(owner['revision'], first['revision'])

    def test_crashed_verifier_keeps_read_claim_and_cannot_be_bypassed_by_another_verifier(self):
        from runtime import delegation
        self.ready_proof_fixture()
        with patch.object(self.api, 'capture_candidate', side_effect=RuntimeError('fixture crash after barrier')):
            with self.assertRaises(RuntimeError):
                self.verify()
        with state._database(self.scope) as db:
            retained = [r for r in delegation._ledger(self.scope, db) if r['data']['role'] == 'coordinator']
        self.assertEqual(len(retained), 1)
        self.assertNotEqual(retained[0]['data']['status'], 'settled')
        before = retained[0]['data']
        retry = self.verify()
        self.assertFalse(retry['verified'])
        self.assertNotEqual(retry['task']['state'], 'ready')
        with state._database(self.scope) as db:
            self.assertEqual(next(r for r in delegation._ledger(self.scope, db) if r['id'] == retained[0]['id'])['data'], before)
        with self.assertRaises(state.StateError):
            delegation._reserve_operation(self.scope, self.readiness_owner(), role='coordinator')
        current = state.task_status(self.scope, 'codex', 'parent')['task']
        with self.assertRaises(state.StateError):
            state.start_task(self.scope, self.identity | dict(task_id='replacement', mode='editable', decision_ref='user:accepted',
                replaces=dict(task_id='task', expected_revision=current['revision'])))

    def test_known_failed_verification_settles_only_own_read_barrier_and_same_task_reader_blocks(self):
        from runtime import delegation
        self.plan()
        unrelated = delegation._reserve_operation(self.scope, self.readiness_owner(claims=[
            dict(kind='service', key='fixture:independent', host='local', mode='read')]), role='coordinator')
        failed = self.verify()
        self.assertFalse(failed['verified'])
        with state._database(self.scope) as db:
            records = delegation._ledger(self.scope, db)
        self.assertEqual(next(r for r in records if r['id'] == unrelated['attempt_id'])['data']['status'], 'prepared')
        verifier = next(r for r in records if r['id'] != unrelated['attempt_id'])
        self.assertEqual(verifier['data']['status'], 'settled')
        self.assertEqual(verifier['data']['result']['outcome'], 'failed')
        reader = self.readiness_owner(identity=self.identity, dispatch='same-task-reader', claims=[
            dict(kind='path', key=str(self.repo / 'app.py'), mode='read')])
        delegation._reserve_operation(self.scope, reader, role='coordinator')
        result = self.verify()
        self.assertFalse(result['verified'])
        self.assertTrue(any('ownership' in item for item in result['blockers']))
        with state._database(self.scope) as db:
            self.assertEqual(len(delegation._ledger(self.scope, db)), 3)
        self.assertNotIn('delegation', result['task'])

    def coordinator_resource_plan(self, jobs):
        return dict(version=1, route=dict(mechanism='codex-native-subagent', client_surface='codex-cli', parent_session_id='parent',
            authority_ref='fixture:accepted-route', controls_ref='fixture:known-controls'),
            authority=dict(state_dir=str(self.scope.runtime.state_dir), participants_ref='fixture:shared-owners', ownership_known=True),
            selection_constraints=dict(complexity='Fixture', risk='Bounded', rationale='Explicit fixture plan', required_controls=['spawn']),
            limits=dict(max_attempts=1, max_resource_units=1, deadline=int(time.time()) + 600, max_parallel_workers=1,
                host_capacity=1, capacity_ref='fixture:capacity'), fallback=dict(action='stop', reference='user:accepted'),
            jobs=jobs)

    def test_ready_shared_service_closure_preserves_independence_but_status_blocks_overlapping_reader(self):
        from runtime import delegation
        self.ready_proof_fixture()
        service = dict(kind='service', key='fixture:used-db', host='local', mode='write')
        plan = self.coordinator_resource_plan([dict(id='coordinator-service', role='coordinator', claims=[service], dependencies=[], max_attempts=1)])
        delegation.plan_delegation(self.scope, self.request(plan=plan))
        independent = self.readiness_owner(claims=[service | dict(key='fixture:independent-db')])
        delegation._reserve_operation(self.scope, independent, role='coordinator')
        ready = self.verify()['task']
        self.assertEqual(ready['state'], 'ready')
        verification = self.api._read(self.scope, ready['evidence']['verification'])
        self.assertIn(service | dict(mode='read'), verification['resource_closure'])
        self.assertFalse(self.api.evidence_status(self.scope, 'codex', 'parent')['evidence']['blockers'])
        reader = self.readiness_owner(session='reader', claims=[service | dict(mode='read')])
        delegation._reserve_operation(self.scope, reader, role='coordinator')
        with state._database(self.scope) as db:
            before_status = state._task(db, state._scope_id(self.scope), 'codex', 'parent')
        self.assertEqual(before_status['state'], 'ready')
        self.assertEqual(before_status['revision'], ready['revision'])
        self.api.revalidate_ready(self.scope, 'codex', 'parent')
        with state._database(self.scope) as db:
            after = state._task(db, state._scope_id(self.scope), 'codex', 'parent')
        self.assertEqual(after['state'], 'verifying')
        self.assertEqual(after['revision'], ready['revision'] + 1)

    def test_status_uses_newly_accepted_d6_resources_when_candidate_is_unchanged(self):
        from runtime import delegation
        self.ready_proof_fixture()
        ready = self.verify()['task']
        original = self.api._read(self.scope, ready['evidence']['verification'])
        dependency = dict(kind='service', key='fixture:new-dependency', host='local', mode='read')
        plan = self.coordinator_resource_plan([dict(id='new-dependency', role='coordinator', claims=[dependency],
            dependencies=[], max_attempts=1)])
        delegation.plan_delegation(self.scope, self.request(plan=plan))
        owner = delegation._reserve_operation(self.scope, self.readiness_owner(claims=[dependency]), role='coordinator')
        status = self.api.evidence_status(self.scope, 'codex', 'parent')
        self.assertEqual(status['evidence']['candidate_digest'], original['candidate_digest'])
        self.assertTrue(any(owner['attempt_id'] in blocker for blocker in status['evidence']['blockers']))
        verified = self.verify()
        self.assertFalse(verified['verified'])
        self.assertEqual(status['evidence']['blockers'], verified['blockers'])

    def test_first_delegation_plan_invalidates_ready_once_and_reuse_preserves_fresh_ready(self):
        from runtime import delegation
        self.ready_proof_fixture()
        ready = self.verify()['task']
        before = json.loads(json.dumps(ready))
        dependency = dict(kind='service', key='fixture:first-plan-dependency', host='local', mode='read')
        plan = self.coordinator_resource_plan([dict(id='dependency', role='coordinator', claims=[dependency],
            dependencies=[], max_attempts=1)])
        request = self.request(plan=plan)
        accepted = delegation.plan_delegation(self.scope, request)
        with state._database(self.scope) as db:
            current = state._task(db, state._scope_id(self.scope), 'codex', 'parent')
        self.assertEqual(current['state'], 'verifying')
        self.assertEqual(current['revision'], before['revision'] + 1)
        self.assertEqual(accepted['revision'], current['revision'])
        self.assertEqual(current['pins'], before['pins'])
        self.assertEqual(current['evidence'], before['evidence'])
        self.assertEqual(current['delegation']['attempts_consumed'], 0)
        self.assertEqual(current['delegation']['resource_units_consumed'], 0)
        with self.assertRaisesRegex(state.StateError, 'revision conflict'):
            delegation.plan_delegation(self.scope, request)
        reuse = delegation.plan_delegation(self.scope, self.request(plan=plan))
        self.assertEqual(reuse, accepted)
        altered = json.loads(json.dumps(plan))
        altered['limits']['max_attempts'] += 1
        with self.assertRaisesRegex(state.StateError, 'immutable'):
            delegation.plan_delegation(self.scope, self.request(plan=altered))
        renewed = self.verify()
        self.assertTrue(renewed['verified'])
        fresh = renewed['task']
        proof = self.api._read(self.scope, fresh['evidence']['verification'])
        self.assertIn(dependency, proof['resource_closure'])
        reuse = delegation.plan_delegation(self.scope, self.request(plan=plan))
        self.assertEqual(reuse['revision'], fresh['revision'])
        with state._database(self.scope) as db:
            unchanged = state._task(db, state._scope_id(self.scope), 'codex', 'parent')
        self.assertEqual(unchanged, fresh)
        writer = delegation.reserve_coordinator(self.scope,
            self.readiness_owner(claims=[dependency | dict(mode='write')]))
        with state._database(self.scope) as db:
            invalidated = state._task(db, state._scope_id(self.scope), 'codex', 'parent')
        self.assertEqual(invalidated['state'], 'verifying')
        self.assertEqual(invalidated['revision'], fresh['revision'] + 1)
        self.assertEqual(writer['status'], 'prepared')

    def test_first_plan_dependency_reader_blocks_status_after_fresh_verification(self):
        from runtime import delegation
        self.ready_proof_fixture()
        self.assertTrue(self.verify()['verified'])
        dependency = dict(kind='service', key='fixture:first-plan-reader', host='local', mode='read')
        plan = self.coordinator_resource_plan([dict(id='dependency', role='coordinator', claims=[dependency],
            dependencies=[], max_attempts=1)])
        delegation.plan_delegation(self.scope, self.request(plan=plan))
        with state._database(self.scope) as db:
            current = state._task(db, state._scope_id(self.scope), 'codex', 'parent')
        self.assertEqual(current['state'], 'verifying')
        self.assertTrue(self.verify()['verified'])
        owner = delegation.reserve_coordinator(self.scope, self.readiness_owner(claims=[dependency]))
        status = state.task_status(self.scope, 'codex', 'parent')
        self.assertEqual(status['task']['state'], 'verifying')
        blockers = self.api.evidence_status(self.scope, 'codex', 'parent')['evidence']['blockers']
        self.assertTrue(any(owner['attempt_id'] in item for item in blockers))

    def test_linked_checkout_shared_git_reservation_invalidates_ready_in_same_transaction(self):
        from runtime import delegation
        self.ready_proof_fixture()
        ready = self.verify()['task']
        linked = self.root / 'linked'
        self.git('worktree', 'add', '-q', '--detach', str(linked), 'HEAD')
        foreign = replace(self.scope, project_id='linked', repository_root=linked)
        request = self.readiness_owner(scope=foreign, claims=[dict(kind='git', key=str(self.scope.git_common_dir), mode='write')])
        delegation._reserve_operation(foreign, request, role='coordinator')
        with state._database(self.scope) as db:
            current = state._task(db, state._scope_id(self.scope), 'codex', 'parent')
        self.assertEqual(current['state'], 'verifying')
        self.assertEqual(current['revision'], ready['revision'] + 1)

    def test_stale_verification_generation_retains_exact_barrier_and_cannot_publish_ready(self):
        from runtime import delegation
        self.ready_proof_fixture()
        original = self.api.capture_candidate
        def capture(scope, plan):
            candidate = original(scope, plan)
            with state._database(scope, write=True) as db:
                db.execute('update checkouts set generation=generation+1 where scope_id=?', (state._scope_id(scope),))
            return candidate
        with patch.object(self.api, 'capture_candidate', side_effect=capture), self.assertRaises(state.StateError):
            self.verify()
        with state._database(self.scope) as db:
            task = state._task(db, state._scope_id(self.scope), 'codex', 'parent')
            records = [r for r in delegation._ledger(self.scope, db) if r['data']['role'] == 'coordinator']
        self.assertNotEqual(task['state'], 'ready')
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['data']['status'], 'prepared')
        self.assertIsNone(records[0]['data']['reconciliation'])

    def test_ready_status_final_scan_sees_reader_admitted_after_analysis(self):
        from runtime import delegation
        self.ready_proof_fixture()
        ready = self.verify()['task']
        reader = self.readiness_owner(claims=[dict(kind='path', key=str(self.repo / 'app.py'), mode='read')])
        original = self.api._blockers
        admitted = []
        def blockers(*args, **kwargs):
            result = original(*args, **kwargs)
            if not admitted:
                admitted.append(delegation._reserve_operation(self.scope, reader, role='coordinator'))
            return result
        with patch.object(self.api, '_blockers', side_effect=blockers):
            self.api.revalidate_ready(self.scope, 'codex', 'parent')
        with state._database(self.scope) as db:
            current = state._task(db, state._scope_id(self.scope), 'codex', 'parent')
        self.assertEqual(current['state'], 'verifying')
        self.assertEqual(current['revision'], ready['revision'] + 1)

    def test_missing_ready_resource_closure_cannot_establish_independence(self):
        from runtime import delegation
        self.ready_proof_fixture()
        ready = self.verify()['task']
        verification = self.api._read(self.scope, ready['evidence']['verification'])
        verification.pop('resource_closure', None)
        with state._database(self.scope, write=True) as db:
            ready['evidence']['verification'] = self.api._artifact(self.scope, verification)
            state._save(db, state._scope_id(self.scope), ready)
        independent = self.readiness_owner(claims=[dict(kind='service', key='fixture:independent', host='local', mode='read')])
        delegation._reserve_operation(self.scope, independent, role='coordinator')
        with state._database(self.scope) as db:
            current = state._task(db, state._scope_id(self.scope), 'codex', 'parent')
        self.assertEqual(current['state'], 'verifying')
        self.assertEqual(current['revision'], ready['revision'] + 1)

    def test_outside_readonly_hardlink_owner_remains_relevant_to_directory_closure(self):
        from runtime import delegation
        self.ready_proof_fixture()
        outside = self.root / 'outside-alias.py'
        os.link(self.repo / 'app.py', outside)
        reader = self.readiness_owner(claims=[dict(kind='path', key=str(outside), mode='read')])
        delegation._reserve_operation(self.scope, reader, role='coordinator')
        result = self.verify()
        self.assertFalse(result['verified'])
        self.assertNotEqual(result['task']['state'], 'ready')
        self.assertTrue(any('ownership' in item for item in result['blockers']))

    def test_verifier_deduplicates_accepted_root_alias_without_relaxing_external_claims(self):
        from runtime import delegation
        self.ready_proof_fixture()
        root = dict(kind='path', key=str(self.repo), mode='read')
        alias = root | dict(key=str(self.repo) + '/')
        plan = self.coordinator_resource_plan([dict(id='coordinator-root', role='coordinator', claims=[alias], dependencies=[], max_attempts=1)])
        delegation.plan_delegation(self.scope, self.request(plan=plan))
        result = self.verify()
        self.assertTrue(result['verified'])
        verification = self.api._read(self.scope, result['task']['evidence']['verification'])
        self.assertEqual(sum(c['kind'] == 'path' and c.get('path') == str(self.repo) for c in verification['resource_closure']), 1)
        with self.assertRaises(state.StateError):
            delegation._claims([root, alias])

    def test_verifier_preserves_all_64_accepted_instruction_paths(self):
        from runtime import delegation
        paths = []
        prefix = self.root
        for depth in range(8):
            prefix = prefix / ('layer-' + str(depth) + '-' + 'x' * 92)
            prefix.mkdir()
        for number in range(64):
            directory = prefix / ('instruction-' + str(number))
            directory.mkdir()
            path = directory / 'AGENTS.md'
            path.write_text('Fixture instruction input\n')
            paths.append(str(path))
        self.plan(instructions=paths)
        result = self.verify()
        self.assertFalse(result['verified'])
        verification = self.api._read(self.scope, result['task']['evidence']['verification'])
        self.assertTrue(set(paths) <= {c.get('path') for c in verification['resource_closure']})
        self.assertGreater(len(verification['resource_closure']), 64)
        with state._database(self.scope) as db:
            self.assertEqual(delegation._ledger(self.scope, db)[0]['data']['status'], 'settled')
            raw = db.execute('select data from assignments').fetchone()[0]
            self.assertGreater(len(raw.encode()), 128 * 1024)

    def test_verifier_preserves_maximum_accepted_d6_job_resource_union(self):
        from runtime import delegation
        self.ready_proof_fixture()
        jobs = [dict(id='j' + str(job), role='coordinator', dependencies=[], max_attempts=1,
            claims=[dict(kind='service', key='s' + format(job * 64 + item, 'x'), host='local', mode='read') for item in range(64)])
            for job in range(32)]
        plan = self.coordinator_resource_plan(jobs)
        self.assertLessEqual(len(self.api._raw(plan)), 128 * 1024)
        delegation.plan_delegation(self.scope, self.request(plan=plan))
        result = self.verify()
        self.assertTrue(result['verified'])
        expected = {claim['key'] for job in jobs for claim in job['claims']}
        verification = self.api._read(self.scope, result['task']['evidence']['verification'])
        self.assertEqual({c['key'] for c in verification['resource_closure'] if c['kind'] == 'service'}, expected)
        self.assertGreater(len(verification['resource_closure']), 32 * 64)
        with state._database(self.scope) as db:
            rows = [r for r in delegation._ledger(self.scope, db) if r['data']['role'] == 'coordinator']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['data']['status'], 'settled')

    def test_external_operations_keep_individual_claim_and_record_byte_limits(self):
        from runtime import delegation
        too_many = self.readiness_owner(claims=[dict(kind='service', key='s' + str(i), host='local', mode='read') for i in range(65)])
        with self.assertRaises(state.StateError):
            delegation._reserve_operation(self.scope, too_many, role='coordinator')
        request = self.readiness_owner()
        admitted = delegation._reserve_operation(self.scope, request, role='coordinator')
        with state._database(self.scope) as db:
            record = next(r for r in delegation._ledger(self.scope, db) if r['id'] == admitted['attempt_id'])
        data = dict(record['data'], result=dict(padding='x' * (128 * 1024)))
        owner = record['owner']
        row = (record['id'], *(owner[k] for k in ('scope_id', 'client', 'session_id', 'task_id', 'dispatch_id')),
               self.api._raw(data).decode())
        with self.assertRaises(state.StateError):
            delegation._record(self.scope, row)

    def test_final_commit_sees_another_session_reservation_after_blocker_scan(self):
        self.plan()
        self.checked()
        self.review()
        plan = self.api._load_plan(self.scope, self.identity)
        other = self.identity | dict(session_id='other-parent', task_id='other-task')
        state.start_task(self.scope, other | dict(mode='editable', decision_ref='user:accepted'))
        self.api.plan_evidence(self.scope, other | dict(expected_revision=1, plan=plan))
        original = self.api._blockers
        inserted = []
        def blockers(*args, **kwargs):
            result = original(*args, **kwargs)
            if not inserted:
                from runtime import delegation
                owner = self.readiness_owner(identity=other, claims=[dict(kind='path', key=str(self.repo / 'app.py'), mode='read')])
                prepared = delegation.reserve_coordinator(self.scope, owner)
                inserted.append(prepared['attempt_id'])
            return result
        with patch.object(self.api, '_blockers', side_effect=blockers):
            result = self.verify()
        self.assertFalse(result['verified'])
        self.assertNotEqual(result['task']['state'], 'ready')
        self.assertTrue(any(inserted[0] in b for b in result['blockers']))

    def test_detached_writer_cannot_pass_without_exact_current_host_reconciliation(self):
        applicability = dict(applicability='inapplicable', reason='Trivial local synthetic fixture', independent=False)
        self.plan(nontrivial=False, reviews={'general': applicability, 'security': applicability})
        plan = self.api._load_plan(self.scope, self.identity)
        child = "import time; from pathlib import Path; time.sleep(2); Path('app.py').write_text('late detached write')"
        parent = "import subprocess,sys; subprocess.Popen([sys.executable,'-c',%r], start_new_session=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)" % child
        plan['checks'][0]['argv'] = [sys.executable, '-c', parent]
        self.api.plan_evidence(self.scope, self.request(plan=plan, change_decision_ref='user:detached-fixture'))
        result = self.api.run_check(self.scope, self.request(check_id='unit'))
        self.assertEqual(result['attempt']['status'], 'uncertain')
        self.assertEqual(result['attempt']['observed_status'], 'passed')
        self.assertFalse(self.verify()['verified'])
        time.sleep(2.2)
        self.assertEqual((self.repo / 'app.py').read_text(), 'late detached write')

    def test_reconciliation_rejects_bare_assertions_and_mismatched_bindings(self):
        self.plan()
        result = self.api.run_check(self.scope, self.request(check_id='unit'))
        self.assertEqual(result['attempt']['status'], 'uncertain')
        with self.assertRaises(state.StateError):
            self.api.reconcile_check(self.scope, self.request(attempt_id=result['attempt_id'], host_proof={'stopped': True}))
        for changes in ({'attempt_id': '0' * 32}, {'expected_revision': 1}, {'execution_digest': '0' * 64},
                        {'current_candidate_digest': '0' * 64}, {'expected_pins': {}}, {'descendants_stopped': False}):
            with self.subTest(changes=changes), self.assertRaises(state.StateError):
                self.reconcile(result, **changes)
        self.assertEqual(self.reconcile(result)['attempt']['status'], 'passed')

    def test_public_status_exposes_scope_binding_for_host_reconciliation(self):
        self.plan()
        result = self.check()
        status = self.api.evidence_status(self.scope, 'codex', 'parent')
        self.assertEqual(status['scope_id'], state._scope_id(self.scope))
        self.assertEqual(result['scope_id'], status['scope_id'])
        self.assertEqual(status['evidence']['candidate_digest'], result['attempt']['candidate_digest'])

    def test_check_host_proof_rejects_bare_repository_location(self):
        bare = self.root / 'bare.git'
        subprocess.run(['git', 'init', '--bare', '-q', str(bare)], check=True, capture_output=True)
        path = bare / 'host-proof.json'
        raw = b'{}'
        path.write_bytes(raw)
        path.chmod(0o400)
        with self.assertRaises(state.StateError):
            self.api._read_host_proof(self.scope, dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest()))

    def test_reconciled_failure_and_cancelled_reservation_never_become_pass(self):
        self.plan()
        plan = self.api._load_plan(self.scope, self.identity)
        plan['checks'][0]['argv'] = [sys.executable, '-c', 'raise SystemExit(1)']
        self.api.plan_evidence(self.scope, self.request(plan=plan, change_decision_ref='user:failure-fixture'))
        result = self.api.run_check(self.scope, self.request(check_id='unit'))
        self.assertEqual(result['attempt']['status'], 'uncertain')
        self.assertEqual(self.reconcile(result)['attempt']['status'], 'failed')
        _, _, attempt, _ = self.api._reserve(self.scope, self.request(), 'check', dict(check_id='unit'))
        result = self.reconcile({'attempt': attempt})
        self.assertEqual(result['attempt']['status'], 'cancelled')
        self.assertFalse(self.verify()['verified'])

    def test_required_proof_and_ready_only_from_current_verifier(self):
        self.plan()
        self.assertFalse(self.verify()['verified'])
        self.checked()
        self.assertFalse(self.verify()['verified'])
        self.review()
        result = self.verify()
        self.assertTrue(result['verified'], result)
        self.assertEqual(result['task']['state'], 'ready')
        with self.assertRaises(state.StateError):
            state.update_task(self.scope, self.request(state='ready', reason='claim', reference='claim'))
        (self.repo / 'app.py').write_text('value = 2\n')
        result = state.task_status(self.scope, 'codex', 'parent')
        self.assertEqual(result['task']['state'], 'verifying')

    def test_candidate_binds_modes_untracked_index_base_environment_and_linked_checkout(self):
        self.plan()
        candidate = self.api.capture_candidate(self.scope, self.api._load_plan(self.scope, self.identity))
        (self.repo / 'app.py').chmod(0o755)
        self.assertNotEqual(candidate, self.api.capture_candidate(self.scope, self.api._load_plan(self.scope, self.identity)))
        (self.repo / 'app.py').chmod(0o644)
        (self.repo / 'untracked').write_text('one')
        first = self.api.capture_candidate(self.scope, self.api._load_plan(self.scope, self.identity))
        (self.repo / 'untracked').write_text('two')
        self.assertNotEqual(first, self.api.capture_candidate(self.scope, self.api._load_plan(self.scope, self.identity)))
        self.git('worktree', 'add', '-q', '--detach', str(self.root / 'linked'))
        other = replace(self.scope, repository_root=self.root / 'linked')
        self.assertNotEqual(candidate['repository_root'], self.api.capture_candidate(other, self.api._load_plan(self.scope, self.identity))['repository_root'])

    def test_failed_baseline_does_not_satisfy_criterion_and_effects_cannot_expand(self):
        self.plan()
        plan = self.api._load_plan(self.scope, self.identity)
        plan['checks'][0]['argv'] = [sys.executable, '-c', 'raise SystemExit(1)']
        plan['checks'][0]['baseline'].update(status='failed', exit_code=1, output_digest=hashlib.sha256(b'').hexdigest())
        self.api.plan_evidence(self.scope, self.request(plan=plan, change_decision_ref='user:changed-command'))
        result = self.checked()
        self.assertEqual(result['attempt']['status'], 'failed')
        self.assertEqual(result['attempt']['baseline_comparison'], 'pre-existing-failure')
        self.assertFalse(self.verify()['verified'])
        plan['checks'][0]['effects']['network'] = True
        with self.assertRaises(state.StateError):
            self.api.plan_evidence(self.scope, self.request(plan=plan, change_decision_ref='user:claimed'))

    def test_forged_report_identity_and_missing_applicability_remain_blocked(self):
        self.plan(reviews={'general': dict(applicability='unresolved', reason='No capacity', independent=True),
                           'security': dict(applicability='required', reason='Runtime', independent=True)})
        self.checked()
        self.assertFalse(self.verify()['verified'])
        with self.assertRaises(state.StateError):
            self.api.collect_review(self.scope, self.request(attempt_id='forged', receipt={'reviewer_id': 'other'}, report={}))

    def test_check_mutation_timeout_and_running_attempt_block_prior_success(self):
        self.plan()
        self.checked()
        plan = self.api._load_plan(self.scope, self.identity)
        plan['checks'][0]['argv'] = [sys.executable, '-c', "from pathlib import Path; Path('app.py').write_text('changed')"]
        self.api.plan_evidence(self.scope, self.request(plan=plan, change_decision_ref='user:check-change'))
        self.assertEqual(self.checked()['attempt']['status'], 'changed-inputs')
        self.assertFalse(self.verify()['verified'])

    def test_private_immutable_artifacts_and_unsafe_or_oversized_inputs(self):
        self.plan()
        folder = self.scope.runtime.state_dir / 'evidence'
        for path in folder.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o400)
        with self.assertRaises(state.StateError):
            self.api.plan_evidence(self.scope, self.request(plan={'x': 'a' * (128 * 1024)}))
        (self.repo / 'link').symlink_to(self.repo / 'app.py')
        with self.assertRaises(state.StateError):
            self.checked()

    def test_ready_has_no_stop_continuation_and_harmless_generation_does_not_erase_proof(self):
        from runtime.engine import RuntimeEvent
        self.plan()
        self.checked()
        self.review()
        self.assertTrue(self.verify()['verified'])
        event = RuntimeEvent('PostToolUse', 'codex', 'parent', self.repo, 'turn', 'call', 'read_file', False, 'receipt')
        state.process_event(self.scope, event)
        self.assertEqual(state.task_status(self.scope, 'codex', 'parent')['task']['state'], 'ready')
        self.assertEqual(state.process_event(self.scope, replace(event, kind='Stop')).action, 'pass')

    def test_security_impact_must_be_reassessed_after_candidate_change(self):
        self.plan()
        (self.repo / 'app.py').write_text('value = 2\n')
        self.checked()
        self.review()
        result = self.verify()
        self.assertFalse(result['verified'])
        self.assertTrue(any('impact' in b for b in result['blockers']))
        impact = dict(status='assessed', reason='Rechecked the changed runtime boundary', reference='code:new-impact')
        self.assertTrue(self.verify(security_impact=impact)['verified'])

    def assert_interleaved_check_diagnostics(self, cancel):
        from runtime import delegation
        self.plan()
        plan = self.api._load_plan(self.scope, self.identity)
        plan['checks'][0]['argv'] = [sys.executable, '-c', "print('actual failure'); raise SystemExit(7)"]
        self.api.plan_evidence(self.scope, self.request(plan=plan, change_decision_ref='user:failure-fixture'))
        request = self.request(check_id='unit', dispatch_id='interleaved-check')
        execute = self.api._execute
        interleaved = []
        def execute_with_operation(*args):
            if cancel:
                state.update_task(self.scope, self.request(state='cancelled', reason='User cancelled during check',
                    reference='user:cancelled'))
            else:
                delegation.reserve_coordinator(self.scope, self.readiness_owner(identity=self.identity,
                    claims=[dict(kind='path', key=str(self.repo / 'app.py'), mode='read')]))
            with state._database(self.scope) as db:
                interleaved.append(state._task(db, state._scope_id(self.scope), 'codex', 'parent'))
            return execute(*args)
        with patch.object(self.api, '_execute', side_effect=execute_with_operation):
            result = self.api.run_check(self.scope, request)
        attempt = result['attempt']
        self.assertEqual(attempt['exit_code'], 7)
        self.assertEqual(attempt['observed_status'], 'failed')
        self.assertEqual(attempt['status'], 'uncertain')
        execution = self.api._read(self.scope, attempt['execution'])
        self.assertEqual(self.api._read(self.scope, execution['output'])['text'], 'actual failure')
        self.assertEqual(execution['result']['exit_code'], 7)
        with state._database(self.scope) as db:
            record = next(r for r in delegation._ledger(self.scope, db) if r['id'] == attempt['id'])
            current = state._task(db, state._scope_id(self.scope), 'codex', 'parent')
        self.assertEqual(record['data']['observation'], attempt['execution'])
        self.assertEqual(record['data']['status'], 'uncertain')
        for field in ('state', 'reason', 'reference', 'pins', 'conditions'):
            self.assertEqual(current[field], interleaved[0][field])
        self.assertEqual(current['revision'], interleaved[0]['revision'] + 1)
        with patch.object(self.api, '_execute', side_effect=AssertionError('stable replay reran command')):
            replay = self.api.run_check(self.scope, request)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['attempt'], attempt)
        self.assertEqual(replay['task'], current)
        if not cancel:
            with self.assertRaisesRegex(state.StateError, 'revision conflict'):
                delegation.reserve_coordinator(self.scope, self.readiness_owner(identity=self.identity,
                    dispatch='stale', claims=[dict(kind='path', key=str(self.repo / 'app.py'), mode='read')]) |
                    dict(expected_revision=request['expected_revision']))
        with self.assertRaises(state.StateError):
            self.reconcile(result, expected_revision=request['expected_revision'])
        settled = self.reconcile(result)
        self.assertEqual(settled['attempt']['status'], 'failed')
        self.assertEqual(settled['attempt']['exit_code'], 7)
        self.assertEqual(settled['task']['state'], current['state'])

    def test_check_result_survives_compatible_same_task_reservation_during_execution(self):
        self.assert_interleaved_check_diagnostics(cancel=False)

    def test_check_result_survives_task_cancellation_during_execution(self):
        self.assert_interleaved_check_diagnostics(cancel=True)

    def test_check_keeps_private_redacted_inspectable_output_and_unknown_failure_comparison(self):
        self.plan()
        plan = self.api._load_plan(self.scope, self.identity)
        plan['checks'][0]['argv'] = [sys.executable, '-c', "print('API_KEY=never-save-this'); print('failure at app.py:1'); raise SystemExit(1)"]
        plan['checks'][0]['baseline']['status'] = 'failed'
        self.api.plan_evidence(self.scope, self.request(plan=plan, change_decision_ref='user:diagnostic'))
        attempt = self.checked()['attempt']
        self.assertEqual(attempt['baseline_comparison'], 'unresolved-failure-comparison')
        execution = self.api._read(self.scope, attempt['execution'])
        output = self.api._read(self.scope, execution['output'])
        self.assertIn('failure at app.py:1', output['text'])
        self.assertNotIn('never-save-this', output['text'])
        self.assertNotIn('never-save-this', json.dumps(attempt))

    def test_timeout_with_surviving_descendant_remains_uncertain_after_new_pass(self):
        self.plan()
        plan = self.api._load_plan(self.scope, self.identity)
        # The child drops stdout, so parent exit/pipe EOF cannot establish its lifecycle.
        plan['checks'][0]['argv'] = [sys.executable, '-c',
            "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(1.5)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); time.sleep(3)"]
        plan['checks'][0]['timeout'] = 1
        self.api.plan_evidence(self.scope, self.request(plan=plan, change_decision_ref='user:timeout'))
        outcome = self.checked()['attempt']
        self.assertEqual(outcome['status'], 'uncertain')
        with self.assertRaises(state.StateError):
            self.api.plan_evidence(self.scope, self.request(plan=plan, change_decision_ref='user:retry'))
        self.assertFalse(self.verify()['verified'])

    def test_corrupt_check_receipt_cannot_establish_readiness(self):
        self.plan()
        checked = self.checked()['attempt']
        self.review()
        path = self.scope.runtime.state_dir / 'evidence' / checked['execution']['name']
        path.chmod(0o600)
        path.write_text('{}')
        path.chmod(0o400)
        with self.assertRaises(state.StateError):
            self.verify()

    def test_relevant_ignored_input_is_captured_and_timeout_is_not_a_pass(self):
        (self.repo / '.gitignore').write_text('ignored.txt\n')
        (self.repo / 'ignored.txt').write_text('first')
        self.plan(relevant_untracked=['ignored.txt'])
        plan = self.api._load_plan(self.scope, self.identity)
        first = self.api.capture_candidate(self.scope, plan)
        (self.repo / 'ignored.txt').write_text('second')
        self.assertNotEqual(first, self.api.capture_candidate(self.scope, plan))
        plan['checks'][0]['argv'] = [sys.executable, '-c', 'import time; time.sleep(3)']
        plan['checks'][0]['timeout'] = 1
        self.api.plan_evidence(self.scope, self.request(plan=plan, change_decision_ref='user:timeout-proof'))
        self.assertIn(self.checked()['attempt']['status'], {'timed-out', 'uncertain'})
        self.assertFalse(self.verify()['verified'])

    def test_changed_content_cannot_erase_surviving_writer_uncertainty(self):
        self.plan()
        def uncertain(scope, check, tool):
            (self.repo / 'app.py').write_text('changed while an unknown writer remains')
            return dict(status='uncertain', exit_code=None, output_digest=hashlib.sha256(b'').hexdigest(),
                        private_output={'text': '', 'truncated': False})
        with patch.object(self.api, '_execute', side_effect=uncertain):
            result = self.checked()
        self.assertEqual(result['attempt']['status'], 'uncertain')
        self.assertTrue(result['attempt']['inputs_changed'])
        self.assertFalse(self.verify()['verified'])

    def test_cancel_and_replace_cannot_forget_uncertain_checkout_writer(self):
        self.plan()
        self.api._reserve(self.scope, self.request(), 'check', dict(check_id='unit'))
        result = state.update_task(self.scope, self.request(state='cancelled', reason='Interrupted parent', reference='user:cancel'))
        old_revision = result['task']['revision']
        with self.assertRaises(state.StateError):
            state.start_task(self.scope, self.identity | dict(task_id='replacement', mode='editable', decision_ref='user:accepted',
                replaces=dict(task_id='task', expected_revision=old_revision)))
        self.assertEqual(state.task_status(self.scope, 'codex', 'parent')['task']['task_id'], 'task')

    def test_latest_unresolved_attempt_cannot_hide_behind_prior_pass(self):
        self.plan()
        self.checked()
        self.review()
        prepared = self.api.prepare_review(self.scope, self.native_review_request(coverage=['general'], criteria=['works'],
            assignment='Review pending latest change read-only.'))
        result = self.verify()
        self.assertFalse(result['verified'])
        self.assertTrue(any('unresolved' in b for b in result['blockers']))
        self.assertEqual(self.api.prepared_native_review(self.scope, prepared['attempt_id'])['parent_session_id'], 'parent')

    def test_scoped_evidence_reuse_requires_unchanged_declared_dependencies(self):
        self.plan()
        check = self.checked()['attempt_id']
        review = self.review()['attempt_id']
        (self.repo / 'unrelated.txt').write_text('unrelated documentation')
        self.assertFalse(self.verify()['verified'])
        reuse = [dict(attempt_id=a, reason='Only unrelated text changed; app.py and its dependencies unchanged',
                      dependencies=['app.py']) for a in (check, review)]
        impact = dict(status='assessed', reason='Unrelated text has no security boundary change', reference='code:impact-recheck')
        self.assertTrue(self.verify(reuse=reuse, security_impact=impact)['verified'])
        (self.repo / 'app.py').write_text('value = 2\n')
        self.assertFalse(self.verify(reuse=reuse)['verified'])

    def test_concurrent_update_during_verification_is_not_overwritten(self):
        self.plan()
        self.checked()
        self.review()
        request = self.request(purpose='completion')
        original = self.api.capture_candidate
        def capture(scope, plan):
            candidate = original(scope, plan)
            state.update_task(scope, self.request(state='blocked', reason='Intervening decision', reference='user:hold'))
            return candidate
        with patch.object(self.api, 'capture_candidate', side_effect=capture), self.assertRaises(state.StateError):
            self.api.verify_completion(self.scope, request)
        self.assertEqual(state.task_status(self.scope, 'codex', 'parent')['task']['state'], 'blocked')

    def test_confirmed_security_finding_survives_edits_and_needs_scoped_fresh_review(self):
        self.plan()
        self.checked()
        finding = dict(id='security-1', severity='high', scope='security', status='confirmed',
                       location='app.py:1 working', scenario='Reachable unsafe path', evidence='Code tracing',
                       counterevidence='No applicable guard')
        prior = self.review(findings=[finding])['attempt_id']
        self.assertFalse(self.verify()['verified'])
        (self.repo / 'app.py').write_text('value = 2\n')
        self.plan()
        self.checked()
        fresh = self.review()['attempt_id']
        self.assertFalse(self.verify()['verified'])
        # A fresh assessment explicitly links code verification to the old immutable finding.
        with state._database(self.scope) as db:
            task = state._task(db, state._scope_id(self.scope), 'codex', 'parent')
            attempt = next(a for a in task['evidence']['attempts'] if a['id'] == fresh)
        assessment = self.api._read(self.scope, attempt['assessment'])['assessment']
        assessment['rechecked_findings'] = [dict(attempt_id=prior, finding_id='security-1', status='resolved',
                                                reference='fresh:code-and-caller-proof')]
        self.api.assess_review(self.scope, self.request(attempt_id=fresh, assessment=assessment))
        self.assertTrue(self.verify()['verified'])

    def test_tool_and_base_ref_changes_invalidate_previous_proof(self):
        self.plan()
        plan = self.api._load_plan(self.scope, self.identity)
        before = self.api.capture_candidate(self.scope, plan)
        plan['checks'][0]['env']['LANG'] = 'C'
        self.assertNotEqual(before, self.api.capture_candidate(self.scope, plan))
        self.git('commit', '--allow-empty', '-qm', 'moved base')
        after = self.api.capture_candidate(self.scope, self.api._load_plan(self.scope, self.identity))
        self.assertNotEqual(before['base'], after['base'])

    def test_merge_evidence_never_grants_merge_authority(self):
        self.plan()
        self.checked()
        self.review()
        result = self.api.verify_completion(self.scope, self.request(purpose='merge-evidence'))
        self.assertTrue(result['verified'], result)
        self.assertFalse(result['merge_authority'])
        self.assertNotEqual(result['task']['state'], 'ready')


if __name__ == '__main__':
    unittest.main()


class CanonicalEvidenceTests(unittest.TestCase):
    def setUp(self):
        from tests.test_state import canonical_scope
        self.fixture = EvidenceTests(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.scope = canonical_scope(self.fixture.scope)
        self.scope = self.fixture.scope
        state.start_task(self.scope, self.fixture.identity | dict(mode='editable', decision_ref='user:accepted'))
        self.fixture.plan()

    def test_canonical_candidate_carries_immutable_selected_identity_and_rejects_replaced_git(self):
        import shutil
        plan = self.fixture.api._load_plan(self.scope, self.fixture.identity)
        candidate = self.fixture.api.capture_candidate(self.scope, plan)
        self.assertEqual(candidate['accepted_identity']['checkout_id'], self.scope.checkout_id)
        self.assertEqual(candidate['pins']['accepted_scope_digest'], self.scope.accepted_scope_digest)
        old = self.fixture.root / 'old-git'
        self.scope.git_common_dir.rename(old)
        shutil.copytree(old, self.scope.git_common_dir)
        with self.assertRaises(state.StateError): self.fixture.api.capture_candidate(self.scope, plan)

    def test_canonical_check_reconciliation_uses_original_four_key_pins(self):
        result = self.fixture.checked()
        self.assertEqual(result['attempt']['status'], 'passed')
        with state._database(self.scope) as db:
            from runtime import delegation
            record = delegation._ledger(self.scope, db)[0]
        self.assertEqual(record['body']['accepted_identity']['checkout_id'], 'checkout')
        self.assertEqual(record['body']['pins']['schema_version'], 3)

    def test_canonical_selected_dependency_is_reobserved_without_pinning_authority_revision(self):
        from runtime.startup import _canonical_plain, _canonical_freeze
        scope = self.scope
        shared = self.fixture.root / 'shared-guide.md'
        shared.write_text('accepted workflow\n')
        identity = _canonical_plain(scope.accepted_identity)
        identity['shared_policy'] = [dict(path=str(shared), sha256=hashlib.sha256(shared.read_bytes()).hexdigest())]
        scope = replace(scope, accepted_identity=_canonical_freeze(identity), accepted_scope_digest=self.fixture.api._digest(identity))
        plan = self.fixture.api._load_plan(self.scope, self.fixture.identity)
        before = self.fixture.api.capture_candidate(scope, plan)
        self.assertEqual(before, self.fixture.api.capture_candidate(replace(scope, authority_revision=scope.authority_revision+1), plan))
        shared.write_text('changed workflow\n')
        with self.assertRaises(state.StateError): self.fixture.api.capture_candidate(scope, plan)


class LinkedPlanTests(unittest.TestCase):
    setUp = CanonicalEvidenceTests.setUp

    def reference(self, task_id):
        directory = self.scope.runtime.state_dir
        def binding(path):
            info = path.stat()
            return dict(device=info.st_dev, inode=info.st_ino)
        return dict(authority=dict(directory=str(directory), database=str(directory / 'runtime.sqlite3'),
            directory_binding=binding(directory), database_binding=binding(directory / 'runtime.sqlite3')),
            scope_id=state._scope_id(self.scope), client='codex', session_id='parent', task_id=task_id)

    def linked_plan(self, own_delivery=None, companions=()):
        from copy import deepcopy
        plan = deepcopy(self.fixture.api._load_plan(self.scope, self.fixture.identity))
        plan.update(version=2, linked=dict(acceptance=[dict(id='integrated', text='Both changes work together')],
            delivery=own_delivery, companions=list(companions)))
        return plan

    def test_self_plus_peers_normalizes_both_directions_and_no_publication(self):
        api = self.fixture.api
        a, b = self.reference('a'), self.reference('b')
        left = self.linked_plan(companions=[dict(task=b, delivery=None)])
        right = self.linked_plan(companions=[dict(task=a, delivery=None)])
        self.assertEqual(api._linked_projection(a, api._plan(left)), api._linked_projection(b, api._plan(right)))
        self.assertEqual([row['delivery'] for row in api._linked_projection(a, left)['participants']], [None, None])

    def test_missing_third_member_and_divergent_delivery_are_not_equal(self):
        api = self.fixture.api
        a, b, c = [self.reference(key) for key in ('a', 'b', 'c')]
        delivery = dict(provider='github', repository='owner/repo', target='main', pull_request='https://github.com/owner/repo/pull/1')
        complete = self.linked_plan(companions=[dict(task=b, delivery=delivery), dict(task=c, delivery=None)])
        missing = self.linked_plan(own_delivery=delivery, companions=[dict(task=a, delivery=None)])
        self.assertNotEqual(api._linked_projection(a, api._plan(complete)), api._linked_projection(b, api._plan(missing)))
        divergent = self.linked_plan(own_delivery=delivery | dict(target='release'),
            companions=[dict(task=a, delivery=None), dict(task=c, delivery=None)])
        self.assertNotEqual(api._linked_projection(a, complete), api._linked_projection(b, api._plan(divergent)))

    def test_duplicate_peer_self_peer_and_duplicate_shared_criterion_reject(self):
        api = self.fixture.api
        a, b = self.reference('a'), self.reference('b')
        duplicate = self.linked_plan(companions=[dict(task=b, delivery=None), dict(task=b, delivery=None)])
        with self.assertRaises(state.StateError): api._plan(duplicate)
        self_peer = self.linked_plan(companions=[dict(task=a, delivery=None)])
        with self.assertRaises(state.StateError): api._linked_projection(a, api._plan(self_peer))
        criteria = self.linked_plan()
        criteria['linked']['acceptance'] *= 2
        with self.assertRaises(state.StateError): api._plan(criteria)

    def test_legacy_owner_cannot_admit_v2_plan(self):
        plan = self.linked_plan()
        legacy = EvidenceTests(methodName='runTest')
        legacy.setUp()
        self.addCleanup(legacy.doCleanups)
        with self.assertRaises(state.StateError):
            legacy.api.plan_evidence(legacy.scope, legacy.request(plan=plan))

    def test_local_completion_cannot_pass_unverified_shared_acceptance(self):
        self.fixture.api.plan_evidence(self.scope, self.fixture.request(plan=self.linked_plan(),
            change_decision_ref='fixture:linked-acceptance'))
        with self.assertRaisesRegex(state.StateError, 'Linked'):
            self.fixture.api.verify_completion(self.scope, self.fixture.request(purpose='completion'))


    def test_admission_rejects_self_companion_without_writes(self):
        api = self.fixture.api
        with state._database(self.scope) as db:
            before = state._task(db, state._scope_id(self.scope), 'codex', 'parent')
        folder = self.scope.runtime.state_dir / 'evidence'
        files = set(folder.iterdir())
        plan = self.linked_plan(companions=[dict(task=self.reference('task'), delivery=None)])
        with self.assertRaises(state.StateError):
            api.plan_evidence(self.scope, self.fixture.request(plan=plan, change_decision_ref='fixture:invalid-self'))
        with state._database(self.scope) as db:
            after = state._task(db, state._scope_id(self.scope), 'codex', 'parent')
        self.assertEqual(after, before)
        self.assertEqual(set(folder.iterdir()), files)


class ArtifactLifecycleTests(unittest.TestCase):
    setUp = CanonicalEvidenceTests.setUp

    def owner(self):
        with state._database(self.scope) as db:
            task = state._task(db, state._scope_id(self.scope), 'codex', 'parent')
        return self.fixture.api._artifact_owner(self.scope, task)

    def test_artifact_registers_observed_file_before_reference_return(self):
        api = self.fixture.api
        reference = api._artifact(self.scope, dict(result='actual content'), owner=self.owner())
        path = self.scope.runtime.state_dir / 'evidence' / reference['name']
        with state._database(self.scope) as db:
            metadata = state._metadata(db, reference['name'])
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata['owner']['project_id'], 'fixture')
        self.assertEqual(metadata['owner']['task']['task_id'], 'task')
        self.assertEqual(metadata['managed']['binding']['inode'], path.stat().st_ino)
        self.assertEqual(metadata['bytes'], len(path.read_bytes()))
        self.assertEqual(metadata['managed']['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertIsNone(metadata['closed_at'])

    def test_registration_uses_existing_writer_and_rollback_leaves_protected_orphan(self):
        api = self.fixture.api
        owner = self.owner()
        with self.assertRaisesRegex(RuntimeError, 'rollback fixture'):
            with state._database(self.scope, write=True) as db:
                reference = api._artifact(self.scope, dict(result='uncommitted'), owner=owner, db=db)
                self.assertIsNotNone(state._metadata(db, reference['name']))
                raise RuntimeError('rollback fixture')
        self.assertTrue((self.scope.runtime.state_dir / 'evidence' / reference['name']).exists())
        with state._database(self.scope) as db:
            self.assertIsNone(state._metadata(db, reference['name']))
        with self.assertRaises(state.StateError):
            api._read(self.scope, reference)

    def test_arbitrary_owner_mapping_and_foreign_connection_cannot_register(self):
        api = self.fixture.api
        with self.assertRaises(state.StateError):
            api._artifact(self.scope, dict(result='unowned'), owner=dict(kind='project', project_id='fixture', task=None))
        import sqlite3
        with sqlite3.connect(':memory:') as foreign:
            with self.assertRaises(state.StateError):
                api._artifact(self.scope, dict(result='foreign'), owner=self.owner(), db=foreign)

    def test_same_byte_replacement_fails_physical_metadata_validation(self):
        api = self.fixture.api
        reference = api._artifact(self.scope, dict(result='physical original'), owner=self.owner())
        path = self.scope.runtime.state_dir / 'evidence' / reference['name']
        replacement = path.with_suffix('.copy')
        replacement.write_bytes(path.read_bytes())
        replacement.chmod(0o400)
        replacement.replace(path)
        with self.assertRaises(state.StateError):
            api._managed_artifact(self.scope, reference)


    def test_read_consumes_only_the_descriptor_validated_before_path_replacement(self):
        api = self.fixture.api
        reference = api._artifact(self.scope, dict(result='original'), owner=self.owner())
        path = self.scope.runtime.state_dir / 'evidence' / reference['name']
        original = api._managed_artifact
        original_open = os.open
        opened = []
        def track_open(target, *args, **kwargs):
            if Path(target) == path:
                opened.append(target)
            return original_open(target, *args, **kwargs)
        def replace_after_validation(*args, **kwargs):
            checked = original(*args, **kwargs)
            replacement = path.with_suffix('.copy')
            replacement.write_bytes(path.read_bytes())
            replacement.chmod(0o400)
            replacement.replace(path)
            return checked
        with patch.object(api, '_managed_artifact', side_effect=replace_after_validation), \
             patch.object(api.os, 'open', side_effect=track_open):
            self.assertEqual(api._read(self.scope, reference), dict(result='original'))
        self.assertEqual(len(opened), 1, 'schema3 consumption reopened a different pathname identity')


class RecoveryContextTests(unittest.TestCase):
    setUp = CanonicalEvidenceTests.setUp
    owner = ArtifactLifecycleTests.owner

    def test_existing_context_reads_managed_artifact_and_baseline_without_scope(self):
        api=self.fixture.api
        reference=api._artifact(self.scope,dict(result='observed'),owner=self.owner())
        with state._database(self.scope) as db:
            observed=api._evidence_context(self.scope)
            context=api._existing_authority_context(dict(observed.authority_set[0]),db=db)
            self.assertEqual(api._read(None,reference,context=context,db=db),dict(result='observed'))
            baseline=state._source_baseline(None,db,context=context)
            self.assertEqual(baseline['content']['source_contract'],2)
            with self.assertRaises(state.StateError): api._read(self.scope,reference,context=context,db=db)
        path=self.scope.runtime.state_dir/'evidence'/reference['name']
        raw=path.read_bytes(); replacement=path.with_name('replacement'); replacement.write_bytes(raw); replacement.chmod(0o400); replacement.replace(path)
        with self.assertRaises(state.StateError): api._read(None,reference,context=context)

    def test_existing_context_rejects_database_binding_substitution(self):
        api=self.fixture.api
        with state._database(self.scope) as db:
            authority=dict(api._evidence_context(self.scope).authority_set[0]); authority['database_binding']=dict(device=0,inode=0)
            with self.assertRaises(state.StateError): api._existing_authority_context(authority,db=db)

    def test_historical_ledger_and_linked_attempt_route_every_read_through_context(self):
        from runtime import delegation
        self.fixture.checked()
        api=self.fixture.api; original=api._read; calls=[]
        with state._database(self.scope) as db:
            context=api._existing_authority_context(state._authority_identity(state._path(self.scope)),db=db)
            def read(scope,reference,**kwargs):
                self.assertIsNone(scope); self.assertIs(kwargs['context'],context); self.assertIs(kwargs['db'],db)
                calls.append(reference)
                return original(scope,reference,**kwargs)
            with patch.object(api,'_read',side_effect=read):
                records=delegation._ledger(None,db,context=context)
                task=state._task(db,state._scope_id(self.scope),'codex','parent')
                for attempt in task['evidence']['attempts']:
                    delegation._linked_attempt(None,state._scope_id(self.scope),task,attempt,records,context=context,db=db)
        self.assertTrue(calls)


class CancelledClosureTests(unittest.TestCase):
    """Disposable owner-proof fixtures; no native stop authority is qualified here."""
    def setUp(self):
        from tests.test_state import StateTests,canonical_scope
        self.f=StateTests(methodName='runTest');self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.scope=canonical_scope(self.f.scope);self.scope=self.f.scope
        from runtime import evidence
        self.api=evidence
        with patch.object(state,'_owner_time',return_value=100):self.f.start()
        self.f.update(state='active')
        self.f.event(kind='UserPromptSubmit',tool_call_id=None)
        self.f.event()
        task=self.f.status()['task']
        identity={k:task[k] for k in ('client','session_id','task_id','scope_ref')}
        proof=dict(version=1,kind='stopped-writer-reconciliation',identity=identity,expected_revision=task['revision'],
            expected_pins=task['pins'],observed_turn_id=task['turn_id'],stopped=True,descendants_stopped=True,
            attempt_ids=[],observation_ref='fixture:independent-stop',coordinator_ref='fixture:checked')
        raw=json.dumps(proof).encode();path=self.f.base/'stop.json';path.write_bytes(raw);path.chmod(0o400)
        self.task=state.retire_task(self.scope,identity|dict(expected_revision=task['revision'],expected_pins=task['pins'],
            reason='Stopped',reference='fixture:cancel',stop_proof=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest())))['task']
        self.context=self.api._evidence_context(self.scope)
        self.ref=self.api._canonical_plain(self.api._artifact_owner(self.scope,self.task).task)
        self.request=identity|dict(expected_revision=self.task['revision'],expected_pins=self.task['pins'])

    def close(self):
        observed=self.api._observe_closure((self.context,),self.ref)
        return self.api.close_task(self.scope,self.request,observed)

    def test_cancelled_dated_owner_closes_without_changing_revision_or_age(self):
        with patch.object(state,'_owner_time',return_value=200):result=self.close()
        task=result['task'];self.assertEqual(task['revision'],self.task['revision'])
        self.assertEqual(task['retirement'],self.task['retirement'])
        self.assertEqual(task['lifecycle']['created_at'],100)
        self.assertEqual(task['lifecycle']['safe_closed_at'],200)
        compact=self.api._read(self.scope,task['lifecycle']['compact'])
        self.assertEqual(compact['outcome'],'cancelled');self.assertEqual(compact['numerical'],[])
        self.assertEqual(compact['usage'],'unknown')
        with patch.object(state,'_owner_time',return_value=300):self.assertEqual(self.close()['task'],task)

    def test_atomic_retirement_preserves_exact_replay_markers(self):
        with patch.object(state,'_owner_time',return_value=200):self.close()
        with patch.object(state,'_owner_time',return_value=250):self.api._retire_closed_task(self.context,self.ref)
        with self.api._context_database(self.context) as db:
            self.assertEqual(db.execute('select count(*) from tasks').fetchone()[0],0)
            marker=state._retired(db,'task',{k:self.ref[k] for k in ('scope_id','client','session_id','task_id')})
            self.assertEqual(marker['created_at'],100);self.assertEqual(marker['outcome'],'cancelled')
        with self.assertRaises(state.StateError):self.f.start()

    def test_unproved_cancelled_flag_and_caller_snapshot_cannot_close(self):
        with self.assertRaises(state.StateError):self.api.close_task(self.scope,self.request,dict(closed=True,stopped=True))
        with state._database(self.scope,write=True) as db:
            task=state._task(db,self.ref['scope_id'],'codex','session');task.pop('retirement')
            db.execute('update tasks set data=?',(json.dumps(task),))
        with self.assertRaises(state.StateError):self.close()


    def test_closed_identity_refuses_side_effects_but_history_and_new_identity_remain(self):
        task=self.close()['task']
        self.assertEqual(state.task_status(self.scope,'codex','session')['task'],task)
        review=dict(applicability='inapplicable',reason='Trivial unexecuted accepted check',independent=False)
        plan=dict(version=1,decision_ref='user:accepted',criteria=[dict(id='works',checks=['unit'],behavior=False)],
            checks=[dict(id='unit',argv=[sys.executable,'-c','pass'],cwd='.',timeout=3,env={'PATH':os.defpath},
                effects=dict(kind='read-only',inspection_ref='fixture:inspected',network=False,production=False,publish=False,migrations=False),
                baseline=dict(status='passed',reference='fixture:baseline'),dependencies=[])],
            reviews=dict(general=review,security=review),security_impact=dict(status='assessed',reason='Local fixture',reference='fixture:checked'),
            base='HEAD',comparison='endpoint',nontrivial=False,instructions=[],exclusions=[],review_limit=1)
        self.api._plan(plan)
        with patch.object(self.api,'capture_candidate',side_effect=AssertionError('capture after closure')), \
             patch.object(self.api,'_artifact',side_effect=AssertionError('artifact after closure')):
            request={k:self.request[k] for k in self.api.IDENTITY}
            with self.assertRaisesRegex(state.StateError,'Safely closed'):self.api.plan_evidence(self.scope,request|dict(plan=plan))
            with self.assertRaises(state.StateError):self.f.start()
        before=self.api._canonical_plain(task)
        self.assertEqual(self.f.event().action,'deny')
        with state._database(self.scope) as db:
            self.assertEqual(state._task(db,self.ref['scope_id'],'codex','session'),before)
        new=self.f.start(task_id='new-task',replaces=dict(task_id='task',expected_revision=task['revision']))
        self.assertEqual(new['task']['task_id'],'new-task')
        with state._database(self.scope) as db:
            self.assertEqual(state._task(db,self.ref['scope_id'],'codex','session','task'),before)

    def test_terminal_admission_stops_native_discovery_commands_and_git_plan_probe(self):
        from runtime import delegation
        self.close();request={k:self.request[k] for k in self.api.IDENTITY}
        native=request|dict(dispatch_id='new',job_id='job',selection={},control_observation={},
            discovery_expectation={},guidance={},resource_units=1,brief={})
        with patch.object(delegation,'_discovery',side_effect=AssertionError('native discovery')), \
             patch.object(delegation,'_git_directory',side_effect=AssertionError('Git probe')), \
             patch.object(self.api,'_execute',side_effect=AssertionError('command execution')):
            with self.assertRaisesRegex(state.StateError,'Safely closed'):delegation._prepare_native(self.scope,native,role='worker')
            with self.assertRaisesRegex(state.StateError,'Safely closed'):delegation.plan_delegation(self.scope,request|dict(plan={}))
            with self.assertRaisesRegex(state.StateError,'Safely closed'):self.api.run_check(self.scope,request|dict(check_id='unit'))
            with self.assertRaisesRegex(state.StateError,'Safely closed'):self.api.verify_completion(self.scope,request|dict(purpose='completion'))

    def test_closed_session_external_completion_invalidates_other_task_checkout(self):
        task=self.close()['task']
        state.start_task(self.scope,self.f.request|dict(session_id='other',task_id='other-task'))
        before=state.task_status(self.scope,'codex','other')['generation']
        result=self.f.event(kind='PostToolUse',tool_call_id='external-new-call')
        self.assertEqual(result.action,'context')
        self.assertEqual(state.task_status(self.scope,'codex','other')['generation'],before+1)
        with state._database(self.scope) as db:
            self.assertEqual(state._task(db,self.ref['scope_id'],'codex','session'),task)
            self.assertIsNone(db.execute("select 1 from receipts where tool_call_id='external-new-call'").fetchone())

    def test_marker_failure_rolls_back_all_rows_and_markers(self):
        self.close();original=state._retired_record
        def fail(kind,*args):
            if kind=='turn':raise state.StateError('fixture:before second marker')
            return original(kind,*args)
        with patch.object(state,'_retired_record',side_effect=fail):
            with self.assertRaises(state.StateError):self.api._retire_closed_task(self.context,self.ref)
        with self.api._context_database(self.context) as db:
            self.assertEqual(db.execute('select count(*) from tasks').fetchone()[0],1)
            self.assertEqual(db.execute('select count(*) from retired_identities').fetchone()[0],0)
            self.assertEqual(db.execute('select count(*) from turns').fetchone()[0],1)

    def test_substituted_same_byte_stop_content_blocks_retirement(self):
        task=self.close()['task']
        path=self.context.directory/'evidence'/task['retirement']['proof']['name']
        replacement=path.with_name('replacement.json');replacement.write_bytes(path.read_bytes());replacement.chmod(0o400)
        os.replace(replacement,path)
        with self.assertRaises(state.StateError):self.api._retire_closed_task(self.context,self.ref)
    def test_actual_d4_source_cut_composes_atomic_retirement_and_rollback(self):
        from tests.test_changes import ScopedChangesTests
        f=ScopedChangesTests(methodName='runTest');f.setUp();self.addCleanup(f.doCleanups)
        request,context,ref,identity,old=f.recovery_release_fixture()
        with self.assertRaises(state.StateError):self.api._observe_closure((context,),ref)
        released=f.changes._register_recovery_release(f.changes._observe_recovery_release(context.authority_set,identity))
        self.assertTrue(released['complete'])
        observed=self.api._observe_closure((context,),ref)
        with self.api._context_database(context) as db:
            task=state._task(db,ref['scope_id'],ref['client'],ref['session_id'],ref['task_id'])
        selected={k:task[k] for k in ('client','session_id','task_id','scope_ref')}
        self.api.close_task(f.release_fixture_scope,selected|dict(expected_revision=task['revision'],expected_pins=task['pins']),observed)
        self.api._retire_closed_task(context,ref)
        self.assertTrue(f.changes.inspect_lifecycle_recovery(context.authority_set,(ref,))['complete'])
        resumed=f.changes._run_scoped(f.directory,request,'resume');self.assertEqual(resumed['exit_code'],0,resumed)
        rolled=f.changes._run_scoped(f.directory,request,'rollback');self.assertEqual(rolled['exit_code'],0,rolled)
        self.assertTrue(f.changes.inspect_lifecycle_recovery(context.authority_set,(ref,))['complete'])

    def test_retired_artifact_attribution_requires_retained_owned_compact(self):
        task=self.close()['task'];self.api._retire_closed_task(self.context,self.ref)
        compact=task['lifecycle']['compact']
        with self.api._context_database(self.context,write=True) as db:
            db.execute('delete from evidence_metadata where name=?',(compact['name'],))
        (self.context.directory/'evidence'/compact['name']).unlink()
        root=dict(owner=dict(authority=self.ref['authority'],artifact=task['retirement']['proof']),
            kind='artifact',reference=task['retirement']['proof'],need='content')
        with self.api._context_database(self.context) as db:
            with self.assertRaises(state.StateError):self.api._lifecycle_requirements(self.context,[root],db=db)

    def test_lower_writers_reject_unissued_mapping_even_with_current_rows(self):
        observed=self.api._canonical_plain(self.api._observe_closure((self.context,),self.ref).facts)
        forged=json.loads(json.dumps(observed));forged['certificate']['proof']['stopped']=False
        content=self.api._closure_content(forged)
        owner=self.api._ClosureOwner(self.api._canonical_freeze(self.ref),self.api._canonical_freeze(forged),
            self.api._canonical_freeze(content),tuple(self.api._canonical_freeze(dict(kind='artifact',reference=r)) for r in forged['artifacts']),100)
        with self.api._context_database(self.context,write=True) as db:
            with self.assertRaises(state.StateError):self.api._artifact(None,content,context=self.context,owner=owner,db=db)
        with self.api._context_database(self.context,write=True) as db:
            with self.assertRaises(state.StateError):state._close_lifecycle(db,self.ref,forged,None)

    def test_source_change_during_marker_insertion_rolls_back_retirement(self):
        task=self.close()['task'];original=state._retired_record;changed=[]
        path=self.context.directory/'evidence'/task['retirement']['proof']['name']
        def mutate(kind,*args):
            result=original(kind,*args)
            if kind=='receipt' and not changed:
                path.chmod(0o600);path.write_bytes(path.read_bytes()+b' ');path.chmod(0o400);changed.append(True)
            return result
        with patch.object(state,'_retired_record',side_effect=mutate):
            with self.assertRaises(state.StateError):self.api._retire_closed_task(self.context,self.ref)
        self.assertTrue(changed)
        with self.api._context_database(self.context) as db:
            self.assertEqual(db.execute('select count(*) from tasks').fetchone()[0],1)
            self.assertEqual(db.execute('select count(*) from retired_identities').fetchone()[0],0)

    def test_unknown_scope_owned_guidance_dependency_is_protected(self):
        self.api._artifact(self.scope,dict(kind='d4-recovery-source',text='caller label cannot turn guidance into owner-issued recovery'),
            owner=self.api._guidance_artifact_owner(self.scope))
        with self.assertRaisesRegex(state.StateError,'Scope-owned consumer'):self.close()

    def test_unknown_unaccounted_artifact_blocks_new_closure(self):
        path=self.context.directory/'evidence'/'orphan.json';path.write_text('{}');path.chmod(0o400)
        with self.assertRaises(state.StateError):self.close()
        with state._database(self.scope) as db:
            self.assertIsNone(state._task(db,self.ref['scope_id'],'codex','session')['lifecycle']['safe_closed_at'])

    def test_late_generation_change_reprotects_closed_support(self):
        self.close();self.f.event(kind='PostToolUse',tool_call_id='late-external')
        with self.assertRaises(state.StateError):self.api._retire_closed_task(self.context,self.ref)
        with state._database(self.scope) as db:self.assertEqual(db.execute('select count(*) from tasks').fetchone()[0],1)

    def test_independent_live_consumer_raw_edge_blocks_closure(self):
        other=state.start_task(self.scope,self.f.request|dict(session_id='other',task_id='other'))['task']
        ref=self.api._artifact(self.scope,dict(kind='fixture:actual-live-consumer'),owner=self.api._artifact_owner(self.scope,other))
        with state._database(self.scope,write=True) as db:
            metadata=state._metadata(db,ref['name']);metadata['dependencies'].append(dict(kind='task',reference=self.ref))
            db.execute('update evidence_metadata set data=? where name=?',(json.dumps(metadata),ref['name']))
            other['evidence']=dict(version=1,plan=ref,candidate=ref,attempts=[])
            state._save(db,self.ref['scope_id'],other)
        with self.assertRaises(state.StateError):self.close()

    def test_generation_change_during_compact_registration_rejects_and_rolls_back(self):
        original=self.api._artifact_registered
        def mutate(scope,value,*args):
            ref=original(scope,value,*args)
            if value.get('kind')=='task-closure':args[-1].execute('update checkouts set generation=generation+1')
            return ref
        before=self.f.status()['generation']
        with patch.object(self.api,'_artifact_registered',side_effect=mutate):
            with self.assertRaises(state.StateError):self.close()
        with state._database(self.scope) as db:
            self.assertIsNone(state._task(db,self.ref['scope_id'],'codex','session')['lifecycle']['safe_closed_at'])
            self.assertEqual(db.execute('select generation from checkouts').fetchone()[0],before)

    def test_regressed_owner_clock_cannot_create_closure_age(self):
        with patch.object(state,'_owner_time',return_value=99):
            with self.assertRaises(state.StateError):self.close()
        with state._database(self.scope) as db:
            self.assertIsNone(state._task(db,self.ref['scope_id'],'codex','session')['lifecycle']['safe_closed_at'])

    def test_compact_registration_failure_leaves_no_closed_row_or_marker(self):
        original=self.api._artifact_registered
        def fail(scope,value,*args):
            ref=original(scope,value,*args)
            if value.get('kind')=='task-closure':raise state.StateError('fixture:after artifact registration')
            return ref
        with patch.object(self.api,'_artifact_registered',side_effect=fail):
            with self.assertRaises(state.StateError):self.close()
        with state._database(self.scope) as db:
            self.assertIsNone(state._task(db,self.ref['scope_id'],'codex','session')['lifecycle']['safe_closed_at'])
            self.assertEqual(db.execute('select count(*) from retired_identities').fetchone()[0],0)
        with self.assertRaises(state.StateError):self.close()


class LinkedVerificationTests(unittest.TestCase):
    """Synthetic trusted coordinator sources; actual disposable check receipts, no native qualification."""
    def setUp(self):
        from types import SimpleNamespace
        from tests.test_state import canonical_scope
        from tests.test_startup import CanonicalAcquisitionTests
        from runtime import evidence
        self.api = evidence
        self.members = []
        for number in range(2):
            f = EvidenceTests(methodName='runTest'); f.setUp(); self.addCleanup(f.doCleanups)
            f.scope = canonical_scope(f.scope)
            state.start_task(f.scope, f.identity | dict(mode='editable', decision_ref='user:accepted'))
            proxy = SimpleNamespace(repo=f.repo, base=f.root, assertIsNone=self.assertIsNone)
            record, path = CanonicalAcquisitionTests.record(proxy)
            identity = evidence._canonical_plain(f.scope.accepted_identity)
            record['project_id'] = identity['project_id']
            record['repositories'][0]['repository_id'] = identity['repository_id']
            record['repositories'][0]['checkouts'][0]['checkout_id'] = identity['checkout_id']
            config = record['repositories'][0]['checkouts'][0]['clients'][0]['configuration']
            config.update(identity['configuration'])
            path.write_text(json.dumps(record))
            self.members.append(f)
        self.selected = self.members[0]
        self.establish()

    def task(self, f):
        with state._database(f.scope) as db:
            return state._task(db, state._scope_id(f.scope), 'codex', 'parent')

    def reference(self, f):
        return self.api._canonical_plain(self.api._artifact_owner(f.scope, self.task(f)).task)

    def establish(self, delivery=None):
        review = dict(applicability='inapplicable', reason='Trivial fixed accepted unit command', independent=False)
        for index, f in enumerate(self.members):
            peers = [dict(task=self.reference(peer), delivery=delivery if peer is self.selected else None)
                     for peer in self.members if peer is not f]
            updates=dict(version=2, nontrivial=False, reviews=dict(general=review, security=review),
                linked=dict(acceptance=[dict(id='together', text='Accepted changes work together')],
                    delivery=delivery if f is self.selected else None, companions=peers))
            task=self.task(f)
            if 'evidence' in task:
                plan=self.api._read(f.scope,task['evidence']['plan']);plan.update(updates)
                self.api.plan_evidence(f.scope,f.request(plan=plan,change_decision_ref='fixture:approved-linked-revision'))
            else:
                f.plan(**updates)
            result = f.checked()
            self.assertEqual(result['attempt']['status'], 'passed')

    def retained(self, f, value):
        return dict(authority=self.reference(f)['authority'],
            reference=self.api._artifact(f.scope, value, owner=self.api._artifact_owner(f.scope, self.task(f))))

    def input_rows(self):
        rows=[]
        for f in self.members:
            task=self.task(f); plan=self.api._read(f.scope,task['evidence']['plan'])
            rows.append(dict(task=self.reference(f),pins=task['pins'],plan_digest=self.api._digest(plan),
                candidate_digest=self.api._digest(self.api.capture_candidate(f.scope,plan))))
        return sorted(rows,key=lambda row:self.api._raw(row['task']))

    def observations(self, *, delivery=None, delivery_status='unknown', shared_status='passed'):
        inputs=self.input_rows(); digest=self.api._digest(inputs)
        plan=self.api._read(self.selected.scope,self.task(self.selected)['evidence']['plan'])
        projection=self.api._linked_projection(self.reference(self.selected),plan)
        decision=self.retained(self.selected,dict(version=1,kind='linked-scope-decision',
            projection_digest=self.api._digest(projection),decision_ref='user:accepted',
            reference='fixture:independently checked complete user scope',observed_at=100))
        integration=self.retained(self.selected,dict(version=1,kind='linked-integration-observation',
            inputs_digest=digest,criteria=dict(together=shared_status),observed_at=101,
            reference='fixture:synthetic independently observed integration for exact versions'))
        deliveries=[]
        if delivery is not None:
            candidate=self.api.capture_candidate(self.selected.scope,plan)
            source=self.retained(self.selected,dict(version=1,kind='linked-delivery-observation',
                delivery=delivery,status=delivery_status,revision=candidate['head'],observed_at=102,
                reference='fixture:synthetic coordinator-verified provider observation'))
            deliveries=[dict(delivery=delivery,status=delivery_status,source=source,
                observed_at=102,revision=candidate['head'])]
        def observe(facts):
            self.assertEqual(facts['inputs_digest'],digest)
            return dict(scope_decision=decision,shared=[dict(id='together',status=shared_status,
                evidence=[integration],reference='fixture:semantic acceptance independently checked')],deliveries=deliveries)
        return dict(members=[dict(scope=f.scope,request=f.request(purpose='completion')) for f in self.members],observe=observe)

    def verify(self, observations=None):
        return self.api.verify_linked(self.selected.scope,self.selected.request(purpose='completion'),
            observations or self.observations())

    def test_multi_member_current_proof_sets_only_selected_implementation_ready(self):
        peer_before=self.task(self.members[1])
        result=self.verify()
        self.assertTrue(result['implementation_verified'])
        self.assertTrue(result['delivery_complete'])
        self.assertEqual(result['task']['state'],'ready')
        self.assertIn('linked_verification',result['task']['evidence'])
        peer_after=self.task(self.members[1])
        self.assertNotIn('linked_verification',peer_after['evidence'])
        self.assertNotEqual(peer_after['state'],'ready')
        self.assertEqual(peer_before['pins'],peer_after['pins'])
        self.assertEqual(state.task_status(self.selected.scope,'codex','parent')['task']['state'],'ready')

    def test_open_delivery_does_not_block_current_implementation(self):
        delivery=dict(provider='fixture',repository='owner/repo',target='main',pull_request='fixture:pull1')
        self.establish(delivery)
        result=self.verify(self.observations(delivery=delivery,delivery_status='open'))
        self.assertTrue(result['implementation_verified'])
        self.assertFalse(result['delivery_complete'])
        self.assertFalse(result['merge_authority'])
        self.assertEqual(result['task']['state'],'ready')

    def test_raw_passing_flags_cannot_supply_trusted_acquisition(self):
        observations=self.observations();observations['observe']=dict(complete=True,passed=True)
        with self.assertRaises(state.StateError):self.verify(observations)

    def test_missing_member_and_divergent_plan_reject(self):
        observations=self.observations();observations['members'].pop()
        with self.assertRaises(state.StateError):self.verify(observations)
        peer=self.members[1]
        plan=self.api._read(peer.scope,self.task(peer)['evidence']['plan'])
        plan['linked']['acceptance'][0]['text']='A different shared agreement'
        self.api.plan_evidence(peer.scope,peer.request(plan=plan,change_decision_ref='fixture:changed'))
        with self.assertRaises(state.StateError):self.verify()

    def test_peer_change_invalidates_selected_ready_without_mutating_peer(self):
        self.verify()
        peer=self.members[1];before=self.task(peer)
        (peer.repo/'app.py').write_text('value = 2\n')
        result=state.task_status(self.selected.scope,'codex','parent')
        self.assertEqual(result['task']['state'],'verifying')
        self.assertEqual(self.task(peer),before)


    def test_foreign_retained_source_is_guarded_before_consumption(self):
        from tests.test_state import canonical_scope
        from runtime import delegation
        extra=EvidenceTests(methodName='runTest');extra.setUp();self.addCleanup(extra.doCleanups)
        extra.scope=canonical_scope(extra.scope)
        state.start_task(extra.scope,extra.identity | dict(mode='editable',decision_ref='user:accepted'))
        observations=self.observations();original_observe=observations['observe']
        source=self.retained(extra,dict(version=1,kind='linked-integration-observation',
            inputs_digest=self.api._digest(self.input_rows()),criteria=dict(together='passed'),observed_at=101,
            reference='fixture:existing independent source authority'))
        def observe(facts):
            acquired=original_observe(facts);acquired['shared'][0]['evidence']=[source];return acquired
        observations['observe']=observe
        original=self.api._linked_source
        def read(reference,**kwargs):
            if reference==source:
                with self.assertRaises(state.StateError):
                    with delegation._reservation_write(extra.scope):pass
            return original(reference,**kwargs)
        with patch.object(self.api,'_linked_source',side_effect=read):result=self.verify(observations)
        self.assertTrue(result['implementation_verified'])

    def test_callback_result_is_snapshotted_before_retained_source_reads(self):
        observations=self.observations();observe=observations['observe'];held=[]
        def acquire(facts):
            result=observe(facts);held.append(result);return result
        observations['observe']=acquire;original=self.api._linked_source
        def read(reference,**kwargs):
            if held:held[0]['shared'][0]['status']='failed'
            return original(reference,**kwargs)
        with patch.object(self.api,'_linked_source',side_effect=read):result=self.verify(observations)
        self.assertTrue(result['implementation_verified'])

    def test_peer_generation_change_during_publication_rejects_without_aggregate(self):
        from runtime.engine import RuntimeEvent
        observations=self.observations();original=self.api._artifact;changed=[];peer=self.members[1]
        def publish(scope,value,**kwargs):
            if value.get('kind')=='linked-verification' and not changed:
                changed.append(True)
                event=RuntimeEvent('PostToolUse','codex','parent',peer.repo,'fixture-turn','fixture-call','apply_patch',False,'fixture')
                state.process_event(peer.scope,event)
            return original(scope,value,**kwargs)
        with patch.object(self.api,'_artifact',side_effect=publish):
            with self.assertRaises(state.StateError):self.verify(observations)
        self.assertTrue(changed)
        self.assertNotIn('linked_verification',self.task(self.selected)['evidence'])

    def test_unknown_integration_source_cannot_pass_shared_criterion(self):
        observations=self.observations();observe=observations['observe']
        unknown=self.retained(self.selected,dict(version=1,kind='caller-passed-flags',passed=True))
        def acquire(facts):
            result=observe(facts);result['shared'][0]['evidence']=[unknown];return result
        observations['observe']=acquire
        result=self.verify(observations)
        self.assertFalse(result['implementation_verified'])
        self.assertEqual(result['task']['state'],'verifying')

    def test_merged_and_unknown_delivery_keep_independent_phase_results(self):
        delivery=dict(provider='fixture',repository='owner/repo',target='main',pull_request='fixture:pull1')
        self.establish(delivery)
        result=self.verify(self.observations(delivery=delivery,delivery_status='merged'))
        self.assertTrue(result['implementation_verified']);self.assertTrue(result['delivery_complete'])
        status=self.api.evidence_status(self.selected.scope,'codex','parent')['evidence']
        self.assertTrue(status['implementation_verified']);self.assertTrue(status['delivery_complete'])

    def test_failed_actual_member_check_blocks_implementation(self):
        peer=self.members[1];plan=self.api._read(peer.scope,self.task(peer)['evidence']['plan'])
        plan['checks'][0]['argv']=[sys.executable,'-c','raise SystemExit(1)']
        self.api.plan_evidence(peer.scope,peer.request(plan=plan,change_decision_ref='fixture:accepted-failing-command'))
        self.assertEqual(peer.checked()['attempt']['status'],'failed')
        result=self.verify()
        self.assertFalse(result['implementation_verified'])
        self.assertEqual(result['task']['state'],'verifying')


    def test_peer_generation_race_during_ready_publication_downgrades_claimant(self):
        from contextlib import contextmanager
        from runtime.engine import RuntimeEvent
        self.verify();original=state._database;peer=self.members[1];changed=[]
        @contextmanager
        def database(scope,write=False,initialize=False):
            if scope is self.selected.scope and write and not changed:
                changed.append(True)
                state.process_event(peer.scope,RuntimeEvent('PostToolUse','codex','parent',peer.repo,
                    'status-race-turn','status-race-call','apply_patch',False,'status-race'))
            with original(scope,write=write,initialize=initialize) as db:yield db
        with patch.object(state,'_database',side_effect=database):
            result=state.task_status(self.selected.scope,'codex','parent')
        self.assertTrue(changed)
        self.assertEqual(result['task']['state'],'verifying')

    def test_same_authority_independent_members_need_no_nested_writer(self):
        from tests.test_state import canonical_scope
        from tests.test_startup import CanonicalAcquisitionTests
        from types import SimpleNamespace
        members=[]
        for index in range(2):
            f=EvidenceTests(methodName='runTest');f.setUp();self.addCleanup(f.doCleanups)
            f.scope=canonical_scope(f.scope,repository_id='repo'+str(index),checkout_id='checkout'+str(index))
            if members:
                identity=self.api._canonical_plain(f.scope.accepted_identity)
                runtime=members[0].scope.runtime
                identity['configuration']['runtime']['state_dir']=str(runtime.state_dir)
                f.scope=replace(f.scope,runtime=runtime,accepted_identity=self.api._canonical_freeze(identity),
                    accepted_scope_digest=self.api._digest(identity))
            state.start_task(f.scope,f.identity | dict(mode='editable',decision_ref='user:accepted'))
            record,path=CanonicalAcquisitionTests.record(SimpleNamespace(repo=f.repo,base=f.root,assertIsNone=self.assertIsNone))
            identity=self.api._canonical_plain(f.scope.accepted_identity)
            record['project_id']=identity['project_id']
            record['repositories'][0]['repository_id']=identity['repository_id']
            record['repositories'][0]['checkouts'][0]['checkout_id']=identity['checkout_id']
            record['repositories'][0]['checkouts'][0]['clients'][0]['configuration'].update(identity['configuration'])
            path.write_text(json.dumps(record));members.append(f)
        self.members=members;self.selected=members[0];self.establish()
        self.assertEqual(members[0].scope.runtime.state_dir,members[1].scope.runtime.state_dir)
        self.assertTrue(self.verify()['implementation_verified'])
        self.assertEqual(state.task_status(self.selected.scope,'codex','parent')['task']['state'],'ready')


    def test_missing_selected_local_proof_downgrades_without_passing_history(self):
        self.verify();task=self.task(self.selected)
        reference=task['evidence']['verification']
        (self.selected.scope.runtime.state_dir/'evidence'/reference['name']).unlink()
        result=state.task_status(self.selected.scope,'codex','parent')
        self.assertEqual(result['task']['state'],'verifying')

    def test_missing_delivery_source_changes_only_delivery_phase(self):
        delivery=dict(provider='fixture',repository='owner/repo',target='main',pull_request='fixture:pull1')
        self.establish(delivery)
        observations=self.observations(delivery=delivery,delivery_status='merged')
        held=[];original=observations['observe']
        def observe(facts):
            result=original(facts);held.append(result['deliveries'][0]['source']);return result
        observations['observe']=observe
        self.assertTrue(self.verify(observations)['delivery_complete'])
        source=held[0]
        (Path(source['authority']['directory'])/'evidence'/source['reference']['name']).unlink()
        result=self.api.evidence_status(self.selected.scope,'codex','parent')
        self.assertEqual(result['task']['state'],'ready')
        self.assertTrue(result['evidence']['implementation_verified'])
        self.assertFalse(result['evidence']['delivery_complete'])

    def test_unpublished_relevant_change_cannot_be_delivered_by_an_old_merged_revision(self):
        delivery=dict(provider='fixture',repository='owner/repo',target='main',pull_request='fixture:pull1')
        (self.selected.repo/'app.py').write_text('value = 2\n')
        self.establish(delivery)
        result=self.verify(self.observations(delivery=delivery,delivery_status='merged'))
        self.assertTrue(result['implementation_verified'])
        self.assertFalse(result['delivery_complete'])


    def test_actual_qualified_review_chains_revalidate_through_foreign_contexts(self):
        review=dict(applicability='required',reason='Independent fixture review',independent=True)
        for f in self.members:
            plan=self.api._read(f.scope,self.task(f)['evidence']['plan'])
            plan.update(nontrivial=True,reviews=dict(general=review,security=review))
            self.api.plan_evidence(f.scope,f.request(plan=plan,change_decision_ref='fixture:required-qualified-review'))
            self.assertEqual(f.checked()['attempt']['status'],'passed')
            f.review()
        result=self.verify()
        self.assertTrue(result['implementation_verified'])
        self.assertEqual(state.task_status(self.selected.scope,'codex','parent')['task']['state'],'ready')


    def test_complete_scope_source_cannot_hide_an_omitted_third_member(self):
        observations=self.observations();observe=observations['observe']
        plan=self.api._read(self.selected.scope,self.task(self.selected)['evidence']['plan'])
        projection=self.api._linked_projection(self.reference(self.selected),plan)
        omitted=dict(self.reference(self.selected),task_id='approved-third-task')
        projection['participants'].append(dict(task=omitted,delivery=None))
        decision=self.retained(self.selected,dict(version=1,kind='linked-scope-decision',
            projection_digest=self.api._digest(projection),decision_ref='user:accepted',observed_at=100,
            reference='fixture:independent complete scope includes the omitted third task'))
        def acquire(facts):
            result=observe(facts);result['scope_decision']=decision;return result
        observations['observe']=acquire
        with self.assertRaises(state.StateError):self.verify(observations)
        self.assertNotIn('linked_verification',self.task(self.selected)['evidence'])

    def test_confirmed_foreign_security_finding_blocks_aggregate_implementation(self):
        peer=self.members[1]
        plan=self.api._read(peer.scope,self.task(peer)['evidence']['plan'])
        review=dict(applicability='required',reason='Independent security fixture review',independent=True)
        plan.update(nontrivial=True,reviews=dict(general=review,security=review))
        self.api.plan_evidence(peer.scope,peer.request(plan=plan,change_decision_ref='fixture:security-required'))
        self.assertEqual(peer.checked()['attempt']['status'],'passed')
        peer.review(findings=[dict(id='linked-security',severity='high',scope='security',status='confirmed',
            location='app.py:1',scenario='Reachable unsafe fixture path',evidence='Independent tracing',
            counterevidence='No applicable guard')])
        result=self.verify()
        self.assertFalse(result['implementation_verified'])
        self.assertTrue(any('security finding' in message for message in result['blockers']))


    def test_legacy_evidence_cannot_adopt_a_canonical_aggregate_pointer(self):
        legacy=EvidenceTests(methodName='runTest');legacy.setUp();self.addCleanup(legacy.doCleanups)
        legacy.plan()
        with state._database(legacy.scope,write=True) as db:
            task=state._task(db,state._scope_id(legacy.scope),'codex','parent')
            task['evidence']['linked_verification']=dict(authority=self.reference(self.selected)['authority'],
                reference=task['evidence']['plan'])
            with self.assertRaises(state.StateError):state._save(db,state._scope_id(legacy.scope),task)


    def assert_final_source_loss_rejected(self, *, merge_evidence=False):
        if merge_evidence:
            for f in self.members:
                f.review()
        observations=self.observations();observe=observations['observe'];held=[]
        def acquire(facts):
            result=observe(facts);held.append(result['shared'][0]['evidence'][0]);return result
        observations['observe']=acquire
        if merge_evidence:
            for row in observations['members']:row['request']['purpose']='merge-evidence'
            result=self.api.verify_linked(self.selected.scope,self.selected.request(purpose='merge-evidence'),observations)
        else:
            result=self.verify(observations)
        self.assertTrue(result['implementation_verified'])
        before=self.task(self.selected)
        if merge_evidence:self.assertNotEqual(before['state'],'ready')
        original=self.api._linked_outcomes;changed=[]
        def consume(*args,**kwargs):
            result=original(*args,**kwargs)
            if not changed:
                source=held[0]
                (Path(source['authority']['directory'])/'evidence'/source['reference']['name']).unlink()
                changed.append(True)
            return result
        with patch.object(self.api,'_linked_outcomes',side_effect=consume):
            if merge_evidence:
                result=self.api.evidence_status(self.selected.scope,'codex','parent')['evidence']
            else:
                result=self.api._revalidate_linked(self.selected.scope,before,update_ready=False)
        self.assertTrue(changed)
        self.assertFalse(result['implementation_verified'])
        self.assertEqual(self.task(self.selected),before)

    def test_read_only_revalidation_rechecks_sources_after_consumption(self):
        self.assert_final_source_loss_rejected()

    def test_non_ready_merge_evidence_status_rechecks_sources_after_consumption(self):
        self.assert_final_source_loss_rejected(merge_evidence=True)

    def test_implementation_source_bytes_change_during_registration_rejects(self):
        observations=self.observations();observe=observations['observe'];held=[]
        def acquire(facts):
            result=observe(facts);held.append(result['shared'][0]['evidence'][0]);return result
        observations['observe']=acquire;original=self.api._artifact;changed=[]
        def publish(scope,value,**kwargs):
            result=original(scope,value,**kwargs)
            if value.get('kind')=='linked-verification' and not changed:
                source=held[0];path=Path(source['authority']['directory'])/'evidence'/source['reference']['name']
                path.chmod(0o600);path.write_text('{"tampered":true}');path.chmod(0o400);changed.append(True)
            return result
        with patch.object(self.api,'_artifact',side_effect=publish):
            with self.assertRaises(state.StateError):self.verify(observations)
        self.assertTrue(changed);self.assertNotIn('linked_verification',self.task(self.selected)['evidence'])

    def test_scope_source_metadata_change_during_registration_rejects(self):
        observations=self.observations();observe=observations['observe'];held=[]
        def acquire(facts):
            result=observe(facts);held.append(result['scope_decision']);return result
        observations['observe']=acquire;original=self.api._artifact;changed=[]
        def publish(scope,value,**kwargs):
            result=original(scope,value,**kwargs)
            if value.get('kind')=='linked-verification' and not changed:
                source=held[0];db=kwargs['db'];metadata=state._metadata(db,source['reference']['name'])
                metadata['created_at']+=1
                db.execute('update evidence_metadata set created_at=?,data=? where name=?',
                    (metadata['created_at'],self.api._raw(metadata).decode(),source['reference']['name']))
                changed.append(True)
            return result
        with patch.object(self.api,'_artifact',side_effect=publish):
            with self.assertRaises(state.StateError):self.verify(observations)
        self.assertTrue(changed);self.assertNotIn('linked_verification',self.task(self.selected)['evidence'])

    def test_delivery_source_change_during_registration_is_only_delivery_unknown(self):
        delivery=dict(provider='fixture',repository='owner/repo',target='main',pull_request='fixture:pull1')
        self.establish(delivery)
        observations=self.observations(delivery=delivery,delivery_status='merged');observe=observations['observe'];held=[]
        def acquire(facts):
            result=observe(facts);held.append(result['deliveries'][0]['source']);return result
        observations['observe']=acquire;original=self.api._artifact;changed=[]
        def publish(scope,value,**kwargs):
            result=original(scope,value,**kwargs)
            if value.get('kind')=='linked-verification' and not changed:
                source=held[0];path=Path(source['authority']['directory'])/'evidence'/source['reference']['name']
                path.chmod(0o600);path.write_text('{"tampered":true}');path.chmod(0o400);changed.append(True)
            return result
        with patch.object(self.api,'_artifact',side_effect=publish):result=self.verify(observations)
        self.assertTrue(changed);self.assertTrue(result['implementation_verified'])
        self.assertFalse(result['delivery_complete']);self.assertEqual(result['task']['state'],'ready')
        content=self.api._linked_source(result['verification'])
        self.assertFalse(content['delivery_complete'])
        self.assertEqual(content['deliveries'][0]['status'],'unknown')


    def test_d4_typed_closure_walk_preserves_foreign_aggregate_proof(self):
        from runtime import changes
        result=self.verify();pointer=result['verification']
        contexts=tuple(self.api._evidence_context(f.scope) for f in self.members)
        # Supply a known owner artifact root; actual typed traversal/physical readers are unmocked.
        def roots(manifest,context,task_refs):
            return [],[],[pointer['reference']] if context.directory==self.selected.scope.runtime.state_dir else []
        with changes._authority_guards([context.directory for context in contexts]), \
             patch.object(changes,'_recovery_owner_refs',side_effect=roots):
            _,_,artifacts,foreign=changes._collect_recovery_references({'owners':[]},contexts)
        peer=self.members[1];proof=self.task(peer)['evidence']['verification']
        self.assertIn(dict(authority=self.reference(peer)['authority'],artifact=proof),artifacts)
        self.assertEqual(foreign,[])
