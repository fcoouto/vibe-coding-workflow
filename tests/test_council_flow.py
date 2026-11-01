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
        self.request = dict(mode='repository', run_id='round-one', question='What follows from the evidence?',
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
            checks=['Native checked scope, decisive citations and omissions.'], report=report if accepted else '')
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

    def test_new_run_requires_mode(self):
        for index, mode in enumerate((None, '', 'automatic', True)):
            with self.subTest(mode=mode):
                self.request['run_id'] = 'invalid-mode-' + str(index)
                if mode is None: self.request.pop('mode', None)
                else: self.request['mode'] = mode
                with self.assertRaisesRegex(ValueError, 'invalid_council_mode'):
                    council.prepare(self.repo, self.request)
                self.assertFalse((self.root / ('council-' + self.request['run_id'])).exists())

    def test_text_question_allows_no_files_without_checkout_writes(self):
        self.request.update(mode='text', approved_files={})
        for seat in self.request['roster'].values():
            if seat['kind'] != 'external': continue
            seat['steps'] = 1
            seat['capabilities']['api'] = 'chat-completions'
            seat['permission_qualification'] = dict(profile='council-text-v1', evidence='native:controlled-probe')
        before = {str(path.relative_to(self.repo)): path.read_bytes()
                  for path in self.repo.rglob('*') if path.is_file()}
        self.prepare()
        manifest = json.loads((self.run / 'manifest.json').read_text())
        self.assertEqual((manifest['mode'], manifest['flow']), ('text', 'peer-review'))
        self.assertEqual(manifest['snapshot_manifest']['files'], {})
        council.snapshot.verify(self.run / 'snapshot', manifest['snapshot_manifest'])
        self.assertEqual(before, {str(path.relative_to(self.repo)): path.read_bytes()
                         for path in self.repo.rglob('*') if path.is_file()})

    def test_repository_requires_approved_files(self):
        self.request.update(mode='repository', approved_files={})
        with self.assertRaisesRegex(ValueError, 'repository_approved_files_required'):
            self.prepare()
        self.assertFalse((self.root / 'council-round-one').exists())

    def test_repository_native_retains_inspection_instead_of_text_prompt(self):
        self.prepare()
        packet = council.packet(self.run, 'investigate', 'native')
        self.assertNotIn('prompt', packet)
        self.assertNotIn('prompt_sha256', packet)
        self.assertTrue((Path(packet['snapshot']) / 'evidence.txt').is_file())

    def test_repository_requires_captured_approved_files(self):
        (self.repo / '.env').write_text('SYNTHETIC_PRIVATE_FIXTURE=excluded')
        self.request['approved_files'] = self.approved(['.env'])
        with self.assertRaisesRegex(ValueError, 'repository_approved_files_required'):
            self.prepare()
        self.assertFalse((self.root / 'round-one-investigate-external-one').exists())

    def test_free_prepare_and_all_inference_paths_blocked(self):
        self.grouped_request('Free')
        with self.assertRaisesRegex(ValueError, 'free_council_temporarily_disabled'):
            self.prepare()
        self.assertFalse((self.root / 'council-round-one').exists())
        # Even an on-disk Free marker cannot reopen an otherwise current paid run.
        self.request['roster']['member-three'] = dict(kind='native', model='native-balanced', effort='max',
            supported_efforts=['max'], input_tokens=10000, output_tokens=4096, steps=12,
            selection='Approved native controls', supervisor_id='coordinator')
        self.request.update(group='Balanced', chair='member-three')
        self.prepare()
        packet = council.packet(self.run, 'investigate', 'member-one')
        brief = json.loads((Path(packet['worker_run']) / 'brief.json').read_text())
        with council._locked(self.run) as value:
            value['group'] = 'Free'
            council._save(self.run, value)
        from scripts import council as cli
        from contextlib import redirect_stdout
        from io import StringIO
        def launch_guard():
            with council.external_launch_guard(Path(packet['worker_run']), brief): pass
        def cli_guard():
            with cli._launch_guard(self.run, 'investigate'): pass
        for operation in (lambda: council.packet(self.run, 'investigate', 'member-three'),
                          lambda: council.resume_member(self.run, 'investigate', 'member-one'),
                          launch_guard, cli_guard):
            with self.assertRaisesRegex(ValueError, 'free_council_temporarily_disabled'):
                operation()
        with redirect_stdout(StringIO()):
            result = council.workers.execute(Path(packet['worker_run']), self.executable, self.auth)
        self.assertEqual(result['state'], 'unresolved')
        self.assertEqual(result['failure']['reason'], 'free_council_temporarily_disabled')
        self.assertIsNone(result['session_id'])

    def test_historical_status_cancel_and_settlement_only(self):
        self.prepare()
        packet = council.packet(self.run, 'investigate', 'native')
        accepted = self.external('investigate', 'external-one', report='Historical original report', cost=0)
        external = council.packet(self.run, 'investigate', 'external-two')
        with council._locked(self.run) as value:
            value.pop('flow', None)
            value['verification_feedback'] = True
            value['members']['investigate:native']['findings'] = [dict(
                claim='Historical disputed claim', correction='Historical correction', evidence='Historical source')]
            feedback = b'Original historical verification feedback.'
            council.changes._atomic(self.run, 'verification-feedback.md', feedback)
            value['frozen']['verification-feedback.md'] = hashlib.sha256(feedback).hexdigest()
            council._save(self.run, value)
        originals = {path: path.read_bytes() for path in self.run.rglob('*')
                     if path.is_file() and path.name not in ('manifest.json', 'lock', 'execution.lock')}
        accepted_result = Path(accepted['worker_run']) / 'result.json'
        originals[accepted_result] = accepted_result.read_bytes()
        for operation in (
                lambda: council.packet(self.run, 'investigate', 'external-two'),
                lambda: council.resume_member(self.run, 'investigate', 'external-two'),
                lambda: council.workers.verify(Path(external['worker_run']), 'accepted', ['Checked'])):
            with self.assertRaisesRegex(ValueError, 'historical_council_read_only'):
                operation()
        from contextlib import redirect_stdout
        from io import StringIO
        with redirect_stdout(StringIO()):
            result = council.workers.execute(Path(external['worker_run']), self.executable, self.auth)
        self.assertEqual(result['failure']['reason'], 'historical_council_read_only')
        self.assertTrue(result['local_execution_stopped'])
        receipt = dict(issued_id=packet['issued_id'], child_id='historical-child', supervisor_id='coordinator',
            observed_model=None, observed_effort=None, fork_turns=None, local_execution_stopped=True,
            accepted=True, checks=['Stopped historical child'], report='New historical verdict')
        with self.assertRaisesRegex(ValueError, 'historical_council_read_only'):
            council.record_native(self.run, 'investigate', 'native', receipt)
        council.cancel(self.run)
        receipt.update(accepted=False, report='')
        council.record_native(self.run, 'investigate', 'native', receipt)
        state = council.status(self.run)
        self.assertTrue(state['cancelled'])
        self.assertTrue(state['all_local_execution_stopped'])
        self.assertFalse(state['fresh_synthesis_available'])
        self.assertEqual(originals, {path: path.read_bytes() for path in originals})
        retained = json.loads((self.run / 'manifest.json').read_text())
        self.assertEqual(retained['members']['investigate:native']['findings'][0]['correction'], 'Historical correction')

    def test_historical_native_stop_requires_child_id_without_writes(self):
        self.prepare()
        packet = council.packet(self.run, 'investigate', 'native')
        with council._locked(self.run) as value:
            value.pop('flow')
            council._save(self.run, value)
        before = (self.run / 'manifest.json').read_bytes()
        receipt = dict(issued_id=packet['issued_id'], supervisor_id='coordinator', accepted=False,
                       report='', local_execution_stopped=True, checks=['Observed stop'])
        with self.assertRaisesRegex(ValueError, 'invalid_native_stop_receipt'):
            council.record_native(self.run, 'investigate', 'native', receipt)
        self.assertEqual(before, (self.run / 'manifest.json').read_bytes())

    def test_no_initial_answer_stops_without_chair(self):
        self.prepare()
        self.native('investigate', '', accepted=False)
        for member in ('external-one', 'external-two'):
            self.external('investigate', member, '', state='failed')
        before = (self.run / 'manifest.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'no_initial_answers'):
            council.packet(self.run, 'critique', 'native')
        self.assertEqual(before, (self.run / 'manifest.json').read_bytes())
        with self.assertRaisesRegex(ValueError, 'phase_not_ready'):
            council.packet(self.run, 'synthesis', 'native')
        state = council.status(self.run)
        self.assertFalse(state['fresh_synthesis_available'])
        self.assertEqual(state['accepted_participation']['investigate']['accepted'], 0)

    def test_partial_counts_and_failed_chair_are_honest(self):
        self.request['roster']['external-two'] = dict(kind='external', unavailable_reason='Unavailable', selection='native:discovery')
        self.prepare(); self.investigations(second=False); self.critiques()
        self.native('synthesis', '', accepted=False)
        state = council.status(self.run)
        self.assertEqual(state['accepted_participation'], dict(investigate=dict(accepted=2, expected=3),
            critique=dict(accepted=2, expected=3), synthesis=dict(accepted=0, expected=1)))
        self.assertEqual(state['outcome'], 'partial')
        self.assertFalse(state['fresh_synthesis_available'])
        self.assertTrue((self.run / 'initial-1.md').exists())
        self.assertTrue((self.run / 'critique-2.md').exists())

    def test_historical_free_prices_reports_and_hashes_remain_readable(self):
        current = copy.deepcopy(self.request)
        historical = copy.deepcopy(self.grouped_request('Free'))
        self.request = current
        self.prepare()
        report = b'Original historical Free report and dissent.'
        council.changes._atomic(self.run, 'initial-1.md', report)
        worker = self.root / 'round-one-investigate-member-one'
        worker.mkdir(mode=0o700)
        result = dict(state='accepted', response=report.decode(), session_id='historical-free-session',
            local_execution_stopped=True, reported_cost_usd=0, known_cost_subtotal_usd=0,
            accounting_complete=True, native_checks=['Original historical check'])
        council.workers.save(worker / 'result.json', result)
        original_result = (worker / 'result.json').read_bytes()
        with council._locked(self.run) as value:
            value.pop('flow'); value.pop('mode')
            value.update(version=2, group='Free', chair='member-one', roster=historical['roster'])
            value['frozen']['initial-1.md'] = hashlib.sha256(report).hexdigest()
            value['members']['investigate:member-one'] = dict(kind='external', worker_run=str(worker),
                verification=dict(sha256=hashlib.sha256(original_result).hexdigest(), session_id='historical-free-session'))
            council._save(self.run, value)
        self.assertEqual(council.status(self.run)['external_total_usd'], 0)
        self.assertEqual(council.cancel(self.run)['accepted_participation']['investigate']['accepted'], 1)
        with self.assertRaisesRegex(ValueError, 'free_council_temporarily_disabled'):
            council.packet(self.run, 'investigate', 'member-two')
        after = json.loads((self.run / 'manifest.json').read_text())
        self.assertEqual(after['roster'], historical['roster'])
        self.assertEqual(after['frozen']['initial-1.md'], hashlib.sha256(report).hexdigest())
        self.assertEqual((self.run / 'initial-1.md').read_bytes(), report)
        self.assertEqual((worker / 'result.json').read_bytes(), original_result)

    def test_legacy_worker_verdict_holds_council_phase_lock(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from runtime.startup import StartupError
        self.prepare(); self.native('investigate')
        packet = self.external('investigate', 'external-one', state='awaiting_verification')
        self.external('investigate', 'external-two')
        original = council.workers.save
        blocked = []
        def save_after_competing_phase_transition(path, result):
            try: council.packet(self.run, 'critique', 'native')
            except StartupError: blocked.append(True)
            else: blocked.append(False)
            return original(path, result)
        with redirect_stdout(StringIO()), patch.object(council, '_elapsed', return_value=601), patch.object(council.workers, 'save', side_effect=save_after_competing_phase_transition):
            council.workers.verify(Path(packet['worker_run']), 'rejected', ['Observed runtime failure; original owner stopped'],
                                   failure=dict(category='runtime'))
        self.assertEqual(blocked, [True])
        self.assertEqual(council.status(self.run)['phase'], 'investigate')

    def test_closed_phase_rejects_late_result(self):
        self.prepare(); self.investigations()
        council.packet(self.run, 'critique', 'native')
        original = (self.run / 'initial-1.md').read_bytes()
        with self.assertRaisesRegex(ValueError, 'native_phase_closed'):
            council.record_native(self.run, 'investigate', 'native', {})
        self.assertEqual((self.run / 'initial-1.md').read_bytes(), original)

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
        guard = council.external_launch_guard
        calls = []
        def busy_then_guard(run, phase):
            calls.append(True)
            if len(calls) == 1: raise StartupError('Onboarding plan busy; retry the same expected revision')
            return guard(run, phase)
        with patch.object(council, 'external_launch_guard', side_effect=busy_then_guard), patch.object(council.workers.time, 'sleep', side_effect=lambda _: council.cancel(self.run)), patch.object(council.workers.subprocess, 'Popen', wraps=council.workers.subprocess.Popen) as spawn, redirect_stdout(StringIO()):
            result = cli._execute(self.run, 'investigate', packet, self.settings)
        self.assertEqual(result['state'], 'unresolved')
        self.assertEqual(result['failure']['reason'], 'cancelled')
        self.assertEqual([call for call in spawn.call_args_list if call.args[0][0] == str(self.executable)], [])

    def test_ungrouped_technical_disposition_preserves_content_and_scope_failure(self):
        self.prepare()
        packet = council.packet(self.run, 'investigate', 'external-one')
        path = Path(packet['worker_run']) / 'result.json'
        report = 'An uncited answer that a critic may dispute.'
        council.workers.save(path, dict(state='awaiting_verification', response=report, local_execution_stopped=True))
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'technical_failure_required'):
            council.workers.verify(Path(packet['worker_run']), 'rejected', ['Disagree with claim'])
        self.assertEqual(before, path.read_bytes())
        checked = council.workers.verify(Path(packet['worker_run']), 'accepted', ['Scope and completion checked'])
        self.assertEqual(checked['response'], report)
        self.assertEqual(council.status(self.run)['accepted_participation']['investigate']['accepted'], 1)
        packet = council.packet(self.run, 'investigate', 'external-two')
        path = Path(packet['worker_run']) / 'result.json'
        council.workers.save(path, dict(state='awaiting_verification', response=report, local_execution_stopped=True))
        checked = council.workers.verify(Path(packet['worker_run']), 'rejected', ['Observed scope violation'],
                                         failure=dict(category='permission', private='withheld'))
        self.assertEqual(checked['response'], report)
        self.assertEqual(checked['failure'], dict(category='permission'))

    def test_ungrouped_verification_requires_stopped_nonempty_bounded_response(self):
        self.prepare()
        packet = council.packet(self.run, 'investigate', 'external-one')
        path = Path(packet['worker_run']) / 'result.json'
        for report, stopped, error in (('', True, 'external_report_required'),
                ('x' * (128 * 1024 + 1), True, 'report_limit'), ('An answer', False, 'not_verifiable')):
            with self.subTest(error=error):
                council.workers.save(path, dict(state='awaiting_verification', response=report, local_execution_stopped=stopped))
                before = path.read_bytes()
                with self.assertRaisesRegex(ValueError, error):
                    council.workers.verify(Path(packet['worker_run']), 'accepted', ['Checked scope'])
                self.assertEqual(before, path.read_bytes())

    def test_snapshot_and_executable_are_rechecked_after_busy_backoff(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from scripts import council as cli
        from runtime.startup import StartupError
        for index, change in enumerate(('snapshot', 'executable')):
            self.request['run_id'] = 'backoff-recheck-' + str(index)
            self.prepare(); packet = council.packet(self.run, 'investigate', 'external-one')
            guard = council.external_launch_guard
            calls = []
            def busy_then_guard(run, phase):
                calls.append(True)
                if len(calls) == 1: raise StartupError('Onboarding plan busy; retry the same expected revision')
                return guard(run, phase)
            def changed(_):
                if change == 'executable': self.executable.write_text('#!/bin/sh\nexit 1\n')
                else:
                    path = self.run / 'snapshot/evidence.txt'; path.chmod(0o600); path.write_text('changed'); path.chmod(0o400)
            with patch.object(council, 'external_launch_guard', side_effect=busy_then_guard), patch.object(council.workers.time, 'sleep', side_effect=changed), patch.object(council.workers.subprocess, 'Popen', wraps=council.workers.subprocess.Popen) as spawn, redirect_stdout(StringIO()):
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
        self.request.update(question='q' * 8000, constraints='c' * 7559)
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
            checks=['Native dispatch tool refused before creating a child; observed no admitted process.'],
            report='Native dispatch unavailable.', failure=dict(category='integration', launch_stage='before_spawn'))
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
            report='Rejected answer from reused child must not become deliberation evidence.', failure=dict(category='integration'))
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
        self.assertIn('no report included', observations)
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
        self.assertIn('report lacks technical and scope checks', observations)
        self.assertIn('Participant 3: late', observations)
        self.assertIn('late/unreviewed evidence', observations)
        self.assertNotIn('initial-2.md', packet['reports'])
        self.assertNotIn('initial-3.md', packet['reports'])

    def grouped_request(self, group='Balanced', native_slot='member-three'):
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
        if packet['kind'] == 'native':
            council.record_native(self.run, phase, member, self.native_receipt(packet,
                f'{phase} evidence by anonymous participant' if disposition == 'accepted' else '', accepted=disposition == 'accepted', child_id=session))
            return packet
        path = Path(packet['worker_run']) / 'result.json'
        result = dict(state='awaiting_verification', response=f'{phase} evidence by anonymous participant',
            session_id=session if session is not None else phase + '-' + member,
            local_execution_stopped=True, reported_cost_usd=0, known_cost_subtotal_usd=0,
            accounting_complete=True, upstream_cancellation_confirmed=False)
        council.workers.save(path, result)
        if verify:
            council.verify_external(self.run, phase, member, disposition, ['Host checked completion, scope and freshness.'],
                                    failure=dict(category='runtime') if disposition == 'rejected' else None)
        return packet

    def grouped_rounds(self, rejected=()):
        for phase in ('investigate', 'critique'):
            for member in self.request['roster']:
                self.grouped_external(phase, member, disposition='rejected' if member in rejected else 'accepted')

    def test_grouped_balanced_seven_fresh_results_complete_and_accounted(self):
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
            self.grouped_request(group, native_slot='member-two'); self.prepare()
            packet = council.packet(self.run, 'investigate', 'member-two')
            self.assertEqual(packet['kind'], 'native')
            self.assertEqual(packet['model'], 'native-' + group.lower())
            receipt = dict(issued_id=packet['issued_id'], child_id='child-' + group,
                supervisor_id='coordinator', observed_model=packet['model'], observed_effort='max',
                fork_turns='none', local_execution_stopped=True, accepted=True,
                checks=['Host verified'], report='Native finding')
            council.record_native(self.run, 'investigate', 'member-two', receipt)
            self.assertEqual(council.status(self.run)['accepted_participation']['investigate']['accepted'], 1)

    def test_grouped_roster_rejects_wrong_topology_free_group_and_duplicate_identity(self):
        base = copy.deepcopy(self.grouped_request())
        cases = []
        def changed(change):
            request = copy.deepcopy(base); change(request); cases.append(request)
        changed(lambda r: r.update(group='Unknown'))
        changed(lambda r: r.update(chair='native'))
        changed(lambda r: r['roster'].pop('member-three'))
        changed(lambda r: r['roster']['member-two'].update(kind='native'))
        changed(lambda r: r['roster']['member-two']['pricing'].update(completion_usd_per_million=True))
        changed(lambda r: r['roster']['member-two'].update(canonical_model='vendor/model-1'))
        changed(lambda r: r['roster']['member-two'].update(model='vendor/paid'))
        changed(lambda r: r['roster']['member-two'].update(unavailable_reason='No route'))
        changed(lambda r: r.update(group='Free'))
        changed(lambda r: r['roster']['member-two'].pop('pricing'))
        for request in cases:
            with self.subTest(request=request), self.assertRaises(ValueError): council.prepare(self.repo, request)
        self.assertFalse((self.root / 'council-round-one').exists())

    def test_grouped_nonchair_synthesis_and_native_receipt_for_external_are_blocked(self):
        self.grouped_request(); self.prepare(); self.grouped_rounds()
        for member in ('native', 'member-one', 'member-two'):
            with self.assertRaisesRegex(ValueError, 'invalid_council_member'):
                council.packet(self.run, 'synthesis', member)
        with self.assertRaises(ValueError): council.record_native(self.run, 'synthesis', self.request['chair'], {})

    def test_grouped_reduced_coverage_counts_same_members(self):
        self.grouped_request(); self.prepare(); self.grouped_rounds(rejected=('member-three',))
        self.grouped_external('synthesis', self.request['chair'])
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
        missing = duplicate
        result.update(state='awaiting_verification', session_id='')
        council.workers.save(path, result)
        with self.assertRaisesRegex(ValueError, 'fresh_external_session_required'):
            council.verify_external(self.run, 'investigate', 'member-two', 'accepted', ['Host verified'])
        council.verify_external(self.run, 'investigate', 'member-two', 'rejected', ['No session observed'], failure=dict(category='integration'))
        manifest = json.loads((self.run / 'manifest.json').read_text())
        self.assertNotIn('session_ids', manifest['members']['investigate:member-two'])
        with self.assertRaisesRegex(ValueError, 'grouped_council_verification_required'):
            council.workers.verify(Path(missing['worker_run']), 'accepted', ['Manual bypass'])
        path = Path(packet['worker_run']) / 'result.json'
        result = json.loads(path.read_text()); result['response'] = 'Changed verified bytes'
        council.workers.save(path, result)
        self.assertEqual(council.status(self.run)['accepted_participation']['investigate']['accepted'], 0)

    def test_grouped_critique_session_freshness_and_terminal_stop_owner(self):
        self.grouped_request(); self.prepare()
        for member in self.request['roster']: self.grouped_external('investigate', member)
        packet = self.grouped_external('critique', 'member-one', session='investigate-member-one', verify=False)
        with self.assertRaisesRegex(ValueError, 'fresh_external_session_required'):
            council.verify_external(self.run, 'critique', 'member-one', 'accepted', ['Host verified'])
        path = Path(packet['worker_run']) / 'result.json'
        result = json.loads(path.read_text()); result.update(state='unresolved', session_id=None,
            local_execution_stopped=False, reported_cost_usd=None, known_cost_subtotal_usd=.05,
            accounting_complete=False, failure=dict(category='runtime', launch_stage='spawn'))
        council.workers.save(path, result)
        report = council.cancel(self.run)
        self.assertFalse(report['fresh_synthesis_available'])
        self.assertIsNone(report['external_total_usd'])
        self.assertEqual(report['known_external_subtotal_usd'], .05)
        self.assertEqual(report['stop_requests'], [dict(phase='critique', member='member-one', worker_run=packet['worker_run'])])
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

    def test_grouped_critique_frozen_changes_and_lost_original_response(self):
        self.grouped_request(); self.prepare()
        for member in self.request['roster']: self.grouped_external('investigate', member)
        original = council.workers.prepare_council
        def lost(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError('lost packet response')
        with patch.object(council.workers, 'prepare_council', side_effect=lost), self.assertRaises(OSError):
            council.packet(self.run, 'critique', 'member-one')
        status = council.status(self.run)
        self.assertFalse(status['all_local_execution_stopped'])
        self.assertEqual(status['stop_requests'][0]['member'], 'member-one')
        with self.assertRaises(FileExistsError): council.packet(self.run, 'critique', 'member-one')
        path = self.run / 'initial-1.md'; path.write_text('tampered'); path.chmod(0o600)
        with self.assertRaisesRegex(ValueError, 'frozen_evidence_changed'): council.status(self.run)

    def test_grouped_headroom_and_external_phase_objective_preflight(self):
        self.grouped_request()
        manifest = dict(files={str(i): dict(size=1) for i in range(council.snapshot.MAX_PATHS - 7)})
        with self.assertRaisesRegex(ValueError, 'headroom'):
            council._phase_headroom(manifest, self.request['roster'], grouped=True)
        self.request['question'] = 'q' * 7800
        self.request['constraints'] = 'c' * 7650
        # The longest phase must be validated too, before the first dispatch.
        with patch.object(council.workers, '_validate_council_brief', wraps=council.workers._validate_council_brief) as validate:
            self.prepare()
        self.assertEqual({call.args[0]['council']['phase'] for call in validate.call_args_list}, {'investigate', 'critique'})

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
        for seat in self.request['roster'].values():
            if seat['kind'] == 'external': seat['permission_qualification']['opencode_sha256'] = digest
        self.prepare(); sessions = []
        for phase in council.PHASES:
            members = list(self.request['roster']) if phase != 'synthesis' else [self.request['chair']]
            for member in members:
                packet = council.packet(self.run, phase, member)
                if packet['kind'] == 'native':
                    receipt = self.native_receipt(packet, phase + ' native evidence')
                    council.record_native(self.run, phase, member, receipt)
                    sessions.append(receipt['child_id'])
                    continue
                with redirect_stdout(StringIO()): result = cli._execute(self.run, phase, packet, self.settings)
                self.assertEqual(result['state'], 'awaiting_verification')
                sessions.append(result['session_id'])
                request = dict(run=str(self.run), phase=phase, member=member, disposition='accepted', checks=['Host source and scope verified'])
                with patch('sys.argv', ['council', 'verify-external', '--cwd', str(self.repo)]), patch('sys.stdin', TextIOWrapper(BytesIO(json.dumps(request).encode()))), redirect_stdout(StringIO()):
                    self.assertEqual(cli.main(), 0)
        self.assertEqual(len(set(sessions)), 7)
        self.assertEqual(council.status(self.run)['outcome'], 'complete')

    def test_grouped_failed_native_chair_keeps_outcome_partial(self):
        self.grouped_request(); self.prepare(); self.grouped_rounds()
        packet = council.packet(self.run, 'synthesis', self.request['chair'])
        council.record_native(self.run, 'synthesis', self.request['chair'],
            self.native_receipt(packet, '', accepted=False))
        report = council.status(self.run)
        self.assertFalse(report['fresh_synthesis_available'])
        self.assertTrue(report['all_local_execution_stopped'])
        self.assertEqual(report['external_total_usd'], 0)

    def test_grouped_external_critique_resume_retains_deadline_and_original_consent(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from scripts import council as cli
        self.grouped_request(); self.prepare()
        for member in self.request['roster']: self.grouped_external('investigate', member)
        packet = council.packet(self.run, 'critique', 'member-one')
        with patch.object(council.workers.settings, 'admission', side_effect=openrouter_settings.SettingsError('openrouter_operation_busy')), patch.object(council.workers.time, 'sleep'), redirect_stdout(StringIO()):
            result = cli._execute(self.run, 'critique', packet, self.settings)
        resumed = council.resume_member(self.run, 'critique', 'member-one')
        self.assertEqual(resumed['worker_run'], packet['worker_run'])
        self.assertEqual(resumed['deadline_monotonic'], result['deadline_monotonic'])
        disabled = openrouter_settings.disable(self.repo, {'expected_revision': self.settings['revision']})
        openrouter_settings.enable(self.repo, {'expected_revision': disabled['revision']})
        with self.assertRaisesRegex(openrouter_settings.SettingsError, 'openrouter_preparation_stale'):
            council.resume_member(self.run, 'critique', 'member-one')
        council.cancel(self.run)
        with self.assertRaisesRegex(ValueError, 'cancelled'):
            council.resume_member(self.run, 'critique', 'member-one')

    def test_grouped_critique_unknown_session_rejects_but_can_settle_after_cancel(self):
        self.grouped_request(); self.prepare()
        for member in self.request['roster']: self.grouped_external('investigate', member)
        packet = self.grouped_external('critique', 'member-one', session='', verify=False)
        with self.assertRaisesRegex(ValueError, 'fresh_external_session_required'):
            council.verify_external(self.run, 'critique', 'member-one', 'accepted', ['Host checked'])
        council.cancel(self.run)
        council.verify_external(self.run, 'critique', 'member-one', 'rejected', ['Unknown session, stopped original owner'], failure=dict(category='integration'))
        self.assertTrue(council.status(self.run)['all_local_execution_stopped'])
        self.assertFalse(council.status(self.run)['fresh_synthesis_available'])

    def test_grouped_partial_coverage_and_pinned_brief_identity_on_launch(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from scripts import council as cli
        self.grouped_request(); self.prepare()
        for member in self.request['roster']: self.grouped_external('investigate', member, disposition='accepted' if member == 'member-one' else 'rejected')
        packet = council.packet(self.run, 'critique', 'member-one')
        path = Path(packet['worker_run']) / 'brief.json'
        brief = json.loads(path.read_text()); brief['canonical_model'] = 'vendor/changed-identity'
        council.workers.save(path, brief)
        with patch.object(council.workers.subprocess, 'Popen', wraps=council.workers.subprocess.Popen) as spawn, redirect_stdout(StringIO()):
            result = cli._execute(self.run, 'critique', packet, self.settings)
        self.assertEqual([call for call in spawn.call_args_list if call.args[0][0] == str(self.executable)], [])
        self.assertTrue(result['local_execution_stopped'])
        self.assertEqual(council.status(self.run)['outcome'], 'partial')

    def test_grouped_paid_full_native_chair_and_wrong_chair(self):
        self.grouped_request('Balanced', native_slot='member-two')
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
            council.packet(self.run, 'synthesis', self.request['chair'])
        packet = council.packet(self.run, 'synthesis', self.request['chair'])
        self.assertIn('critique evidence', (Path(packet['snapshot']) / '__council__/critique-1.md').read_text())
        self.assertEqual(json.loads((self.run / 'manifest.json').read_text())['phase'], 'synthesis')

    def test_grouped_all_six_phase_stop_owners_and_ambiguous_spawn_are_retained(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from scripts import council as cli
        self.grouped_request(); self.prepare()
        for member in self.request['roster']: self.grouped_external('investigate', member)
        for member in ('member-two', 'member-three'): self.grouped_external('critique', member)
        packet = council.packet(self.run, 'critique', 'member-one')
        original = council.workers.subprocess.Popen
        def ambiguous(command, *args, **kwargs):
            if command[0] == str(self.executable): raise OSError('ambiguous spawn')
            return original(command, *args, **kwargs)
        with patch.object(council.workers.subprocess, 'Popen', side_effect=ambiguous), redirect_stdout(StringIO()):
            result = cli._execute(self.run, 'critique', packet, self.settings)
        self.assertFalse(result['local_execution_stopped'])
        self.assertEqual(result['failure']['launch_stage'], 'spawn')
        self.assertEqual(council.status(self.run)['stop_requests'], [dict(phase='critique', member='member-one', worker_run=packet['worker_run'])])
        for path in self.root.glob('round-one-*/result.json'):
            result = json.loads(path.read_text()); result['local_execution_stopped'] = False
            council.workers.save(path, result)
        with council._locked(self.run) as value:
            for item in value['members'].values():
                if item['kind'] == 'native': item['receipt']['local_execution_stopped'] = False
            council._save(self.run, value)
        owners = council.cancel(self.run)['stop_requests']
        self.assertEqual(len(owners), 6)
        with self.assertRaisesRegex(ValueError, 'not_resumable|cancelled'):
            council.resume_member(self.run, 'critique', 'member-one')

    def test_grouped_expired_synthesis_cannot_be_accepted_or_refreshed(self):
        self.grouped_request(); self.prepare(); self.grouped_rounds()
        packet = council.packet(self.run, 'synthesis', self.request['chair'])
        with patch.object(council, '_elapsed', return_value=1201):
            council.record_native(self.run, 'synthesis', self.request['chair'], self.native_receipt(packet))
        self.assertFalse(council.status(self.run)['fresh_synthesis_available'])
        self.assertTrue(council.status(self.run)['all_local_execution_stopped'])

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


    def test_grouped_free_documented_default_decodes_but_cannot_start(self):
        self.grouped_request('Free')
        seat = self.request['roster']['member-one']
        seat['effort'] = 'default'
        seat['capabilities'].update(reasoning={'default_enabled': True},
            source='Exact route documentation: reasoning enabled by default; maximum mapping unverified')
        council.workers._council_contract(dict(seat, council=dict(run_id='round-one', phase='investigate',
            member_id='member-one', group='Free', chair='member-one')))
        with self.assertRaisesRegex(ValueError, 'free_council_temporarily_disabled'):
            self.prepare()
        self.assertFalse((self.root / 'council-round-one').exists())

    def test_grouped_retained_sessions_block_reuse_after_closed_results_change_or_disappear(self):
        base = copy.deepcopy(self.grouped_request())
        for state in ('accepted', 'rejected', 'failed'):
            for change in ('mutated', 'deleted'):
                with self.subTest(state=state, change=change):
                    self.request = copy.deepcopy(base)
                    self.request['run_id'] = 'retained-' + state + '-' + change
                    self.prepare()
                    prior = self.grouped_external('investigate', 'member-one',
                        disposition=state if state != 'failed' else 'accepted', verify=state != 'failed')
                    path = Path(prior['worker_run']) / 'result.json'
                    if state == 'failed':
                        result = json.loads(path.read_text())
                        result.update(state='failed', reported_cost_usd=None,
                            known_cost_subtotal_usd=.03, accounting_complete=False)
                        council.workers.save(path, result)
                    self.grouped_external('investigate', 'member-two')
                    self.grouped_external('investigate', 'member-three')
                    council.packet(self.run, 'critique', 'member-three')  # Close and retain original observations.
                    original_session = 'investigate-member-one'
                    if change == 'deleted': path.unlink()
                    else:
                        result = json.loads(path.read_text()); result['session_id'] = 'changed-prior-session'
                        council.workers.save(path, result)
                    later = self.grouped_external('critique', 'member-one', session=original_session, verify=False)
                    with self.assertRaisesRegex(ValueError, 'fresh_external_session_required'):
                        council.verify_external(self.run, 'critique', 'member-one', 'accepted', ['Host verified'])
                    manifest = json.loads((self.run / 'manifest.json').read_text())
                    self.assertIn(original_session, manifest['members']['investigate:member-one']['session_ids'])
                    # Rejection still settles the original current owner without inventing a session.
                    result = council.verify_external(self.run, 'critique', 'member-one', 'rejected', ['Reused session rejected'], failure=dict(category='integration'))
                    self.assertEqual(result['session_id'], original_session)
                    self.assertTrue(result['local_execution_stopped'])
                    self.assertEqual(result['reported_cost_usd'], 0)

    def test_grouped_phase_closure_keeps_verification_session_and_new_current_observation(self):
        self.grouped_request(); self.prepare()
        prior = self.grouped_external('investigate', 'member-one')
        path = Path(prior['worker_run']) / 'result.json'
        result = json.loads(path.read_text()); result.update(state='failed', session_id='second-observed-session')
        council.workers.save(path, result)
        self.grouped_external('investigate', 'member-two'); self.grouped_external('investigate', 'member-three')
        council.packet(self.run, 'critique', 'member-three')
        path.unlink()
        manifest = json.loads((self.run / 'manifest.json').read_text())
        self.assertEqual(manifest['members']['investigate:member-one']['session_ids'],
                         ['investigate-member-one', 'second-observed-session'])
        for session in ('investigate-member-one', 'second-observed-session'):
            packet = self.grouped_external('critique', 'member-one' if session.startswith('investigate') else 'member-two',
                session=session, verify=False)
            member = 'member-one' if session.startswith('investigate') else 'member-two'
            with self.assertRaisesRegex(ValueError, 'fresh_external_session_required'):
                council.verify_external(self.run, 'critique', member, 'accepted', ['Host verified'])


    def test_grouped_held_council_lock_is_bounded_not_launched_and_cancel_settles_prepared(self):
        from contextlib import redirect_stdout
        from io import StringIO
        self.grouped_request(); self.prepare()
        packet = council.packet(self.run, 'investigate', 'member-one')
        with council._locked(self.run), patch.object(council.workers.time, 'sleep'), redirect_stdout(StringIO()):
            result = council.workers.execute(Path(packet['worker_run']), self.executable, self.auth)
        self.assertEqual(result['state'], 'not_launched')
        self.assertEqual(result['failure']['reason'], 'Onboarding plan busy; retry the same expected revision')
        self.assertTrue(result['local_execution_stopped'])
        self.assertTrue(council.workers.resumable(result))
        self.assertIsNone(result['session_id'])
        original_deadline = result['deadline_monotonic']
        unstarted = council.packet(self.run, 'investigate', 'member-two')
        council.cancel(self.run)
        with redirect_stdout(StringIO()):
            settled = council.workers.execute(Path(packet['worker_run']), self.executable, self.auth)
        self.assertEqual(settled['failure']['reason'], 'cancelled')
        self.assertTrue(settled['local_execution_stopped'])
        self.assertEqual(settled['deadline_monotonic'], original_deadline)
        self.assertIsNone(settled['session_id'])
        with redirect_stdout(StringIO()), patch.object(council.workers.subprocess, 'Popen', wraps=council.workers.subprocess.Popen) as spawn:
            prepared = council.workers.execute(Path(unstarted['worker_run']), self.executable, self.auth)
        self.assertTrue(prepared['local_execution_stopped'])
        self.assertEqual(prepared['failure']['reason'], 'cancelled')
        self.assertIsNone(prepared['session_id'])
        self.assertEqual([call for call in spawn.call_args_list if call.args[0][0] == str(self.executable)], [])

    def test_grouped_external_processes_share_guard_contention_without_duplicate_launch(self):
        import multiprocessing
        from contextlib import contextmanager, redirect_stdout
        from runtime.startup import StartupError
        from io import StringIO
        self.executable.write_text('#!/usr/bin/env python3\nimport json, sys\nfrom pathlib import Path\n'
            + f'with Path({str(self.temporary / "spawns")!r}).open("a") as stream: stream.write(sys.argv[sys.argv.index("--title") + 1] + "\\n")\n'
            + 'session = sys.argv[sys.argv.index("--title") + 1]\n'
            + 'print(json.dumps({"type":"text","sessionID":session,"part":{"text":"Synthetic local evidence"}}))\n'
            + 'print(json.dumps({"type":"step_finish","sessionID":session,"part":{"reason":"stop","cost":0,"tokens":{}}}))\n')
        self.grouped_request()
        digest = hashlib.sha256(self.executable.read_bytes()).hexdigest()
        for seat in self.request['roster'].values():
            if seat['kind'] == 'external': seat['permission_qualification']['opencode_sha256'] = digest
        self.prepare()
        self.grouped_external('investigate', 'member-three')
        packets = [council.packet(self.run, 'investigate', member) for member in ('member-one', 'member-two')]
        context = multiprocessing.get_context('fork')
        output = context.Queue()
        start = context.Event()
        contention = context.Event()
        def execute(packet):
            try:
                if not start.wait(timeout=5): raise TimeoutError('fixture start gate')
                original = council.external_launch_guard
                @contextmanager
                def observed_guard(*args, **kwargs):
                    try:
                        with original(*args, **kwargs) as ceiling: yield ceiling
                    except StartupError as error:
                        if str(error) == 'Onboarding plan busy; retry the same expected revision': contention.set()
                        raise
                with redirect_stdout(StringIO()), patch.object(council, 'external_launch_guard', side_effect=observed_guard):
                    result = council.workers.execute(Path(packet['worker_run']), self.executable, self.auth,
                        deadline_monotonic=packet['deadline_monotonic'])
                output.put(dict(member=packet['member'], result=result))
            except Exception as error:
                output.put(dict(member=packet['member'], error=type(error).__name__ + ': ' + str(error)))
        processes = [context.Process(target=execute, args=(packet,)) for packet in packets]
        self.addCleanup(lambda: [process.kill() for process in processes if process.is_alive()])
        for process in processes: process.start()
        with council._locked(self.run):
            start.set()
            until = time.monotonic() + 2
            while time.monotonic() < until:
                if contention.is_set() and all(json.loads((Path(packet['worker_run']) / 'result.json').read_text())['state'] == 'running' for packet in packets): break
                if all(not process.is_alive() for process in processes): break
                time.sleep(.02)
        self.assertTrue(contention.is_set(), 'fixture must observe an actual Council lock collision')
        results = [output.get(timeout=12) for _ in processes]
        for process in processes: process.join(timeout=2)
        self.assertFalse([item for item in results if 'error' in item], results)
        for item in results:
            if item['result']['state'] == 'not_launched':
                self.assertTrue(council.workers.resumable(item['result']))
                original_deadline = item['result']['deadline_monotonic']
                packet = next(packet for packet in packets if packet['member'] == item['member'])
                with redirect_stdout(StringIO()):
                    item['result'] = council.workers.execute(Path(packet['worker_run']), self.executable, self.auth)
                self.assertEqual(item['result']['deadline_monotonic'], original_deadline)
        self.assertTrue(all(item['result']['state'] == 'awaiting_verification' for item in results), results)
        launched = (self.temporary / 'spawns').read_text().splitlines()
        self.assertEqual(sorted(launched), sorted(Path(packet['worker_run']).name for packet in packets))
        for item in results:
            packet = next(packet for packet in packets if packet['member'] == item['member'])
            self.assertLessEqual(item['result']['deadline_monotonic'], packet['deadline_monotonic'])
            self.assertTrue(item['result']['local_execution_stopped'])
        self.assertEqual(len(set(item['result']['session_id'] for item in results)), 2)

    def test_external_council_phase_guidance_reaches_execution_with_existing_bounds(self):
        from contextlib import redirect_stdout
        from io import StringIO
        script = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
config = json.loads(os.environ['OPENCODE_CONFIG_CONTENT'])
prompt = config['agent']['pilot']['prompt']
objective = sys.stdin.read()
title = sys.argv[sys.argv.index('--title') + 1]
phase = next(phase for phase in ('investigate', 'critique', 'synthesis') if '-' + phase + '-' in title)
assert 'copied workspace' in prompt
assert all(word in prompt for word in ('.council-snapshot.json', 'internal', 'denied', 'unnecessary', 'glob'))
assert len(prompt) <= 1500
paths = {'investigate': (), 'critique': ('__council__/initial-*.md', '__council__/research.md'),
    'synthesis': ('__council__/initial-*.md', '__council__/critique-*.md', '__council__/research.md', '__council__/execution-observations.md')}
for path in paths[phase]:
    assert path in prompt
    assert list(Path('.').glob(path))
if phase == 'investigate': assert '__council__/' not in prompt
read = config['permission']['read']
assert read['*'] == 'deny' and '.council-snapshot.json' not in read
assert config['permission']['*'] == 'deny'
assert config['permission']['glob'] == config['permission']['grep'] == 'allow'
assert config['agent']['pilot']['steps'] == 12
model = next(iter(config['provider']['openrouter']['models'].values()))
assert model['options']['maxOutputTokens'] == 8000
assert model['options']['provider']['allow_fallbacks'] is False
assert 0 < len(objective) <= 16000 and 'Read only; explain uncertainty.' in objective
assert 'copied workspace' not in objective
print(json.dumps({'type': 'text', 'sessionID': title, 'part': {'text': 'Synthetic phase guidance and boundaries verified.'}}))
print(json.dumps({'type': 'step_finish', 'sessionID': title, 'part': {'reason': 'stop', 'cost': 0, 'tokens': {}}}))
'''
        self.executable.write_text(script)
        self.grouped_request()
        digest = hashlib.sha256(self.executable.read_bytes()).hexdigest()
        for seat in self.request['roster'].values():
            if seat['kind'] == 'external': seat['permission_qualification']['opencode_sha256'] = digest
        self.prepare()
        for phase in council.PHASES[:2]:
            packet = council.packet(self.run, phase, 'member-one')
            with redirect_stdout(StringIO()):
                result = council.workers.execute(Path(packet['worker_run']), self.executable, self.auth,
                    deadline_monotonic=packet['deadline_monotonic'])
            self.assertEqual(result['state'], 'awaiting_verification', (phase, result))
            self.assertLessEqual(result['deadline_monotonic'], packet['deadline_monotonic'])
            council.verify_external(self.run, phase, 'member-one', 'accepted', ['Synthetic prompt/permission checks passed'])
            if phase != 'synthesis':
                for member in ('member-two', 'member-three'): self.grouped_external(phase, member)
        self.grouped_external('synthesis', self.request['chair'])
        self.assertEqual(council.status(self.run)['outcome'], 'complete')
