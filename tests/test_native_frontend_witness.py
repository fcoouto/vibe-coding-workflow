"""Owned executable fixtures only; no result qualifies a real Codex frontend."""

from contextlib import contextmanager
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

from runtime import doctor, setup_observation, startup
from runtime.adapters import codex


class NativeFrontendFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='native-frontend-witness-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def api(self, module, name):
        value = getattr(module, name, None)
        self.assertIsNotNone(value, f'Owned frontend witness API is missing: {name}')
        return value

    def process(self, raw, *, arguments=('exec', '--json'), delay=0, deadline=None):
        executable = self.root/f'fixture-{len(list(self.root.iterdir()))}'
        executable.write_text(f'#!{sys.executable}\nimport sys,time\ntime.sleep({delay!r})\n'
                              f'sys.stdout.buffer.write({raw!r})\nsys.stdout.buffer.flush()\n')
        executable.chmod(0o700)
        child = doctor.NativeProcess([str(executable), *arguments],
            deadline if deadline is not None else time.monotonic()+2)
        self.addCleanup(child.close)
        return child

    def header(self, child):
        return self.api(child, 'cli_header')()



class NativeFrontendWitnessTests(NativeFrontendFixture):
    def test_owned_cli_header_has_exact_source_and_never_rpc_identity(self):
        raw = b'{"type":"thread.started","thread_id":"thread-fixture"}\n'
        child = self.process(raw)
        observed = startup._canonical_plain(self.header(child))
        self.assertEqual(observed['thread_id'], 'thread-fixture')
        self.assertEqual(observed['source']['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertIn(str(child.process.pid), observed['source']['reference'])
        self.assertIsNone(child.identity)
        self.assertNotIn('run_id', observed)

    def test_header_facts_are_deeply_immutable(self):
        child = self.process(b'{"type":"thread.started","thread_id":"thread-fixture"}\n')
        observed = self.header(child)
        with self.assertRaises(TypeError):
            observed['source']['sha256'] = 'f'*64

    def test_api_stdout_cannot_be_relabelled_as_cli_even_with_matching_header(self):
        child = self.process(b'{"type":"thread.started","thread_id":"thread-fixture"}\n',
            arguments=('app-server', '--listen', 'stdio://'))
        self.api(child, 'cli_header')
        with self.assertRaises(doctor.ObservationError):
            child.cli_header()
        self.assertEqual(child.bytes_read, 0)

    def test_exec_without_json_cannot_be_relabelled_as_cli(self):
        child = self.process(b'{"type":"thread.started","thread_id":"thread-fixture"}\n',
            arguments=('exec', 'fixture-prompt'))
        self.api(child, 'cli_header')
        with self.assertRaises(doctor.ObservationError):
            child.cli_header()
        self.assertEqual(child.bytes_read, 0)

    def test_malformed_header_does_not_expose_private_child_output(self):
        for raw in (b'PRIVATE_OUTPUT\n',
                    b'{"type":"thread.started","thread_id":"","private":"PRIVATE_OUTPUT"}\n',
                    b'{"type":"thread.started","thread_id":"one","thread_id":"two"}\n',
                    b'{"type":"turn.started"}\n'):
            with self.subTest(raw=raw):
                child = self.process(raw)
                self.api(child, 'cli_header')
                with self.assertRaises(doctor.ObservationError) as caught:
                    child.cli_header()
                self.assertNotIn('PRIVATE_OUTPUT', str(caught.exception))

    def test_header_respects_original_process_deadline(self):
        child = self.process(b'{"type":"thread.started","thread_id":"thread-fixture"}\n',
            delay=.2, deadline=time.monotonic()+.05)
        self.api(child, 'cli_header')
        with self.assertRaisesRegex(doctor.ObservationError, '^timeout$'):
            child.cli_header()

    def test_header_uses_existing_input_and_total_output_caps(self):
        child = self.process(b'{"type":"thread.started","thread_id":"'+b'x'*1024+b'"}\n')
        self.api(child, 'cli_header')
        with patch.object(doctor, 'MAX_OUTPUT', 100):
            with self.assertRaisesRegex(doctor.ObservationError, '^output_limit$'):
                child.cli_header()

    def test_d4_launch_options_reach_same_owned_child(self):
        descriptor, sender = os.pipe()
        self.addCleanup(os.close, descriptor)
        self.addCleanup(os.close, sender)
        os.write(sender, b'x')
        source = ('import json,os,sys\n'
                  'print(json.dumps(dict(cwd=os.getcwd(),value=os.environ.get("NATIVE_FIXTURE"),'
                  'session=os.getsid(0)==os.getpid(),fd=os.read(int(sys.argv[1]),1).decode())),flush=True)\n'
                  'print("PRIVATE_STDERR",file=sys.stderr,flush=True)\n')
        child = doctor.NativeProcess([sys.executable, '-I', '-B', '-c', source, str(descriptor)],
            time.monotonic()+2, cwd=self.root, env=dict(NATIVE_FIXTURE='original-allocation'),
            start_new_session=True, pass_fds=(descriptor,), stdin=subprocess.DEVNULL)
        self.addCleanup(child.close)
        raw = b''
        while b'\n' not in raw:
            chunk = child.read(child.deadline)
            self.assertTrue(chunk)
            raw += chunk
        self.assertEqual(json.loads(raw), dict(cwd=str(self.root),value='original-allocation',session=True,fd='x'))
        self.assertIsNone(child.process.stdin)
        self.assertIsNone(child.process.stderr)

    def test_public_witness_constructor_cannot_seal_caller_json(self):
        witness_type = self.api(doctor, 'NativeSetupWitness')
        with self.assertRaises(doctor.ObservationError):
            witness_type(dict(native=dict(surface='codex-cli'), observations={'startup-context': []}))

    def test_unissued_json_cannot_supply_witness_facts(self):
        read = self.api(doctor, '_native_witness_content')
        self.api(doctor, 'NativeSetupWitness')
        with self.assertRaises(doctor.ObservationError):
            read(dict(binding={}, native=dict(surface='codex-cli'), bootstrap=[dict(reference='fake', sha256='f'*64)]))

    def test_raw_attempt_rejected_by_real_core_before_any_native_io(self):
        observe = self.api(codex, 'observe_cli_basic')
        child = self.process(b'{"type":"thread.started","thread_id":"thread-fixture"}\n')
        with self.assertRaises(startup.StartupError):
            observe(child, {})
        self.assertEqual(child.bytes_read, 0)
        self.assertIsNone(child.identity)

    def test_managed_raw_attempt_cannot_observe_or_issue_case_evidence(self):
        observe = self.api(codex, 'observe_managed_case')
        child = self.process(b'{"type":"thread.started","thread_id":"thread-fixture"}\n')
        with self.assertRaises(startup.StartupError):
            observe(child, {}, {}, 'pre-tool-enforcement')
        self.assertEqual(child.bytes_read, 0)


class NativeCaptureFixtureTests(NativeFrontendFixture):
    """Only the trusted Core custody/retained-reader boundary is synthetic."""

    def setUp(self):
        super().setUp()
        self.home = self.root/'home'; self.home.mkdir()
        self.log = self.root/'rpc.jsonl'
        self.responses_path = self.root/'responses.json'
        self.responses = {
            'initialize': dict(codexHome=str(self.home),platformFamily='unix',platformOs='macos',userAgent='fixture'),
            'thread/read': dict(thread=dict(id='native-cli-thread',cwd=str(self.root),source='exec',originator='codex_exec',cliVersion='0.165.0')),
            'hooks/list': dict(data=[dict(cwd=str(self.root),hooks=[],errors=[],warnings=[])]),
            'config/read': dict(layers=[dict(name=dict(type='user',file=str(self.home/'config.toml')),
                config=dict(features=dict(hooks=True)),version='fixture')]),
            'configRequirements/read': dict(requirements=None)}
        self.executable = self.root/'codex-fixture'
        self.write_executable()
        self.identity = dict(repository_root=str(self.root),git_common_dir=str(self.root/'.git'),client='codex')

    def write_executable(self):
        self.responses_path.write_text(json.dumps(self.responses))
        if self.executable.exists():return
        self.executable.write_text(f'#!{sys.executable}\nimport json,sys\n'
            'if sys.argv[1]=="exec":\n print(json.dumps({"type":"thread.started","thread_id":"native-cli-thread"}),flush=True)\n'
            'else:\n'+f' responses=json.load(open({str(self.responses_path)!r}))\n'
            ' for line in sys.stdin:\n  request=json.loads(line)\n'+
            f'  with open({str(self.log)!r},"a") as stream: stream.write(json.dumps(request)+"\\n")\n'
            '  if "id" in request: print(json.dumps({"id":request["id"],"result":responses[request["method"]]}),flush=True)\n')
        self.executable.chmod(0o700)

    def owned(self, metadata=False, *, argv=None):
        arguments = argv if argv is not None else (
            ('app-server','--listen','stdio://') if metadata else ('exec','--json','PRIVATE_PROMPT'))
        child = doctor.NativeProcess([str(self.executable),*arguments],
            time.monotonic()+3,cwd=self.root,env=dict(CODEX_HOME=str(self.home),HOME=str(self.root),NATIVE_PRIVATE_VAR='PRIVATE_ENV'),
            stdin=subprocess.PIPE if metadata else subprocess.DEVNULL)
        self.addCleanup(child.close)
        return child

    @contextmanager
    def admitted(self, child, *, metadata=False, original=None, managed=False, bounded=False, declared_argv=None):
        decision = object()
        reference = dict(reference='fixture:metadata-attempt' if metadata else 'fixture:cli-attempt',sha256='a'*64)
        attempt = dict(reference=reference,task=dict(client='codex',session_id='native-cli-thread',task_id='fixture-task') if managed else None,
            native_sessions=['native-cli-thread'] if metadata or managed else [],
            limits=dict(deadline=time.time()+30,max_attempts=1,max_resource_units=1))
        if bounded:
            attempt['native_execution'] = dict(source_contract='bounded-native-source-v1', cwd=str(self.root),
                argv=list(child.argv) if declared_argv is None else declared_argv)
        if metadata:
            retained = self.root/'original-capture.json'
            raw = json.dumps(original,sort_keys=True,separators=(',',':')).encode();retained.write_bytes(raw)
            route = str(retained) + ('#native-observation:fixture:claim' if bounded else '')
            attempt['source_capture'] = dict(reference=route,sha256=hashlib.sha256(raw).hexdigest())
        projection = dict(identity=self.identity,target=dict(disposable=True),transaction_id='metadata-transaction' if metadata else 'cli-transaction',attempt=attempt)
        calls = []
        def validate(value, *, operation=None, case_id, process=None):
            if value is not decision or process is not child:
                raise startup.StartupError('Synthetic original process claim differs')
            calls.append((operation,case_id))
            return startup._canonical_freeze(projection)
        def source(value, *, process):
            validate(value,operation='observe-setup-metadata',case_id='startup-context',process=process)
            raw = retained.read_bytes()
            if hashlib.sha256(raw).hexdigest() != attempt['source_capture']['sha256']:
                raise startup.StartupError('Synthetic retained capture changed')
            return startup._canonical_freeze(json.loads(raw))
        with patch.object(setup_observation,'qualification_attempt_projection',side_effect=validate,create=True), \
                patch.object(setup_observation,'setup_capture_projection',side_effect=source,create=True), \
                patch.object(setup_observation,'setup_probe_projection',return_value=None,create=True), \
                patch.object(setup_observation,'setup_context_projection',return_value=None,create=True):
            yield decision,projection,calls

    def partial(self, *, argv=None, bounded=False):
        child = self.owned(argv=argv)
        with self.admitted(child,bounded=bounded) as (decision,projection,_):
            witness = self.api(codex,'observe_cli_basic')(child,decision)
        return doctor._native_witness_content(witness),projection

    def hook_isolation(self):
        inherited = [f'{self.home}/hooks.json:stop:0:{index}' for index in range(2)]
        override = 'hooks.state={' + ','.join(json.dumps(key) + '={enabled=false}' for key in reversed(inherited)) + '}'
        launch = ('exec','--json','--sandbox','read-only','-c',override,'--','PRIVATE_PROMPT')
        metadata = ('app-server','--listen','stdio://','-c',override)
        source = doctor.PACKAGE/'hooks/codex.json'
        definitions = json.loads(source.read_bytes())['hooks']
        hooks = self.responses['hooks/list']['data'][0]['hooks']
        for order, (name, groups) in enumerate(definitions.items()):
            event = name[0].lower() + name[1:]
            handler = groups[0]['hooks'][0]
            hooks.append(dict(key=f'fixture-plugin:{event}', eventName=event, sourcePath=str(source), source='plugin',
                currentHash='sha256:'+'a'*64, trustStatus='trusted', handlerType='command', enabled=True,
                isManaged=False, displayOrder=order, timeoutSec=handler['timeout'], matcher=groups[0].get('matcher'),
                command=handler['command'].replace('${PLUGIN_ROOT}', str(doctor.PACKAGE))))
        hooks.extend(dict(key=key, eventName='stop', sourcePath=str(self.home/'hooks.json'), source='user',
            enabled=False, isManaged=False) for key in inherited)
        config = self.responses['config/read']
        config['layers'].insert(0, dict(name=dict(type='sessionFlags'),
            config=dict(hooks=dict(state={key:dict(enabled=False) for key in inherited})), version='fixture'))
        config['config'] = dict(unrelated='x' * doctor.MAX_INPUT)
        self.write_executable()
        return inherited, launch, metadata

    def test_scoped_hook_isolation_correlates_owned_launch_and_large_native_metadata(self):
        inherited, launch, metadata = self.hook_isolation()
        original, _ = self.partial(argv=launch, bounded=True)
        retained = original['native']['threads'][0]['launch']
        self.assertIs(retained['configuration_overrides_present'], True)
        self.assertEqual(retained['disabled_inherited_hook_keys'], inherited)
        self.assertNotIn('PRIVATE_PROMPT', json.dumps(original))
        child = self.owned(metadata=True, argv=metadata)
        with self.admitted(child, metadata=True, original=original, bounded=True) as (decision, _, __):
            content = doctor._native_witness_content(codex.observe_setup_metadata(child, decision))
        self.assertEqual(content['native']['threads'][0]['launch'], retained)
        self.assertEqual(content['observations'], {})

    def test_scoped_hook_isolation_rejects_unverified_launch_and_metadata(self):
        inherited, launch, metadata = self.hook_isolation()
        original, _ = self.partial(argv=launch, bounded=True)
        for invalid in (launch[:5]+('hooks.state={}',)+launch[6:],
                        launch[:5]+(launch[5].replace('enabled=false','enabled=true'),)+launch[6:],
                        launch[:5]+(launch[5].replace('enabled=false','enabled=false,extra=false'),)+launch[6:],
                        launch[:5]+(launch[5]+'\n[features]\nhooks=false',)+launch[6:],
                        launch[:6]+('--disable','hooks')+launch[6:]):
            with self.subTest(argv=invalid), self.assertRaises(doctor.ObservationError):
                self.partial(argv=invalid, bounded=True)
        for arguments, bounded, declared in (
                (metadata[:3], True, None), (metadata, False, None),
                (metadata, True, [str(self.executable), *metadata[:3]]),
                (metadata[:4]+(metadata[4].replace(inherited[0], 'unknown'),), True, None)):
            child = self.owned(metadata=True, argv=arguments)
            with self.subTest(argv=arguments), self.admitted(child, metadata=True, original=original,
                    bounded=bounded, declared_argv=declared) as (decision, _, __), self.assertRaises(doctor.ObservationError):
                codex.observe_setup_metadata(child, decision)
            self.assertEqual(child.bytes_read, 0)

    def test_scoped_hook_isolation_rejects_conflicting_native_hook_metadata(self):
        from copy import deepcopy
        inherited, launch, metadata = self.hook_isolation()
        original, _ = self.partial(argv=launch, bounded=True)
        complete = deepcopy(self.responses)
        for mutation in ('missing layer', 'wrong flag', 'wrong key', 'active user hook', 'unknown user key',
                         'non-user key', 'untrusted candidate', 'active other plugin'):
            self.responses = deepcopy(complete)
            layers = self.responses['config/read']['layers']
            hooks = self.responses['hooks/list']['data'][0]['hooks']
            states = layers[0]['config']['hooks']['state']
            if mutation == 'missing layer': layers.pop(0)
            elif mutation == 'wrong flag': states[inherited[0]]['enabled'] = 0
            elif mutation == 'wrong key': states['other'] = states.pop(inherited[0])
            elif mutation == 'active user hook': hooks[-1]['enabled'] = True
            elif mutation == 'unknown user key': hooks.pop()
            elif mutation == 'non-user key': hooks[-1]['source'] = 'project'
            elif mutation == 'untrusted candidate': hooks[0]['trustStatus'] = 'untrusted'
            else: hooks.append(dict(hooks[0], key='other-plugin', sourcePath=str(self.home/'other-hooks.json')))
            self.write_executable()
            child = self.owned(metadata=True, argv=metadata)
            with self.subTest(mutation=mutation), self.admitted(child, metadata=True, original=original,
                    bounded=True) as (decision, _, __), self.assertRaises(doctor.ObservationError):
                codex.observe_setup_metadata(child, decision)

    def test_claimed_cli_issues_partial_witness_without_fabricated_behavior(self):
        content,projection = self.partial()
        self.assertEqual(content['binding']['attempt_ref'],projection['attempt']['reference'])
        self.assertEqual(content['binding']['transaction_id'],'cli-transaction')
        self.assertEqual(content['native']['threads'][0]['id'],'native-cli-thread')
        self.assertEqual(content['native']['executable']['path'],str(self.executable))
        self.assertEqual(content['native']['executable']['sha256'],hashlib.sha256(self.executable.read_bytes()).hexdigest())
        self.assertIsNone(content['native']['version'])
        self.assertIsNone(content['hooks'])
        self.assertEqual(content['observations'],{})
        self.assertTrue(content['bootstrap'])
        self.assertTrue(content['pending_reason'])
        retained=json.dumps(content)
        self.assertNotIn('PRIVATE_PROMPT',retained)
        self.assertNotIn('PRIVATE_ENV',retained)
        self.assertNotIn('argv',content['native']['threads'][0].get('launch',{}))
        self.assertEqual(content['native']['threads'][0]['launch']['cwd'],str(self.root))
        self.assertEqual(content['native']['threads'][0]['launch']['codex_home'],str(self.home))

    def test_metadata_combines_original_cli_with_only_fixed_exact_rpc_reads(self):
        original,_ = self.partial();child = self.owned(metadata=True)
        with self.admitted(child,metadata=True,original=original) as (decision,projection,calls):
            witness = self.api(codex,'observe_setup_metadata')(child,decision)
        content = doctor._native_witness_content(witness)
        self.assertEqual(content['binding']['attempt_ref'],projection['attempt']['reference'])
        self.assertEqual(content['binding']['transaction_id'],'metadata-transaction')
        self.assertEqual(content['native']['surface'],'codex-cli')
        self.assertEqual(content['native']['version'],'0.165.0')
        self.assertEqual(content['native']['threads'][0]['id'],'native-cli-thread')
        self.assertEqual(content['native']['threads'][0]['capture_binding'],original['binding'])
        self.assertEqual(content['native']['executable'],original['native']['executable'])
        self.assertEqual(content['hooks'],self.responses['hooks/list'])
        self.assertEqual(content['layers'],self.responses['config/read']['layers'])
        self.assertIsNone(content['requirements'])
        self.assertEqual(content['observations'],{})
        self.assertTrue(content['pending_reason'])
        self.assertTrue(all(ref in content['bootstrap'] for ref in original['bootstrap']))
        self.assertIn(projection['attempt']['source_capture'],content['bootstrap'])
        requests=[json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual([row['method'] for row in requests],['initialize','initialized','thread/read','hooks/list','config/read','configRequirements/read'])
        self.assertEqual(requests[2]['params'],dict(threadId='native-cli-thread',includeTurns=False))
        self.assertEqual(requests[3]['params'],dict(cwds=[str(self.root)]))
        self.assertEqual(requests[4]['params'],dict(cwd=str(self.root),includeLayers=True))
        self.assertIn(('observe-setup-metadata','startup-context'),calls)
        content['bootstrap'].clear()
        self.assertTrue(doctor._native_witness_content(witness)['bootstrap'])

    def test_foreign_process_is_rejected_before_cli_read(self):
        original = self.owned();foreign = self.owned()
        with self.admitted(original) as (decision,_,__):
            with self.assertRaises(startup.StartupError):
                self.api(codex,'observe_cli_basic')(foreign,decision)
        self.assertEqual(foreign.bytes_read,0)

    def test_metadata_rejects_wrong_native_surface_checkout_home_and_executable(self):
        for field,value in (('source','vscode'),('cwd','/different'),('codexHome','/different')):
            with self.subTest(field=field):
                original,_ = self.partial()
                branch='initialize' if field=='codexHome' else 'thread/read'
                selected=self.responses[branch] if branch=='initialize' else self.responses[branch]['thread']
                saved=selected[field];selected[field]=value;self.write_executable()
                # Recompute original executable pin: each subcase isolates metadata-field validation.
                original['native']['executable']['sha256']=hashlib.sha256(self.executable.read_bytes()).hexdigest()
                child=self.owned(metadata=True)
                with self.admitted(child,metadata=True,original=original) as (decision,_,__):
                    with self.assertRaises(doctor.ObservationError):
                        self.api(codex,'observe_setup_metadata')(child,decision)
                selected[field]=saved;self.write_executable()
        original,_=self.partial();original['native']['executable']['sha256']='f'*64
        child=self.owned(metadata=True)
        with self.admitted(child,metadata=True,original=original) as (decision,_,__):
            with self.assertRaises(doctor.ObservationError):
                self.api(codex,'observe_setup_metadata')(child,decision)
        self.assertEqual(child.bytes_read,0)

    def test_d4_process_and_attempt_cannot_replace_managed_task_ownership(self):
        child=self.owned()
        with self.admitted(child,managed=True) as (decision,_,calls):
            with self.assertRaises(startup.StartupError):
                self.api(codex,'observe_managed_case')(child,{},decision,'pre-tool-enforcement')
        self.assertEqual(child.bytes_read,0)
        self.assertEqual(calls,[])

    def test_metadata_raw_attempt_rejected_by_real_core_before_io(self):
        child=self.owned(metadata=True)
        with self.assertRaises(startup.StartupError):
            self.api(codex,'observe_setup_metadata')(child,{})
        self.assertEqual(child.bytes_read,0)


if __name__ == '__main__':
    unittest.main()
