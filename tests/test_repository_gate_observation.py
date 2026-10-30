"""Exercise real bounded child reads against a local, credential-free GitHub CLI double."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from runtime import repository_gate as gate
from runtime.doctor import NativeProcess, ObservationError


REPOSITORY = 'owner/repository'
PREFIX = '/repos/owner/repository'
SECRET = 'PRIVATE_RESPONSE_MUST_NOT_ESCAPE'


def response(value, status=200, headers=''):
    body = value if isinstance(value, str) else json.dumps(value)
    return (f'HTTP/2.0 {status} Result\r\nContent-Type: application/json; charset=utf-8\r\n'
            'Date: Thu, 29 Oct 2026 18:00:00 GMT\r\nX-GitHub-Request-Id: TEST:1234\r\n'
            f'ETag: "fixture"\r\n{headers}\r\n{body}')


class GitHubObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='vcw github observation ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.config = self.root / 'responses.json'
        self.log = self.root / 'calls.jsonl'
        self.executable = self.root / 'gh'
        self.documents = {
            '/user': {'login': 'reader', 'id': 10, 'email': SECRET},
            PREFIX: {'id': 20, 'node_id': 'REPO_NODE', 'full_name': REPOSITORY,
                     'owner': {'id': 30, 'login': 'owner'}, 'private_field': SECRET},
            PREFIX + '/pulls/11': {'id': 40, 'number': 11, 'state': 'closed', 'merged': True, 'draft': False,
                'base': {'repo': {'id': 20, 'owner': {'id': 30}}, 'ref': 'main', 'sha': 'a' * 40},
                'head': {'repo': {'id': 50, 'owner': {'id': 60}}, 'ref': 'feature', 'sha': 'b' * 40}, 'body': SECRET},
            PREFIX + '/git/ref/heads/main': {'ref': 'refs/heads/main', 'node_id': 'REF_NODE',
                                            'object': {'type': 'commit', 'sha': 'c' * 40}},
        }
        self.settings = {'responses': {}, 'exit_code': 0, 'delay': 0, 'version': 'gh version 2.102.0 (2026-09-30)'}
        self.executable.write_text(f'''#!{sys.executable}
import json, os, stat, sys, time
settings = json.load(open({str(self.config)!r}))
with open({str(self.log)!r}, 'a') as log:
    log.write(json.dumps({{'argv': sys.argv[1:], 'stdin_devnull': stat.S_ISCHR(os.fstat(0).st_mode)}}) + '\\n')
time.sleep(settings['delay'])
if sys.argv[1:] == ['--version']:
    print(settings['version'])
    raise SystemExit(0)
assert sys.argv[1:7] == ['api', '--hostname', 'github.com', '--method', 'GET', '--include']
assert all(flag not in sys.argv for flag in ['--input', '--field', '--raw-field', '--paginate', '--cache', '--verbose'])
wire = settings['responses'][sys.argv[-1]]
sys.stdout.buffer.write(wire.encode())
raise SystemExit(settings['exit_code'])
''')
        self.executable.chmod(0o700)
        self.save()

    def save(self):
        self.settings['responses'] = {path: response(value) for path, value in self.documents.items()}
        self.config.write_text(json.dumps(self.settings))

    def override(self, path, wire, **settings):
        self.settings['responses'][path] = wire
        self.settings.update(settings)
        self.config.write_text(json.dumps(self.settings))

    def observe(self, repository=REPOSITORY, target='refs/heads/main', pull=11):
        with patch('shutil.which', return_value=str(self.executable)):
            return gate.observe_github(repository, target, pull)

    def calls(self):
        return [json.loads(row) for row in self.log.read_text().splitlines()] if self.log.exists() else []

    def rejected(self, **arguments):
        with self.assertRaises(ObservationError) as error:
            self.observe(**arguments)
        self.assertNotIn(SECRET, str(error.exception))

    def test_projects_actual_metadata_without_conflating_base_or_granting_authority(self):
        result = self.observe()
        self.assertEqual(result['account'], {'login': 'reader', 'id': 10})
        self.assertEqual(result['repository'], {'id': 20, 'node_id': 'REPO_NODE', 'full_name': REPOSITORY, 'owner_id': 30})
        self.assertEqual(result['target'], {'ref': 'refs/heads/main', 'sha': 'c' * 40})
        self.assertEqual(result['pull_request']['base'], {'repository_id': 20, 'owner_id': 30, 'ref': 'main', 'sha': 'a' * 40})
        self.assertEqual(result['pull_request']['head'], {'repository_id': 50, 'owner_id': 60, 'ref': 'feature', 'sha': 'b' * 40})
        self.assertEqual(result['pull_request']['state'], 'closed')
        self.assertFalse(result['merge_authority'])
        self.assertNotIn(SECRET, json.dumps(result))
        provenance = result['provenance']
        self.assertEqual(provenance['resolved_path'], str(self.executable))
        self.assertEqual(provenance['sha256'], hashlib.sha256(self.executable.read_bytes()).hexdigest())
        self.assertEqual(provenance['version'], 'gh version 2.102.0 (2026-09-30)')
        self.assertEqual([r['endpoint'] for r in provenance['requests']], list(self.documents))
        self.assertTrue(all(r['status'] == 200 and r['request_id'] == 'TEST:1234' for r in provenance['requests']))
        self.assertLessEqual(provenance['started_at'], provenance['finished_at'])
        self.assertGreaterEqual(provenance['duration'], 0)
        calls = self.calls()
        self.assertEqual(len(calls), 5)
        self.assertTrue(all(row['stdin_devnull'] for row in calls))
        self.assertTrue(all(row['argv'][4] == 'GET' for row in calls[1:]))

    def test_invalid_selectors_never_launch_a_child(self):
        for arguments in ({'repository': '../repo'}, {'repository': 'https://github.com/owner/repository'},
                          {'repository': 'owner/repo?x'}, {'target': 'refs/tags/main'},
                          {'target': 'refs/heads/../main'}, {'target': 'refs/heads/main\n'},
                          {'target': 'refs/heads/main?x'}, {'target': 'refs/heads/a.lock'},
                          {'pull': True}, {'pull': 0}, {'pull': '11'}):
            with self.subTest(arguments=arguments):
                self.rejected(**arguments)
                self.assertEqual(self.calls(), [])

    def test_wrong_repository_base_target_and_commit_identities_reject(self):
        original = deepcopy(self.documents)
        mutations = [(PREFIX, 'full_name', 'other/repository'), (PREFIX, 'id', True),
                     (PREFIX + '/pulls/11', 'number', 12),
                     (PREFIX + '/git/ref/heads/main', 'ref', 'refs/heads/other')]
        for path, key, value in mutations:
            with self.subTest(key=key, value=value):
                self.documents = deepcopy(original)
                self.documents[path][key] = value
                self.save()
                self.rejected()
        for key, value in [('repo', {'id': 21, 'owner': {'id': 30}}), ('ref', 'other'), ('sha', SECRET)]:
            self.documents = deepcopy(original)
            self.documents[PREFIX + '/pulls/11']['base'][key] = value
            self.save()
            self.rejected()
        self.documents = deepcopy(original)
        self.documents[PREFIX + '/git/ref/heads/main']['object']['type'] = 'tag'
        self.save()
        self.rejected()

    def test_exact_missing_ref_rejects_once_without_retry(self):
        path = PREFIX + '/git/ref/heads/main'
        self.override(path, response({'message': SECRET}, 404), exit_code=0)
        self.rejected()
        self.assertEqual([r['argv'][-1] for r in self.calls()].count(path), 1)

    def test_auth_rate_limit_server_and_nonzero_failures_are_sanitized(self):
        for status, code in [(401, 1), (403, 1), (429, 1), (500, 1), (200, 1)]:
            with self.subTest(status=status, code=code):
                self.override('/user', response({'login': SECRET, 'id': 10}, status), exit_code=code)
                self.rejected()

    def test_malformed_headers_redirect_blocks_and_json_reject(self):
        wires = [SECRET, response(self.documents['/user'], 302),
                 response(self.documents['/user']) + '\nHTTP/2.0 200 OK\n\n{}',
                 response(self.documents['/user'], headers='Date: Thu, 29 Oct 2026 18:00:00 GMT\r\n'),
                 response(self.documents['/user']).replace('application/json', 'text/html'),
                 response('{"login":"reader","id":10,"id":11}'),
                 response('{"login":"reader","id":NaN}'), response('[]')]
        for wire in wires:
            with self.subTest(wire=wire[:60]):
                self.override('/user', wire)
                self.rejected()

    def test_json_body_and_child_output_limits_reject(self):
        for wire in [response({'login': 'reader', 'id': 10, 'extra': 'x' * (128 * 1024)}), 'x' * (513 * 1024)]:
            self.override('/user', wire)
            self.rejected()

    def test_original_deadline_covers_all_children_and_stops_on_timeout(self):
        self.settings['delay'] = 0.06
        self.save()
        began = time.monotonic()
        with patch.object(gate, 'GITHUB_SECONDS', 0.18, create=True):
            self.rejected()
        self.assertLess(time.monotonic() - began, 1)
        self.assertLess(len(self.calls()), 5)

    def test_missing_executable_and_invalid_version_are_source_errors(self):
        with patch('shutil.which', return_value=None):
            with self.assertRaises(ObservationError):
                gate.observe_github(REPOSITORY, 'refs/heads/main', 11)
        self.assertEqual(self.calls(), [])
        self.settings['version'] = SECRET
        self.save()
        self.rejected()

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'requires a filesystem FIFO')
    def test_nonregular_executable_rejects_before_opening_an_unbounded_stream(self):
        self.executable.unlink()
        os.mkfifo(self.executable)
        with patch.object(Path, 'open', side_effect=AssertionError('unsafe stream opened')):
            self.rejected()


class NativeProcessInputTests(unittest.TestCase):
    def test_devnull_input_is_safe_to_close_and_cannot_send(self):
        child = NativeProcess([sys.executable, '-c', 'print("done")'], time.monotonic() + 3,
                              stdin=subprocess.DEVNULL)
        try:
            with self.assertRaises(ObservationError):
                child.send({'unexpected': 'input'})
            self.assertEqual(child.read(child.deadline), b'done\n')
        finally:
            child.close()

    def test_default_pipe_still_supports_rpc_send_and_receive(self):
        program = 'import json,sys; r=json.loads(sys.stdin.readline()); print(json.dumps({"id":r["id"],"result":{"observed":True}}),flush=True)'
        child = NativeProcess([sys.executable, '-c', program], time.monotonic() + 3)
        try:
            self.assertEqual(child.request(1, 'read', {}), {'observed': True})
        finally:
            child.close()


if __name__ == '__main__':
    unittest.main()
