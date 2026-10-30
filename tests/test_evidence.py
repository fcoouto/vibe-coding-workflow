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
from runtime.startup import ProjectScope, RuntimeSettings, StartupError, policy_digest


def _run_d4_fixture(fixture, request, operation):
    """Issue fresh internal test-host authority; this does not qualify a native provider."""
    changes = fixture.changes
    class Host:
        def acquire_d4_bookkeeping(self, facts, issue):return issue(facts)
    with changes._bootstrap_d4_host(Host(), issuer=changes._D4_HOST_BOOTSTRAP_ISSUER) as host:
        return changes._run_scoped(fixture.directory, request, operation, host=host)


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


class D4RecoveryFixture:
    def enroll_recovery(self, *, shared=False):
        from tests.test_changes import ScopedChangesTests
        from runtime import changes, onboarding
        from runtime.startup import AcceptedScope, canonical_scope_projection, decode_project_record, _canonical_freeze, _canonical_plain
        storage = self.fixture.root / 'recovery-authority'
        self.recovery_fixtures = []

        def fixture():
            d4 = ScopedChangesTests(methodName='runTest');d4.setUp();self.addCleanup(d4.doCleanups)
            return d4

        def apply(d4, request):
            for repository in request['manifest']['enrollment']['record']['repositories']:
                for checkout in repository['checkouts']:
                    checkout['clients'][0]['configuration']['runtime'] = dict(schema_version=3, state_dir=str(storage))
            request['approval']['manifest_digest'] = onboarding._digest(request['manifest'])
            self.assertFalse((storage / 'runtime.sqlite3').exists())
            result = _run_d4_fixture(d4, request, 'apply')
            self.assertEqual(result['exit_code'], 0, result)
            return request

        dependency = None
        if shared:
            other = fixture()
            other_request = apply(other, other.scoped_request())
            dependency = other.repo / 'AGENTS.md'

        d4 = fixture();d4.repo = self.fixture.repo
        pointer = '@' + str(dependency) + '\n' if dependency else ''
        (d4.repo / 'AGENTS.md').write_text('product rules\nlegacy process\n' + pointer)
        d4.scoped_inspect()
        proposal = d4.scoped_proposal()
        action = proposal['assessments']['repositories'][0]['actions'][0]
        action['text'] += pointer
        action['after'] = hashlib.sha256(action['text'].encode()).hexdigest()
        onboarding.record_plan(d4.directory, proposal)
        request = d4.scoped_request(prepared=True)
        record = request['manifest']['enrollment']['record']
        if dependency:
            record['shared_policy'] = [dict(path=str(dependency), sha256=hashlib.sha256(dependency.read_bytes()).hexdigest())]
            record['repositories'][0]['checkouts'][0]['clients'][0]['configuration']['shared_dependencies'] = [str(dependency)]
        apply(d4, request)
        authority = d4.repo / '.vibe-coding-workflow/project.json'
        published = json.loads(authority.read_text())
        self.assertEqual(published, record)
        repository = published['repositories'][0];checkout = repository['checkouts'][0]
        identity = canonical_scope_projection(decode_project_record(published),
            repository_id=repository['repository_id'], checkout_id=checkout['checkout_id'], client='codex')
        self.recovery_fixtures.append((d4, request))
        if shared:
            self.assertNotEqual(published['project_id'], other_request['manifest']['enrollment']['record']['project_id'])
            self.recovery_fixtures.append((other, other_request))
        self.recovery_index = 0
        # Internal scope from actual configured publication; no native activation is claimed.
        scope = AcceptedScope(published['project_id'], repository['repository_id'], checkout['checkout_id'],
            Path(published['project_root']), authority, _canonical_freeze(changes._scoped_target(d4.repo, str(authority.relative_to(d4.repo)))),
            published['revision'], d4.repo, Path(repository['primary_root']), Path(checkout['git_dir']),
            Path(repository['git_common_dir']), _canonical_freeze(repository['binding'] | checkout['binding']), 'codex',
            identity['configuration']['policy_digest'], identity['configuration']['runtime_digest'], RuntimeSettings(3, storage),
            identity, onboarding._digest(_canonical_plain(identity)),
            _canonical_freeze(dict(kind='trusted-coordinator', **request['approval']['evidence'][0])))
        with state._database(scope,write=True,initialize=True) as db:
            state._checkout_row(db,scope,initialize=True)
        return scope

    def recovery(self,task):
        from runtime import changes
        api=self.fixture.api;context=api._evidence_context(self.scope)
        ref=api._canonical_plain(api._artifact_owner(self.scope,task).task)
        d4,request=self.recovery_fixtures[self.recovery_index];self.recovery_index+=1
        candidate=api.capture_candidate(self.scope,api._load_plan(self.scope,self.fixture.identity))
        result=_run_d4_fixture(d4,request,'resume');self.assertEqual(result['exit_code'],0,result)
        self.assertEqual(api.capture_candidate(self.scope,api._load_plan(self.scope,self.fixture.identity)),candidate)
        old,source=self.recovery_head(d4,context)
        self.assertTrue(any(item['reference']==ref for item in source['tasks']))
        with self.assertRaises(StartupError):api._observe_closure((context,),ref)
        return d4,request,context,ref,source,old

    def recovery_head(self,d4,context):
        from runtime import changes
        _,heads=changes._recovery_sources(context)
        selected=[(pointer,content) for pointer,content in heads if content['identity']['plan_dir']==str(d4.directory)]
        self.assertEqual(len(selected),1)
        return selected[0]


class CanonicalEvidenceTests(D4RecoveryFixture, unittest.TestCase):
    def setUp(self, *, d4_recovery=False, shared=False):
        from tests.test_state import canonical_scope
        self.fixture = EvidenceTests(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.scope = self.enroll_recovery(shared=shared) if d4_recovery else canonical_scope(self.fixture.scope)
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


class AssignedCancelledClosureTests(unittest.TestCase):
    """Real local check/reconciliation artifacts; synthetic coordinator stop authority."""
    setUp = CanonicalEvidenceTests.setUp

    def stopped(self):
        api=self.fixture.api
        result=self.fixture.checked()
        task=state.task_status(self.scope,'codex','parent')['task']
        proof=dict(version=1,kind='stopped-writer-reconciliation',identity=self.fixture.identity,
            expected_revision=task['revision'],expected_pins=task['pins'],observed_turn_id=task['turn_id'],
            stopped=True,descendants_stopped=True,attempt_ids=[],observation_ref='fixture:checked-stop',coordinator_ref='fixture:independent')
        raw=json.dumps(proof).encode();path=self.fixture.root/'cancel-proof.json';path.write_bytes(raw);path.chmod(0o400)
        task=state.retire_task(self.scope,self.fixture.request(expected_pins=task['pins'],reason='Cancelled after independent stop',
            reference='fixture:cancel',stop_proof=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest())))['task']
        context=api._evidence_context(self.scope)
        ref=api._canonical_plain(api._artifact_owner(self.scope,task).task)
        return task,context,ref,result['attempt']

    def close(self,task,context,ref):
        api=self.fixture.api
        return api.close_task(self.scope,self.fixture.request(expected_pins=task['pins']),api._observe_closure((context,),ref))['task']

    def test_actual_check_values_and_original_ages_survive_atomic_assignment_retirement(self):
        api=self.fixture.api;task,context,ref,attempt=self.stopped()
        closed=self.close(task,context,ref);compact=api._read(self.scope,closed['lifecycle']['compact'])
        self.assertEqual(compact['outcome'],'cancelled');self.assertEqual(compact['usage'],'unknown')
        self.assertEqual(len(compact['stopped']['assignments']),1)
        numbers={item['field']:item for item in compact['numerical']}
        for field,unit in (('exit_code','exit-code'),('output_bytes','bytes')):
            self.assertEqual(numbers[field]['value'],attempt[field]);self.assertEqual(numbers[field]['unit'],unit)
            self.assertEqual(numbers[field]['source'],attempt['execution'])
        with api._context_database(context) as db:
            age=state._metadata(db,attempt['execution']['name'])['created_at']
        self.assertEqual(numbers['output_bytes']['created_at'],age)
        api._retire_closed_task(context,ref)
        with api._context_database(context) as db:
            self.assertEqual(db.execute('select count(*) from assignments').fetchone()[0],0)
            self.assertEqual(db.execute('select count(*) from tasks').fetchone()[0],0)
            marker=state._retired_assignment(db,attempt['id'])
            certificate=compact['stopped']['assignments'][0]
            self.assertEqual(marker['created_at'],certificate['created_at'])
            self.assertEqual(marker['request_digest'],certificate['request_digest'])
            self.assertEqual(marker['outcome'],'completed')
        with self.assertRaises(state.StateError):
            api.run_check(self.scope,self.fixture.identity|dict(expected_revision=task['revision'],check_id='unit'))

    def test_failure_after_assignment_markers_rolls_back_assignments_and_task(self):
        api=self.fixture.api;task,context,ref,attempt=self.stopped();self.close(task,context,ref)
        original=state._retired_record
        def fail(kind,*args):
            if kind=='task':raise state.StateError('fixture:after assignment marker')
            return original(kind,*args)
        with patch.object(state,'_retired_record',side_effect=fail):
            with self.assertRaises(state.StateError):api._retire_closed_task(context,ref)
        with api._context_database(context) as db:
            self.assertEqual(db.execute('select count(*) from assignments').fetchone()[0],1)
            self.assertEqual(db.execute('select count(*) from tasks').fetchone()[0],1)
            self.assertEqual(db.execute('select count(*) from retired_identities').fetchone()[0],0)

    def test_execution_change_after_assignment_removal_rolls_back_all_local_rows(self):
        api=self.fixture.api;task,context,ref,attempt=self.stopped();self.close(task,context,ref)
        path=context.directory/'evidence'/attempt['execution']['name'];original=state._retired_record
        changed=[]
        def mutate(kind,*args):
            result=original(kind,*args)
            if kind=='task' and not changed:
                path.chmod(0o600);path.write_bytes(path.read_bytes()+b' ');path.chmod(0o400);changed.append(True)
            return result
        with patch.object(state,'_retired_record',side_effect=mutate):
            with self.assertRaises(state.StateError):api._retire_closed_task(context,ref)
        self.assertTrue(changed)
        with api._context_database(context) as db:
            self.assertEqual(db.execute('select count(*) from assignments').fetchone()[0],1)
            self.assertEqual(db.execute('select count(*) from tasks').fetchone()[0],1)
            self.assertEqual(db.execute('select count(*) from retired_identities').fetchone()[0],0)

    def test_complete_certificate_set_and_original_assignment_pointer_are_required(self):
        from runtime import changes,delegation
        api=self.fixture.api;task,context,ref,_=self.stopped()
        with api._context_database(context) as db:
            certificate=changes._stopped_certificate(context,db,dict(reference=ref,pins=task['pins']))
            self.assertEqual(len(certificate['assignments']),1)
            incomplete=api._canonical_plain(certificate);incomplete['assignments']=[]
            with self.assertRaises(state.StateError):delegation._closure_assignments(context,db,ref,task,incomplete)
            wrong=api._canonical_plain(certificate)
            wrong['assignments'][0]['reference']['assignment']=task['evidence']['candidate']
            with self.assertRaises(state.StateError):delegation._closure_assignments(context,db,ref,task,wrong)

    def test_merely_settled_assignment_without_exact_reconciliation_cannot_close(self):
        api=self.fixture.api;task,context,ref,attempt=self.stopped()
        with api._context_database(context,write=True) as db:
            row=db.execute('select data from assignments where id=?',(attempt['id'],)).fetchone()
            data=json.loads(row[0]);data['reconciliation']=task['retirement']['proof']
            db.execute('update assignments set data=? where id=?',(json.dumps(data),attempt['id']))
        with self.assertRaises(StartupError):self.close(task,context,ref)

    def test_missing_or_substituted_numerical_source_cannot_close(self):
        api=self.fixture.api;task,context,ref,attempt=self.stopped()
        with api._context_database(context,write=True) as db:
            changed=state._task(db,ref['scope_id'],'codex','parent','task')
            changed['evidence']['attempts'][0]['output_bytes']+=1
            db.execute('update tasks set data=?',(json.dumps(changed),))
        with self.assertRaises(state.StateError):self.close(task,context,ref)

    def test_independent_live_body_consumer_prevents_assignment_retirement(self):
        api=self.fixture.api;task,context,ref,_=self.stopped()
        other=state.start_task(self.scope,self.fixture.identity|dict(session_id='other',task_id='other',mode='editable',decision_ref='user:accepted'))['task']
        source=api._artifact(self.scope,dict(kind='fixture:required-body'),owner=api._artifact_owner(self.scope,other))
        with api._context_database(context,write=True) as db:
            metadata=state._metadata(db,source['name']);metadata['dependencies'].append(dict(kind='task',reference=ref))
            db.execute('update evidence_metadata set data=? where name=?',(json.dumps(metadata),source['name']))
            other['evidence']=dict(version=1,plan=source,candidate=source,attempts=[])
            state._save(db,ref['scope_id'],other)
        with self.assertRaises(state.StateError):self.close(task,context,ref)

    def test_review_findings_and_original_dispositions_survive_cancelled_closure(self):
        finding=dict(id='review-1',severity='medium',scope='general',status='confirmed',location='app.py:1 working',
            scenario='Actual reviewed fixture path',evidence='Code tracing',counterevidence='None',correction='Bounded correction')
        reviewed=self.fixture.review(findings=[finding]);review_id=reviewed['attempt_id']
        task,context,ref,_=self.stopped();closed=self.close(task,context,ref)
        compact=self.fixture.api._read(self.scope,closed['lifecycle']['compact'])
        review=next(item for item in compact['reviews'] if item['assignment_id']==review_id)
        self.assertEqual(review['report']['findings'],[finding])
        self.assertEqual(review['assessments'][0]['assessment']['dispositions'],[])
        self.assertEqual(review['report']['limitations'],[])

    def test_actual_d4_assigned_source_cut_composes_owner_retirement_and_exact_pointer(self):
        from tests.test_changes import ScopedChangesTests
        f=ScopedChangesTests(methodName='runTest');f.setUp();self.addCleanup(f.doCleanups)
        request,context,ref,identity,_=f.recovery_release_fixture(assignment=True)
        api=self.fixture.api
        with self.assertRaises(StartupError):api._observe_closure((context,),ref)
        released=f.changes._register_recovery_release(f.changes._observe_recovery_release(context.authority_set,identity))
        self.assertTrue(released['complete'])
        with api._context_database(context) as db:
            task=state._task(db,ref['scope_id'],ref['client'],ref['session_id'],ref['task_id'])
        selected={key:task[key] for key in ('client','session_id','task_id','scope_ref')}
        closed=api.close_task(f.release_fixture_scope,selected|dict(expected_revision=task['revision'],expected_pins=task['pins']),
            api._observe_closure((context,),ref))['task']
        compact=api._read(None,closed['lifecycle']['compact'],context=context)
        assignment=compact['stopped']['assignments'][0]
        api._retire_closed_task(context,ref)
        with api._context_database(context) as db:
            self.assertEqual(db.execute('select count(*) from assignments').fetchone()[0],0)
            self.assertEqual(db.execute('select count(*) from tasks').fetchone()[0],0)
            f.changes._check_stopped_certificate(context,db,compact['stopped'])
        changed=json.loads(json.dumps(assignment['reference']));changed['assignment']=task['retirement']['proof']
        with self.assertRaisesRegex(StartupError,'issued pointer'):f.changes._stopped_assignment_certificate(compact['stopped'],changed)
        self.assertTrue(f.changes.inspect_lifecycle_recovery(context.authority_set,(ref,))['complete'])
        for operation in ('resume','rollback'):
            self.assertEqual(_run_d4_fixture(f,request,operation)['exit_code'],0)


