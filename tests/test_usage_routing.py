"""Local-only management and request-bound validation."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from runtime import usage_routing as routing
from runtime.usage_budget import BudgetError


PROFILE = dict(model='example-model', reasoning='medium', tier='default', input_rate=4,
               cached_input_rate=2, cache_write_rate=8, output_rate=20,
               max_input_tokens=10000, max_output_tokens=1000,
               verified_at=100, valid_until=1000, count_maximum=0)
PACKET = dict(version=1, model='example-model', reasoning='medium', text='Synthetic offline text',
              input_tokens=1200, max_output_tokens=250)


class RoutingTests(unittest.TestCase):
    def test_status_off_never_creates_state_or_reads_credentials(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {'OPENAI_API_KEY': 'must-not-read'}):
            with patch('socket.socket', side_effect=AssertionError('network forbidden')):
                result = routing.status(directory)
        self.assertEqual(result['mode'], 'off')
        self.assertFalse(result['live_dispatch'])
        self.assertFalse(result['review_authority'])

    def test_canonical_enrollment_is_orientation_without_live_readiness(self):
        from tests.fixture_canonical_birth import CanonicalBirthFixture
        owner = CanonicalBirthFixture('runTest')
        self.addCleanup(owner.doCleanups)
        fixture, _, _ = owner.accepted_birth(linked=True)
        observed = routing.status(fixture.repo)
        self.assertTrue(observed['enrolled'])
        self.assertFalse(observed['live_dispatch'])
        self.assertEqual(observed['enrollment'], 'configured')

    def test_live_enable_and_run_always_block(self):
        for operation in (routing.enable, routing.run):
            with self.assertRaisesRegex(BudgetError, 'live_execution_unavailable'):
                operation(None, {'enabled': True})

    def test_quote_uses_highest_input_rate_and_rounds_up(self):
        quote = routing.quote(PACKET, PROFILE, 101)
        self.assertEqual(quote['maximum_usd_micros'], 1)
        p = {**PROFILE, 'output_rate': 20_000_000}
        self.assertEqual(routing.quote(PACKET, p, 101)['maximum_usd_micros'], 5001)
        self.assertTrue(quote['simulation_only'])
        self.assertNotEqual(quote['digest'], routing.quote({**PACKET, 'text':'changed'}, PROFILE, 101)['digest'])

    def test_quote_rejects_unknown_fields_mismatch_staleness_and_overflows(self):
        cases = [({**PACKET, 'tools': []}, PROFILE, 101),
                 ({**PACKET, 'model':'other'}, PROFILE, 101),
                 (PACKET, {**PROFILE, 'tier':'auto'}, 101),
                 (PACKET, PROFILE, 1000), (PACKET, PROFILE, 99),
                 ({**PACKET, 'input_tokens':True}, PROFILE, 101),
                 ({**PACKET, 'max_output_tokens':1001}, PROFILE, 101),
                 (PACKET, {**PROFILE, 'count_maximum':None}, 101)]
        for packet, profile, now in cases:
            with self.subTest(packet=packet, profile=profile, now=now), self.assertRaises(BudgetError):
                routing.quote(packet, profile, now)

    def test_cli_status_and_quote_are_offline_and_bounded(self):
        command = [sys.executable, '-I', '-B', 'scripts/usage_routing.py']
        result = subprocess.run(command + ['status', '--cwd', '.'], capture_output=True, text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['mode'],'off')
        result = subprocess.run(command + ['quote'], input=json.dumps(dict(version=1,packet=PACKET,profile=PROFILE,now=101)), capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(json.loads(result.stdout)['simulation_only'])
        for payload in ('x'*70000, '{"version":1,"version":1}'):
            result = subprocess.run(command + ['quote'], input=payload,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertNotIn('Traceback',result.stderr)


if __name__ == '__main__': unittest.main()
