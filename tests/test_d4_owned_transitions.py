"""Internal fixture proofs for owned suspension and unrelated durable heads."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from runtime import delegation, evidence, onboarding, state
from runtime.startup import PROJECT_FILE
from tests import test_changes


class D4OwnedTransitionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_changes.ScopedChangesTests(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.changes = self.fixture.changes

    def _host(self, facts, grants):
        class Host:
            def acquire_d4_bookkeeping(self, acquired, issue):
                facts.append(evidence._canonical_plain(acquired))
                grant = issue(acquired)
                grants.append(grant)
                return grant
        return self.changes._bootstrap_d4_host(Host(), issuer=self.changes._D4_HOST_BOOTSTRAP_ISSUER)

    def _fresh_request(self, label, *, runtime=None):
        fixture = self.fixture
        fixture.directory = fixture.base / label
        fixture.directory.mkdir(mode=0o700)
        for item in fixture.record['toolkit']['files']:
            raw = Path(item['local_path']).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), item['sha256'])
            local = fixture.directory / item['path']
            local.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            local.write_bytes(raw); local.chmod(0o600)
            item['local_path'] = str(local)
        fixture.source = Path(fixture.record['toolkit']['files'][0]['local_path'])
        onboarding.inspect_project(fixture.repo, fixture.directory, fixture.project_record())
        proposal = fixture.scoped_proposal()
        action = proposal['assessments']['repositories'][0]['actions'][0]
        action['text'] = 'product rules\n' + label + '\n'
        action['after'] = hashlib.sha256(action['text'].encode()).hexdigest()
        onboarding.record_plan(fixture.directory, proposal)
        request = fixture.scoped_request(existing=True)
        request['manifest']['transaction_id'] = label
        entry = request['manifest']['enrollment']['record']['repositories'][0]['checkouts'][0]['clients'][0]
        entry['configuration']['runtime'] = runtime
        request['approval']['manifest_digest'] = onboarding._digest(request['manifest'])
        return request

    def _stopped_operation(self, scope):
        owner = dict(client='codex', session_id='owned-source', task_id='owned-source', scope_ref='fixture:owned-source')
        state.start_task(scope, owner | dict(mode='editable', decision_ref='fixture:owned-decision'))
        prepared = delegation.reserve_coordinator(scope, owner | dict(expected_revision=1, dispatch_id='owned-source-operation',
            claims=[dict(kind='path', key=str(scope.repository_root / 'AGENTS.md'), mode='write')],
            operation=dict(id='owned-source-operation', kind='coordinator-work'), reason='Retained task-owned support',
            ownership_ref='fixture:owned-operation', stop_conditions=['Stop after observation']))
        with state._database(scope) as db:
            task = state._task(db, state._scope_id(scope), owner['client'], owner['session_id'], owner['task_id'])
            row = next(row for row in delegation._ledger(scope, db) if row['id'] == prepared['attempt_id'])
        facts = dict(operation_id='owned-source-operation', operation_digest=row['body']['operation']['digest'],
            claims_digest=evidence._digest(row['data']['claims']))
        reference = evidence._artifact(scope, dict(facts, observation='Actual operation stopped before the owned update'),
            owner=evidence._artifact_owner(scope, task))
        proof = dict(version=2, kind='coordinator-operation-reconciliation', identity=owner, expected_pins=task['pins'],
            expected_revision=task['revision'], scope_id=row['owner']['scope_id'], attempt_id=row['id'],
            dispatch_id=row['owner']['dispatch_id'], assignment_digest=row['data']['assignment']['digest'],
            decision_ref=task['decision_ref'], operation_evidence=reference, resource_observations=reference,
            operation_stopped=True, operation_descendants_stopped=True, observation_ref='fixture:owned-stop',
            coordinator_ref='fixture:independent-owned-observer', **facts)
        path = self.fixture.directory / 'owned-operation-stop.json'
        raw = json.dumps(proof).encode(); path.write_bytes(raw); path.chmod(0o600)
        delegation.reconcile_assignment(scope, owner | dict(expected_revision=task['revision'], attempt_id=row['id'],
            host_proof=dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest()), assessment=dict(outcome='cancelled',
                changed_paths=[], result_assessment='Stopped actual operation', partial_change_assessment='No remaining effects',
                evidence=['fixture:owned-inspection'], coordinator_ref='fixture:independent-owned-observer')))
        task = state.task_status(scope, owner['client'], owner['session_id'])['task']
        stop = dict(version=1, kind='stopped-writer-reconciliation', identity=owner, expected_revision=task['revision'],
            expected_pins=task['pins'], observed_turn_id=task['turn_id'], stopped=True, descendants_stopped=True,
            attempt_ids=[], observation_ref='fixture:owned-task-stop', coordinator_ref='fixture:independent-owned-observer')
        path = self.fixture.directory / 'owned-task-stop.json'
        raw = json.dumps(stop).encode(); path.write_bytes(raw); path.chmod(0o600)
        stopped = state.retire_task(scope, owner | dict(expected_revision=task['revision'], expected_pins=task['pins'],
            reason='Stopped before owned update', reference='fixture:owned-retirement',
            stop_proof=dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest())))['task']
        self.assertEqual(stopped['state'], 'cancelled')
        with state._database(scope) as db:
            self.assertTrue(all(row['data']['status'] == 'settled' for row in delegation._ledger(scope, db)))
        return reference, stopped

    def _markers(self, context, project_root):
        canonical = Path(self.changes.LOCK_ROOT) / ('canonical-' + hashlib.sha256(
            ('destination:' + str(project_root / PROJECT_FILE)).encode()).hexdigest() + '.lock')
        return [*self.changes._authority_locations([context.directory]), canonical]

    def test_owned_suspended_postimage_reacquires_and_registers_existing_task_body(self):
        fixture = self.fixture
        # These existing qualification inputs are synthetic; no native execution is asserted.
        active = fixture.activate_request(fixture.scoped_request())
        staged = self.changes._run_scoped(fixture.directory, active, 'apply')
        self.assertEqual(staged['exit_code'], 2, staged)
        self.assertFalse(staged['qualified'], staged)
        self.assertTrue(any('Fresh scoped adoption qualification observations are required' in row['reason']
            for row in staged['blocked']), staged)
        self.assertFalse((fixture.repo / PROJECT_FILE).exists())
        active = fixture.observe_active(active)
        applied = self.changes._run_scoped(fixture.directory, active, 'resume')
        self.assertEqual(applied['exit_code'], 0, applied)
        self.assertTrue(applied['qualified'], applied)
        prior = json.loads((fixture.repo / PROJECT_FILE).read_text())
        self.assertEqual(prior, active['manifest']['enrollment']['record'])
        journal = self.changes._load_journal(fixture.directory)
        scopes = self.changes._scoped_qualification(journal, active['observations'], prior, published=True)
        self.assertEqual(len(scopes), 1)
        scope = scopes[0]
        self.assertEqual(scope.authority_revision, prior['revision'])
        self.assertEqual(evidence._canonical_plain(scope.qualification_provenance)['kind'], 'trusted-coordinator')
        self.assertFalse((scope.runtime.state_dir / 'runtime.sqlite3').exists())
        with state._database(scope, write=True, initialize=True):
            pass
        body, task = self._stopped_operation(scope)
        context = evidence._evidence_context(scope)
        with evidence._context_database(context) as db:
            original = evidence._managed_artifact(None, body, context=context, db=db)
        request = self._fresh_request('owned-suspended-update', runtime=dict(schema_version=3, state_dir=str(context.directory)))
        before = {a['id']: self.changes._fingerprint(Path(a['owner']['root']), a['effects'][0]['path'])
            for a in request['manifest']['actions']}
        self.assertTrue(self.changes._validate_scoped(request, fixture.plan())[3])
        facts, grants, interruptions = [], [], []
        real_publish = self.changes._scoped_publish

        def interrupt_after_owned_publish(path, journal, phase, record):
            real_publish(path, journal, phase, record)
            if phase == 'suspended':
                current = json.loads((scope.project_root / PROJECT_FILE).read_text())
                self.assertEqual(current, self.changes._scoped_suspended(journal))
                self.assertTrue(self.changes._scoped_owned_authority(journal))
                self.assertEqual(journal['enrollment']['postimages'][-1]['status'], 'published')
                interruptions.append(copy.deepcopy(current))
                raise RuntimeError('fixture interruption after durable owned suspension')

        with self._host(facts, grants) as host:
            with patch.object(self.changes, '_scoped_publish', side_effect=interrupt_after_owned_publish):
                with self.assertRaisesRegex(RuntimeError, 'durable owned suspension'):
                    self.changes._run_scoped(fixture.directory, request, 'apply', host=host)
        self.assertEqual(len(interruptions), 1)
        self.assertEqual(len(grants), 1)
        for action in request['manifest']['actions']:
            self.assertEqual(self.changes._fingerprint(Path(action['owner']['root']), action['effects'][0]['path']), before[action['id']])
        markers = self._markers(context, scope.project_root)
        self.assertTrue(all(self.changes._authority_owner(marker) is not None for marker in markers))
        with evidence._context_database(context) as db:
            baseline = evidence._canonical_plain(state._source_baseline(None, db, context=context))
            first_edge = next(edge for edge in baseline['dependencies'] if edge['reference']['identity'] == facts[0]['identity'])
            first_head = first_edge['reference']['artifact']
            original_age = state._metadata(db, first_head['name'])['created_at']
        real_register = evidence._register_recovery_source
        suspended_registrations = []

        def observe_registration(actual_scope, db, source, *, context=None):
            reference = real_register(actual_scope, db, source, context=context)
            current = json.loads((scope.project_root / PROJECT_FILE).read_text())
            if current == interruptions[0]:
                current_journal = self.changes._load_journal(fixture.directory)
                self.assertTrue(self.changes._scoped_owned_authority(current_journal))
                key = tuple(task['accepted_identity'][k] for k in ('repository_id', 'checkout_id', 'client'))
                self.assertTrue(self.changes._d4_owned_transition(current_journal, key))
                qualified = dict(authority=evidence._canonical_plain(context.authority_set[0]), artifact=body)
                self.assertIn(qualified, evidence._canonical_plain(source.content)['artifacts'])
                self.assertTrue(any(item['reference'] == original[0]['owner']['task'] for item in source.content['tasks']))
                self.assertEqual(state._metadata(db, reference['name'])['created_at'], original_age)
                suspended_registrations.append(evidence._canonical_plain(reference))
            return reference

        with self._host(facts, grants) as host:
            with patch.object(evidence, '_register_recovery_source', side_effect=observe_registration):
                resumed = self.changes._run_scoped(fixture.directory, request, 'resume', host=host)
        self.assertEqual(resumed['exit_code'], 0, resumed)
        self.assertEqual(len(suspended_registrations), 1)
        self.assertEqual(len(grants), 3)
        self.assertEqual(facts[-1]['journal']['state'], 'applied')
        self.assertEqual(len({id(grant.acquisition) for grant in grants}), len(grants))
        for grant in grants:
            with self.assertRaises(self.changes.StartupError): self.changes._check_d4_grant(grant)
        final_journal = self.changes._load_journal(fixture.directory)
        self.assertEqual(sum(row['phase'] == 'suspended' for row in final_journal['enrollment']['postimages']), 1)
        self.assertEqual(json.loads((scope.project_root / PROJECT_FILE).read_text()), request['manifest']['enrollment']['record'])
        with evidence._context_database(context) as db:
            self.assertEqual(evidence._managed_artifact(None, body, context=context, db=db), original)
            current_task = state._task(db, state._scope_id(scope), task['client'], task['session_id'], task['task_id'])
            self.assertEqual(current_task['pins'], task['pins'])
            baseline = evidence._canonical_plain(state._source_baseline(None, db, context=context))
            self.assertEqual(len(baseline['dependencies']), 1)
            edge = next(row for row in baseline['dependencies'] if row['reference']['identity'] == facts[0]['identity'])
            final_body = evidence._read(None, edge['reference']['artifact'], context=context, db=db)
            self.assertEqual(final_body['journal']['state'], 'applied')
            self.assertIn(dict(authority=evidence._canonical_plain(context.authority_set[0]), artifact=body),
                evidence._canonical_plain(final_body)['artifacts'])
            history = evidence._recovery_source_history(context, db, edge['reference']['artifact'], facts[0]['identity'])
            self.assertIn(first_head, [dict(reference) for reference, _ in history])
            self.assertIn(suspended_registrations[0], [dict(reference) for reference, _ in history])
            self.assertTrue(all(state._metadata(db, reference['name'])['created_at'] == original_age for reference, _ in history))
        for action in request['manifest']['actions']:
            self.assertEqual(self.changes._fingerprint(Path(action['owner']['root']), action['effects'][0]['path']), action['effects'][0]['after'])
        self.assertTrue(all(self.changes._authority_owner(marker) is None for marker in markers))

    def test_distinct_operation_preserves_genuinely_released_unrelated_edge_and_age(self):
        fixture = self.fixture
        request, _, guidance, context, _ = fixture.d4_reachable_taskless_guidance()
        facts, grants = [], []
        with self._host(facts, grants) as host:
            result = self.changes._run_scoped(fixture.directory, request, 'apply', host=host)
        self.assertEqual(result['exit_code'], 0, result)
        identity = facts[0]['identity']
        with evidence._context_database(context) as db:
            baseline = evidence._canonical_plain(state._source_baseline(None, db, context=context))
            first_head = next(edge['reference']['artifact'] for edge in baseline['dependencies']
                if edge['reference']['identity'] == identity)
            first_age = state._metadata(db, first_head['name'])['created_at']
        observed = self.changes._observe_recovery_release(context.authority_set, identity)
        self.assertTrue(observed.content['stopped'])
        self.assertIn(dict(authority=evidence._canonical_plain(context.authority_set[0]), artifact=guidance),
            evidence._canonical_plain(observed.content)['artifacts'])
        released = self.changes._register_recovery_release(observed)
        self.assertTrue(released['complete'], released)
        with evidence._context_database(context) as db:
            baseline = evidence._canonical_plain(state._source_baseline(None, db, context=context))
            old_edge = next(edge for edge in baseline['dependencies'] if edge['reference']['identity'] == identity)
            head = old_edge['reference']['artifact']
            original = evidence._managed_artifact(None, head, context=context, db=db)
            self.assertNotEqual(head, first_head)
            self.assertEqual(original[0]['created_at'], first_age)
            history = [(dict(ref), dict(body)) for ref, body in evidence._recovery_source_history(context, db, head, identity)]
        second = self._fresh_request('unrelated-edge-update')
        self.assertNotEqual(second['manifest']['transaction_id'], identity['transaction_id'])
        self.assertNotEqual(str(fixture.directory), identity['plan_dir'])
        batches = []
        real_register = evidence._register_recovery_source

        def preserve_original(actual_scope, db, source, *, context=None):
            before = evidence._canonical_plain(state._source_baseline(None, db, context=context))
            self.assertIn(old_edge, before['dependencies'])
            reference = real_register(actual_scope, db, source, context=context)
            after = evidence._canonical_plain(state._source_baseline(None, db, context=context))
            self.assertIn(old_edge, after['dependencies'])
            self.assertEqual(evidence._managed_artifact(None, head, context=context, db=db), original)
            self.assertEqual([(dict(ref), dict(body)) for ref, body in evidence._recovery_source_history(context, db, head, identity)], history)
            self.assertNotEqual(evidence._canonical_plain(source.content)['identity'], identity)
            batches.append(evidence._canonical_plain(reference))
            return reference

        with self._host(facts, grants) as host:
            with patch.object(evidence, '_register_recovery_source', side_effect=preserve_original):
                result = self.changes._run_scoped(fixture.directory, second, 'apply', host=host)
        self.assertEqual(result['exit_code'], 0, result)
        self.assertEqual(len(batches), 2)
        with evidence._context_database(context) as db:
            baseline = evidence._canonical_plain(state._source_baseline(None, db, context=context))
            self.assertEqual(len(baseline['dependencies']), 2)
            self.assertIn(old_edge, baseline['dependencies'])
            new_edge = next(edge for edge in baseline['dependencies'] if edge != old_edge)
            self.assertEqual(new_edge['reference']['identity'], facts[-1]['identity'])
            self.assertEqual(new_edge['reference']['artifact'], batches[-1])
            self.assertEqual(evidence._managed_artifact(None, head, context=context, db=db), original)
            self.assertEqual([(dict(ref), dict(body)) for ref, body in evidence._recovery_source_history(context, db, head, identity)], history)
        self.assertTrue(all(self.changes._authority_owner(marker) is None for marker in self._markers(context, fixture.repo)))


if __name__ == '__main__':
    unittest.main()