class ReadyClosureTests(D4RecoveryFixture, unittest.TestCase):
    """Real ready verification and owner stop; fixture host authority is unqualified."""
    def setUp(self):
        CanonicalEvidenceTests.setUp(self, d4_recovery=
            self._testMethodName == 'test_actual_ready_d4_cut_precedes_closure_and_retired_raw_removal')

    def ready(self):
        from runtime.engine import RuntimeEvent
        f=self.fixture
        for kind in ('PreToolUse','PostToolUse'):
            state.process_event(self.scope,RuntimeEvent(kind,'codex','parent',f.repo,turn_id='turn',tool_call_id='fixture-read',
                tool_name='read_file',receipt_fingerprint='a'*64))
        f.checked();f.review()
        result=f.verify();self.assertEqual(result['task']['state'],'ready',result)
        return result['task']

    def stop_request(self,task,**proof_updates):
        api=self.fixture.api;context=api._evidence_context(self.scope)
        with api._context_database(context) as db:bindings=state._ready_stop_bindings(context,db,task)
        verification=api._read(self.scope,task['evidence']['verification'])
        proof=dict(version=2,kind='stopped-writer-reconciliation',identity=self.fixture.identity,
            expected_revision=task['revision'],expected_pins=task['pins'],observed_turn_id=task['turn_id'],
            stopped=True,descendants_stopped=True,attempt_ids=[a['id'] for a in task['evidence']['attempts']],
            observation_ref='fixture:independent-complete-stop',coordinator_ref='fixture:host-checked',
            candidate_digest=verification['candidate_digest'],verification_digest=task['evidence']['verification']['digest'],**bindings)
        proof.update(proof_updates);raw=json.dumps(proof).encode();path=self.fixture.root/('ready-stop-'+hashlib.sha256(raw).hexdigest()+'.json')
        path.write_bytes(raw);path.chmod(0o400)
        return self.fixture.identity|dict(expected_revision=task['revision'],expected_pins=task['pins'],stop_proof=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest()))

    def stopped(self):
        task=self.ready();request=self.stop_request(task)
        result=state._retain_ready_stop(self.scope,request)
        self.assertEqual(result['task']['state'],'ready');self.assertEqual(result['task']['revision'],task['revision'])
        self.assertEqual(result['task']['lifecycle'],task['lifecycle'])
        return result['task'],request

    def test_real_ready_stop_closes_and_atomically_retires_with_original_outcome(self):
        api=self.fixture.api;task,request=self.stopped();context=api._evidence_context(self.scope)
        ref=api._canonical_plain(api._artifact_owner(self.scope,task).task)
        closed=api.close_task(self.scope,self.fixture.request(expected_pins=task['pins']),api._observe_closure((context,),ref))['task']
        self.assertEqual(closed['state'],'ready');self.assertEqual(closed['revision'],task['revision'])
        compact=api._read(self.scope,closed['lifecycle']['compact'])
        self.assertEqual(compact['outcome'],'ready');self.assertEqual(compact['usage'],'unknown')
        self.assertEqual(len(compact['stopped']['assignments']),3)
        self.assertTrue(compact['reviews']);self.assertTrue(compact['numerical']);self.assertTrue(compact['verifications'])
        api._retire_closed_task(context,ref)
        with api._context_database(context) as db:
            self.assertEqual(state._metadata(db,closed['lifecycle']['compact']['name'])['closed_at'],closed['lifecycle']['safe_closed_at'])
            self.assertEqual(db.execute('select count(*) from tasks').fetchone()[0],0)
            self.assertEqual(db.execute('select count(*) from assignments').fetchone()[0],0)
            self.assertEqual(db.execute('select count(*) from turns').fetchone()[0],0)
            self.assertEqual(db.execute('select count(*) from receipts').fetchone()[0],0)
            self.assertIsNotNone(state._retired(db,'turn',dict(scope_id=ref['scope_id'],client='codex',session_id='parent',turn_id='turn')))
            self.assertEqual(state._retired(db,'task',{k:ref[k] for k in ('scope_id','client','session_id','task_id')})['outcome'],'ready')
            from runtime import changes
            changes._check_stopped_certificate(context,db,compact['stopped'])

    def test_ready_barrier_alone_is_not_stop_authority(self):
        task=self.ready();api=self.fixture.api;context=api._evidence_context(self.scope)
        ref=api._canonical_plain(api._artifact_owner(self.scope,task).task)
        with self.assertRaises(StartupError):api._observe_closure((context,),ref)
        from runtime import changes
        with api._context_database(context) as db,self.assertRaises(StartupError):changes._stopped_certificate(context,db,dict(reference=ref,pins=task['pins']))


    def test_ready_stop_rejects_incomplete_or_forged_independent_proof(self):
        task=self.ready()
        for delta in (dict(version=1),dict(stopped=False),dict(descendants_stopped=False),dict(attempt_ids=[]),
            dict(assignments_digest='f'*64),dict(attempts_digest='f'*64),dict(task_digest='f'*64),dict(candidate_digest='f'*64),
            dict(verification_digest='f'*64),dict(generation=True),dict(observed_turn_id='foreign-turn'),dict(expected_revision=task['revision']-1),
            dict(expected_pins=task['pins']|dict(policy_digest='f'*64)),dict(native_authority=True)):
            with self.subTest(delta=delta),self.assertRaises(StartupError):state._retain_ready_stop(self.scope,self.stop_request(task,**delta))
        with state._database(self.scope) as db:
            self.assertNotIn('writer_stop',state._task(db,state._scope_id(self.scope),'codex','parent','task'))

    def test_ready_stop_exact_replay_and_generic_writers_preserve_original_envelope(self):
        api=self.fixture.api;task,request=self.stopped();context=api._evidence_context(self.scope)
        raw=Path(request['stop_proof']['path']).read_bytes();Path(request['stop_proof']['path']).unlink()
        with patch.object(api,'_artifact',side_effect=AssertionError('Replay created new managed facts')),patch.object(api,'_read_host_proof',side_effect=AssertionError('Replay reread external authority')):
            replay=state._retain_ready_stop(self.scope,request)
        self.assertTrue(replay['replayed']);self.assertEqual(replay['task'],task)
        bad=dict(request,stop_proof=dict(request['stop_proof'],path=str(self.fixture.root/'other-proof.json')))
        Path(bad['stop_proof']['path']).write_bytes(raw);Path(bad['stop_proof']['path']).chmod(0o400)
        with self.assertRaises(StartupError):state._retain_ready_stop(self.scope,bad)
        for action in ('remove','replace'):
            with api._context_database(context,write=True) as db,self.assertRaises(StartupError):
                changed=json.loads(json.dumps(task))
                if action=='remove':changed.pop('writer_stop')
                else:changed['writer_stop']['request_digest']='f'*64
                state._save(db,state._scope_id(self.scope),changed)

    def test_ready_stop_becomes_stale_after_generation_or_resumed_task(self):
        api=self.fixture.api;task,request=self.stopped();context=api._evidence_context(self.scope)
        with api._context_database(context,write=True) as db:
            db.execute('update checkouts set generation=generation+1')
        with self.assertRaises(StartupError):state._retain_ready_stop(self.scope,request)
        with api._context_database(context,write=True) as db:
            db.execute('update checkouts set generation=generation-1')
            changed=json.loads(json.dumps(task));changed.update(state='active',revision=task['revision']+1)
            state._save(db,state._scope_id(self.scope),changed)
        with self.assertRaises(StartupError):state._retain_ready_stop(self.scope,request)
        from runtime import changes
        ref=api._canonical_plain(api._artifact_owner(self.scope,task).task)
        with api._context_database(context) as db,self.assertRaises(StartupError):changes._stopped_certificate(context,db,dict(reference=ref,pins=task['pins']))

    def test_closed_ready_status_is_historical_and_new_owner_does_not_reopen_it(self):
        api=self.fixture.api;task,_=self.stopped();context=api._evidence_context(self.scope)
        ref=api._canonical_plain(api._artifact_owner(self.scope,task).task)
        closed=api.close_task(self.scope,self.fixture.request(expected_pins=task['pins']),api._observe_closure((context,),ref))['task']
        from runtime.engine import RuntimeEvent
        state.process_event(self.scope,RuntimeEvent('PostToolUse','codex','parent',self.fixture.repo,turn_id='turn',tool_call_id='late',receipt_fingerprint='b'*64))
        with patch.object(api,'capture_candidate',side_effect=AssertionError('Historical status captured current readiness')),            patch.object(api,'_capture',side_effect=AssertionError('Historical status captured current inputs')):
            status=state.task_status(self.scope,'codex','parent');evidence=api.evidence_status(self.scope,'codex','parent')
        self.assertEqual(status['task'],closed);self.assertTrue(status['historical']['historical'])
        self.assertFalse(evidence['evidence']['implementation_verified']);self.assertFalse(evidence['evidence']['merge_authority'])
        for purpose in ('completion','merge-evidence'):
            with self.subTest(purpose=purpose),self.assertRaises(StartupError):api.verify_completion(self.scope,self.fixture.request(purpose=purpose))
        self.fixture.readiness_owner(session='new-parent')
        with api._context_database(context) as db:self.assertEqual(state._task(db,state._scope_id(self.scope),'codex','parent','task'),closed)

    def test_actual_ready_d4_cut_precedes_closure_and_retired_raw_removal(self):
        from runtime import changes
        api=self.fixture.api;task,_=self.stopped();context=api._evidence_context(self.scope)
        ref=api._canonical_plain(api._artifact_owner(self.scope,task).task)
        d4,request=self.recovery_fixtures[0]
        candidate=api.capture_candidate(self.scope,api._load_plan(self.scope,self.fixture.identity))
        result=_run_d4_fixture(d4,request,'resume');self.assertEqual(result['exit_code'],0,result)
        self.assertEqual(api.capture_candidate(self.scope,api._load_plan(self.scope,self.fixture.identity)),candidate)
        old,source=self.recovery_head(d4,context)
        self.assertTrue(any(item['reference']==ref for item in source['tasks']))
        with self.assertRaises(StartupError):api._observe_closure((context,),ref)
        observed=changes._observe_recovery_release(context.authority_set,dict(source['identity']))
        with api._context_database(context) as db:
            originals=[r for r,_ in api._recovery_source_history(context,db,dict(old),dict(source['identity']))]
        released=changes._register_recovery_release(observed);self.assertTrue(released['complete'],released)
        with api._context_database(context) as db:
            current=state._task(db,state._scope_id(self.scope),'codex','parent','task')
            self.assertEqual(current['state'],'ready');self.assertEqual(current['revision'],task['revision']);self.assertIsNone(current['lifecycle']['safe_closed_at'])
        closed=api.close_task(self.scope,self.fixture.request(expected_pins=task['pins']),api._observe_closure((context,),ref))['task']
        compact=api._read(self.scope,closed['lifecycle']['compact'])
        self.assertEqual(compact['outcome'],'ready');self.assertTrue(compact['scope_guidance'])
        api._retire_closed_task(context,ref)
        retained={a['artifact']['name'] for a in observed.content['artifacts']}
        for item in list(source['artifacts']):
            if item['artifact']['name'] not in retained:(context.directory/'evidence'/item['artifact']['name']).unlink(missing_ok=True)
        for item in originals:(context.directory/'evidence'/item['name']).unlink(missing_ok=True)
        self.assertTrue(changes.inspect_lifecycle_recovery(context.authority_set,(ref,))['complete'])
        for operation in ('resume','rollback'):
            result=_run_d4_fixture(d4,request,operation);self.assertEqual(result['exit_code'],0,result)


    def test_ready_source_mutation_during_stop_rolls_back(self):
        api=self.fixture.api;task=self.ready();request=self.stop_request(task);original=api._artifact
        def move_stop(scope,value,**kwargs):
            result=original(scope,value,**kwargs)
            if value.get('kind')=='stopped-writer-reconciliation':(self.fixture.repo/'app.py').write_text('changed during stop\n')
            return result
        with patch.object(api,'_artifact',side_effect=move_stop),self.assertRaises(StartupError):state._retain_ready_stop(self.scope,request)
        with state._database(self.scope) as db:self.assertNotIn('writer_stop',state._task(db,state._scope_id(self.scope),'codex','parent','task'))
        # Disposable failed registration leaves its artifact an unknown protected orphan.

    def test_ready_candidate_mutation_during_compact_registration_rolls_back(self):
        api=self.fixture.api;task,_=self.stopped();context=api._evidence_context(self.scope)
        ref=api._canonical_plain(api._artifact_owner(self.scope,task).task);observation=api._observe_closure((context,),ref)
        original=api._artifact
        def move_compact(scope,value,**kwargs):
            result=original(scope,value,**kwargs)
            if value.get('kind')=='task-closure':(self.fixture.repo/'app.py').write_text('changed during closure\n')
            return result
        with patch.object(api,'_artifact',side_effect=move_compact),self.assertRaises(StartupError):
            api.close_task(self.scope,self.fixture.identity|dict(expected_revision=task['revision'],expected_pins=task['pins']),observation)
        with api._context_database(context) as db:
            current=state._task(db,state._scope_id(self.scope),'codex','parent','task')
            self.assertEqual(current['state'],'ready');self.assertEqual(current['revision'],task['revision'])
            self.assertIsNone(current['lifecycle']['safe_closed_at'])

    def test_blocking_findings_stay_protected(self):
        self.fixture.checked()
        finding=dict(id='open',severity='high',scope='security',status='confirmed',location='app.py:1',
            scenario='Unresolved reachable fixture path',evidence='Independent trace',counterevidence='None')
        self.fixture.review(findings=[finding]);result=self.fixture.verify();task=result['task']
        self.assertNotEqual(task['state'],'ready')
        with self.assertRaises(StartupError):state._retain_ready_stop(self.scope,self.stop_request(task))

    def test_cancelled_synchronous_barrier_without_complete_stop_stays_protected(self):
        api=self.fixture.api;task=self.ready()
        proof=dict(version=1,kind='stopped-writer-reconciliation',identity=self.fixture.identity,expected_revision=task['revision'],
            expected_pins=task['pins'],observed_turn_id=task['turn_id'],stopped=True,descendants_stopped=True,attempt_ids=[],
            observation_ref='fixture:legacy-stop',coordinator_ref='fixture:independent')
        raw=json.dumps(proof).encode();path=self.fixture.root/'legacy-cancel.json';path.write_bytes(raw);path.chmod(0o400)
        cancelled=state.retire_task(self.scope,self.fixture.request(expected_pins=task['pins'],reason='Cancelled',reference='fixture:cancel',
            stop_proof=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest())))['task']
        context=api._evidence_context(self.scope);ref=api._canonical_plain(api._artifact_owner(self.scope,cancelled).task)
        with self.assertRaises(StartupError):api._observe_closure((context,),ref)


    def test_ready_complete_older_barriers_and_verification_ages_are_retained(self):
        api=self.fixture.api;self.ready();task=self.fixture.verify()['task']
        task=state._retain_ready_stop(self.scope,self.stop_request(task))['task'];context=api._evidence_context(self.scope)
        ref=api._canonical_plain(api._artifact_owner(self.scope,task).task)
        closed=api.close_task(self.scope,self.fixture.request(expected_pins=task['pins']),api._observe_closure((context,),ref))['task']
        compact=api._read(self.scope,closed['lifecycle']['compact'])
        self.assertEqual(len(compact['stopped']['assignments']),4);self.assertEqual(len(compact['verifications']),2)
        with api._context_database(context) as db:
            for item in compact['verifications']:self.assertEqual(item['created_at'],state._metadata(db,item['source']['name'])['created_at'])

    def test_ready_assignment_task_and_event_marker_fault_rolls_back_together(self):
        api=self.fixture.api;task,_=self.stopped();context=api._evidence_context(self.scope)
        ref=api._canonical_plain(api._artifact_owner(self.scope,task).task)
        closed=api.close_task(self.scope,self.fixture.request(expected_pins=task['pins']),api._observe_closure((context,),ref))['task']
        original=state._retired_record
        def fail_task(kind,*args):
            if kind=='task':raise state.StateError('fixture marker fault after assignment removal')
            return original(kind,*args)
        with patch.object(state,'_retired_record',side_effect=fail_task),self.assertRaises(StartupError):api._retire_closed_task(context,ref)
        with api._context_database(context) as db:
            self.assertEqual(state._task(db,state._scope_id(self.scope),'codex','parent','task'),closed)
            self.assertEqual(db.execute('select count(*) from assignments').fetchone()[0],3)
            self.assertEqual(db.execute('select count(*) from retired_identities').fetchone()[0],0)
            self.assertEqual(db.execute('select count(*) from turns').fetchone()[0],1)
            self.assertEqual(db.execute('select count(*) from receipts').fetchone()[0],2)


    def test_unrelated_ancestor_sibling_during_compact_write_keeps_ready_candidate_valid(self):
        api=self.fixture.api;task,_=self.stopped();context=api._evidence_context(self.scope)
        ref=api._canonical_plain(api._artifact_owner(self.scope,task).task);observed=api._observe_closure((context,),ref)
        original=api._artifact
        def sibling(scope,value,**kwargs):
            result=original(scope,value,**kwargs)
            if value.get('kind')=='task-closure':(self.fixture.root/'unrelated.txt').write_text('Outside candidate repository')
            return result
        with patch.object(api,'_artifact',side_effect=sibling):
            closed=api.close_task(self.scope,self.fixture.identity|dict(expected_revision=task['revision'],expected_pins=task['pins']),observed)['task']
        self.assertEqual(closed['state'],'ready');self.assertEqual(closed['revision'],task['revision'])


    def test_new_candidate_input_and_same_byte_replacement_protect_compact_commit(self):
        for mutation in ('addition','same-bytes'):
            with self.subTest(mutation=mutation):
                scenario=ReadyClosureTests(methodName='runTest');scenario.setUp()
                try:
                    api=scenario.fixture.api;task,_=scenario.stopped();context=api._evidence_context(scenario.scope)
                    ref=api._canonical_plain(api._artifact_owner(scenario.scope,task).task);observed=api._observe_closure((context,),ref)
                    original=api._artifact
                    def mutate(scope,value,**kwargs):
                        result=original(scope,value,**kwargs)
                        if value.get('kind')=='task-closure':
                            if mutation=='addition':(scenario.fixture.repo/'new-input.py').write_text('new candidate input')
                            else:
                                path=scenario.fixture.repo/'app.py';replacement=path.with_name('replacement.py')
                                replacement.write_bytes(path.read_bytes());os.replace(replacement,path)
                        return result
                    with patch.object(api,'_artifact',side_effect=mutate),self.assertRaises(StartupError):
                        api.close_task(scenario.scope,scenario.fixture.identity|dict(expected_revision=task['revision'],expected_pins=task['pins']),observed)
                finally:scenario.doCleanups()

    def source_scenario(self,*,shared=False):
        from tests.test_state import canonical_scope
        from runtime.startup import _canonical_plain,_canonical_freeze
        import shutil
        scenario=ReadyClosureTests(methodName='runTest');scenario.fixture=EvidenceTests(methodName='runTest')
        scenario.fixture.setUp();scenario.addCleanup(scenario.fixture.doCleanups)
        original_package=state.PACKAGE;package=scenario.fixture.root/'installed'
        for source in [*state._runtime_sources(),*(original_package/'policies').glob('*.md')]:
            target=package/source.relative_to(original_package);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        patcher=patch.object(state,'PACKAGE',package);patcher.start();scenario.addCleanup(patcher.stop)
        scope=canonical_scope(scenario.fixture.scope)
        dependency=scenario.fixture.root/'shared-guide.md';dependency.write_text('accepted workflow')
        if shared:
            identity=_canonical_plain(scope.accepted_identity)
            identity['shared_policy']=[dict(path=str(dependency),sha256=hashlib.sha256(dependency.read_bytes()).hexdigest())]
            scope=replace(scope,accepted_identity=_canonical_freeze(identity),accepted_scope_digest=scenario.fixture.api._digest(identity))
        scenario.scope=scope;scenario.fixture.scope=scope
        state.start_task(scope,scenario.fixture.identity|dict(mode='editable',decision_ref='user:accepted'));scenario.fixture.plan()
        return scenario,package,dependency

    def test_required_shared_policy_and_installed_source_changes_block_final_writer(self):
        for source_kind in ('shared','policy','runtime','policy-membership'):
            with self.subTest(source=source_kind):
                scenario,package,dependency=self.source_scenario(shared=source_kind=='shared')
                try:
                    api=scenario.fixture.api;task,_=scenario.stopped();context=api._evidence_context(scenario.scope)
                    ref=api._canonical_plain(api._artifact_owner(scenario.scope,task).task);observed=api._observe_closure((context,),ref)
                    original=api._artifact
                    target=dependency if source_kind=='shared' else package/('runtime/engine.py' if source_kind=='runtime' else
                        'policies/new-policy.md' if source_kind=='policy-membership' else 'policies/00-index.md')
                    def mutate(scope,value,**kwargs):
                        result=original(scope,value,**kwargs)
                        if value.get('kind')=='task-closure':target.write_text('changed required source')
                        return result
                    with patch.object(api,'_artifact',side_effect=mutate),self.assertRaises(StartupError):
                        api.close_task(scenario.scope,scenario.fixture.identity|dict(expected_revision=task['revision'],expected_pins=task['pins']),observed)
                    with api._context_database(context) as db:
                        self.assertIsNone(state._task(db,state._scope_id(scenario.scope),'codex','parent','task')['lifecycle']['safe_closed_at'])
                finally:scenario.doCleanups()


