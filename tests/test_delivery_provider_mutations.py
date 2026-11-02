"""Low-level provider fixtures; transport success is not operation authority."""
from copy import deepcopy
import json
import subprocess
import sys
import unittest
from urllib.parse import unquote

from runtime.adapters.github_delivery import GitHubDelivery
from tests import test_github_delivery


class ProviderMutationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_github_delivery.GitHubDeliveryTests('runTest')
        self.fixture.setUp()
        self.pr = self.fixture.pr
        self.pr.update(title='Human title', body='Human introduction')
        self.exists, self.lost_create, self.failed_undo, self.next_page = True, False, False, False
        self.merge_race, self.metadata_race, self.target_race, self.lost_comment = False, False, False, False
        self.calls, self.creates, self.comments, self.labels, self.known_labels = [], 0, [], set(), set()
        self.adapter = GitHubDelivery(executable=sys.executable, host='github.com', run=self.transport_run,
            mutate=self.transport_run, merge=self.fenced_merge)

    def fenced_merge(self, argv, **bounds):
        # Software-only target fence. Ordinary GitHub REST supplies no such guarantee.
        expected = bounds.pop('preconditions')['binding']
        if self.target_race:
            self.pr['base']['ref'] = 'release'
            self.target_race = False
        actual = dict(host='github.com', repository=self.fixture.repo['full_name'], repository_id=self.fixture.repo['id'],
            pull_request=42, head=self.pr['head']['sha'], base=self.pr['base']['sha'], branch=self.pr['head']['ref'],
            target=self.pr['base']['ref'], state=self.pr['state'], merged=self.pr['merged'])
        if any(actual[key] != value for key, value in expected.items()):
            return 1, b'private binding conflict'
        return self.transport_run(argv, **bounds)

    def listing(self, rows):
        headers = b'HTTP/2.0 200 OK\r\n'
        if self.next_page:
            headers += b'Link: <https://github.example/next>; rel="next"\r\n'
        return 0, headers + b'\r\n' + json.dumps(rows).encode()

    def transport_run(self, argv, **bounds):
        self.calls.append((argv, bounds))
        if argv[1:3] == ['pr', 'ready']:
            if '--undo' in argv and self.failed_undo:
                return 1, b'private detail'
            self.pr['draft'] = '--undo' in argv
            return 0, b''
        endpoint = argv[-1]
        path = endpoint.split('?', 1)[0]
        method = argv[argv.index('--method') + 1] if '--method' in argv else 'GET'
        payload = json.loads(bounds['input']) if 'input' in bounds else None
        if method != 'GET' and self.metadata_race:
            self.pr.update(title='New human title', body='New human body')
            self.metadata_race = False
        if '/issues/42/labels' in path:
            if method == 'GET':
                return self.listing([dict(name=name) for name in self.labels])
            if method == 'DELETE':
                self.labels.discard(unquote(path.rsplit('/', 1)[1]))
                return 0, b''
            self.labels.update(payload['labels'])
            return 0, json.dumps([dict(name=name) for name in self.labels]).encode()
        if '/issues/42/comments' in path:
            if method == 'GET':
                return self.listing(self.comments)
            comment = dict(id=len(self.comments) + 1, body=payload['body'])
            self.comments.append(comment)
            if self.lost_comment:
                self.lost_comment = False
                raise subprocess.TimeoutExpired(argv[0], 10)
            return 0, json.dumps(comment).encode()
        if '/labels/' in path:
            name = unquote(path.rsplit('/', 1)[1])
            return (0, json.dumps(dict(name=name)).encode()) if name in self.known_labels else (1, b'not found')
        if path.endswith('/labels'):
            self.known_labels.add(payload['name'])
            return 0, json.dumps(payload).encode()
        if method == 'POST' and path.endswith('/pulls'):
            self.creates += 1
            self.exists = True
            self.pr.update({key: payload[key] for key in ('title', 'body', 'draft')})
            if self.lost_create:
                self.lost_create = False
                raise subprocess.TimeoutExpired(argv[0], 10)
        elif method == 'PUT':
            if self.merge_race:
                self.pr['head']['sha'] = 'e' * 40
            if payload['sha'] != self.pr['head']['sha']:
                return 1, b'private expected-head failure'
            self.pr.update(state='closed', draft=False, merged=True,
                merged_at='2026-11-02T12:00:00Z', merge_commit_sha='c' * 40)
        if '/pulls?' in endpoint:
            return self.listing([self.pr] if self.exists else [])
        if '/git/ref/' in path:
            return 0, json.dumps(dict(ref='refs/heads/codex/feature', object=dict(sha='a' * 40))).encode()
        value = self.pr if '/pulls' in path else self.fixture.repo
        return 0, json.dumps(value).encode()

    def operation(self, **updates):
        return dict(publication=deepcopy(self.fixture.publication), head='a' * 40, marker='d' * 64,
            operation_id='a' * 64, repository_id=123, title='Feature', body='Checkpoint\nAccepted progress') | updates

    def test_checkpoint_preserves_human_title_body_and_prior_comments(self):
        self.adapter.execute('checkpoint', self.operation())
        self.pr['body'] += '\nHuman follow-up'
        self.adapter.execute('checkpoint', self.operation(body='Next checkpoint', operation_id='b' * 64))
        self.assertEqual(self.pr['title'], 'Human title')
        self.assertEqual(self.pr['body'], 'Human introduction\nHuman follow-up')
        self.assertIn('Accepted progress', self.comments[0]['body'])
        self.assertIn('Next checkpoint', self.comments[1]['body'])
        self.assertEqual(self.labels, {'[BLOCKED]'})

    def test_checkpoint_never_rewrites_shared_title_or_description(self):
        before = self.pr['title'], self.pr['body']
        self.adapter.execute('checkpoint', self.operation())
        self.assertEqual((self.pr['title'], self.pr['body']), before)
        self.assertFalse(any('PATCH' in argv for argv, _ in self.calls))

    def test_lost_create_ack_discovers_one_draft_instead_of_creating_another(self):
        self.exists, self.lost_create = False, True
        operation = self.operation(publication=self.fixture.publication | dict(pull_request=None))
        with self.assertRaises(ValueError):
            self.adapter.execute('checkpoint', operation)
        result = self.adapter.execute('checkpoint', operation)
        self.assertEqual(self.creates, 1)
        self.assertEqual(result['pull_request'], 42)
        self.assertTrue(result['draft'])
        self.assertEqual(self.pr['title'], 'Feature')
        self.assertEqual(self.labels, {'[BLOCKED]'})

    def test_lost_comment_ack_and_replay_do_not_duplicate_progress(self):
        self.lost_comment = True
        with self.assertRaises(ValueError):
            self.adapter.execute('checkpoint', self.operation())
        self.adapter.execute('checkpoint', self.operation())
        self.assertEqual(len(self.comments), 1)
        with self.assertRaises(ValueError):
            self.adapter.execute('checkpoint', self.operation(body='Changed reused operation'))
        self.assertEqual(len(self.comments), 1)

    def test_incomplete_discovery_cannot_create_or_claim_absence(self):
        self.exists, self.next_page = False, True
        with self.assertRaises(ValueError):
            self.adapter.execute('checkpoint', self.operation(publication=self.fixture.publication | dict(pull_request=None)))
        self.assertEqual(self.creates, 0)

    def test_ready_and_reopen_preserve_the_human_title(self):
        ready = self.adapter.execute('ready', self.operation())
        self.assertFalse(ready['draft'])
        self.assertEqual(self.pr['title'], 'Human title')
        self.assertEqual(self.labels, {'[READY]'})
        reopened = self.adapter.execute('reopen', self.operation(operation_id='b' * 64))
        self.assertTrue(reopened['draft'])
        self.assertEqual(self.pr['title'], 'Human title')
        self.assertEqual(self.labels, {'[BLOCKED]'})

    def test_failed_ready_withdrawal_does_not_report_success(self):
        self.pr['draft'] = False
        self.labels.add('[READY]')
        self.failed_undo = True
        with self.assertRaises(ValueError):
            self.adapter.execute('reopen', self.operation())
        self.assertFalse(self.pr['draft'])
        self.assertEqual(self.pr['title'], 'Human title')
        self.assertNotIn('[READY]', self.labels)

    def test_direct_merge_requires_a_separate_target_enforcement_source(self):
        metadata = GitHubDelivery(executable=sys.executable, host='github.com', run=self.transport_run, mutate=self.transport_run)
        self.pr['draft'] = False
        with self.assertRaises(ValueError):
            metadata.execute('merge', self.operation(method='squash'))
        self.assertFalse(any('PUT' in argv for argv, _ in self.calls))
        result = self.adapter.execute('merge', self.operation(method='squash'))
        self.assertTrue(result['merged'])
        mutation = next((argv, bounds) for argv, bounds in self.calls if 'PUT' in argv)
        self.assertEqual(json.loads(mutation[1]['input']), dict(sha='a' * 40, merge_method='squash'))
        flattened = [value for argv, _ in self.calls for value in argv]
        for forbidden in ('--admin', '--auto', '--delete-branch', 'merge-async'):
            self.assertNotIn(forbidden, flattened)
        self.calls.clear()
        self.adapter.execute('merge', self.operation(method='squash'))
        self.assertFalse(any('--method' in argv for argv, _ in self.calls))

    def test_changed_head_is_rejected_by_the_conditional_merge_request(self):
        self.pr['draft'], self.merge_race = False, True
        with self.assertRaises(ValueError) as error:
            self.adapter.execute('merge', self.operation(method='squash'))
        self.assertFalse(self.pr['merged'])
        self.assertNotIn('private expected-head failure', str(error.exception))

    def test_unowned_existing_branch_pr_is_not_replaced(self):
        with self.assertRaises(ValueError):
            self.adapter.execute('checkpoint', self.operation(publication=self.fixture.publication | dict(pull_request=None)))
        self.assertEqual(self.creates, 0)

    def test_plain_read_executor_cannot_enable_a_provider_mutation(self):
        plain = GitHubDelivery(executable=sys.executable, host='github.com', run=self.transport_run)
        with self.assertRaises(ValueError):
            plain.execute('checkpoint', self.operation())
        self.assertFalse(any('--method' in argv for argv, _ in self.calls))

    def test_concurrent_human_text_is_not_overwritten(self):
        self.metadata_race = True
        self.adapter.execute('checkpoint', self.operation())
        self.assertEqual(self.pr['title'], 'New human title')
        self.assertEqual(self.pr['body'], 'New human body')

    def test_retarget_cannot_merge_into_an_unapproved_branch(self):
        self.pr['draft'], self.target_race = False, True
        with self.assertRaises(ValueError):
            self.adapter.execute('merge', self.operation(method='squash'))
        self.assertFalse(self.pr['merged'])

    def test_reused_operation_conflicts_before_ready_or_label_changes(self):
        self.adapter.execute('checkpoint', self.operation())
        with self.assertRaises(ValueError):
            self.adapter.execute('ready', self.operation(body='Changed reused operation'))
        self.assertTrue(self.pr['draft'])
        self.assertEqual(self.labels, {'[BLOCKED]'})
        self.assertEqual(len(self.comments), 1)
