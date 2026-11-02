"""Provider observations preserve unknowns and never manufacture merge authority."""
from copy import deepcopy
import importlib.util
import json
import sys
import unittest


class GitHubDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.publication = dict(host='github.com', repository='owner/repo', target='main',
                                branch='codex/feature', pull_request=42)
        self.repo = dict(id=123, full_name='owner/repo', default_branch='main')
        self.pr = dict(number=42, state='open', draft=True, merged=False, merged_at=None,
                       merge_commit_sha=None, mergeable=None,
                       base=dict(ref='main', sha='b' * 40, repo=self.repo),
                       head=dict(ref='codex/feature', sha='a' * 40, repo=self.repo))
        self.calls = []

    def adapter(self, *, code=0, raw=None):
        self.assertIsNotNone(importlib.util.find_spec('runtime.adapters.github_delivery'),
                             'GitHub delivery observation is missing')
        from runtime.adapters.github_delivery import GitHubDelivery

        def run(argv, **bounds):
            self.calls.append((argv, bounds))
            value = self.pr if argv[-1].endswith('/pulls/42') else self.repo
            return code, json.dumps(value).encode() if raw is None else raw

        return GitHubDelivery(executable=sys.executable, host='github.com', run=run)

    def test_open_pr_observation_retains_unknown_checks_and_reviews(self):
        result = self.adapter().observe(self.publication)
        self.assertEqual(result['repository_id'], 123)
        self.assertEqual(result['head'], 'a' * 40)
        self.assertFalse(result['merged'])
        self.assertEqual(result['checks'], 'unobserved')
        self.assertEqual(result['reviews'], 'unobserved')
        self.assertIsNone(result['mergeability'])
        self.assertNotIn('merge_authorized', result)
        for argv, bounds in self.calls:
            self.assertEqual(argv[:4], [sys.executable, 'api', '--hostname', 'github.com'])
            self.assertIn('X-GitHub-Api-Version: 2022-11-28', argv)
            self.assertEqual(bounds, dict(timeout=10, limit=128 * 1024))

    def test_merged_pr_records_result_without_requiring_head_ancestry(self):
        self.pr.update(state='closed', draft=False, merged=True,
                       merged_at='2026-11-02T12:00:00Z', merge_commit_sha='c' * 40)
        result = self.adapter().observe(self.publication)
        self.assertTrue(result['merged'])
        self.assertEqual(result['merge_commit'], 'c' * 40)
        self.assertNotEqual(result['head'], result['merge_commit'])

    def test_wrong_host_or_repository_text_is_rejected_before_execution(self):
        for update in (dict(host='other.example'), dict(repository='owner/repo?secret=x'),
                       dict(repository='--help'), dict(pull_request=True), dict(pull_request=0)):
            self.calls.clear()
            with self.assertRaises(ValueError):
                self.adapter().observe(self.publication | update)
            self.assertEqual(self.calls, [])

    def test_wrong_base_fork_or_changed_branch_is_rejected(self):
        original = deepcopy(self.pr)
        for location, update in (('base', dict(ref='other')), ('head', dict(ref='other')),
                                 ('head', dict(repo=self.repo | dict(id=999)))):
            self.pr = deepcopy(original)
            self.pr[location].update(update)
            with self.assertRaises(ValueError):
                self.adapter().observe(self.publication)

    def test_incomplete_merge_and_boolean_repository_id_are_rejected(self):
        self.pr.update(merged=True, merged_at=None)
        with self.assertRaises(ValueError):
            self.adapter().observe(self.publication)
        self.repo['id'] = True
        with self.assertRaises(ValueError):
            self.adapter().observe(self.publication)

    def test_unavailable_or_oversized_response_never_becomes_absence(self):
        for code, raw in ((1, b'private-token-do-not-echo'), (0, b' ' * (128 * 1024 + 1)),
                          (0, b'{}'), (0, b'not JSON')):
            with self.subTest(code=code), self.assertRaises(ValueError) as error:
                self.adapter(code=code, raw=raw).observe(self.publication)
            self.assertNotIn('private-token', str(error.exception))

    def test_invalid_expected_refs_are_rejected_before_execution(self):
        for update in (dict(target=None), dict(branch=None), dict(target='--help'),
                       dict(branch='bad..branch'), dict(target='refs/heads/../main')):
            self.calls.clear()
            with self.assertRaises(ValueError):
                self.adapter().observe(self.publication | update)
            self.assertEqual(self.calls, [])

    def test_standard_subprocess_timeout_is_sanitized(self):
        import subprocess
        adapter = self.adapter()

        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired('private-token-do-not-echo', 10, output=b'private-output')

        adapter.run = timeout
        with self.assertRaises(ValueError) as error:
            adapter.observe(self.publication)
        self.assertNotIn('private-token', str(error.exception))
