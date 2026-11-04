"""Private local settings never acquire live funding or change enrollment."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime import usage_routing as routing, usage_settings as settings
from runtime.usage_budget import BudgetError
from tests.test_smart_balance import BINDING, POLICY
from tests.test_usage_routing import PROFILE


class UsageSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.folder = self.root / 'private'
        self.addCleanup(self.temp.cleanup)
        for mock in (patch.object(settings,'scope',return_value=('scope',self.root)),
                     patch.object(settings,'directory',return_value=self.folder),
                     patch('time.time',return_value=101)):
            mock.start(); self.addCleanup(mock.stop)
        self.request = dict(version=1,expected_revision=0,expected_org_revision=0,
                            binding=BINDING,policy=POLICY,profile=PROFILE,class_name='investigation',mode='smart')

    def test_read_only_lookup_never_initializes_missing_state(self):
        result = routing.evaluate(self.root,{})
        self.assertEqual(result['decision'],'paused')
        self.assertFalse(self.folder.exists())

    def test_keychain_binding_persists_only_metadata_without_access(self):
        binding = dict(organization='org-example', project='proj_example',
                       credential_ref='vcw_' + '0' * 32, storage_kind='macos_keychain')
        with patch('runtime.usage_credentials._keychain') as keychain:
            result = routing.configure(self.root, dict(self.request, version=2, binding=binding))
            self.assertEqual(result['mode'], 'off')
            with settings.controller(self.root) as controller:
                data = controller.ledger.snapshot()
                self.assertEqual(controller._config(data)['binding'], binding)
                self.assertFalse(controller.status()['live_dispatch'])
            with self.assertRaisesRegex(BudgetError, 'invalid_credential_reference'):
                routing.configure(self.root, dict(self.request, version=2, binding=BINDING))
            keychain.assert_not_called()

    def test_configure_persists_off_and_disable_only_changes_local_consent(self):
        result = routing.configure(self.root,self.request)
        self.assertEqual(result['mode'],'off');self.assertEqual(result['requested_mode'],'smart')
        with settings.controller(self.root) as controller:
            self.assertFalse(controller.status()['live_dispatch'])
            self.assertTrue(controller.enable(1)['enabled'])
        self.assertEqual(routing.disable(self.root,dict(expected_revision=2))['reason'],'disabled')
        with self.assertRaises(BudgetError): routing.disable(self.root,dict(expected_revision=2))
        self.assertFalse((self.root / '.vibe-coding-workflow').exists())
        self.assertFalse((self.root / '.env').exists())

    def test_explicit_mode_enablement_preserves_shared_policy_and_off_recovery(self):
        configured = routing.configure(self.root, self.request)
        self.assertEqual(configured['mode'], 'off')
        with settings.controller(self.root) as controller:
            before = controller.ledger.snapshot()['organizations']
        manual = routing.enable(self.root, dict(expected_revision=1, mode='manual'))
        self.assertEqual(manual['mode'], 'manual')
        self.assertFalse(manual['live_dispatch'])
        self.assertTrue(manual['warnings'])
        with self.assertRaisesRegex(BudgetError, 'consent_revision_changed'):
            routing.enable(self.root, dict(expected_revision=1, mode='smart'))
        with self.assertRaisesRegex(BudgetError, 'invalid_mode'):
            routing.enable(self.root, dict(expected_revision=2, mode='paid-fallback'))
        smart = routing.enable(self.root, dict(expected_revision=2, mode='smart'))
        self.assertEqual(smart['mode'], 'smart')
        self.assertFalse(smart['live_dispatch'])
        self.assertEqual(routing.disable(self.root, dict(expected_revision=3))['mode'], 'off')
        with settings.controller(self.root) as controller:
            self.assertEqual(controller.ledger.snapshot()['organizations'], before)

    def test_missing_database_with_saved_checkout_pin_never_recreates_allowance(self):
        routing.configure(self.root,self.request)
        (self.folder/'organizations.sqlite3').unlink()
        with self.assertRaises(BudgetError): routing.configure(self.root,self.request)
        self.assertFalse((self.folder/'organizations.sqlite3').exists())

    def test_another_checkout_cannot_initialize_over_lost_existing_authority(self):
        routing.configure(self.root,self.request)
        (self.folder/'organizations.sqlite3').unlink()
        with patch.object(settings,'scope',return_value=('other',self.root)), self.assertRaises(BudgetError):
            routing.configure(self.root,self.request)
        self.assertFalse((self.folder/'organizations.sqlite3').exists())

    def test_stale_checkout_revision_does_not_modify_shared_policy(self):
        routing.configure(self.root,self.request)
        changed=copy.deepcopy(self.request);changed['expected_org_revision']=1;changed['policy']['amount']=999
        with self.assertRaises(BudgetError): routing.configure(self.root,changed)
        with settings.controller(self.root) as controller:
            self.assertEqual(controller.ledger.snapshot()['organizations']['org']['policy']['amount'],500)

    def test_corrupt_private_database_is_reported_as_recovery_required(self):
        routing.configure(self.root,self.request)
        (self.folder/'organizations.sqlite3').write_bytes(b'not a database')
        with self.assertRaisesRegex(BudgetError,'manual_recovery_required'):
            with settings.controller(self.root): pass

    def test_symlink_marker_is_rejected(self):
        routing.configure(self.root,self.request)
        marker=self.folder/'checkout-scope.json'
        other=self.folder/'other.json';marker.rename(other);marker.symlink_to(other)
        with self.assertRaises(BudgetError):
            with settings.controller(self.root): pass

if __name__ == '__main__': unittest.main()
