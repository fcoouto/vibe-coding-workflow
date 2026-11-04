"""Foreground Codex admission with synthetic receipts and a disposable ledger."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from runtime import usage_admission, usage_budget, usage_routing, usage_settings, worker_visibility
from runtime.usage_budget import BudgetError
from tests.test_openai_api import Connection, Response, completed
from tests.test_smart_balance import POLICY, qualification
from tests.test_usage_routing import PACKET, PROFILE


class CodexUsageHostTests(unittest.TestCase):
    def setUp(self):
        from runtime import usage_codex_host
        self.host = usage_codex_host
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        path = self.root / 'private' / 'ledger'
        self.ledger = usage_budget.Ledger(path, usage_budget.initialize(path))
        self.addCleanup(self.ledger.close)
        self.now = 101
        self.control = usage_routing.Controller(self.ledger, 'scope', root=self.root, clock=lambda: self.now)
        self.binding = dict(organization='org', project='project', credential_ref='vcw_' + '1' * 32,
                            storage_kind='macos_keychain')
        self.reviewer = self.host.Reviewer(coordinator='coordinator', identity='independent-reviewer')
        self.limits = dict(accountId='account', ordinaryUsageAllowed=True, rateLimitsByLimitId={
            'codex': dict(limitId='codex', spendControlReached=False, secondary=None,
                          primary=dict(usedPercent=48.1, windowDurationMins=10080, resetsAt=900))})
        self.grant = usage_admission.Grant('org', 'project', 800, POLICY['expiry'], 105,
                                           'platform-credit-grants', 'benefit')
        self.price = self.host.Price(profile_digest=usage_routing.profile_digest(PROFILE),
                                     observed_at=PROFILE['verified_at'], valid_until=PROFILE['valid_until'])

        @contextmanager
        def local_controller(*args, **kwargs):
            yield self.control

        for target, attribute, options in (
            (usage_settings, 'controller', dict(side_effect=local_controller)),
            (self.host, 'package_digest', dict(return_value='a' * 64)),
            (self.host.time, 'time', dict(side_effect=lambda: self.now)),
        ):
            patcher = patch.object(target, attribute, **options)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(usage_routing, '_run_live', return_value={'accepted': False})
        self.dispatch = patcher.start()
        self.addCleanup(patcher.stop)

    def configure(self, mode='manual', *, enabled=True, profile=PROFILE):
        self.control.configure(dict(version=2, expected_revision=0, expected_org_revision=0,
                                    binding=self.binding, policy=POLICY, profile=profile,
                                    class_name='investigation', mode=mode))
        if mode == 'smart':
            # Install the stored qualification fixture without making any host claims.
            with self.ledger.transaction() as data:
                config = data['routing']['scope']
                config['qualification'] = dict(qualification(), native_allowance_pp=7)
                config['qualification_revision'] = 1
        if enabled:
            self.control.enable(1)

    def proposal(self, **changes):
        return dict(task_id='task', class_name='investigation', packet=dict(PACKET), provider='openai-api',
                    local_preferred=False, api_only=False, snapshots=[],
                    visibility=dict(version=1, role='Scout', specialty='Investigate')) | changes

    def receipt(self, text='Prepare the bounded work.', *, turn='prepare', status='inProgress',
                started=101, role='userMessage', host='desktop', item=None):
        return dict(thread=dict(kind='codex', id=self.reviewer.coordinator, hostId=host, cwd=str(self.root)),
                    turns=[dict(id=turn, status=status, startedAt=started, items=[
                        dict(type=role, id=item or 'user-' + turn, content=[dict(type='text', text=text)])])])

    def freeze(self, *proposals, **overrides):
        options = dict(thread_snapshot=self.receipt(), native_limits=self.limits, reviewer=self.reviewer,
                       maximum_usd_micros=100, expires_at=200) | overrides
        return self.host.freeze(self.root, list(proposals) or [self.proposal()], **options)

    def execute(self, plan, proposal=None, *, when=106, **overrides):
        self.now = when
        options = dict(thread_snapshot=self.receipt(self.host.approval_text(plan), turn='approval', started=105),
                       reviewer=self.reviewer, native_limits=self.limits, native_observed_at=105,
                       grant=self.grant, price=self.price) | overrides
        return self.host.execute(plan, proposal if proposal is not None else self.proposal(), **options)

    def test_default_off_and_non_explicit_manual_proposals_cannot_freeze(self):
        self.configure(enabled=False)
        before = self.ledger.snapshot()
        with self.assertRaises(BudgetError):
            self.freeze()
        self.assertEqual(self.control.status()['mode'], 'off')
        self.assertEqual(self.ledger.snapshot(), before)
        self.control.enable(1)
        with self.assertRaises(BudgetError):
            self.freeze(self.proposal(provider='auto'))
        with self.assertRaises(BudgetError):
            self.freeze(self.proposal(), self.proposal(task_id='second'))
        self.dispatch.assert_not_called()

    def test_role_metadata_does_not_gate_or_change_dispatch_identity(self):
        self.configure()
        proposal = self.proposal()
        missing = {key: value for key, value in proposal.items() if key != 'visibility'}
        plan = self.freeze(proposal)
        variants = (missing, self.proposal(visibility={'role': 'Default'}), proposal)
        for item in variants:
            self.assertEqual(self.freeze(item), plan)
        for item in variants:
            self.execute(plan, item)
        self.assertEqual(len({call.args[1]['run_id'] for call in self.dispatch.call_args_list}), 1)

    def test_manual_exact_native_approval_binds_task_and_stable_attempt(self):
        self.configure()
        proposal = self.proposal()
        plan = self.freeze(proposal)
        receipt = self.receipt(self.host.approval_text(plan) + '\n', turn='approval', started=105)
        self.assertEqual(self.execute(plan, proposal, thread_snapshot=receipt), {'accepted': False})
        cwd, task, evidence = self.dispatch.call_args.args
        self.assertEqual(Path(cwd), self.root)
        self.assertEqual({key: task[key] for key in proposal if key != 'visibility'},
                         {key: value for key, value in proposal.items() if key != 'visibility'})
        self.assertNotIn('visibility', task)
        self.assertTrue(task['reviewer_available'])
        self.assertEqual(task['native']['account'], 'account')
        self.assertEqual(task['native']['task'], 'task')
        self.assertEqual(task['native']['windows'][0]['allowance_pp'], 5)
        self.assertEqual(evidence.task_digest, usage_admission.digest(task))
        self.assertEqual((evidence.coordinator, evidence.reviewer), ('coordinator', 'independent-reviewer'))
        self.assertEqual(evidence.maximum_usd_micros, 100)
        self.assertEqual(evidence.grant, self.grant)
        self.execute(plan, proposal, thread_snapshot=receipt)
        _, repeated, repeat_evidence = self.dispatch.call_args.args
        self.assertEqual(repeated['run_id'], task['run_id'])
        self.assertEqual(repeat_evidence.approval_id, evidence.approval_id)

    def test_changed_proposal_receipt_reviewer_price_or_balance_denies_before_dispatch(self):
        self.configure()
        plan = self.freeze()
        token = self.host.approval_text(plan)
        changed_packet = self.proposal(packet=dict(PACKET, text='Changed after freeze'))
        for changes in (
            dict(proposal=changed_packet),
            dict(thread_snapshot=self.receipt(token, turn='approval', started=105, role='agentMessage')),
            dict(thread_snapshot=self.receipt(token, turn='approval', started=105, host='other-host')),
            dict(thread_snapshot=self.receipt(token + ' ', turn='approval', started=105)),
            dict(reviewer=self.host.Reviewer('coordinator', 'different-reviewer')),
            dict(grant=replace(self.grant, balance=0)),
            dict(price=replace(self.price, profile_digest='b' * 64)),
        ):
            with self.subTest(changes=changes), self.assertRaises(BudgetError):
                self.execute(plan, **changes)
        self.dispatch.assert_not_called()

    def test_stale_configuration_rejected_even_after_mode_is_enabled_again(self):
        self.configure()
        plan = self.freeze()
        self.control.disable(2)
        self.control.enable(3)
        self.assertEqual(self.control.status()['mode'], 'manual')
        with self.assertRaises(BudgetError):
            self.execute(plan)
        self.dispatch.assert_not_called()

    def manual_price(self):
        profile = dict(PROFILE, verified_at=101, valid_until=190)
        return self.host.Price(usage_routing.profile_digest(profile), 101, 190)

    def test_one_shot_manual_freezes_off_and_restores_off(self):
        self.configure(enabled=False)
        before = self.ledger.snapshot()
        price = self.manual_price()
        plan = self.freeze(manual_price=price)
        self.assertEqual(self.ledger.snapshot(), before)
        with self.assertRaises(BudgetError):
            self.execute(plan, price=price, thread_snapshot=self.receipt('Preparation only.'))
        self.assertEqual(self.ledger.snapshot(), before)

        def check_temporary(*_):
            self.assertEqual(self.control.status()['mode'], 'manual')
            current = self.control._config(self.ledger.snapshot())
            self.assertEqual(current['revision'], 2)
            self.assertEqual(usage_routing.profile_digest(current['profile']), price.profile_digest)
            with self.assertRaisesRegex(BudgetError, 'manual_test_in_use'):
                self.control.record_qualification(dict(qualification(), profile_digest=price.profile_digest))
            return {'accepted': False}

        self.dispatch.side_effect = check_temporary
        self.assertEqual(self.execute(plan, price=price), {'accepted': False})
        after = self.ledger.snapshot()
        self.assertEqual(self.control.status()['mode'], 'off')
        self.assertEqual(self.control._config(after)['profile'], PROFILE)
        self.assertEqual(self.control.status()['revision'], 3)
        self.assertEqual(after['organizations'], before['organizations'])
        with self.assertRaises(BudgetError):
            self.execute(plan, price=price)
        self.dispatch.assert_called_once()

    def test_one_shot_manual_restores_off_after_enable_commit_error(self):
        self.configure(enabled=False)
        price = self.manual_price()
        plan = self.freeze(manual_price=price)
        transaction = self.ledger.transaction
        raised = False

        @contextmanager
        def after_commit(*args, **kwargs):
            nonlocal raised
            with transaction(*args, **kwargs) as data:
                yield data
                active = self.control._config(data)['enabled']
            if active and not raised:
                raised = True
                raise BudgetError('fixture_after_enable_commit')

        with patch.object(self.ledger, 'transaction', side_effect=after_commit):
            with self.assertRaisesRegex(BudgetError, 'fixture_after_enable_commit'):
                self.execute(plan, price=price)
        self.assertEqual(self.control.status()['mode'], 'off')
        self.dispatch.assert_not_called()

    def test_manual_pilot_reuses_approval_only_after_prior_review_lifecycle(self):
        saved_profile = dict(PROFILE, max_output_tokens=64)
        self.configure(enabled=False, profile=saved_profile)
        first = self.proposal()
        second = self.proposal(task_id='second')
        profile = dict(saved_profile, max_output_tokens=PACKET['max_output_tokens'], verified_at=101, valid_until=190)
        price = self.host.Price(usage_routing.profile_digest(profile), 101, 190)
        plan = self.freeze(first, second, manual_price=price, pilot_digest='b' * 64)
        self.assertEqual(self.control.status()['mode'], 'off')
        self.assertEqual(self.control._config(self.ledger.snapshot())['profile'], saved_profile)
        approved = self.receipt(self.host.approval_text(plan), turn='approval', started=105)
        completed_approval = self.receipt(self.host.approval_text(plan), turn='approval', started=105, status='completed')

        def fake_run(_, task, evidence):
            counted = Connection(Response(dict(object='response.input_tokens', input_tokens=1200)))
            reply = completed()
            reply['model'] = PROFILE['model']
            reply['usage'].update(input_tokens=1200, total_tokens=1217)
            connections = iter((counted, Connection(Response(reply))))
            return self.control._run_live(task, evidence, connection_factory=lambda *_: next(connections),
                                          credential_resolver=lambda _: b'synthetic-key')

        self.dispatch.side_effect = fake_run
        with self.assertRaises(BudgetError):
            self.execute(plan, second, price=price, thread_snapshot=approved)
        self.dispatch.assert_not_called()
        result = self.execute(plan, first, price=price, thread_snapshot=approved)
        self.assertFalse(result['accepted'])
        self.assertTrue(result['requires_native_review'])
        self.assertEqual(self.control.status()['mode'], 'off')
        continuation = self.receipt('Continue the approved batch.', turn='later', started=108)
        options = dict(price=price, thread_snapshot=continuation, approval_snapshot=completed_approval,
                       when=109, native_observed_at=108)
        with self.assertRaisesRegex(BudgetError, 'manual_test_in_use'):
            self.execute(plan, second, **options)
        post_review = dict(self.host.native_capacity('account', self.limits, 110, 110, 5), task='task')
        self.ledger.release_native('account', 'task', post_review, 110)
        options.update(when=112, native_observed_at=111)
        with self.assertRaisesRegex(BudgetError, 'manual_pilot_review_required'):
            self.execute(plan, second, **options)
        prior = self.host.PilotReview(self.reviewer.identity, result['run_id'], True)
        self.assertTrue(self.execute(plan, second, prior_review=prior, **options)['requires_native_review'])
        self.assertEqual(self.control.status()['mode'], 'off')
        self.assertEqual(self.control.status()['revision'], 5)
        self.assertEqual(self.control._config(self.ledger.snapshot())['profile'], saved_profile)
        self.assertEqual(len(self.ledger.snapshot()['runs']), 2)
        self.assertEqual(self.dispatch.call_count, 2)

    def test_smart_uses_same_thread_older_approval_and_only_frozen_proposals(self):
        self.configure('smart')
        with self.ledger.transaction() as data:
            data['routing']['scope'].pop('live_consent', None)
        first = self.proposal(provider='auto')
        second = self.proposal(task_id='second', provider='auto')
        plan = self.freeze(first, second)
        approved = self.receipt(self.host.approval_text(plan), turn='approval', started=102, status='completed')
        current = self.receipt('Continue the approved work.', turn='current', started=105)
        options = dict(thread_snapshot=current, approval_snapshot=approved)
        for proposal in (first, second, first):
            self.execute(plan, proposal, **options)
        calls = [call.args for call in self.dispatch.call_args_list]
        self.assertEqual([call[1]['task_id'] for call in calls], ['task', 'second', 'task'])
        self.assertNotEqual(calls[0][1]['run_id'], calls[1][1]['run_id'])
        self.assertEqual(calls[0][1]['run_id'], calls[2][1]['run_id'])
        for _, task, evidence in calls:
            self.assertEqual(task['native']['windows'][0]['allowance_pp'], 7)
            self.assertEqual(evidence.task_digest, usage_admission.digest(task))
            self.assertIsNotNone(evidence.qualification_digest)
            self.assertEqual(evidence.maximum_usd_micros, 100)
        self.dispatch.reset_mock()
        with self.assertRaises(BudgetError):
            self.execute(plan, self.proposal(task_id='outside', provider='auto'), **options)
        wrong_host = dict(approved, thread=dict(approved['thread'], hostId='other-host'))
        with self.assertRaises(BudgetError):
            self.execute(plan, first, thread_snapshot=current, approval_snapshot=wrong_host)
        self.dispatch.assert_not_called()

    def test_standing_smart_first_task_uses_saved_consent_without_benchmark_or_approval(self):
        self.configure('smart')
        with self.ledger.transaction() as data:
            config = data['routing']['scope']
            config.update(qualification=None, qualification_revision=0, live_consent=True)
        proposal = self.proposal(provider='auto')
        first_plan = self.freeze(proposal, standing_consent=True)
        self.execute(first_plan, proposal, thread_snapshot=self.receipt('Investigate the issue.', started=105))
        _, task, evidence = self.dispatch.call_args.args
        self.assertEqual(task['native']['windows'][0]['allowance_pp'], 5)
        self.assertIsNone(evidence.qualification_digest)
        self.now = 107
        second_plan = self.freeze(proposal, standing_consent=True,
                                  thread_snapshot=self.receipt('Continue.', started=107))
        self.execute(second_plan, proposal, when=108,
                     thread_snapshot=self.receipt('Continue.', started=107))
        self.assertEqual(self.dispatch.call_args.args[1]['run_id'], task['run_id'])

    def test_standing_smart_rejects_old_consent_and_repository_snapshots(self):
        self.configure('smart')
        proposal = self.proposal(provider='auto')
        with self.ledger.transaction() as data:
            data['routing']['scope'].pop('live_consent', None)
        with self.assertRaisesRegex(BudgetError, 'standing_consent_required'):
            self.freeze(proposal, standing_consent=True)
        self.control.enable(2)
        source = self.root / 'source.py'
        source.write_bytes(b'private source')
        snapshot = dict(path=str(source), sha256='a' * 64)
        with self.assertRaisesRegex(BudgetError, 'standing_source_scope_exceeded'):
            self.freeze(dict(proposal, snapshots=[snapshot]), standing_consent=True)
        self.dispatch.assert_not_called()

    def test_manual_task_selection_uses_active_direct_message_without_second_approval(self):
        self.configure()
        with self.ledger.transaction() as data:
            data['routing']['scope']['live_consent'] = True
        selection = 'Use the OpenAI API for this test.'
        receipt = self.receipt(selection)
        plan = self.freeze(thread_snapshot=receipt)
        self.execute(plan, thread_snapshot=receipt, manual_selection=selection)
        _, task, evidence = self.dispatch.call_args.args
        self.assertEqual(evidence.approved_at, 101)
        self.dispatch.reset_mock()
        for invalid in (self.receipt(selection, role='agentMessage'),
                        self.receipt(selection, turn='later'),
                        self.receipt('Continue with native Codex.')):
            with self.assertRaisesRegex(BudgetError, 'codex_approval_missing'):
                self.execute(plan, thread_snapshot=invalid, manual_selection=selection)
        self.dispatch.assert_not_called()
        second = self.proposal(task_id='second')
        self.now = 106
        second_plan = self.freeze(second, thread_snapshot=receipt)
        self.execute(second_plan, second, thread_snapshot=receipt, manual_selection=selection)
        self.assertEqual(self.dispatch.call_args.args[1]['run_id'], task['run_id'])

    def habblaud_context(self):
        self.reviewer = self.host.Reviewer('e98f7dd1-70f7-44e3-98de-d6307c2fa04b', 'independent-reviewer')
        return dict(plugin_root=str(self.root), endpoint='http://127.0.0.1:4747', account='.codex',
                    model=PROFILE['model'], model_display_name='GPT-6.1 Sol')

    def test_habblaud_uses_completed_generation_and_keeps_native_review_pending(self):
        context = self.habblaud_context() | dict(visibility={'role': 'Reviewer'})
        declaration = self.proposal()['visibility']
        self.configure()
        plan = self.freeze()
        counted = Connection(Response(dict(object='response.input_tokens', input_tokens=1200)))
        reply = completed()
        reply['model'] = PROFILE['model']
        reply['usage'].update(input_tokens=1200, total_tokens=1217)
        generated = Connection(Response(reply))
        connections = iter((counted, generated))
        events = []
        agents = [dict(id='.codex:' + plan.thread_id, kind='main', account='.codex', provider='codex')]

        def dispatch(_, task, evidence):
            result = self.control._run_live(task, evidence, connection_factory=lambda *_: next(connections),
                                            credential_resolver=lambda _: b'synthetic-key')
            return result | dict(simulation_only=False)

        def event(account, value):
            events.append((account, value))
            if value['hook_event_name'] == 'SubagentStart':
                agents.append(dict(id=account + ':' + value['agent_id'],
                                   parentId=account + ':' + value['session_id'], role=value['agent_type']))

        def wire(binding, name, phase=None):
            return dict(hook_event_name=name, session_id=binding['parent'], agent_id=binding['agent_id'],
                        agent_type=binding['label'], cwd=binding['cwd'], phase=phase)

        client = SimpleNamespace(snapshot=lambda _: dict(agents=agents), event=event)
        transport = SimpleNamespace(Client=lambda _: client, _event=wire)
        self.dispatch.side_effect = dispatch
        with patch.object(worker_visibility, 'transport', return_value=transport):
            result = self.execute(plan, habblaud=context)
        self.assertFalse(result['accepted'])
        self.assertTrue(result['requires_native_review'])
        self.assertTrue(result['visibility']['delivered'])
        self.assertEqual([item['hook_event_name'] for _, item in events],
                         ['SubagentStart', 'PreToolUse', 'SubagentStop'])
        self.assertEqual({account for account, _ in events}, {'.codex'})
        self.assertEqual({item['session_id'] for _, item in events}, {plan.thread_id})
        self.assertEqual({item['agent_type'] for _, item in events}, {'Scout · GPT-6.1 Sol'})
        self.assertNotEqual(events[0][1]['agent_id'], plan.thread_id)
        self.assertEqual(events[1][1]['phase'], 'completed')
        self.assertNotIn(result['text'], str(events))
        baseline = self.ledger.snapshot()
        self.assertEqual(len(baseline['native']), 1)
        _, task, evidence = self.dispatch.call_args.args
        run_id = task['run_id']

        for field, value in (
            ('run_id', 'another-run'), ('simulation_only', True), ('accepted', True),
            ('requires_native_review', False), ('execution_route', 'auto'),
            ('reported_cost_usd_micros', result['reported_cost_usd_micros'] + 1),
        ):
            with self.subTest(result_field=field), patch.object(worker_visibility, 'transport') as load_transport:
                outcome = self.host._publish_generation(plan, task, evidence, result | {field: value}, context,
                                                        visibility=declaration)
                self.assertEqual(outcome, dict(delivered=False, reason='generation_unconfirmed'))
                load_transport.assert_not_called()

        for change in ('missing_run', 'count_only', 'task', 'scope', 'admission', 'closed', 'unresolved'):
            with self.subTest(ledger_change=change), patch.object(worker_visibility, 'transport') as load_transport:
                modified = deepcopy(baseline)
                run = modified['runs'][run_id]
                if change == 'missing_run':
                    del modified['runs'][run_id]
                elif change == 'count_only':
                    del run['calls']['generation']
                elif change == 'task':
                    run['task'] = 'another-task'
                elif change == 'scope':
                    run['consent']['scope'] = 'another-scope'
                elif change == 'admission':
                    run['live_admission']['pin'] = 'another-pin'
                elif change == 'closed':
                    run['closed'] = False
                else:
                    run['calls']['generation']['state'] = 'unresolved'
                with patch.object(self.ledger, 'snapshot', return_value=modified):
                    outcome = self.host._publish_generation(plan, task, evidence, result, context,
                                                            visibility=declaration)
                self.assertEqual(outcome, dict(delivered=False, reason='generation_unconfirmed'))
                load_transport.assert_not_called()

        agents[0]['provider'] = 'claude'
        with patch.object(worker_visibility, 'transport', return_value=transport):
            outcome = self.host._publish_generation(plan, task, evidence, result, context, visibility=declaration)
        self.assertEqual(outcome, dict(delivered=False, reason='visibility_parent_unavailable'))
        self.assertEqual(len(events), 3)
        self.assertEqual(self.ledger.snapshot(), baseline)

    def test_habblaud_does_not_publish_simulated_or_unrecorded_generations(self):
        context = self.habblaud_context()
        self.configure()
        plan = self.freeze()

        for simulated in (True, False):
            self.dispatch.side_effect = lambda _, task, evidence: dict(
                run_id=task['run_id'], simulation_only=simulated, accepted=False,
                requires_native_review=True, reported_cost_usd_micros=0, execution_route='openai-api',
                text='unrecorded response')
            with patch.object(worker_visibility, 'transport', side_effect=AssertionError('unexpected display')):
                result = self.execute(plan, habblaud=context)
                self.assertFalse(result['accepted'])
                self.assertEqual(result['visibility'], dict(delivered=False, reason='generation_unconfirmed'))

    def test_smart_host_and_runner_keep_one_task_through_review(self):
        self.configure('smart')
        first = self.proposal(provider='auto')
        second = self.proposal(task_id='second', provider='auto')
        plan = self.freeze(first, second)
        approved = self.receipt(self.host.approval_text(plan), turn='approval', started=105)
        counted = Connection(Response(dict(object='response.input_tokens', input_tokens=1200)))
        reply = completed()
        reply['model'] = PROFILE['model']
        reply['usage'].update(input_tokens=1200, total_tokens=1217)
        generated = Connection(Response(reply))
        connections = iter((counted, generated))
        self.dispatch.side_effect = lambda _, task, evidence: self.control._run_live(
            task, evidence, connection_factory=lambda *_: next(connections),
            credential_resolver=lambda _: b'synthetic-key')

        result = self.execute(plan, first, thread_snapshot=approved)
        self.assertFalse(result['accepted'])
        self.assertTrue(result['requires_native_review'])
        self.assertEqual(len(self.ledger.snapshot()['native']), 1)
        with self.assertRaisesRegex(BudgetError, 'native_task_outstanding'):
            self.execute(plan, second, thread_snapshot=approved)
        with self.assertRaisesRegex(BudgetError, 'live_run_id_already_used'):
            self.execute(plan, first, thread_snapshot=approved)
        self.assertEqual([conn.requests[0][1] for conn in (counted, generated)],
                         ['/v1/responses/input_tokens', '/v1/responses'])
        self.assertEqual(len(self.ledger.snapshot()['runs']), 1)


if __name__ == '__main__':
    unittest.main()
