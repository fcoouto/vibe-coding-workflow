"""Synthetic D7 decisions are distinct from source authentication or enforcement."""

from copy import deepcopy
import importlib
import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


def fixture(schema_version=2):
    source = dict(issuer='qualified-fixture-app', workflow_ref='trusted/gate.yml', revision='a' * 40)
    pins = dict(schema_version=schema_version, policy_digest='b' * 64, runtime_digest='c' * 64)
    binding = dict(repository='owner/repo', target='refs/heads/main', head='d' * 40, base='e' * 40,
                   candidate_digest='f' * 64, queue=None, pins=pins, definitions_digest='1' * 64)
    policy = dict(version=1, binding=binding, current_runs={'unit': 'run-unit', 'review': 'run-review', 'writers': 'run-writers'}, max_age=300,
                  merge_methods=['merge', 'squash', 'rebase'], queue_mode='disabled', bypass_actors=[],
                  verifier=source, required_checks=[dict(id='unit', source=source, definition_digest='2' * 64)],
                  required_reviews=[dict(coverage='general', source=source, reviewers=['reviewer'])],
                  writer_source=source, revoked_runs=[])

    def record(id, **fields):
        return dict(id=id, run_id='run-' + id, source=deepcopy(source), binding=deepcopy(binding),
                    observed_at=990, conclusion='success', **fields)

    check = record('unit', definition_digest='2' * 64)
    review = record('review', reviewer_id='reviewer', author_id='author', coverage=['general'],
                    findings=[], dispositions=[], decision_refs=[], rechecked_findings=[])
    writers = record('writers', unresolved=[], reconciled=[dict(
        identity=dict(client='codex', session_id='session', task_id='task', scope_ref='user:task'),
        expected_revision=7, expected_pins=deepcopy(pins), attempt_id='attempt',
        candidate_digest='f' * 64, plan_digest='1' * 64, stopped=True, descendants_stopped=True)])
    observation = dict(version=1, binding=deepcopy(binding), observed_at=995,
                       verifier=deepcopy(source), merge_method='merge', bypass_actors=[], checks=[check],
                       reviews=[review], writers=writers)
    return dict(version=1, policy=policy, before=observation, after=deepcopy(observation), now=1000)


