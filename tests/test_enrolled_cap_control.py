"""Private enrolled controls use real disposable enrollment and inert callbacks."""

from contextlib import contextmanager
from contextvars import copy_context
import copy
import json
import os
from pathlib import Path
import shutil
import time
import unittest
from unittest.mock import patch

from runtime import changes, evidence, review_storage as storage, state
from runtime.startup import StartupError, _canonical_plain
from tests import test_enrolled_accounting_integration as enrolled_tests
from tests import test_project_owner_enrolled as owner_tests
from tests import test_review_storage as storage_tests


class InspectControl:
    def __init__(self, action=None):
        self.action = action
        self.calls = []

    def access(self, **facts):
        self.calls.append(facts)
        if self.action is not None:
            self.action(facts)
        return dict(inspected=True)


class EnrolledCapControlTests(unittest.TestCase):
    def fixture(self, prepare=True):
        fixture = enrolled_tests.EnrolledUmbrellaAccountingTests(methodName='runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        if prepare:
            result = storage.prepare_storage(fixture.private / 'temporary-state')
            self.assertTrue(result['ok'], result)
        return fixture

    def acquire(self, fixture, control, budget=None):
        helper = getattr(storage, '_acquire_enrolled_accounting', None)
        self.assertTrue(callable(helper), 'Private enrolled control acquisition is missing')
        return helper(fixture.members[0], control=control, budget=budget)

    @staticmethod
    def budget():
        return dict(paths=0, bytes=0, deadline=time.monotonic() + 15)

    def test_live_guard_actual_contexts_immutable_facts_and_serial_reobservation(self):
        fixture = self.fixture()
        ordinary = storage.acquire_enrolled_accounting(fixture.members[0])
        budget = self.budget()
        manager = evidence._context_database
        active = []
        acquisitions = []
        contexts = []
        selection = storage._enrolled_selection
        acquire = storage._acquire_canonical_membership

        @contextmanager
        def serial(context, **options):
            self.assertEqual(active, [], 'Seam readers must be serial')
            with manager(context, **options) as db:
                active.append((context, db))
                try:
                    yield db
                finally:
                    active.pop()

        def observe(*args, **options):
            self.assertIs(options['budget'], budget)
            value = acquire(*args, **options)
            acquisitions.append(value)
            return value

        def select(*args):
            result = selection(*args)
            contexts.append(result[3])
            return result

        def inspect(facts):
            self.assertEqual(active, [])
            acquired = storage._MACHINE_ACQUISITION.get()
            self.assertIsNotNone(acquired)
            self.assertEqual(acquired['path'], fixture.locator)
            self.assertEqual(os.fstat(acquired['descriptor']).st_ino, acquired['parents'][str(fixture.locator.parent)]['inode'])
            self.assertIs(facts['budget'], budget)
            self.assertEqual(_canonical_plain(facts['project']), fixture.record)
            self.assertEqual(_canonical_plain(facts['accounting']), ordinary)
            self.assertIs(facts['project_context'], contexts[0])
            self.assertEqual(facts['project_context'].database, fixture.storage / 'runtime.sqlite3')
            self.assertTrue(any(facts['temporary_context'] is context for context in acquired['contexts']))
            self.assertEqual(_canonical_plain(facts['config']), storage._configuration(acquired['path'], acquired['descriptor']))
            for value in (facts['project'], facts['config'], facts['accounting']):
                with self.assertRaises(TypeError):
                    value['changed'] = True
            directories = sorted({facts['project_context'].directory, facts['temporary_context'].directory})
            with changes._authority_guards(directories):
                self.assertTrue(changes._held_authority_guards(directories))
                facts['reobserve']()
                self.assertEqual(active, [])
                with evidence._context_database(facts['project_context']) as db:
                    self.assertIsNotNone(state._source_baseline(None, db, context=facts['project_context']))
                facts['reobserve']()
            observed = {_canonical_plain(item.observation)['root'] for item in acquisitions if item.observation is not None}
            self.assertTrue({str(member) for member in fixture.members} <= observed)

        control = InspectControl(inspect)
        def storage_bytes():
            return (storage_tests.ReviewStorageTests.tree_snapshot(fixture.storage),
                    storage_tests.ReviewStorageTests.tree_snapshot(fixture.private / 'temporary-state'),
                    fixture.authority.read_bytes(), fixture.locator.read_bytes())
        before = storage_bytes()
        with patch.object(evidence, '_context_database', side_effect=serial), \
                patch.object(storage, '_enrolled_selection', side_effect=select), \
                patch.object(storage, '_acquire_canonical_membership', side_effect=observe):
            result = self.acquire(fixture, control, budget)
        self.assertEqual(result, dict(inspected=True))
        self.assertEqual(len(control.calls), 1)
        self.assertTrue(storage_bytes() == before, 'Inert inspection must leave actual accounting storage unchanged')
        self.assertGreater(budget['paths'], 0)
        self.assertGreater(budget['bytes'], 0)

    def test_reobserve_rejects_expired_and_copied_acquisition(self):
        fixture = self.fixture()
        captured = []
        def inspect(facts):
            original = storage._MACHINE_ACQUISITION.get()
            captured.append(original)
            token = storage._MACHINE_ACQUISITION.set(dict(original))
            try:
                with self.assertRaises(StartupError):
                    facts['reobserve']()
            finally:
                storage._MACHINE_ACQUISITION.reset(token)
            facts['reobserve']()
        control = InspectControl(inspect)
        self.assertEqual(self.acquire(fixture, control, self.budget()), dict(inspected=True))
        reobserve = control.calls[0]['reobserve']
        with self.assertRaises(StartupError):
            reobserve()
        with storage._machine_guard():
            self.assertIsNot(storage._MACHINE_ACQUISITION.get(), captured[0])
            with self.assertRaises(StartupError):
                reobserve()

    def test_copied_context_cannot_revive_closed_callback_in_later_guard(self):
        fixture = self.fixture()
        captured = []
        def inspect(facts):
            captured.append((copy_context(), storage._MACHINE_ACQUISITION.get(), facts['reobserve']))
        self.assertEqual(self.acquire(fixture, InspectControl(inspect), self.budget()), dict(inspected=True))
        old_context, old_guard, reobserve = captured[0]
        with storage._machine_guard():
            current = storage._MACHINE_ACQUISITION.get()
            self.assertIsNot(current, old_guard)
            self.assertEqual(current['descriptor'], old_guard['descriptor'], 'Exercise actual descriptor reuse')
            with self.assertRaises(StartupError):
                old_context.run(reobserve)

    def test_live_acquisition_descriptor_path_and_parents_cannot_be_substituted(self):
        fixture = self.fixture()
        rejected = []
        def inspect(facts):
            machine = storage._MACHINE_ACQUISITION.get()
            replacement = os.open(fixture.private, os.O_RDONLY | os.O_DIRECTORY)
            try:
                for key, value in (('descriptor', replacement), ('path', fixture.locator.with_name('other.json')),
                                   ('parents', {})):
                    original = machine[key]
                    machine[key] = value
                    try:
                        with self.assertRaises(StartupError):
                            facts['reobserve']()
                        rejected.append(key)
                    finally:
                        machine[key] = original
                facts['reobserve']()
            finally:
                os.close(replacement)
        self.assertEqual(self.acquire(fixture, InspectControl(inspect), self.budget()), dict(inspected=True))
        self.assertEqual(rejected, ['descriptor', 'path', 'parents'])

    def test_temporary_screening_control_is_not_forwarded_to_enrolled_branch(self):
        fixture = self.fixture()
        scope = owner_tests.ProjectOwnerEnrolledTests.scope(fixture.record)
        control = InspectControl()
        before = fixture.snapshot()
        result = storage._project_owner_result(scope, control=control, budget=self.budget())
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'resolved')
        self.assertEqual(control.calls, [])
        self.assertTrue(fixture.snapshot() == before, 'Temporary screening control must remain separate')

    def test_public_default_preserves_signature_result_and_read_only_storage(self):
        import inspect
        self.assertEqual(str(inspect.signature(storage.acquire_enrolled_accounting)), '(target, *, deadline=None, budget=None)')
        for prepared in (False, True):
            with self.subTest(prepared=prepared):
                fixture = self.fixture(prepared)
                before = fixture.snapshot()
                public = storage.acquire_enrolled_accounting(fixture.members[0])
                helper = getattr(storage, '_acquire_enrolled_accounting', None)
                self.assertTrue(callable(helper), 'Private enrolled control acquisition is missing')
                self.assertEqual(helper(fixture.members[0]), public)
                self.assertTrue(public['ok'])
                self.assertEqual(public['temporary_history']['complete'], prepared)
                self.assertTrue(fixture.snapshot() == before, 'Public acquisition must remain read-only')
                self.doCleanups()

    def test_missing_and_bounded_history_never_enter_control(self):
        for variant in ('missing', 'bounded'):
            with self.subTest(variant=variant):
                fixture = self.fixture(variant != 'missing')
                control = InspectControl()
                before = fixture.snapshot()
                with patch.object(storage, 'MAX_RECORDS', 0 if variant == 'bounded' else storage.MAX_RECORDS):
                    result = self.acquire(fixture, control, self.budget())
                self.assertFalse(result['ok'])
                self.assertEqual(control.calls, [])
                self.assertTrue(fixture.snapshot() == before, 'Protected acquisition must not write storage')
                self.doCleanups()

    def test_real_related_sibling_history_never_enters_control(self):
        owner = owner_tests.ProjectOwnerEnrolledTests(methodName='runTest')
        self.addCleanup(owner.doCleanups)
        prior = []
        def publish(fixture, record):
            self.assertTrue(storage.prepare_storage(fixture.private / 'temporary-state')['ok'])
            result = storage.resolve_owner(record['repositories'][1]['primary_root'])
            self.assertTrue(result['ok'])
            prior.append(result)
        fixture = owner.umbrella(publish)
        before = fixture.snapshot()
        control = InspectControl()
        result = self.acquire(fixture, control, self.budget())
        self.assertFalse(result['ok'])
        self.assertEqual(control.calls, [])
        self.assertEqual(len(prior), 1)
        self.assertTrue(fixture.snapshot() == before, 'Related original owner and age must be preserved')

    def test_full_membership_preserves_excluded_removed_and_outside_observations(self):
        for variant in ('excluded', 'removed', 'outside', 'absent-authority'):
            with self.subTest(variant=variant):
                fixture = self.fixture()
                record = copy.deepcopy(fixture.record)
                sibling = record['repositories'][1]
                member = fixture.members[1]
                if variant == 'excluded':
                    record['membership']['exclude'] = [member.name]
                elif variant == 'outside':
                    record['membership']['include'] = [fixture.members[0].name]
                else:
                    sibling['membership'] = 'removed'
                    if variant == 'absent-authority':
                        outside = fixture.private / 'historical-outside'
                        member.rename(outside)
                        sibling['primary_root'] = str(outside)
                        sibling['git_common_dir'] = str(outside / '.git')
                        sibling['checkouts'][0]['root'] = str(outside)
                        sibling['checkouts'][0]['git_dir'] = str(outside / '.git')
                fixture.authority.write_text(json.dumps(record))
                control = InspectControl(lambda facts: facts['reobserve']())
                result = self.acquire(fixture, control, self.budget())
                self.assertEqual(result, dict(inspected=True))
                self.assertEqual(_canonical_plain(control.calls[0]['project']), record)
                self.doCleanups()

    def test_late_actual_changes_reject_full_reobservation(self):
        for variant in ('config', 'enrollment', 'baseline', 'parent', 'history'):
            with self.subTest(variant=variant):
                fixture = self.fixture()
                unrelated = None
                if variant == 'history':
                    other = storage_tests.ReviewStorageTests(methodName='runTest')
                    other.setUp()
                    self.addCleanup(other.doCleanups)
                    unrelated = storage.resolve_owner(other.repo)
                    self.assertTrue(unrelated['ok'])
                rejected = []
                def inspect(facts):
                    if variant == 'config':
                        config = json.loads(fixture.locator.read_text())
                        config['created_at'] += 1
                        fixture.locator.write_text(json.dumps(config))
                    elif variant == 'enrollment':
                        record = json.loads(fixture.authority.read_text())
                        record['membership']['future_join'] = not record['membership']['future_join']
                        fixture.authority.write_text(json.dumps(record))
                    elif variant == 'baseline':
                        path = facts['project_context'].directory / 'evidence' / fixture.baseline['reference']['name']
                        original = path.read_bytes()
                        path.chmod(0o600)
                        path.write_bytes(original + b' ')
                        path.chmod(0o400)
                    elif variant == 'parent':
                        original = fixture.locator.parent
                        moved = original.with_name('original-machine-parent')
                        original.rename(moved)
                        shutil.copytree(moved, original)
                    else:
                        path = facts['temporary_context'].directory / 'evidence' / unrelated['reference']['name']
                        original = path.read_bytes()
                        path.chmod(0o600)
                        path.write_bytes(original + b' ')
                        path.chmod(0o400)
                    try:
                        facts['reobserve']()
                    except StartupError:
                        rejected.append(True)
                        raise
                control = InspectControl(inspect)
                result = self.acquire(fixture, control, self.budget())
                self.assertEqual(rejected, [True])
                self.assertFalse(result['ok'])
                self.assertEqual(len(control.calls), 1)
                self.doCleanups()

    def test_changed_sibling_binding_and_unavailable_checkout_protect(self):
        for variant in ('binding', 'missing'):
            with self.subTest(variant=variant):
                fixture = self.fixture()
                member = fixture.members[1]
                if variant == 'binding':
                    saved = member.with_name('old-member')
                    member.rename(saved)
                    shutil.copytree(saved, member)
                else:
                    member.rename(member.with_name('missing-member'))
                control = InspectControl()
                result = self.acquire(fixture, control, self.budget())
                self.assertFalse(result['ok'])
                self.assertEqual(control.calls, [])
                self.doCleanups()

    def test_callback_failure_preserves_its_actual_partial_report(self):
        fixture = self.fixture()
        report = dict(observed=[])
        def inspect(facts):
            report['observed'].append(_canonical_plain(facts['accounting'])['reference'])
            raise StartupError('Inert callback stopped after observation')
        result = self.acquire(fixture, InspectControl(inspect), self.budget())
        self.assertFalse(result['ok'])
        self.assertEqual(report['observed'], [fixture.baseline['reference']])


if __name__ == '__main__':
    unittest.main()
