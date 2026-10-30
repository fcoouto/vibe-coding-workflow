"""Actual configured birth readers and late canonical drift; no native qualification."""
from contextlib import contextmanager
import time
import unittest
from unittest.mock import patch

from runtime import changes, evidence, review_storage as storage, state
from tests import test_canonical_birth as birth_tests
from tests.test_enrolled_cap_control import InspectControl


class EnrolledHistorySerialTests(unittest.TestCase):
    def birth(self, *, umbrella=False, history=False):
        fixture=birth_tests.CanonicalBirthTests(methodName='runTest')
        self.addCleanup(fixture.doCleanups)
        prepared=fixture.prepare(umbrella=umbrella,history=history)
        self.assertEqual(fixture.invoke(prepared)['exit_code'],2)
        f,_,_,directory=prepared
        certificate=changes._load_journal(f.directory)['birth']['certificate']
        canonical=changes._recovery_context(certificate['allocation']['authority'])
        return f,canonical,certificate

    def test_genuine_empty_birth_retains_authenticated_certificate_with_serial_readers(self):
        f,canonical,certificate=self.birth()
        manager=evidence._context_database;active=[];events=[]
        @contextmanager
        def serial(context,**options):
            self.assertEqual(active,[],'Configured birth seam readers must be serial')
            with manager(context,**options) as db:
                active.append(context);events.append(context.database)
                try:yield db
                finally:active.pop()
        with patch.object(evidence,'_context_database',side_effect=serial):
            result=storage.acquire_enrolled_accounting(f.repo)
        self.assertTrue(result['ok'],result)
        self.assertEqual(active,[])
        temporary=sum(path!=canonical.database for path in events)
        self.assertGreaterEqual(temporary,2)
        self.assertGreaterEqual(events.count(canonical.database),2*temporary)
        self.assertEqual(result['temporary_history']['handoff']['certificate_digest'],evidence._digest(certificate))

    def test_late_real_birth_handoff_dependency_change_after_temporary_close_is_rejected(self):
        f,canonical,certificate=self.birth()
        manager=evidence._context_database;active=[];temporary_closes=[];changed=[]
        @contextmanager
        def late(context,**options):
            # This negative allows the old nesting so RED isolates missing closing recheck.
            with manager(context,**options) as db:
                active.append(context)
                try:yield db
                finally:active.pop()
            if context.database!=canonical.database and not options.get('write',False):
                temporary_closes.append(context.database)
                if len(temporary_closes)==3:
                    self.assertEqual(active,[],'Late mutation must follow actual reader closure')
                    with manager(canonical,write=True) as writer:
                        baseline=state._source_baseline(None,writer,context=canonical)
                        metadata=state._metadata(writer,baseline['reference']['name'])
                        self.assertTrue(metadata['dependencies'])
                        metadata['dependencies']=[]
                        writer.execute('update evidence_metadata set data=? where name=?',
                            (evidence._raw(metadata).decode(),baseline['reference']['name']))
                    changed.append(True)
        control=InspectControl()
        budget=dict(paths=0,bytes=0,deadline=time.monotonic()+15)
        with patch.object(evidence,'_context_database',side_effect=late):
            result=storage._acquire_enrolled_accounting(f.repo,control=control,budget=budget)
        self.assertEqual(changed,[True])
        self.assertNotIn('inspected',result,'Late canonical drift must not reach the control')
        self.assertEqual(control.calls,[])
        self.assertFalse(result['ok'],result)
        self.assertEqual(active,[])

    def test_real_umbrella_screening_history_has_serial_readers_and_original_owners(self):
        f,canonical,certificate=self.birth(umbrella=True,history=True)
        expected=certificate['intent']['history']
        self.assertTrue(expected['related'])
        self.assertTrue(expected['screening_sources'])
        manager=evidence._context_database;active=[]
        @contextmanager
        def serial(context,**options):
            self.assertEqual(active,[],'Screening birth readers must be serial')
            with manager(context,**options) as db:
                active.append(context)
                try:yield db
                finally:active.pop()
        with patch.object(evidence,'_context_database',side_effect=serial):
            result=storage.acquire_enrolled_accounting(f.repo)
        self.assertTrue(result['ok'],result)
        self.assertEqual(active,[])
        self.assertEqual({evidence._raw(row['reference']) for row in result['temporary_history']['owners']},
                         {evidence._raw(reference) for reference in expected['related']})
        self.assertEqual(result['temporary_history']['handoff']['certificate_digest'],evidence._digest(certificate))
