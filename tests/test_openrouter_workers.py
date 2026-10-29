import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import uuid
import os
import signal
import sys
import time

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/openrouter_workers.py'


class WorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = None
        if SCRIPT.exists():
            spec = importlib.util.spec_from_file_location('workers', SCRIPT)
            cls.api = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.api)

    def setUp(self):
        self.assertIsNotNone(self.api, 'worker runner must exist')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'input.txt').write_text('three lines\nof evidence\nfor review\n')
        self.brief = dict(task_id='pilot-1', role='Scout', specialty='File analysis',
                          coordinator_chat_id=str(uuid.uuid4()), model='vendor/model',
                          model_display_name='Model', provider='provider', objective='Read input.txt and count lines.',
                          source_root=str(self.source), files=['input.txt'], timeout_seconds=5,
                          steps=3, credit={'observed_at':100, 'remaining':1}, approval_ref='user-approved', effort='low')

    def test_snapshot_excludes_unselected_inputs_and_rejects_replay(self):
        (self.source / 'secret.txt').write_text('not selected')
        run = self.api.prepare(self.root / 'runs', self.brief, now=100)
        self.assertEqual((run / 'workspace/input.txt').read_text(), 'three lines\nof evidence\nfor review\n')
        self.assertFalse((run / 'workspace/secret.txt').exists())
        import subprocess
        actual_root = subprocess.check_output(['git', '-C', str(run/'workspace'), 'rev-parse', '--show-toplevel'], text=True).strip()
        self.assertEqual(actual_root, str(run/'workspace'))
        with self.assertRaises(FileExistsError):
            self.api.prepare(self.root / 'runs', self.brief, now=100)

    def test_unsafe_inputs_and_stale_credit_fail_before_run_creation(self):
        (self.source / 'link').symlink_to(self.source / 'input.txt')
        for files in [['../escape'], ['link'], ['/absolute'], ['.env']]:
            with self.subTest(files=files), self.assertRaises(ValueError):
                self.api.prepare(self.root / 'runs', dict(self.brief, files=files), now=100)
        with self.assertRaises(ValueError):
            self.api.prepare(self.root / 'runs', self.brief, now=200)
        self.assertFalse((self.root / 'runs/pilot-1').exists())

    def test_permission_patterns_cannot_be_injected_through_filenames(self):
        for name in ['*', 'file?', '[a]', './input.txt', 'folder//file.txt']:
            if '/' not in name: (self.source/name).write_text('fixture')
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.api.prepare(self.root/'runs', dict(self.brief, files=[name]), now=100)

    def test_permissions_deny_shell_writes_network_and_other_agents(self):
        config = self.api.configuration(self.brief)
        permissions = config['permission']
        self.assertEqual(permissions['*'], 'deny')
        self.assertEqual(permissions['read']['*'], 'deny')
        self.assertEqual(permissions['read']['input.txt'], 'allow')
        self.assertNotIn('/absolute', permissions['read'])
        for tool in ['bash', 'edit', 'task', 'webfetch', 'external_directory']:
            self.assertNotEqual(permissions.get(tool), 'allow')
        self.assertFalse(config['provider']['openrouter']['models']['vendor/model']['options']['provider']['allow_fallbacks'])

    def test_missing_visibility_adapter_does_not_prevent_worker_execution(self):
        import subprocess
        brief = dict(self.brief, credit={'observed_at':time.time(), 'remaining':1})
        exe = self.fixture("print(json.dumps({'type':'error','error':{'message':'provider unavailable'}}))\n")
        result = subprocess.run([sys.executable, str(SCRIPT), 'run', '--root', str(self.root/'runs'),
                                 '--opencode', str(exe), '--auth-data', str(self.root/'auth'),
                                 '--visibility-plugin', str(self.root/'missing')], input=json.dumps(brief),
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((self.root/'runs/pilot-1/result.json').read_text())['state'], 'failed')
        self.assertFalse(json.loads((self.root/'runs/pilot-1/visibility.json').read_text())['delivered'])

    def fixture(self, body):
        p = self.root / 'worker'
        p.write_text('#!/usr/bin/env python3\nimport json, sys, time\n' + body)
        p.chmod(0o700)
        return p

    def test_real_subprocess_records_tools_usage_and_requires_native_verification(self):
        exe = self.fixture('''sys.stdin.read()
for event in [
 {'type':'step_start','sessionID':'ses_1','part':{}},
 {'type':'tool_use','sessionID':'ses_1','part':{'tool':'read','state':{'status':'completed','output':'PRIVATE CONTENT'}}},
 {'type':'text','sessionID':'ses_1','part':{'text':'There are three lines.'}},
 {'type':'step_finish','sessionID':'ses_1','part':{'reason':'stop','cost':0.001,'tokens':{'input':10,'output':5,'reasoning':2,'cache':{'read':0,'write':0}}}}
]: print(json.dumps(event), flush=True)
''')
        run = self.api.prepare(self.root / 'runs', self.brief, now=100)
        result = self.api.execute(run, exe, self.root / 'auth', publish=lambda phase: None)
        self.assertEqual(result['state'], 'awaiting_verification')
        self.assertEqual(result['tools'], ['read'])
        self.assertAlmostEqual(result['reported_cost_usd'], 0.001)
        self.assertEqual(result['reported_tokens']['input'], 10)
        self.assertNotIn('PRIVATE CONTENT', (run / 'progress.jsonl').read_text())
        with self.assertRaises(ValueError): self.api.verify(run, 'accepted', [])
        self.assertEqual(self.api.verify(run, 'accepted', ['Native line count: 3; matches response'])['state'], 'accepted')

    def test_error_even_with_zero_exit_never_becomes_success(self):
        exe = self.fixture("print(json.dumps({'type':'error','error':{'message':'SECRET'}}))\n")
        run = self.api.prepare(self.root / 'runs', self.brief, now=100)
        result = self.api.execute(run, exe, self.root / 'auth')
        self.assertEqual(result['state'], 'failed')
        self.assertNotIn('SECRET', (run / 'progress.jsonl').read_text())

    def test_timeout_and_missing_finish_remain_unresolved(self):
        for body in ['time.sleep(5)\n', "print(json.dumps({'type':'text','part':{'text':'unfinished'}}))\n"]:
            with tempfile.TemporaryDirectory() as d:
                brief = dict(self.brief, timeout_seconds=1)
                run = self.api.prepare(Path(d).resolve(), brief, now=100)
                result = self.api.execute(run, self.fixture(body), self.root / 'auth')
                self.assertEqual(result['state'], 'unresolved')
                with self.assertRaises(ValueError): self.api.verify(run, 'accepted', ['self-reported success'])

    def test_malformed_part_is_persisted_as_unresolved(self):
        exe = self.fixture("print(json.dumps({'type':'step_finish','part':[]}))\n")
        run = self.api.prepare(self.root / 'runs', self.brief, now=100)
        self.assertEqual(self.api.execute(run, exe, self.root / 'auth')['state'], 'unresolved')
        self.assertEqual(json.loads((run / 'result.json').read_text())['state'], 'unresolved')

    def test_missing_step_cost_is_not_a_complete_total(self):
        exe = self.fixture("""for part in [{'reason':'tool-calls','cost':0.1}, {'reason':'stop'}]:
 print(json.dumps({'type':'step_finish','part':part}))
print(json.dumps({'type':'text','part':{'text':'answer'}}))
""")
        run = self.api.prepare(self.root / 'runs', self.brief, now=100)
        result = self.api.execute(run, exe, self.root / 'auth')
        self.assertIsNone(result['reported_cost_usd'])
        self.assertEqual(result['known_cost_subtotal_usd'], 0.1)
        self.assertFalse(result['accounting_complete'])

    def test_descendant_cannot_outlive_exited_leader(self):
        pidfile = self.root / 'descendant.pid'
        exe = self.fixture("""import os, signal
pid=os.fork()
if pid == 0:
 signal.signal(signal.SIGTERM, signal.SIG_IGN)
 os.close(1)
 time.sleep(20)
else:
 with open(%r,'w') as f: f.write(str(pid))
 time.sleep(.1)
""" % str(pidfile))
        run = self.api.prepare(self.root / 'runs', self.brief, now=100)
        self.api.execute(run, exe, self.root / 'auth')
        pid = int(pidfile.read_text())
        try:
            time.sleep(.1)
            with self.assertRaises(ProcessLookupError): os.kill(pid, 0)
        finally:
            try: os.kill(pid, signal.SIGKILL)
            except ProcessLookupError: pass


if __name__ == '__main__': unittest.main()
