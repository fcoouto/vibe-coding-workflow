"""Synthetic Council flow; no inference or live client configuration."""
import copy
import hashlib
import json
from pathlib import Path
import time
from unittest.mock import patch

from tests.council_fixtures import CouncilCase
from runtime import openrouter_settings

try:
    from runtime import council
except ImportError:
    council = None


class CouncilFlowTests(CouncilCase):
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(council, 'Council flow helper is not implemented')
        (self.repo / 'evidence.txt').write_text('Shared reviewed evidence\n')
        caps = dict(model='vendor/frontier', provider='fixture', context_length=20000,
                    max_output_tokens=8000, tools=True, reasoning={'efforts': ['low', 'high']},
                    observed_at='fixture-date', source='native:endpoint-observation')
        external = dict(kind='external', model='vendor/frontier', model_display_name='Fixture',
            provider='fixture', effort='high', input_tokens=10000, output_tokens=4096, steps=12,
            capabilities=caps, permission_qualification=dict(
                opencode_sha256=hashlib.sha256(self.executable.read_bytes()).hexdigest(),
                version='1.19.5', profile='council-readonly-v2', evidence='native:controlled-probe'),
            selection='native:benchmark and endpoint observations')
        self.request = dict(run_id='round-one', question='What follows from the evidence?',
            constraints='Read only; explain uncertainty.', coordinator_chat_id='00000000-0000-4000-8000-000000000001',
            approval_ref='native:explicit-council-consent', approved_files=self.approved(['evidence.txt']),
            research='# Shared research\nPublic source, date and excerpt.\n',
            phase_seconds={'investigate': 600, 'critique': 360, 'synthesis': 240},
            roster={'native': dict(kind='native', model='native-frontier', effort='max',
                supported_efforts=['high', 'max'], input_tokens=20000, output_tokens=8000, steps=20,
                selection='native:guidance and current controls', supervisor_id='coordinator'),
                'external-one': external, 'external-two': copy.deepcopy(external)})
        self.run = None

    def prepare(self):
        result = council.prepare(self.repo, self.request)
        self.run = Path(result['run'])
        return result

    def native(self, phase, report='Native evidence and uncertainty.', accepted=True):
        packet = council.packet(self.run, phase, 'native')
        receipt = dict(issued_id=packet['issued_id'], child_id='child-' + phase,
            supervisor_id='coordinator', observed_model='native-frontier', observed_effort='max',
            fork_turns='none', local_execution_stopped=True, accepted=accepted,
            checks=['Native checked scope, decisive citations and omissions.'], report=report)
        council.record_native(self.run, phase, 'native', receipt)
        return packet

    def external(self, phase, member, report='External finding.', state='accepted', cost=None):
        packet = council.packet(self.run, phase, member)
        path = Path(packet['worker_run']) / 'result.json'
        value = dict(state=state, response=report, local_execution_stopped=True,
            reported_cost_usd=cost, known_cost_subtotal_usd=cost or 0,
            accounting_complete=cost is not None, upstream_cancellation_confirmed=False,
            native_checks=['Native checked scope and evidence.'] if state == 'accepted' else [])
        path.write_text(json.dumps(value)); path.chmod(0o600)
        return packet

    def investigations(self, second=True):
        self.native('investigate')
        self.external('investigate', 'external-one')
        if second: self.external('investigate', 'external-two', 'Decisive minority objection.')

    def critiques(self):
        self.native('critique')
        self.external('critique', 'external-one')
        if not self.request['roster']['external-two'].get('unavailable_reason'):
            self.external('critique', 'external-two')

    def test_initial_reports_stay_hidden_and_lost_native_response_is_not_reissued(self):
        self.prepare(); self.native('investigate')
        packet = council.packet(self.run, 'investigate', 'external-one')
        self.assertNotIn('Native evidence', json.dumps(packet))
        with self.assertRaisesRegex(ValueError, 'already_issued'):
            council.packet(self.run, 'investigate', 'native')

    def test_phase_order_and_fresh_synthesis_preserve_plain_dissent(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, 'phase_not_ready'):
            council.packet(self.run, 'critique', 'native')
        self.investigations(); self.critiques()
        packet = council.packet(self.run, 'synthesis', 'native')
        self.assertEqual(packet['fork_turns'], 'none')
        self.assertEqual(packet['reasoning_effort'], 'max')
        self.assertNotIn('conversation_history', packet)
        self.assertIn('Decisive minority objection.', packet['reports'])
        self.assertNotIn('vendor/frontier', packet['reports'])
        self.assertIn('Shared research', packet['research'])

    def test_complete_requires_synthesis_and_all_members(self):
        self.prepare(); self.investigations(); self.critiques()
        self.assertEqual(council.status(self.run)['outcome'], 'partial')
        self.native('synthesis', 'Synthesis preserves dissent and limitations.')
        self.assertEqual(council.status(self.run)['outcome'], 'complete')

    def test_missing_model_with_reciprocal_critique_is_incomplete(self):
        self.request['roster']['external-two'] = dict(kind='external', unavailable_reason='No supported endpoint', selection='native:discovery')
        self.prepare(); self.investigations(second=False); self.critiques(); self.native('synthesis')
        self.assertEqual(council.status(self.run)['outcome'], 'incomplete')

    def test_single_critic_cannot_claim_incomplete(self):
        self.request['roster']['external-two'] = dict(kind='external', unavailable_reason='Unavailable', selection='native:discovery')
        self.prepare(); self.investigations(second=False); self.native('critique')
        self.external('critique', 'external-one', state='failed')
        self.native('synthesis')
        self.assertEqual(council.status(self.run)['outcome'], 'partial')

    def test_unverified_external_report_does_not_advance(self):
        self.prepare(); self.native('investigate')
        self.external('investigate', 'external-one', state='awaiting_verification')
        self.external('investigate', 'external-two')
        with self.assertRaisesRegex(ValueError, 'phase_not_ready'):
            council.packet(self.run, 'critique', 'native')

    def test_late_report_and_changed_research_are_rejected_after_freeze(self):
        self.prepare(); self.investigations(); council.packet(self.run, 'critique', 'native')
        (self.run / 'research.md').write_text('Late unreviewed evidence')
        with self.assertRaisesRegex(ValueError, 'frozen_evidence_changed'):
            council.packet(self.run, 'critique', 'external-one')
        with self.assertRaises(ValueError): self.native('investigate')

    def test_cancel_returns_exact_owners_and_blocks_launches(self):
        self.prepare(); packet = council.packet(self.run, 'investigate', 'native')
        report = council.cancel(self.run)
        self.assertTrue(report['cancelled'])
        self.assertEqual(report['stop_requests'][0]['issued_id'], packet['issued_id'])
        self.assertFalse(report['all_local_execution_stopped'])
        with self.assertRaisesRegex(ValueError, 'cancelled'):
            council.packet(self.run, 'investigate', 'external-one')

    def test_disable_blocks_external_launch(self):
        self.prepare()
        openrouter_settings.disable(self.repo, {'expected_revision': self.settings['revision']})
        with self.assertRaises(Exception): council.packet(self.run, 'investigate', 'external-one')

    def test_unknown_costs_remain_unknown_after_local_stop(self):
        self.prepare(); self.investigations()
        report = council.status(self.run)
        self.assertIsNone(report['external_total_usd'])
        self.assertEqual(report['known_external_subtotal_usd'], 0)
        self.assertFalse(report['upstream_cancellation_confirmed'])

    def test_deadline_exhaustion_and_uncertain_clock_never_replenish(self):
        self.prepare()
        with patch.object(council.time, 'monotonic', return_value=time.monotonic() + 1201), patch.object(council.time, 'time', return_value=time.time() + 1201):
            self.assertEqual(council.status(self.run)['remaining_seconds'], 0)
            with self.assertRaisesRegex(ValueError, 'deadline'): council.packet(self.run, 'investigate', 'native')
        with patch.object(council.time, 'time', return_value=time.time() - 100):
            with self.assertRaisesRegex(ValueError, 'timing_uncertain'): council.packet(self.run, 'investigate', 'native')

    def test_maximum_native_effort_and_total_budget_are_required(self):
        self.request['roster']['native']['effort'] = 'high'
        with self.assertRaisesRegex(ValueError, 'maximum'): self.prepare()
        self.request['roster']['native']['effort'] = 'max'
        self.request['phase_seconds']['synthesis'] = 241
        with self.assertRaisesRegex(ValueError, '1200'): self.prepare()

    def test_snapshot_stays_common_after_source_changes_and_critique_has_reports_as_files(self):
        self.prepare(); (self.repo / 'evidence.txt').write_text('Changed later')
        self.investigations()
        packet = council.packet(self.run, 'critique', 'external-one')
        workspace = Path(packet['worker_run']) / 'workspace'
        self.assertEqual((workspace / 'evidence.txt').read_text(), 'Shared reviewed evidence\n')
        self.assertIn('Decisive minority objection.', (workspace / '__council__/initial-3.md').read_text())

    def test_native_receipt_requires_actual_settings_stop_and_checks(self):
        self.prepare(); packet = council.packet(self.run, 'investigate', 'native')
        receipt = dict(issued_id=packet['issued_id'], child_id='child', supervisor_id='coordinator',
            observed_model='wrong', observed_effort='max', fork_turns='none',
            local_execution_stopped=True, accepted=True, checks=['checked'], report='Report')
        with self.assertRaisesRegex(ValueError, 'native_settings'): council.record_native(self.run, 'investigate', 'native', receipt)
        receipt['observed_model'] = 'native-frontier'; receipt['local_execution_stopped'] = False
        with self.assertRaisesRegex(ValueError, 'native_stop'): council.record_native(self.run, 'investigate', 'native', receipt)

    def test_report_limit_and_replay_are_enforced(self):
        self.prepare(); self.native('investigate')
        with self.assertRaises(ValueError): self.prepare()
        self.external('investigate', 'external-one', 'x' * (128 * 1024 + 1))
        self.external('investigate', 'external-two')
        with self.assertRaisesRegex(ValueError, 'report_limit'): council.packet(self.run, 'critique', 'native')

    def test_active_lifecycle_needs_actual_phase_admission_and_never_reuses_it(self):
        self.request['roster']['native']['lifecycle_active'] = True
        self.prepare()
        with self.assertRaisesRegex(ValueError, 'active_native_lifecycle'):
            council.packet(self.run, 'investigate', 'native')
        admission = dict(reference='actual:admission', run_id='round-one', phase='investigate', member_id='native')
        packet = council.packet(self.run, 'investigate', 'native', native_receipt=admission)
        self.assertTrue(packet['issued_id'])
        with self.assertRaisesRegex(ValueError, 'already_issued'):
            council.packet(self.run, 'investigate', 'native', native_receipt=admission)

    def test_unsettled_native_blocks_phase_even_after_deadline(self):
        self.prepare(); council.packet(self.run, 'investigate', 'native')
        self.external('investigate', 'external-one'); self.external('investigate', 'external-two')
        with patch.object(council.time, 'monotonic', return_value=time.monotonic() + 601), patch.object(council.time, 'time', return_value=time.time() + 601):
            with self.assertRaisesRegex(ValueError, 'phase_not_ready'):
                council.packet(self.run, 'critique', 'native')

    def test_late_external_settlement_cannot_change_frozen_participation(self):
        self.request['roster']['external-two'] = dict(kind='external', unavailable_reason='Unavailable', selection='native:discovery')
        self.prepare(); self.native('investigate')
        packet = self.external('investigate', 'external-one', state='failed')
        self.native('critique'); self.external('critique', 'external-one'); self.native('synthesis')
        path = Path(packet['worker_run']) / 'result.json'
        result = json.loads(path.read_text()); result.update(state='accepted', native_checks=['late checks'])
        path.write_text(json.dumps(result))
        self.assertEqual(council.status(self.run)['outcome'], 'partial')

    def test_native_child_identity_cannot_be_reused_across_fresh_phases(self):
        self.prepare(); self.investigations()
        packet = council.packet(self.run, 'critique', 'native')
        receipt = dict(issued_id=packet['issued_id'], child_id='child-investigate', supervisor_id='coordinator',
            observed_model='native-frontier', observed_effort='max', fork_turns='none',
            local_execution_stopped=True, accepted=True, checks=['checked'], report='Critique')
        with self.assertRaisesRegex(ValueError, 'fresh_native_child'):
            council.record_native(self.run, 'critique', 'native', receipt)

    def test_native_and_external_critics_share_exact_sealed_evidence(self):
        self.prepare(); self.investigations()
        native = council.packet(self.run, 'critique', 'native')
        external = council.packet(self.run, 'critique', 'external-one')
        brief = json.loads((Path(external['worker_run']) / 'brief.json').read_text())
        self.assertEqual(native['snapshot'], brief['evidence']['snapshot'])
        self.assertEqual(native['snapshot_manifest'], brief['evidence']['manifest'])

    def test_known_cost_total_and_unknown_partial_cost_are_distinct(self):
        self.prepare(); self.native('investigate')
        self.external('investigate', 'external-one', cost=1.25)
        packet = self.external('investigate', 'external-two', cost=2.5)
        self.assertEqual(council.status(self.run)['external_total_usd'], 3.75)
        path = Path(packet['worker_run']) / 'result.json'
        result = json.loads(path.read_text()); result['reported_cost_usd'] = None
        path.write_text(json.dumps(result))
        report = council.status(self.run)
        self.assertIsNone(report['external_total_usd'])
        self.assertEqual(report['known_external_subtotal_usd'], 3.75)

    def test_cli_native_member_and_synthetic_external_worker(self):
        from contextlib import redirect_stdout
        from io import BytesIO, StringIO, TextIOWrapper
        from scripts import council as cli
        def invoke(action, request):
            output = StringIO()
            with patch('sys.argv', ['council', action, '--cwd', str(self.repo)]), patch('sys.stdin', TextIOWrapper(BytesIO(json.dumps(request).encode()))), redirect_stdout(output):
                code = cli.main()
            return code, json.loads(output.getvalue().splitlines()[-1])
        events = [dict(type='text', part={'text': 'Synthetic cited finding.'}),
                  dict(type='step_finish', part=dict(reason='stop', cost=0.25, tokens={'input': 10, 'output': 5}))]
        self.executable.write_text('#!/bin/sh\ncat <<\'EVENTS\'\n' + '\n'.join(json.dumps(x) for x in events) + '\nEVENTS\n')
        for member in ('external-one', 'external-two'):
            self.request['roster'][member]['permission_qualification']['opencode_sha256'] = hashlib.sha256(self.executable.read_bytes()).hexdigest()
        code, result = invoke('prepare', self.request)
        self.assertEqual(code, 0); self.run = Path(result['run'])
        code, native = invoke('member', dict(run=str(self.run), phase='investigate', member='native'))
        self.assertEqual(code, 0); self.assertEqual(native['fork_turns'], 'none')
        code, result = invoke('member', dict(run=str(self.run), phase='investigate', member='external-one'))
        self.assertEqual(code, 0); self.assertEqual(result['state'], 'awaiting_verification')
        path = self.root / 'round-one-investigate-external-one'
        from scripts import openrouter_workers
        with redirect_stdout(StringIO()):
            settled = openrouter_workers.verify(path, 'accepted', ['Native checked synthetic citation.'])
        self.assertEqual(settled['state'], 'accepted')
        code, _ = invoke('member', dict(run=str(self.run), phase='investigate', member='external-one'))
        self.assertEqual(code, 1)

    def test_cli_rejects_cross_checkout_run(self):
        from contextlib import redirect_stdout
        from io import BytesIO, StringIO, TextIOWrapper
        from scripts import council as cli
        self.prepare()
        with patch('sys.argv', ['council', 'status', '--cwd', str(self.repo)]), patch('sys.stdin', TextIOWrapper(BytesIO(json.dumps({'run': str(self.temporary)}).encode()))), redirect_stdout(StringIO()):
            self.assertEqual(cli.main(), 1)

    def test_synthesis_cannot_reuse_coordinator_identity(self):
        self.prepare(); self.investigations(); self.critiques()
        packet = council.packet(self.run, 'synthesis', 'native')
        receipt = dict(issued_id=packet['issued_id'], child_id=self.request['coordinator_chat_id'], supervisor_id='coordinator',
            observed_model='native-frontier', observed_effort='max', fork_turns='none',
            local_execution_stopped=True, accepted=True, checks=['checked'], report='Synthesis')
        with self.assertRaisesRegex(ValueError, 'fresh_native_child'):
            council.record_native(self.run, 'synthesis', 'native', receipt)

    def test_cancel_before_actual_spawn_prevents_subprocess(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from scripts import council as cli
        self.prepare()
        packet = council.packet(self.run, 'investigate', 'external-one')
        council.cancel(self.run)
        with patch.object(council.workers.subprocess, 'Popen', wraps=council.workers.subprocess.Popen) as spawn, redirect_stdout(StringIO()):
            result = cli._execute(self.run, 'investigate', packet, self.settings)
        self.assertEqual([call for call in spawn.call_args_list if call.args[0][0] == str(self.executable)], [])
        self.assertTrue(result['local_execution_stopped'])
        self.assertEqual(result['state'], 'unresolved')

    def test_cancel_after_actual_spawn_requests_owner_stop_and_records_local_stop(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from scripts import council as cli
        self.prepare()
        packet = council.packet(self.run, 'investigate', 'external-one')
        cancellation = []
        def observed_progress(phase):
            if phase == 'Starting':
                cancellation.append(council.cancel(self.run))
                raise KeyboardInterrupt()
        with patch.object(council.workers.subprocess, 'Popen', wraps=council.workers.subprocess.Popen) as spawn, redirect_stdout(StringIO()):
            result = council.workers.execute(Path(packet['worker_run']), self.executable, self.auth,
                observed_progress, launch_guard=lambda: cli._launch_guard(self.run, 'investigate'))
        self.assertEqual(len([call for call in spawn.call_args_list if call.args[0][0] == str(self.executable)]), 1)
        self.assertEqual(cancellation[0]['stop_requests'][0]['worker_run'], packet['worker_run'])
        self.assertTrue(result['local_execution_stopped'])
        self.assertIsNone(result['reported_cost_usd'])
        self.assertFalse(result['upstream_cancellation_confirmed'])

    def test_external_execution_stops_at_elapsed_phase_ceiling(self):
        from contextlib import redirect_stdout
        from io import StringIO
        import sys
        from scripts import council as cli
        self.executable.write_text('#!' + sys.executable + '\nimport time\ntime.sleep(10)\n')
        for member in ('external-one', 'external-two'):
            self.request['roster'][member]['permission_qualification']['opencode_sha256'] = hashlib.sha256(self.executable.read_bytes()).hexdigest()
        self.prepare()
        packet = council.packet(self.run, 'investigate', 'external-one')
        packet['deadline_monotonic'] = time.monotonic() + 0.2
        started = time.monotonic()
        with redirect_stdout(StringIO()):
            result = cli._execute(self.run, 'investigate', packet, self.settings)
        self.assertLess(time.monotonic() - started, 4)
        self.assertEqual(result['failure']['category'], 'deadline')
        self.assertTrue(result['local_execution_stopped'])
        self.assertIsNone(result['reported_cost_usd'])

    def test_lost_external_preparation_receipt_cannot_replay_and_reports_owner(self):
        self.prepare()
        real_save = council._save
        def interrupted(run, value):
            if 'investigate:external-one' in value['members']:
                raise OSError('lost preparation publication')
            return real_save(run, value)
        with patch.object(council, '_save', side_effect=interrupted), self.assertRaises(OSError):
            council.packet(self.run, 'investigate', 'external-one')
        # Original worker result remains the lifecycle authority, even without Council publication.
        report = council.status(self.run)
        self.assertEqual(report['members']['investigate']['external-one']['state'], 'prepared')
        self.assertIn('worker_run', report['stop_requests'][0])
        with self.assertRaises(FileExistsError):
            council.packet(self.run, 'investigate', 'external-one')

    def test_large_markdown_reports_use_files_without_objective_truncation(self):
        self.prepare(); self.native('investigate', 'native evidence ' * 4000)
        self.external('investigate', 'external-one', 'external evidence ' * 4000)
        self.external('investigate', 'external-two', 'minority dissent ' * 4000)
        packet = council.packet(self.run, 'critique', 'external-one')
        brief = json.loads((Path(packet['worker_run']) / 'brief.json').read_text())
        self.assertLess(len(brief['objective']), 16000)
        self.assertEqual((Path(packet['worker_run']) / 'workspace/__council__/initial-3.md').read_text(), 'minority dissent ' * 4000)

    def test_native_spawn_refusal_records_absent_child_without_fabricated_settings(self):
        self.prepare(); packet = council.packet(self.run, 'investigate', 'native')
        receipt = dict(issued_id=packet['issued_id'], child_id=None, supervisor_id='coordinator',
            observed_model=None, observed_effort=None, fork_turns=None,
            local_execution_stopped=True, accepted=False,
            checks=['Native dispatch tool refused before creating a child; observed no admitted process.'], report='Native dispatch unavailable.')
        council.record_native(self.run, 'investigate', 'native', receipt)
        self.assertEqual(council.status(self.run)['members']['investigate']['native']['state'], 'rejected')
        self.assertTrue(council.status(self.run)['all_local_execution_stopped'])

    def test_native_supports_observed_ultra_effort_without_downgrade(self):
        self.request['roster']['native']['supported_efforts'].append('ultra')
        self.request['roster']['native']['effort'] = 'ultra'
        self.prepare()
        self.assertEqual(council.packet(self.run, 'investigate', 'native')['reasoning_effort'], 'ultra')

    def test_empty_native_answer_cannot_count_as_accepted_evidence(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, 'native_report_required'):
            self.native('investigate', '  ')

    def test_explicit_custom_total_is_finite_and_worker_calls_stay_bounded(self):
        self.request['timeout_seconds'] = 3600
        self.request['phase_seconds'] = dict(investigate=1800, critique=1080, synthesis=720)
        self.prepare()
        packet = council.packet(self.run, 'investigate', 'external-one')
        brief = json.loads((Path(packet['worker_run']) / 'brief.json').read_text())
        self.assertEqual(brief['timeout_seconds'], 1200)
        self.assertGreater(council.status(self.run)['remaining_seconds'], 3500)

    def test_unknown_native_settings_can_count_with_verified_controls_and_disclosed_limits(self):
        self.prepare(); packet = council.packet(self.run, 'investigate', 'native')
        receipt = dict(issued_id=packet['issued_id'], child_id='observed-child', supervisor_id='coordinator',
            observed_model=None, observed_effort=None, fork_turns='none', controls_verified=True,
            local_execution_stopped=True, accepted=True, checks=['Native verified configured dispatch model/maximum controls, scope and citations.'], report='Verified finding; execution model and reasoning telemetry unavailable.')
        with self.assertRaisesRegex(ValueError, 'controls_verification'):
            council.record_native(self.run, 'investigate', 'native', dict(receipt, controls_verified=False))
        council.record_native(self.run, 'investigate', 'native', receipt)
        native = council.status(self.run)['members']['investigate']['native']
        self.assertEqual(native['state'], 'accepted')
        self.assertIsNone(native['observed_model'])
        self.assertTrue(native['limitations'])

    def test_phase_artifact_headroom_accepts_boundaries_and_rejects_next_file_or_byte(self):
        reserve = 4 * 128 * 1024
        files = {str(n): {'size': 0} for n in range(1996)}
        files['0']['size'] = 32 * 1024 * 1024 - reserve
        council._phase_headroom({'files': files}, self.request['roster'])
        files['extra'] = {'size': 0}
        with self.assertRaisesRegex(ValueError, 'phase_artifact_headroom'):
            council._phase_headroom({'files': files}, self.request['roster'])
        del files['extra']; files['0']['size'] += 1
        with self.assertRaisesRegex(ValueError, 'phase_artifact_headroom'):
            council._phase_headroom({'files': files}, self.request['roster'])

    def test_impossible_phase_scope_is_rejected_during_prepare_before_any_launch(self):
        (self.repo / 'second.txt').write_text('More source evidence')
        self.request['approved_files'] = self.approved(['evidence.txt', 'second.txt'])
        with patch.object(council.snapshot, 'MAX_PATHS', 5), self.assertRaisesRegex(ValueError, 'phase_artifact_headroom'):
            self.prepare()
        self.assertFalse((self.root / 'round-one-investigate-external-one').exists())