class RepositoryGateTests(unittest.TestCase):
    def setUp(self):
        self.api = importlib.import_module('runtime.repository_gate')
        self.data = fixture()

    def evaluate(self):
        d = self.data
        return self.api.evaluate(d['policy'], d['before'], d['after'], now=d['now'])

    def changed(self, change):
        change(self.data['before'])
        self.data['after'] = deepcopy(self.data['before'])
        return self.evaluate()

    def assert_blocked(self, result, code):
        self.assertFalse(result['evidence_valid'], result)
        self.assertIn(code, result['blockers'])
        self.assertFalse(result['merge_authorized'])

    def test_complete_current_fixture_passes_decisions_without_granting_authority(self):
        result = self.evaluate()
        self.assertTrue(result['evidence_valid'], result)
        self.assertEqual(result['blockers'], [])
        self.assertEqual(result['source_authentication'], 'unverified')
        self.assertEqual(result['execution_blockers'], ['unqualified_publisher', 'unqualified_evidence_source'])
        self.assertFalse(result['merge_authorized'])
        self.assertFalse(result['published'])

    def test_current_d6_runtime_pins_pass_and_historical_schema_pins_remain_rejected(self):
        for schema_version, accepted in ((2, True), (1, False)):
            with self.subTest(schema_version=schema_version):
                self.data = fixture(schema_version=schema_version)
                if accepted:
                    self.assertTrue(self.evaluate()['evidence_valid'])
                else:
                    self.assert_blocked(self.evaluate(), 'invalid_input')

    def test_every_required_check_requires_explicit_success(self):
        for status in ('failure', 'cancelled', 'skipped', 'neutral', 'timed_out', 'pending', ''):
            with self.subTest(status=status):
                self.data = fixture()
                self.assert_blocked(self.changed(lambda o: o['checks'][0].update(conclusion=status)), 'check_not_success')
        self.data = fixture()
        self.assert_blocked(self.changed(lambda o: o.update(checks=[])), 'missing_check')

    def test_changed_repository_target_candidate_base_and_pins_are_rejected(self):
        for field, value in [('repository', 'other/repo'), ('target', 'refs/heads/other'), ('head', '9' * 40),
                             ('base', '8' * 40), ('candidate_digest', '7' * 64), ('definitions_digest', '6' * 64)]:
            with self.subTest(field=field):
                self.data = fixture()
                self.assert_blocked(self.changed(lambda o: o['binding'].update({field: value})), 'binding_mismatch')
        for field in ('policy_digest', 'runtime_digest'):
            with self.subTest(pin=field):
                self.data = fixture()
                self.assert_blocked(self.changed(lambda o: o['binding']['pins'].update({field: '9' * 64})), 'binding_mismatch')

    def test_record_binding_and_check_definition_cannot_be_substituted(self):
        self.assert_blocked(self.changed(lambda o: o['checks'][0]['binding'].update(base='9' * 40)), 'record_binding_mismatch')
        self.data = fixture()
        self.assert_blocked(self.changed(lambda o: o['checks'][0].update(definition_digest='9' * 64)), 'check_definition_mismatch')

    def test_observations_cannot_select_their_own_trusted_source_or_policy(self):
        for kind in ('checks', 'reviews'):
            for field in ('issuer', 'workflow_ref', 'revision'):
                with self.subTest(kind=kind, field=field):
                    self.data = fixture()
                    self.assert_blocked(self.changed(lambda o: o[kind][0]['source'].update({field: '9' * 40 if field == 'revision' else 'forged'})), 'source_mismatch')
        self.data = fixture()
        self.assert_blocked(self.changed(lambda o: o.update(policy=self.data['policy'])), 'invalid_input')
        self.data = fixture()
        self.assert_blocked(self.changed(lambda o: o.update(authenticated=True)), 'invalid_input')

    def test_verifier_configuration_is_bound_to_separate_policy(self):
        self.assert_blocked(self.changed(lambda o: o['verifier'].update(workflow_ref='candidate/gate.yml')), 'verifier_mismatch')

    def test_duplicate_revoked_stale_future_and_replayed_records_are_rejected(self):
        cases = [
            (lambda o: o['checks'].append(deepcopy(o['checks'][0])), 'duplicate_record'),
            (lambda o: o['checks'][0].update(observed_at=699), 'stale_evidence'),
            (lambda o: o['checks'][0].update(observed_at=1001), 'stale_evidence'),
            (lambda o: o['checks'][0].update(run_id='old-run'), 'replayed_evidence'),
            (lambda o: o.update(observed_at=699), 'stale_evidence'),
        ]
        for change, code in cases:
            with self.subTest(code=code):
                self.data = fixture()
                self.assert_blocked(self.changed(change), code)
        self.data = fixture()
        self.data['policy']['revoked_runs'] = ['run-unit']
        self.assert_blocked(self.evaluate(), 'revoked_evidence')

    def test_requery_may_advance_timestamps_without_changing_semantic_state(self):
        self.data['after']['observed_at'] = 1000
        self.data['after']['checks'][0]['observed_at'] = 999
        self.assertTrue(self.evaluate()['evidence_valid'])

    def test_requery_accepts_reordered_qualified_reviews(self):
        second = deepcopy(self.data['before']['reviews'][0])
        second.update(id='second-review', run_id='run-second-review')
        self.data['policy']['current_runs']['second-review'] = 'run-second-review'
        self.data['before']['reviews'].append(second)
        self.data['after'] = deepcopy(self.data['before'])
        self.data['after']['reviews'].reverse()
        self.assertTrue(self.evaluate()['evidence_valid'])

    def test_requery_accepts_reordered_bypass_actors_but_rejects_changed_values(self):
        self.data['policy']['bypass_actors'] = ['admin', 'release']
        self.data['before']['bypass_actors'] = ['admin', 'release']
        self.data['after']['bypass_actors'] = ['release', 'admin']
        self.assertTrue(self.evaluate()['evidence_valid'])
        self.data['after']['bypass_actors'] = ['admin', 'other']
        self.assert_blocked(self.evaluate(), 'inputs_changed')

    def test_requery_preserves_meaningful_queue_member_order(self):
        queue = dict(candidate='3' * 40, base='e' * 40, members=['d' * 40, '4' * 40])
        self.data['policy']['binding']['queue'] = deepcopy(queue)
        self.data['policy']['queue_mode'] = 'required'
        for observation in (self.data['before'], self.data['after']):
            observation['binding']['queue'] = deepcopy(queue)
            for record in [*observation['checks'], *observation['reviews'], observation['writers']]:
                record['binding']['queue'] = deepcopy(queue)
        self.assertTrue(self.evaluate()['evidence_valid'])
        self.data['after']['binding']['queue']['members'].reverse()
        self.assert_blocked(self.evaluate(), 'inputs_changed')

    def test_a_current_run_for_one_record_cannot_be_replayed_as_another(self):
        def swap(o):
            o['checks'][0]['run_id'], o['reviews'][0]['run_id'] = o['reviews'][0]['run_id'], o['checks'][0]['run_id']
        self.assert_blocked(self.changed(swap), 'replayed_evidence')

    def test_requery_must_be_complete_and_unchanged(self):
        self.data['after']['checks'][0]['run_id'] = 'replacement'
        self.assert_blocked(self.evaluate(), 'inputs_changed')
        self.data['after'] = None
        self.assert_blocked(self.evaluate(), 'invalid_input')

    def test_merge_methods_queue_composition_and_bypass_scope_are_explicit(self):
        self.assert_blocked(self.changed(lambda o: o.update(merge_method='direct-update')), 'unsupported_merge_method')
        self.data = fixture()
        self.assert_blocked(self.changed(lambda o: o.update(bypass_actors=['admin'])), 'bypass_mismatch')
        self.data = fixture()
        queue = dict(candidate='3' * 40, base='e' * 40, members=['d' * 40])
        self.data['policy']['binding']['queue'] = deepcopy(queue)
        self.data['policy']['queue_mode'] = 'required'
        for observation in (self.data['before'], self.data['after']):
            observation['binding']['queue'] = deepcopy(queue)
            for record in [*observation['checks'], *observation['reviews'], observation['writers']]:
                record['binding']['queue'] = deepcopy(queue)
        self.assertTrue(self.evaluate()['evidence_valid'])
        self.assert_blocked(self.changed(lambda o: o['binding']['queue']['members'].append('4' * 40)), 'binding_mismatch')

    def test_review_coverage_reviewer_independence_and_conclusion_are_required(self):
        for change, code in [
            (lambda o: o.update(reviews=[]), 'missing_review'),
            (lambda o: o['reviews'][0].update(coverage=[]), 'missing_review'),
            (lambda o: o['reviews'][0].update(reviewer_id='fabricated'), 'untrusted_reviewer'),
            (lambda o: o['reviews'][0].update(author_id='reviewer'), 'review_not_independent'),
            (lambda o: o['reviews'][0].update(conclusion='neutral'), 'review_not_success'),
            (lambda o: o['reviews'][0].update(observed_at=1), 'stale_evidence')]:
            with self.subTest(code=code):
                self.data = fixture()
                self.assert_blocked(self.changed(change), code)

    def finding(self, severity='medium', scope='general'):
        return dict(id='finding', severity=severity, scope=scope, status='confirmed')

    def test_findings_need_complete_permitted_dispositions(self):
        self.assert_blocked(self.changed(lambda o: o['reviews'][0]['findings'].append(self.finding())), 'unresolved_finding')
        review = self.data['before']['reviews'][0]
        review['dispositions'] = [dict(finding_id='finding', status='accepted', reason='Accepted scoped tradeoff')]
        self.data['after'] = deepcopy(self.data['before'])
        self.assert_blocked(self.evaluate(), 'unresolved_finding')
        review['decision_refs'] = ['user:accepted-finding']
        self.data['after'] = deepcopy(self.data['before'])
        self.assertTrue(self.evaluate()['evidence_valid'])
        review['findings'][0].update(scope='security', severity='high')
        self.data['after'] = deepcopy(self.data['before'])
        self.assert_blocked(self.evaluate(), 'unresolved_finding')

    def test_a_clean_report_cannot_hide_a_known_finding_and_resolution_needs_fresh_scoped_review(self):
        original = self.data['before']['reviews'][0]
        original['findings'] = [self.finding()]
        fresh = deepcopy(original)
        fresh.update(id='fresh', run_id='run-fresh', reviewer_id='second', findings=[])
        self.data['policy']['required_reviews'][0]['reviewers'].append('second')
        self.data['policy']['current_runs']['fresh'] = 'run-fresh'
        self.data['before']['reviews'].append(fresh)
        self.data['after'] = deepcopy(self.data['before'])
        self.assert_blocked(self.evaluate(), 'unresolved_finding')
        fresh['rechecked_findings'] = [dict(attempt_id='review', finding_id='finding', status='resolved', reference='fixture:recheck')]
        self.data['after'] = deepcopy(self.data['before'])
        self.assertTrue(self.evaluate()['evidence_valid'])
        fresh['coverage'] = ['security']
        self.data['after'] = deepcopy(self.data['before'])
        self.assert_blocked(self.evaluate(), 'unresolved_finding')

    def test_unresolved_writers_and_mismatched_d6_reconciliation_block(self):
        cases = [
            (lambda o: o['writers'].update(unresolved=['session:uncertain']), 'unresolved_writers'),
            (lambda o: o['writers'].update(conclusion='cancelled'), 'unresolved_writers'),
            (lambda o: o['writers']['reconciled'][0].update(stopped=False), 'unresolved_writers'),
            (lambda o: o['writers']['reconciled'][0].update(descendants_stopped=False), 'unresolved_writers'),
            (lambda o: o['writers']['reconciled'][0].update(candidate_digest='9' * 64), 'writer_binding_mismatch'),
            (lambda o: o['writers']['reconciled'][0]['expected_pins'].update(runtime_digest='9' * 64), 'writer_binding_mismatch'),
            (lambda o: o['writers']['source'].update(issuer='forged'), 'source_mismatch'),
        ]
        for change, code in cases:
            with self.subTest(code=code):
                self.data = fixture()
                self.assert_blocked(self.changed(change), code)

    def test_writer_attempt_identity_is_order_independent_for_duplicate_detection(self):
        def duplicate(o):
            second = deepcopy(o['writers']['reconciled'][0])
            second['identity'] = dict(reversed(list(second['identity'].items())))
            o['writers']['reconciled'].append(second)
        self.assert_blocked(self.changed(duplicate), 'duplicate_record')

    def test_d6_writer_revision_must_be_positive(self):
        self.assert_blocked(self.changed(lambda o: o['writers']['reconciled'][0].update(expected_revision=0)), 'invalid_input')

    def test_finding_cannot_be_accepted_outside_observed_review_coverage(self):
        def hide(o):
            review = o['reviews'][0]
            review['findings'] = [self.finding(scope='security')]
            review['dispositions'] = [dict(finding_id='finding', status='accepted', reason='Scoped tradeoff')]
            review['decision_refs'] = ['user:accepted']
        self.assert_blocked(self.changed(hide), 'finding_coverage_mismatch')

    def test_review_cannot_self_assert_a_scope_that_has_no_qualified_policy_source(self):
        self.assert_blocked(self.changed(lambda o: o['reviews'][0]['coverage'].append('security')), 'review_coverage_mismatch')

    def test_source_records_must_not_postdate_their_observation_capture(self):
        self.assert_blocked(self.changed(lambda o: o['checks'][0].update(observed_at=999)), 'record_after_capture')

    def test_unknown_schema_version_and_invalid_target_are_not_accepted(self):
        for change in (lambda d: d['policy']['binding']['pins'].update(schema_version=99),
                       lambda d: d['policy']['binding'].update(target='refs/heads/../main')):
            self.data = fixture()
            change(self.data)
            self.assert_blocked(self.evaluate(), 'invalid_input')

    def test_strict_validator_rejects_oversized_nested_unknown_and_wrong_types(self):
        cases = [lambda d: d.update(unknown='secret'), lambda d: d.update(version=True),
                 lambda d: d['policy'].update(max_age=True),
                 lambda d: d['before']['checks'][0].update(id='x' * 513),
                 lambda d: d['before'].update(checks=[deepcopy(d['before']['checks'][0])] * 129),
                 lambda d: d['before']['writers']['reconciled'][0].update(expected_revision=True),
                 lambda d: d['policy']['binding'].update(head='main'),
                 lambda d: d['policy']['binding'].update(queue={'nested': [[[[]]]]}),
                 lambda d: d['before'].update(observed_at=float('inf'))]
        for change in cases:
            with self.subTest(change=change):
                data = fixture()
                change(data)
                with self.assertRaises(self.api.GateError):
                    self.api.validate_envelope(data)

    def cli(self, raw, *args):
        return subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'scripts/repository_gate.py'), *args],
                              input=raw, capture_output=True)

    def test_cli_inspects_but_never_authenticates_or_publishes_fixture(self):
        result = self.cli(json.dumps(self.data).encode())
        self.assertEqual(result.returncode, 1)
        output = json.loads(result.stdout)
        self.assertTrue(output['evidence_valid'])
        self.assertFalse(output['merge_authorized'])
        self.assertFalse(output['published'])
        self.assertEqual(output['source_authentication'], 'unverified')
        self.assertEqual(result.stderr, b'')

    def test_cli_malformed_oversized_duplicate_and_secret_inputs_fail_sanitized(self):
        for raw in (b'{"secret":"do-not-print"', b'x' * (512 * 1024 + 1),
                    b'{"version":1,"version":1}', b'[' * 10000, b'{"secret":NaN}', b'\xff'):
            with self.subTest(length=len(raw)):
                result = self.cli(raw)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(json.loads(result.stdout)['evidence_valid'])
                self.assertNotIn(b'do-not-print', result.stdout + result.stderr)
                self.assertEqual(result.stderr, b'')
        result = self.cli(b'{}', '--secret-do-not-print')
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(b'secret-do-not-print', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
