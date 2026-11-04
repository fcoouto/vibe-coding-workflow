"""Exercise the host bridge with synthetic picker, connector, and helper events."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from runtime import usage_setup
from runtime.usage_setup import SetupError, prepare_setup
from tests.test_usage_key_setup import ENCRYPT, HELPER, NODE, SECRET


SELECTION = dict(name='Usage Routing', organization_id='org-selected', project_id='proj_selected',
                 expires_in_seconds=604800)
JWK = dict(kty='RSA', n='g' + 'A' * 682, e='AQAB')
CIPHERTEXT = 'A' * 683
REFERENCE = 'vcw_' + '1' * 32
RESULT = {'structuredContent': {'encrypted_api_key': {'version': 1, 'ciphertext': CIPHERTEXT}}}


class UsageSetupTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.reference = REFERENCE

    @contextmanager
    def start_helper(self, organization, project):
        self.events.append(('start', organization, project))
        try:
            yield self
        finally:
            self.events.append('closed')

    def public_key(self):
        return JWK.copy()

    def ready(self):
        return True

    def store(self, ciphertext):
        self.events.append(('store', ciphertext == CIPHERTEXT))
        if isinstance(self.reference, Exception):
            raise self.reference
        return {'credential_ref': self.reference}

    def approve(self, proposal):
        self.events.append(('approve', dict(proposal)))
        return True

    def test_confirmed_picker_fields_survive_creation_and_storage(self):
        with prepare_setup(SELECTION, self.approve, start_helper=self.start_helper) as pending:
            self.assertEqual(pending.creation_arguments(), dict(SELECTION, recipient_public_key_jwk=JWK))
            receipt = pending.finish(RESULT)
        self.assertEqual(self.events, [
            ('approve', dict(SELECTION, storage_kind='macos_keychain', keychain='default',
                             service='vibe-coding-workflow.openai')),
            ('start', 'org-selected', 'proj_selected'), ('store', True), 'closed',
        ])
        self.assertEqual(receipt, {'selection': SELECTION, 'mode': 'off', 'binding': {
            'organization': 'org-selected', 'project': 'proj_selected',
            'credential_ref': REFERENCE, 'storage_kind': 'macos_keychain',
        }})

    def test_declined_or_unconfirmed_destination_never_starts_helper(self):
        for decision in (False, None, 'approved', {'approved': True}):
            with self.subTest(decision=decision), self.assertRaisesRegex(SetupError, 'credential_setup_not_approved'):
                with prepare_setup(SELECTION, lambda _: decision, start_helper=self.start_helper):
                    self.fail('unconfirmed setup must not be prepared')
        self.assertEqual(self.events, [])

    def test_absent_expiry_is_omitted_and_invalid_expiry_cannot_be_approved(self):
        selection = {key: value for key, value in SELECTION.items() if key != 'expires_in_seconds'}
        with prepare_setup(selection, self.approve, start_helper=self.start_helper) as pending:
            self.assertNotIn('expires_in_seconds', pending.creation_arguments())
        self.assertIsNone(self.events[0][1]['expires_in_seconds'])
        for expiry in (None, 0, -1, True, '604800', 2**53):
            with self.subTest(expiry=expiry), self.assertRaisesRegex(SetupError, 'invalid_key_selection'):
                with prepare_setup(dict(selection, expires_in_seconds=expiry), self.approve,
                                   start_helper=self.start_helper):
                    self.fail('invalid picker selection reached setup')
        self.assertEqual(len(self.events), 3)

    def test_pending_exchange_is_single_use_and_closes(self):
        with prepare_setup(SELECTION, self.approve, start_helper=self.start_helper) as pending:
            with self.assertRaises(SetupError):
                pending.finish(RESULT)
            pending.creation_arguments()
            with self.assertRaises(SetupError):
                pending.creation_arguments()
            pending.finish(RESULT)
            with self.assertRaises(SetupError):
                pending.finish(RESULT)
        with self.assertRaises(SetupError):
            pending.creation_arguments()
        self.assertEqual(self.events.count(('store', True)), 1)
        self.assertEqual(self.events[-1], 'closed')

    def test_connector_failure_or_target_mismatch_does_not_store(self):
        for result in (None, {'isError': True, **RESULT}, {'content': [RESULT]},
                       {'structuredContent': dict(RESULT['structuredContent'], project_id='proj_other')}):
            with self.subTest(result=result), prepare_setup(SELECTION, self.approve,
                                                            start_helper=self.start_helper) as pending:
                pending.creation_arguments()
                with self.assertRaisesRegex(SetupError, 'credential_creation_unverified'):
                    pending.finish(result)
                with self.assertRaises(SetupError):
                    pending.creation_arguments()
        self.assertNotIn(('store', True), self.events)
        self.assertEqual(self.events.count('closed'), 4)

    def test_connector_cannot_echo_a_boolean_as_confirmed_expiry(self):
        selection = dict(SELECTION, expires_in_seconds=1)
        result = {'structuredContent': dict(RESULT['structuredContent'], expires_in_seconds=True)}
        with prepare_setup(selection, self.approve, start_helper=self.start_helper) as pending:
            pending.creation_arguments()
            with self.assertRaisesRegex(SetupError, 'credential_creation_unverified'):
                pending.finish(result)
        self.assertNotIn(('store', True), self.events)

    def test_storage_failure_and_bad_receipt_require_recovery_without_replay(self):
        for reference in (RuntimeError('sensitive helper output'), 'sensitive helper output'):
            self.reference = reference
            with prepare_setup(SELECTION, self.approve, start_helper=self.start_helper) as pending:
                pending.creation_arguments()
                with self.assertRaises(SetupError) as error:
                    pending.finish(RESULT)
                self.assertEqual(str(error.exception), 'credential_storage_recovery_required')
                self.assertIsNone(error.exception.__cause__)
                with self.assertRaises(SetupError):
                    pending.finish(RESULT)
        self.assertEqual(self.events.count(('store', True)), 2)
        self.assertEqual(self.events.count('closed'), 2)

    def test_production_helper_requires_an_explicit_absolute_node_executable(self):
        with patch.object(usage_setup.sys, 'platform', 'darwin'), patch.object(usage_setup.subprocess, 'Popen') as start:
            for node in (None, 'node', 'bin/node'):
                with self.subTest(node=node), self.assertRaisesRegex(SetupError, 'credential_setup_unavailable'):
                    with prepare_setup(SELECTION, self.approve, node_executable=node):
                        self.fail('unqualified Node reached setup')
            start.assert_not_called()

    @unittest.skipUnless(NODE and sys.platform == 'darwin', 'macOS and Node required')
    def test_node_bridge_completes_via_private_pipe_with_synthetic_writer(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'scripts').mkdir()
            (root / 'runtime').mkdir()
            script = root / 'scripts' / HELPER.name
            shutil.copyfile(HELPER, script)
            writer = root / 'runtime' / 'usage_credentials.py'
            writer.write_text('import sys\n'
                              'assert sys.argv[1:] == ["org-selected", "proj_selected"]\n'
                              f'assert sys.stdin.buffer.read() == {SECRET!r}\n'
                              f'print({json.dumps({"credential_ref": REFERENCE})!r})\n')
            with patch.object(usage_setup, '_HELPER', script), prepare_setup(
                SELECTION, self.approve, node_executable=Path(NODE).resolve()
            ) as pending:
                request = pending.creation_arguments()
                encrypted = subprocess.run([NODE, '-e', ENCRYPT, json.dumps(request['recipient_public_key_jwk'])],
                                           input=SECRET, capture_output=True, check=True, timeout=10)
                receipt = pending.finish({'structuredContent': {'encrypted_api_key': json.loads(encrypted.stdout)}})
            self.assertEqual(receipt['binding']['credential_ref'], REFERENCE)

    @unittest.skipUnless(NODE and sys.platform == 'darwin', 'macOS and Node required')
    def test_helper_cleanup_stops_writer_after_node_leader_exits(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / 'child.pid'
            script = Path(temp) / 'leader.mjs'
            script.write_text(
                'import { spawn } from "node:child_process";\n'
                'import { writeFileSync } from "node:fs";\n'
                'const child = spawn(process.execPath, ["-e", "setInterval(() => {}, 60000)"], '
                '{stdio: "ignore"});\n'
                'child.unref();\n'
                f'writeFileSync({json.dumps(str(marker))}, String(child.pid));\n'
                f'console.log(JSON.stringify({json.dumps({"recipient_public_key_jwk": JWK})}));\n'
            )
            with patch.object(usage_setup, '_HELPER', script), usage_setup._start_helper(
                'org-selected', 'proj_selected', Path(NODE).resolve()
            ) as helper:
                try:
                    helper.public_key()
                finally:
                    if marker.is_file():
                        self.addCleanup(self.stop_fixture, int(marker.read_text()), helper.process.pid)
                child_pid = int(marker.read_text())
                self.assertTrue(select.select([helper.process.stdout], [], [], 3)[0], 'leader did not exit')
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                status = subprocess.run(['/bin/ps', '-o', 'stat=', '-p', str(child_pid)],
                                        capture_output=True, timeout=2).stdout.strip()
                if not status or status.startswith(b'Z'):
                    break
                time.sleep(0.02)
            else:
                self.fail('leader exited but the helper left its writer running')

    @staticmethod
    def stop_fixture(child_pid, group):
        try:
            if os.getpgid(child_pid) == group:
                os.kill(child_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
