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

    def test_reduced_panel_distinguishes_fresh_synthesis_from_evidence_only(self):
        self.prepare(); self.native('investigate', accepted=False)
        self.external('investigate', 'external-one'); self.external('investigate', 'external-two')
        self.native('critique', accepted=False)
        self.external('critique', 'external-one'); self.external('critique', 'external-two')
        before = council.status(self.run)
        self.assertFalse(before['fresh_synthesis_available'])
        self.native('synthesis', 'Supported conclusion with gaps.')
        report = council.status(self.run)
        self.assertEqual(report['outcome'], 'partial')
        self.assertEqual(report['accepted_participation'], dict(investigate=dict(accepted=2, expected=3), critique=dict(accepted=2, expected=3), synthesis=dict(accepted=1, expected=1)))
        self.assertTrue(report['fresh_synthesis_available'])

    def test_failed_synthesis_exposes_no_verdict(self):
        self.prepare(); self.investigations(); self.critiques(); self.native('synthesis', accepted=False)
        self.assertFalse(council.status(self.run)['fresh_synthesis_available'])

    def test_critique_build_recovers_staging_and_completed_snapshot_publication(self):
        for index, after_capture in enumerate((False, True)):
            (self.repo / 'evidence.txt').write_text('Shared reviewed evidence\n')
            self.request['run_id'] = 'snapshot-resume-' + str(index)
            self.prepare(); self.investigations()
            capture = council.snapshot.capture
            def interrupted(*args, **kwargs):
                if after_capture: capture(*args, **kwargs)
                raise OSError('interrupted local publication')
            with patch.object(council.snapshot, 'capture', side_effect=interrupted), self.assertRaises(OSError):
                council.packet(self.run, 'critique', 'native')
            (self.repo / 'evidence.txt').write_text('Changed live source must stay excluded')
            packet = council.packet(self.run, 'critique', 'native')
            self.assertEqual((Path(packet['snapshot']) / 'evidence.txt').read_text(), 'Shared reviewed evidence\n')
            self.assertIn('Decisive minority objection.', packet['reports'])

    def test_critique_recovery_preserves_changed_or_unfamiliar_artifacts(self):
        self.prepare(); self.investigations()
        with patch.object(council.snapshot, 'capture', side_effect=OSError('interrupted')), self.assertRaises(OSError):
            council.packet(self.run, 'critique', 'native')
        stranger = self.run / 'critique-inputs' / 'unfamiliar.txt'
        stranger.write_text('keep this file'); stranger.chmod(0o600)
        with self.assertRaisesRegex(ValueError, 'critique.*conflict'):
            council.packet(self.run, 'critique', 'native')
        self.assertEqual(stranger.read_text(), 'keep this file')

    def test_recovery_publication_preserves_destination_created_during_publish(self):
        for sealed in (False, True):
            with self.subTest(sealed=sealed):
                directory = self.root / ('partial-target' if sealed else 'staging-race')
                directory.mkdir(mode=0o700)
                retained = directory / 'retained.md'
                retained.write_bytes(b'retained frozen evidence'); retained.chmod(0o400 if sealed else 0o600)
                competing = b'concurrent changed artifact: preserve'
                injected = []
                def racing(publication):
                    def publish(source, destination, *args, **kwargs):
                        if destination == 'report.md':
                            injected.append(True)
                            (directory / 'report.md').write_bytes(competing)
                            (directory / 'report.md').chmod(0o400 if sealed else 0o600)
                        return publication(source, destination, *args, **kwargs)
                    return publish
                with patch.object(council.os, 'replace', side_effect=racing(council.os.replace)), patch.object(council.os, 'link', side_effect=racing(council.os.link)):
                    with self.assertRaisesRegex(ValueError, 'critique_artifact_conflict'):
                        council._reconcile_inputs(directory, {'retained.md': b'retained frozen evidence',
                            'report.md': b'frozen expected report'}, sealed=sealed)
                self.assertEqual(injected, [True])
                self.assertEqual((directory / 'report.md').read_bytes(), competing)
                self.assertEqual(retained.read_bytes(), b'retained frozen evidence')
                self.assertEqual({path.name for path in directory.iterdir()}, {'retained.md', 'report.md'})

    def test_busy_worker_resumes_exact_owner_and_status_projects_safe_failure(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from scripts import council as cli
        self.prepare(); packet = council.packet(self.run, 'investigate', 'external-one')
        with patch.object(council.workers.settings, 'admission', side_effect=openrouter_settings.SettingsError('openrouter_operation_busy')), patch.object(council.workers.time, 'sleep'), redirect_stdout(StringIO()):
            result = cli._execute(self.run, 'investigate', packet, self.settings)
        self.assertEqual(result['state'], 'not_launched')
        report = council.status(self.run)
        failure = report['members']['investigate']['external-one']['failure']
        self.assertEqual(failure['reason'], 'openrouter_operation_busy')
        resumed = council.resume_member(self.run, 'investigate', 'external-one')
        self.assertEqual(resumed['worker_run'], packet['worker_run'])
        self.assertEqual(resumed['deadline_monotonic'], result['deadline_monotonic'])
        with redirect_stdout(StringIO()): cli._execute(self.run, 'investigate', resumed, self.settings)
        with self.assertRaisesRegex(ValueError, 'not_resumable'):
            council.resume_member(self.run, 'investigate', 'external-one')
        with self.assertRaisesRegex(ValueError, 'already_issued'):
            council.packet(self.run, 'investigate', 'external-one')

    def test_failure_projection_drops_arbitrary_diagnostics_in_status_and_anonymous_context(self):
        self.prepare(); self.native('investigate')
        packet = self.external('investigate', 'external-one', state='failed')
        path = Path(packet['worker_run']) / 'result.json'
        item = json.loads(path.read_text())
        item['failure'] = dict(category='policy', error_class='ContentFilterError', terminal_reason='content-filter', launch_stage='launched', reason='SECRET', message='SECRET', origin='SECRET')
        path.write_text(json.dumps(item))
        self.external('investigate', 'external-two')
        report = council.status(self.run)
        failure = report['members']['investigate']['external-one']['failure']
        self.assertEqual(failure, dict(category='policy', error_class='ContentFilterError', terminal_reason='content-filter', launch_stage='launched'))
        packet = council.packet(self.run, 'critique', 'native')
        self.assertIn('ContentFilterError', packet['execution_observations'])
        self.assertNotIn('SECRET', json.dumps(report) + packet['execution_observations'])

    def test_staging_creation_and_partial_capture_interruptions_resume_frozen_bytes(self):
        for index, target_partial in enumerate((False, True)):
            self.request['run_id'] = 'partial-artifacts-' + str(index)
            self.prepare(); self.investigations()
            owner = council.changes if target_partial else council
            helper = '_atomic' if target_partial else '_publish_input'
            atomic = getattr(owner, helper)
            def interrupted(directory, name, *args, **kwargs):
                wanted = 'critique-snapshot' if target_partial else 'critique-inputs'
                if wanted in Path(directory).parts and name == 'evidence.txt':
                    raise KeyboardInterrupt()
                return atomic(directory, name, *args, **kwargs)
            with patch.object(owner, helper, side_effect=interrupted), self.assertRaises(KeyboardInterrupt):
                council.packet(self.run, 'critique', 'native')
            packet = council.packet(self.run, 'critique', 'native')
            council.snapshot.verify(Path(packet['snapshot']), packet['snapshot_manifest'])

    def test_completed_snapshot_recovery_rejects_changed_inventory_hashes_and_permissions(self):
        for index, change in enumerate(('extra', 'bytes', 'directory_mode')):
            self.request['run_id'] = 'snapshot-conflict-' + str(index)
            self.prepare(); self.investigations()
            capture = council.snapshot.capture
            def interrupted(*args, **kwargs):
                capture(*args, **kwargs)
                raise KeyboardInterrupt()
            with patch.object(council.snapshot, 'capture', side_effect=interrupted), self.assertRaises(KeyboardInterrupt):
                council.packet(self.run, 'critique', 'native')
            target = self.run / 'critique-snapshot'
            target.chmod(0o700)
            if change == 'extra':
                path = target / 'extra.txt'; path.write_text('preserve'); path.chmod(0o400); target.chmod(0o500)
            elif change == 'bytes':
                path = target / 'evidence.txt'; path.chmod(0o600); path.write_text('changed'); path.chmod(0o400); target.chmod(0o500)
            with self.assertRaises(ValueError): council.packet(self.run, 'critique', 'native')
            if change == 'extra': self.assertEqual(path.read_text(), 'preserve')

    def busy_packet(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from scripts import council as cli
        packet = council.packet(self.run, 'investigate', 'external-one')
        with patch.object(council.workers.settings, 'admission', side_effect=openrouter_settings.SettingsError('openrouter_operation_busy')), patch.object(council.workers.time, 'sleep'), redirect_stdout(StringIO()):
            cli._execute(self.run, 'investigate', packet, self.settings)
        return packet

    def test_resume_cli_uses_same_owner_and_blocks_native_recovery(self):
        from contextlib import redirect_stdout
        from io import BytesIO, StringIO, TextIOWrapper
        from scripts import council as cli
        self.prepare(); packet = self.busy_packet()
        request = dict(run=str(self.run), phase='investigate', member='external-one')
        output = StringIO()
        with patch('sys.argv', ['council', 'resume-member', '--cwd', str(self.repo)]), patch('sys.stdin', TextIOWrapper(BytesIO(json.dumps(request).encode()))), redirect_stdout(output):
            self.assertEqual(cli.main(), 0)
        self.assertNotEqual(json.loads(output.getvalue().splitlines()[-1])['state'], 'not_launched')
        with self.assertRaisesRegex(ValueError, 'invalid_council_member'): council.resume_member(self.run, 'investigate', 'native')
        self.assertTrue(Path(packet['worker_run']).is_dir())

    def test_resume_does_not_refresh_consent_or_evidence_and_blocks_changed_executable(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from scripts import council as cli
        for index, change in enumerate(('consent', 'snapshot', 'executable', 'cancel')):
            self.request['run_id'] = 'resume-guard-' + str(index)
            self.prepare(); packet = self.busy_packet()
            if change == 'consent':
                disabled = openrouter_settings.disable(self.repo, {'expected_revision': self.settings['revision']})
                self.settings = openrouter_settings.enable(self.repo, {'expected_revision': disabled['revision']})
            elif change == 'snapshot':
                path = self.run / 'snapshot/evidence.txt'; path.chmod(0o600); path.write_text('changed'); path.chmod(0o400)
            elif change == 'executable': self.executable.write_text('#!/bin/sh\nexit 1\n')
            else: council.cancel(self.run)
            with patch.object(council.workers.subprocess, 'Popen', wraps=council.workers.subprocess.Popen) as spawn, redirect_stdout(StringIO()):
                if change == 'executable':
                    resumed = council.resume_member(self.run, 'investigate', 'external-one')
                    result = cli._execute(self.run, 'investigate', resumed, self.settings)
                    self.assertEqual(result['failure']['reason'], 'council_runtime_qualification_mismatch')
                else:
                    with self.assertRaises((ValueError, openrouter_settings.SettingsError)):
                        council.resume_member(self.run, 'investigate', 'external-one')
            self.assertEqual([call for call in spawn.call_args_list if call.args[0][0] == str(self.executable)], [])
            if change == 'executable': self.executable.write_text('#!/bin/sh\nexit 0\n')

    def test_cancel_during_busy_backoff_prevents_launch(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from scripts import council as cli
        from runtime.startup import StartupError
        self.prepare(); packet = council.packet(self.run, 'investigate', 'external-one')
        guard = cli._launch_guard
        calls = []
        def busy_then_guard(run, phase):
            calls.append(True)
            if len(calls) == 1: raise StartupError('Onboarding plan busy; retry the same expected revision')
            return guard(run, phase)
        with patch.object(cli, '_launch_guard', side_effect=busy_then_guard), patch.object(council.workers.time, 'sleep', side_effect=lambda _: council.cancel(self.run)), patch.object(council.workers.subprocess, 'Popen', wraps=council.workers.subprocess.Popen) as spawn, redirect_stdout(StringIO()):
            result = cli._execute(self.run, 'investigate', packet, self.settings)
        self.assertEqual(result['state'], 'unresolved')
        self.assertEqual(result['failure']['reason'], 'cancelled')
        self.assertEqual([call for call in spawn.call_args_list if call.args[0][0] == str(self.executable)], [])

    def test_presentation_verification_preserves_original_report_for_advisory_and_hard_limits(self):
        report = ' '.join(['evidence'] * 809)
        for index, hard in enumerate((False, True)):
            self.request['run_id'] = 'presentation-' + str(index)
            self.request['constraints'] = 'Read only. ' + ('Hard maximum: 800 words.' if hard else 'Aim for 800 words.')
            self.prepare()
            packet = council.packet(self.run, 'investigate', 'external-one')
            path = Path(packet['worker_run']) / 'result.json'
            value = dict(state='awaiting_verification', response=report, local_execution_stopped=True)
            path.write_text(json.dumps(value)); path.chmod(0o600)
            checked = council.workers.verify(Path(packet['worker_run']), 'rejected' if hard else 'accepted',
                ['Substantive evidence checked. ' + ('Explicit hard 800-word limit exceeded.' if hard else 'Presentation warning: 809 words exceeds advisory 800-word target; shorten chat delivery.')])
            self.assertEqual(checked['response'], report)
            self.assertEqual(council.status(self.run)['accepted_participation']['investigate']['accepted'], 0 if hard else 1)

    def test_snapshot_and_executable_are_rechecked_after_busy_backoff(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from scripts import council as cli
        from runtime.startup import StartupError
        for index, change in enumerate(('snapshot', 'executable')):
            self.request['run_id'] = 'backoff-recheck-' + str(index)
            self.prepare(); packet = council.packet(self.run, 'investigate', 'external-one')
            guard = cli._launch_guard
            calls = []
            def busy_then_guard(run, phase):
                calls.append(True)
                if len(calls) == 1: raise StartupError('Onboarding plan busy; retry the same expected revision')
                return guard(run, phase)
            def changed(_):
                if change == 'executable': self.executable.write_text('#!/bin/sh\nexit 1\n')
                else:
                    path = self.run / 'snapshot/evidence.txt'; path.chmod(0o600); path.write_text('changed'); path.chmod(0o400)
            with patch.object(cli, '_launch_guard', side_effect=busy_then_guard), patch.object(council.workers.time, 'sleep', side_effect=changed), patch.object(council.workers.subprocess, 'Popen', wraps=council.workers.subprocess.Popen) as spawn, redirect_stdout(StringIO()):
                result = cli._execute(self.run, 'investigate', packet, self.settings)
            self.assertEqual(result['state'], 'unresolved')
            self.assertEqual([call for call in spawn.call_args_list if call.args[0][0] == str(self.executable)], [])
            self.executable.write_text('#!/bin/sh\nexit 0\n')

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

    def test_unprepared_external_members_retain_original_consent_across_phases(self):
        for phase in ('investigate', 'critique'):
            for changed_auth in (False, True):
                with self.subTest(phase=phase, changed_auth=changed_auth):
                    self.request['run_id'] = phase + '-' + str(changed_auth).lower()
                    self.prepare()
                    if phase == 'critique':
                        self.investigations()
                    disabled = openrouter_settings.disable(self.repo, {'expected_revision': self.settings['revision']})
                    if changed_auth:
                        auth = self.temporary / ('auth-' + phase)
                        auth.mkdir(mode=0o700)
                        disabled = openrouter_settings.configure(self.repo, dict(expected_revision=disabled['revision'],
                            routes=['council'], opencode=str(self.executable), auth_data=str(auth)))
                    self.settings = openrouter_settings.enable(self.repo, {'expected_revision': disabled['revision']})
                    with patch.object(council.workers.subprocess, 'Popen', wraps=council.workers.subprocess.Popen) as spawn:
                        with self.assertRaisesRegex(openrouter_settings.SettingsError, 'openrouter_preparation_stale'):
                            council.packet(self.run, phase, 'external-one')
                    self.assertEqual([call for call in spawn.call_args_list if call.args[0][0] == str(self.executable)], [])
                    self.assertFalse((self.root / (self.request['run_id'] + '-' + phase + '-external-one')).exists())
                    self.assertEqual(council.status(self.run)['outcome'], 'partial')

    def test_prepare_rejects_invalid_executable_external_briefs_before_work(self):
        cases = [('steps', 0, 'invalid_bounds'), ('steps', 65, 'invalid_bounds'),
                 ('steps', True, 'invalid_bounds'), ('model', 'no-slash', 'invalid_model'),
                 ('provider', 'bad provider', 'invalid_provider'),
                 ('model_display_name', '', 'invalid_brief_value'),
                 ('model_display_name', [], 'invalid_brief_value'),
                 ('model_display_name', 'x' * 16001, 'invalid_brief_value')]
        original = copy.deepcopy(self.request['roster']['external-one'])
        for number, (field, value, reason) in enumerate(cases):
            with self.subTest(field=field, value=str(value)[:32]):
                self.request['run_id'] = 'invalid-' + str(number)
                seat = copy.deepcopy(original)
                seat[field] = value
                if field in ('model', 'provider'):
                    seat['capabilities'][field] = value
                self.request['roster']['external-one'] = seat
                with self.assertRaisesRegex(ValueError, reason):
                    self.prepare()
                self.assertFalse((self.root / ('council-' + self.request['run_id']) / 'manifest.json').exists())

    def test_prepare_checks_combined_objectives_for_both_external_phases(self):
        for size in (8000, 7820):
            with self.subTest(constraint_length=size):
                self.request.update(run_id='long-' + str(size), question='q' * 8000, constraints='c' * size)
                with self.assertRaisesRegex(ValueError, 'invalid_brief_value'):
                    self.prepare()
                self.assertFalse((self.root / ('council-' + self.request['run_id']) / 'manifest.json').exists())

    def test_prepare_accepts_exact_worker_objective_boundary_without_truncation(self):
        self.request.update(question='q' * 8000, constraints='c' * 7812)
        self.prepare(); self.investigations()
        packet = council.packet(self.run, 'critique', 'external-one')
        brief = json.loads((Path(packet['worker_run']) / 'brief.json').read_text())
        self.assertEqual(len(brief['objective']), 16000)
        self.assertIn(self.request['question'], brief['objective'])
        self.assertIn(self.request['constraints'], brief['objective'])

    def test_prepare_rejects_external_permission_patterns_before_work(self):
        (self.repo / 'pattern*.txt').write_text('Reviewed evidence with an unsafe permission pattern.')
        self.request['approved_files'] = self.approved(['pattern*.txt'])
        with self.assertRaisesRegex(ValueError, 'unsafe_permission_pattern'):
            self.prepare()
        self.assertFalse((self.root / 'council-round-one/manifest.json').exists())

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

    def test_ambiguous_spawn_retains_owner_across_deadline_and_cancellation(self):
        from scripts import council as cli
        for error, category in ((TimeoutError, 'deadline'), (KeyboardInterrupt, 'interrupted')):
            with self.subTest(error=error.__name__):
                self.request['run_id'] = 'ambiguous-' + category
                self.prepare(); self.native('investigate'); self.external('investigate', 'external-two')
                packet = council.packet(self.run, 'investigate', 'external-one')
                launch = council.workers.subprocess.Popen
                def interrupted(command, **kwargs):
                    if command[0] == str(self.executable): raise error()
                    return launch(command, **kwargs)
                with patch.object(council.workers.subprocess, 'Popen', side_effect=interrupted):
                    result = cli._execute(self.run, 'investigate', packet, self.settings)
                self.assertEqual(result['state'], 'unresolved')
                self.assertFalse(council.workers.resumable(result))
                with self.assertRaisesRegex(ValueError, 'member_not_resumable'):
                    council.resume_member(self.run, 'investigate', 'external-one')
                with self.assertRaisesRegex(ValueError, 'already_issued'):
                    council.packet(self.run, 'investigate', 'external-one')
                expected_stop = [dict(phase='investigate', member='external-one', worker_run=packet['worker_run'])]
                report = council.status(self.run)
                self.assertEqual(report['stop_requests'], expected_stop)
                self.assertFalse(report['all_local_execution_stopped'])
                self.assertEqual(report['members']['investigate']['external-one']['state'], 'unresolved')
                with self.assertRaisesRegex(ValueError, 'phase_not_ready'):
                    council.packet(self.run, 'critique', 'native')
                with patch.object(council, '_elapsed', return_value=601):
                    with self.assertRaisesRegex(ValueError, 'phase_not_ready'):
                        council.packet(self.run, 'critique', 'native')
                cancelled = council.cancel(self.run)
                self.assertTrue(cancelled['cancelled'])
                self.assertFalse(cancelled['all_local_execution_stopped'])
                self.assertEqual(cancelled['stop_requests'], expected_stop)

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

    def test_rejected_reused_native_child_records_truthful_stop_without_acceptance(self):
        self.prepare(); self.investigations()
        packet = council.packet(self.run, 'critique', 'native')
        receipt = dict(issued_id=packet['issued_id'], child_id='child-investigate', supervisor_id='coordinator',
            observed_model='native-frontier', observed_effort='max', fork_turns='all',
            local_execution_stopped=True, accepted=False, checks=['Observed reused child and confirmed local stop.'],
            report='Rejected answer from reused child must not become deliberation evidence.')
        council.record_native(self.run, 'critique', 'native', receipt)
        native = council.status(self.run)['members']['critique']['native']
        self.assertEqual(native['state'], 'rejected')
        self.assertTrue(native['local_execution_stopped'])
        self.external('critique', 'external-one'); self.external('critique', 'external-two')
        synthesis = council.packet(self.run, 'synthesis', 'native')
        self.assertNotIn(receipt['report'], synthesis['reports'])
        self.assertIn('Participant 1: rejected', synthesis['execution_observations'])
        self.assertIn('fresh context not confirmed', synthesis['execution_observations'])
        self.assertEqual(council.status(self.run)['outcome'], 'partial')

    def test_fresh_synthesis_receives_frozen_anonymous_execution_gaps_and_unknown_telemetry(self):
        private_reason = 'vendor/private-model on private-provider unavailable; child-private-reference'
        self.request['roster']['external-two'] = dict(kind='external', unavailable_reason=private_reason, selection='native:private-discovery')
        self.prepare(); packet = council.packet(self.run, 'investigate', 'native')
        council.record_native(self.run, 'investigate', 'native', dict(
            issued_id=packet['issued_id'], child_id='private-investigator-child', supervisor_id='coordinator',
            observed_model=None, observed_effort=None, fork_turns='none', controls_verified=True,
            local_execution_stopped=True, accepted=True, checks=['Verified configured controls, scope and evidence.'],
            report='Verified evidence with unknown execution telemetry.'))
        worker = self.external('investigate', 'external-one')
        self.native('critique')
        # A later changed result cannot rewrite the already frozen phase observations.
        path = Path(worker['worker_run']) / 'result.json'
        result = json.loads(path.read_text()); result['state'] = 'failed'
        result['failure'] = dict(category='auth', reason='private-provider/private-account')
        path.write_text(json.dumps(result))
        worker = self.external('critique', 'external-one', state='failed')
        path = Path(worker['worker_run']) / 'result.json'
        result = json.loads(path.read_text()); result['failure'] = dict(category='deadline', reason='private-session-identity')
        path.write_text(json.dumps(result))
        synthesis = council.packet(self.run, 'synthesis', 'native')
        observations = synthesis['execution_observations']
        self.assertIn('Participant 1', observations)
        self.assertIn('investigate', observations)
        self.assertIn('critique', observations)
        self.assertIn('unavailable', observations)
        self.assertIn('details withheld from deliberation', observations)
        self.assertIn('model telemetry unavailable', observations)
        self.assertIn('effort telemetry unavailable', observations)
        self.assertIn('failed', observations)
        self.assertIn('deadline', observations)
        self.assertIn('no verified evidence included', observations)
        self.assertIn('Participant 2: accepted', observations)
        for identity in (private_reason, 'private-provider', 'private-session-identity', 'private-investigator-child', 'native-frontier', 'vendor/frontier', 'external-one', 'external-two'):
            self.assertNotIn(identity, observations)

    def test_synthesis_discloses_frozen_verification_gap_and_late_unreviewed_evidence(self):
        import os
        self.prepare(); self.native('investigate')
        self.external('investigate', 'external-one', state='awaiting_verification')
        late = self.external('investigate', 'external-two')
        path = Path(late['worker_run']) / 'result.json'
        with council._locked(self.run) as value:
            late_wall = value['started_wall'] + 601
        os.utime(path, (late_wall, late_wall))
        with patch.object(council.time, 'monotonic', return_value=time.monotonic() + 601), patch.object(council.time, 'time', return_value=time.time() + 601):
            self.critiques()
            packet = council.packet(self.run, 'synthesis', 'native')
        observations = packet['execution_observations']
        self.assertIn('Participant 2: awaiting_verification', observations)
        self.assertIn('report lacks native verification', observations)
        self.assertIn('Participant 3: late', observations)
        self.assertIn('late/unreviewed evidence', observations)
        self.assertNotIn('initial-2.md', packet['reports'])
        self.assertNotIn('initial-3.md', packet['reports'])

    def grouped_request(self, group='Free', native_slot='member-two'):
        native = self.request['roster']['native']
        external = self.request['roster']['external-one']
        roster = {}
        for number, member in enumerate(('member-one', 'member-two', 'member-three'), 1):
            seat = copy.deepcopy(external)
            seat.update(model=f'vendor/model-{number}' + (':free' if group == 'Free' else ''),
                        canonical_model=f'vendor/model-{number}', pricing=dict(
                            prompt_usd_per_million=0 if group == 'Free' else 1,
                            completion_usd_per_million=0 if group == 'Free' else 2,
                            source='fixture discovery', observed_at='2026-10-30'))
            seat['capabilities']['model'] = seat['model']
            roster[member] = seat
        if group != 'Free':
            roster[native_slot] = dict(native, model='native-' + group.lower())
        self.request.update(group=group, chair='member-one' if group == 'Free' else native_slot, roster=roster)
        return self.request

    def grouped_external(self, phase, member, *, session=None, disposition='accepted', verify=True):
        packet = council.packet(self.run, phase, member)
        path = Path(packet['worker_run']) / 'result.json'
        result = dict(state='awaiting_verification', response=f'{phase} evidence by anonymous participant',
            session_id=session if session is not None else phase + '-' + member,
            local_execution_stopped=True, reported_cost_usd=0, known_cost_subtotal_usd=0,
            accounting_complete=True, upstream_cancellation_confirmed=False)
        council.workers.save(path, result)
        if verify:
            council.verify_external(self.run, phase, member, disposition, ['Host verified citations, scope and freshness.'])
        return packet

    def grouped_rounds(self, rejected=()):
        for phase in ('investigate', 'critique'):
            for member in self.request['roster']:
                self.grouped_external(phase, member, disposition='rejected' if member in rejected else 'accepted')

    def test_grouped_free_seven_fresh_external_results_complete_and_accounted(self):
        self.grouped_request(); self.prepare()
        manifest = json.loads((self.run / 'manifest.json').read_text())
        self.assertEqual(manifest['version'], 2)
        self.grouped_rounds()
        self.assertEqual(council.status(self.run)['outcome'], 'partial')
        packet = self.grouped_external('synthesis', self.request['chair'])
        report = council.status(self.run)
        self.assertEqual(report['outcome'], 'complete')
        self.assertTrue(report['fresh_synthesis_available'])
        self.assertEqual(report['external_total_usd'], 0)
        self.assertEqual(sum(len(x) for x in report['members'].values()), 7)
        self.assertTrue(report['all_local_execution_stopped'])
        source = Path(packet['snapshot'])
        self.assertNotEqual(source.name, 'critique-snapshot')
        for number in range(1, 4):
            self.assertIn('critique evidence', (source / f'__council__/critique-{number}.md').read_text())
        observations = (source / '__council__/execution-observations.md').read_text()
        self.assertIn('investigate execution observations', observations)
        self.assertIn('critique execution observations', observations)
        self.assertNotIn('vendor/', observations)
        self.assertNotIn('session_id', observations)

    def test_grouped_paid_native_selection_and_chair_are_per_run(self):
        for group in ('Frontier', 'Balanced'):
            self.request['run_id'] = group.lower()
            # Reuse only a complete legacy fixture seat while selecting the new group.
            if 'native' not in self.request['roster']:
                self.request['roster'] = {'native': self.native_fixture, 'external-one': self.external_fixture}
            else:
                self.native_fixture = copy.deepcopy(self.request['roster']['native'])
                self.external_fixture = copy.deepcopy(self.request['roster']['external-one'])
            self.grouped_request(group); self.prepare()
            packet = council.packet(self.run, 'investigate', 'member-two')
            self.assertEqual(packet['kind'], 'native')
            self.assertEqual(packet['model'], 'native-' + group.lower())
            receipt = dict(issued_id=packet['issued_id'], child_id='child-' + group,
                supervisor_id='coordinator', observed_model=packet['model'], observed_effort='max',
                fork_turns='none', local_execution_stopped=True, accepted=True,
                checks=['Host verified'], report='Native finding')
            council.record_native(self.run, 'investigate', 'member-two', receipt)
            self.assertEqual(council.status(self.run)['accepted_participation']['investigate']['accepted'], 1)

    def test_grouped_roster_rejects_wrong_topology_free_pricing_and_duplicate_identity(self):
        base = copy.deepcopy(self.grouped_request())
        cases = []
        def changed(change):
            request = copy.deepcopy(base); change(request); cases.append(request)
        changed(lambda r: r.update(group='Unknown'))
        changed(lambda r: r.update(chair='native'))
        changed(lambda r: r['roster'].pop('member-three'))
        changed(lambda r: r['roster']['member-two'].update(kind='native'))
        changed(lambda r: r['roster']['member-two']['pricing'].update(prompt_usd_per_million=.1))
        changed(lambda r: r['roster']['member-two']['pricing'].update(completion_usd_per_million=True))
        changed(lambda r: r['roster']['member-two'].update(canonical_model='vendor/model-1'))
        changed(lambda r: r['roster']['member-two'].update(model='vendor/paid'))
        changed(lambda r: r['roster']['member-two'].update(unavailable_reason='No route'))
        changed(lambda r: r.update(group='Balanced'))
        changed(lambda r: r['roster']['member-two'].pop('pricing'))
        for request in cases:
            with self.subTest(request=request), self.assertRaises(ValueError): council.prepare(self.repo, request)
        self.assertFalse((self.root / 'council-round-one').exists())

    def test_grouped_nonchair_synthesis_and_native_free_are_blocked(self):
        self.grouped_request(); self.prepare(); self.grouped_rounds()
        for member in ('native', 'member-two', 'member-three'):
            with self.assertRaisesRegex(ValueError, 'invalid_council_member'):
                council.packet(self.run, 'synthesis', member)
        with self.assertRaises(ValueError): council.record_native(self.run, 'synthesis', 'member-one', {})

    def test_grouped_reduced_coverage_counts_same_external_members(self):
        self.grouped_request(); self.prepare(); self.grouped_rounds(rejected=('member-three',))
        self.grouped_external('synthesis', 'member-one')
        report = council.status(self.run)
        self.assertEqual(report['outcome'], 'incomplete')
        self.assertEqual(report['accepted_participation']['critique']['accepted'], 2)

    def test_grouped_missing_or_reused_session_and_manual_acceptance_do_not_count(self):
        self.grouped_request(); self.prepare()
        packet = self.grouped_external('investigate', 'member-one')
        duplicate = self.grouped_external('investigate', 'member-two', session='investigate-member-one', verify=False)
        with self.assertRaisesRegex(ValueError, 'fresh_external_session_required'):
            council.verify_external(self.run, 'investigate', 'member-two', 'accepted', ['Host verified'])
        path = Path(duplicate['worker_run']) / 'result.json'
        result = json.loads(path.read_text()); result.update(state='accepted', native_checks=['Manual bypass'])
        council.workers.save(path, result)
        self.assertEqual(council.status(self.run)['accepted_participation']['investigate']['accepted'], 1)
        missing = self.grouped_external('investigate', 'member-three', session='', verify=False)
        with self.assertRaisesRegex(ValueError, 'fresh_external_session_required'):
            council.verify_external(self.run, 'investigate', 'member-three', 'accepted', ['Host verified'])
        council.verify_external(self.run, 'investigate', 'member-three', 'rejected', ['No session observed'])
        with self.assertRaisesRegex(ValueError, 'grouped_council_verification_required'):
            council.workers.verify(Path(missing['worker_run']), 'accepted', ['Manual bypass'])
        path = Path(packet['worker_run']) / 'result.json'
        result = json.loads(path.read_text()); result['response'] = 'Changed verified bytes'
        council.workers.save(path, result)
        self.assertEqual(council.status(self.run)['accepted_participation']['investigate']['accepted'], 0)

    def test_grouped_synthesis_session_freshness_and_terminal_stop_owner(self):
        self.grouped_request(); self.prepare(); self.grouped_rounds()
        packet = self.grouped_external('synthesis', 'member-one', session='investigate-member-one', verify=False)
        with self.assertRaisesRegex(ValueError, 'fresh_external_session_required'):
            council.verify_external(self.run, 'synthesis', 'member-one', 'accepted', ['Host verified'])
        path = Path(packet['worker_run']) / 'result.json'
        result = json.loads(path.read_text()); result.update(state='unresolved', session_id=None,
            local_execution_stopped=False, reported_cost_usd=None, known_cost_subtotal_usd=.05,
            accounting_complete=False, failure=dict(category='runtime', launch_stage='spawn'))
        council.workers.save(path, result)
        report = council.cancel(self.run)
        self.assertFalse(report['fresh_synthesis_available'])
        self.assertIsNone(report['external_total_usd'])
        self.assertEqual(report['known_external_subtotal_usd'], .05)
        self.assertEqual(report['stop_requests'], [dict(phase='synthesis', member='member-one', worker_run=packet['worker_run'])])
        result['local_execution_stopped'] = True; council.workers.save(path, result)
        self.assertTrue(council.status(self.run)['all_local_execution_stopped'])

    def test_grouped_launch_rechecks_paid_variant_and_pinned_roster(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from scripts import council as cli
        self.grouped_request(); self.prepare()
        packet = council.packet(self.run, 'investigate', 'member-one')
        path = Path(packet['worker_run']) / 'brief.json'
        brief = json.loads(path.read_text())
        brief['model'] = 'vendor/paid'; brief['capabilities']['model'] = brief['model']
        council.workers.save(path, brief)
        with patch.object(council.workers.subprocess, 'Popen', wraps=council.workers.subprocess.Popen) as spawn, redirect_stdout(StringIO()):
            try: cli._execute(self.run, 'investigate', packet, self.settings)
            except ValueError: pass
        self.assertEqual([call for call in spawn.call_args_list if call.args[0][0] == str(self.executable)], [])

    def test_grouped_synthesis_frozen_changes_and_lost_original_response(self):
        self.grouped_request(); self.prepare(); self.grouped_rounds()
        original = council.workers.prepare_council
        def lost(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError('lost packet response')
        with patch.object(council.workers, 'prepare_council', side_effect=lost), self.assertRaises(OSError):
            council.packet(self.run, 'synthesis', 'member-one')
        status = council.status(self.run)
        self.assertFalse(status['all_local_execution_stopped'])
        self.assertEqual(status['stop_requests'][0]['member'], 'member-one')
        with self.assertRaises(FileExistsError): council.packet(self.run, 'synthesis', 'member-one')
        path = self.run / 'critique-1.md'; path.write_text('tampered'); path.chmod(0o600)
        with self.assertRaisesRegex(ValueError, 'frozen_evidence_changed'): council.status(self.run)

    def test_grouped_headroom_and_synthesis_objective_preflight(self):
        self.grouped_request()
        manifest = dict(files={str(i): dict(size=1) for i in range(council.snapshot.MAX_PATHS - 7)})
        with self.assertRaisesRegex(ValueError, 'headroom'):
            council._phase_headroom(manifest, self.request['roster'], grouped=True)
        self.request['question'] = 'q' * 7900
        self.request['constraints'] = 'c' * 7850
        # The longest phase must be validated too, before the first dispatch.
        with patch.object(council.workers, '_validate_council_brief', wraps=council.workers._validate_council_brief) as validate:
            self.prepare()
        self.assertEqual({call.args[0]['council']['phase'] for call in validate.call_args_list}, set(council.PHASES))

    def test_grouped_real_seven_attempts_verify_original_sessions_and_cli(self):
        from contextlib import redirect_stdout
        from io import BytesIO, StringIO, TextIOWrapper
        from scripts import council as cli
        self.executable.write_text('#!/usr/bin/env python3\nimport json, sys\n'
            'session = sys.argv[sys.argv.index("--title") + 1]\n'
            'print(json.dumps({"type":"text","sessionID":session,"part":{"text":"Evidence: evidence.txt; uncertainty retained."}}))\n'
            'print(json.dumps({"type":"step_finish","sessionID":session,"part":{"reason":"stop","cost":0,"tokens":{"input":1,"output":1}}}))\n')
        digest = hashlib.sha256(self.executable.read_bytes()).hexdigest()
        self.grouped_request()
        for seat in self.request['roster'].values(): seat['permission_qualification']['opencode_sha256'] = digest
        self.prepare(); sessions = []
        for phase in council.PHASES:
            members = list(self.request['roster']) if phase != 'synthesis' else [self.request['chair']]
            for member in members:
                packet = council.packet(self.run, phase, member)
                with redirect_stdout(StringIO()): result = cli._execute(self.run, phase, packet, self.settings)
                self.assertEqual(result['state'], 'awaiting_verification')
                sessions.append(result['session_id'])
                request = dict(run=str(self.run), phase=phase, member=member, disposition='accepted', checks=['Host source and scope verified'])
                with patch('sys.argv', ['council', 'verify-external', '--cwd', str(self.repo)]), patch('sys.stdin', TextIOWrapper(BytesIO(json.dumps(request).encode()))), redirect_stdout(StringIO()):
                    self.assertEqual(cli.main(), 0)
        self.assertEqual(len(set(sessions)), 7)
        self.assertEqual(council.status(self.run)['outcome'], 'complete')

    def test_grouped_failed_external_chair_never_advertises_native_fallback(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from scripts import council as cli
        self.grouped_request(); self.prepare(); self.grouped_rounds()
        packet = council.packet(self.run, 'synthesis', 'member-one')
        # The fixture exits without a report; its actual stop still settles ownership.
        with redirect_stdout(StringIO()): result = cli._execute(self.run, 'synthesis', packet, self.settings)
        self.assertTrue(result['local_execution_stopped'])
        self.assertFalse(result['native_fallback_ready'])
        report = council.status(self.run)
        self.assertFalse(report['fresh_synthesis_available'])
        self.assertTrue(report['all_local_execution_stopped'])
        self.assertIsNone(report['external_total_usd'])

    def test_grouped_external_synthesis_resume_retains_deadline_and_original_consent(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from scripts import council as cli
        self.grouped_request(); self.prepare(); self.grouped_rounds()
        packet = council.packet(self.run, 'synthesis', 'member-one')
        with patch.object(council.workers.settings, 'admission', side_effect=openrouter_settings.SettingsError('openrouter_operation_busy')), patch.object(council.workers.time, 'sleep'), redirect_stdout(StringIO()):
            result = cli._execute(self.run, 'synthesis', packet, self.settings)
        resumed = council.resume_member(self.run, 'synthesis', 'member-one')
        self.assertEqual(resumed['worker_run'], packet['worker_run'])
        self.assertEqual(resumed['deadline_monotonic'], result['deadline_monotonic'])
        disabled = openrouter_settings.disable(self.repo, {'expected_revision': self.settings['revision']})
        openrouter_settings.enable(self.repo, {'expected_revision': disabled['revision']})
        with self.assertRaisesRegex(openrouter_settings.SettingsError, 'openrouter_preparation_stale'):
            council.resume_member(self.run, 'synthesis', 'member-one')
        council.cancel(self.run)
        with self.assertRaisesRegex(ValueError, 'cancelled'):
            council.resume_member(self.run, 'synthesis', 'member-one')

    def test_grouped_synthesis_unknown_session_rejects_but_can_settle_after_cancel(self):
        self.grouped_request(); self.prepare(); self.grouped_rounds()
        packet = self.grouped_external('synthesis', 'member-one', session='', verify=False)
        with self.assertRaisesRegex(ValueError, 'fresh_external_session_required'):
            council.verify_external(self.run, 'synthesis', 'member-one', 'accepted', ['Host checked'])
        council.cancel(self.run)
        council.verify_external(self.run, 'synthesis', 'member-one', 'rejected', ['Unknown session, stopped original owner'])
        self.assertTrue(council.status(self.run)['all_local_execution_stopped'])
        self.assertFalse(council.status(self.run)['fresh_synthesis_available'])

    def test_grouped_partial_coverage_and_pinned_brief_identity_on_launch(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from scripts import council as cli
        self.grouped_request(); self.prepare(); self.grouped_rounds(rejected=('member-two', 'member-three'))
        packet = council.packet(self.run, 'synthesis', 'member-one')
        path = Path(packet['worker_run']) / 'brief.json'
        brief = json.loads(path.read_text()); brief['canonical_model'] = 'vendor/changed-identity'
        council.workers.save(path, brief)
        with patch.object(council.workers.subprocess, 'Popen', wraps=council.workers.subprocess.Popen) as spawn, redirect_stdout(StringIO()):
            result = cli._execute(self.run, 'synthesis', packet, self.settings)
        self.assertEqual([call for call in spawn.call_args_list if call.args[0][0] == str(self.executable)], [])
        self.assertTrue(result['local_execution_stopped'])
        self.assertEqual(council.status(self.run)['outcome'], 'partial')

    def test_grouped_paid_full_native_chair_and_wrong_chair(self):
        self.grouped_request('Balanced')
        wrong = copy.deepcopy(self.request); wrong['chair'] = 'member-one'
        with self.assertRaisesRegex(ValueError, 'topology'): council.prepare(self.repo, wrong)
        self.prepare()
        for phase in council.PHASES:
            members = self.request['roster'] if phase != 'synthesis' else ['member-two']
            for member in members:
                if member != 'member-two': self.grouped_external(phase, member); continue
                packet = council.packet(self.run, phase, member)
                receipt = dict(issued_id=packet['issued_id'], child_id='balanced-' + phase,
                    supervisor_id='coordinator', observed_model='native-balanced', observed_effort='max',
                    fork_turns='none', local_execution_stopped=True, accepted=True,
                    checks=['Host source and scope verified'], report='Supported native evidence and dissent')
                council.record_native(self.run, phase, member, receipt)
        self.assertEqual(council.status(self.run)['outcome'], 'complete')

    def test_grouped_synthesis_snapshot_recovers_without_clobbering_conflicts(self):
        self.grouped_request(); self.prepare(); self.grouped_rounds()
        original = council.snapshot.capture
        def interrupted(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError('lost sealed snapshot response')
        with patch.object(council.snapshot, 'capture', side_effect=interrupted), self.assertRaises(OSError):
            council.packet(self.run, 'synthesis', 'member-one')
        packet = council.packet(self.run, 'synthesis', 'member-one')
        self.assertIn('critique evidence', (Path(packet['snapshot']) / '__council__/critique-1.md').read_text())
        self.assertEqual(json.loads((self.run / 'manifest.json').read_text())['phase'], 'synthesis')

    def test_grouped_all_seven_stop_owners_and_ambiguous_spawn_are_retained(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from scripts import council as cli
        self.grouped_request(); self.prepare(); self.grouped_rounds()
        packet = council.packet(self.run, 'synthesis', 'member-one')
        original = council.workers.subprocess.Popen
        def ambiguous(command, *args, **kwargs):
            if command[0] == str(self.executable): raise OSError('ambiguous spawn')
            return original(command, *args, **kwargs)
        with patch.object(council.workers.subprocess, 'Popen', side_effect=ambiguous), redirect_stdout(StringIO()):
            result = cli._execute(self.run, 'synthesis', packet, self.settings)
        self.assertFalse(result['local_execution_stopped'])
        self.assertEqual(result['failure']['launch_stage'], 'spawn')
        self.assertEqual(council.status(self.run)['stop_requests'], [dict(phase='synthesis', member='member-one', worker_run=packet['worker_run'])])
        for path in self.root.glob('round-one-*/result.json'):
            result = json.loads(path.read_text()); result['local_execution_stopped'] = False
            council.workers.save(path, result)
        owners = council.cancel(self.run)['stop_requests']
        self.assertEqual(len(owners), 7)
        self.assertEqual(len({owner['worker_run'] for owner in owners}), 7)
        with self.assertRaisesRegex(ValueError, 'not_resumable|cancelled'):
            council.resume_member(self.run, 'synthesis', 'member-one')

    def test_grouped_expired_synthesis_cannot_be_accepted_or_refreshed(self):
        self.grouped_request(); self.prepare(); self.grouped_rounds()
        self.grouped_external('synthesis', 'member-one', verify=False)
        with patch.object(council, '_elapsed', return_value=1201):
            with self.assertRaisesRegex(ValueError, 'deadline_exhausted'):
                council.verify_external(self.run, 'synthesis', 'member-one', 'accepted', ['Host verified'])
            council.verify_external(self.run, 'synthesis', 'member-one', 'rejected', ['Late stopped output'])
        self.assertFalse(council.status(self.run)['fresh_synthesis_available'])

    def test_grouped_verification_rejects_changed_original_worker_copy(self):
        self.grouped_request(); self.prepare()
        packet = self.grouped_external('investigate', 'member-one', verify=False)
        path = Path(packet['worker_run']) / 'workspace/evidence.txt'
        path.chmod(0o600); path.write_text('changed copied evidence'); path.chmod(0o400)
        with self.assertRaises(ValueError):
            council.verify_external(self.run, 'investigate', 'member-one', 'accepted', ['Host verified'])
        self.assertEqual(council.status(self.run)['accepted_participation']['investigate']['accepted'], 0)
        self.assertTrue(council.status(self.run)['all_local_execution_stopped'])

    def test_grouped_direct_worker_execution_keeps_absolute_phase_deadline(self):
        from contextlib import redirect_stdout
        from io import StringIO
        self.grouped_request(); self.prepare()
        packet = council.packet(self.run, 'investigate', 'member-one')
        # Model a delayed dispatch without waiting or renewing its original ceiling.
        with council._locked(self.run) as value:
            value['started_monotonic'] -= 10; value['started_wall'] -= 10
            expected = value['started_monotonic'] + council._end(value, 'investigate')
            council._save(self.run, value)
        with redirect_stdout(StringIO()):
            result = council.workers.execute(Path(packet['worker_run']), self.executable, self.auth)
        self.assertLessEqual(result['deadline_monotonic'], expected)


    def test_grouped_free_documented_default_survives_all_phases_without_maximum_claim(self):
        self.grouped_request()
        seat = self.request['roster']['member-one']
        seat['effort'] = 'default'
        seat['capabilities'].update(reasoning={'default_enabled': True},
            source='Exact route documentation: reasoning enabled by default; maximum mapping unverified')
        self.prepare(); self.grouped_rounds()
        packet = self.grouped_external('synthesis', 'member-one')
        brief = json.loads((Path(packet['worker_run']) / 'brief.json').read_text())
        self.assertEqual(brief['effort'], 'default')
        self.assertEqual(brief['capabilities']['reasoning'], {'default_enabled': True})
        self.assertNotIn('reasoning', council.workers.configuration(brief)['provider']['openrouter']['models'][seat['model']]['options'])
        report = council.status(self.run)
        self.assertEqual(report['outcome'], 'complete')
        self.assertEqual(report['external_total_usd'], 0)
        self.assertTrue(report['fresh_synthesis_available'])
