"""Native transport observations; subprocess fixtures never qualify a client."""

import sys
import time
import unittest
from unittest.mock import patch

from runtime.doctor import NativeProcess, ObservationError


class NativeProcessFixture:
    def process(self, notifications, **options):
        source = ('import json,sys\n'
                  'for line in sys.stdin:\n'
                  ' request=json.loads(line)\n'
                  ' if \"id\" not in request: continue\n'
                  f' for event in {notifications!r}: print(json.dumps(event),flush=True)\n'
                  ' print(json.dumps({"id":request["id"],"result":{"ok":True,"codexHome":"/fixture","platformFamily":"unix","platformOs":"macos","userAgent":"fixture"}}),flush=True)\n')
        child = NativeProcess([sys.executable, '-I', '-B', '-c', source],
                              time.monotonic() + 2, **options)
        self.addCleanup(child.close)
        return child


class NativeNotificationTests(NativeProcessFixture, unittest.TestCase):
    def test_opt_in_observer_receives_interleaved_native_hook_events(self):
        events = [dict(method='hook/started', params=dict(threadId='selected', run=dict(id='run'))),
                  dict(method='hook/completed', params=dict(threadId='selected', run=dict(id='run')))]
        observed = []
        child = self.process(events, on_notification=observed.append)
        self.assertTrue(child.request(1, 'thread/read', {})['ok'])
        self.assertEqual(observed, events)
        # Observations from the stream carry no automatic qualification or authority.
        self.assertFalse(hasattr(child, 'qualification'))

    def test_default_reader_still_discards_notifications(self):
        child = self.process([dict(method='hook/completed', params=dict(private='not logged'))])
        self.assertTrue(child.request(1, 'thread/read', {})['ok'])

    def test_malformed_notification_cannot_reach_observer(self):
        observed = []
        child = self.process([dict(method='hook/completed', result={})], on_notification=observed.append)
        with self.assertRaisesRegex(ObservationError, '^malformed_response$'):
            child.request(1, 'thread/read', {})
        self.assertEqual(observed, [])

    def test_observer_rejection_stops_request_without_returning_success(self):
        def reject(event):
            raise ObservationError('observation_rejected')
        child = self.process([dict(method='hook/completed', params={})], on_notification=reject)
        with self.assertRaisesRegex(ObservationError, '^observation_rejected$'):
            child.request(1, 'thread/read', {})

    def test_existing_output_limit_applies_before_observer_delivery(self):
        observed = []
        child = self.process([dict(method='hook/completed', params=dict(text='x' * 1000))],
                             on_notification=observed.append)
        with patch('runtime.doctor.MAX_OUTPUT', 100):
            with self.assertRaisesRegex(ObservationError, '^output_limit$'):
                child.request(1, 'thread/read', {})
        self.assertEqual(observed, [])

    def test_invalid_observer_is_rejected_before_starting_native_child(self):
        with patch('runtime.doctor.subprocess.Popen') as spawn:
            with self.assertRaisesRegex(ObservationError, '^invalid_observer$'):
                NativeProcess(['unused'], time.monotonic() + 1, on_notification={})
        spawn.assert_not_called()

    def test_native_reader_forwards_opt_in_observer_through_initialize_and_read(self):
        from runtime.adapters import codex
        event = dict(method='hook/completed', params=dict(threadId='selected', run=dict(id='run')))
        observed = []
        def spawn(argv, deadline, **options):
            return self.process([event], **options)
        with patch.object(codex, 'version', return_value='fixture'), \
                patch.object(codex.shutil, 'which', return_value='/fixture/codex'), \
                patch.object(codex, 'NativeProcess', side_effect=spawn):
            with codex._native_reader(codex.REVIEW_METHODS, on_notification=observed.append) as (_, request):
                self.assertTrue(request('thread/read', {})['ok'])
        self.assertEqual(observed, [event, event])


class ScopedHookCollectionTests(NativeProcessFixture, unittest.TestCase):
    def events(self):
        run = dict(id='run', eventName='preToolUse', source='plugin',
                   sourcePath='/candidate/hooks/codex.json', scope='turn',
                   executionMode='sync', handlerType='command', displayOrder=0,
                   startedAt=100, completedAt=None, durationMs=None, status='running',
                   entries=[dict(kind='context', text='PRIVATE_HOOK_OUTPUT')],
                   statusMessage='PRIVATE_STATUS')
        return [dict(method='hook/started', params=dict(threadId='selected', turnId='turn', run=run)),
                dict(method='hook/completed', params=dict(threadId='selected', turnId='turn',
                    run=dict(run, completedAt=101, durationMs=1, status='completed')))]

    def collector(self):
        from runtime.doctor import HookCollector
        return HookCollector(thread_id='selected', turn_id='turn', source_path='/candidate/hooks/codex.json')

    def test_scoped_pair_keeps_only_metadata_without_private_output(self):
        collector = self.collector()
        child = self.process(self.events(), on_notification=collector)
        self.assertTrue(child.request(1, 'thread/read', {})['ok'])
        snapshot = collector.snapshot()
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0]['status'], 'completed')
        self.assertEqual(snapshot[0]['thread_id'], 'selected')
        self.assertNotIn('PRIVATE', repr(snapshot))
        with self.assertRaises(TypeError):
            snapshot[0]['status'] = 'qualified'

    def test_other_session_turn_or_source_never_produces_observation(self):
        for field, value in [('threadId', 'other'), ('turnId', 'other'), ('sourcePath', '/other/hooks.json')]:
            with self.subTest(field=field):
                events = self.events()
                for event in events:
                    target = event['params']['run'] if field == 'sourcePath' else event['params']
                    target[field] = value
                collector = self.collector()
                self.assertTrue(self.process(events, on_notification=collector).request(1, 'read', {})['ok'])
                self.assertEqual(collector.snapshot(), ())

    def test_unpaired_changed_or_duplicate_completion_is_rejected(self):
        for mode in ('unpaired', 'changed', 'duplicate', 'malformed'):
            with self.subTest(mode=mode):
                events = self.events()
                if mode == 'unpaired': events = events[1:]
                if mode == 'changed': events[1]['params']['run']['eventName'] = 'stop'
                if mode == 'duplicate': events.append(events[-1])
                if mode == 'malformed': events[1]['params']['run']['completedAt'] = True
                collector = self.collector()
                with self.assertRaises(ObservationError):
                    self.process(events, on_notification=collector).request(1, 'read', {})
                with self.assertRaises(ObservationError):
                    collector.snapshot()

    def test_collection_limit_fails_without_publishing_partial_snapshot(self):
        events = []
        for index in range(65):
            pair = self.events()
            for event in pair: event['params']['run']['id'] = str(index)
            events.extend(pair)
        collector = self.collector()
        with self.assertRaises(ObservationError):
            self.process(events, on_notification=collector).request(1, 'read', {})
        with self.assertRaises(ObservationError): collector.snapshot()

    def test_thread_scoped_hook_can_carry_triggering_turn_binding(self):
        events = self.events()
        for event in events:
            event['params']['run'].update(eventName='sessionStart', scope='thread', id='r' * 512)
        collector = self.collector()
        self.assertTrue(self.process(events, on_notification=collector).request(1, 'read', {})['ok'])
        self.assertEqual(collector.snapshot()[0]['scope'], 'thread')
