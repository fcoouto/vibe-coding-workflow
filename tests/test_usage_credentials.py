"""Offline credential contract tests. The native store is never opened."""
import unittest
import subprocess
import os
from unittest.mock import patch

from runtime import usage_credentials as credentials


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.items = {}
        backend = patch.object(credentials, '_keychain')
        self.backend = backend.start()
        self.addCleanup(backend.stop)
        self.backend.return_value.add.side_effect = self.items.__setitem__
        self.backend.return_value.read.side_effect = self.items.__getitem__
        reader = patch.object(credentials, '_read_key', side_effect=self.items.__getitem__)
        self.reader = reader.start()
        self.addCleanup(reader.stop)
        self.secret = b'synthetic-secret'

    def binding(self, reference):
        return dict(storage_kind='macos_keychain', organization='org-example',
                    project='proj_example', credential_ref=reference)

    def test_round_trip_and_scope(self):
        ref = credentials.store_key('org-example', 'proj_example', self.secret)
        binding = self.binding(ref)
        self.assertEqual(credentials.resolve_key(binding), self.secret)
        self.assertEqual(list(self.items), [f'org-example/proj_example/{ref}'])
        for field in ('organization', 'project', 'credential_ref'):
            with self.subTest(field=field), self.assertRaises(credentials.CredentialError):
                credentials.resolve_key(dict(binding, **{field: 'vcw_' + '0' * 32}))

    def test_invalid_inputs_never_open_storage(self):
        with self.assertRaises(credentials.CredentialError):
            credentials.resolve_key(dict(organization='org-example', project='proj_example',
                                         credential_ref='OPENAI_API_KEY'))
        for secret in (b'', b'bad\nvalue', b'x' * 513):
            with self.assertRaises(credentials.CredentialError):
                credentials.store_key('org-example', 'proj_example', secret)
        self.backend.assert_not_called()

    def test_backend_failures_are_sanitized(self):
        self.reader.side_effect = RuntimeError('synthetic-secret')
        with self.assertRaisesRegex(credentials.CredentialError, '^credential_unavailable$'):
            credentials.resolve_key(self.binding('vcw_' + '0' * 32))
        self.backend.return_value.add.side_effect = RuntimeError('synthetic-secret')
        with self.assertRaisesRegex(credentials.CredentialError, '^credential_store_failed$'):
            credentials.store_key('org-example', 'proj_example', self.secret)
        self.backend.return_value.add.assert_called_once()

    def test_non_macos_rejected_without_loading_framework(self):
        with patch.object(credentials.sys, 'platform', 'linux'), self.assertRaises(
                credentials.CredentialError):
            credentials._native_keychain()


class LookupPipeTests(unittest.TestCase):
    def test_read_is_bounded_and_keeps_secret_out_of_arguments_and_output(self):
        def child(args, **kwargs):
            self.assertEqual(kwargs['timeout'], credentials.READ_TIMEOUT)
            self.assertEqual(kwargs['stdout'], subprocess.DEVNULL)
            self.assertEqual(kwargs['stderr'], subprocess.DEVNULL)
            self.assertNotIn('synthetic-secret', args)
            os.write(kwargs['pass_fds'][0], b'synthetic-secret')

        binding = dict(storage_kind='macos_keychain', organization='org-example',
                       project='proj_example', credential_ref='vcw_' + '0' * 32)
        with patch.object(credentials.sys, 'platform', 'darwin'), patch.object(
                credentials.subprocess, 'run', side_effect=child):
            self.assertEqual(credentials.resolve_key(binding), b'synthetic-secret')
        with patch.object(credentials.sys, 'platform', 'darwin'), patch.object(
                credentials.subprocess, 'run', side_effect=subprocess.TimeoutExpired('child', 5)):
            with self.assertRaisesRegex(credentials.CredentialError, '^credential_unavailable$'):
                credentials.resolve_key(binding)


if __name__ == '__main__':
    unittest.main()
