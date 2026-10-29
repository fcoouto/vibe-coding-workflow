"""Real producer observations for the future-only D4 historical witness contract."""
import copy
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

    def test_actual_source_records_original_stop_reason_before_permission_denial(self):
        fixture = self.fixture
        request, scope, context, task, shared = fixture.historical_shared_consumer()
        with evidence._context_database(context, write=True) as db:
            proof = dict(version=1, kind='stopped-writer-reconciliation',
                identity={k: task[k] for k in ('client', 'session_id', 'task_id', 'scope_ref')},
                expected_revision=task['revision'], expected_pins=task['pins'], observed_turn_id=task['turn_id'],
                stopped=True, descendants_stopped=True, attempt_ids=[], observation_ref='fixture:stopped', coordinator_ref='fixture:owner')
            reference = evidence._artifact(scope, proof, owner=evidence._artifact_owner(scope, task), db=db)
            retired = copy.deepcopy(task)
            retired.update(state='cancelled', revision=task['revision'] + 1,
                retirement=dict(proof_digest=reference['digest'], proof=reference,
                    observation_ref='fixture:stopped', coordinator_ref='fixture:owner', previous_revision=task['revision']))
            state._save(db, state._scope_id(scope), retired)
        captured = []
        observe = fixture.changes._observe_recovery_source
        def observe_actual(*args, **kwargs):
            source = observe(*args, **kwargs)
            captured.append(source)
            return source
        before = shared.read_bytes()
        with patch.object(fixture.changes, '_observe_recovery_source', side_effect=observe_actual):
            result = fixture.run_with_d4_host(request, 'apply')
        # The producer half deliberately leaves the existing permission gate closed.
        self.assertNotEqual(result['exit_code'], 0, result)
        self.assertIn('Current D4 source subject enrollment changed', str(result))
        self.assertEqual(shared.read_bytes(), before)
        self.assertTrue(captured, result)
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
        # Exercise the real cut producer without granting or registering the held source.
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
