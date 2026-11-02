"""Checks transport fixtures: no credentials, network, or readiness authority."""
from copy import deepcopy
import json
import unittest

from runtime.adapters.github_checks import ChecksError, GitHubChecks


class GitHubChecksTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.responses = []
        self.head = 'a' * 40
        self.binding = dict(head_sha=self.head, name='workflow/final', external_id='operation:one')
        self.repo = dict(id=20, full_name='owner/repo')
        self.run = dict(id=40, app=dict(id=30), head_sha=self.head, name='workflow/final',
                        external_id='operation:one', status='in_progress', conclusion=None)
        self.api = GitHubChecks(repository='owner/repo', repository_id=20, app_id=30, request=self.request)

    def request(self, method, endpoint, *, payload, timeout, limit):
        self.calls.append((method, endpoint, deepcopy(payload), timeout, limit))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        status, value = response
        return status, value if isinstance(value, bytes) else json.dumps(value).encode()

    def queue(self, *responses):
        self.responses.extend(responses)

    def test_create_binds_actual_repository_app_head_and_owned_run(self):
        self.queue((200, self.repo), (201, self.run))
        receipt = self.api.create(**self.binding)
        self.assertEqual(receipt['id'], 40)
        self.assertEqual(receipt['repository_id'], 20)
        self.assertEqual(receipt['app_id'], 30)
        self.assertFalse(receipt['merge_authority'])
        self.assertEqual(self.calls[1][:3], ('POST', '/repos/owner/repo/check-runs',
            dict(self.binding, status='in_progress')))
        self.assertTrue(all(row[3:] == (10, 128 * 1024) for row in self.calls))

    def test_complete_reobserves_owned_run_before_patch(self):
        completed = dict(self.run, status='completed', conclusion='success')
        self.queue((200, self.repo), (200, self.run), (200, completed))
        receipt = self.api.complete(run_id=40, conclusion='success', **self.binding)
        self.assertEqual(receipt['conclusion'], 'success')
        self.assertEqual([row[:2] for row in self.calls], [('GET', '/repos/owner/repo'),
            ('GET', '/repos/owner/repo/check-runs/40'), ('PATCH', '/repos/owner/repo/check-runs/40')])
        self.assertEqual(self.calls[-1][2]['status'], 'completed')
        self.assertNotIn('ready', receipt)
        self.assertFalse(receipt['merge_authority'])

    def test_wrong_repository_or_run_identity_prevents_write(self):
        for field, value in [('id', 21), ('full_name', 'other/repo')]:
            with self.subTest(field=field):
                self.calls.clear()
                self.responses = [(200, dict(self.repo, **{field: value}))]
                with self.assertRaises(ChecksError):
                    self.api.create(**self.binding)
                self.assertEqual(len(self.calls), 1)
        for field, value in [('id', 41), ('app', dict(id=31)), ('head_sha', 'b' * 40),
                             ('external_id', 'operation:other'), ('name', 'other')]:
            with self.subTest(field=field):
                self.calls.clear()
                self.responses = [(200, self.repo), (200, dict(self.run, **{field: value}))]
                with self.assertRaises(ChecksError):
                    self.api.complete(run_id=40, conclusion='success', **self.binding)
                self.assertFalse(any(row[0] == 'PATCH' for row in self.calls))

    def test_invalid_selectors_and_conclusions_do_not_call_transport(self):
        for options in [dict(self.binding, head_sha='bad'), dict(self.binding, external_id=''),
                        dict(self.binding, name='private\nname')]:
            with self.subTest(options=options), self.assertRaises(ChecksError):
                self.api.create(**options)
        with self.assertRaises(ChecksError):
            self.api.complete(run_id=True, conclusion='success', **self.binding)
        with self.assertRaises(ChecksError):
            self.api.complete(run_id=40, conclusion='neutral', **self.binding)
        self.assertEqual(self.calls, [])
        with self.assertRaises(ChecksError):
            GitHubChecks(repository='../repo', repository_id=20, app_id=30, request=self.request)
        with self.assertRaises(ChecksError):
            GitHubChecks(repository='owner/repo', repository_id=20, app_id=30, request=None)

    def test_transport_failure_is_sanitized_without_retry(self):
        self.queue((200, self.repo), RuntimeError('PRIVATE_TOKEN_AND_RESPONSE'))
        with self.assertRaises(ChecksError) as caught:
            self.api.create(**self.binding)
        self.assertNotIn('PRIVATE', str(caught.exception))
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.responses, [])

    def test_response_bounds_duplicate_json_and_wrong_create_result_reject(self):
        for result in [(201, b'x' * (128 * 1024 + 1)),
                       (201, b'{"id":40,"id":41}'),
                       (201, dict(self.run, head_sha='b' * 40)), (403, self.run)]:
            with self.subTest(result=result[0]):
                self.responses = [(200, self.repo), result]
                with self.assertRaises(ChecksError):
                    self.api.create(**self.binding)

    def test_reconcile_uncertain_create_never_creates_or_selects_foreign_app(self):
        foreign = dict(self.run, id=41, app=dict(id=31))
        self.queue((200, self.repo), (200, dict(total_count=2, check_runs=[foreign, self.run])))
        receipt = self.api.reconcile(**self.binding)
        self.assertEqual(receipt['id'], 40)
        self.assertTrue(all(row[0] == 'GET' for row in self.calls))
        self.calls.clear()
        self.queue((200, self.repo), (200, dict(total_count=0, check_runs=[])))
        self.assertIsNone(self.api.reconcile(**self.binding))
        self.assertTrue(all(row[0] == 'GET' for row in self.calls))

    def test_reconcile_incomplete_or_ambiguous_listing_rejects(self):
        for listing in [dict(total_count=2, check_runs=[self.run]),
                        dict(total_count=101, check_runs=[]),
                        dict(total_count=2, check_runs=[self.run, dict(self.run, id=41)])]:
            self.responses = [(200, self.repo), (200, listing)]
            with self.assertRaises(ChecksError):
                self.api.reconcile(**self.binding)