class CancelledBarrierClosureTests(D4RecoveryFixture, unittest.TestCase):
    """Actual synchronous barriers; independent fixture host authority remains unqualified."""
    def setUp(self):
        consumers = {
            'test_cancelled_barrier_complete_stop_d4_cut_closure_and_retired_recovery',
            'test_independent_raw_consumer_protects_cancelled_task_after_d4_cut',
            'test_cancelled_source_mutation_during_d4_cut_keeps_raw_support',
            'test_cancelled_new_input_during_d4_cut_keeps_raw_support',
        }
        CanonicalEvidenceTests.setUp(self, d4_recovery=self._testMethodName in consumers,
            shared=self._testMethodName == 'test_independent_raw_consumer_protects_cancelled_task_after_d4_cut')

    ready = ReadyClosureTests.ready
    stop_request = ReadyClosureTests.stop_request

    def cancelled(self, *, failed=False, stale=False, older_failed=False):
        api=self.fixture.api
        if older_failed:
            self.fixture.checked();self.fixture.verify();self.fixture.review();task=self.fixture.verify()['task']
            self.assertEqual(task['state'],'ready')
        elif failed:
            self.fixture.checked()
            task=self.fixture.verify()['task']
            self.assertNotEqual(task['state'],'ready')
        else:task=self.ready()
        proof=dict(version=1,kind='stopped-writer-reconciliation',identity=self.fixture.identity,
            expected_revision=task['revision'],expected_pins=task['pins'],observed_turn_id=task['turn_id'],
            stopped=True,descendants_stopped=True,attempt_ids=[],observation_ref='fixture:legacy-stop',coordinator_ref='fixture:independent')
        raw=json.dumps(proof).encode();path=self.fixture.root/'legacy-cancel.json';path.write_bytes(raw);path.chmod(0o400)
        task=state.retire_task(self.scope,self.fixture.request(expected_pins=task['pins'],reason='Cancelled',reference='fixture:cancel',
            stop_proof=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest())))['task']
        if stale:(self.fixture.repo/'app.py').write_text('changed after historical verification\n')
        return task

    def stopped(self, **options):
        api=self.fixture.api;task=self.cancelled(**options)
        candidate=api.capture_candidate(self.scope,api._load_plan(self.scope,self.fixture.identity))
        request=self.stop_request(task,candidate_digest=api._digest(candidate))
        stopped=state._retain_ready_stop(self.scope,request)['task']
        for key in ('state','revision','retirement','pins','lifecycle'):self.assertEqual(stopped[key],task[key])
        return stopped,request

    def test_cancelled_barrier_complete_stop_d4_cut_closure_and_retired_recovery(self):
        from runtime import changes
        api=self.fixture.api;task,_=self.stopped()
        d4,request,context,ref,source,old=self.recovery(task)
        observed=changes._observe_recovery_release(context.authority_set,dict(source['identity']))
        with api._context_database(context) as db:
            originals=[r for r,_ in api._recovery_source_history(context,db,dict(old),dict(source['identity']))]
        self.assertTrue(changes._register_recovery_release(observed)['complete'])
        with api._context_database(context) as db:
            current=state._task(db,state._scope_id(self.scope),'codex','parent','task')
            self.assertEqual(current,task)
        closed=api.close_task(self.scope,self.fixture.request(expected_pins=task['pins']),api._observe_closure((context,),ref))['task']
        compact=api._read(self.scope,closed['lifecycle']['compact'])
        self.assertEqual(compact['outcome'],'cancelled');self.assertEqual(closed['retirement'],task['retirement'])
        self.assertEqual(len(compact['stopped']['assignments']),3)
        api._retire_closed_task(context,ref)
        with api._context_database(context) as db:
            self.assertEqual(db.execute('select count(*) from tasks').fetchone()[0],0)
            self.assertEqual(db.execute('select count(*) from assignments').fetchone()[0],0)
            self.assertEqual(db.execute('select count(*) from turns').fetchone()[0],0)
            self.assertEqual(db.execute('select count(*) from receipts').fetchone()[0],0)
            marker=state._retired(db,'task',{k:ref[k] for k in ('scope_id','client','session_id','task_id')})
            self.assertEqual(marker['outcome'],'cancelled');self.assertEqual(marker['created_at'],task['lifecycle']['created_at'])
            changes._check_stopped_certificate(context,db,compact['stopped'])
        retained={a['artifact']['name'] for a in observed.content['artifacts']}
        for item in source['artifacts']:
            if item['artifact']['name'] not in retained:(context.directory/'evidence'/item['artifact']['name']).unlink(missing_ok=True)
        for item in originals:(context.directory/'evidence'/item['name']).unlink(missing_ok=True)
        self.assertTrue(changes.inspect_lifecycle_recovery(context.authority_set,(ref,))['complete'])
        for operation in ('resume','rollback'):
            result=_run_d4_fixture(d4,request,operation);self.assertEqual(result['exit_code'],0,result)


    def test_failed_and_stale_barriers_retain_actual_historical_verification(self):
        for options in (dict(failed=True),dict(stale=True),dict(older_failed=True)):
            with self.subTest(options=options):
                scenario=CancelledBarrierClosureTests(methodName='runTest');scenario.setUp()
                try:
                    api=scenario.fixture.api;task,_=scenario.stopped(**options);context=api._evidence_context(scenario.scope)
                    ref=api._canonical_plain(api._artifact_owner(scenario.scope,task).task)
                    original=api._read(scenario.scope,task['evidence']['verification'])
                    closed=api.close_task(scenario.scope,scenario.fixture.request(expected_pins=task['pins']),api._observe_closure((context,),ref))['task']
                    compact=api._read(scenario.scope,closed['lifecycle']['compact'])
                    self.assertEqual(compact['outcome'],'cancelled');self.assertIn(original,[v['result'] for v in compact['verifications']])
                    if options.get('failed'):self.assertTrue(original['blockers'])
                    elif options.get('older_failed'):
                        self.assertEqual(len(compact['verifications']),2)
                        self.assertTrue(any(v['result']['blockers'] for v in compact['verifications']))
                    else:self.assertNotEqual(task['writer_stop']['candidate']['digest'],original['candidate_digest'])
                    with api._context_database(context) as db:
                        for item in compact['verifications']:
                            self.assertEqual(item['created_at'],state._metadata(db,item['source']['name'])['created_at'])
                    api._retire_closed_task(context,ref)
                finally:scenario.doCleanups()

    def test_cancelled_complete_stop_requires_exact_full_proof(self):
        task=self.cancelled();api=self.fixture.api
        for delta in (dict(version=1),dict(stopped=False),dict(descendants_stopped=False),dict(attempt_ids=[]),
            dict(attempt_ids=[a['id'] for a in task['evidence']['attempts']]+['foreign']),dict(assignments_digest='f'*64),
            dict(attempts_digest='f'*64),dict(task_digest='f'*64),dict(candidate_digest='f'*64),dict(verification_digest='f'*64),
            dict(expected_revision=task['revision']-1),dict(observed_turn_id='foreign-turn')):
            with self.subTest(delta=delta),self.assertRaises(StartupError):state._retain_ready_stop(self.scope,self.stop_request(task,**delta))
        context=api._evidence_context(self.scope)
        with api._context_database(context) as db:self.assertNotIn('writer_stop',state._task(db,state._scope_id(self.scope),'codex','parent','task'))

    def test_cancelled_check_without_synchronous_barrier_cannot_acquire_complete_stop(self):
        api=self.fixture.api;self.fixture.checked();task=state.task_status(self.scope,'codex','parent')['task']
        proof=dict(version=1,kind='stopped-writer-reconciliation',identity=self.fixture.identity,
            expected_revision=task['revision'],expected_pins=task['pins'],observed_turn_id=task['turn_id'],stopped=True,
            descendants_stopped=True,attempt_ids=[],observation_ref='fixture:no-barrier',coordinator_ref='fixture:independent')
        raw=json.dumps(proof).encode();path=self.fixture.root/'no-barrier-cancel.json';path.write_bytes(raw);path.chmod(0o400)
        task=state.retire_task(self.scope,self.fixture.request(expected_pins=task['pins'],reason='Cancelled',reference='fixture:cancel',
            stop_proof=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest())))['task']
        context=api._evidence_context(self.scope)
        with api._context_database(context) as db:bindings=state._ready_stop_bindings(context,db,task)
        candidate=api.capture_candidate(self.scope,api._load_plan(self.scope,self.fixture.identity))
        proof.update(version=2,expected_revision=task['revision'],attempt_ids=[a['id'] for a in task['evidence']['attempts']],
            candidate_digest=api._digest(candidate),verification_digest='f'*64,**bindings)
        raw=json.dumps(proof).encode();path=self.fixture.root/'no-barrier-complete.json';path.write_bytes(raw);path.chmod(0o400)
        with self.assertRaisesRegex(StartupError,'actual original synchronous barrier'):
            state._retain_ready_stop(self.scope,self.fixture.request(expected_pins=task['pins'],stop_proof=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest())))

    def test_cancelled_complete_stop_replay_and_generic_writer_preserve_original_age(self):
        api=self.fixture.api;task,request=self.stopped();context=api._evidence_context(self.scope)
        Path(request['stop_proof']['path']).unlink()
        with patch.object(api,'_artifact',side_effect=AssertionError('Replay wrote new support')),patch.object(api,'_read_host_proof',side_effect=AssertionError('Replay read host proof')):
            replay=state._retain_ready_stop(self.scope,request)
        self.assertTrue(replay['replayed']);self.assertEqual(replay['task'],task)
        for action in ('remove','replace'):
            with api._context_database(context,write=True) as db,self.assertRaises(StartupError):
                changed=json.loads(json.dumps(task))
                if action=='remove':changed.pop('writer_stop')
                else:changed['writer_stop']['request_digest']='f'*64
                state._save(db,state._scope_id(self.scope),changed)

    def test_changed_cancelled_barrier_source_or_revision_blocks_closure(self):
        for mutation in ('source','barrier','revision','retirement-proof','generation'):
            with self.subTest(mutation=mutation):
                scenario=CancelledBarrierClosureTests(methodName='runTest');scenario.setUp()
                try:
                    api=scenario.fixture.api;task,_=scenario.stopped();context=api._evidence_context(scenario.scope)
                    ref=api._canonical_plain(api._artifact_owner(scenario.scope,task).task)
                    if mutation=='source':(scenario.fixture.repo/'app.py').write_text('changed after complete stop')
                    elif mutation=='retirement-proof':
                        path=context.directory/'evidence'/task['retirement']['proof']['name'];path.chmod(0o600);path.write_bytes(path.read_bytes()+b' ');path.chmod(0o400)
                    else:
                        with api._context_database(context,write=True) as db:
                            if mutation=='barrier':
                                from runtime import delegation
                                row=next(r for r in delegation._ledger(None,db,context=context) if r['data']['role']=='coordinator')
                                data=dict(row['data'],revision=row['data']['revision']-1)
                                db.execute('update assignments set data=? where id=?',(json.dumps(data),row['id']))
                            elif mutation=='generation':db.execute('update checkouts set generation=generation+1')
                            else:
                                changed=dict(task,revision=task['revision']+1);state._save(db,state._scope_id(scenario.scope),changed)
                    with self.assertRaises(StartupError):api._observe_closure((context,),ref)
                finally:scenario.doCleanups()

    def test_cancelled_stop_source_change_during_registration_rolls_back(self):
        api=self.fixture.api;task=self.cancelled();request=self.stop_request(task);original=api._artifact
        def mutate(scope,value,**kwargs):
            result=original(scope,value,**kwargs)
            if value.get('kind')=='stopped-writer-reconciliation':(self.fixture.repo/'app.py').write_text('changed during stop')
            return result
        with patch.object(api,'_artifact',side_effect=mutate),self.assertRaises(StartupError):state._retain_ready_stop(self.scope,request)
        with state._database(self.scope) as db:self.assertNotIn('writer_stop',state._task(db,state._scope_id(self.scope),'codex','parent','task'))

    def test_cancelled_assignment_task_and_event_retirement_fault_is_atomic(self):
        api=self.fixture.api;task,_=self.stopped();context=api._evidence_context(self.scope)
        ref=api._canonical_plain(api._artifact_owner(self.scope,task).task)
        closed=api.close_task(self.scope,self.fixture.request(expected_pins=task['pins']),api._observe_closure((context,),ref))['task']
        original=state._retired_record
        def fail(kind,*args):
            if kind=='task':raise state.StateError('fixture: cancelled task marker fault')
            return original(kind,*args)
        with patch.object(state,'_retired_record',side_effect=fail),self.assertRaises(StartupError):api._retire_closed_task(context,ref)
        with api._context_database(context) as db:
            self.assertEqual(state._task(db,state._scope_id(self.scope),'codex','parent','task'),closed)
            self.assertEqual(db.execute('select count(*) from assignments').fetchone()[0],3)
            self.assertEqual(db.execute('select count(*) from retired_identities').fetchone()[0],0)
            self.assertEqual(db.execute('select count(*) from turns').fetchone()[0],1)
            self.assertEqual(db.execute('select count(*) from receipts').fetchone()[0],2)

    def test_independent_raw_consumer_protects_cancelled_task_after_d4_cut(self):
        from runtime import changes
        api=self.fixture.api;task,_=self.stopped();_,_,context,ref,source,_=self.recovery(task)
        _,_,_,_,other,_=self.recovery(task)
        observed=changes._observe_recovery_release(context.authority_set,dict(source['identity']))
        self.assertTrue(changes._register_recovery_release(observed)['complete'])
        inspected=changes.inspect_lifecycle_recovery(context.authority_set,())
        self.assertTrue(any(r['kind']=='task' and r['reference']==ref and r['need']=='raw' and
            r['root']['identity']==dict(other['identity']) for r in inspected['requirements']))
        with self.assertRaisesRegex(StartupError,'raw task body'):api._observe_closure((context,),ref)


    def test_cancellation_after_ready_complete_stop_keeps_stale_envelope_protected(self):
        api=self.fixture.api;task=ReadyClosureTests.stopped(self)[0]
        proof=dict(version=1,kind='stopped-writer-reconciliation',identity=self.fixture.identity,
            expected_revision=task['revision'],expected_pins=task['pins'],observed_turn_id=task['turn_id'],stopped=True,
            descendants_stopped=True,attempt_ids=[],observation_ref='fixture:later-cancellation',coordinator_ref='fixture:independent')
        raw=json.dumps(proof).encode();path=self.fixture.root/'later-cancel.json';path.write_bytes(raw);path.chmod(0o400)
        cancelled=state.retire_task(self.scope,self.fixture.request(expected_pins=task['pins'],reason='Cancelled',reference='fixture:cancel',
            stop_proof=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest())))['task']
        self.assertEqual(cancelled['writer_stop'],task['writer_stop'])
        with self.assertRaises(StartupError):state._retain_ready_stop(self.scope,self.stop_request(cancelled))
        context=api._evidence_context(self.scope);ref=api._canonical_plain(api._artifact_owner(self.scope,cancelled).task)
        with self.assertRaises(StartupError):api._observe_closure((context,),ref)

    def test_cancelled_source_mutation_during_compact_write_rolls_back_closure(self):
        api=self.fixture.api;task,_=self.stopped();context=api._evidence_context(self.scope)
        ref=api._canonical_plain(api._artifact_owner(self.scope,task).task);observed=api._observe_closure((context,),ref)
        original=api._artifact
        def mutate(scope,value,**kwargs):
            result=original(scope,value,**kwargs)
            if value.get('kind')=='task-closure':(self.fixture.repo/'app.py').write_text('changed during cancelled closure')
            return result
        with patch.object(api,'_artifact',side_effect=mutate),self.assertRaises(StartupError):
            api.close_task(self.scope,self.fixture.request(expected_pins=task['pins']),observed)
        with api._context_database(context) as db:
            current=state._task(db,state._scope_id(self.scope),'codex','parent','task')
            self.assertEqual(current,task)

    def test_cancelled_source_mutation_during_d4_cut_keeps_raw_support(self):
        from runtime import changes
        api=self.fixture.api;task,_=self.stopped();_,_,context,ref,source,old=self.recovery(task)
        observed=changes._observe_recovery_release(context.authority_set,dict(source['identity']));original=api._artifact
        def mutate(scope,value,**kwargs):
            result=original(scope,value,**kwargs)
            if value.get('kind')=='d4-recovery-source' and value.get('version')==2:
                (self.fixture.repo/'app.py').write_text('changed during cancelled source cut')
            return result
        with patch.object(api,'_artifact',side_effect=mutate):result=changes._register_recovery_release(observed)
        self.assertFalse(result['complete'])
        with api._context_database(context) as db:
            self.assertEqual(state._task(db,state._scope_id(self.scope),'codex','parent','task'),task)
            self.assertEqual(db.execute('select count(*) from assignments').fetchone()[0],3)
            api._read(None,dict(old),context=context,db=db)


    def test_cancelled_new_input_during_d4_cut_keeps_raw_support(self):
        from runtime import changes
        api=self.fixture.api;task,_=self.stopped();_,_,context,ref,source,old=self.recovery(task)
        observed=changes._observe_recovery_release(context.authority_set,dict(source['identity']));original=api._artifact
        def mutate(scope,value,**kwargs):
            result=original(scope,value,**kwargs)
            if value.get('kind')=='d4-recovery-source' and value.get('version')==2:
                (self.fixture.repo/'new-candidate-input.py').write_text('new input during cancelled source cut')
            return result
        with patch.object(api,'_artifact',side_effect=mutate):result=changes._register_recovery_release(observed)
        self.assertFalse(result['complete'])
        with api._context_database(context) as db:
            self.assertEqual(state._task(db,state._scope_id(self.scope),'codex','parent','task'),task)
            self.assertEqual(db.execute('select count(*) from assignments').fetchone()[0],3)
            api._read(None,dict(old),context=context,db=db)


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
        with patch.object(state,'_owner_time',return_value=200):closed=self.close()['task']
        with patch.object(state,'_owner_time',return_value=250):self.api._retire_closed_task(self.context,self.ref)
        with self.api._context_database(self.context) as db:
            self.assertEqual(db.execute('select count(*) from tasks').fetchone()[0],0)
            marker=state._retired(db,'task',{k:self.ref[k] for k in ('scope_id','client','session_id','task_id')})
            self.assertEqual(marker['created_at'],100);self.assertEqual(marker['outcome'],'cancelled')
            self.assertEqual(state._metadata(db,closed['lifecycle']['compact']['name'])['closed_at'],closed['lifecycle']['safe_closed_at'])
        with self.assertRaises(state.StateError):self.f.start()

    def test_cancelled_retirement_date_stamp_exact_replay(self):
        task=self.close()['task'];observation=self.api._observe_closure((self.context,),self.ref)
        compact=task['lifecycle']['compact'];closed_at=task['lifecycle']['safe_closed_at']
        with self.api._context_database(self.context,write=True) as db:
            self.api._stamp_linked_retirement(self.context,db,self.ref,observation)
            first=state._metadata(db,compact['name'])
            self.api._stamp_linked_retirement(self.context,db,self.ref,observation)
            second=state._metadata(db,compact['name'])
        self.assertEqual(first['closed_at'],closed_at)
        self.assertEqual(second,first)

    def test_cancelled_retirement_date_conflict_and_transaction_retry(self):
        from runtime import delegation
        task=self.close()['task'];compact=task['lifecycle']['compact'];safe_closed_at=task['lifecycle']['safe_closed_at']
        with patch.object(delegation,'retire_settled',side_effect=state.StateError('fixture:after date stamp')):
            with self.assertRaises(state.StateError):self.api._retire_closed_task(self.context,self.ref)
        with self.api._context_database(self.context) as db:
            self.assertIsNone(state._metadata(db,compact['name'])['closed_at'])
            self.assertIsNotNone(state._task(db,self.ref['scope_id'],'codex','session'))
            self.assertEqual(db.execute('select count(*) from retired_identities').fetchone()[0],0)
        with self.api._context_database(self.context,write=True) as db:
            metadata=state._metadata(db,compact['name']);conflict=safe_closed_at+1
            metadata=dict(metadata,closed_at=conflict)
            db.execute('update evidence_metadata set closed_at=?,data=? where name=?',
                (conflict,json.dumps(metadata,separators=(',',':')),compact['name']))
        with self.api._context_database(self.context) as db:before=list(db.iterdump())
        with self.assertRaises(state.StateError):self.api._retire_closed_task(self.context,self.ref)
        with self.api._context_database(self.context) as db:self.assertEqual(list(db.iterdump()),before)
        with self.api._context_database(self.context,write=True) as db:
            metadata=state._metadata(db,compact['name']);metadata=dict(metadata,closed_at=None)
            db.execute('update evidence_metadata set closed_at=NULL,data=? where name=?',
                (json.dumps(metadata,separators=(',',':')),compact['name']))
        self.api._retire_closed_task(self.context,self.ref)
        with self.api._context_database(self.context) as db:
            self.assertEqual(state._metadata(db,compact['name'])['closed_at'],safe_closed_at)
            self.assertEqual(state._retired(db,'task',{k:self.ref[k] for k in ('scope_id','client','session_id','task_id')})['outcome'],'cancelled')

    def test_retirement_rejects_mismatched_closure_envelope_date(self):
        self.close();identity=tuple(self.ref[key] for key in ('scope_id','client','session_id','task_id'))
        with self.api._context_database(self.context,write=True) as db:
            row=db.execute('select data from tasks where scope_id=? and client=? and session_id=? and task_id=?',identity).fetchone()
            task=json.loads(row[0]);task['lifecycle']['closure']['observed_at']+=1
            db.execute('update tasks set data=? where scope_id=? and client=? and session_id=? and task_id=?',
                (json.dumps(task,separators=(',',':')),*identity))
        with self.api._context_database(self.context) as db:before=list(db.iterdump())
        with self.assertRaises(state.StateError):self.api._retire_closed_task(self.context,self.ref)
        with self.api._context_database(self.context) as db:
            self.assertEqual(list(db.iterdump()),before)
            self.assertIsNotNone(state._task(db,*identity))
            self.assertIsNone(state._retired(db,'task',{k:self.ref[k] for k in ('scope_id','client','session_id','task_id')}))

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
        resumed=_run_d4_fixture(f,request,'resume');self.assertEqual(resumed['exit_code'],0,resumed)
        rolled=_run_d4_fixture(f,request,'rollback');self.assertEqual(rolled['exit_code'],0,rolled)
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


