"""Real producer observations for the future-only D4 historical witness contract."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from runtime import evidence, recovery_uses, state
from tests import test_changes as changes_tests


class HistoricalWitnessTests(unittest.TestCase):
    def setUp(self):
        self.fixture = changes_tests.ScopedChangesTests(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.addCleanup(self.fixture.tearDown)

    def observe_before_storage(self):
        """Acquire a real source while the finite host deliberately omits its historical subject."""
        fixture = self.fixture
        request, scope, context, task, shared = fixture.historical_shared_consumer()
        identity={k:task[k] for k in ('client','session_id','task_id','scope_ref')}
        proof=dict(version=1,kind='stopped-writer-reconciliation',identity=identity,
            expected_revision=task['revision'],expected_pins=task['pins'],observed_turn_id=task['turn_id'],
            stopped=True,descendants_stopped=True,attempt_ids=[],observation_ref='fixture:stopped',coordinator_ref='fixture:owner')
        path=fixture.directory/'historical-witness-stop.json';raw=json.dumps(proof,sort_keys=True).encode();path.write_bytes(raw);path.chmod(0o600)
        retired=state.retire_task(scope,identity|dict(expected_revision=task['revision'],expected_pins=task['pins'],
            reason='Observed stopped writer and descendants',reference='fixture:native-retirement',
            stop_proof=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest())))['task']
        self.assertEqual(retired['pins'],task['pins']);self.assertEqual(retired['state'],'cancelled')
        reference=retired['retirement']['proof']
        captured = []
        observe = fixture.changes._observe_recovery_source
        def observe_actual(*args, **kwargs):
            source = observe(*args, **kwargs)
            captured.append(source)
            return source
        before = shared.read_bytes()
        from tests import test_onboarding_host
        from scripts.onboard_coordinator import run_verified_operation
        contexts=tuple(evidence._evidence_context(existing) for existing in fixture.d4_bookkeeping_scopes)
        decision=test_onboarding_host.OnboardingHostTests.decision(self,fixture,request,'apply',contexts)
        decision['bookkeeping_scope']['subjects']=[subject for subject in decision['bookkeeping_scope']['subjects']
            if not all(subject[key]==task['accepted_identity'][key] for key in ('project_id','repository_id','checkout_id','client'))]
        with patch.object(fixture.changes, '_observe_recovery_source', side_effect=observe_actual):
            result = run_verified_operation(decision,fixture.directory,request)
        self.assertNotEqual(result['exit_code'], 0, result)
        self.assertEqual(shared.read_bytes(), before)
        self.assertTrue(captured, result)
        return request,scope,context,task,shared,reference,captured

    def test_actual_source_preserves_original_stop_without_omitted_current_consent(self):
        fixture=self.fixture
        request,scope,context,task,shared,reference,captured=self.observe_before_storage()
        content = evidence._canonical_plain(captured[-1].content)
        self.assertIn('use_contract', content)
        contract = recovery_uses.validate(content['use_contract'])
        historical = [root for root in contract['roots'] if root['purpose'] == 'historical-stop']
        self.assertEqual(len(historical), 1)
        original = dict(authority=evidence._canonical_plain(context.authority_set[0]),
            scope_id=state._scope_id(scope), client='codex', session_id='historical-consumer', task_id='historical-consumer')
        self.assertEqual(historical[0]['task'], original)
        self.assertEqual(historical[0]['proof'], dict(authority=original['authority'], artifact=reference))
        action = next(action for action in request['manifest']['actions'] if action['owner']['kind'] == 'project')
        self.assertEqual(historical[0]['effect'], dict(action_id=action['id'], path=action['effects'][0]['path']))
        self.assertEqual(next(row for row in content['tasks'] if row['reference'] == original)['pins'], task['pins'])
        self.assertTrue(any(row['dependency'] == dict(kind='artifact', reference=historical[0]['proof'])
            and row['purpose'] == 'retention-only' for row in contract['edges']))
        # A supported cancelled witness keeps original pins across an installed package upgrade.
        with tempfile.TemporaryDirectory(prefix='vcw-historical-upgrade-') as temporary:
            upgraded = Path(temporary)
            for directory in ('runtime', 'policies'):
                shutil.copytree(state.PACKAGE / directory, upgraded / directory)
            (upgraded / 'scripts').mkdir()
            shutil.copyfile(state.PACKAGE / 'scripts/workflow.py', upgraded / 'scripts/workflow.py')
            with (upgraded / 'runtime/state.py').open('a') as stream:
                stream.write('\n# Disposable upgraded runtime source.\n')
            with (upgraded / 'policies/00-index.md').open('a') as stream:
                stream.write('\nDisposable upgraded policy source.\n')
            with evidence._context_database(context) as db:
                baseline = evidence._canonical_plain(state._source_baseline(None, db, context=context))
                original_task = state._task(db, original['scope_id'], original['client'], original['session_id'], original['task_id'])
            with patch.object(state, 'PACKAGE', upgraded):
                self.assertNotEqual(state.runtime_fingerprint(), task['pins']['runtime_digest'])
                self.assertNotEqual(fixture.changes.policy_digest(upgraded), task['pins']['policy_digest'])
                with evidence._context_database(context) as db:
                    self.assertEqual(fixture.changes._historical_recovery_roots(
                        request['manifest'], context, db, original_task, original), historical)
                    self.assertEqual(evidence._canonical_plain(state._source_baseline(None, db, context=context)), baseline)
                    self.assertEqual(state._task(db, original['scope_id'], original['client'], original['session_id'], original['task_id']), original_task)
                with self.assertRaisesRegex(fixture.changes.StartupError, 'Scoped plan/package/source pins changed'):
                    fixture.changes._validate_scoped(request, fixture.plan())
        # A genuine independent named selection must survive owner/reference deduplication.
        reasons = []
        journal = fixture.changes._load_journal(fixture.directory)
        tasks, assignments, artifacts, foreign = fixture.changes._collect_recovery_references(
            journal['manifest'], captured[-1].contexts, (original,), use_roots=reasons)
        self.assertEqual(foreign, [])
        mixed = dict(content, tasks=tasks, assignments=assignments, artifacts=artifacts)
        mixed_contract = fixture.changes._build_recovery_uses(mixed, captured[-1].contexts, reasons)
        self.assertEqual({root['purpose'] for root in mixed_contract['roots']}, {'historical-stop', 'content'})
        self.assertEqual({row['purpose'] for row in mixed_contract['edges']
            if row['parent'] is None and row['dependency'] == dict(kind='task', reference=original)},
            {'retention-only', 'content'})
        # Exercise the real cut producer without granting or registering the observed source.
        with evidence._context_database(context) as db:
            certificate = fixture.changes._stopped_certificate(context, db,
                next(row for row in content['tasks'] if row['reference'] == original))
        cut = fixture.changes._cut_recovery_content(content, [certificate], captured[-1].contexts)
        self.assertEqual(cut['version'], 2)
        self.assertEqual(cut['use_contract']['roots'], contract['roots'])
        self.assertEqual(cut['use_contract']['edges'], [])
        self.assertEqual(cut['tasks'], [])
        self.assertEqual(cut['stopped'][0]['pins'], task['pins'])
        self.assertEqual(content, evidence._canonical_plain(captured[-1].content))


if __name__ == '__main__': unittest.main()
