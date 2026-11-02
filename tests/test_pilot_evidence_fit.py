"""One disposable canonical lifecycle; native qualification remains synthetic."""
from contextlib import ExitStack
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from runtime import evidence, recovery_uses, state
from tests import test_evidence as fixtures


def _cleanup_fixture(fixture, report, owned_roots):
    report['outer_fixture_cleanup_succeeded'] = fixture.doCleanups()
    # Nested TestCases discard False returns; check their known temporary roots independently.
    report['remaining_fixture_roots'] = [str(root) for root in owned_roots if os.path.lexists(root)]
    report['fixture_cleanup_succeeded'] = (report['outer_fixture_cleanup_succeeded'] and bool(owned_roots)
        and not report['remaining_fixture_roots'])
    if not report['fixture_cleanup_succeeded']:
        report['status'] = 'cleanup_failed'
        raise AssertionError('Canonical fixture cleanup failed')


class PilotEvidenceFitTests(unittest.TestCase):
    def test_inner_cleanup_failure_cannot_report_success_with_an_owned_root_remaining(self):
        with tempfile.TemporaryDirectory(prefix='vcw-pilot-cleanup-negative-') as directory:
            outer = unittest.TestCase('runTest')
            inner = unittest.TestCase('runTest')
            inner_results = []

            def fail_inner_cleanup():
                raise OSError('Injected inner fixture cleanup failure')

            inner.addCleanup(fail_inner_cleanup)
            outer.addCleanup(lambda: inner_results.append(inner.doCleanups()))
            report = {}
            with self.assertRaisesRegex(AssertionError, 'Canonical fixture cleanup failed'):
                _cleanup_fixture(outer, report, [Path(directory)])
            self.assertEqual(inner_results, [False])
            self.assertTrue(report['outer_fixture_cleanup_succeeded'])
            self.assertFalse(report['fixture_cleanup_succeeded'])
            self.assertEqual(report['remaining_fixture_roots'], [directory])

    def test_plan_cleanup_uncertain_check_recovery_and_merge_evidence(self):
        # Releasing an unresolved check or treating its timeout as a pass must fail here.
        fixture = fixtures.EvidenceTests('runTest')
        report = dict(authority='disposable software fixture; synthetic native qualification/review',
            status='incomplete', phase='birth', cleanup=[], capture_budgets=[])
        budgets = []
        owned_roots = []
        started = time.monotonic()
        initialize = recovery_uses.CaptureBudget.__init__
        cleanup = evidence._cleanup_closed_details

        def observe_budget(budget, *args, **kwargs):
            initialize(budget, *args, **kwargs)
            budgets.append((report['phase'], budget))

        def observe_cleanup(*args, **kwargs):
            result = cleanup(*args, **kwargs)
            report['cleanup'].append(deepcopy(result))
            return result

        def clean_fixture():
            _cleanup_fixture(fixture, report, owned_roots)

        def emit_report():
            report['capture_budgets'] = [dict(phase=phase, limits=deepcopy(budget.limits),
                used=deepcopy(budget.used)) for phase, budget in budgets]
            report['elapsed_including_cleanup_seconds'] = time.monotonic() - started
            print('E pilot fitness: ' + json.dumps(report, sort_keys=True), flush=True)

        with ExitStack() as stack:
            stack.callback(emit_report)
            stack.enter_context(patch.object(recovery_uses.CaptureBudget, '__init__', observe_budget))
            stack.enter_context(patch.object(evidence, '_cleanup_closed_details', observe_cleanup))
            stack.callback(clean_fixture)
            try:
                fixture.setUp()
                context = evidence._evidence_context(fixture.scope)
                owned_roots.extend((fixture.root, context.directory.parent))
                report['owned_fixture_roots'] = [str(root) for root in owned_roots]
                report['authority_set'] = evidence._canonical_plain(context.authority_set)
                marker = fixture.root / 'allow-check-to-finish'
                program = ('import time; from pathlib import Path; '
                    'time.sleep(0 if Path(' + repr(str(marker)) + ').exists() else 5)')
                check = dict(id='unit', argv=[sys.executable, '-c', program], cwd='.', timeout=1,
                    env={'PATH': os.defpath}, effects=dict(kind='read-only',
                        inspection_ref='fixture:inspected-no-spawn-sleep-program', network=False,
                        production=False, publish=False, migrations=False),
                    baseline=dict(status='passed', reference='fixture:baseline'), dependencies=['app.py'])
                report['phase'] = 'plan-triggered-cleanup'
                fixture.plan(checks=[check])
                self.assertEqual(len(report['cleanup']), 1)
                maintenance = report['cleanup'][0]
                self.assertEqual(maintenance['expired'], [])
                self.assertEqual(maintenance['pending'], [])
                self.assertFalse(maintenance['project']['complete'])
                self.assertIsNone(maintenance['project'].get('cap_satisfied'))
                self.assertTrue(maintenance['limitations'])
                report['retention_scope'] = 'Fresh open task; no aged closed detail or cap-pressure proof'

                report['phase'] = 'interrupted-check'
                interrupted = fixture.check()
                attempt = interrupted['attempt']
                report['interrupted_attempt'] = dict(id=attempt['id'], status=attempt['status'],
                    observed_status=attempt['observed_status'], process_id=attempt['process_id'])
                self.assertEqual(attempt['status'], 'uncertain')
                self.assertEqual(attempt['observed_status'], 'timed-out')
                before = state.task_status(fixture.scope, 'codex', 'parent')['task']
                self.assertFalse(fixture.verify()['verified'])
                with self.assertRaises(state.StateError):
                    fixture.check()
                with self.assertRaises(state.StateError):
                    fixture.reconcile(interrupted, attempt_id='0' * 32)
                retained = state.task_status(fixture.scope, 'codex', 'parent')['task']
                self.assertEqual(retained['revision'], before['revision'])
                self.assertEqual(retained['evidence']['attempts'], before['evidence']['attempts'])

                report['phase'] = 'exact-recovery'
                # This inspected program has no spawn path; process absence is checked independently.
                with self.assertRaises(ProcessLookupError):
                    os.kill(attempt['process_id'], 0)
                recovered = fixture.reconcile(interrupted,
                    observation_ref='fixture:independent-process-absence-and-no-spawn-inspection')
                self.assertEqual(recovered['attempt']['status'], 'timed-out')
                self.assertFalse(fixture.verify()['verified'])
                marker.touch()
                passed = fixture.check()
                with self.assertRaises(ProcessLookupError):
                    os.kill(passed['attempt']['process_id'], 0)
                reconciled = fixture.reconcile(passed,
                    observation_ref='fixture:independent-process-absence-and-no-spawn-inspection')
                self.assertEqual(reconciled['attempt']['status'], 'passed')
                self.assertNotEqual(passed['attempt_id'], interrupted['attempt_id'])
                self.assertEqual(passed['attempt']['plan_digest'], attempt['plan_digest'])
                self.assertEqual(passed['attempt']['candidate_digest'], attempt['candidate_digest'])

                report['phase'] = 'required-reviews'
                self.assertFalse(fixture.verify()['verified'])
                fixture.review()
                report['phase'] = 'merge-evidence'
                result = evidence.verify_completion(fixture.scope, fixture.request(purpose='merge-evidence'))
                self.assertTrue(result['verified'], result)
                self.assertFalse(result['merge_authority'])
                self.assertNotEqual(result['task']['state'], 'DONE')
                self.assertIsNone(result['task']['lifecycle']['safe_closed_at'])
                attempts = {item['id']: item for item in result['task']['evidence']['attempts']}
                self.assertEqual(attempts[interrupted['attempt_id']]['status'], 'timed-out')
                self.assertEqual(attempts[passed['attempt_id']]['status'], 'passed')
                self.assertEqual(len(report['cleanup']), 1, 'Publication must not repeat maintenance')
                report['artifacts'] = [dict(name=path.name, bytes=path.stat().st_size)
                    for path in sorted((context.directory / 'evidence').iterdir())]
                self.assertTrue(report['artifacts'])
                self.assertLessEqual(max(item['bytes'] for item in report['artifacts']), evidence.MAX_ARTIFACT)
                report['status'] = 'passed'
            except BaseException as error:
                report.update(status='failed', error=type(error).__name__)
                raise


if __name__ == '__main__':
    unittest.main()
