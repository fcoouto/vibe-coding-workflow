"""Foreground host receipt checks with synthetic Desktop responses."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime import usage_admission, usage_budget, usage_canary, usage_canary_host as host, usage_routing
from runtime.usage_budget import BudgetError
from tests.test_openai_api import Connection, Response, completed


class CanaryHostTests(unittest.TestCase):
    def setUp(self):
        self.plan = host.Plan(
            thread_id='thread', host_id='desktop', checkout='/fixture/project', scope='scope',
            package_digest='a' * 64, account='account', reviewer='independent-reviewer',
            organization='org-fixture', project='proj_fixture', key_name='Codex',
            key_expiry=None, grant_expiry=10_000, grant_amount=270_000_000, created_at=100, expires_at=200,
        )
        self.message = dict(type='userMessage', id='user-item',
                            content=[dict(type='text', text=host.approval_text(self.plan))])
        self.snapshot = dict(thread=dict(kind='codex', id='thread', hostId='desktop', cwd='/fixture/project'),
                             turns=[dict(id='turn', status='inProgress', startedAt=105, items=[self.message])])
        self.binding = dict(organization='org-fixture', project='proj_fixture', storage_kind='macos_keychain',
                            credential_ref='vcw_' + '0' * 32)
        self.receipt = dict(selection=dict(name='Codex', organization_id='org-fixture', project_id='proj_fixture'),
                            mode='off', binding=self.binding)
        self.config = dict(enabled=True, disabled=False, requested_mode='manual', revision=2, org_revision=1,
                           class_name='canary', binding=self.binding,
                           profile=usage_canary.profile_for(101, 200))
        self.policy = dict(cycle='fixture', start=90, end=10_000, expiry=10_000, stop_at=900,
                           ceiling='subscription_benefit', amount=None, grant_amount=270_000_000,
                           pilot_limit=50_640, task_limit=50_640)
        self.limits = dict(accountId='account', ordinaryUsageAllowed=True, rateLimitsByLimitId={
            'codex': dict(limitId='codex', spendControlReached=False, secondary=None,
                          primary=dict(usedPercent=48.1, windowDurationMins=10080, resetsAt=900))})
        self.grant = usage_admission.Grant('org-fixture', 'proj_fixture', 270_000_000, 10_000, 105,
                                           'platform-credit-grants', 'benefit')

    def issue(self, **overrides):
        args = dict(thread_snapshot=self.snapshot, key_receipt=self.receipt, config=self.config,
                    policy=self.policy, grant=self.grant, native_limits=self.limits,
                    native_observed_at=105, reviewer='independent-reviewer', scope='scope',
                    package_digest='a' * 64, now=106)
        args.update(overrides)
        return host.issue(self.plan, **args)

    def test_exact_foreground_approval_binds_one_canary(self):
        evidence, native = self.issue()
        task = usage_canary.task_for(evidence.approval_id, self.binding, native)
        usage_canary.validate(evidence, binding=self.binding, profile=self.config['profile'], task=task, now=106)
        self.assertEqual(native['windows'][0]['remaining_pp'], 51)
        self.assertEqual(native['windows'][0]['allowance_pp'], 5)
        self.assertEqual(evidence.approval_until, 200)
        self.message['id'] = 'another-direct-message'
        repeated, _ = self.issue()
        self.assertEqual(repeated.approval_id, evidence.approval_id)

    def test_native_approval_allows_one_terminal_line_feed(self):
        token = host.approval_text(self.plan)
        self.message['content'][0]['text'] = token + '\n'
        self.assertEqual(host.verify_approval(self.plan, self.snapshot, 106), 105)
        for text in (token + '\n\n', token + ' ', token + '\r\n', '\n' + token, token + '\nextra'):
            with self.subTest(text=text), self.assertRaisesRegex(BudgetError, 'canary_approval_missing'):
                self.message['content'][0]['text'] = text
                host.verify_approval(self.plan, self.snapshot, 106)

    def test_refuses_wrong_role_text_host_and_stale_turn(self):
        self.message['type'] = 'agentMessage'
        with self.assertRaises(BudgetError):
            self.issue()
        self.message['type'] = 'userMessage'
        self.message['content'][0]['text'] += ' and another test'
        with self.assertRaises(BudgetError):
            self.issue()
        self.message['content'][0]['text'] = host.approval_text(self.plan)
        self.snapshot['thread']['hostId'] = 'other-host'
        with self.assertRaises(BudgetError):
            self.issue()
        self.snapshot['thread']['hostId'] = 'desktop'
        self.snapshot['turns'][0]['startedAt'] = 99
        with self.assertRaises(BudgetError):
            self.issue()

    def test_refuses_candidate_funding_and_key_changes(self):
        for change in (dict(package_digest='b' * 64), dict(grant=replace(self.grant, pool='mixed')),
                       dict(reviewer='other-worker'), dict(now=201),
                       dict(key_receipt=dict(self.receipt, selection=dict(self.receipt['selection'],
                                                                       expires_in_seconds=86400)))):
            with self.subTest(change=change), self.assertRaises(BudgetError):
                self.issue(**change)

    def test_missing_or_changed_quota_is_not_capacity(self):
        for limits in (dict(self.limits, accountId='other'), dict(self.limits, ordinaryUsageAllowed=False),
                       dict(self.limits, rateLimitsByLimitId={}), dict(self.limits, rateLimitsByLimitId={
                           **self.limits['rateLimitsByLimitId'], 'unknown': {}})):
            with self.assertRaises(BudgetError):
                self.issue(native_limits=limits)

    @contextmanager
    def controller(self):
        root = Path(self.plan.checkout)
        with tempfile.TemporaryDirectory() as temporary:
            ledger_path = Path(temporary) / 'private' / 'ledger'
            with usage_budget.Ledger(ledger_path, usage_budget.initialize(ledger_path)) as ledger:
                control = usage_routing.Controller(ledger, 'scope', root=root, clock=lambda: 106)

                @contextmanager
                def settings(*args, **kwargs):
                    yield control

                with patch.object(host.time, 'time', return_value=106), patch.object(
                        host, 'package_digest', return_value=self.plan.package_digest), patch.object(
                        host.usage_settings, 'scope', return_value=('scope', root)), patch.object(
                        host.usage_settings, 'controller', side_effect=settings):
                    yield control

    def execute(self):
        return host.execute(
            self.plan, thread_snapshot=self.snapshot, key_receipt=self.receipt, grant=self.grant,
            native_limits=self.limits, native_observed_at=105, reviewer=self.plan.reviewer,
            price_observed_at=101, price_valid_until=200)

    def test_execution_failure_restores_off_and_same_plan_cannot_retry(self):
        with self.controller() as control:
            def reject(*args, **kwargs):
                self.assertEqual(control.status()['mode'], 'manual')
                raise BudgetError('fixture_transport_error')

            with patch.object(usage_canary, 'run', side_effect=reject) as run:
                with self.assertRaisesRegex(BudgetError, 'fixture_transport_error'):
                    self.execute()
                self.assertEqual(control.status()['mode'], 'off')
                with self.assertRaisesRegex(BudgetError, 'canary_state_already_configured'):
                    self.execute()
                run.assert_called_once()

    def test_enable_commit_then_failure_still_restores_off(self):
        with self.controller() as control:
            transaction = control.ledger.transaction
            failed = False

            @contextmanager
            def fail_after_enable(*args, **kwargs):
                nonlocal failed
                with transaction(*args, **kwargs) as data:
                    yield data
                    enabled = data.get('routing', {}).get('scope', {}).get('enabled', False)
                if enabled and not failed:
                    failed = True
                    raise BudgetError('fixture_after_commit')

            with patch.object(control.ledger, 'transaction', side_effect=fail_after_enable), patch.object(
                    usage_canary, 'run') as run:
                with self.assertRaisesRegex(BudgetError, 'fixture_after_commit'):
                    self.execute()
                run.assert_not_called()
            self.assertEqual(control.status()['mode'], 'off')

    def test_full_foreground_rehearsal_uses_one_count_and_generation(self):
        count = Connection(Response(dict(object='response.input_tokens', input_tokens=5)))
        reply = completed()
        reply['model'] = self.config['profile']['model']
        reply['usage'].update(input_tokens=5, total_tokens=22)
        reply['usage']['input_tokens_details'] = dict(cached_tokens=0)
        generate = Connection(Response(reply))
        connections = iter((count, generate))
        with self.controller() as control:
            def dispatch(cwd, task, evidence):
                return control._run_live(
                    task, evidence, connection_factory=lambda *args: next(connections),
                    credential_resolver=lambda binding: b'synthetic-key')

            with patch.object(usage_routing, '_run_live', side_effect=dispatch):
                result = self.execute()
            self.assertTrue(result['requires_native_review'])
            self.assertEqual(control.status()['mode'], 'off')
            self.assertEqual([c.requests[0][1] for c in (count, generate)],
                             ['/v1/responses/input_tokens', '/v1/responses'])
            data = control.ledger.snapshot()
            self.assertIsNone(data['slot'])
            self.assertEqual(len(data['native']), 1)


if __name__ == '__main__':
    unittest.main()
