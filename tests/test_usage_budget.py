"""Offline spending invariants; all state is disposable and no network is used."""
import multiprocessing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime import usage_budget as budget


def competing(path, identity, name, queue):
    try:
        with budget.Ledger(path, identity) as ledger:
            ledger.begin('org', name, name, 'packet', 10, 1, 101, native(name))
        queue.put('accepted')
    except budget.BudgetError:
        queue.put('blocked')


def competing_live(path, identity, queue):
    try:
        with budget.Ledger(path, identity) as ledger:
            ledger.begin('org', 'task', 'same-run', 'packet', 10, 1, 101, native(),
                         live_gate=lambda data, now: dict(pin='a' * 64, maximum=20))
        queue.put('accepted')
    except budget.BudgetError as error:
        queue.put(str(error))


def native(task='task', remaining=90):
    return {'account': 'account', 'task': task, 'windows': [
        {'id': 'weekly:1', 'remaining_pp': remaining, 'resolution_pp': 1,
         'allowance_pp': 10, 'observed_at': 100, 'reset_at': 10000}]}


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'private' / 'organizations.sqlite3'
        self.identity = budget.initialize(self.path)
        self.ledger = budget.Ledger(self.path, self.identity)
        self.configure()

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def configure(self, **updates):
        policy = dict(cycle='cycle1', start=0, end=10000, expiry=10000,
                      stop_at=9000, ceiling='custom', amount=500,
                      grant_amount=800, pilot_limit=500, task_limit=200)
        policy.update(updates)
        return self.ledger.configure('org', policy, 0)

    def observe(self, amount=800, at=100):
        self.ledger.observe('org', amount, at)

    def begin(self, run='run', task='task', maximum=10, now=101, evidence=None, **options):
        return self.ledger.begin('org', task, run, 'packet', maximum, 1, now,
                                 native(task) if evidence is None else evidence, **options)

    def count_done(self, run='run', cost=1):
        self.ledger.dispatch(run, 'count', 1, 102)
        self.ledger.complete(run, 'count', cost)

    def test_quota_records_do_not_block_api_accounting_or_dispatch(self):
        self.observe()
        with self.ledger.transaction() as data:
            data['native_paused'] = {'account': 'native_allowance_overrun'}
        for index, windows in enumerate((native(remaining=15)['windows'], native(remaining=0)['windows'], [])):
            task = 'quota-' + str(index)
            self.begin(task, task, evidence=dict(account='account', task=task, windows=windows))
            self.count_done(task)
            self.ledger.close_run(task)
        saved = self.ledger.snapshot()
        self.assertEqual(len(saved['runs']), 3)
        self.assertEqual(saved['native_paused'], {'account': 'native_allowance_overrun'})
        with self.assertRaisesRegex(budget.BudgetError, 'insufficient_headroom'):
            self.begin('unfunded', 'unfunded', maximum=1000, evidence=dict(account='account', task='unfunded', windows=[]))

    def test_initialization_never_overwrites_and_identity_is_required(self):
        with self.assertRaises(budget.BudgetError): budget.initialize(self.path)
        with self.assertRaises(budget.BudgetError): budget.Ledger(self.path, 'wrong')
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_missing_observation_blocks_without_claiming_slot(self):
        with self.assertRaises(budget.BudgetError): self.begin()
        self.assertIsNone(self.ledger.snapshot()['slot'])

    def test_invalid_optional_diagnostic_never_prevents_unresolved_accounting(self):
        self.observe()
        # Bind only the temporary ledger's test routing scope.
        with self.ledger.transaction() as data:
            data['routing'] = {'scope': dict(revision=1, disabled=False, qualification_revision=None)}
        self.begin(consent=dict(scope='scope', revision=1, qualification_revision=None))
        self.ledger.dispatch('run', 'count', 1, 102)
        self.ledger.uncertain('run', 'count', diagnostic={'private header': 'secret value'})
        before = self.ledger.snapshot()
        call = before['runs']['run']['calls']['count']
        self.assertEqual(call['state'], 'unresolved')
        self.assertIsNone(call['cost'])
        self.assertNotIn('diagnostic', call)
        self.assertEqual(before['slot'], 'run')
        # Old or corrupt optional metadata is also checked before display.
        with self.ledger.transaction() as data:
            data['runs']['run']['calls']['count']['diagnostic'] = {'private header': 'secret value'}
        before = self.ledger.snapshot()
        self.assertNotIn('diagnostic', self.ledger.reconcile(scope='scope')['pending'])
        self.assertEqual(self.ledger.snapshot(), before)

    def test_optional_transport_diagnostic_rejects_free_text_and_invalid_scalars(self):
        diagnostic = dict(version=1, phase='count', stage='response_headers',
                          exception_category='remote_disconnected', deadline_fired=False,
                          elapsed_ms=12, remaining_ms=987, request_id='req_synthetic',
                          response_id=None, http_status=200)
        self.assertEqual(budget.transport_diagnostic(diagnostic), diagnostic)
        for change in [dict(version=True), dict(version=2), dict(phase='private phase'),
                       dict(stage='private stage'), dict(exception_category='PrivateExceptionName'),
                       dict(deadline_fired=1), dict(elapsed_ms=True), dict(elapsed_ms=-1),
                       dict(elapsed_ms=300001), dict(remaining_ms=float('nan')),
                       dict(remaining_ms=-300001), dict(request_id='private header detail'),
                       dict(response_id='private response detail'), dict(http_status=True),
                       dict(http_status=600), {'private header': 'secret value'}]:
            with self.subTest(change=change):
                self.assertIsNone(budget.transport_diagnostic(diagnostic | change))
        self.assertIsNone(budget.transport_diagnostic(None))

    def test_optional_diagnostic_capacity_never_blocks_unresolved_transition(self):
        self.observe()
        self.begin()
        self.ledger.dispatch('run', 'count', 1, 102)
        diagnostic = dict(version=1, phase='count', stage='response_headers',
                          exception_category='remote_disconnected', deadline_fired=False,
                          elapsed_ms=12, remaining_ms=987, request_id=None,
                          response_id=None, http_status=None)
        capacity = len(json.dumps(self.ledger.snapshot(), separators=(',', ':'))) + 16
        with patch.object(budget, 'MAX_RECORD', capacity):
            self.ledger.uncertain('run', 'count', diagnostic=diagnostic)
        state = self.ledger.snapshot()
        call = state['runs']['run']['calls']['count']
        self.assertEqual(call['state'], 'unresolved')
        self.assertIsNone(call['cost'])
        self.assertNotIn('diagnostic', call)
        self.assertEqual(state['slot'], 'run')

    def test_count_and_generation_settle_separately_without_retiring_credit_cost(self):
        self.observe()
        self.begin()
        self.count_done()
        self.ledger.reserve_generation('run', 'generation-packet', 30, 1, 103)
        self.ledger.dispatch('run', 'generation', 1, 104)
        self.ledger.complete('run', 'generation', 12)
        state = self.ledger.snapshot()
        self.assertIsNone(state['slot'])
        self.assertEqual(self.ledger.headroom('org'), 487)
        self.assertEqual(len(state['runs']['run']['calls']), 2)
        self.ledger.observe('org', 787, 110)
        self.assertEqual(self.ledger.headroom('org'), 487)
        self.assertEqual(self.ledger.credit_headroom('org'), 614)
        self.assertEqual(len(state['native']), 1)  # Task identity remains for integration/review.

    def test_unknown_count_blocks_generation_and_other_sessions_after_restart(self):
        self.observe(); self.begin(); self.ledger.dispatch('run', 'count', 1, 102)
        self.ledger.uncertain('run', 'count')
        self.ledger.close(); self.ledger = budget.Ledger(self.path, self.identity)
        with self.assertRaises(budget.BudgetError): self.ledger.reserve_generation('run', 'g', 10, 1, 103)
        with self.assertRaises(budget.BudgetError): self.begin('other', 'other')
        self.assertEqual(self.ledger.snapshot()['slot'], 'run')

    def test_generation_denied_preserves_count_and_close_releases_slot(self):
        self.observe(); self.begin(); self.count_done()
        with self.assertRaises(budget.BudgetError): self.ledger.reserve_generation('run', 'g', 201, 1, 103)
        self.ledger.close_run('run')
        self.assertIsNone(self.ledger.snapshot()['slot'])
        self.assertEqual(self.ledger.headroom('org'), 499)
        with self.assertRaises(budget.BudgetError): self.ledger.dispatch('run', 'count', 1, 104)

    def test_crash_between_calls_never_replays_or_auto_continues(self):
        self.observe(); self.begin(); self.count_done()
        self.ledger.close(); self.ledger = budget.Ledger(self.path, self.identity)
        before = self.ledger.snapshot()
        self.begin()  # Same ID returns record only.
        self.assertEqual(self.ledger.snapshot(), before)
        self.ledger.close_run('run')
        with self.assertRaises(budget.BudgetError): self.ledger.reserve_generation('run', 'g', 20, 1, 103)

    def test_policy_change_revokes_prepared_dispatch_without_erasing_cost(self):
        self.observe(); self.begin()
        policy = self.ledger.snapshot()['organizations']['org']['policy'].copy()
        policy['amount'] = 5
        self.ledger.configure('org', policy, 1)
        with self.assertRaises(budget.BudgetError): self.ledger.dispatch('run', 'count', 1, 102)
        self.assertEqual(self.ledger.headroom('org'), 0)

    def test_unchanged_validated_policy_preserves_revision_and_all_accounting(self):
        self.observe(); self.begin()
        before = self.ledger.snapshot()
        policy = before['organizations']['org']['policy'].copy()
        self.assertEqual(self.ledger.configure('org', policy, 1), 1)
        self.assertEqual(self.ledger.snapshot(), before)
        with self.assertRaisesRegex(budget.BudgetError, 'policy_revision_changed'):
            self.ledger.configure('org', policy, 0)
        with self.assertRaisesRegex(budget.BudgetError, 'invalid_integer'):
            self.ledger.configure('org', dict(policy, amount=True), 1)
        self.ledger.dispatch('run', 'count', 1, 102)

    def test_same_task_correction_reuses_identity_but_retains_call_cost(self):
        self.observe(); self.begin(); self.count_done(); self.ledger.close_run('run')
        self.begin('correction')
        self.assertEqual(len(self.ledger.snapshot()['native']), 1)
        self.assertEqual(self.ledger.headroom('org'), 489)

    def test_native_completion_requires_stopped_task_and_preserves_records(self):
        self.observe(); self.begin()
        with self.assertRaises(budget.BudgetError): self.ledger.release_native('account', 'task', native(), 101)
        self.ledger.close_run('run')
        before = self.ledger.snapshot()
        self.ledger.release_native('account', 'task', native(), 1001)
        after = self.ledger.snapshot()
        self.assertEqual(after['native'], before['native'])
        self.assertEqual(after['runs'], before['runs'])
        self.assertIn('["account", "task"]', after['finished_native'])

    def test_lowest_balance_is_monotonic_and_refresh_never_clears_deductions(self):
        self.observe(); self.begin(); self.count_done(); self.ledger.close_run('run')
        self.ledger.observe('org', 50, 110)
        self.assertEqual(self.ledger.headroom('org'), 0)
        self.ledger.observe('org', 1000, 120)
        self.assertEqual(self.ledger.headroom('org'), 0)
        self.assertEqual(self.ledger.reconcile(), {'state': 'manual_recovery_required'})

    def test_expiry_freshness_and_future_observations_block(self):
        self.observe()
        for now in (99, 1001, 9000, 10000):
            with self.assertRaises(budget.BudgetError): self.begin(now=now)

    def test_unexpected_actual_cost_keeps_maximum_and_blocks_org(self):
        self.observe(); self.begin(); self.ledger.dispatch('run', 'count', 1, 102)
        with self.assertRaises(budget.BudgetError): self.ledger.complete('run', 'count', 11)
        self.assertEqual(self.ledger.snapshot()['runs']['run']['calls']['count']['maximum'], 10)
        with self.assertRaises(budget.BudgetError): self.begin('other', 'other')

    def test_bool_and_negative_money_rejected(self):
        self.observe()
        for value in (True, -1, 1.2, 2**63):
            with self.assertRaises(budget.BudgetError): self.begin(maximum=value)

    def test_two_processes_share_single_slot(self):
        self.observe()
        ctx = multiprocessing.get_context('spawn'); queue = ctx.Queue()
        processes = [ctx.Process(target=competing, args=(self.path, self.identity, name, queue)) for name in ('a','b')]
        for process in processes: process.start()
        for process in processes: process.join(10); self.assertEqual(process.exitcode, 0)
        self.assertEqual(sorted(queue.get(timeout=2) for _ in processes), ['accepted', 'blocked'])
        queue.close(); queue.join_thread()

    def test_live_gate_caps_retained_cost_and_reservations_across_runs(self):
        self.observe(); self.begin('old'); self.count_done('old', cost=4); self.ledger.close_run('old')
        gate = lambda data, now: dict(pin='a' * 64, maximum=13)
        with self.assertRaisesRegex(budget.BudgetError, 'live_cap_exceeded'):
            self.begin(maximum=10, live_gate=gate)
        self.begin(maximum=9, live_gate=gate)
        self.ledger.dispatch('run', 'count', 1, 102, live_gate=gate)
        self.ledger.complete('run', 'count', 2)
        with self.assertRaisesRegex(budget.BudgetError, 'live_cap_exceeded'):
            self.ledger.reserve_generation('run', 'g', 8, 1, 103, live_gate=gate)
        self.ledger.reserve_generation('run', 'g', 7, 1, 103, live_gate=gate)
        self.ledger.dispatch('run', 'generation', 1, 104, live_gate=gate)
        self.assertEqual(self.ledger.snapshot()['runs']['run']['live_admission'],
                         dict(pin='a' * 64, maximum=13))

    def test_live_gate_credit_staging_rolls_back_on_failure(self):
        def gate(data, now):
            data['organizations']['org'].update(balance=300, floor=60, observed_at=now)
            return dict(pin='a' * 64, maximum=20)

        def reject(data, now):
            gate(data, now)
            raise budget.BudgetError('evidence_changed')

        before = self.ledger.snapshot()
        with self.assertRaisesRegex(budget.BudgetError, 'evidence_changed'):
            self.begin(live_gate=reject)
        self.assertEqual(self.ledger.snapshot(), before)
        self.begin(live_gate=gate)
        before = self.ledger.snapshot()
        with self.assertRaisesRegex(budget.BudgetError, 'evidence_changed'):
            self.ledger.dispatch('run', 'count', 1, 102, live_gate=reject)
        self.assertEqual(self.ledger.snapshot(), before)

    def test_live_gate_requires_same_pin_and_cap_at_each_phase(self):
        self.observe()
        gate = lambda data, now: dict(pin='a' * 64, maximum=20)
        self.begin(live_gate=gate)
        for phase in ('dispatch', 'reserve'):
            before = self.ledger.snapshot()
            for changed in (dict(pin='b' * 64, maximum=20), dict(pin='a' * 64, maximum=21)):
                with self.assertRaisesRegex(budget.BudgetError, 'live_admission_mismatch'):
                    if phase == 'dispatch':
                        self.ledger.dispatch('run', 'count', 1, 102, live_gate=lambda *_: changed)
                    else:
                        self.ledger.reserve_generation('run', 'g', 5, 1, 103, live_gate=lambda *_: changed)
                self.assertEqual(self.ledger.snapshot(), before)
            if phase == 'dispatch':
                self.ledger.dispatch('run', 'count', 1, 102, live_gate=gate)
                self.ledger.complete('run', 'count', 1)

    def test_shadow_and_live_runs_cannot_reuse_each_others_admission(self):
        self.observe()
        gate = lambda data, now: dict(pin='a' * 64, maximum=20)
        self.begin('shadow')
        with self.assertRaisesRegex(budget.BudgetError, 'live_run_id_already_used'):
            self.begin('shadow', live_gate=gate)
        with self.assertRaisesRegex(budget.BudgetError, 'live_admission_mismatch'):
            self.ledger.dispatch('shadow', 'count', 1, 102, live_gate=gate)
        self.count_done('shadow')
        with self.assertRaisesRegex(budget.BudgetError, 'live_admission_mismatch'):
            self.ledger.reserve_generation('shadow', 'g', 5, 1, 103, live_gate=gate)
        self.ledger.close_run('shadow')
        self.begin(live_gate=gate)
        with self.assertRaisesRegex(budget.BudgetError, 'live_run_id_already_used'):
            self.begin()
        with self.assertRaisesRegex(budget.BudgetError, 'live_admission_mismatch'):
            self.ledger.dispatch('run', 'count', 1, 102)
        self.ledger.dispatch('run', 'count', 1, 102, live_gate=gate)
        self.ledger.complete('run', 'count', 1)
        with self.assertRaisesRegex(budget.BudgetError, 'live_admission_mismatch'):
            self.ledger.reserve_generation('run', 'g', 5, 1, 103)

    def test_two_processes_cannot_begin_same_live_id(self):
        self.observe()
        ctx = multiprocessing.get_context('spawn'); queue = ctx.Queue()
        processes = [ctx.Process(target=competing_live, args=(self.path, self.identity, queue)) for _ in range(2)]
        for process in processes: process.start()
        for process in processes: process.join(10); self.assertEqual(process.exitcode, 0)
        self.assertEqual(sorted(queue.get(timeout=2) for _ in processes), ['accepted', 'live_run_id_already_used'])
        queue.close(); queue.join_thread()

    def test_all_ceiling_choices_and_no_accounting_reset_on_mode_change(self):
        self.observe(); self.begin(); self.count_done(); self.ledger.close_run('run')
        policy = self.ledger.snapshot()['organizations']['org']['policy'].copy()
        policy.update(ceiling='none', amount=None)
        self.ledger.configure('org', policy, 1)
        self.assertEqual(self.ledger.headroom('org'), 499)  # Pilot cap still applies.
        policy.update(ceiling='subscription_benefit', grant_amount=20)
        self.ledger.configure('org', policy, 2)
        self.assertEqual(self.ledger.headroom('org'), 19)
        with self.assertRaises(budget.BudgetError): self.ledger.configure('org', policy, 2)

    def test_optional_caps_are_independent_and_benefit_ceiling_still_applies(self):
        self.observe()
        policy = dict(self.ledger.snapshot()['organizations']['org']['policy'],
                      ceiling='subscription_benefit', amount=None, grant_amount=400)
        for revision, caps, maximum in ((1, dict(pilot_limit=None, task_limit=200), 201),
                                        (2, dict(pilot_limit=300, task_limit=None), 301)):
            self.ledger.configure('org', dict(policy, **caps), revision)
            with self.subTest(caps=caps), self.assertRaisesRegex(budget.BudgetError, 'insufficient_headroom'):
                self.ledger.begin('org', 'task', 'run', 'packet', maximum, revision + 1, 101, native())

        self.ledger.configure('org', dict(policy, pilot_limit=None, task_limit=None), 3)
        self.ledger.begin('org', 'task', 'run', 'packet', 350, 4, 101, native())
        self.ledger.dispatch('run', 'count', 4, 102)
        self.ledger.complete('run', 'count', 350)
        self.ledger.close_run('run')
        self.assertEqual(self.ledger.headroom('org'), 50)
        with self.assertRaisesRegex(budget.BudgetError, 'insufficient_headroom'):
            self.ledger.begin('org', 'task', 'next', 'packet', 51, 4, 103, native())

    def test_lower_grant_balance_revokes_a_reservation_with_both_optional_caps_omitted(self):
        self.observe()
        policy = dict(self.ledger.snapshot()['organizations']['org']['policy'], ceiling='subscription_benefit',
                      amount=None, pilot_limit=None, task_limit=None)
        self.ledger.configure('org', policy, 1)
        self.ledger.begin('org', 'task', 'run', 'packet', 300, 2, 101, native())
        self.ledger.observe('org', 459, 102)
        with self.assertRaisesRegex(budget.BudgetError, 'credit_changed'):
            self.ledger.dispatch('run', 'count', 2, 103)
        call = self.ledger.snapshot()['runs']['run']['calls']['count']
        self.assertEqual((call['state'], call['maximum']), ('reserved', 300))

    def test_new_cycle_retains_prior_cost_and_unknown_exposure(self):
        self.observe(); self.begin(); self.count_done(); self.ledger.close_run('run')
        policy = self.ledger.snapshot()['organizations']['org']['policy'].copy()
        policy.update(cycle='cycle2', start=10000, end=20000, expiry=20000, stop_at=19000)
        self.ledger.configure('org', policy, 1)
        self.assertEqual(self.ledger.snapshot()['runs']['run']['calls']['count']['cycle'], 'cycle1')
        self.assertEqual(self.ledger.credit_headroom('org'), 639)
        self.assertEqual(self.ledger.headroom('org'), 499)  # Pilot accounting does not reset.

    def test_refresh_can_revoke_an_existing_reservation_before_dispatch(self):
        self.observe(); self.begin()
        self.ledger.observe('org', 160, 102)
        with self.assertRaises(budget.BudgetError): self.ledger.dispatch('run', 'count', 1, 103)

    def test_missing_replaced_and_permissive_ledger_fail_closed(self):
        self.ledger.close()
        replacement = self.path.with_suffix('.old')
        self.path.rename(replacement)
        with self.assertRaises(budget.BudgetError): budget.Ledger(self.path, self.identity)
        new_identity = budget.initialize(self.path)
        with self.assertRaises(budget.BudgetError): budget.Ledger(self.path, self.identity)
        self.path.chmod(0o644)
        with self.assertRaises(budget.BudgetError): budget.Ledger(self.path, new_identity)
        self.path.chmod(0o600)
        self.ledger = budget.Ledger(self.path, new_identity)

    def test_correction_cannot_continue_after_task_completion(self):
        self.observe(); self.begin(); self.count_done(); self.ledger.close_run('run')
        evidence = native(); evidence['windows'][0]['observed_at'] = 105
        self.ledger.release_native('account', 'task', evidence, 106)
        with self.assertRaises(budget.BudgetError): self.begin('correction')

    def test_symlink_database_rejected(self):
        alias = self.path.parent / 'alias'; alias.symlink_to(self.path)
        with self.assertRaises(budget.BudgetError): budget.Ledger(alias, self.identity)


if __name__ == '__main__': unittest.main()
