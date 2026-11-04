"""Smart Balance decisions and shared runner exercised without account access."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from runtime import usage_budget as budget, usage_routing as routing
from tests.test_usage_budget import native
from tests.test_usage_routing import PACKET, PROFILE

BINDING = dict(organization='org', project='project', credential_ref='OPENAI_API_KEY')
POLICY = dict(cycle='cycle1', start=0, end=10000, expiry=10000, stop_at=9000,
              ceiling='custom', amount=500, grant_amount=800, pilot_limit=500, task_limit=200)


def qualification():
    return dict(class_name='investigation', profile_digest=routing.profile_digest(PROFILE),
                samples=4, quality_passed=True, net_native_saved=5, uncertainty=1,
                unit='allowance_pp', native_calibrated=True, observed_at=100, valid_until=900)


def task(**updates):
    value = dict(task_id='task', run_id='run', class_name='investigation', packet=PACKET.copy(),
                 provider='auto', local_preferred=False, api_only=False, reviewer_available=True,
                 native=native(), snapshots=[])
    value.update(updates)
    return value


class SmartBalanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'private' / 'ledger'
        self.identity = budget.initialize(self.path)
        self.ledger = budget.Ledger(self.path, self.identity)
        self.controller = routing.Controller(self.ledger, 'scope', clock=lambda: 101)
        self.request = dict(version=1, expected_revision=0, expected_org_revision=0,
                            binding=BINDING, policy=POLICY, profile=PROFILE,
                            class_name='investigation', mode='smart')
        self.controller.configure(self.request)
        self.ledger.observe('org', 800, 100)
        self.controller.record_qualification(qualification())

    def tearDown(self):
        self.ledger.close(); self.temp.cleanup()

    def test_enable_warns_without_requiring_auto_reload_to_be_disabled(self):
        state = self.controller.status()
        self.assertEqual(state['mode'], 'off')
        self.assertEqual(state['requested_mode'], 'smart')
        self.assertFalse(state['live_dispatch'])
        enabled = self.controller.enable(1)
        self.assertTrue(enabled['enabled'])
        self.assertEqual(enabled['mode'],'smart')
        self.assertFalse(enabled['live_dispatch'])
        self.assertTrue(enabled['warnings'])
        self.assertEqual(enabled['funding_policy'],'best_effort_grant')

    def test_smart_shadow_selects_qualified_work_without_writes_or_calls(self):
        before = self.ledger.snapshot()
        decision = self.controller.evaluate(task())
        self.assertEqual(decision['decision'], 'eligible')
        self.assertTrue(decision['simulation_only'])
        self.assertEqual(decision['live_blocker'], 'live_adapter_unavailable')
        self.assertEqual(self.ledger.snapshot(), before)

    def test_provider_and_local_choices_are_preserved(self):
        for change in (dict(provider='openrouter'), dict(local_preferred=True)):
            self.assertEqual(self.controller.evaluate(task(**change))['decision'], 'native')
        self.assertEqual(self.controller.evaluate(task(provider='openrouter',api_only=True))['decision'], 'paused')

    def test_missing_review_qualification_or_capacity_pauses(self):
        for change in (dict(reviewer_available=False), dict(class_name='new'), dict(native=native(remaining=25))):
            self.assertEqual(self.controller.evaluate(task(**change))['decision'], 'paused')
        q = qualification(); q['net_native_saved'] = q['uncertainty']
        self.controller.record_qualification(q)
        self.assertEqual(self.controller.evaluate(task())['reason'], 'savings_unqualified')

    def test_changed_profile_or_proxy_only_measurement_cannot_qualify_smart(self):
        q = qualification(); q['profile_digest'] = '0'*64
        with self.assertRaises(budget.BudgetError): self.controller.record_qualification(q)
        q = qualification(); q['unit'] = 'tokens'
        self.controller.record_qualification(q)
        self.assertEqual(self.controller.evaluate(task())['reason'], 'savings_unqualified')

    def test_disable_revisions_invalidate_prepared_decisions(self):
        self.controller.disable(1)
        self.assertEqual(self.controller.evaluate(task())['reason'], 'disabled')
        with self.assertRaises(budget.BudgetError): self.controller.disable(1)

    def test_balances_cannot_be_promoted_to_funding_authority(self):
        self.controller.clock = lambda: 120
        observation = dict(version=1, organization='org', project='project', currency='USD',
                           balance=700, expiry=10000, observed_at=110, source='codex-dashboard', pool='benefit')
        self.controller.observe(observation)
        self.assertFalse(self.controller.status()['live_dispatch'])
        for changes in (dict(currency='EUR'),dict(organization='other'),dict(expiry=11000),dict(source='worker')):
            with self.assertRaises(budget.BudgetError): self.controller.observe({**observation,**changes})

    def test_snapshot_changes_pause_before_counting(self):
        source = Path(self.temp.name) / 'source.txt'; source.write_text('before')
        snapshot = dict(path=str(source),sha256=hashlib.sha256(source.read_bytes()).hexdigest())
        source.write_text('changed')
        self.assertEqual(self.controller.evaluate(task(snapshots=[snapshot]))['reason'], 'snapshot_changed')

    def test_one_original_task_stays_reserved_through_review(self):
        self.ledger.begin('org','task','run','packet',0,1,101,native())
        self.ledger.close_run('run')
        with self.assertRaisesRegex(budget.BudgetError, 'native_task_outstanding'):
            self.ledger.begin('org','other','other','packet',0,1,101,native('other'))

    def test_full_fake_runner_settles_calls_but_never_accepts_model_output(self):
        from unittest.mock import patch
        from tests.test_openai_api import Connection, Response, completed
        response = completed(); response['model'] = PROFILE['model']
        queue = [Response(dict(object='response.input_tokens',input_tokens=1200)), Response(response)]
        response['usage'].update(input_tokens=1200,total_tokens=1217)
        queue[1] = Response(response)
        connections = []
        def factory(host, timeout):
            connection = Connection(queue.pop(0)); connections.append(connection); return connection
        with patch('runtime.openai_api.time.time',return_value=101):
            result = self.controller.run_shadow(task(), connection_factory=factory)
        self.assertFalse(result['accepted']); self.assertTrue(result['requires_native_review'])
        self.assertTrue(result['simulation_only'])
        self.assertIsNone(self.ledger.snapshot()['slot'])
        self.assertEqual(len(self.ledger.snapshot()['native']),1)
        self.assertEqual(len(connections),2)
        replay = self.controller.run_shadow(task(), connection_factory=factory)
        self.assertTrue(replay['replayed']); self.assertEqual(len(connections),2)

    def test_disable_between_count_and_generation_prevents_second_send(self):
        from unittest.mock import patch
        from tests.test_openai_api import Connection, Response
        sent = []
        def factory(host,timeout):
            connection = Connection(Response(dict(object='response.input_tokens',input_tokens=1200)))
            sent.append(connection)
            original = connection.getresponse
            def receive():
                self.controller.disable(1)
                return original()
            connection.getresponse = receive
            return connection
        with patch('runtime.openai_api.time.time',return_value=101), self.assertRaises(budget.BudgetError):
            self.controller.run_shadow(task(),connection_factory=factory)
        self.assertEqual(sum(len(connection.requests) for connection in sent),1)
        self.assertIsNone(self.ledger.snapshot()['slot'])

    def test_credential_denial_after_count_preserves_only_the_sent_charge(self):
        from unittest.mock import Mock, patch
        from runtime import usage_credentials
        from tests.test_openai_api import Connection, Response

        request = dict(self.request, version=2, expected_revision=1, expected_org_revision=1,
                       binding=dict(BINDING, storage_kind='macos_keychain',
                                    credential_ref='vcw_' + '0' * 32),
                       profile=dict(PROFILE, count_maximum=7))
        self.controller.configure(request)
        self.controller.record_qualification(dict(
            qualification(), profile_digest=routing.profile_digest(request['profile'])))
        connection = Connection(Response(dict(object='response.input_tokens', input_tokens=1200)))
        factory = Mock(return_value=connection)
        resolver = Mock(side_effect=[b'synthetic-key', usage_credentials.CredentialError('denied')])

        with patch('runtime.openai_api.time.time', return_value=101), self.assertRaisesRegex(
                budget.BudgetError, 'credential_unavailable'):
            self.controller.run_shadow(task(), connection_factory=factory, credential_resolver=resolver)

        state = self.ledger.snapshot()
        calls = state['runs']['run']['calls']
        self.assertEqual((calls['count']['state'], calls['count']['cost']), ('completed', 7))
        self.assertEqual((calls['generation']['state'], calls['generation']['cost']),
                         ('rejected-before-send', 0))
        self.assertIsNone(state['slot'])
        self.assertEqual(len(state['native']), 1)
        self.assertEqual(resolver.call_count, 2)
        factory.assert_called_once()
        self.assertEqual(len(connection.requests), 1)
        self.assertEqual(connection.requests[0][3]['Authorization'], 'Bearer synthetic-key')

    def test_ambiguous_count_never_retries_or_falls_back(self):
        from unittest.mock import patch
        from tests.test_openai_api import Connection, Response
        calls = []
        def factory(host,timeout):
            calls.append(host);return Connection(Response({}),error=TimeoutError())
        with patch('runtime.openai_api.time.time',return_value=101), self.assertRaises(budget.BudgetError):
            self.controller.run_shadow(task(),connection_factory=factory)
        self.assertEqual(len(calls),1)
        self.assertEqual(self.ledger.snapshot()['slot'],'run')
        self.assertEqual(self.ledger.snapshot()['runs']['run']['calls']['count']['state'],'unresolved')

    def test_config_change_after_selection_cannot_borrow_new_consent(self):
        from unittest.mock import patch
        from tests.test_openai_api import Connection,Response
        original=self.controller.evaluate
        def changed(item):
            result=original(item)
            request=copy.deepcopy(self.request)
            request.update(expected_revision=1,expected_org_revision=1,class_name='different')
            self.controller.configure(request)
            return result
        sent=[]
        def factory(host,timeout):
            sent.append(host);return Connection(Response(dict(object='response.input_tokens',input_tokens=1200)))
        with patch.object(self.controller,'evaluate',side_effect=changed), patch('runtime.openai_api.time.time',return_value=101), self.assertRaises(budget.BudgetError):
            self.controller.run_shadow(task(),connection_factory=factory)
        self.assertEqual(sent,[])

    def test_proven_unsent_failure_releases_slot_and_zeroes_call_reservation(self):
        from unittest.mock import patch
        def factory(host,timeout): raise OSError('not connected')
        with patch('runtime.openai_api.time.time',return_value=101), self.assertRaises(budget.BudgetError):
            self.controller.run_shadow(task(),connection_factory=factory)
        state=self.ledger.snapshot()
        self.assertIsNone(state['slot'])
        self.assertEqual(state['runs']['run']['calls']['count']['state'],'rejected-before-send')

    def test_disable_during_connection_preparation_prevents_request(self):
        from unittest.mock import patch
        from tests.test_openai_api import Connection,Response
        connection=Connection(Response(dict(object='response.input_tokens',input_tokens=1200)))
        def factory(host,timeout):
            self.controller.disable(1)
            return connection
        with patch('runtime.openai_api.time.time',return_value=101),self.assertRaises(budget.BudgetError):
            self.controller.run_shadow(task(),connection_factory=factory)
        self.assertEqual(connection.requests,[])
        self.assertTrue(connection.closed)
        self.assertIsNone(self.ledger.snapshot()['slot'])

    def test_reset_crossing_after_count_cannot_send_generation(self):
        from unittest.mock import patch
        from tests.test_openai_api import Connection,Response
        clock=[101];self.controller.clock=lambda:clock[0]
        current=task();current['native']['windows'][0]['reset_at']=102
        sent=[]
        def factory(host,timeout):
            connection=Connection(Response(dict(object='response.input_tokens',input_tokens=1200)))
            original=connection.getresponse
            def received():
                clock[0]=103
                return original()
            connection.getresponse=received
            sent.append(connection)
            return connection
        with patch('runtime.openai_api.time.time',return_value=101),self.assertRaises(budget.BudgetError):
            self.controller.run_shadow(current,connection_factory=factory)
        self.assertEqual(len(sent),1)
        self.assertIsNone(self.ledger.snapshot()['slot'])

    def test_native_allowance_overrun_pauses_subsequent_automatic_work(self):
        self.ledger.begin('org','task','run','packet',0,1,101,native())
        self.ledger.close_run('run')
        later=native(remaining=60);later['windows'][0]['observed_at']=110
        with self.assertRaisesRegex(budget.BudgetError,'native_requalification_required'):
            self.ledger.release_native('account','task',later,111)
        self.assertEqual(self.ledger.snapshot()['native_paused']['account'],'native_allowance_overrun')
        with self.assertRaises(budget.BudgetError):
            self.ledger.begin('org','other','next','packet',0,1,112,native('other',remaining=60))

    def test_handoff_keeps_pending_api_reservations_and_is_idempotent(self):
        self.ledger.begin('org','task','run','packet',10,1,101,native())
        self.ledger.dispatch('run','count',1,101);self.ledger.uncertain('run','count')
        before=self.ledger.headroom('org')
        first=self.controller.request_handoff(task(),'insufficient_headroom')
        second=self.controller.request_handoff(task(),'expiry_or_cycle_boundary')
        self.assertEqual(first['handoff_id'],second['handoff_id'])
        self.assertEqual(first['state'],'ready')
        self.assertTrue(first['pending_api_accounting'])
        self.assertTrue(first['requires_native_review'])
        self.assertFalse(first['accepted'])
        self.assertEqual(self.ledger.headroom('org'),before)
        self.assertEqual(self.ledger.snapshot()['slot'],'run')
        claimed=self.controller.claim_handoff('task','native-child')
        self.assertEqual(claimed['state'],'claimed')
        self.assertTrue(claimed['new_claim'])
        self.assertFalse(self.controller.claim_handoff('task','native-child')['new_claim'])
        with self.assertRaises(budget.BudgetError): self.controller.claim_handoff('task','duplicate-child')

    def test_handoff_preserves_api_only_and_native_capacity_limits(self):
        blocked=self.controller.request_handoff(task(api_only=True),'insufficient_headroom')
        self.assertEqual(blocked['state'],'user_choice_required')
        with self.assertRaises(budget.BudgetError): self.controller.claim_handoff('task','child')
        limited=self.controller.request_handoff(task(task_id='limited',run_id='limited',native=native('limited',remaining=25)), 'insufficient_headroom')
        self.assertEqual(limited['state'],'waiting_for_native_capacity')
        with self.assertRaises(budget.BudgetError): self.controller.claim_handoff('limited','child')

    def test_handoff_rechecks_capacity_before_claim(self):
        self.controller.request_handoff(task(),'insufficient_headroom')
        self.controller.clock=lambda:1001
        with self.assertRaises(budget.BudgetError): self.controller.claim_handoff('task','child')

    def test_funding_stop_recommends_native_handoff_without_sending(self):
        self.ledger.observe('org',160,102)
        self.controller.clock=lambda:103
        decision=self.controller.evaluate(task())
        self.assertEqual(decision['decision'],'paused')
        self.assertTrue(decision['handoff_recommended'])
        self.assertEqual(self.ledger.snapshot()['runs'],{})

    def test_unclaimed_handoff_refreshes_choices_and_recovers_capacity(self):
        ready=self.controller.request_handoff(task(),'insufficient_headroom')
        for change in (dict(api_only=True),dict(provider='openrouter'),dict(reviewer_available=False)):
            with self.subTest(change=change):
                paused=self.controller.request_handoff(task(**change),'insufficient_headroom')
                self.assertNotEqual(paused['state'],'ready')
                with self.assertRaises(budget.BudgetError): self.controller.claim_handoff('task','attempt')
                recovered=self.controller.request_handoff(task(),'insufficient_headroom')
                self.assertEqual(recovered['state'],'ready')
                self.assertEqual(recovered['handoff_id'],ready['handoff_id'])

    def test_handoff_claim_keeps_native_reserve_until_fresh_post_claim_evidence(self):
        self.ledger.begin('org','task','run','packet',0,1,101,native())
        self.ledger.close_run('run')
        self.controller.request_handoff(task(),'insufficient_headroom')
        self.controller.clock=lambda:200
        self.controller.claim_handoff('task','native-attempt')
        stale=native();stale['windows'][0]['observed_at']=150
        with self.assertRaisesRegex(budget.BudgetError,'native_observation_precedes_work'):
            self.ledger.release_native('account','task',stale,201)

    def test_shared_organization_policy_change_invalidates_other_scope(self):
        other = routing.Controller(self.ledger, 'other-scope', clock=lambda:101)
        req = copy.deepcopy(self.request);req['expected_org_revision']=1
        other.configure(req)
        self.assertEqual(self.controller.evaluate(task())['reason'], 'policy_revision_changed')


if __name__ == '__main__': unittest.main()
