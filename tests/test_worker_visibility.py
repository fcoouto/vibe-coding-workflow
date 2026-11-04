import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
import sys
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

from runtime.adapters import codex
from runtime.startup import StartupError


def fixture_transport(provider='codex'):
    client = SimpleNamespace(agents=[], events=[], unavailable=False)

    def snapshot(account):
        if client.unavailable:
            raise OSError('offline')
        return dict(accounts=[dict(id=account, provider=provider)],
                    agents=copy.deepcopy(client.agents), meta={})

    def event(account, value):
        client.events.append(copy.deepcopy(value))
        if value['hook_event_name'] == 'SubagentStart':
            client.agents.append(dict(id=account + ':' + value['agent_id'],
                parentId=account + ':' + value['session_id'], role=value['agent_type'], status='working'))

    def wire(binding, name, phase=None):
        value = dict(hook_event_name=name, session_id=binding['parent'],
                     agent_id=binding['agent_id'], agent_type=binding['label'], cwd=binding['cwd'])
        if phase is not None:
            value.update(tool_name=phase, tool_use_id='fixture-activity', tool_input={})
        return value

    return client, SimpleNamespace(Client=lambda endpoint: SimpleNamespace(snapshot=snapshot, event=event), _event=wire)


class VisibilityTests(unittest.TestCase):
    def setUp(self):
        try:
            from runtime import worker_visibility
        except ImportError:
            self.fail('Shared native/OpenRouter visibility implementation is missing')
        self.api = worker_visibility
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.root.chmod(0o700)
        self.metadata = dict(version=1, role='Reviewer', specialty='Security assessment',
                             custom_role_name='Threat reviewer · 東京')
        self.parent, self.child = str(uuid.uuid4()), str(uuid.uuid4())
        self.binding = dict(parent=self.parent, agent_id=self.child,
                            label='Threat reviewer · 東京 · Native model', cwd=str(self.root))
        self.client, self.transport = fixture_transport()

    def publisher(self, binding=None, metadata=None):
        return self.api.publisher(self.transport, 'http://127.0.0.1:1', 'account',
            binding or self.binding, metadata or self.metadata, self.root / 'delivery.json')

    def external_args(self):
        return dict(module=self.transport, endpoint='http://127.0.0.1:1', account='account',
                    parent='018e5cb4-73ab-7bed-ae5a-c912132405db', checkout=str(self.root),
                    run_id='fixture-run', execution_route='openai-api',
                    model_display_name='GPT-6.1 Sol', visibility=self.metadata | dict(role='Scout'),
                    state_directory=self.root)

    def test_external_registration_replays_exact_legacy_identity_and_canonical_label(self):
        args = self.external_args()
        external_id = 'e16ee46f-5dff-57a5-a771-6e5147660779'
        receipt = self.root / f'habblaud-{external_id}.json'
        for _ in range(2):
            self.assertEqual(self.api.register_external(**args), dict(delivered=True))
        self.assertEqual(self.client.events, [
            dict(hook_event_name=name, session_id=args['parent'], agent_id=external_id,
                 agent_type='Scout · GPT-6.1 Sol', cwd=str(self.root), **activity)
            for name, activity in (
                ('SubagentStart', {}),
                ('PreToolUse', dict(tool_name='completed', tool_use_id='fixture-activity', tool_input={})),
                ('SubagentStop', {}),
            )
        ])
        saved = json.loads(receipt.read_text())
        self.assertEqual(saved['visibility'], args['visibility'])
        self.assertTrue(saved['stopped'])
        self.client.agents.clear()
        self.assertEqual(self.api.register_external(**args),
                         dict(delivered=False, reason='visibility_unconfirmed'))
        self.assertEqual(len(self.client.events), 3)

    def test_external_registration_replays_flat_legacy_receipt_without_start(self):
        args = self.external_args()
        external_id = 'e16ee46f-5dff-57a5-a771-6e5147660779'
        receipt = self.root / f'habblaud-{external_id}.json'
        self.api.save(receipt, dict(delivered=True, agent_id=external_id, parent=args['parent'],
                                    account=args['account'], phase='completed', observed_at=1))
        self.assertEqual(self.api.register_external(**args),
                         dict(delivered=False, reason='visibility_unconfirmed'))
        self.assertEqual(self.client.events, [])
        self.client.agents.append(dict(id='account:' + external_id, parentId='account:' + args['parent'],
                                       role='Scout · GPT-6.1 Sol'))
        self.assertEqual(self.api.register_external(**args), dict(delivered=True))
        self.assertEqual([event['hook_event_name'] for event in self.client.events],
                         ['PreToolUse', 'SubagentStop'])

    def test_external_registration_preserves_conflicting_frozen_binding(self):
        args = self.external_args()
        external_id = 'e16ee46f-5dff-57a5-a771-6e5147660779'
        receipt = self.root / f'habblaud-{external_id}.json'
        binding = dict(parent=args['parent'], agent_id=external_id,
                       label='Scout · GPT-6.1 Sol', cwd=str(self.root))
        frozen = dict(version=1, binding=binding, visibility=args['visibility'], account=args['account'],
                      delivered=True, started=True, stopped=True, phase='completed')
        for change in (dict(label='Historical alias · GPT-6.1 Sol'), dict(parent=self.parent)):
            with self.subTest(change=change):
                self.api.save(receipt, frozen | dict(binding=binding | change))
                before = receipt.read_bytes()
                self.assertEqual(self.api.register_external(**args),
                                 dict(delivered=False, reason='visibility_binding_changed'))
                self.assertEqual(receipt.read_bytes(), before)
        self.api.save(receipt, frozen | dict(account='other-account'))
        before = receipt.read_bytes()
        self.assertEqual(self.api.register_external(**args),
                         dict(delivered=False, reason='visibility_binding_changed'))
        self.assertEqual(receipt.read_bytes(), before)
        self.assertEqual(self.client.events, [])

    def test_external_registration_never_relabels_conflicting_receiver_binding(self):
        args = self.external_args()
        external_id = 'e16ee46f-5dff-57a5-a771-6e5147660779'
        observed = dict(id='account:' + external_id, parentId='account:' + args['parent'],
                        role='Scout · GPT-6.1 Sol')
        for change in (dict(role='Historical alias · GPT-6.1 Sol'), dict(parentId='account:' + self.parent)):
            with self.subTest(change=change):
                self.client.agents = [observed | change]
                self.assertEqual(self.api.register_external(**args),
                                 dict(delivered=False, reason='habblaud_binding_mismatch'))
                self.assertEqual(self.client.agents, [observed | change])
        self.assertEqual(self.client.events, [])

    def test_external_registration_is_independent_of_host_and_namespaces_actual_route(self):
        client, module = fixture_transport(provider='second-host')
        args = self.external_args()
        account = 'second-account'
        main = dict(id=account + ':' + args['parent'], kind='main', account=account, provider='second-host')
        client.agents.append(main)
        observed, = module.Client(args['endpoint']).snapshot(account)['agents']
        self.assertEqual((observed['kind'], observed['account'], observed['provider']),
                         ('main', account, 'second-host'))
        args.update(module=module, account=account, parent=observed['id'].split(':', 1)[1])
        for route in ('openai-api', 'second-api'):
            self.assertEqual(self.api.register_external(**(args | dict(execution_route=route))),
                             dict(delivered=True))
        children = client.agents[1:]
        self.assertEqual({agent['id'] for agent in children}, {
            'second-account:e16ee46f-5dff-57a5-a771-6e5147660779',
            'second-account:5e9ba79b-2747-5a01-a931-c2947ccff669',
        })
        self.assertTrue(all(agent['parentId'] == main['id'] for agent in children))

    def test_external_registration_rejects_unsafe_inputs_without_delivery_or_receipt(self):
        args = self.external_args()
        unsafe = self.root / 'public'
        unsafe.mkdir()
        unsafe.chmod(0o755)
        for change in (dict(parent=args['parent'] + ':other'), dict(parent=object()),
                       dict(execution_route='openai-api:other'), dict(execution_route='../escape'),
                       dict(execution_route='x' * 257), dict(run_id='x' * 257), dict(run_id='line\nbreak'),
                       dict(run_id=' '), dict(model_display_name='x' * 161),
                       dict(model_display_name='visible\nhidden'), dict(checkout='x\x00y'),
                       dict(visibility=args['visibility'] | dict(source='private input')),
                       dict(state_directory=unsafe)):
            with self.subTest(change=change):
                self.assertEqual(self.api.register_external(**(args | change)),
                                 dict(delivered=False, reason='visibility_unavailable'))
        self.assertEqual(self.client.events, [])
        self.assertEqual(list(self.root.iterdir()), [unsafe])
        self.assertEqual(list(unsafe.iterdir()), [])

    def test_explicit_roles_and_custom_names_are_model_independent(self):
        cases = [
            (dict(version=1, role='Scout', specialty='Read'), 'Same model', 'Scout · Same model'),
            (dict(version=1, role='Reviewer', specialty='Review'), 'Same model', 'Reviewer · Same model'),
            (dict(version=1, role='Reviewer', specialty='Review'), 'Other model', 'Reviewer · Other model'),
            (self.metadata, 'Native model', 'Threat reviewer · 東京 · Native model'),
            (dict(version=1, role='Builder', specialty='Fix'), None, 'Builder · Model unknown'),
        ]
        for metadata, model, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(self.api.display_label(metadata, model), expected)
                self.assertEqual(self.api.declaration(metadata), metadata)

    def test_invalid_declarations_reject_without_silent_label_replacement(self):
        for change in (dict(role='Worker'), dict(version=True), dict(version=2),
                       dict(custom_role_name=''), dict(custom_role_name='x\ny'),
                       dict(custom_role_name='x' * 4097), dict(specialty='\t'), dict(extra='field')):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.api.declaration(self.metadata | change)

    def test_maximum_length_custom_name_reaches_transport_in_full(self):
        name = '界' * 4096
        model = '🌙' * 4096
        metadata = self.metadata | dict(custom_role_name=name, specialty='界' * 4096)
        try:
            label = self.api.display_label(metadata, model)
            result = self.publisher(binding=self.binding | dict(label=label), metadata=metadata)('Working')
        except ValueError as error:
            self.fail(f'Valid full label must fit the transport: {error}')
        self.assertTrue(result['delivered'])
        self.assertEqual(self.client.events[0]['agent_type'], name + ' · ' + model)

    def test_native_identity_and_full_custom_label_reach_first_event(self):
        result = self.publisher()('Working')
        self.assertTrue(result['delivered'])
        self.assertEqual(self.client.events[0], dict(hook_event_name='SubagentStart',
            session_id=self.parent, agent_id=self.child,
            agent_type='Threat reviewer · 東京 · Native model', cwd=str(self.root)))
        saved = json.loads((self.root / 'delivery.json').read_text())
        self.assertEqual(saved['visibility'], self.metadata)
        self.assertEqual(saved['binding']['agent_id'], self.child)

    def test_replay_and_continuation_do_not_create_another_character(self):
        self.publisher()('Working')
        self.publisher()('Reviewing')
        self.publisher()('accepted')
        self.publisher()('accepted')
        names = [event['hook_event_name'] for event in self.client.events]
        self.assertEqual(names.count('SubagentStart'), 1)
        self.assertEqual(names.count('SubagentStop'), 1)
        self.assertEqual({event['agent_id'] for event in self.client.events}, {self.child})

    def test_conflicting_first_binding_is_reported_without_relabel_or_duplicate(self):
        self.client.agents = [dict(id='account:' + self.child,
            parentId='account:' + self.parent, role='Worker', status='working')]
        result = self.publisher()('Working')
        self.assertFalse(result['delivered'])
        self.assertEqual(result['reason'], 'habblaud_binding_mismatch')
        self.assertEqual(self.client.events, [])

    def test_failed_delivery_freezes_labels_before_retry(self):
        self.client.unavailable = True
        self.assertFalse(self.publisher()('Working')['delivered'])
        self.client.unavailable = False
        changed = self.binding | dict(label='Different role · Native model')
        result = self.publisher(binding=changed)('Working')
        self.assertFalse(result['delivered'])
        self.assertEqual(result['reason'], 'visibility_binding_changed')
        self.assertEqual(self.client.events, [])
        self.assertTrue(self.publisher()('Working')['delivered'])

    def test_receiver_rejected_name_remains_explicit(self):
        metadata = self.metadata | dict(custom_role_name='Guardian reviewer')
        binding = self.binding | dict(label='Guardian reviewer · Native model')
        result = self.publisher(binding=binding, metadata=metadata)('Working')
        self.assertFalse(result['delivered'])
        self.assertEqual(result['reason'], 'unsupported_display_label')
        self.assertEqual(self.client.events, [])

    def test_unrelated_receipt_is_never_overwritten(self):
        path = self.root / 'delivery.json'
        frozen = dict(version=1, binding=self.binding, visibility=self.metadata,
                      account='account', delivered=True, started=True, stopped=False, phase='Working')
        for value in (dict(unrelated='keep'), frozen | dict(unrelated='keep'), frozen | dict(started=1)):
            with self.subTest(value=value):
                raw = json.dumps(value)
                path.write_text(raw)
                path.chmod(0o600)
                self.assertFalse(self.publisher()('Working')['delivered'])
                self.assertEqual(path.read_text(), raw)
        self.assertEqual(self.client.events, [])

    def test_receiver_reset_restores_active_binding_with_same_identity(self):
        self.assertTrue(self.publisher()('Working')['delivered'])
        self.client.agents.clear()
        self.assertTrue(self.publisher()('Continuing')['delivered'])
        starts = [event for event in self.client.events if event['hook_event_name'] == 'SubagentStart']
        self.assertEqual(len(starts), 2)
        self.assertEqual(starts[0], starts[1])


class NativeVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        home = Path(self.temp.name).resolve()
        self.root = home / 'checkout'
        self.root.mkdir(mode=0o700)
        self.task_context = home / 'task'
        self.task_context.mkdir(mode=0o700)
        self.parent, self.child = str(uuid.uuid4()), str(uuid.uuid4())
        self.parent_thread = dict(id=self.parent, cwd=str(self.root), cliVersion='0.163.0',
                                  source='exec', originator='codex_exec')
        self.child_thread = dict(id=self.child, parentThreadId=self.parent, cwd=str(self.root),
            cliVersion='0.163.0', model='Native model', modelProvider='native-account',
            source={'subAgent': {'thread_spawn': {'parent_thread_id': self.parent, 'agent_path': '/root/review_original'}}})
        self.spawn_prompt = None

    def reader(self, methods):
        from contextlib import contextmanager

        @contextmanager
        def reader():
            self.assertEqual(set(methods), {'initialize', 'thread/read'} |
                ({'thread/items/read'} if self.spawn_prompt is not None else set()))
            def request(method, params):
                if method == 'thread/items/read':
                    self.assertEqual(params, {'threadId': self.parent, 'turnId': 'parent-turn', 'itemIds': ['spawn']})
                    return dict(data=[dict(turnId='parent-turn', item=dict(id='spawn', type='collabAgentToolCall',
                        tool='spawnAgent', status='completed', senderThreadId=self.parent,
                        receiverThreadIds=[self.child], prompt=self.spawn_prompt))])
                self.assertEqual(method, 'thread/read')
                return dict(thread=copy.deepcopy(self.parent_thread if params['threadId'] == self.parent else self.child_thread))
            yield '0.163.0', request
        return reader()

    def observe(self):
        with patch.object(codex, '_native_reader', self.reader):
            return codex.observe_worker_visibility(self.root, self.parent, self.child)

    def test_ordinary_native_observation_needs_no_enrollment_or_database(self):
        self.assertTrue(hasattr(codex, 'observe_worker_visibility'), 'Native visibility observer is missing')
        value = self.observe()
        self.assertEqual(value['worker_id'], self.child)
        self.assertEqual(value['parent_session_id'], self.parent)
        self.assertEqual(value['configured_model'], 'Native model')
        self.assertIsNone(value['execution_model'])
        self.assertEqual(value['agent_path'], '/root/review_original')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_native_observation_rejects_unrelated_or_uncertain_lineage(self):
        self.assertTrue(hasattr(codex, 'observe_worker_visibility'), 'Native visibility observer is missing')
        for field, value in [('parentThreadId', str(uuid.uuid4())), ('cwd', '/other'), ('source', 'exec')]:
            original = copy.deepcopy(self.child_thread)
            self.child_thread[field] = value
            with self.subTest(field=field), self.assertRaises(StartupError):
                self.observe()
            self.child_thread = original

    def native_helper(self):
        path = Path(__file__).resolve().parents[1] / 'scripts' / 'worker_visibility.py'
        self.assertTrue(path.is_file(), 'Ordinary native visibility helper is missing')
        spec = importlib.util.spec_from_file_location('native_visibility_helper', path)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        return helper

    def test_original_start_event_gets_only_bound_private_label(self):
        helper = self.native_helper()
        request = self.native_request()
        path = helper.hook_context_path(self.task_context, self.parent, 'review_original')
        path.parent.mkdir(mode=0o700)
        helper.prepare_native(path, request)
        executable = Path(sys.executable).resolve()
        event = dict(hook_event_name='SubagentStart', session_id=self.parent,
                     agent_id=self.child, cwd=str(self.root), agent_type='default', extra='preserve')
        with patch.object(codex, 'observe_worker_visibility', return_value=self.observe()):
            actual = helper.enrich_start(event, self.task_context, self.root, executable)
            self.assertEqual(actual, event | dict(agent_role='Audit lead · Native model',
                                                   agent_type='Audit lead · Native model'))
            self.assertEqual(event['agent_type'], 'default')
            self.assertEqual(helper.enrich_start(event | dict(agent_role='Native reviewer'),
                                                 self.task_context, self.root, executable)['agent_role'], 'Native reviewer')
            other = event | dict(agent_id=str(uuid.uuid4()))
            self.assertEqual(helper.enrich_start(other, self.task_context, self.root, executable), other)
            unrelated = event | dict(cwd=str(self.task_context))
            self.assertEqual(helper.enrich_start(unrelated, self.task_context, self.root, executable), unrelated)

    def test_start_wrapper_preserves_original_bytes_and_exit_status(self):
        helper = self.native_helper()
        raw = b'not JSON\n' + b'x' * (130 * 1024)
        result = subprocess.run([sys.executable, '-I', '-B', helper.__file__, 'forward-start',
            '--context-directory', str(self.task_context), '--checkout', str(self.root),
            '--codex-executable', str(Path(sys.executable).resolve()), '--',
            sys.executable, '-c',
            'import sys; sys.stdout.buffer.write(sys.stdin.buffer.read()); sys.exit(7)'],
            input=raw, capture_output=True)
        self.assertEqual(result.stdout, raw)
        self.assertEqual(result.stderr, b'')
        self.assertEqual(result.returncode, 7)

    def test_native_binding_preserves_context_and_child_across_continuation(self):
        from runtime import worker_visibility
        helper = self.native_helper()
        client, transport = fixture_transport()
        path = self.task_context / 'assignment.json'
        request = dict(parent_session_id=self.parent, checkout=str(self.root), task_name='review_original',
                       visibility=dict(version=1, role='Reviewer', specialty='Read only', custom_role_name='Audit lead'))
        helper.prepare_native(path, request)
        self.assertEqual(client.events, [])
        with self.assertRaises(FileExistsError):
            helper.prepare_native(path, request | dict(visibility=request['visibility'] | dict(role='Builder')))
        with patch.object(codex, '_native_reader', self.reader), patch.object(worker_visibility, 'transport', return_value=transport):
            first = helper.publish_native(path, self.child, 'Reviewing', self.root, 'http://127.0.0.1:1', 'account')
            second = helper.publish_native(path, self.child, 'Continuing', self.root, 'http://127.0.0.1:1', 'account')
            replaced = helper.publish_native(path, str(uuid.uuid4()), 'Continuing', self.root, 'http://127.0.0.1:1', 'account')
        self.assertTrue(first['delivered'])
        self.assertTrue(second['delivered'])
        self.assertFalse(replaced['delivered'])
        self.assertEqual(replaced['reason'], 'native_visibility_identity_changed')
        self.assertEqual([e['hook_event_name'] for e in client.events].count('SubagentStart'), 1)
        self.assertEqual({e['agent_id'] for e in client.events}, {self.child})
        self.assertEqual({e['agent_type'] for e in client.events}, {'Audit lead · Native model'})
        saved = worker_visibility.read(path)
        self.assertEqual(saved['task_name'], 'review_original')
        self.assertEqual(saved['visibility'], request['visibility'])
        self.assertFalse(any(p.suffix in {'.db', '.sqlite', '.sqlite3'} for p in self.task_context.iterdir()))

    def test_no_native_character_when_child_lineage_is_unobserved(self):
        from runtime import worker_visibility
        helper = self.native_helper()
        client, transport = fixture_transport()
        path = self.task_context / 'assignment.json'
        helper.prepare_native(path, dict(parent_session_id=self.parent, checkout=str(self.root),
            task_name='review_original', visibility=dict(version=1, role='Reviewer', specialty='Read only')))
        self.child_thread['parentThreadId'] = str(uuid.uuid4())
        with patch.object(codex, '_native_reader', self.reader), patch.object(worker_visibility, 'transport', return_value=transport):
            result = helper.publish_native(path, self.child, 'Reviewing', self.root, 'http://127.0.0.1:1', 'account')
        self.assertFalse(result['delivered'])
        self.assertEqual(result['reason'], 'native_visibility_identity_unobserved')
        self.assertEqual(client.events, [])

    def native_request(self):
        return dict(parent_session_id=self.parent, checkout=str(self.root), task_name='review_original',
                    visibility=dict(version=1, role='Reviewer', specialty='Read only', custom_role_name='Audit lead'))

    def test_checkout_context_is_rejected_before_any_file_or_lock_write(self):
        helper = self.native_helper()
        path = self.root / 'assignment.json'
        with self.assertRaises(ValueError):
            helper.prepare_native(path, self.native_request())
        self.assertEqual(list(self.root.iterdir()), [])
        outside = self.task_context / 'assignment.json'
        helper.prepare_native(outside, self.native_request())
        path.write_bytes(outside.read_bytes())
        path.chmod(0o600)
        result = helper.publish_native(path, self.child, 'Working', self.root, 'http://127.0.0.1:1', 'account')
        self.assertFalse(result['delivered'])
        self.assertEqual(list(self.root.iterdir()), [path])

    def test_same_parent_is_insufficient_without_original_task_marker(self):
        from runtime import worker_visibility
        helper = self.native_helper()
        client, transport = fixture_transport()
        path = self.task_context / 'assignment.json'
        helper.prepare_native(path, self.native_request())
        del self.child_thread['source']['subAgent']['thread_spawn']['agent_path']
        with patch.object(codex, '_native_reader', self.reader), patch.object(worker_visibility, 'transport', return_value=transport):
            result = helper.publish_native(path, self.child, 'Reviewing', self.root, 'http://127.0.0.1:1', 'account')
        self.assertFalse(result['delivered'])
        self.assertEqual(result['reason'], 'native_visibility_identity_unobserved')
        self.assertEqual(client.events, [])

    def test_missing_native_path_can_use_exact_observed_spawn_binding(self):
        from runtime import worker_visibility
        helper = self.native_helper()
        del self.child_thread['source']['subAgent']['thread_spawn']['agent_path']
        for managed in (False, True):
            with self.subTest(managed=managed):
                client, transport = fixture_transport()
                path = self.task_context / f'assignment-{managed}.json'
                request = self.native_request()
                if managed:
                    body = dict(binding=dict(task_name=request['task_name']),
                                request=dict(visibility=request['visibility']))
                    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                    request['ledger_assignment_digest'] = digest
                    prepared = helper.prepare_native(path, request)
                    self.spawn_prompt = json.dumps(dict(ownership=body, ledger_assignment_digest=digest))
                else:
                    prepared = helper.prepare_native(path, request)
                    self.assertIn('prompt_marker', prepared)
                    self.spawn_prompt = prepared['prompt_marker'] + '\nRead only.'
                with patch.object(codex, '_native_reader', self.reader), patch.object(worker_visibility, 'transport', return_value=transport):
                    valid_prompt = self.spawn_prompt
                    self.spawn_prompt = 'Different assignment'
                    wrong = helper.publish_native(path, self.child, 'Reviewing', self.root, 'http://127.0.0.1:1', 'account',
                                                  parent_turn_id='parent-turn', spawn_item_id='spawn')
                    self.assertFalse(wrong['delivered'])
                    self.assertEqual(client.events, [])
                    self.spawn_prompt = valid_prompt
                    result = helper.publish_native(path, self.child, 'Reviewing', self.root, 'http://127.0.0.1:1', 'account',
                                                   parent_turn_id='parent-turn', spawn_item_id='spawn')
                self.assertTrue(result['delivered'])
                self.assertEqual(client.events[0]['agent_id'], self.child)
                self.assertEqual(client.events[0]['agent_type'], 'Audit lead · Native model')


if __name__ == '__main__':
    unittest.main()
