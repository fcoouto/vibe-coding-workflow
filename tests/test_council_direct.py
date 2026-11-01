"""Tool-free Council transport against isolated endpoints and disposable consent."""
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time
from unittest.mock import patch

from runtime import council, openrouter_settings
from scripts import openrouter_workers as workers
from tests.council_fixtures import CouncilCase

try:
    from scripts import council_direct as direct
except ImportError:
    direct = None


class DirectTests(CouncilCase):
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(direct, 'direct tool-free requester must exist')
        self.calls = []
        self.reply = dict(id='gen-fixture', model='vendor/text', choices=[dict(
            finish_reason='stop', message=dict(content='A supported conclusion.'))],
            usage=dict(prompt_tokens=20, completion_tokens=8, total_tokens=28, cost=.01))
        self.http_status, self.delay, self.redirect = 200, 0, None
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_POST(self):
                raw = self.rfile.read(int(self.headers['Content-Length']))
                owner.calls.append((self.path, dict(self.headers), json.loads(raw)))
                time.sleep(owner.delay)
                self.send_response(owner.http_status)
                if owner.redirect: self.send_header('Location', owner.redirect)
                self.end_headers()
                try: self.wfile.write(json.dumps(owner.reply).encode())
                except (BrokenPipeError, ConnectionResetError): pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.endpoint = 'http://127.0.0.1:' + str(self.server.server_port) + '/chat'
        (self.auth / 'opencode').mkdir(mode=0o700)
        self.auth_file = self.auth / 'opencode/auth.json'
        self.auth_file.write_text(json.dumps({'openrouter': {'type': 'api', 'key': 'fixture-private-key'}}))
        self.auth_file.chmod(0o600)
        self.payload = dict(model='vendor/text', messages=[dict(role='user', content='Approved question')],
            provider=dict(only=['fixture'], allow_fallbacks=False, require_parameters=True),
            reasoning=dict(effort='max'), max_tokens=4096, stream=False)
        self.request = dict(mode='text', group='Balanced', chair='member-one', run_id='text-round',
            question='Approved question', constraints='Approved constraints',
            coordinator_chat_id='00000000-0000-4000-8000-000000000001', approval_ref='approved',
            approved_files={}, research='Approved shared research',
            phase_seconds=dict(investigate=600, critique=360, synthesis=240),
            roster={'member-one': self.native_seat(), 'member-two': self.seat('vendor/text'),
                    'member-three': self.seat('vendor/other')})
        self.wrapper = self.temporary / 'direct-fixture.py'
        self.wrapper.write_text('import sys\nsys.path.insert(0, %r)\nfrom scripts import council_direct\n'
            'council_direct.ENDPOINT = %r\nsys.exit(council_direct.main())\n' % (str(workers.PACKAGE), self.endpoint))

    def seat(self, model):
        return dict(kind='external', model=model, canonical_model=model, model_display_name='Fixture',
            provider='fixture', effort='max', input_tokens=10000, output_tokens=4096, steps=1,
            capabilities=dict(model=model, provider='fixture', context_length=20000,
                max_output_tokens=8000, tools=False, api='chat-completions', reasoning=dict(efforts=['high', 'max']),
                observed_at='fixture-date', source='native:capability-observation'),
            permission_qualification=dict(profile='council-text-v1', evidence='native:controlled-probe'),
            selection='native:selection', pricing=dict(prompt_usd_per_million=1,
                completion_usd_per_million=2, source='native:pricing', observed_at='fixture-date'))

    def send(self, payload=None):
        with patch.object(direct, 'ENDPOINT', self.endpoint):
            return direct.send(payload or self.payload, self.auth, 2)

    def prepare(self):
        self.run = Path(council.prepare(self.repo, self.request)['run'])
        packet = council.packet(self.run, 'investigate', 'member-two')
        return Path(packet['worker_run'])

    def execute(self, run, *, interrupt=False, timeout=None):
        spawn = workers.subprocess.Popen
        self.processes, self.commands = [], []
        def local(command, **kwargs):
            self.commands.append(command)
            if len(command) > 1 and str(command[1]).endswith('council_direct.py'):
                command = [command[0], str(self.wrapper), *command[2:]]
                process = spawn(command, **kwargs)
                self.processes.append(process)
                if interrupt: raise_after_start.append(process)
                return process
            return spawn(command, **kwargs)
        raise_after_start = []
        real_select = workers.selectors.DefaultSelector.select
        def select(selector, *args):
            if raise_after_start:
                raise_after_start.clear()
                council.cancel(self.run)
                os.kill(os.getpid(), signal.SIGTERM)
            return real_select(selector, *args)
        with patch.object(workers.subprocess, 'Popen', side_effect=local), patch.object(
                workers.selectors.DefaultSelector, 'select', select):
            return workers.execute(run, self.executable, self.auth,
                deadline_monotonic=time.monotonic() + timeout if timeout else None)

    def test_text_wire_has_only_approved_material_and_no_tools(self):
        (self.repo / 'approved.txt').write_text('Exact approved evidence')
        (self.repo / 'unapproved.txt').write_text('UNAPPROVED SOURCE')
        self.request['approved_files'] = self.approved(['approved.txt'])
        result = self.execute(self.prepare())
        self.assertEqual(result['state'], 'awaiting_verification')
        payload = self.calls[0][2]
        wire = json.dumps(payload)
        for approved in ('Approved question', 'Approved constraints', 'Approved shared research', 'Exact approved evidence'):
            self.assertIn(approved, wire)
        for denied in ('tools', 'previous_response_id', 'UNAPPROVED SOURCE', str(self.auth), str(self.repo), str(self.root)):
            self.assertNotIn(denied, wire)
        self.assertFalse(any(command[0] == str(self.executable) for command in self.commands))
        saved = (Path(self.run) / 'manifest.json').read_text() + (Path(result['task_id']).name)
        worker = self.root / result['task_id']
        saved += (worker / 'result.json').read_text() + (worker / 'progress.jsonl').read_text()
        self.assertNotIn('fixture-private-key', saved)
        self.assertNotIn('UNAPPROVED SOURCE', saved)
        output = (worker / 'result.json').read_text() + (worker / 'progress.jsonl').read_text()
        for private in (str(self.auth), str(self.repo), str(self.root)):
            self.assertNotIn(private, output)

    def test_fixed_provider_max_reasoning_and_no_fallback(self):
        result = self.send()
        self.assertIsNone(result['failure'])
        payload = self.calls[0][2]
        self.assertEqual(payload, self.payload)
        for change in ({'tools': []}, {'stream': True}, {'provider': {'only': ['fixture'], 'allow_fallbacks': True}},
                       {'endpoint': self.endpoint}, {'previous_response_id': 'old'},
                       {'messages': [dict(role='user', content='Prior conversation'), *self.payload['messages']]}):
            with self.subTest(change=change):
                result = self.send(dict(self.payload, **change))
                self.assertIsNotNone(result['failure'])
                self.assertEqual(result['failure']['category'], 'invalid_request')
        self.assertEqual(len(self.calls), 1)

    def test_output_ceiling_is_optional_but_explicit_values_are_validated(self):
        payload = dict(self.payload)
        payload.pop('max_tokens')
        self.assertIsNone(self.send(payload)['failure'])
        self.assertNotIn('max_tokens', self.calls[0][2])
        self.assertEqual(self.calls[0][2]['reasoning'], {'effort': 'max'})
        for value in (None, True, 0, 1.5, '8192'):
            with self.subTest(value=value):
                with patch.object(direct.onboarding, '_read_file', side_effect=AssertionError('must not read auth')):
                    result = self.send(dict(payload, max_tokens=value))
                self.assertEqual(result['failure']['category'], 'invalid_request')
        self.assertEqual(len(self.calls), 1)

    def test_free_routes_block_direct_send_and_main_before_auth_or_network(self):
        import subprocess
        for model in ('vendor/model:free', 'openrouter/free'):
            payload = dict(self.payload, model=model)
            with patch.object(direct.onboarding, '_read_file', side_effect=AssertionError('must not read auth')):
                result = self.send(payload)
            self.assertEqual(result['failure']['category'], 'invalid_request')
            process = subprocess.run([sys.executable, str(Path(direct.__file__)),
                '--auth-data', str(self.temporary / 'missing-auth'), '--timeout', '1'],
                input=json.dumps(payload), text=True, capture_output=True, timeout=3)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout)['failure']['category'], 'invalid_request')
        self.assertEqual(self.calls, [])

    def test_private_auth_only_and_redirect_rejected(self):
        with patch.dict(os.environ, OPENROUTER_API_KEY='override-never-used'):
            self.send()
        self.assertEqual(self.calls[0][1]['Authorization'], 'Bearer fixture-private-key')
        self.http_status, self.redirect = 307, self.endpoint + '/other'
        self.assertIsNotNone(self.send()['failure'])
        self.assertEqual(len(self.calls), 2)

        self.http_status, self.redirect = 200, None
        for record in ({}, {'openrouter': {'type': 'oauth', 'access': 'SECRET'}}, {'other': {'type': 'api', 'key': 'SECRET'}}):
            self.auth_file.write_text(json.dumps(record))
            self.assertEqual(self.send()['failure']['category'], 'authentication')
        self.auth_file.chmod(0o644)
        self.assertEqual(self.send()['failure']['category'], 'authentication')
        self.assertEqual(len(self.calls), 2)

    def test_bounded_response_never_becomes_terminal_text(self):
        for size, reason in ((128 * 1024 + 1, 'council_report_limit'), (workers.LIMIT + 1, 'output_limit')):
            self.reply['choices'][0]['message']['content'] = 'x' * size
            result = self.send()
            self.assertEqual(result['response'], '')
            self.assertEqual(result['failure']['reason'], reason)

    def test_terminal_content_and_error_classification(self):
        original = copy.deepcopy(self.reply)
        cases = [(dict(choices=[dict(finish_reason='stop', message=dict(content='', reasoning='SECRET'))]), 'incomplete_output'),
                 (dict(choices=[dict(finish_reason='length', message=dict(content='partial'))]), 'incomplete_output'),
                 (dict(choices=[dict(finish_reason='stop', message=dict(content='partial', tool_calls=[{}]))]), 'runtime_or_output'),
                 (dict(error=dict(code=429, message='SECRET')), 'rate_limit')]
        for update, category in cases:
            self.reply = dict(original, **update)
            result = self.send()
            self.assertEqual(result['failure']['category'], category)
            self.assertEqual(result['response'], update.get('choices', [{}])[0].get('message', {}).get('content', ''))
            self.assertNotIn('SECRET', json.dumps(result))
        for status, category in ((401, 'authentication'), (402, 'budget'), (403, 'permission'),
                                 (429, 'rate_limit'), (500, 'service')):
            self.http_status, self.reply = status, dict(error=dict(code=status, message='SECRET'))
            self.assertEqual(self.send()['failure']['category'], category)
        self.http_status = 200
        self.reply = dict(original, choices=[dict(finish_reason='stop', message=dict(content='I cannot help with that.'))])
        self.reply.pop('usage')
        result = self.send()
        self.assertEqual(result['response'], 'I cannot help with that.')
        self.assertFalse(result['accounting_complete'])
        self.assertIsNone(result['reported_cost_usd'])

    def test_truncated_text_retained_privately_but_never_distributed(self):
        self.request['recovery'] = True
        self.reply['choices'][0] = dict(finish_reason='length', message=dict(
            content='Partial private answer.', reasoning='SECRET reasoning'))
        run = self.prepare()
        result = self.execute(run)
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['failure']['category'], 'incomplete_output')
        self.assertEqual(result['response'], 'Partial private answer.')
        self.assertEqual(result['final_response'], '')
        saved = (run / 'result.json').read_text()
        self.assertNotIn('SECRET', saved)
        with self.assertRaisesRegex(ValueError, 'not_verifiable'):
            council.verify_external(self.run, 'investigate', 'member-two', 'accepted', ['Complete'])
        packet = council.packet(self.run, 'investigate', 'member-one')
        council.record_native(self.run, 'investigate', 'member-one', self.native_receipt(packet, 'Usable answer'))
        packet = council.packet(self.run, 'investigate', 'member-three')
        self.reply['choices'][0] = dict(finish_reason='stop', message=dict(content='Another usable answer'))
        self.execute(Path(packet['worker_run']))
        council.verify_external(self.run, 'investigate', 'member-three', 'accepted', ['Complete and within scope'])
        critique = council.packet(self.run, 'critique', 'member-one')
        self.assertNotIn('__council__/initial-2.md', critique['snapshot_manifest']['files'])
        for name in critique['snapshot_manifest']['files']:
            self.assertNotIn('Partial private answer.', (Path(critique['snapshot']) / name).read_text())

    def test_http_error_machine_diagnostics_are_bounded_and_private(self):
        self.http_status = 403
        self.reply = dict(error=dict(code=403, message='SECRET', metadata=dict(
            limit_source='openrouter_key_limit', raw='SECRET')))
        result = self.send()
        self.assertEqual(result['failure'], dict(category='budget', status_code=403, limit_source='openrouter_key_limit'))
        self.assertNotIn('SECRET', json.dumps(result))
        self.reply = dict(error=dict(code=403, message='SECRET', metadata=dict(error_type='refusal')))
        self.assertEqual(self.send()['failure']['category'], 'policy')

    def test_direct_preparation_identity_cannot_be_rebound_or_reused(self):
        run = self.prepare()
        initial = json.loads((run / 'result.json').read_text())
        initial['attempt_id'] = '00000000-0000-4000-8000-000000000002'
        workers.save(run / 'result.json', initial)
        result = self.execute(run)
        self.assertEqual(self.processes, [])
        self.assertIsNotNone(result['failure'])
        self.assertEqual(self.calls, [])
        self.request['run_id'] = 'fresh-second'
        second = self.prepare()
        good = self.execute(second)
        self.assertNotEqual(good['attempt_id'], initial['attempt_id'])

    def test_prepared_recovery_receipt_is_rebound_after_lost_manifest_save(self):
        self.request['recovery'] = True
        run = self.prepare()
        with council._locked(self.run) as value:
            owner = value['members']['investigate:member-two']
            for key in ('direct_attempt_id', 'direct_request_sha256', 'brief_sha256'): owner.pop(key)
            council._save(self.run, value)
        packet = council.resume_member(self.run, 'investigate', 'member-two')
        self.assertEqual(Path(packet['worker_run']), run)
        result = self.execute(run)
        self.assertEqual(result['state'], 'awaiting_verification')
        council.verify_external(self.run, 'investigate', 'member-two', 'accepted', ['Checked source'])

    def test_busy_direct_admission_resumes_same_attempt_and_original_deadline(self):
        run = self.prepare()
        with patch.object(workers.settings, 'admission', side_effect=openrouter_settings.SettingsError('openrouter_operation_busy')), patch.object(workers.time, 'sleep'):
            before = self.execute(run)
        self.assertEqual(before['state'], 'not_launched')
        self.assertEqual(self.processes, [])
        council.resume_member(self.run, 'investigate', 'member-two')
        after = self.execute(run)
        self.assertEqual(after['state'], 'awaiting_verification')
        self.assertEqual(after['attempt_id'], before['attempt_id'])
        self.assertEqual(after['deadline_monotonic'], before['deadline_monotonic'])

    def test_text_recovery_rejects_opencode_only_request_conversion(self):
        with self.assertRaisesRegex(ValueError, 'unsupported_correction'):
            council.recovery._correction(dict(kind='request_representation', source=0,
                representation='output_limit_only'), self.seat('vendor/text'), [{}])

    def test_text_recovery_and_anonymous_phase_reports_use_direct_receipts(self):
        self.request['recovery'] = True
        run = self.prepare()
        result = self.execute(run)
        self.assertEqual(result['state'], 'awaiting_verification')
        council.verify_external(self.run, 'investigate', 'member-two', 'accepted', ['Checked approved evidence'])
        native = council.packet(self.run, 'investigate', 'member-one')
        council.record_native(self.run, 'investigate', 'member-one', self.native_receipt(native, 'Native anonymous report'))
        third = council.packet(self.run, 'investigate', 'member-three')
        third_run = Path(third['worker_run'])
        self.execute(third_run)
        council.verify_external(self.run, 'investigate', 'member-three', 'accepted', ['Checked evidence'])
        critique = council.packet(self.run, 'critique', 'member-two')
        self.assertEqual(council.status(self.run)['phase'], 'critique')
        self.execute(Path(critique['worker_run']))
        wire = json.dumps(self.calls[-1][2])
        self.assertIn('Native anonymous report', wire)
        self.assertIn('initial-1.md', wire)
        self.assertNotIn('gen-fixture', wire)
        self.assertNotIn('vendor/other', wire)
        self.assertNotIn(str(self.run), wire)

    def test_disputed_claims_reach_critique_and_synthesis_unchanged(self):
        self.request['recovery'] = True
        claims = ['There is no external forcing function.\nDissent: café ≠ certainty.', 'Assume a three-hour drive.',
                  'Relocation is the only reasonable conclusion.']
        self.run = Path(council.prepare(self.repo, self.request)['run'])
        children = []
        for phase, reports in (('investigate', claims), ('critique', [
                'The relocation conclusion is unsupported. Prefer 1, 2, 3.',
                'The assumed drive is mistaken; prefer 3, 1, 2.',
                'I disagree with the forcing-function claim; ranking omitted.'])):
            for index, member in enumerate(council.GROUP_MEMBERS):
                packet = council.packet(self.run, phase, member)
                if phase == 'critique':
                    for number, claim in enumerate(claims, 1):
                        self.assertEqual((Path(packet['snapshot']) / f'__council__/initial-{number}.md').read_text(), claim)
                    self.assertIn('rank', packet['objective'].lower())
                if packet['kind'] == 'native':
                    self.assert_native_prompt(packet)
                    receipt = self.native_receipt(packet, reports[index])
                    children.append(receipt['child_id'])
                    council.record_native(self.run, phase, member, receipt)
                else:
                    self.reply['choices'][0]['message']['content'] = reports[index]
                    self.execute(Path(packet['worker_run']))
                    council.verify_external(self.run, phase, member, 'accepted', ['Complete response within scope'])
        chair = council.packet(self.run, 'synthesis', 'member-one')
        self.assert_native_prompt(chair)
        for number, claim in enumerate(claims, 1):
            self.assertEqual((Path(chair['snapshot']) / f'__council__/initial-{number}.md').read_text(), claim)
        self.assertIn('ranking omitted', (Path(chair['snapshot']) / '__council__/critique-3.md').read_text())
        self.assertIn('assumptions', chair['objective'])
        self.assertIn('dissent', chair['objective'])
        synthesis = 'The drive remains an assumption; relocation is uncertain. Meaningful dissent remains.'
        receipt = self.native_receipt(chair, synthesis)
        self.assertNotIn(receipt['child_id'], children)
        council.record_native(self.run, 'synthesis', 'member-one', receipt)
        self.assertEqual(council.status(self.run)['outcome'], 'complete')
        self.assertEqual((self.run / 'synthesis-native.md').read_text() if not self.request.get('recovery') else
                         (self.run / ('native-' + chair['issued_id'] + '.md')).read_text(), synthesis)
        self.assertEqual(len(self.calls), 4)
        for _, _, payload in self.calls[2:]:
            inputs = json.loads(payload['messages'][0]['content'].split('Approved evidence and phase reports (JSON):\n', 1)[1])
            for number, claim in enumerate(claims, 1):
                self.assertEqual(inputs[f'__council__/initial-{number}.md'], claim)

    def assert_native_prompt(self, packet):
        prompt = packet['prompt']
        self.assertEqual(packet['prompt_sha256'], hashlib.sha256(prompt.encode('utf-8')).hexdigest())
        encoded = prompt.split('Approved evidence and phase reports (JSON):\n', 1)[1]
        inputs, end = json.JSONDecoder().raw_decode(encoded)
        for name in packet['snapshot_manifest']['files']:
            self.assertEqual(inputs[name].encode('utf-8'), (Path(packet['snapshot']) / name).read_bytes())
        observations = packet['execution_observations']
        if '__council__/execution-observations.md' in inputs:
            self.assertEqual(inputs['__council__/execution-observations.md'], observations)
            self.assertFalse(encoded[end:].strip())
        elif observations:
            self.assertEqual(encoded[end:], '\n\nExecution observations:\n' + observations)
        self.assertEqual(packet['reasoning_effort'], 'max')
        for denied in (str(self.repo), str(self.auth), str(self.run), self.request['coordinator_chat_id']):
            self.assertNotIn(denied, prompt)

    def test_native_text_prompt_preserves_evidence_and_original_deadline(self):
        evidence = 'Exact Unicode evidence: café\n"quoted" \\ path\n'
        (self.repo / 'evidence.txt').write_text(evidence)
        self.request['approved_files'] = self.approved(['evidence.txt'])
        self.run = Path(council.prepare(self.repo, self.request)['run'])
        before = json.loads((self.run / 'manifest.json').read_text())
        packet = council.packet(self.run, 'investigate', 'member-one')
        self.assert_native_prompt(packet)
        saved = json.loads((self.run / 'manifest.json').read_text())
        self.assertEqual(saved['members']['investigate:member-one']['prompt_sha256'], packet['prompt_sha256'])
        self.assertEqual(packet['deadline_monotonic'], before['started_monotonic'] + 600)
        self.assertEqual(before['timeout_seconds'], 1200)
        self.assertEqual(before['phase_seconds'], dict(investigate=600, critique=360, synthesis=240))
        with self.assertRaisesRegex(ValueError, 'already_issued'):
            council.packet(self.run, 'investigate', 'member-one')

    def test_private_timing_tracks_issuance_and_verification_without_renewal(self):
        for recovery in (False, True):
            with self.subTest(recovery=recovery):
                self.request['run_id'] = 'timing-' + str(recovery).lower()
                if recovery: self.request['recovery'] = True
                self.run = Path(council.prepare(self.repo, self.request)['run'])
                before = json.loads((self.run / 'manifest.json').read_text())
                packet = council.packet(self.run, 'investigate', 'member-one')
                issued = council.status(self.run)['timings']['investigate:member-one']
                self.assertGreaterEqual(issued['issued_at'], before['started_wall'])
                self.assertNotIn('verified_at', issued)
                council.record_native(self.run, 'investigate', 'member-one', self.native_receipt(packet))
                worker = council.packet(self.run, 'investigate', 'member-two')
                self.execute(Path(worker['worker_run']))
                council.verify_external(self.run, 'investigate', 'member-two', 'accepted', ['Observed complete local response'])
                status = council.status(self.run)
                self.assertEqual(status['timings'], council.status(self.run)['timings'])
                for member in ('member-one', 'member-two'):
                    times = status['timings']['investigate:' + member]
                    self.assertGreaterEqual(times['verified_at'], times['issued_at'])
                events = [json.loads(line) for line in (Path(worker['worker_run']) / 'progress.jsonl').read_text().splitlines()]
                phases = [event['phase'] for event in events]
                self.assertLess(phases.index('Starting'), phases.index('Transport result received'))
                self.assertLess(phases.index('Transport result received'), phases.index('Awaiting verification'))
                after = json.loads((self.run / 'manifest.json').read_text())
                self.assertEqual(after['started_monotonic'], before['started_monotonic'])
                self.assertEqual(after['phase_seconds'], before['phase_seconds'])

    def test_missing_ranking_keeps_critique(self):
        self.run = Path(council.prepare(self.repo, self.request)['run'])
        for phase in ('investigate', 'critique'):
            for member in council.GROUP_MEMBERS:
                packet = council.packet(self.run, phase, member)
                report = 'The premise is uncertain; no ranking supplied.' if phase == 'critique' else 'An initial answer.'
                if packet['kind'] == 'native':
                    council.record_native(self.run, phase, member, self.native_receipt(packet, report))
                else:
                    self.reply['choices'][0]['message']['content'] = report
                    self.execute(Path(packet['worker_run']))
                    council.verify_external(self.run, phase, member, 'accepted', ['Complete response within scope'])
        chair = council.packet(self.run, 'synthesis', 'member-one')
        for number in range(1, 4):
            self.assertEqual((Path(chair['snapshot']) / f'__council__/critique-{number}.md').read_text(),
                             'The premise is uncertain; no ranking supplied.')

    def test_direct_cancel_and_deadline_stop_owned_process(self):
        self.delay = 3
        for index, interrupt in enumerate((True, False)):
            self.request['run_id'] = 'stop-' + str(index)
            result = self.execute(self.prepare(), interrupt=interrupt, timeout=.15 if not interrupt else None)
            self.assertEqual(result['failure']['category'], 'interrupted' if interrupt else 'deadline')
            self.assertTrue(result['local_execution_stopped'])
            self.assertFalse(result['upstream_cancellation_confirmed'])
            self.assertIsNone(result['session_id'])
            self.assertEqual(len(self.processes), 1)
            self.assertIsNotNone(self.processes[0].poll())
            progress = self.root / result['task_id'] / 'progress.jsonl'
            events = [json.loads(line)['phase'] for line in progress.read_text().splitlines()] if progress.exists() else []
            self.assertNotIn('Transport result received', events)

    def test_local_failure_records_transport_result_without_provider_response(self):
        self.auth_file.write_text('{}')
        worker = self.prepare()
        result = self.execute(worker)
        self.assertEqual(result['failure']['category'], 'authentication')
        self.assertFalse(self.calls)
        events = [json.loads(line)['phase'] for line in (worker / 'progress.jsonl').read_text().splitlines()]
        self.assertIn('Transport result received', events)
        self.assertNotIn('Response received', events)

    def test_fresh_attempt_hash_not_fake_session(self):
        run = self.prepare()
        result = self.execute(run)
        brief = json.loads((run / 'brief.json').read_text())
        self.assertEqual(brief['transport'], 'openrouter-chat')
        self.assertEqual(result['transport'], 'openrouter-chat')
        self.assertIsNone(result['session_id'])
        self.assertEqual(result['generation_id'], 'gen-fixture')
        self.assertEqual(result['reported_model'], 'vendor/text')
        self.assertEqual(result['reported_cost_usd'], .01)
        self.assertRegex(result['attempt_id'], r'^[0-9a-f-]{36}$')
        self.assertRegex(result['request_sha256'], r'^[0-9a-f]{64}$')
        self.assertEqual(result['request_sha256'], hashlib.sha256(json.dumps(self.calls[0][2],
            sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()).hexdigest())
        accepted = council.verify_external(self.run, 'investigate', 'member-two', 'accepted', ['Checked source and scope'])
        self.assertEqual(accepted['state'], 'accepted')
        self.assertEqual(council._observations(json.loads((self.run / 'manifest.json').read_text()), 'investigate')['member-two']['state'], 'accepted')
        accepted['request_sha256'] = '0' * 64
        workers.save(run / 'result.json', accepted)
        value = json.loads((self.run / 'manifest.json').read_text())
        self.assertEqual(council._observations(value, 'investigate')['member-two']['state'], 'awaiting_verification')
        with self.assertRaisesRegex(ValueError, 'already_started'):
            self.execute(run)

    def ungrouped(self):
        self.request.pop('group')
        self.request.pop('chair')
        self.request['roster'] = dict(zip(council.MEMBERS, self.request['roster'].values()))
        for seat in self.request['roster'].values():
            if seat['kind'] == 'external':
                seat.pop('canonical_model')
                seat.pop('pricing')
        self.run = Path(council.prepare(self.repo, self.request)['run'])
        self.assertEqual(json.loads((self.run / 'manifest.json').read_text())['version'], 1)

    def test_ungrouped_text_verification_seals_reports_through_both_rounds(self):
        self.ungrouped()
        reports = {}
        for phase in ('investigate', 'critique'):
            for number, member in enumerate(council.MEMBERS, 1):
                packet = council.packet(self.run, phase, member)
                if phase == 'critique':
                    for name, report in reports['investigate'].items():
                        self.assertEqual((Path(packet['snapshot']) / '__council__' / name).read_bytes(), report)
                report = f'{phase}: perspective {number}; uncertain, uncited.\n'.encode()
                reports.setdefault(phase, {})[f'{"initial" if phase == "investigate" else "critique"}-{number}.md'] = report
                if member == 'native':
                    council.record_native(self.run, phase, member, self.native_receipt(packet, report.decode()))
                else:
                    worker = Path(packet['worker_run'])
                    self.reply['choices'][0]['message']['content'] = report.decode()
                    self.execute(worker)
                    accepted = workers.verify(worker, 'accepted', ['Checked completion, ownership and scope'])
                    self.assertEqual(accepted['response'].encode(), report)
                    with self.assertRaisesRegex(ValueError, 'not_verifiable'):
                        workers.verify(worker, 'accepted', ['Checked again'])
                    with self.assertRaisesRegex(ValueError, 'already_started'):
                        self.execute(worker)
                self.assertEqual(council.status(self.run)['accepted_participation'][phase]['accepted'], number)
        chair = council.packet(self.run, 'synthesis', 'native')
        expected = []
        for phase_reports in reports.values():
            for name, report in phase_reports.items():
                self.assertEqual((self.run / name).read_bytes(), report)
                expected.append(b'## ' + name.encode() + b'\n' + report)
        self.assertEqual(chair['reports'].encode(), b'\n\n'.join(expected))
        self.assertEqual(len(self.calls), 4)

    def test_ungrouped_text_verification_rejects_tampering_and_excludes_changed_proof(self):
        self.ungrouped()
        packet = council.packet(self.run, 'investigate', 'external-one')
        worker = Path(packet['worker_run'])
        result = self.execute(worker)
        result_path = worker / 'result.json'
        for key, replacement in (('attempt_id', '00000000-0000-4000-8000-000000000009'),
                                 ('request_sha256', '0' * 64), ('transport', 'opencode'),
                                 ('session_id', 'not-a-direct-session')):
            with self.subTest(stage='before', key=key):
                workers.save(result_path, dict(result, **{key: replacement}))
                before = result_path.read_bytes()
                with self.assertRaisesRegex(ValueError, 'fresh_external_attempt_required'):
                    workers.verify(worker, 'accepted', ['Checked scope'])
                self.assertEqual(result_path.read_bytes(), before)
        workers.save(result_path, result)
        brief_path = worker / 'brief.json'
        brief = brief_path.read_bytes()
        changed = json.loads(brief)
        changed['objective'] += ' Unapproved request change.'
        workers.save(brief_path, changed)
        with self.assertRaisesRegex(ValueError, 'council_worker_brief_changed'):
            workers.verify(worker, 'accepted', ['Checked scope'])
        brief_path.write_bytes(brief)
        accepted = workers.verify(worker, 'accepted', ['Checked completion, ownership and scope'])
        value = json.loads((self.run / 'manifest.json').read_text())
        self.assertTrue(council._external_verified(value, value['members']['investigate:external-one'],
            accepted, result_path.read_bytes()))
        for key, replacement in (('response', 'Altered answer'), ('request_sha256', '0' * 64),
                                 ('attempt_id', '00000000-0000-4000-8000-000000000009')):
            with self.subTest(stage='after', key=key):
                workers.save(result_path, dict(accepted, **{key: replacement}))
                self.assertEqual(council.status(self.run)['accepted_participation']['investigate']['accepted'], 0)
                with self.assertRaisesRegex(ValueError, 'not_verifiable'):
                    workers.verify(worker, 'accepted', ['Checked again'])

    def test_changed_consent_auth_and_free_block_dispatch(self):
        for index, change in enumerate(('consent', 'auth', 'free')):
            self.request['run_id'] = 'binding-' + str(index)
            run = self.prepare()
            if change == 'consent':
                openrouter_settings.disable(self.repo, {'expected_revision': self.settings['revision']})
            elif change == 'auth':
                original = self.auth
                self.auth = self.temporary / 'different-auth'
                self.auth.mkdir(mode=0o700)
            else:
                brief = json.loads((run / 'brief.json').read_text())
                brief['council']['group'] = 'Free'
                workers.save(run / 'brief.json', brief)
                with self.assertRaisesRegex(ValueError, 'council_worker_identity_changed'):
                    self.execute(run)
                self.assertEqual(self.processes, [])
                self.assertEqual(self.calls, [])
                continue
            result = self.execute(run)
            self.assertEqual(self.processes, [])
            self.assertEqual(self.calls, [])
            self.assertTrue(result['local_execution_stopped'])
            if change == 'consent':
                self.settings = openrouter_settings.enable(self.repo, {'expected_revision': self.settings['revision'] + 1})
            elif change == 'auth': self.auth = original

    def test_repository_still_uses_qualified_opencode(self):
        (self.repo / 'source.txt').write_text('Repository evidence')
        self.request.update(mode='repository', approved_files=self.approved(['source.txt']))
        with self.assertRaisesRegex(ValueError, 'invalid_council_capabilities|qualification'):
            self.prepare()
        for seat in list(self.request['roster'].values())[1:]:
            seat['capabilities'].pop('api')
            seat['capabilities']['tools'] = True
            seat['steps'] = 12
            seat['permission_qualification'] = dict(profile='council-readonly-v2', version='1.19.5',
                opencode_sha256=hashlib.sha256(self.executable.read_bytes()).hexdigest(), evidence='native:probe')
        run = self.prepare()
        result = self.execute(run)
        self.assertEqual(result['transport'], 'opencode')
        self.assertTrue(any(command[0] == str(self.executable) for command in self.commands))
        self.assertEqual(self.calls, [])

    def test_text_rejects_repository_qualification(self):
        for seat in list(self.request['roster'].values())[1:]:
            seat['capabilities'].pop('api')
            seat['capabilities']['tools'] = True
            seat['steps'] = 12
            seat['permission_qualification'] = dict(profile='council-readonly-v2', version='1.19.5',
                opencode_sha256=hashlib.sha256(self.executable.read_bytes()).hexdigest(), evidence='native:probe')
        with self.assertRaisesRegex(ValueError, 'council_text_single_request_required'):
            self.prepare()
        self.assertEqual(self.calls, [])

    def test_text_allowances_are_advisory_without_a_default_output_ceiling(self):
        self.request['question'] = 'x' * 12000
        for seat in self.request['roster'].values():
            seat.update(input_tokens=1, output_tokens=1)
        result = self.execute(self.prepare())
        self.assertEqual(result['state'], 'awaiting_verification')
        payload = self.calls[0][2]
        self.assertNotIn('max_tokens', payload)
        self.assertEqual(payload['reasoning'], {'effort': 'max'})
        self.assertIn('advisory', payload['messages'][0]['content'])
        packet = council.packet(self.run, 'investigate', 'member-one')
        self.assertIn('advisory', packet['objective'])

    def test_advisory_targets_can_exceed_provider_capacity(self):
        self.request['roster']['member-two'].update(input_tokens=50000, output_tokens=50000)
        result = self.execute(self.prepare())
        self.assertEqual(result['state'], 'awaiting_verification')
        self.assertNotIn('max_tokens', self.calls[0][2])

    def test_structured_context_failure_remains_distinct_from_bad_request(self):
        self.http_status = 400
        for error in (dict(code='context_length_exceeded'),
                      dict(code=400, metadata=dict(error_type='context_length_exceeded'))):
            self.reply = dict(error=dict(error, message='PRIVATE provider diagnostic'))
            failure = self.send()['failure']
            self.assertEqual(failure, dict(category='context', status_code=400))
        self.reply = dict(error=dict(code=400, message='context_length_exceeded PRIVATE'))
        self.assertEqual(self.send()['failure'], dict(category='invalid_request', status_code=400))

    def test_live_context_failure_can_correct_capacity_without_changing_targets(self):
        self.request.update(recovery=True, fallbacks={member: [] for member in council.GROUP_MEMBERS})
        complete = self.reply
        self.http_status, self.reply = 400, dict(error=dict(code='context_length_exceeded'))
        first = self.execute(self.prepare())
        self.assertEqual(first['failure']['category'], 'context')
        opened = council.investigate_failure(self.run, 'investigate', 'member-two')
        council.record_investigation(self.run, 'investigate', 'member-two', dict(
            candidate_id=opened['candidate_id'], failure_id=opened['failure_id'], searches=0, reads=1,
            sources=[dict(url='https://docs.example.org/context', checked_at=time.time(), authority='official',
                          applicability='Controlled endpoint requires a lower output ceiling')],
            corrections=[dict(kind='output_capacity', source=0, max_output_tokens=6000)]))
        council.correct_candidate(self.run, 'investigate', 'member-two', 0)
        packet = council.packet(self.run, 'investigate', 'member-two')
        self.http_status, self.reply = 200, complete
        result = self.execute(Path(packet['worker_run']))
        self.assertEqual(result['state'], 'awaiting_verification')
        self.assertEqual([call[2].get('max_tokens') for call in self.calls], [None, 6000])
        self.assertTrue(all(call[2]['reasoning'] == {'effort': 'max'} for call in self.calls))

    def test_length_failure_can_set_explicit_endpoint_capacity(self):
        self.request.update(recovery=True, fallbacks={member: [] for member in council.GROUP_MEMBERS})
        complete = copy.deepcopy(self.reply)
        self.reply['choices'][0] = dict(finish_reason='length', message=dict(content='Partial answer'))
        first = self.execute(self.prepare())
        self.assertEqual(first['failure']['category'], 'incomplete_output')
        self.assertEqual(first['failure']['terminal_reason'], 'length')
        self.assertNotIn('max_tokens', self.calls[0][2])
        opened = council.investigate_failure(self.run, 'investigate', 'member-two')
        council.record_investigation(self.run, 'investigate', 'member-two', dict(
            candidate_id=opened['candidate_id'], failure_id=opened['failure_id'], searches=0, reads=1,
            sources=[dict(url='https://docs.example.org/default-output', checked_at=time.time(), authority='official',
                          applicability='Provider default truncated; explicit observed capacity permits more output')],
            corrections=[dict(kind='output_capacity', source=0, max_output_tokens=8000)]))
        council.correct_candidate(self.run, 'investigate', 'member-two', 0)
        packet = council.packet(self.run, 'investigate', 'member-two')
        self.reply = complete
        result = self.execute(Path(packet['worker_run']))
        self.assertEqual(result['state'], 'awaiting_verification')
        self.assertEqual([call[2].get('max_tokens') for call in self.calls], [None, 8000])
        self.assertTrue(all(call[2]['reasoning'] == {'effort': 'max'} for call in self.calls))
