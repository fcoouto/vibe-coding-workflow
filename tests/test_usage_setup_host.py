"""Exercise the Codex setup bridge without account tools or credential storage."""
from contextlib import contextmanager
import os
import pty
import termios
import unittest
from unittest.mock import Mock, patch

from scripts import usage_key_setup_host as bridge


class SetupBridgeTests(unittest.TestCase):
    def test_dedicated_terminal_disables_echo_and_restores_settings(self):
        master, slave = pty.openpty()
        try:
            with os.fdopen(slave, 'r') as terminal, patch.object(bridge.sys, 'stdin', terminal):
                previous = termios.tcgetattr(slave)
                with bridge._private_terminal():
                    flags = termios.tcgetattr(slave)[3]
                    self.assertEqual(flags & (termios.ECHO | termios.ICANON), 0)
                restored = termios.tcgetattr(slave)
                self.assertEqual(restored[3] & (termios.ECHO | termios.ICANON),
                                 previous[3] & (termios.ECHO | termios.ICANON))
                self.assertEqual(restored[6], previous[6])
        finally:
            os.close(master)

    def test_forwards_only_creation_arguments_and_safe_off_receipt(self):
        selection = dict(name='Pilot', organization_id='org_fixture', project_id='proj_fixture')
        encrypted = {'structuredContent': {'encrypted_api_key': {'version': 1, 'ciphertext': 'fixture'}}}
        request = dict(selection, recipient_public_key_jwk={'kty': 'RSA'})
        receipt = dict(mode='off', binding={'credential_ref': 'fixture'})
        pending = Mock()
        pending.creation_arguments.return_value = request
        pending.finish.return_value = receipt
        frames = Mock(side_effect=[selection, encrypted])
        output = Mock()

        @contextmanager
        def setup(chosen, approve, *, node_executable):
            self.assertEqual(chosen, selection)
            self.assertIs(approve(chosen), True)
            self.assertEqual(node_executable, '/qualified/node')
            yield pending

        with patch.object(bridge.usage_setup, 'prepare_setup', side_effect=setup):
            bridge.exchange(frames, output, node_executable='/qualified/node')
        pending.creation_arguments.assert_called_once_with()
        pending.finish.assert_called_once_with(encrypted)
        self.assertEqual([call.args[0] for call in output.call_args_list], [
            {'ready': True}, {'creation_arguments': request}, {'receipt': receipt},
        ])

    def test_lost_connector_frame_marks_creation_unverified(self):
        pending = Mock()
        pending.finish.side_effect = bridge.usage_setup.SetupError('credential_creation_unverified')
        frames = Mock(side_effect=[{}, TimeoutError()])
        output = Mock()

        @contextmanager
        def setup(*args, **kwargs):
            yield pending

        with patch.object(bridge.usage_setup, 'prepare_setup', side_effect=setup):
            with self.assertRaisesRegex(bridge.usage_setup.SetupError, 'credential_creation_unverified'):
                bridge.exchange(frames, output, node_executable='/qualified/node')
        pending.finish.assert_called_once_with(None)


if __name__ == '__main__':
    unittest.main()
