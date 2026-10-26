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
from runtime.startup import ProjectScope, RuntimeSettings


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
        self.scope = ProjectScope('fixture', self.repo, self.repo / '.git', 'policy', RuntimeSettings(1, self.root / 'state'))
        self.identity = dict(client='codex', session_id='parent', task_id='task', scope_ref='user:task')
        state.start_task(self.scope, self.identity | dict(mode='editable', decision_ref='user:accepted'))
        self.api = importlib.import_module('runtime.evidence')

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

    def review(self, findings=None, coverage=None):
        coverage = coverage or ['general', 'security']
        prepared = self.api.prepare_review(self.scope, self.request(coverage=coverage, criteria=['works'],
            assignment='Review read-only; inspect app.py and callers. Return the bound report.'))
        attempt = prepared['attempt_id']
        binding = self.api.prepared_native_review(self.scope, attempt)
        report = dict(version=1, attempt_id=attempt, assignment_digest=binding['assignment_digest'],
            candidate_digest=binding['candidate_digest'], coverage=coverage, findings=findings or [], limitations=[])
        receipt = dict(version=1, mechanism='codex-persisted-history', native_version='0.163.0', parent_session_id='parent',
            parent_turn_id='turn', spawn_item_id='spawn', reviewer_id='reviewer', review_turn_id='child-turn',
            report_item_id='final', assignment_digest=report['assignment_digest'], candidate_digest=report['candidate_digest'],
            report_digest=hashlib.sha256(json.dumps(report).encode()).hexdigest(), requested_model=None, requested_effort=None)
        with patch('runtime.adapters.codex.collect_native_review', return_value={'receipt': receipt, 'report': report}, create=True):
            self.api.collect_review(self.scope, self.request(attempt_id=attempt, parent_turn_id='turn', spawn_item_id='spawn'))
        return self.api.assess_review(self.scope, self.request(attempt_id=attempt, assessment=dict(coverage=coverage,
            criteria=['works'], qualification='Qualified in runtime/security review', independence='Different observed native child',
            semantic_coverage='Inspected requirements, code and failure paths', dispositions=[], decision_refs=['user:accepted'])))

    def verify(self, **fields):
        return self.api.verify_completion(self.scope, self.request(purpose='completion', **fields))

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
                prepared = self.api.prepare_review(self.scope, other | dict(expected_revision=2, coverage=['general'],
                    criteria=['works'], assignment='Read-only concurrent review.'))
                inserted.append(prepared['attempt_id'])
            return result
        with patch.object(self.api, '_blockers', side_effect=blockers):
            result = self.verify()
        self.assertFalse(result['verified'])
        self.assertNotEqual(result['task']['state'], 'ready')
        self.assertTrue(any('history' in b for b in result['blockers']))

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
        self.identity['task_id'] = 'replacement'
        state.start_task(self.scope, self.identity | dict(mode='editable', decision_ref='user:accepted',
            replaces=dict(task_id='task', expected_revision=old_revision)))
        self.plan()
        self.checked()
        self.review()
        result = self.verify()
        self.assertFalse(result['verified'])
        self.assertTrue(any('history' in b for b in result['blockers']))

    def test_latest_unresolved_attempt_cannot_hide_behind_prior_pass(self):
        self.plan()
        self.checked()
        self.review()
        prepared = self.api.prepare_review(self.scope, self.request(coverage=['general'], criteria=['works'],
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