class LinkedVerificationTests(D4RecoveryFixture, unittest.TestCase):
    """Synthetic trusted coordinator sources; actual disposable check receipts, no native qualification."""
    def setUp(self):
        from types import SimpleNamespace
        from tests.test_state import canonical_scope
        from tests.test_startup import CanonicalAcquisitionTests
        from runtime import evidence
        self.api = evidence
        self.members = []
        d4_recovery = self._testMethodName in {
            'test_linked_non_success_mixed_required_merged_history_survives_d4_retirement',
            'test_linked_no_verifier_native_history_survives_d4_retirement_and_guidance',
            'test_linked_preparation_compacts_precede_d4_cut_without_closure_or_raw_retirement',
            'test_linked_preparation_post_release_observation_substitution_keeps_raw_source',
            'test_linked_safe_closure_second_transaction_failure_reuses_registered_candidate',
            'test_linked_retirement_sequential_members_preserve_markers_and_recovery',
            'test_linked_safe_closure_recovery_progress_accepts_exact_prior_closure',
            'test_linked_safe_closure_foreign_recovery_raw_root_stays_protected',
            'test_linked_safe_closure_changed_prior_lifecycle_envelope_rejects',
            'test_linked_safe_closure_sequential_members_preserves_raw_history_and_recovery',
            'test_preparation_reuse_inspection_captures_once_and_preserves_requirements_and_rows',
            'test_linked_preparation_component_owned_source_keeps_explicit_foreign_raw_demand',
            'test_linked_safe_closure_late_peer_change_preserves_committed_history',
            'test_linked_safe_closure_late_source_change_preserves_committed_history',
            'test_linked_safe_closure_stale_pending_candidate_stays_protected',
            'test_linked_safe_closure_substituted_pending_candidate_stays_protected',
            'test_linked_safe_closure_unregistered_candidate_lookalike_stays_protected',
        }
        for number in range(2):
            f = EvidenceTests(methodName='runTest'); f.setUp(); self.addCleanup(f.doCleanups)
            f.scope = canonical_scope(f.scope)
            if d4_recovery and number == 0:
                self.current_record(f)
                self.fixture = f
                f.scope = self.enroll_recovery(shared=self._testMethodName == 'test_linked_preparation_compacts_precede_d4_cut_without_closure_or_raw_retirement')
                if self._testMethodName in {
                    'test_linked_non_success_mixed_required_merged_history_survives_d4_retirement',
                    'test_linked_preparation_compacts_precede_d4_cut_without_closure_or_raw_retirement',
                }:
                    (f.scope.git_dir / 'info').mkdir(exist_ok=True)
                    with (f.scope.git_dir / 'info/exclude').open('a') as exclude:
                        exclude.write('\n/AGENTS.md\n')
                self.scope = f.scope
            state.start_task(f.scope, f.identity | dict(mode='editable', decision_ref='user:accepted'))
            if not (d4_recovery and number == 0):self.current_record(f)
            self.members.append(f)
        self.selected = self.members[0]
        self.establish()

    def current_record(self,f):
        from types import SimpleNamespace
        from tests.test_startup import CanonicalAcquisitionTests
        record,path=CanonicalAcquisitionTests.record(SimpleNamespace(repo=f.repo,base=f.root,assertIsNone=self.assertIsNone))
        identity=self.api._canonical_plain(f.scope.accepted_identity)
        record['project_id']=identity['project_id'];record['repositories'][0]['repository_id']=identity['repository_id']
        record['repositories'][0]['checkouts'][0]['checkout_id']=identity['checkout_id']
        record['repositories'][0]['checkouts'][0]['clients'][0]['configuration'].update(identity['configuration'])
        path.write_text(json.dumps(record))
        return path

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

    def stop_request(self,f,pointer,**updates):
        task=self.task(f);context=self.api._evidence_context(f.scope)
        with self.api._context_database(context) as db:bindings=state._ready_stop_bindings(context,db,task)
        plan=self.api._read(f.scope,task['evidence']['plan']);candidate=self.api.capture_candidate(f.scope,plan)
        proof=dict(version=2,kind='stopped-writer-reconciliation',identity=f.identity,expected_revision=task['revision'],
            expected_pins=task['pins'],observed_turn_id=task['turn_id'],stopped=True,descendants_stopped=True,
            attempt_ids=[a['id'] for a in task['evidence']['attempts']],observation_ref='fixture:independent-linked-stop',
            coordinator_ref='fixture:host-checked',candidate_digest=self.api._digest(candidate),
            verification_digest=task['evidence']['verification']['digest'],**bindings)
        with self.api._linked_stop_guards(pointer,self.api._canonical_plain(context.authority_set)) as authorities:
            proof['linked_digest']=self.api._digest(self.api._linked_stop_basis(pointer,authorities))
        proof.update(updates)
        raw=json.dumps(proof).encode();path=f.root/('linked-stop-'+hashlib.sha256(raw).hexdigest()+'.json');path.write_bytes(raw);path.chmod(0o400)
        return f.identity|dict(expected_revision=task['revision'],expected_pins=task['pins'],linked_verification=pointer,
            stop_proof=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest()))

    def cancel_linked_members(self,cancel=(0,1)):
        originals=[]
        for index,f in enumerate(self.members):
            task=self.task(f)
            if index in cancel:
                proof=dict(version=1,kind='stopped-writer-reconciliation',identity=f.identity,expected_revision=task['revision'],expected_pins=task['pins'],
                    observed_turn_id=task['turn_id'],stopped=True,descendants_stopped=True,attempt_ids=[],observation_ref='fixture:independent-non-success-cancellation',coordinator_ref='fixture:host-checked')
                raw=json.dumps(proof).encode();path=f.root/'non-success-cancel.json';path.write_bytes(raw);path.chmod(0o400)
                task=state.retire_task(f.scope,f.request(expected_pins=task['pins'],reason='Settled failed linked work',reference='fixture:cancelled-non-success',
                    stop_proof=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest())))['task']
            originals.append(task)
        return originals

    def non_success_cancelled_component(self,*,shared_status='failed',cancel=(0,1)):
        result=self.verify(self.observations(shared_status=shared_status));pointer=result['verification']
        self.assertFalse(result['implementation_verified']);self.assertFalse(result['merge_authority']);self.assertTrue(result['delivery_complete'])
        self.assertTrue(result['blockers']);self.assertTrue(all(self.task(f)['state']!='ready' for f in self.members))
        return pointer,self.cancel_linked_members(cancel)

    def test_linked_failed_null_publication_cancelled_complete_stops_preserve_failure(self):
        pointer,originals=self.non_success_cancelled_component()
        content=self.api._linked_source(pointer);self.assertFalse(content['implementation_verified']);self.assertTrue(content['blockers'])
        for index,f in enumerate(self.members):
            stopped=state._retain_ready_stop(f.scope,self.stop_request(f,pointer))['task']
            for key in ('state','revision','retirement','pins','lifecycle'):self.assertEqual(stopped[key],originals[index][key])
            self.assertEqual(stopped['state'],'cancelled')
        self.assertEqual(self.api._linked_source(pointer),content)

    def test_linked_failed_null_publication_history_closes_and_retires_without_acceptance(self):
        from runtime import delegation
        pointer,originals=self.non_success_cancelled_component();content=self.api._linked_source(pointer)
        contexts=tuple(self.api._evidence_context(f.scope) for f in self.members);refs=tuple(self.reference(f) for f in self.members)
        with patch.object(self.api,'_verify_member',side_effect=AssertionError('Lifecycle invoked new verification')), \
             patch.object(delegation,'_reserve_operation',side_effect=AssertionError('Lifecycle created a new verifier/barrier')):
            for f in self.members:state._retain_ready_stop(f.scope,self.stop_request(f,pointer))
            authorities=[self.api._canonical_plain(c.authority_set[0]) for c in contexts]
            prepared=self.api._prepare_linked_closure(self.api._observe_linked_preparation(pointer,authorities));self.assertTrue(prepared['complete'])
            closed=[]
            for index,ref in enumerate(refs):
                task=self.api.close_task(self.members[index].scope,self.linked_closure_request(index),self.api._observe_closure(contexts,ref))['task'];closed.append(task)
                self.assertEqual(task['state'],originals[index]['state']);self.assertEqual(task['revision'],originals[index]['revision']);self.assertEqual(task['pins'],originals[index]['pins'])
            for index,(context,ref) in enumerate(zip(contexts,refs)):
                compact=self.api._read(None,closed[index]['lifecycle']['compact'],context=context)
                self.assertEqual(compact['stopped']['linked']['content'],content);self.assertTrue(compact['numerical']);self.assertTrue(compact['verifications'])
                self.assertFalse(compact['stopped']['linked']['content']['implementation_verified']);self.assertEqual(compact['stopped']['retirement'],originals[index]['retirement'])
                self.assertTrue(self.api._retire_closed_task(context,ref)['retired'])
                with self.api._context_database(context) as db:
                    marker=state._retired(db,'task',{key:ref[key] for key in ('scope_id','client','session_id','task_id')})
                    self.assertEqual(marker['outcome'],'cancelled');self.assertEqual(marker['created_at'],originals[index]['lifecycle']['created_at'])
        self.assertEqual(self.api._linked_source(pointer),content)

    def test_linked_non_success_mixed_required_merged_history_survives_d4_retirement(self):
        from runtime import changes,delegation
        from runtime.engine import RuntimeEvent
        delivery=dict(provider='fixture',repository='owner/repo',target='main',pull_request='fixture:required-non-success')
        self.establish(delivery)
        peer=self.members[1];plan=self.api._read(peer.scope,self.task(peer)['evidence']['plan'])
        plan['checks'][0]['argv']=[sys.executable,'-c','import sys; print("real failed result"); sys.exit(7)']
        self.api.plan_evidence(peer.scope,peer.request(plan=plan,change_decision_ref='user:accepted-failing-check-fixture'))
        failed=peer.checked()['attempt'];self.assertEqual(failed['status'],'failed');self.assertEqual(failed['exit_code'],7)
        finding=dict(id='unresolved-result',severity='medium',scope='general',status='confirmed',location='app.py:1',
            scenario='Observed unfinished result',evidence='Actual fixture code trace',counterevidence='No accepted correction')
        reviewed=self.selected.review(findings=[finding]);attempt=next(a for a in self.task(self.selected)['evidence']['attempts'] if a['id']==reviewed['attempt_id'])
        assessment=self.api._read(self.selected.scope,attempt['assessment'])['assessment']
        assessment['dispositions']=[dict(finding_id=finding['id'],status='open',reference='fixture:original-open-disposition')]
        self.api.assess_review(self.selected.scope,self.selected.request(attempt_id=reviewed['attempt_id'],assessment=assessment))
        for f in self.members:
            for kind in ('PreToolUse','PostToolUse'):
                state.process_event(f.scope,RuntimeEvent(kind,'codex','parent',f.repo,turn_id='turn',tool_call_id='non-success-read',tool_name='read_file',receipt_fingerprint='a'*64))
        result=self.verify(self.observations(delivery=delivery,delivery_status='merged',shared_status='unknown'));pointer=result['verification'];content=self.api._linked_source(pointer)
        self.assertFalse(result['implementation_verified']);self.assertFalse(result['merge_authority']);self.assertTrue(result['delivery_complete'])
        originals=self.cancel_linked_members(cancel=(0,));self.assertEqual([t['state'] for t in originals],['cancelled','verifying'])
        contexts=tuple(self.api._evidence_context(f.scope) for f in self.members);refs=tuple(self.reference(f) for f in self.members)
        with patch.object(self.api,'_verify_member',side_effect=AssertionError('Historical lifecycle invoked fresh verification')), \
             patch.object(delegation,'_reserve_operation',side_effect=AssertionError('Historical lifecycle invented a verifier/barrier')):
            for f in self.members:state._retain_ready_stop(f.scope,self.stop_request(f,pointer))
            d4,request=self.recovery_fixtures[0];candidates=self.input_rows()
            applied=_run_d4_fixture(d4,request,'resume');self.assertEqual(applied['exit_code'],0,applied)
            self.assertEqual(self.input_rows(),candidates)
            _,source=self.recovery_head(d4,contexts[0])
            for context in contexts:
                self.assertEqual(self.recovery_head(d4,context)[1],source)
            authorities=self.api._canonical_plain(source['authorities'])
            self.assertEqual(sorted(authorities,key=self.api._digest),
                sorted([self.api._canonical_plain(c.authority_set[0]) for c in contexts],key=self.api._digest))
            self.assertTrue(all(any(item['reference']==ref for item in source['tasks']) for ref in refs))
            prepared=self.api._prepare_linked_closure(self.api._observe_linked_preparation(pointer,authorities));self.assertTrue(prepared['complete'])
            released=changes._register_recovery_release(changes._observe_recovery_release(authorities,dict(source['identity'])))
            self.assertTrue(released['complete'],released)
            recovery=changes.inspect_lifecycle_recovery(authorities,refs);self.assertTrue(recovery['complete'],recovery['blockers'])
            self.assertFalse(any(edge['need']=='raw' and edge['kind']=='task' and edge['reference'] in refs for edge in recovery['requirements']))
            closed=[]
            for index,ref in enumerate(refs):
                task=self.api.close_task(self.members[index].scope,self.linked_closure_request(index),self.api._observe_closure(contexts,ref))['task'];closed.append(task)
                for field in ('state','revision','pins','retirement'):
                    if field in originals[index]:self.assertEqual(task[field],originals[index][field])
            for index,(context,ref) in enumerate(zip(contexts,refs)):
                compact=self.api._read(None,closed[index]['lifecycle']['compact'],context=context)
                self.assertEqual(compact['stopped']['linked']['content'],content);self.assertEqual(compact['outcome'],originals[index]['state'])
                if index==0:
                    self.assertTrue(compact['native_guidance']);self.assertTrue(compact['workers']);self.assertEqual(compact['reviews'][0]['report']['findings'],[finding])
                    self.assertTrue(any(a['assessment']['dispositions']==assessment['dispositions'] for a in compact['reviews'][0]['assessments']))
                else:self.assertTrue(any(value['field']=='exit_code' and value['value']==7 for value in compact['numerical']))
                retired=self.api._retire_closed_task(context,ref);self.assertTrue(retired['retired']);self.assertEqual(retired['outcome'],originals[index]['state'])
                self.assertEqual(self.api._retire_closed_task(context,ref),retired)
                recovery=changes.inspect_lifecycle_recovery(authorities,refs);self.assertTrue(recovery['complete'],dict(member=index,blockers=recovery['blockers']))
                with self.api._context_database(context) as db:
                    marker=state._retired(db,'task',{key:ref[key] for key in ('scope_id','client','session_id','task_id')})
                    self.assertEqual(marker['created_at'],originals[index]['lifecycle']['created_at']);self.assertEqual(marker['outcome'],originals[index]['state'])
                    self.assertEqual(state._metadata(db,closed[index]['lifecycle']['compact']['name'])['closed_at'],closed[index]['lifecycle']['safe_closed_at'])
            for action in ('resume','rollback','rollback'):
                outcome=_run_d4_fixture(d4,request,action);self.assertEqual(outcome['exit_code'],0,outcome)
                recovery=changes.inspect_lifecycle_recovery(authorities,refs);self.assertTrue(recovery['complete'],dict(action=action,blockers=recovery['blockers']))
        self.assertEqual(self.api._linked_source(pointer),content)

    def test_linked_unknown_result_mixed_stopped_outcomes_preserve_actual_states(self):
        pointer,originals=self.non_success_cancelled_component(shared_status='unknown',cancel=(0,))
        for index,f in enumerate(self.members):
            stopped=state._retain_ready_stop(f.scope,self.stop_request(f,pointer))['task']
            self.assertEqual(stopped['state'],originals[index]['state']);self.assertEqual(stopped['revision'],originals[index]['revision'])
        self.assertEqual([self.task(f)['state'] for f in self.members],['cancelled','verifying'])

    def test_linked_failed_reconciled_local_check_acquires_stops_without_passing(self):
        f=self.members[1];plan=self.api._read(f.scope,self.task(f)['evidence']['plan'])
        plan['checks'][0]['argv']=[sys.executable,'-c','import sys; print("real failed result"); sys.exit(7)']
        self.api.plan_evidence(f.scope,f.request(plan=plan,change_decision_ref='user:accepted-failing-check-fixture'))
        failed=f.checked()['attempt'];self.assertEqual(failed['status'],'failed');self.assertEqual(failed['exit_code'],7)
        pointer,originals=self.non_success_cancelled_component(shared_status='passed')
        self.assertTrue(any('check' in message for message in self.api._linked_source(pointer)['blockers']))
        for index,member in enumerate(self.members):
            stopped=state._retain_ready_stop(member.scope,self.stop_request(member,pointer))['task']
            self.assertEqual(stopped['state'],originals[index]['state'])
        actual=next(a for a in self.task(f)['evidence']['attempts'] if a['id']==failed['id']);self.assertEqual(actual['status'],'failed');self.assertEqual(actual['exit_code'],7)

    def test_linked_missing_aggregate_complete_contracts_accept_independent_stops(self):
        observations=self.observations()
        observe=observations['observe']
        def absent(facts):
            observe(facts);raise RuntimeError('fixture: stopped before aggregate publication')
        observations['observe']=absent
        with self.assertRaisesRegex(RuntimeError,'before aggregate publication'):self.verify(observations)
        self.assertTrue(all('linked_verification' not in self.task(f)['evidence'] for f in self.members))
        originals=self.cancel_linked_members()
        observations=dict(members=[dict(scope=f.scope,request=f.request(purpose='completion')) for f in self.members],observe=observe)
        from runtime import delegation
        with patch.object(self.api,'_verify_member',side_effect=AssertionError('Absent aggregate caused verification')),patch.object(delegation,'_reserve_operation',side_effect=AssertionError('Absent aggregate created barrier')):
            captured=self.api._acquire_linked_basis(self.selected.scope,self.selected.request(purpose='completion'),observations)
        for index,f in enumerate(self.members):
            task=self.task(f);context=self.api._evidence_context(f.scope)
            with self.api._context_database(context) as db:bindings=state._ready_stop_bindings(context,db,task)
            plan=self.api._read(f.scope,task['evidence']['plan']);candidate=self.api.capture_candidate(f.scope,plan)
            proof=dict(version=2,kind='stopped-writer-reconciliation',identity=f.identity,expected_revision=task['revision'],expected_pins=task['pins'],
                observed_turn_id=task['turn_id'],stopped=True,descendants_stopped=True,attempt_ids=[a['id'] for a in task['evidence']['attempts']],
                observation_ref='fixture:independent-aggregate-absent-stop',coordinator_ref='fixture:host-checked',candidate_digest=self.api._digest(candidate),
                verification_digest=task['evidence']['verification']['digest'],linked_digest=self.api._digest(captured['basis']),**bindings)
            raw=json.dumps(proof).encode();path=f.root/'aggregate-absent-stop.json';path.write_bytes(raw);path.chmod(0o400)
            request=f.identity|dict(expected_revision=task['revision'],expected_pins=task['pins'],stop_proof=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest()))
            stopped=state._retain_ready_stop(f.scope,request,linked_basis=captured['reference'])['task'];self.assertEqual(stopped['state'],originals[index]['state'])

    def no_verifier_capture(self,observations=None):
        observations=observations or self.observations(shared_status='unknown');inputs=self.input_rows()
        plan=self.api._read(self.selected.scope,self.task(self.selected)['evidence']['plan'])
        projection=self.api._linked_projection(self.reference(self.selected),plan)
        acquired=observations['observe'](dict(projection=projection,projection_digest=self.api._digest(projection),inputs=inputs,inputs_digest=self.api._digest(inputs)))
        self.assertEqual(acquired['shared'][0]['status'],'unknown')
        originals=self.cancel_linked_members(tuple(range(len(self.members))))
        observations=dict(members=[dict(scope=f.scope,request=f.request(purpose='completion')) for f in self.members],observe=observations['observe'])
        from runtime import delegation
        for name,target in (('_verify_member',self.api),('_reserve_operation',delegation)):
            guard=patch.object(target,name,side_effect=AssertionError('No-verifier lifecycle executed verifier/barrier'));guard.start();self.addCleanup(guard.stop)
        captured=self.api._acquire_linked_basis(self.selected.scope,self.selected.request(purpose='completion'),observations)
        return captured,originals,observations

    def no_verifier_stop_request(self,f,captured,**updates):
        task=self.task(f);self.assertNotIn('verification',task['evidence']);context=self.api._evidence_context(f.scope)
        with self.api._context_database(context) as db:bindings=state._ready_stop_bindings(context,db,task)
        plan=self.api._read(f.scope,task['evidence']['plan']);candidate=self.api.capture_candidate(f.scope,plan)
        proof=dict(version=2,kind='stopped-writer-reconciliation',identity=f.identity,expected_revision=task['revision'],expected_pins=task['pins'],
            observed_turn_id=task['turn_id'],stopped=True,descendants_stopped=True,attempt_ids=[a['id'] for a in task['evidence']['attempts']],
            observation_ref='fixture:independent-no-verifier-stop',coordinator_ref='fixture:host-checked',candidate_digest=self.api._digest(candidate),
            verification_digest=None,linked_digest=self.api._digest(captured['basis']),**bindings)
        proof.update(updates)
        raw=json.dumps(proof).encode();path=f.root/('no-verifier-stop-'+hashlib.sha256(raw).hexdigest()+'.json');path.write_bytes(raw);path.chmod(0o400)
        return f.identity|dict(expected_revision=task['revision'],expected_pins=task['pins'],stop_proof=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest()))

    def no_verifier_stops(self,observations=None):
        captured,originals,_=self.no_verifier_capture(observations)
        for index,f in enumerate(self.members):
            stopped=state._retain_ready_stop(f.scope,self.no_verifier_stop_request(f,captured),linked_basis=captured['reference'])['task']
            self.assertEqual(stopped['state'],originals[index]['state'])
        contexts=tuple(self.api._evidence_context(f.scope) for f in self.members);refs=tuple(self.reference(f) for f in self.members)
        return captured,originals,contexts,refs

    def test_linked_factual_capture_requires_each_exact_stop_and_registered_common_root(self):
        captured,originals,observations=self.no_verifier_capture();root=captured['reference'];authorities=captured['basis']['authorities']
        self.assertEqual(self.api._acquire_linked_basis(self.selected.scope,self.selected.request(purpose='completion'),observations),captured)
        with self.assertRaises(StartupError):self.api._observe_linked_preparation(root,authorities)
        f=self.selected
        for invalid in (dict(descendants_stopped=False),dict(stopped=False),dict(attempt_ids=[]),dict(generation=captured['basis']['members'][0]['bindings']['generation']+1),
                dict(linked_digest='0'*64),dict(verification_digest='0'*64)):
            with self.subTest(invalid=invalid),self.assertRaises((StartupError,state.StateError)):
                state._retain_ready_stop(f.scope,self.no_verifier_stop_request(f,captured,**invalid),linked_basis=root)
            self.assertEqual([self.task(member) for member in self.members],originals)
        request=self.no_verifier_stop_request(f,captured)
        peer=self.members[1];body=self.api._linked_source(root)
        owner=self.api._LinkedOwner(self.api._artifact_owner(peer.scope,self.task(peer)),tuple(self.api._canonical_freeze(edge) for edge in self.api._linked_capture_dependencies(body)[1:]))
        forged=dict(authority=self.reference(peer)['authority'],reference=self.api._artifact(peer.scope,body,owner=owner))
        with self.assertRaises((StartupError,state.StateError)):
            state._retain_ready_stop(f.scope,request,linked_basis=forged)
        for wrong in (dict(authority=root['authority'],reference=dict(name='0'*64+'.json',digest='0'*64)),
                dict(authority=root['authority'],reference=self.task(f)['evidence']['plan'])):
            with self.subTest(root=wrong),self.assertRaises((StartupError,state.StateError)):
                state._retain_ready_stop(f.scope,request,linked_basis=wrong)
        stopped=state._retain_ready_stop(f.scope,request,linked_basis=root)['task'];first=dict(stopped['writer_stop'])
        self.assertEqual(state._retain_ready_stop(f.scope,request,linked_basis=root)['task'],stopped)
        with self.assertRaises(StartupError):self.api._observe_linked_preparation(root,authorities)
        local=dict(authority=root['authority'],reference=first['linked']);peer=self.members[1]
        with self.assertRaises((StartupError,state.StateError)):
            state._retain_ready_stop(peer.scope,self.no_verifier_stop_request(peer,captured),linked_basis=local)
        context=self.api._evidence_context(f.scope)
        with self.api._context_database(context) as db:
            before=state._metadata(db,root['reference']['name'])
        self.assertEqual(self.api._acquire_linked_basis(f.scope,f.request(purpose='completion'),observations),captured)
        with self.api._context_database(context) as db:self.assertEqual(state._metadata(db,root['reference']['name']),before)
        (peer.repo/'app.py').write_text('value = 987\n')
        with self.assertRaises((StartupError,state.StateError)):
            state._retain_ready_stop(peer.scope,self.no_verifier_stop_request(peer,captured),linked_basis=root)
        self.assertEqual(self.task(f)['writer_stop'],first);self.assertNotIn('writer_stop',self.task(peer))
        self.assertTrue(all(self.task(member)['lifecycle']['safe_closed_at'] is None for member in self.members))

    def test_linked_factual_capture_cannot_omit_approved_third_member_or_stop(self):
        from types import SimpleNamespace
        from tests.test_state import canonical_scope
        from tests.test_startup import CanonicalAcquisitionTests
        third=EvidenceTests(methodName='runTest');third.setUp();self.addCleanup(third.doCleanups)
        third.scope=canonical_scope(third.scope);state.start_task(third.scope,third.identity|dict(mode='editable',decision_ref='user:accepted'))
        record,path=CanonicalAcquisitionTests.record(SimpleNamespace(repo=third.repo,base=third.root,assertIsNone=self.assertIsNone))
        identity=self.api._canonical_plain(third.scope.accepted_identity);record['project_id']=identity['project_id']
        record['repositories'][0]['repository_id']=identity['repository_id'];record['repositories'][0]['checkouts'][0]['checkout_id']=identity['checkout_id']
        record['repositories'][0]['checkouts'][0]['clients'][0]['configuration'].update(identity['configuration'])
        path.write_text(json.dumps(record));self.members.append(third);self.establish()
        captured,originals,observations=self.no_verifier_capture();root=captured['reference'];authorities=captured['basis']['authorities']
        with self.assertRaises(StartupError):self.api._acquire_linked_basis(self.selected.scope,self.selected.request(purpose='completion'),dict(observations,members=observations['members'][:2]))
        for f in self.members[:2]:state._retain_ready_stop(f.scope,self.no_verifier_stop_request(f,captured),linked_basis=root)
        with self.assertRaises(StartupError):self.api._observe_linked_preparation(root,authorities[:2])
        state._retain_ready_stop(third.scope,self.no_verifier_stop_request(third,captured),linked_basis=root)
        observed=self.api._observe_linked_preparation(root,authorities[:2]);self.assertEqual(len(observed.facts['members']),3)
        self.assertEqual(len(self.api._prepare_linked_closure(observed)['preparations']),3)
        for f,original in zip(self.members,originals):
            for key in ('state','revision','pins','lifecycle'):self.assertEqual(self.task(f)[key],original[key])

    def test_linked_factual_stops_never_withdraw_required_open_unknown_or_wrong_head_delivery(self):
        delivery=dict(provider='fixture',repository='owner/repo',target='main',pull_request='fixture:required-non-success')
        for status in ('open','unknown','wrong-head'):
            with self.subTest(status=status):
                scenario=LinkedVerificationTests(methodName='runTest');scenario.setUp();self.addCleanup(scenario.doCleanups);scenario.establish(delivery)
                observations=scenario.observations(delivery=delivery,delivery_status='merged' if status=='wrong-head' else status,shared_status='unknown')
                if status=='wrong-head':
                    acquired=observations['observe'](dict(inputs_digest=scenario.api._digest(scenario.input_rows())))
                    original=acquired['deliveries'][0];body=scenario.api._linked_source(original['source']);body['revision']='0'*40
                    source=scenario.retained(scenario.selected,body);acquired['deliveries']=[dict(original,revision='0'*40,source=source)]
                    observations['observe']=lambda facts,value=acquired:value
                captured,originals,_,_=scenario.no_verifier_stops(observations)
                self.assertFalse(captured['basis']['delivery_complete'])
                with self.assertRaises(StartupError):scenario.api._observe_linked_preparation(captured['reference'],captured['basis']['authorities'])
                for f,original in zip(scenario.members,originals):
                    for key in ('state','revision','pins','lifecycle'):self.assertEqual(scenario.task(f)[key],original[key])
                    self.assertNotEqual(scenario.task(f)['state'],'ready')
                scenario.doCleanups()

    def test_linked_no_aggregate_or_verifier_complete_stops_preserve_unknown_result(self):
        captured,originals,contexts,refs=self.no_verifier_stops()
        prepared=self.api._prepare_linked_closure(self.api._observe_linked_preparation(captured['reference'],captured['basis']['authorities']))
        self.assertTrue(prepared['complete']);closed=[]
        for index,ref in enumerate(refs):
            task=self.api.close_task(self.members[index].scope,self.linked_closure_request(index),self.api._observe_closure(contexts,ref))['task'];closed.append(task)
            self.assertEqual(task['state'],originals[index]['state']);self.assertEqual(task['revision'],originals[index]['revision'])
        for index,(context,ref) in enumerate(zip(contexts,refs)):
            compact=self.api._read(None,closed[index]['lifecycle']['compact'],context=context)
            self.assertIsNone(compact['component']['aggregate'] if 'component' in compact else compact['stopped']['linked']['aggregate'])
            self.assertIsNone(compact['stopped']['writer_stop']['verification']);self.assertEqual(compact['verifications'],[])
            self.assertTrue(self.api._retire_closed_task(context,ref)['retired'])
            with self.api._context_database(context) as db:
                marker=state._retired(db,'task',{key:ref[key] for key in ('scope_id','client','session_id','task_id')})
                self.assertEqual(marker['outcome'],originals[index]['state']);self.assertEqual(marker['created_at'],originals[index]['lifecycle']['created_at'])

    def existing_aggregate_cannot_become_absent(self,*,historical=False):
        result=self.verify(self.observations(shared_status='failed'));pointer=result['verification'];original=self.api._linked_source(pointer)
        self.assertFalse(result['implementation_verified'])
        if historical:
            f=self.selected;plan=self.api._read(f.scope,self.task(f)['evidence']['plan'])
            self.api.plan_evidence(f.scope,f.request(plan=plan,change_decision_ref='user:actual-plan-history'))
            self.assertNotIn('linked_verification',self.task(f)['evidence'])
            self.assertEqual(self.api._linked_source(pointer),original)
        self.cancel_linked_members();observations=self.observations(shared_status='unknown')
        before=[self.task(f) for f in self.members]
        with self.assertRaisesRegex(StartupError,'aggregate requires its actual v1 lifecycle source'):
            self.api._acquire_linked_basis(self.selected.scope,self.selected.request(purpose='completion'),observations)
        self.assertEqual([self.task(f) for f in self.members],before);self.assertEqual(self.api._linked_source(pointer),original)

    def test_linked_existing_failed_aggregate_is_not_nulled(self):self.existing_aggregate_cannot_become_absent()

    def test_linked_historical_failed_aggregate_is_not_nulled(self):self.existing_aggregate_cannot_become_absent(historical=True)

    def test_linked_no_verifier_native_history_survives_d4_retirement_and_guidance(self):
        from runtime import changes,delegation
        finding=dict(id='unverified-optional',severity='info',scope='general',status='optional',location='app.py:1',
            scenario='Actual optional historical suggestion',evidence='Original fixture report',counterevidence='No acceptance claim')
        reviewed=self.selected.review(findings=[finding]);task=self.task(self.selected)
        review=next(a for a in task['evidence']['attempts'] if a['id']==reviewed['attempt_id']);assessment=self.api._read(self.selected.scope,review['assessment'])['assessment']
        assessment['dispositions']=[dict(finding_id=finding['id'],status='accepted',reference='user:optional-result-retained')]
        self.api.assess_review(self.selected.scope,self.selected.request(attempt_id=reviewed['attempt_id'],assessment=assessment))
        captured,originals,contexts,refs=self.no_verifier_stops();root=captured['reference']
        d4,request=self.recovery_fixtures[0];candidates=self.input_rows()
        applied=_run_d4_fixture(d4,request,'resume');self.assertEqual(applied['exit_code'],0,applied)
        self.assertEqual(self.input_rows(),candidates)
        _,source=self.recovery_head(d4,contexts[0])
        for context in contexts:
            self.assertEqual(self.recovery_head(d4,context)[1],source)
        authorities=self.api._canonical_plain(source['authorities'])
        self.assertEqual(sorted(authorities,key=self.api._digest),
            sorted([self.api._canonical_plain(c.authority_set[0]) for c in contexts],key=self.api._digest))
        self.assertTrue(all(any(item['reference']==ref for item in source['tasks']) for ref in refs))
        prepared=self.api._prepare_linked_closure(self.api._observe_linked_preparation(root,authorities));self.assertTrue(prepared['complete'])
        released=changes._register_recovery_release(changes._observe_recovery_release(authorities,dict(source['identity'])))
        self.assertTrue(released['complete'],released)
        recovery=changes.inspect_lifecycle_recovery(authorities,refs);self.assertTrue(recovery['complete'],recovery['blockers'])
        self.assertFalse(any(edge['kind']=='task' and edge['reference'] in refs and edge['need']=='raw' for edge in recovery['requirements']))
        closed=[]
        for index,ref in enumerate(refs):closed.append(self.api.close_task(self.members[index].scope,self.linked_closure_request(index),self.api._observe_closure(contexts,ref))['task'])
        for index,(context,ref) in enumerate(zip(contexts,refs)):
            compact=self.api._read(None,closed[index]['lifecycle']['compact'],context=context)
            self.assertEqual(compact['verifications'],[]);self.assertIsNone(compact['stopped']['linked']['aggregate'])
            self.assertIsNone(compact['stopped']['writer_stop']['verification']);self.assertEqual(compact['outcome'],originals[index]['state'])
            if index==0:
                self.assertTrue(compact['native_guidance']);self.assertTrue(compact['workers']);self.assertEqual(compact['reviews'][0]['report']['findings'],[finding])
                self.assertTrue(any(a['assessment']['dispositions']==assessment['dispositions'] for a in compact['reviews'][0]['assessments']))
            retired=self.api._retire_closed_task(context,ref);self.assertTrue(retired['retired']);self.assertEqual(self.api._retire_closed_task(context,ref),retired)
            recovery=changes.inspect_lifecycle_recovery(authorities,refs);self.assertTrue(recovery['complete'],dict(member=index,blockers=recovery['blockers']))
            with self.api._context_database(context) as db:
                marker=state._retired(db,'task',{key:ref[key] for key in ('scope_id','client','session_id','task_id')})
                self.assertEqual(marker['created_at'],originals[index]['lifecycle']['created_at']);self.assertEqual(marker['outcome'],originals[index]['state'])
                guidance=delegation._closure_guidance(context,db,delegation._ledger(None,db,context=context));self.assertEqual(len(guidance['retained']),1)
                if index==0:self.assertTrue(guidance['sources'])
        for action in ('resume','rollback','rollback'):
            outcome=_run_d4_fixture(d4,request,action);self.assertEqual(outcome['exit_code'],0,outcome)
            recovery=changes.inspect_lifecycle_recovery(authorities,refs);self.assertTrue(recovery['complete'],dict(action=action,blockers=recovery['blockers']))

    def test_linked_stop_actual_selected_ready_and_peer_verifying_issue_exact_certificates(self):
        from runtime import changes
        result=self.verify();pointer=result['verification']
        originals=[self.task(f) for f in self.members]
        self.assertEqual([t['state'] for t in originals],['ready','verifying'])
        for f,original in zip(self.members,originals):
            stopped=state._retain_ready_stop(f.scope,self.stop_request(f,pointer))['task']
            for key in ('state','revision','pins','lifecycle'):self.assertEqual(stopped[key],original[key])
            context=self.api._evidence_context(f.scope);ref=self.reference(f)
            with self.api._context_database(context) as db:
                certificate=changes._stopped_certificate(context,db,dict(reference=ref,pins=stopped['pins']))
                self.assertEqual(certificate['state'],original['state'])
                changes._check_stopped_certificate(context,db,certificate)
            with self.assertRaises(StartupError):self.api._observe_closure((context,),ref)
            if f is self.selected:
                peer=self.members[1];peer_context=self.api._evidence_context(peer.scope)
                with self.api._context_database(peer_context) as db,self.assertRaises(StartupError):
                    changes._stopped_certificate(peer_context,db,dict(reference=self.reference(peer),pins=self.task(peer)['pins']))

    def test_linked_stop_d4_reads_certificates_but_preserves_complete_raw_routes(self):
        from runtime import changes,onboarding
        from tests.test_changes import ScopedChangesTests
        from tests.test_state import canonical_scope
        pointer=self.verify()['verification']
        extra=EvidenceTests(methodName='runTest');extra.setUp();self.addCleanup(extra.doCleanups)
        extra.scope=canonical_scope(extra.scope);state.start_task(extra.scope,extra.identity|dict(mode='editable',decision_ref='user:accepted'))
        contexts=tuple(self.api._evidence_context(f.scope) for f in [*self.members,extra])
        refs=tuple(self.reference(f) for f in self.members)
        d4=ScopedChangesTests(methodName='runTest');d4.setUp();self.addCleanup(d4.doCleanups)
        request=d4.scoped_request()
        for repository in request['manifest']['enrollment']['record']['repositories']:
            for checkout in repository['checkouts']:checkout['clients'][0]['configuration']['runtime']=dict(schema_version=3,state_dir=str(contexts[0].directory))
        request['approval']['manifest_digest']=onboarding._digest(request['manifest'])
        self.assertEqual(changes._run_scoped(d4.directory,request,'apply')['exit_code'],0)
        source=changes._observe_recovery_source(d4.directory,changes._load_journal(d4.directory),contexts,refs)
        for context in contexts:
            with self.api._context_database(context,write=True) as db:self.api._register_recovery_source(None,db,source,context=context)
        for f in self.members:
            stopped=state._retain_ready_stop(f.scope,self.stop_request(f,pointer))['task']
            basis=self.api._read(f.scope,stopped['writer_stop']['linked'])
            self.assertIn(self.reference(extra)['authority'],basis['authorities'])
        released=changes._register_recovery_release(changes._observe_recovery_release(source.content['authorities'],dict(source.content['identity'])))
        self.assertTrue(released['complete'],released)
        inspected=changes.inspect_lifecycle_recovery(source.content['authorities'],refs)
        self.assertTrue(inspected['complete'],inspected)
        for ref in refs:self.assertTrue(any(r['kind']=='task' and r['reference']==ref and r['need']=='raw' for r in inspected['requirements']))
        for context,ref in zip(contexts,refs):
            with self.assertRaises(StartupError):self.api._observe_closure((context,),ref)

    def test_linked_stop_incomplete_independent_proof_never_stops_any_member(self):
        pointer=self.verify()['verification'];f=self.members[1]
        for delta in (dict(descendants_stopped=False),dict(stopped=False),dict(attempt_ids=[]),dict(assignments_digest='f'*64),
            dict(task_digest='f'*64),dict(linked_digest='f'*64),dict(verification_digest='f'*64),dict(expected_revision=1)):
            with self.subTest(delta=delta),self.assertRaises(StartupError):state._retain_ready_stop(f.scope,self.stop_request(f,pointer,**delta))
        for member in self.members:self.assertNotIn('writer_stop',self.task(member))

    def test_linked_stop_exact_replay_keeps_original_ages_and_immutable_envelope(self):
        pointer=self.verify()['verification'];requests=[]
        for f in self.members:
            request=self.stop_request(f,pointer);requests.append(request);state._retain_ready_stop(f.scope,request)
        for f,request in zip(self.members,requests):
            original=self.task(f);Path(request['stop_proof']['path']).unlink()
            with patch.object(self.api,'_artifact',side_effect=AssertionError('Stop replay wrote support')),patch.object(self.api,'_read_host_proof',side_effect=AssertionError('Stop replay reread host authority')):
                replay=state._retain_ready_stop(f.scope,request)
            self.assertTrue(replay['replayed']);self.assertEqual(replay['task'],original)
            with state._database(f.scope,write=True) as db,self.assertRaises(StartupError):
                changed=json.loads(json.dumps(original));changed['writer_stop'].pop('linked');state._save(db,state._scope_id(f.scope),changed)

    def test_linked_stop_wrong_aggregate_reference_cannot_replace_actual_publication(self):
        pointer=self.verify()['verification'];context=self.api._evidence_context(self.selected.scope)
        content=self.api._linked_source(pointer)
        with self.api._context_database(context) as db:metadata=state._metadata(db,pointer['reference']['name'])
        owner=self.api._LinkedOwner(self.api._artifact_owner(self.selected.scope,self.task(self.selected)),
            tuple(self.api._canonical_freeze(edge) for edge in metadata['dependencies'][1:]))
        clone=dict(authority=pointer['authority'],reference=self.api._artifact(self.selected.scope,content,owner=owner))
        with self.assertRaisesRegex(StartupError,'selected original publication'):self.stop_request(self.members[1],clone)

    def test_linked_stop_peer_revision_generation_plan_and_source_changes_are_protected(self):
        for mutation in ('revision','generation','plan','source'):
            with self.subTest(mutation=mutation):
                scenario=LinkedVerificationTests(methodName='runTest');scenario.setUp()
                try:
                    pointer=scenario.verify()['verification'];f=scenario.selected;peer=scenario.members[1]
                    request=scenario.stop_request(f,pointer)
                    if mutation=='source':(peer.repo/'app.py').write_text('changed linked member source')
                    elif mutation=='plan':
                        plan=scenario.api._read(peer.scope,scenario.task(peer)['evidence']['plan']);plan['linked']['acceptance'][0]['text']='Divergent approved scope'
                        scenario.api.plan_evidence(peer.scope,peer.request(plan=plan,change_decision_ref='fixture:changed-linked-contract'))
                    else:
                        with state._database(peer.scope,write=True) as db:
                            if mutation=='generation':db.execute('update checkouts set generation=generation+1')
                            else:
                                task=scenario.task(peer);task['revision']+=1;state._save(db,state._scope_id(peer.scope),task)
                    with self.assertRaises(StartupError):state._retain_ready_stop(f.scope,request)
                    self.assertNotIn('writer_stop',scenario.task(f))
                finally:scenario.doCleanups()

    def test_linked_stop_late_foreign_input_rolls_back_original_owner(self):
        pointer=self.verify()['verification'];f=self.selected;peer=self.members[1];request=self.stop_request(f,pointer)
        original=self.api._artifact;before=self.task(f)
        def mutate(scope,value,**kwargs):
            result=original(scope,value,**kwargs)
            if value.get('kind')=='linked-complete-stop':(peer.repo/'late-linked-input.py').write_text('late foreign input')
            return result
        with patch.object(self.api,'_artifact',side_effect=mutate),self.assertRaises(StartupError):state._retain_ready_stop(f.scope,request)
        self.assertEqual(self.task(f),before)

    def test_linked_stop_cancelled_peer_preserves_exact_original_predecessor(self):
        pointer=self.verify()['verification'];peer=self.members[1];task=self.task(peer)
        proof=dict(version=1,kind='stopped-writer-reconciliation',identity=peer.identity,expected_revision=task['revision'],expected_pins=task['pins'],
            observed_turn_id=task['turn_id'],stopped=True,descendants_stopped=True,attempt_ids=[],observation_ref='fixture:cancelled-linked-peer',coordinator_ref='fixture:independent')
        raw=json.dumps(proof).encode();path=peer.root/'linked-cancel.json';path.write_bytes(raw);path.chmod(0o400)
        cancelled=state.retire_task(peer.scope,peer.request(expected_pins=task['pins'],reason='Cancelled linked peer',reference='fixture:cancel',
            stop_proof=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest())))['task']
        for f in (peer,self.selected):
            stopped=state._retain_ready_stop(f.scope,self.stop_request(f,pointer))['task']
            if f is peer:
                for key in ('state','revision','retirement','pins','lifecycle'):self.assertEqual(stopped[key],cancelled[key])
                context=self.api._evidence_context(f.scope)
                from runtime import changes
                with self.api._context_database(context) as db:
                    certificate=changes._stopped_certificate(context,db,dict(reference=self.reference(f),pins=stopped['pins']))
                    self.assertEqual(certificate['state'],'cancelled');changes._check_stopped_certificate(context,db,certificate)
        contexts=tuple(self.api._evidence_context(f.scope) for f in self.members);refs=tuple(self.reference(f) for f in self.members)
        authorities=[self.api._canonical_plain(context.authority_set[0]) for context in contexts]
        prepared=self.api._prepare_linked_closure(self.api._observe_linked_preparation(pointer,authorities));self.assertTrue(prepared['complete'])
        original=[self.task(f) for f in self.members];raw=self.raw_rows(contexts)
        for index in (1,0):
            closed=self.api.close_task(self.members[index].scope,self.linked_closure_request(index),self.api._observe_closure(contexts,refs[index]))['task']
            self.assertEqual({key:value for key,value in closed.items() if key!='lifecycle'},{key:value for key,value in original[index].items() if key!='lifecycle'})
            self.assertEqual(closed['lifecycle']['created_at'],original[index]['lifecycle']['created_at']);self.assertIsNotNone(closed['lifecycle']['safe_closed_at'])
        self.assertEqual(self.task(peer)['retirement'],cancelled['retirement']);self.assertEqual(self.task(peer)['state'],'cancelled')
        for before,after in zip(raw,self.raw_rows(contexts)):
            self.assertEqual({key:value for key,value in before.items() if key!='tasks'},{key:value for key,value in after.items() if key!='tasks'})
        for context,ref in zip(contexts,refs):
            historical=self.api._observe_closure(contexts,ref)
            with self.api._context_database(context,write=True) as db,self.assertRaises(StartupError):state.retire_closed(db,ref,historical)
        published=[self.task(f) for f in self.members]
        for index,(context,ref) in enumerate(zip(contexts,refs)):
            result=self.api._retire_closed_task(context,ref);self.assertTrue(result['retired']);self.assertEqual(result['outcome'],published[index]['state'])
            with self.api._context_database(context) as db:
                marker=state._retired(db,'task',{key:ref[key] for key in ('scope_id','client','session_id','task_id')})
                self.assertEqual(marker['outcome'],published[index]['state']);self.assertEqual(marker['created_at'],published[index]['lifecycle']['created_at'])
                self.assertEqual(state._metadata(db,published[index]['lifecycle']['compact']['name'])['closed_at'],published[index]['lifecycle']['safe_closed_at'])
                compact=self.api._read(None,published[index]['lifecycle']['compact'],context=context,db=db)
                if index==1:self.assertEqual(compact['stopped']['retirement'],cancelled['retirement']);self.assertEqual(compact['outcome'],'cancelled')
            self.assertEqual(self.api._retire_closed_task(context,ref),result)

    def test_linked_stop_open_delivery_does_not_claim_delivery_or_closure(self):
        delivery=dict(provider='fixture',repository='owner/repo',target='main',pull_request='fixture:pull1')
        self.establish(delivery);result=self.verify(self.observations(delivery=delivery,delivery_status='open'))
        self.assertFalse(result['delivery_complete'])
        for f in self.members:
            stopped=state._retain_ready_stop(f.scope,self.stop_request(f,result['verification']))
            self.assertNotIn('delivery_complete',stopped);self.assertNotIn('implementation_verified',stopped)
            linked=self.api._read(f.scope,stopped['task']['writer_stop']['linked'])
            self.assertFalse(linked['delivery_complete']);self.assertIsNone(stopped['task']['lifecycle']['safe_closed_at'])

    def test_linked_stop_missing_actual_synchronous_barrier_stays_protected(self):
        from runtime import delegation
        pointer=self.verify()['verification'];peer=self.members[1]
        with state._database(peer.scope,write=True) as db:
            record=next(r for r in delegation._ledger(peer.scope,db) if r['data']['role']=='coordinator')
            db.execute('delete from assignments where id=?',(record['id'],))
        with self.assertRaises(StartupError):state._retain_ready_stop(peer.scope,self.stop_request(peer,pointer))

    def test_linked_stop_three_approved_members_cannot_be_truncated(self):
        from types import SimpleNamespace
        from tests.test_state import canonical_scope
        from tests.test_startup import CanonicalAcquisitionTests
        third=EvidenceTests(methodName='runTest');third.setUp();self.addCleanup(third.doCleanups)
        third.scope=canonical_scope(third.scope)
        state.start_task(third.scope,third.identity|dict(mode='editable',decision_ref='user:accepted'))
        record,path=CanonicalAcquisitionTests.record(SimpleNamespace(repo=third.repo,base=third.root,assertIsNone=self.assertIsNone))
        identity=self.api._canonical_plain(third.scope.accepted_identity);record['project_id']=identity['project_id']
        record['repositories'][0]['repository_id']=identity['repository_id'];record['repositories'][0]['checkouts'][0]['checkout_id']=identity['checkout_id']
        record['repositories'][0]['checkouts'][0]['clients'][0]['configuration'].update(identity['configuration'])
        path.write_text(json.dumps(record));self.members.append(third);self.establish()
        pointer=self.verify()['verification'];content=self.api._linked_source(pointer)
        self.assertEqual(len(content['members']),3)
        task=state._retain_ready_stop(third.scope,self.stop_request(third,pointer))['task']
        self.assertEqual(task['state'],'verifying')
        incomplete=json.loads(json.dumps(content));incomplete['members'].pop()
        clone=self.retained(self.selected,incomplete)
        with self.assertRaisesRegex(StartupError,'participant set is incomplete'):self.stop_request(self.selected,clone)

    def test_linked_stop_foreign_semantic_source_is_guarded_and_retains_raw_dependency(self):
        from tests.test_state import canonical_scope
        from runtime import delegation
        extra=EvidenceTests(methodName='runTest');extra.setUp();self.addCleanup(extra.doCleanups)
        extra.scope=canonical_scope(extra.scope);state.start_task(extra.scope,extra.identity|dict(mode='editable',decision_ref='user:accepted'))
        observations=self.observations();observe=observations['observe']
        source=self.retained(extra,dict(version=1,kind='linked-integration-observation',inputs_digest=self.api._digest(self.input_rows()),
            criteria=dict(together='passed'),observed_at=101,reference='fixture:independent foreign semantic source'))
        def acquire(facts):
            acquired=observe(facts);acquired['shared'][0]['evidence']=[source];return acquired
        observations['observe']=acquire;pointer=self.verify(observations)['verification'];original=self.api._linked_source;guarded=[]
        def read(reference,**kwargs):
            if reference==source:
                with self.assertRaises(StartupError):
                    with delegation._reservation_write(extra.scope):pass
                guarded.append(True)
            return original(reference,**kwargs)
        with patch.object(self.api,'_linked_source',side_effect=read):
            result=state._retain_ready_stop(self.selected.scope,self.stop_request(self.selected,pointer))
        self.assertTrue(guarded)
        basis=self.api._read(self.selected.scope,result['task']['writer_stop']['linked'])
        self.assertIn(source['authority'],basis['authorities'])
        entry=next(s for s in basis['sources'] if s['reference']==source)
        self.assertTrue(any(e['kind']=='task' and e['reference']==self.reference(extra) for e in entry['metadata']['dependencies']))

    def test_linked_stop_stale_foreign_source_cannot_supply_live_certificate(self):
        from runtime import changes
        pointer=self.verify()['verification']
        for f in self.members:state._retain_ready_stop(f.scope,self.stop_request(f,pointer))
        f=self.selected;context=self.api._evidence_context(f.scope);task=self.task(f)
        with self.api._context_database(context) as db:
            certificate=changes._stopped_certificate(context,db,dict(reference=self.reference(f),pins=task['pins']))
        (self.members[1].repo/'app.py').write_text('changed foreign source after both independent stops')
        with self.api._context_database(context) as db,self.assertRaises(StartupError):changes._check_stopped_certificate(context,db,certificate)
        self.assertEqual(self.task(f),task)

    def test_linked_stop_shared_authority_qualifies_scope_with_identical_local_ids(self):
        from tests import test_state
        from runtime import changes
        shared=tempfile.TemporaryDirectory(prefix='linked-stop-shared-');self.addCleanup(shared.cleanup)
        canonical=test_state.canonical_scope;count=[0]
        def scope(legacy,**kwargs):
            number=count[0];count[0]+=1
            legacy=replace(legacy,runtime=RuntimeSettings(2,Path(shared.name).resolve()/'state'))
            return canonical(legacy,repository_id='repository-'+str(number),checkout_id='checkout-'+str(number),**kwargs)
        scenario=LinkedVerificationTests(methodName='runTest')
        with patch.object(test_state,'canonical_scope',side_effect=scope):scenario.setUp()
        self.addCleanup(scenario.doCleanups)
        self.assertEqual(scenario.reference(scenario.members[0])['authority'],scenario.reference(scenario.members[1])['authority'])
        pointer=scenario.verify()['verification']
        for f in scenario.members:
            before=scenario.task(f);stopped=state._retain_ready_stop(f.scope,scenario.stop_request(f,pointer))['task']
            for key in ('state','revision','pins','lifecycle'):self.assertEqual(stopped[key],before[key])
            context=self.api._evidence_context(f.scope);ref=scenario.reference(f)
            with self.api._context_database(context) as db:
                certificate=changes._stopped_certificate(context,db,dict(reference=ref,pins=stopped['pins']))
                changes._check_stopped_certificate(context,db,certificate)
            candidate=self.api._read(f.scope,stopped['writer_stop']['candidate'])
            self.assertEqual(self.api._ready_stop_candidate(context,stopped,candidate),stopped['writer_stop']['inputs'])
            self.assertIn(str(f.repo),stopped['writer_stop']['inputs'])

    def test_linked_stop_late_accepted_umbrella_replacement_rejects_preserved_child_inodes(self):
        from types import SimpleNamespace
        from tests.test_state import canonical_scope
        from tests.test_startup import CanonicalAcquisitionTests
        scenario=LinkedVerificationTests(methodName='runTest');scenario.api=self.api;scenario.members=[];projects={}
        for number in range(2):
            f=EvidenceTests(methodName='runTest');f.setUp();self.addCleanup(f.doCleanups)
            project=f.root/'umbrella';project.mkdir();primary=project/'primary';f.repo.rename(primary);linked=f.root/'linked'
            subprocess.run(['git','-C',str(primary),'worktree','add','--detach',str(linked)],check=True,capture_output=True)
            f.repo=linked;legacy=replace(f.scope,repository_root=linked,git_common_dir=primary/'.git')
            scope=canonical_scope(legacy,primary_root=primary,git_dir=primary/'.git/worktrees/linked')
            identity=self.api._canonical_plain(scope.accepted_identity);info=project.stat()
            identity.update(project_root=str(project),project_binding=dict(device=info.st_dev,inode=info.st_ino))
            f.scope=replace(scope,project_root=project,authority_path=project/state.PROJECT_FILE,
                accepted_identity=self.api._canonical_freeze(identity),accepted_scope_digest=self.api._digest(identity))
            state.start_task(f.scope,f.identity|dict(mode='editable',decision_ref='user:accepted'))
            record,path=CanonicalAcquisitionTests.record(SimpleNamespace(repo=linked,base=f.root,assertIsNone=self.assertIsNone),project=project,selected=linked)
            record['project_id']=identity['project_id'];record['repositories'][0]['repository_id']=identity['repository_id']
            record['repositories'][0]['checkouts'][0]['checkout_id']=identity['checkout_id']
            record['repositories'][0]['checkouts'][0]['clients'][0]['configuration'].update(identity['configuration'])
            path.write_text(json.dumps(record));scenario.members.append(f);projects[str(linked)]=project
        scenario.selected=scenario.members[0];scenario.establish();pointer=scenario.verify()['verification'];f=scenario.selected
        request=scenario.stop_request(f,pointer);before=scenario.task(f)
        artifact=self.api._artifact;basis=self.api._linked_stop_basis;files=self.api._stop_input_files
        phase=dict(armed=False,captures=0,active=0,moved=False)
        def arm(scope,value,**kwargs):
            result=artifact(scope,value,**kwargs)
            if value.get('kind')=='linked-complete-stop':phase['armed']=True
            return result
        def capture(*args,**kwargs):
            if phase['armed']:phase['captures']+=1;phase['active']=phase['captures']
            try:return basis(*args,**kwargs)
            finally:phase['active']=0
        def move(task,candidate):
            if phase['active']==2 and not phase['moved'] and task['accepted_identity']['repository_root']==str(f.repo):
                project=projects[str(f.repo)];previous=project.with_name('old-umbrella');project.rename(previous);project.mkdir()
                for child in list(previous.iterdir()):child.rename(project/child.name)
                phase['moved']=True
            return files(task,candidate)
        with patch.object(self.api,'_artifact',side_effect=arm),patch.object(self.api,'_linked_stop_basis',side_effect=capture), \
                patch.object(self.api,'_stop_input_files',side_effect=move),self.assertRaises(StartupError):
            state._retain_ready_stop(f.scope,request)
        self.assertTrue(phase['moved']);self.assertEqual(scenario.task(f),before)

    def preparation_fixture(self, *, delivery=None, delivery_status='merged', stopped=True):
        from types import SimpleNamespace
        if delivery is not None:self.establish(delivery)
        from runtime.engine import RuntimeEvent
        for f in self.members:
            for kind in ('PreToolUse','PostToolUse'):
                state.process_event(f.scope,RuntimeEvent(kind,'codex','parent',f.repo,turn_id='turn',tool_call_id='preparation-read',tool_name='read_file',receipt_fingerprint='a'*64))
        pointer=self.verify(self.observations(delivery=delivery,delivery_status=delivery_status))['verification']
        contexts=tuple(self.api._evidence_context(f.scope) for f in self.members);refs=tuple(self.reference(f) for f in self.members)
        if stopped:
            for f in self.members:state._retain_ready_stop(f.scope,self.stop_request(f,pointer))
        d4,request=self.recovery_fixtures[0]
        applied=_run_d4_fixture(d4,request,'resume');self.assertEqual(applied['exit_code'],0,applied)
        _,content=self.recovery_head(d4,contexts[0])
        for context in contexts:self.assertEqual(self.recovery_head(d4,context)[1],content)
        self.assertTrue(all(any(row['reference']==ref for row in content['tasks']) for ref in refs))
        source=SimpleNamespace(content=self.api._canonical_freeze(content))
        return pointer,d4,source,contexts,refs

    def raw_rows(self,contexts):
        result=[]
        for context in contexts:
            with self.api._context_database(context) as db:
                result.append({name:db.execute('select * from '+name+' order by rowid').fetchall() for name in ('tasks','assignments','turns','receipts','bindings','retired_identities')})
        return result

    def test_linked_preparation_compacts_precede_d4_cut_without_closure_or_raw_retirement(self):
        from runtime import changes
        delivery=dict(provider='fixture',repository='owner/repo',target='main',pull_request='fixture:required')
        pointer,_,source,contexts,refs=self.preparation_fixture(delivery=delivery)
        profile={};phase=['observe-preparation']
        for name in ('_linked_preparation_facts','_linked_stop_basis'):
            original=getattr(self.api,name)
            def counted(*args,_original=original,_name=name,**kwargs):
                start=time.monotonic();result=_original(*args,**kwargs)
                row=profile.setdefault(phase[0],{}).setdefault(_name,dict(count=0,seconds=0,digests=set()))
                row['count']+=1;row['seconds']+=time.monotonic()-start;row['digests'].add(self.api._digest(result));return result
            patcher=patch.object(self.api,name,side_effect=counted);patcher.start();self.addCleanup(patcher.stop)
        before=self.raw_rows(contexts);tasks=[self.task(f) for f in self.members]
        self.assertTrue(all(rows['turns'] and rows['receipts'] for rows in before))
        observed=self.api._observe_linked_preparation(pointer,self.api._canonical_plain(source.content['authorities']))
        phase[0]='prepare-compacts';prepared=self.api._prepare_linked_closure(observed)
        self.assertTrue(prepared['complete']);self.assertEqual(len(prepared['preparations']),len(refs))
        for f,original in zip(self.members,tasks):
            receipt=next(row for row in prepared['preparations'] if row['task']==self.reference(f))
            compact=self.api._linked_source(dict(authority=receipt['reference']['authority'],reference=receipt['reference']['artifact']))
            self.assertEqual(compact['outcome'],original['state']);self.assertEqual(compact['created_at'],original['lifecycle']['created_at'])
            self.assertTrue(compact['numerical']);self.assertTrue(compact['verifications']);self.assertEqual(compact['usage'],'unknown')
            ctx=self.api._evidence_context(f.scope)
            for number in compact['numerical']:
                attempt=next(a for a in original['evidence']['attempts'] if a['id']==number['assignment_id'])
                with self.api._context_database(ctx) as db:age=state._metadata(db,attempt['execution']['name'])['created_at']
                self.assertEqual(number['value'],attempt[number['field']]);self.assertEqual(number['created_at'],age)
                self.assertEqual(number['source'],attempt['execution'])
                self.assertEqual(number['unit'],{'exit_code':'exit-code','output_bytes':'bytes'}[number['field']])
            self.assertEqual(self.task(f),original)
        phase[0]='observe-d4-release';release=changes._observe_recovery_release(source.content['authorities'],dict(source.content['identity']))
        phase[0]='register-d4-release';released=changes._register_recovery_release(release)
        self.assertTrue(released['complete'],released)
        phase[0]='inspect-own-release';inspected=changes.inspect_lifecycle_recovery(source.content['authorities'],refs)
        self.assertTrue(inspected['complete'],inspected)
        self.assertFalse(any(r['kind']=='task' and r['reference'] in refs and r['need']=='raw' for r in inspected['requirements']))
        self.assertEqual(self.raw_rows(contexts),before)
        phase[0]='independent-recovery-root'
        from tests.test_changes import ScopedChangesTests
        from runtime import onboarding
        other=ScopedChangesTests(methodName='runTest');other.setUp();self.addCleanup(other.doCleanups);request=other.scoped_request()
        for repository in request['manifest']['enrollment']['record']['repositories']:
            for checkout in repository['checkouts']:checkout['clients'][0]['configuration']['runtime']=dict(schema_version=3,state_dir=str(contexts[0].directory))
        request['approval']['manifest_digest']=onboarding._digest(request['manifest'])
        self.assertEqual(changes._run_scoped(other.directory,request,'apply')['exit_code'],0)
        independent=changes._observe_recovery_source(other.directory,changes._load_journal(other.directory),contexts,refs)
        for context in contexts:
            with self.api._context_database(context,write=True) as db:self.api._register_recovery_source(None,db,independent,context=context)
        inspected=changes.inspect_lifecycle_recovery(source.content['authorities'],refs)
        self.assertTrue(inspected['complete'],inspected)
        for ref in refs:
            self.assertTrue(any(r['kind']=='task' and r['reference']==ref and r['need']=='identity' and r['root']['identity']==dict(source.content['identity']) for r in inspected['requirements']))
            self.assertTrue(any(r['kind']=='task' and r['reference']==ref and r['need']=='raw' and r['root']['identity']==dict(independent.content['identity']) for r in inspected['requirements']))
        self.assertEqual(self.raw_rows(contexts),before)
        for context,ref in zip(contexts,refs):
            with self.assertRaises(StartupError):self.api._observe_closure((context,),ref)
        print('PREPARATION_CAPTURE_PROFILE '+json.dumps({stage:{name:dict(count=row['count'],inclusive_seconds=row['seconds'],distinct_facts=len(row['digests'])) for name,row in values.items()} for stage,values in profile.items()}),flush=True)

    def preparation_stops(self,pointer,skip=None):
        for index,f in enumerate(self.members):
            if index!=skip:state._retain_ready_stop(f.scope,self.stop_request(f,pointer))
        return list({self.api._raw(self.reference(f)['authority']):self.reference(f)['authority'] for f in self.members}.values())

    def preparation_receipts(self,contexts):
        receipts=[]
        for context in contexts:
            with self.api._context_database(context) as db:
                for row in db.execute("select name,digest,owner_key,class,created_at,closed_at,status,bytes,data from evidence_metadata where class='compact'"):
                    ref=dict(name=row[0],digest=row[1]);body=self.api._read(None,ref,context=context,db=db)
                    if body.get('kind')=='linked-closure-preparation':receipts.append(dict(reference=ref,metadata=state._metadata_record(row),body=body))
        return receipts

    def test_linked_preparation_second_write_failure_and_replay_preserve_exact_receipts_and_age(self):
        pointer=self.verify()['verification'];authorities=self.preparation_stops(pointer)
        contexts=tuple(self.api._evidence_context(f.scope) for f in self.members);before=self.raw_rows(contexts)
        observed=self.api._observe_linked_preparation(pointer,authorities);artifact=self.api._artifact;count=[0]
        def fail(scope,value,**kwargs):
            if value.get('kind')=='linked-closure-preparation':
                count[0]+=1
                if count[0]==2:raise state.StateError('fixture: before second preparation')
            return artifact(scope,value,**kwargs)
        with patch.object(self.api,'_artifact',side_effect=fail),self.assertRaises(StartupError):self.api._prepare_linked_closure(observed)
        partial=self.preparation_receipts(contexts);self.assertEqual(len(partial),1);self.assertEqual(self.raw_rows(contexts),before)
        original=partial[0]
        completed=self.api._prepare_linked_closure(self.api._observe_linked_preparation(pointer,authorities))
        self.assertEqual(len(completed['preparations']),2)
        self.assertIn(original,self.preparation_receipts(contexts))
        with patch.object(self.api,'_artifact',side_effect=AssertionError('Replay wrote duplicate support')):
            replay=self.api._prepare_linked_closure(self.api._observe_linked_preparation(pointer,authorities))
        self.assertEqual(replay,completed);self.assertEqual(len(self.preparation_receipts(contexts)),2)
        self.assertEqual(self.raw_rows(contexts),before)

    def test_linked_preparation_required_open_unknown_and_wrong_head_deliveries_stay_protected(self):
        delivery=dict(provider='fixture',repository='owner/repo',target='main',pull_request='fixture:required')
        for status in ('open','unknown','wrong-head'):
            with self.subTest(status=status):
                scenario=LinkedVerificationTests(methodName='runTest');scenario.setUp();self.addCleanup(scenario.doCleanups)
                scenario.establish(delivery);observations=scenario.observations(delivery=delivery,delivery_status='merged' if status=='wrong-head' else status)
                if status=='wrong-head':
                    observe=observations['observe']
                    def wrong(facts):
                        value=observe(facts);row=value['deliveries'][0];source=scenario.api._linked_source(row['source'])
                        source['revision']='f'*40;row['revision']='f'*40;row['source']=scenario.retained(scenario.selected,source);return value
                    observations['observe']=wrong
                result=scenario.verify(observations);self.assertFalse(result['delivery_complete'])
                authorities=scenario.preparation_stops(result['verification'])
                with self.assertRaisesRegex(StartupError,'merged or approved-null'):scenario.api._observe_linked_preparation(result['verification'],authorities)
                self.assertEqual(scenario.preparation_receipts(tuple(scenario.api._evidence_context(f.scope) for f in scenario.members)),[])

    def test_linked_preparation_changed_peer_and_incomplete_observation_cannot_write(self):
        pointer=self.verify()['verification'];authorities=self.preparation_stops(pointer,skip=1)
        with self.assertRaises(StartupError):self.api._observe_linked_preparation(pointer,authorities)
        state._retain_ready_stop(self.members[1].scope,self.stop_request(self.members[1],pointer))
        observed=self.api._observe_linked_preparation(pointer,authorities)
        wrong=self.api._canonical_plain(observed.facts);wrong['members'].pop()
        with self.assertRaises(StartupError):self.api._prepare_linked_closure(replace(observed,facts=self.api._canonical_freeze(wrong)))
        peer=self.members[1]
        with state._database(peer.scope,write=True) as db:
            task=self.task(peer);task['revision']+=1;state._save(db,state._scope_id(peer.scope),task)
        with self.assertRaises(StartupError):self.api._prepare_linked_closure(observed)
        self.assertEqual(self.preparation_receipts(tuple(self.api._evidence_context(f.scope) for f in self.members)),[])

    def test_linked_preparation_changed_shared_source_after_observation_cannot_write(self):
        pointer=self.verify()['verification'];authorities=self.preparation_stops(pointer)
        observed=self.api._observe_linked_preparation(pointer,authorities);content=self.api._linked_source(pointer)
        source=content['observations']['scope_decision'];context=self.api._reference_context(source['authority'])
        path=context.directory/'evidence'/source['reference']['name'];path.chmod(0o600);path.write_bytes(path.read_bytes()+b' ');path.chmod(0o400)
        with self.assertRaises(StartupError):self.api._prepare_linked_closure(observed)
        self.assertEqual(self.preparation_receipts(tuple(self.api._evidence_context(f.scope) for f in self.members)),[])

    def test_linked_preparation_forged_owner_generic_artifact_and_unregistered_copy_are_not_replacements(self):
        from runtime import changes
        pointer=self.verify()['verification'];authorities=self.preparation_stops(pointer)
        observed=self.api._observe_linked_preparation(pointer,authorities);facts=self.api._canonical_plain(observed.facts)
        f=self.selected;ref=self.reference(f);context=self.api._evidence_context(f.scope);content=self.api._preparation_content(facts,ref)
        with self.assertRaises(StartupError):self.api._prepare_linked_closure(dict(complete=True,facts=facts))
        owner=self.api._PreparationOwner(self.api._canonical_freeze(ref),dict(complete=True),self.api._canonical_freeze(content),(),content['created_at'])
        with self.assertRaises(StartupError):self.api._artifact(None,content,context=context,owner=owner)
        generic=self.api._artifact(f.scope,content,owner=self.api._artifact_owner(f.scope,self.task(f)))
        with self.api._context_database(context) as db:
            metadata=state._metadata(db,generic['name']);self.assertEqual(metadata['class'],'detail')
            self.assertIn(dict(kind='task',reference=ref),metadata['dependencies'])
        contexts=tuple(self.api._evidence_context(member.scope) for member in self.members)
        certificates=[]
        for member,ctx in zip(self.members,contexts):
            with self.api._context_database(ctx) as db:certificates.append(changes._stopped_certificate(ctx,db,dict(reference=self.reference(member),pins=self.task(member)['pins'])))
        with self.api._linked_stop_guards(pointer,authorities):
            issued,_,_=self.api._linked_prepared_replacements(certificates,contexts)
        self.assertFalse(any('preparation' in c for c in issued))
        orphan=context.directory/'evidence'/'unregistered-preparation.json';orphan.write_bytes(self.api._raw(content));orphan.chmod(0o400)
        with self.assertRaisesRegex(StartupError,'Unaccounted'):self.api._prepare_linked_closure(observed)
        self.assertEqual(self.preparation_receipts(contexts),[])

    def test_linked_preparation_post_release_observation_substitution_keeps_raw_source(self):
        from runtime import changes
        pointer,_,source,contexts,refs=self.preparation_fixture();before=self.raw_rows(contexts)
        self.api._prepare_linked_closure(self.api._observe_linked_preparation(pointer,self.api._canonical_plain(source.content['authorities'])))
        observed=changes._observe_recovery_release(source.content['authorities'],dict(source.content['identity']))
        old_heads=[]
        for context in contexts:
            with self.api._context_database(context) as db:old_heads.append(state._source_baseline(None,db,context=context))
        compact=self.preparation_receipts(contexts)[0];path=Path(compact['metadata']['managed']['path'])
        replacement=path.with_name('replacement.json');replacement.write_bytes(path.read_bytes());replacement.chmod(0o400);os.replace(replacement,path)
        released=changes._register_recovery_release(observed);self.assertFalse(released['complete'])
        for context,old in zip(contexts,old_heads):
            with self.api._context_database(context) as db:self.assertEqual(state._source_baseline(None,db,context=context),old)
        self.assertEqual(self.raw_rows(contexts),before)

    def test_linked_preparation_interrupted_and_complete_receipts_do_not_block_unrelated_ordinary_closure(self):
        from tests import test_state
        shared=tempfile.TemporaryDirectory(prefix='linked-preparation-shared-');self.addCleanup(shared.cleanup)
        canonical=test_state.canonical_scope;counter=[0]
        def scope(legacy,**kwargs):
            number=counter[0];counter[0]+=1;legacy=replace(legacy,runtime=RuntimeSettings(2,Path(shared.name).resolve()/'state'))
            return canonical(legacy,repository_id='repository-'+str(number),checkout_id='checkout-'+str(number),**kwargs)
        scenario=LinkedVerificationTests(methodName='runTest')
        with patch.object(test_state,'canonical_scope',side_effect=scope):scenario.setUp()
        self.addCleanup(scenario.doCleanups)
        pointer=scenario.verify()['verification'];authorities=scenario.preparation_stops(pointer)
        observed=self.api._observe_linked_preparation(pointer,authorities);artifact=self.api._artifact;count=[0]
        def fail(scope,value,**kwargs):
            if value.get('kind')=='linked-closure-preparation':
                count[0]+=1
                if count[0]==2:raise state.StateError('fixture: before second preparation')
            return artifact(scope,value,**kwargs)
        with patch.object(self.api,'_artifact',side_effect=fail),self.assertRaises(StartupError):self.api._prepare_linked_closure(observed)
        f=scenario.selected;context=self.api._evidence_context(f.scope)
        for stage in ('interrupted','complete','pending-closure'):
            if stage=='complete':self.api._prepare_linked_closure(self.api._observe_linked_preparation(pointer,authorities))
            if stage=='pending-closure':
                close=state._close_lifecycle
                def fail(db,ref,observation,compact):
                    close(db,ref,observation,compact)
                    raise RuntimeError('fixture: rollback publication after durable candidate')
                ref=scenario.reference(f)
                with patch.object(state,'_close_lifecycle',side_effect=fail),self.assertRaises(RuntimeError):
                    self.api.close_task(f.scope,scenario.linked_closure_request(0),self.api._observe_closure((context,),ref))
                self.assertEqual(len(self.linked_closure_candidates(context,ref)),1)
                self.assertIsNone(scenario.task(f)['lifecycle']['safe_closed_at'])
            identity=dict(client='codex',session_id='ordinary-'+stage,task_id='ordinary-'+stage,scope_ref='user:ordinary')
            task=state.start_task(f.scope,identity|dict(mode='editable',decision_ref='user:accepted'))['task']
            proof=dict(version=1,kind='stopped-writer-reconciliation',identity=identity,expected_revision=task['revision'],expected_pins=task['pins'],
                observed_turn_id=task['turn_id'],stopped=True,descendants_stopped=True,attempt_ids=[],observation_ref='fixture:ordinary-stop',coordinator_ref='fixture:independent')
            raw=json.dumps(proof).encode();path=f.root/(stage+'-ordinary-stop.json');path.write_bytes(raw);path.chmod(0o400)
            task=state.retire_task(f.scope,identity|dict(expected_revision=task['revision'],expected_pins=task['pins'],reason='Cancelled',reference='fixture:cancel',
                stop_proof=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest())))['task']
            ref=self.api._canonical_plain(self.api._artifact_owner(f.scope,task).task)
            closed=self.api.close_task(f.scope,identity|dict(expected_revision=task['revision'],expected_pins=task['pins']),self.api._observe_closure((context,),ref))['task']
            self.assertIsNotNone(closed['lifecycle']['safe_closed_at'])
            for member in scenario.members:self.assertIsNone(scenario.task(member)['lifecycle']['safe_closed_at'])

    def test_linked_preparation_missing_approved_third_stop_and_member_stay_protected(self):
        from types import SimpleNamespace
        from tests.test_state import canonical_scope
        from tests.test_startup import CanonicalAcquisitionTests
        third=EvidenceTests(methodName='runTest');third.setUp();self.addCleanup(third.doCleanups)
        third.scope=canonical_scope(third.scope)
        state.start_task(third.scope,third.identity|dict(mode='editable',decision_ref='user:accepted'))
        record,path=CanonicalAcquisitionTests.record(SimpleNamespace(repo=third.repo,base=third.root,assertIsNone=self.assertIsNone))
        identity=self.api._canonical_plain(third.scope.accepted_identity);record['project_id']=identity['project_id']
        record['repositories'][0]['repository_id']=identity['repository_id'];record['repositories'][0]['checkouts'][0]['checkout_id']=identity['checkout_id']
        record['repositories'][0]['checkouts'][0]['clients'][0]['configuration'].update(identity['configuration'])
        path.write_text(json.dumps(record));self.members.append(third);self.establish()
        pointer=self.verify()['verification'];authorities=self.preparation_stops(pointer,skip=2)
        with self.assertRaises(StartupError):self.api._observe_linked_preparation(pointer,authorities[:2])
        contexts=tuple(self.api._evidence_context(f.scope) for f in self.members[:2])
        with self.assertRaises(StartupError):self.api._observe_closure(contexts,self.reference(self.selected))
        state._retain_ready_stop(third.scope,self.stop_request(third,pointer))
        observed=self.api._observe_linked_preparation(pointer,authorities[:2])
        self.assertEqual(len(observed.facts['members']),3)
        with self.assertRaises(StartupError):self.api._observe_closure(contexts,self.reference(self.selected))
        self.assertTrue(all(self.task(f)['lifecycle']['safe_closed_at'] is None for f in self.members))
        incomplete=self.api._canonical_plain(observed.facts);incomplete['members'].pop()
        with self.assertRaises(StartupError):self.api._prepare_linked_closure(replace(observed,facts=self.api._canonical_freeze(incomplete)))
        self.assertEqual(self.preparation_receipts(tuple(self.api._evidence_context(f.scope) for f in self.members)),[])

    def test_linked_preparation_preserves_bound_review_findings_dispositions_and_guidance_without_prompt_copy(self):
        finding=dict(id='optional-note',severity='info',scope='general',status='optional',location='app.py:1',
            scenario='Optional fixture suggestion',evidence='Original code trace',counterevidence='No correctness defect')
        for f in self.members:
            reviewed=f.review(findings=[finding]);task=self.task(f)
            attempt=next(a for a in task['evidence']['attempts'] if a['id']==reviewed['attempt_id'])
            assessment=self.api._read(f.scope,attempt['assessment'])['assessment']
            assessment['dispositions']=[dict(finding_id=finding['id'],status='accepted',reference='user:accepted-optional')]
            self.api.assess_review(f.scope,f.request(attempt_id=reviewed['attempt_id'],assessment=assessment))
        pointer=self.verify()['verification'];authorities=self.preparation_stops(pointer)
        prepared=self.api._prepare_linked_closure(self.api._observe_linked_preparation(pointer,authorities))
        for receipt in prepared['preparations']:
            compact=self.api._linked_source(dict(authority=receipt['reference']['authority'],reference=receipt['reference']['artifact']))
            self.assertEqual(compact['reviews'][0]['report']['findings'],[finding])
            self.assertTrue(any(a['assessment']['dispositions']==[dict(finding_id=finding['id'],status='accepted',reference='user:accepted-optional')] for a in compact['reviews'][0]['assessments']))
            self.assertTrue(compact['native_guidance']);self.assertTrue(compact['scope_guidance']);self.assertTrue(compact['workers'])
            self.assertEqual(compact['usage'],'unknown')
            self.assertNotIn('Review read-only; inspect app.py and callers. Return the bound report.',json.dumps(compact))

        contexts=tuple(self.api._evidence_context(f.scope) for f in self.members);refs=tuple(self.reference(f) for f in self.members)
        closed=[]
        for index,ref in enumerate(refs):closed.append(self.api.close_task(self.members[index].scope,self.linked_closure_request(index),self.api._observe_closure(contexts,ref))['task'])
        originals=[self.api._read(None,t['lifecycle']['compact'],context=c) for t,c in zip(closed,contexts)]
        from runtime import delegation
        for index,(context,ref) in enumerate(zip(contexts,refs)):
            self.assertTrue(self.api._retire_closed_task(context,ref)['retired'])
            with self.api._context_database(context) as db:
                guidance=delegation._closure_guidance(context,db,delegation._ledger(None,db,context=context))
                self.assertTrue(originals[index]['native_guidance']);self.assertTrue(guidance['sources']);self.assertEqual(len(guidance['retained']),1)
            self.assertEqual(self.api._read(None,closed[index]['lifecycle']['compact'],context=context),originals[index])
        f=self.members[0]
        from types import SimpleNamespace
        def ordinary(task_id):
            with self.api._context_database(contexts[0]) as db:
                bound=db.execute('select task_id from bindings where scope_id=? and client=? and session_id=?',(refs[0]['scope_id'],'codex','parent')).fetchone()
                previous=state._task(db,refs[0]['scope_id'],'codex','parent',bound[0]) if bound else None
            f.identity=dict(f.identity,task_id=task_id)
            replacement=dict(replaces=dict(task_id=previous['task_id'],expected_revision=previous['revision'])) if previous else {}
            state.start_task(f.scope,f.identity|dict(mode='editable',decision_ref='user:accepted')|replacement)
            review=dict(applicability='inapplicable',reason='Trivial later ordinary fixture',independent=False)
            f.plan(nontrivial=False,reviews=dict(general=review,security=review));f.checked();task=f.verify()['task']
            stopped=state._retain_ready_stop(f.scope,ReadyClosureTests.stop_request(SimpleNamespace(fixture=f,scope=f.scope),task))['task']
            ref=self.api._canonical_plain(self.api._artifact_owner(f.scope,stopped).task)
            return stopped,ref,self.api._observe_closure((contexts[0],),ref)
        stopped,ref,observed=ordinary('later-ordinary')
        current=self.api.close_task(f.scope,f.request(expected_pins=stopped['pins']),observed)['task']
        compact=self.api._read(f.scope,current['lifecycle']['compact']);self.assertTrue(compact['scope_guidance'])
        stopped,ref,observed=ordinary('later-ordinary-source-check');artifact=self.api._artifact;moved=[]
        foreign_source=closed[1]['evidence']['verification']
        def late(scope,value,**kwargs):
            result=artifact(scope,value,**kwargs)
            if value.get('kind')=='task-closure' and not moved:
                moved.append(True)
                with self.api._context_database(contexts[1],write=True) as db:
                    metadata=state._metadata(db,foreign_source['name']);metadata['dependencies'].append(dict(kind='task',reference=refs[0]))
                    db.execute('update evidence_metadata set data=? where name=?',(json.dumps(metadata),foreign_source['name']))
            return result
        with patch.object(self.api,'_artifact',side_effect=late),self.assertRaises(StartupError):
            self.api.close_task(f.scope,f.request(expected_pins=stopped['pins']),observed)
        self.assertTrue(moved)
        with self.api._context_database(contexts[0]) as db:
            self.assertEqual(state._task(db,ref['scope_id'],ref['client'],ref['session_id'],ref['task_id']),stopped)

    def test_linked_preparation_final_recovery_read_movement_rejects(self):
        from runtime import changes, onboarding
        from tests.test_state import canonical_scope
        from tests.test_changes import ScopedChangesTests
        api = self.api
        pointer = self.verify()['verification']
        authorities = self.preparation_stops(pointer)
        observed = api._observe_linked_preparation(pointer, authorities)
        artifact = api._artifact
        inspect = changes._inspect_lifecycle_recovery_guarded
        phase = dict(prepared=0, armed=False, moved=False)

        def arm(scope, value, **kwargs):
            result = artifact(scope, value, **kwargs)
            if value.get('kind') == 'linked-closure-preparation':
                phase['prepared'] += 1
                if phase['prepared'] == 2:
                    phase['armed'] = True
            return result

        def move_after_inspection(*args, **kwargs):
            result = inspect(*args, **kwargs)
            if phase['armed'] and (not phase['moved']):
                (self.members[1].repo / 'app.py').write_text('Changed participant after final recovery inspection\n')
                phase['moved'] = True
                print('LATE_PARTICIPANT_MOVE_AFTER_FINAL_INSPECTION True', flush=True)
            return result
        rejected = False
        result = None
        try:
            with patch.object(api, '_artifact', side_effect=arm), patch.object(changes, '_inspect_lifecycle_recovery_guarded', side_effect=move_after_inspection):
                result = api._prepare_linked_closure(observed)
        except StartupError:
            rejected = True
        self.assertTrue(phase['moved'], 'Probe must reach second-artifact final inspection')
        with self.assertRaises(StartupError):
            api._linked_stop_basis(pointer, authorities)
        print('PREPARATION_REJECTED ' + str(rejected), flush=True)
        print('PREPARATION_RESULT ' + json.dumps(result), flush=True)
        self.assertTrue(rejected, 'Preparation reports complete with receipts despite a late participant input change')

    def test_linked_preparation_component_owned_source_keeps_explicit_foreign_raw_demand(self):
        from runtime import changes
        api = self.api
        foreign_fixture = CanonicalEvidenceTests(methodName='runTest')
        foreign_fixture.setUp(d4_recovery=True)
        self.addCleanup(foreign_fixture.doCleanups)
        extra = foreign_fixture.fixture
        task = state.start_task(extra.scope, extra.identity | dict(mode='editable', decision_ref='user:accepted'))['task']
        proof = dict(version=1, kind='stopped-writer-reconciliation', identity=extra.identity, expected_revision=task['revision'], expected_pins=task['pins'], observed_turn_id=task['turn_id'], stopped=True, descendants_stopped=True, attempt_ids=[], observation_ref='fixture:independent-extra-stop', coordinator_ref='fixture:checked')
        raw = json.dumps(proof).encode()
        path = extra.root / 'foreign-stop.json'
        path.write_bytes(raw)
        path.chmod(256)
        state.retire_task(extra.scope, extra.request(expected_pins=task['pins'], reason='Cancelled', reference='fixture:cancel', stop_proof=dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest())))
        foreign = self.reference(extra)
        observations = self.observations()
        observe = observations['observe']
        retained = []

        def acquire(facts):
            value = observe(facts)
            body = api._linked_source(value['shared'][0]['evidence'][0])
            owner = api._LinkedOwner(api._artifact_owner(self.selected.scope, self.task(self.selected)), (api._canonical_freeze(dict(kind='task', reference=foreign)),))
            reference = api._artifact(self.selected.scope, body, owner=owner)
            source = dict(authority=self.reference(self.selected)['authority'], reference=reference)
            value['shared'][0]['evidence'] = [source]
            retained.append(source)
            return value
        observations['observe'] = acquire
        pointer = self.verify(observations)['verification']
        contexts = tuple((api._evidence_context(f.scope) for f in [*self.members, extra]))
        refs = tuple((self.reference(f) for f in self.members))
        for member in self.members:
            state._retain_ready_stop(member.scope, self.stop_request(member, pointer))
        d4, request = self.recovery_fixtures[0]
        applied = _run_d4_fixture(d4, request, 'resume')
        self.assertEqual(applied['exit_code'], 0, applied)
        _, source = self.recovery_head(d4, contexts[0])
        for context in contexts:
            self.assertEqual(self.recovery_head(d4, context)[1], source)
        self.assertTrue(all(any(row['reference'] == ref for row in source['tasks']) for ref in (*refs, foreign)))
        prepared = api._prepare_linked_closure(api._observe_linked_preparation(pointer, api._canonical_plain(source['authorities'])))
        self.assertTrue(prepared['complete'])
        observed = changes._observe_recovery_release(source['authorities'], dict(source['identity']))
        semantic = dict(authority=retained[0]['authority'], artifact=retained[0]['reference'])
        original = next((row for row in source['tasks'] if dict(row['reference']) == foreign))
        present = any((dict(row['reference']) == foreign for row in observed.content['tasks']))
        print('EXPLICIT_FOREIGN_RAW_REFERENCE ' + json.dumps(foreign), flush=True)
        print('SEMANTIC_SOURCE_RETAINED ' + str(any((api._canonical_plain(row) == semantic for row in observed.content['artifacts']))), flush=True)
        print('FOREIGN_RAW_TASK_RETAINED ' + str(present), flush=True)
        print('ORIGINAL_SOURCE_REQUIRED_FOREIGN_RAW_TASK ' + str(bool(original)), flush=True)
        self.assertTrue(any(api._canonical_plain(row) == semantic for row in observed.content['artifacts']))
        self.assertTrue(original)
        self.assertTrue(present, 'D4 erases an explicit foreign raw-task demand merely because its semantic source owner belongs to the prepared component')

    def linked_closure_fixture(self):
        from runtime import changes
        pointer,d4,source,contexts,refs=self.preparation_fixture()
        observed=self.api._observe_linked_preparation(pointer,self.api._canonical_plain(source.content['authorities']))
        self.assertTrue(self.api._prepare_linked_closure(observed)['complete'])
        released=changes._register_recovery_release(changes._observe_recovery_release(source.content['authorities'],dict(source.content['identity'])))
        self.assertTrue(released['complete'],released)
        return pointer,d4,source,contexts,refs

    def linked_closure_request(self,index):
        task=self.task(self.members[index])
        return {key:task[key] for key in ('client','session_id','task_id','scope_ref')}|dict(expected_revision=task['revision'],expected_pins=task['pins'])

    def linked_closure_candidates(self,context,reference):
        found=[]
        with self.api._context_database(context) as db:
            for row in db.execute("select name,digest,owner_key,class,created_at,closed_at,status,bytes,data from evidence_metadata where class='compact'"):
                metadata=state._metadata_record(row)
                if metadata['owner'].get('task')!=reference:continue
                ref=dict(name=row[0],digest=row[1]);body=self.api._read(None,ref,context=context,db=db)
                if body.get('kind')=='task-closure':found.append(dict(reference=ref,metadata=metadata,content=body))
        return found

    def test_linked_safe_closure_second_transaction_failure_reuses_registered_candidate(self):
        _,_,_,contexts,refs=self.linked_closure_fixture()
        first=self.api.close_task(self.members[0].scope,self.linked_closure_request(0),self.api._observe_closure(contexts,refs[0]))['task']
        peer=self.task(self.members[1]);before=self.raw_rows(contexts);closed=state._close_lifecycle;failed=[]
        def fail(db,ref,observation,compact):
            result=closed(db,ref,observation,compact);failed.append(result)
            raise RuntimeError('fixture: failure after lifecycle SQL before commit')
        observed=self.api._observe_closure(contexts,refs[1])
        with patch.object(state,'_close_lifecycle',side_effect=fail),self.assertRaises(RuntimeError):
            self.api.close_task(self.members[1].scope,self.linked_closure_request(1),observed)
        self.assertEqual(len(failed),1);self.assertEqual(self.task(self.members[0]),first);self.assertEqual(self.task(self.members[1]),peer)
        self.assertEqual(self.raw_rows(contexts),before)
        candidates=self.linked_closure_candidates(contexts[1],refs[1]);self.assertEqual(len(candidates),1,'A retry needs durable managed ownership, not an unregistered orphan')
        candidate=candidates[0];self.assertEqual(candidate['metadata']['created_at'],peer['lifecycle']['created_at'])
        retry=self.api.close_task(self.members[1].scope,self.linked_closure_request(1),self.api._observe_closure(contexts,refs[1]))['task']
        self.assertEqual(retry['lifecycle']['compact'],candidate['reference']);self.assertIsNotNone(retry['lifecycle']['safe_closed_at'])
        self.assertEqual(self.linked_closure_candidates(contexts[1],refs[1]),candidates)
        replay=self.api.close_task(self.members[1].scope,self.linked_closure_request(1),self.api._observe_closure(contexts,refs[1]))['task']
        self.assertEqual(replay,retry);self.assertEqual(self.task(self.members[0]),first)

    def test_linked_retirement_all_closures_faults_tamper_and_partial_retry(self):
        from runtime.engine import RuntimeEvent
        for f in self.members:
            for kind in ('PreToolUse','PostToolUse'):
                state.process_event(f.scope,RuntimeEvent(kind,'codex','parent',f.repo,turn_id='turn',tool_call_id='retirement-read',tool_name='read_file',receipt_fingerprint='a'*64))
        pointer=self.verify()['verification'];authorities=self.preparation_stops(pointer)
        self.assertTrue(self.api._prepare_linked_closure(self.api._observe_linked_preparation(pointer,authorities))['complete'])
        contexts=tuple(self.api._evidence_context(f.scope) for f in self.members);refs=tuple(self.reference(f) for f in self.members)
        def dumps():
            result=[]
            for context in contexts:
                with self.api._context_database(context) as db:result.append(list(db.iterdump()))
            return result
        closed=[self.api.close_task(self.members[0].scope,self.linked_closure_request(0),self.api._observe_closure(contexts,refs[0]))['task']]
        with patch.object(state,'_close_lifecycle',side_effect=RuntimeError('fixture: pending closure')),self.assertRaises(RuntimeError):
            self.api.close_task(self.members[1].scope,self.linked_closure_request(1),self.api._observe_closure(contexts,refs[1]))
        before=dumps()
        with self.assertRaises(StartupError):self.api._retire_closed_task(contexts[0],refs[0])
        self.assertEqual(dumps(),before,'Pending last candidate must confer no removal or original closure date')
        closed.append(self.api.close_task(self.members[1].scope,self.linked_closure_request(1),self.api._observe_closure(contexts,refs[1]))['task'])
        retire=state.retire_closed
        def fail_after_sql(*args):
            retire(*args);raise RuntimeError('fixture: after local retirement SQL')
        before=dumps()
        with patch.object(state,'retire_closed',side_effect=fail_after_sql),self.assertRaisesRegex(RuntimeError,'after local retirement SQL'):
            self.api._retire_closed_task(contexts[0],refs[0])
        self.assertEqual(dumps(),before,'Assignments, events, task marker and closure date must roll back together')
        marker=state._retired_record
        for changed in ('peer','source'):
            peer=contexts[1];fired=[]
            with self.api._context_database(peer) as db:
                if changed=='peer':query='select data from tasks where scope_id=? and client=? and session_id=? and task_id=?';key=tuple(refs[1][k] for k in ('scope_id','client','session_id','task_id'))
                else:query='select data from evidence_metadata where name=?';key=(closed[1]['evidence']['verification']['name'],)
                original=db.execute(query,key).fetchone()[0]
            def late(kind,*args):
                result=marker(kind,*args)
                if kind=='task' and not fired:
                    fired.append(True);value=json.loads(original)
                    if changed=='peer':value['revision']+=1
                    else:value['dependencies'].append(dict(kind='task',reference=refs[0]))
                    with self.api._context_database(peer,write=True) as db:
                        table='tasks' if changed=='peer' else 'evidence_metadata';where=query.split(' where ',1)[1]
                        db.execute('update '+table+' set data=? where '+where,(json.dumps(value),*key))
                return result
            with patch.object(state,'_retired_record',side_effect=late),self.assertRaises(StartupError):self.api._retire_closed_task(contexts[0],refs[0])
            self.assertTrue(fired);self.assertEqual(dumps()[0],before[0])
            with self.api._context_database(peer,write=True) as db:
                table='tasks' if changed=='peer' else 'evidence_metadata';where=query.split(' where ',1)[1]
                db.execute('update '+table+' set data=? where '+where,(original,*key))
            self.assertEqual(dumps(),before)
        first=self.api._retire_closed_task(contexts[0],refs[0]);self.assertTrue(first['retired']);committed=dumps()
        with self.api._context_database(contexts[0]) as db:
            rows=db.execute("select kind,identity_digest,data from retired_identities where kind in ('task','assignment') order by kind").fetchall()
        for kind,identity,raw in (rows[0],rows[-1]):
            value=json.loads(raw)
            if kind=='task':value['outcome']='cancelled'
            else:value['request_digest']='0'*64
            with self.api._context_database(contexts[0],write=True) as db:db.execute('update retired_identities set data=? where kind=? and identity_digest=?',(json.dumps(value),kind,identity))
            changed=dumps()
            with self.assertRaises(StartupError):self.api._retire_closed_task(contexts[1],refs[1])
            self.assertEqual(dumps(),changed)
            with self.api._context_database(contexts[0],write=True) as db:db.execute('update retired_identities set data=? where kind=? and identity_digest=?',(raw,kind,identity))
        candidate=closed[0]['lifecycle']['compact'];path=contexts[0].directory/'evidence'/candidate['name'];saved=contexts[0].directory/'original-closure-for-fixture'
        path.rename(saved);path.write_bytes(saved.read_bytes());path.chmod(0o400)
        with self.assertRaises(StartupError):self.api._retire_closed_task(contexts[1],refs[1])
        path.unlink();saved.rename(path)
        with patch.object(state,'retire_closed',side_effect=fail_after_sql),self.assertRaises(RuntimeError):self.api._retire_closed_task(contexts[1],refs[1])
        self.assertEqual(dumps(),committed,'A second-authority failure must preserve the first committed retirement')
        second=self.api._retire_closed_task(contexts[1],refs[1]);self.assertTrue(second['retired']);complete=dumps()
        self.assertEqual(self.api._retire_closed_task(contexts[0],refs[0]),first);self.assertEqual(self.api._retire_closed_task(contexts[1],refs[1]),second)
        self.assertEqual(dumps(),complete)
        consumer=state.start_task(self.members[1].scope,dict(client='codex',session_id='consumer',task_id='consumer',scope_ref='user:consumer',mode='editable',decision_ref='user:accepted'))['task']
        owner=self.api._LinkedOwner(self.api._artifact_owner(self.members[1].scope,consumer),(self.api._canonical_freeze(dict(kind='task',reference=refs[0])),))
        source=self.api._artifact(self.members[1].scope,dict(kind='fixture:independent-raw-consumer'),owner=owner)
        with self.api._context_database(contexts[1],write=True) as db:
            consumer['evidence']=dict(version=1,plan=source,candidate=source,attempts=[]);state._save(db,refs[1]['scope_id'],consumer)
        protected=dumps()
        with self.assertRaises(StartupError):self.api._retire_closed_task(contexts[0],refs[0])
        self.assertEqual(dumps(),protected)

    def test_linked_retirement_preparation_raw_source_must_remain_live(self):
        from runtime import changes
        from tests.test_state import canonical_scope
        extra=EvidenceTests(methodName='runTest');extra.setUp();self.addCleanup(extra.doCleanups);extra.scope=canonical_scope(extra.scope)
        foreign_task=state.start_task(extra.scope,extra.identity|dict(mode='editable',decision_ref='user:accepted'))['task']
        foreign=self.api._canonical_plain(self.api._artifact_owner(extra.scope,foreign_task).task)
        observations=self.observations();observe=observations['observe']
        def acquire(facts):
            value=observe(facts);body=self.api._linked_source(value['shared'][0]['evidence'][0])
            owner=self.api._LinkedOwner(self.api._artifact_owner(self.selected.scope,self.task(self.selected)),
                (self.api._canonical_freeze(dict(kind='task',reference=foreign)),))
            source=self.api._artifact(self.selected.scope,body,owner=owner)
            value['shared'][0]['evidence']=[dict(authority=self.reference(self.selected)['authority'],reference=source)];return value
        observations['observe']=acquire;pointer=self.verify(observations)['verification'];authorities=self.preparation_stops(pointer)+[foreign['authority']]
        self.assertTrue(self.api._prepare_linked_closure(self.api._observe_linked_preparation(pointer,authorities))['complete'])
        contexts=tuple(self.api._evidence_context(f.scope) for f in [*self.members,extra]);refs=tuple(self.reference(f) for f in self.members)
        for index,ref in enumerate(refs):self.api.close_task(self.members[index].scope,self.linked_closure_request(index),self.api._observe_closure(contexts,ref))
        # A missing external raw body must never become successful compact attribution.
        with self.api._context_database(contexts[2],write=True) as db:
            db.execute('delete from tasks where scope_id=? and client=? and session_id=? and task_id=?',tuple(foreign[k] for k in ('scope_id','client','session_id','task_id')))
        before=self.raw_rows(contexts)
        with self.assertRaises(StartupError):self.api._retire_closed_task(contexts[0],refs[0])
        self.assertEqual(self.raw_rows(contexts),before)

    def test_linked_retirement_marker_roundtrip_preserves_closed_dates_without_current_readiness(self):
        pointer=self.verify()['verification'];authorities=self.preparation_stops(pointer)
        self.assertTrue(self.api._prepare_linked_closure(self.api._observe_linked_preparation(pointer,authorities))['complete'])
        contexts=tuple(self.api._evidence_context(f.scope) for f in self.members);refs=tuple(self.reference(f) for f in self.members);closed=[]
        for index,ref in enumerate(refs):closed.append(self.api.close_task(self.members[index].scope,self.linked_closure_request(index),self.api._observe_closure(contexts,ref))['task'])
        for f in self.members:(f.repo/'app.py').write_text('later working tree is independent of closed history\n')
        with patch.object(self.api,'_capture',side_effect=AssertionError('Retirement demanded fresh working-tree readiness')):
            for index,(context,ref) in enumerate(zip(contexts,refs)):
                result=self.api._retire_closed_task(context,ref);self.assertTrue(result['retired']);self.assertEqual(result['outcome'],closed[index]['state'])
                with self.api._context_database(context) as db:
                    self.assertIsNone(db.execute('select 1 from tasks where scope_id=? and client=? and session_id=? and task_id=?',tuple(ref[key] for key in ('scope_id','client','session_id','task_id'))).fetchone())
                    marker=state._retired(db,'task',{key:ref[key] for key in ('scope_id','client','session_id','task_id')})
                    self.assertEqual(marker['outcome'],closed[index]['state']);self.assertEqual(marker['created_at'],closed[index]['lifecycle']['created_at'])
                    metadata=state._metadata(db,closed[index]['lifecycle']['compact']['name'])
                    self.assertEqual(metadata['closed_at'],closed[index]['lifecycle']['safe_closed_at']);before=list(db.iterdump())
                self.assertEqual(self.api._retire_closed_task(context,ref),result)
                with self.api._context_database(context) as db:self.assertEqual(list(db.iterdump()),before)

    def test_linked_retirement_sequential_members_preserve_markers_and_recovery(self):
        from runtime import changes,onboarding
        from tests.test_changes import ScopedChangesTests
        _,first,source,contexts,refs=self.linked_closure_fixture()
        other=ScopedChangesTests(methodName='runTest');other.setUp();self.addCleanup(other.doCleanups);request=other.scoped_request()
        for repository in request['manifest']['enrollment']['record']['repositories']:
            for checkout in repository['checkouts']:checkout['clients'][0]['configuration']['runtime']=dict(schema_version=3,state_dir=str(contexts[0].directory))
        request['approval']['manifest_digest']=onboarding._digest(request['manifest']);self.assertEqual(changes._run_scoped(other.directory,request,'apply')['exit_code'],0)
        companion=changes._observe_recovery_source(other.directory,changes._load_journal(other.directory),contexts,refs)
        for context in contexts:
            with self.api._context_database(context,write=True) as db:self.api._register_recovery_source(None,db,companion,context=context)
        released=changes._register_recovery_release(changes._observe_recovery_release(companion.content['authorities'],dict(companion.content['identity'])))
        self.assertTrue(released['complete'],released)
        closed=[]
        for index,ref in enumerate(refs):
            closed.append(self.api.close_task(self.members[index].scope,self.linked_closure_request(index),self.api._observe_closure(contexts,ref))['task'])
        compacts=[self.api._read(f.scope,task['lifecycle']['compact']) for f,task in zip(self.members,closed)]
        for index,(context,ref,journal_fixture) in enumerate(zip(contexts,refs,(first,other))):
            result=self.api._retire_closed_task(context,ref);self.assertTrue(result['retired']);self.assertEqual(result['outcome'],closed[index]['state'])
            with self.api._context_database(context) as db:
                self.assertIsNone(db.execute('select 1 from tasks where scope_id=? and client=? and session_id=? and task_id=?',tuple(ref[key] for key in ('scope_id','client','session_id','task_id'))).fetchone())
                marker=state._retired(db,'task',{key:ref[key] for key in ('scope_id','client','session_id','task_id')})
                self.assertEqual(marker['outcome'],closed[index]['state']);self.assertEqual(marker['pins_digest'],self.api._digest(closed[index]['pins']))
                self.assertEqual(marker['created_at'],closed[index]['lifecycle']['created_at'])
                metadata=state._metadata(db,closed[index]['lifecycle']['compact']['name'])
                self.assertEqual(metadata['closed_at'],closed[index]['lifecycle']['safe_closed_at']);self.assertGreaterEqual(marker['retired_at'],metadata['closed_at'])
                self.assertFalse(db.execute('select 1 from assignments where scope_id=? and client=? and session_id=? and task_id=?',tuple(ref[key] for key in ('scope_id','client','session_id','task_id'))).fetchone())
                self.assertFalse(db.execute('select 1 from turns where scope_id=? and client=? and session_id=?',tuple(ref[key] for key in ('scope_id','client','session_id'))).fetchone())
                before=list(db.iterdump())
            self.assertEqual(self.api._retire_closed_task(context,ref),result)
            with self.api._context_database(context) as db:self.assertEqual(list(db.iterdump()),before)
            self.assertEqual(self.api._read(None,closed[index]['lifecycle']['compact'],context=context),compacts[index])
            recovery=changes.inspect_lifecycle_recovery(source.content['authorities'],refs)
            self.assertTrue(recovery['complete'],dict(member=index,action='after-retirement',blockers=recovery['blockers'],discovered=recovery['discovered_authorities']))
            journal=changes._load_journal(journal_fixture.directory);operation=dict(schema_version=2,manifest=journal['manifest'],approval=journal['approval'])
            for action in ('resume','rollback','rollback'):
                outcome=changes._run_scoped(journal_fixture.directory,operation,action);self.assertEqual(outcome['exit_code'],0,outcome)
                recovery=changes.inspect_lifecycle_recovery(source.content['authorities'],refs)
                self.assertTrue(recovery['complete'],dict(member=index,action=action,blockers=recovery['blockers'],discovered=recovery['discovered_authorities']))
            with patch.object(self.api,'_execute',side_effect=AssertionError('Retired owner executed verification')),self.assertRaises(StartupError):
                self.api.verify_completion(self.members[index].scope,{key:closed[index][key] for key in ('client','session_id','task_id','scope_ref')}|
                    dict(expected_revision=closed[index]['revision'],expected_pins=closed[index]['pins'],purpose='completion'))

    def test_linked_safe_closure_historical_observation_refuses_direct_retirement(self):
        from runtime import delegation
        def rows():
            result=[]
            for context in contexts:
                with self.api._context_database(context) as db:result.append(list(db.iterdump()))
            return result
        pointer=self.verify()['verification'];authorities=self.preparation_stops(pointer)
        self.assertTrue(self.api._prepare_linked_closure(self.api._observe_linked_preparation(pointer,authorities))['complete'])
        contexts=tuple(self.api._evidence_context(f.scope) for f in self.members);refs=tuple(self.reference(f) for f in self.members)
        first=self.api.close_task(self.members[0].scope,self.linked_closure_request(0),self.api._observe_closure(contexts,refs[0]))['task']
        for complete in (False,True):
            if complete:self.api.close_task(self.members[1].scope,self.linked_closure_request(1),self.api._observe_closure(contexts,refs[1]))
            historical=self.api._observe_closure(contexts,refs[0]);before=self.raw_rows(contexts);all_rows=rows()
            self.assertIn('retained_linked_closure',historical.facts)
            for entry in (delegation.retire_settled,state.retire_closed):
                with self.subTest(all_members_closed=complete,entry=entry.__name__),self.api._context_database(contexts[0],write=True) as db:
                    with self.assertRaises(state.StateError):entry(db,refs[0],historical)
                self.assertEqual(self.raw_rows(contexts),before);self.assertEqual(rows(),all_rows)
            self.assertEqual(self.task(self.members[0]),first)

    def test_linked_safe_closure_recovery_progress_accepts_exact_prior_closure(self):
        from runtime import changes
        _,d4,source,contexts,refs=self.linked_closure_fixture();original=[self.task(f) for f in self.members];before=self.raw_rows(contexts)
        first=self.api.close_task(self.members[0].scope,self.linked_closure_request(0),self.api._observe_closure(contexts,refs[0]))['task']
        journal=changes._load_journal(d4.directory)
        request=dict(schema_version=2,manifest=journal['manifest'],approval=journal['approval'])
        resumed=changes._run_scoped(d4.directory,request,'resume');self.assertEqual(resumed['exit_code'],0,resumed)
        rolled=changes._run_scoped(d4.directory,request,'rollback');self.assertEqual(rolled['exit_code'],0,rolled)
        self.assertTrue(changes.inspect_lifecycle_recovery(source.content['authorities'],refs)['complete'])
        second=self.api.close_task(self.members[1].scope,self.linked_closure_request(1),self.api._observe_closure(contexts,refs[1]))['task']
        self.assertIsNotNone(second['lifecycle']['safe_closed_at']);self.assertEqual(self.task(self.members[0]),first)
        replay=self.api.close_task(self.members[0].scope,self.linked_closure_request(0),self.api._observe_closure(contexts,refs[0]))['task']
        self.assertEqual(replay,first)
        for f,old in zip(self.members,original):
            current=self.task(f)
            self.assertEqual({key:value for key,value in current.items() if key!='lifecycle'},{key:value for key,value in old.items() if key!='lifecycle'})
            self.assertEqual(current['lifecycle']['created_at'],old['lifecycle']['created_at'])
            compact=self.api._read(f.scope,current['lifecycle']['compact'])
            preparation=self.api._read(f.scope,compact['artifacts'][0])
            for key in ('numerical','reviews','workers','native_guidance','scope_guidance','verifications','sources'):
                self.assertEqual(compact[key],preparation[key])
        for old,current in zip(before,self.raw_rows(contexts)):
            self.assertEqual({key:value for key,value in old.items() if key!='tasks'},{key:value for key,value in current.items() if key!='tasks'})
        for context,ref in zip(contexts,refs):
            historical=self.api._observe_closure(contexts,ref)
            with self.api._context_database(context,write=True) as db,self.assertRaises(StartupError):state.retire_closed(db,ref,historical)

    def linked_closure_late_change(self,kind):
        _,_,_,contexts,refs=self.linked_closure_fixture()
        first=self.api.close_task(self.members[0].scope,self.linked_closure_request(0),self.api._observe_closure(contexts,refs[0]))['task']
        peer=self.task(self.members[1]);before=self.raw_rows(contexts);observed=self.api._observe_closure(contexts,refs[1]);close=state._close_lifecycle;changed=[]
        def move(db,ref,observation,compact):
            if kind=='peer':(self.members[0].repo/'app.py').write_text('changed after closure observation\n')
            else:
                basis=self.api._read(self.members[0].scope,first['writer_stop']['linked'])
                source=next(row for row in basis['sources'] if self.api._linked_source(row['reference']).get('kind')=='linked-integration-observation')
                path=Path(source['metadata']['managed']['path']);replacement=path.with_name(path.name+'.replacement')
                replacement.write_bytes(path.read_bytes());replacement.chmod(0o400);os.replace(replacement,path)
            changed.append(True);return close(db,ref,observation,compact)
        with patch.object(state,'_close_lifecycle',side_effect=move),self.assertRaises(StartupError):
            self.api.close_task(self.members[1].scope,self.linked_closure_request(1),observed)
        self.assertEqual(changed,[True]);self.assertEqual(self.raw_rows(contexts),before)
        self.assertEqual(self.task(self.members[0]),first);self.assertEqual(self.task(self.members[1]),peer)
        self.assertEqual(len(self.linked_closure_candidates(contexts[1],refs[1])),1)
        with self.assertRaises(StartupError):self.api._observe_closure(contexts,refs[1])
        with patch.object(self.api,'_capture',side_effect=AssertionError('Historical replay captured current readiness')):
            status=state.task_status(self.members[0].scope,'codex','parent')
            replay=self.api.close_task(self.members[0].scope,self.linked_closure_request(0),self.api._observe_closure(contexts,refs[0]))['task']
        self.assertEqual(status['task'],first);self.assertTrue(status['historical']['historical']);self.assertFalse(status['historical']['current'])
        self.assertEqual(replay,first)

    def test_linked_safe_closure_late_peer_change_preserves_committed_history(self):self.linked_closure_late_change('peer')

    def test_linked_safe_closure_late_source_change_preserves_committed_history(self):self.linked_closure_late_change('source')

    def linked_closure_pending_protection(self,kind):
        _,_,_,contexts,refs=self.linked_closure_fixture();before=[self.task(f) for f in self.members]
        observed=self.api._observe_closure(contexts,refs[0])
        with patch.object(state,'_close_lifecycle',side_effect=RuntimeError('fixture: before lifecycle publication')),self.assertRaises(RuntimeError):
            self.api.close_task(self.members[0].scope,self.linked_closure_request(0),observed)
        candidate=self.linked_closure_candidates(contexts[0],refs[0])[0];path=Path(candidate['metadata']['managed']['path'])
        if kind=='stale':
            f=self.members[0];state.start_task(f.scope,dict(client='codex',session_id='later-owner',task_id='later-task',scope_ref='user:later',mode='editable',decision_ref='user:accepted'))
        elif kind=='substituted':
            replacement=path.with_name(path.name+'.replacement');replacement.write_bytes(path.read_bytes());replacement.chmod(0o400);os.replace(replacement,path)
        else:
            lookalike=path.with_name('0'*32+'.json');lookalike.write_bytes(path.read_bytes());lookalike.chmod(0o400)
        with self.assertRaises(StartupError):self.api._observe_closure(contexts,refs[0])
        self.assertEqual([self.task(f) for f in self.members],before)
        with self.api._context_database(contexts[0]) as db:
            self.assertEqual(state._metadata(db,candidate['reference']['name']),candidate['metadata'])
        self.assertEqual(candidate['metadata']['created_at'],before[0]['lifecycle']['created_at']);self.assertIsNone(candidate['metadata']['closed_at'])

    def test_linked_safe_closure_stale_pending_candidate_stays_protected(self):self.linked_closure_pending_protection('stale')

    def test_linked_safe_closure_substituted_pending_candidate_stays_protected(self):self.linked_closure_pending_protection('substituted')

    def test_linked_safe_closure_unregistered_candidate_lookalike_stays_protected(self):self.linked_closure_pending_protection('lookalike')

    def test_linked_safe_closure_foreign_recovery_raw_root_stays_protected(self):
        from runtime import changes,onboarding
        from tests.test_changes import ScopedChangesTests
        _,_,source,contexts,refs=self.linked_closure_fixture();before=self.raw_rows(contexts)
        other=ScopedChangesTests(methodName='runTest');other.setUp();self.addCleanup(other.doCleanups);request=other.scoped_request()
        for repository in request['manifest']['enrollment']['record']['repositories']:
            for checkout in repository['checkouts']:checkout['clients'][0]['configuration']['runtime']=dict(schema_version=3,state_dir=str(contexts[0].directory))
        request['approval']['manifest_digest']=onboarding._digest(request['manifest']);self.assertEqual(changes._run_scoped(other.directory,request,'apply')['exit_code'],0)
        independent=changes._observe_recovery_source(other.directory,changes._load_journal(other.directory),contexts,refs)
        for context in contexts:
            with self.api._context_database(context,write=True) as db:self.api._register_recovery_source(None,db,independent,context=context)
        recovery=changes.inspect_lifecycle_recovery(source.content['authorities'],refs);self.assertTrue(recovery['complete'])
        self.assertTrue(any(edge['kind']=='task' and edge['reference'] in refs and edge['need']=='raw' for edge in recovery['requirements']))
        with self.assertRaises(StartupError):self.api._observe_closure(contexts,refs[0])
        self.assertEqual(self.raw_rows(contexts),before)

    def test_linked_safe_closure_changed_prior_lifecycle_envelope_rejects(self):
        _,_,_,contexts,refs=self.linked_closure_fixture()
        first=self.api.close_task(self.members[0].scope,self.linked_closure_request(0),self.api._observe_closure(contexts,refs[0]))['task']
        corrupt=self.api._canonical_plain(self.api._canonical_freeze(first));corrupt['lifecycle']['closure']['dependency_digest']='0'*64
        with self.api._context_database(contexts[0],write=True) as db:
            db.execute('update tasks set data=? where scope_id=? and client=? and session_id=? and task_id=?',
                (json.dumps(corrupt),*(refs[0][key] for key in ('scope_id','client','session_id','task_id'))))
        with self.assertRaises(StartupError):self.api._observe_closure(contexts,refs[1])
        self.assertIsNone(self.task(self.members[1])['lifecycle']['safe_closed_at'])
        self.assertEqual(state.task_status(self.members[0].scope,'codex','parent')['historical']['status'],'unavailable')

    def test_linked_safe_closure_sequential_members_preserves_raw_history_and_recovery(self):
        from runtime import changes
        pointer,_,source,contexts,refs=self.preparation_fixture()
        observed=self.api._observe_linked_preparation(pointer,self.api._canonical_plain(source.content['authorities']))
        self.assertTrue(self.api._prepare_linked_closure(observed)['complete'])
        released=changes._register_recovery_release(changes._observe_recovery_release(source.content['authorities'],dict(source.content['identity'])))
        self.assertTrue(released['complete'],released)
        original=[self.task(f) for f in self.members];raw=self.raw_rows(contexts);compacts=[]
        for index,(f,ref) in enumerate(zip(self.members,refs)):
            task=original[index]
            request={key:task[key] for key in ('client','session_id','task_id','scope_ref')}
            request.update(expected_revision=task['revision'],expected_pins=task['pins'])
            closure=self.api._observe_closure(contexts,ref)
            closed=self.api.close_task(f.scope,request,closure)['task'];compacts.append(closed['lifecycle']['compact'])
            self.assertIsNotNone(closed['lifecycle']['safe_closed_at'])
            self.assertEqual({k:v for k,v in closed.items() if k!='lifecycle'},{k:v for k,v in task.items() if k!='lifecycle'})
            self.assertEqual(closed['lifecycle']['created_at'],task['lifecycle']['created_at'])
            self.assertTrue(changes.inspect_lifecycle_recovery(source.content['authorities'],refs)['complete'])
            for before,after in zip(raw,self.raw_rows(contexts)):
                self.assertEqual({k:v for k,v in after.items() if k!='tasks'},{k:v for k,v in before.items() if k!='tasks'})
        first=self.task(self.members[0]);task=original[0]
        replay=self.api.close_task(self.members[0].scope,{key:task[key] for key in ('client','session_id','task_id','scope_ref')}|
            dict(expected_revision=task['revision'],expected_pins=task['pins']),self.api._observe_closure(contexts,refs[0]))['task']
        self.assertEqual(replay,first)
        for context,ref in zip(contexts,refs):
            historical=self.api._observe_closure(contexts,ref)
            with self.api._context_database(context,write=True) as db,self.assertRaises(StartupError):state.retire_closed(db,ref,historical)
        self.assertEqual(compacts,[self.task(f)['lifecycle']['compact'] for f in self.members])

    def preparation_reader_fixture(self):
        pointer=self.verify()['verification'];authorities=self.preparation_stops(pointer)
        observed=self.api._observe_linked_preparation(pointer,authorities)
        prepared=self.api._prepare_linked_closure(observed);self.assertTrue(prepared['complete'])
        facts=self.api._canonical_plain(observed.facts);member=facts['members'][0]
        receipt=self.api._preparation_receipt(facts,member['reference'])
        certificate=dict(member['certificate'],preparation=dict(reference=receipt['artifact'],
            component_digest=self.api._digest(facts),authorities=authorities))
        return pointer,authorities,facts,self.api._reference_context(member['reference']['authority']),certificate

    def test_preparation_reuse_reader_lifetime_authority_pointer_and_default_semantics(self):
        from runtime import changes
        pointer,authorities,facts,context,certificate=self.preparation_reader_fixture()
        with self.api._linked_stop_guards(pointer,authorities),self.api._context_database(context) as db:
            with self.api._linked_preparation_reader(authorities) as reader, \
                    patch.object(self.api,'_linked_preparation_facts',wraps=self.api._linked_preparation_facts) as captures:
                for _ in range(2):changes._check_stopped_certificate(context,db,certificate,preparation_reader=reader)
                self.assertEqual(captures.call_count,1)
                wrong=self.api._canonical_plain(self.api._canonical_freeze(certificate));wrong['preparation']['reference']['digest']='0'*64
                with self.assertRaises(state.StateError):changes._check_stopped_certificate(context,db,wrong,preparation_reader=reader)
                wrong=self.api._canonical_plain(self.api._canonical_freeze(certificate));wrong['preparation']['component_digest']='0'*64
                with self.assertRaises(state.StateError):changes._check_stopped_certificate(context,db,wrong,preparation_reader=reader)
                wrong=self.api._canonical_plain(self.api._canonical_freeze(certificate));wrong['preparation']['authorities']=authorities[:1]
                with self.assertRaises(state.StateError):changes._check_stopped_certificate(context,db,wrong,preparation_reader=reader)
                with self.api._linked_preparation_reader(authorities):
                    with self.assertRaises(state.StateError):changes._check_stopped_certificate(context,db,certificate,preparation_reader=reader)
                reader.finish()
            self.assertFalse(reader.active);self.assertEqual(reader.entries,{})
            with self.assertRaises(state.StateError):changes._check_stopped_certificate(context,db,certificate,preparation_reader=reader)
            with self.api._linked_preparation_reader(authorities[:1]) as foreign:
                with self.assertRaises(state.StateError):changes._check_stopped_certificate(context,db,certificate,preparation_reader=foreign)
            with patch.object(self.api,'_linked_preparation_facts',wraps=self.api._linked_preparation_facts) as captures:
                for _ in range(2):changes._check_stopped_certificate(context,db,certificate)
                self.assertEqual(captures.call_count,2,'Absent reader must retain full semantic validation')
            with self.api._linked_preparation_reader(authorities) as fresh, \
                    patch.object(self.api,'_linked_preparation_facts',wraps=self.api._linked_preparation_facts) as captures:
                changes._check_stopped_certificate(context,db,certificate,preparation_reader=fresh);fresh.finish()
                self.assertEqual(captures.call_count,1,'A separate inspection must capture again')
        from tests.test_state import canonical_scope
        extra=EvidenceTests(methodName='runTest');extra.setUp();self.addCleanup(extra.doCleanups)
        extra.scope=canonical_scope(extra.scope);state.start_task(extra.scope,extra.identity|dict(mode='editable',decision_ref='user:accepted'))
        expanded=[*authorities,self.api._canonical_plain(self.api._evidence_context(extra.scope).authority_set[0])]
        superset=self.api._canonical_plain(self.api._canonical_freeze(certificate));superset['preparation']['authorities']=expanded
        incomplete=self.api._canonical_plain(self.api._canonical_freeze(certificate));incomplete['preparation']['authorities']=[authorities[0],expanded[-1]]
        with self.api._linked_stop_guards(pointer,expanded),self.api._context_database(context) as db:
            for valid in (certificate,superset):changes._check_stopped_certificate(context,db,valid)
            with self.assertRaises(state.StateError):changes._check_stopped_certificate(context,db,incomplete)
            with self.api._linked_preparation_reader(expanded) as reader, \
                    patch.object(self.api,'_linked_preparation_facts',wraps=self.api._linked_preparation_facts) as captures:
                for valid in (certificate,superset):changes._check_stopped_certificate(context,db,valid,preparation_reader=reader)
                self.assertEqual(captures.call_count,1,'Complete held set and aggregate identify the capture across valid supersets')
                with self.assertRaises(state.StateError):changes._check_stopped_certificate(context,db,incomplete,preparation_reader=reader)
                reader.finish()

    def preparation_reader_late_change(self,kind):
        from runtime import changes
        pointer,authorities,facts,context,certificate=self.preparation_reader_fixture()
        with self.api._linked_stop_guards(pointer,authorities),self.api._context_database(context) as db, \
                self.api._linked_preparation_reader(authorities) as reader:
            changes._check_stopped_certificate(context,db,certificate,preparation_reader=reader)
            if kind=='peer':(self.members[1].repo/'late-reader-input.py').write_text('changed = True\n')
            elif kind=='source':
                path=Path(facts['sources'][0]['metadata']['managed']['path'])
            else:
                receipt=self.api._preparation_receipt(facts,facts['members'][1]['reference'])
                peer_context=self.api._reference_context(receipt['authority'])
                path=peer_context.directory/'evidence'/receipt['artifact']['name']
            if kind!='peer':
                replacement=path.with_name(path.name+'.replacement');replacement.write_bytes(path.read_bytes()+b'\n');os.replace(replacement,path)
            with self.assertRaises((state.StateError,StartupError)):reader.finish()
        self.assertFalse(reader.active);self.assertEqual(reader.entries,{})

    def test_preparation_reuse_late_peer_change_rejected(self):self.preparation_reader_late_change('peer')

    def test_preparation_reuse_late_source_change_rejected(self):self.preparation_reader_late_change('source')

    def test_preparation_reuse_late_receipt_change_rejected(self):self.preparation_reader_late_change('receipt')

    def test_preparation_reuse_inspection_captures_once_and_preserves_requirements_and_rows(self):
        from runtime import changes
        pointer,_,source,contexts,refs=self.preparation_fixture()
        self.api._prepare_linked_closure(self.api._observe_linked_preparation(pointer,self.api._canonical_plain(source.content['authorities'])))
        released=changes._register_recovery_release(changes._observe_recovery_release(source.content['authorities'],dict(source.content['identity'])))
        self.assertTrue(released['complete'],released);before=self.raw_rows(contexts)
        with patch.object(self.api,'_linked_preparation_facts',wraps=self.api._linked_preparation_facts) as captures, \
                patch.object(self.api,'_artifact',side_effect=AssertionError('Inspection attempted artifact registration')):
            inspected=changes.inspect_lifecycle_recovery(source.content['authorities'],refs)
        self.assertTrue(inspected['complete'],inspected);self.assertEqual(self.raw_rows(contexts),before)
        for ref in refs:
            self.assertTrue(any(r['kind']=='task' and r['reference']==ref and r['need']=='identity' for r in inspected['requirements']))
            self.assertFalse(any(r['kind']=='task' and r['reference']==ref and r['need']=='raw' for r in inspected['requirements']))
        print('INSPECTION_PREPARATION_FACTS_CAPTURES '+str(captures.call_count),flush=True)
        self.assertEqual(captures.call_count,1,'One read-only inspection must fully capture each actual prepared component once')
        readers=[];factory=self.api._linked_preparation_reader
        from contextlib import contextmanager
        @contextmanager
        def record(authorities):
            with factory(authorities) as reader:
                readers.append(reader);yield reader
        with changes._authority_guards([context.directory for context in contexts],observe=True), \
                patch.object(self.api,'_linked_preparation_reader',side_effect=record), \
                patch.object(self.api,'_linked_preparation_facts',wraps=self.api._linked_preparation_facts) as captures:
            partial=changes._inspect_lifecycle_recovery_guarded(source.content['authorities'][:1],refs)
        self.assertFalse(partial['complete']);self.assertTrue(partial['discovered_authorities'])
        self.assertEqual(captures.call_count,0);self.assertFalse(readers[-1].active);self.assertEqual(readers[-1].entries,{})
        with patch.object(self.api,'_linked_preparation_reader',side_effect=record), \
                patch.object(self.api,'_linked_preparation_facts',wraps=self.api._linked_preparation_facts) as captures:
            again=changes.inspect_lifecycle_recovery(source.content['authorities'],refs)
        self.assertEqual(again,inspected);self.assertEqual(captures.call_count,1)
        self.assertFalse(readers[-1].active);self.assertEqual(readers[-1].entries,{})
        finish=self.api._PreparationReader.finish;changed=[]
        def late_peer(reader):
            (self.members[1].repo/'late-foreign-stop-input.py').write_text('changed = True\n');changed.append(True)
            return finish(reader)
        with patch.object(self.api,'_linked_preparation_reader',side_effect=record), \
                patch.object(self.api._PreparationReader,'finish',late_peer):
            stale=changes.inspect_lifecycle_recovery(source.content['authorities'],refs)
        self.assertTrue(changed,'Mutation must follow final source/journal rereads')
        self.assertFalse(stale['complete']);self.assertTrue(stale['blockers']);self.assertEqual(self.raw_rows(contexts),before)
        self.assertFalse(readers[-1].active);self.assertEqual(readers[-1].entries,{})

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
        self.current_record(extra)
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

    def test_observer_cannot_rewrite_original_linked_producer_request(self):
        observations=self.observations();original=observations['observe']
        request=self.selected.request(purpose='completion')
        def observe(facts):
            request['purpose']='merge-evidence'
            return original(facts)
        observations['observe']=observe
        result=self.api.verify_linked(self.selected.scope,request,observations)
        self.assertEqual(request['purpose'],'merge-evidence')
        self.assertTrue(result['implementation_verified'])
        self.assertEqual(result['task']['state'],'ready')
        retained=self.api._linked_source(result['verification'])
        self.assertEqual(retained['purpose'],'completion')
        selected=next(row for row in retained['members'] if row['task']==retained['selected'])
        verification=self.api._read(self.selected.scope,selected['verification'])
        self.assertEqual(verification['purpose'],'completion')

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
