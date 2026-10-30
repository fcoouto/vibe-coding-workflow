"""Read-only cap inputs use genuine enrolled owners; no cap deletion or native qualification."""

from contextlib import contextmanager
from pathlib import Path
import shutil
import time
import unittest
from unittest.mock import patch


class RetentionCapInputTests(unittest.TestCase):
    def test_actual_pressure_reaches_cap_inputs_after_age_guards_close(self):
        from runtime import changes, evidence, review_storage as storage, state
        from runtime.startup import StartupError, _canonical_plain
        from tests.test_detail_retention import DetailRetentionTests
        from tests.test_review_storage import ReviewStorageTests

        fixture = DetailRetentionTests(methodName='runTest')
        self.addCleanup(fixture.doCleanups)
        umbrella, api, context, cap, paths, original_details = fixture.umbrella_cap_fixture()
        temporary_root = umbrella.private / 'temporary-private'
        prepared = storage.prepare_storage(temporary_root)
        self.assertTrue(prepared.get('ok'), prepared)
        with storage._machine_guard() as (path, descriptor, parents):
            config = storage._configuration(path, descriptor)
            temporary = storage._ready_context(config, parents)
            with api._context_database(temporary) as db:
                self.assertEqual(storage._owners(config, temporary, db), [])
        with api._context_database(context) as db:
            original_rows = api._evidence_inventory_rows(db)
        original_stats = {row['reference']['name']: api._closure_file_stat(Path(row['metadata']['managed']['path']))
                          for row in original_rows}
        expected_directories = sorted({context.directory, temporary.directory})
        def snapshot():
            return (ReviewStorageTests.tree_snapshot(context.directory),
                    ReviewStorageTests.tree_snapshot(temporary.directory),
                    umbrella.authority.read_bytes(), umbrella.locator.read_bytes())
        before = snapshot()
        active, budgets, callbacks, guarded, reobserved, targets, subjects, censuses = [], [], [], [], [], [], [], []
        original_database = evidence._context_database
        original_guards = changes._authority_guards
        original_machine = storage._machine_guard
        original_acquire = storage._acquire_enrolled_accounting
        original_budget = storage._budget
        original_subject = evidence._source_subject
        original_inventory = evidence._historical_inventory
        original_census = evidence._cap_input_inventory

        def budget(*args, **kwargs):
            started = time.monotonic()
            value = original_budget(*args, **kwargs)
            self.assertGreater(value['deadline'], started)
            self.assertLessEqual(value['deadline'], time.monotonic() + 4)
            budgets.append(value)
            return value

        @contextmanager
        def database(selected, **options):
            if budgets:
                self.assertFalse(active, 'Cap-input readers must remain serial')
                self.assertFalse(options.get('write'), 'Cap-input observation opened a writer')
            with original_database(selected, **options) as db:
                active.append((selected, db))
                try:
                    yield db
                finally:
                    active.pop()

        @contextmanager
        def machine(**options):
            self.assertFalse(active, 'Cap acquisition began with an age reader open')
            self.assertFalse(getattr(changes._authority_context, 'held', ()),
                             'Cap acquisition began inside the age authority guard')
            with original_machine(**options) as acquired:
                yield acquired

        @contextmanager
        def guards(directories, *args, **options):
            directories = list(directories)
            machine_owner = storage._MACHINE_ACQUISITION.get()
            if machine_owner is not None:
                self.assertTrue(machine_owner['active'])
                self.assertFalse(active)
                self.assertEqual(directories, expected_directories,
                                 'Cap inputs require one sorted complete Project/temporary guard set')
                guarded.append(tuple(directories))
            with original_guards(directories, *args, **options) as held:
                yield held

        def subject(*args, **options):
            value = original_subject(*args, **options)
            if budgets:
                subjects.append((args[0], args[2], value))
            return value

        def inventory(*args, **options):
            self.assertIsNone(storage._MACHINE_ACQUISITION.get(),
                              'Cap-input size census reread the complete payload inventory')
            return original_inventory(*args, **options)

        def census(*args, **options):
            self.assertTrue(changes._held_authority_guards(expected_directories))
            self.assertIsNotNone(storage._MACHINE_ACQUISITION.get())
            value = original_census(*args, **options)
            entries = value['entries']
            self.assertEqual([entry['reference'] for entry in entries], [row['reference'] for row in original_rows])
            self.assertEqual([entry['metadata'] for entry in entries], [row['metadata'] for row in original_rows])
            self.assertEqual([entry['stat'] for entry in entries], [original_stats[row['reference']['name']] for row in original_rows])
            self.assertEqual(value['physical_bytes'], sum(item[5] for item in original_stats.values()))
            self.assertEqual(value['authority'], api._canonical_plain(context.authority_set[0]))
            candidates = value['candidates']
            self.assertTrue(candidates)
            self.assertEqual(candidates, sorted(candidates,
                key=lambda item: (item['closed_at'], item['created_at'], api._raw(item['reference']))))
            censuses.append(value)
            return value

        def acquire(target, *, deadline=None, budget=None, control=None):
            self.assertFalse(active)
            self.assertFalse(getattr(changes._authority_context, 'held', ()))
            self.assertIsNotNone(control, 'Pressure used ordinary accounting instead of the cap-input owner')
            self.assertIs(budget, budgets[0])
            targets.append(Path(target))
            owner = control
            class ObserveControl:
                def access(inner, **facts):
                    self.assertFalse(active, 'Cap-input callback entered with a reader open')
                    machine_owner = storage._MACHINE_ACQUISITION.get()
                    self.assertIsNotNone(machine_owner)
                    self.assertTrue(machine_owner['active'])
                    self.assertEqual(_canonical_plain(facts['project']), umbrella.record)
                    for field in ('directory', 'database', 'directory_binding', 'database_binding', 'authority_set'):
                        self.assertEqual(getattr(facts['project_context'], field), getattr(context, field))
                        self.assertEqual(getattr(facts['temporary_context'], field), getattr(temporary, field))
                    self.assertEqual(_canonical_plain(facts['accounting'])['temporary_history'],
                                     dict(complete=True, reason='authenticated_no_related_history'))
                    self.assertIs(facts['budget'], budget)
                    callbacks.append(facts['reobserve'])
                    reobserve = facts['reobserve']
                    def checked_reobserve():
                        self.assertFalse(active, 'Full cap reobservation entered with a reader open')
                        self.assertTrue(changes._held_authority_guards(expected_directories))
                        reobserved.append(True)
                        return reobserve()
                    return owner.access(**dict(facts, reobserve=checked_reobserve))
            return original_acquire(target, deadline=deadline, budget=budget, control=ObserveControl())

        with patch.object(storage, '_budget', side_effect=budget), \
                patch.object(evidence, '_context_database', side_effect=database), \
                patch.object(changes, '_authority_guards', side_effect=guards), \
                patch.object(storage, '_machine_guard', side_effect=machine), \
                patch.object(storage, '_acquire_enrolled_accounting', side_effect=acquire), \
                patch.object(evidence, '_source_subject', side_effect=subject), \
                patch.object(evidence, '_historical_inventory', side_effect=inventory), \
                patch.object(evidence, '_cap_input_inventory', side_effect=census), \
                patch.object(api, '_CLOSED_DETAIL_CAP_BYTES', cap):
            report = api._cleanup_closed_details(context)

        self.assertTrue(callbacks, 'Actual Project pressure did not reach cap-input callback')
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(len(budgets), 1, 'Cap-input observation reset its shared budget')
        self.assertEqual(len(guarded), 1)
        self.assertGreaterEqual(len(reobserved), 2)
        self.assertFalse(active)
        self.assertEqual(len(targets), 1)
        self.assertIn(targets[0], umbrella.members)
        self.assertTrue(any(selected.database == context.database and selected.database_binding == context.database_binding
                            and Path(value['identity']['repository_root']) == targets[0]
                            for selected, _, value in subjects),
                        'Cap target was not derived from an actual managed source subject')
        self.assertEqual(snapshot(), before, 'Read-only cap inputs changed actual enrolled storage')
        self.assertEqual([[path.read_bytes() for path in group] for group in paths], original_details)
        self.assertFalse(report['expired'])
        self.assertFalse(report['pending'])
        self.assertFalse(report['project']['complete'])
        self.assertIsNone(report['project']['cap_satisfied'])
        observed = report['cap_inputs']
        self.assertFalse(observed['complete'])
        self.assertEqual(observed['store_count'], 1, 'Shared physical Project store was counted more than once')
        self.assertEqual(observed['metadata_records'], len(original_rows))
        self.assertEqual(observed['physical_bytes'], sum(value[5] for value in original_stats.values()))
        self.assertEqual(len(censuses), 2)
        self.assertEqual(censuses[0], censuses[1])
        self.assertEqual(observed['potential_candidates'], len(censuses[0]['candidates']))
        self.assertNotIn('entries', observed)
        self.assertNotIn('stores', observed)
        with self.assertRaises(StartupError):
            callbacks[0]()


class RetentionCapInputControlTests(unittest.TestCase):
    def test_budget_creation_failure_preserves_original_age_report(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        from runtime import changes, evidence, review_storage as storage, state
        context = SimpleNamespace(directory=Path('/unused-cap-input-scheduling-control'))
        with patch.object(changes, '_authority_guards', return_value=nullcontext()), \
                patch.object(evidence, '_context_database', return_value=nullcontext(object())), \
                patch.object(evidence, '_evidence_inventory_rows', return_value=[]), \
                patch.object(evidence, '_closed_detail_accounting', return_value=dict(project=dict(
                    complete=False, cap_satisfied=None, excess_bytes=1))), \
                patch.object(storage, '_budget', side_effect=state.StateError('Initial cap deadline failed')):
            report = evidence._cleanup_closed_details(context)
        self.assertFalse(report['expired'])
        self.assertFalse(report['pending'])
        self.assertFalse(report['project']['complete'])
        self.assertIsNone(report['project']['cap_satisfied'])
        self.assertIn('Initial cap deadline failed', report['cap_inputs']['protected'])
        self.assertIsNone(evidence._CAP_INPUT_BUDGET.get())

    def test_nonpositive_or_unknown_age_pressure_does_not_acquire_cap_inputs(self):
        """Only the old report's scheduling hint is substituted; no cap validator succeeds here."""
        from contextlib import nullcontext
        from types import SimpleNamespace
        from runtime import changes, evidence
        context = SimpleNamespace(directory=Path('/unused-cap-input-scheduling-control'))
        for excess in (0, -1, None):
            with self.subTest(excess=excess), \
                    patch.object(changes, '_authority_guards', return_value=nullcontext()), \
                    patch.object(evidence, '_context_database', return_value=nullcontext(object())), \
                    patch.object(evidence, '_evidence_inventory_rows', return_value=[]), \
                    patch.object(evidence, '_closed_detail_accounting', return_value=dict(project=dict(
                        complete=False, cap_satisfied=None, excess_bytes=excess))), \
                    patch.object(evidence, '_closed_detail_cap_inputs') as acquire:
                report = evidence._cleanup_closed_details(context)
                acquire.assert_not_called()
                self.assertNotIn('cap_inputs', report)
                self.assertFalse(report['project']['complete'])
                self.assertIsNone(report['project']['cap_satisfied'])
                self.assertFalse(report['expired'])
                self.assertFalse(report['pending'])

    def test_genuine_related_sibling_history_blocks_control_with_shared_budget(self):
        """Real pre-enrollment producer; this proves history rejection, not closure/cap eligibility."""
        from runtime import evidence, review_storage as storage
        from tests.test_project_owner_enrolled import ProjectOwnerEnrolledTests
        owner = ProjectOwnerEnrolledTests(methodName='runTest')
        self.addCleanup(owner.doCleanups)
        prior = []
        def publish(fixture, record):
            self.assertTrue(storage.prepare_storage(fixture.private / 'temporary-state')['ok'])
            result = storage.resolve_owner(record['repositories'][1]['primary_root'])
            self.assertTrue(result['ok'], result)
            prior.append(result)
        fixture = owner.umbrella(publish)
        before = fixture.snapshot()
        calls = []
        class RejectEntry:
            def access(inner, **facts):
                calls.append(True)
                raise AssertionError('Related temporary history entered cap control')
        budget = storage._budget()
        token = evidence._CAP_INPUT_BUDGET.set(budget)
        try:
            result = storage._acquire_enrolled_accounting(fixture.members[0], budget=budget, control=RejectEntry())
        finally:
            evidence._CAP_INPUT_BUDGET.reset(token)
        self.assertEqual(len(prior), 1)
        self.assertFalse(result.get('ok'), result)
        self.assertEqual(calls, [])
        self.assertEqual(fixture.snapshot(), before)
        self.assertGreater(budget['bytes'], 0)

    def test_actual_cleanup_protects_missing_history_and_late_callback_changes(self):
        from runtime import evidence, review_storage as storage
        from runtime.startup import _canonical_plain
        from tests.test_detail_retention import DetailRetentionTests
        fixture = DetailRetentionTests(methodName='runTest')
        self.addCleanup(fixture.doCleanups)
        umbrella, api, context, cap, paths, original_details = fixture.umbrella_cap_fixture()
        with patch.object(api, '_CLOSED_DETAIL_CAP_BYTES', cap):
            missing = api._cleanup_closed_details(context)
        self.assertFalse(umbrella.locator.exists())
        self.assertEqual(missing['cap_inputs']['store_count'], 0)
        self.assertFalse(missing['project']['complete'])
        self.assertIsNone(missing['project']['cap_satisfied'])
        self.assertTrue(storage.prepare_storage(umbrella.private / 'temporary-private')['ok'])
        original_acquire = storage._acquire_enrolled_accounting
        original_witnesses = evidence._cap_input_witnesses
        original_census = evidence._cap_input_inventory
        stale = []
        for variant in ('target', 'stale-callback', 'unsupported-history', 'source', 'binding', 'raw-config', 'raw-canonical', 'physical'):
            restorations = []
            reached = []
            witness_calls, census_calls = [], []
            original_authority = umbrella.authority.read_bytes()
            original_config = umbrella.locator.read_bytes()
            def acquire(target, *, deadline=None, budget=None, control=None):
                owner = control
                class ObserveControl:
                    def access(inner, **facts):
                        reached.append(True)
                        if variant == 'target':
                            stale.append(facts['reobserve'])
                        elif variant == 'stale-callback':
                            facts['reobserve'] = stale[0]
                        elif variant == 'unsupported-history':
                            # Negative admission seam; original enrolled tests exercise real related-owner producers.
                            actual = _canonical_plain(facts['accounting'])
                            actual['temporary_history'] = dict(complete=True, reason='authenticated_retained_history')
                            facts['accounting'] = api._canonical_freeze(actual)
                        elif variant == 'source':
                            path = Path(owner.trigger['metadata']['managed']['path'])
                            raw, mode = path.read_bytes(), path.stat().st_mode & 0o777
                            path.chmod(0o600)
                            path.write_bytes(raw + b' ')
                            path.chmod(mode)
                            def restore():
                                path.chmod(0o600);path.write_bytes(raw);path.chmod(mode)
                            restorations.append(restore)
                        elif variant == 'binding':
                            saved = context.database.with_name('saved-runtime.sqlite3')
                            context.database.rename(saved)
                            shutil.copy2(saved, context.database)
                            def restore():
                                context.database.unlink();saved.rename(context.database)
                            restorations.append(restore)
                        return owner.access(**facts)
                if variant == 'target':
                    target = next(member for member in umbrella.members if member != Path(target))
                return original_acquire(target, deadline=deadline, budget=budget, control=ObserveControl())
            def witnesses(*args, **kwargs):
                result = original_witnesses(*args, **kwargs)
                witness_calls.append(True)
                if len(witness_calls) == 1:
                    if variant == 'raw-config':
                        umbrella.locator.write_bytes(original_config + b'\n')
                        restorations.append(lambda: umbrella.locator.write_bytes(original_config))
                    elif variant == 'raw-canonical':
                        umbrella.authority.write_bytes(original_authority + b'\n')
                        restorations.append(lambda: umbrella.authority.write_bytes(original_authority))
                return result
            def census(*args, **kwargs):
                result = original_census(*args, **kwargs)
                census_calls.append(True)
                if variant == 'physical' and len(census_calls) == 1:
                    unknown = context.directory / 'evidence' / 'unregistered-cap-input.json'
                    unknown.write_bytes(b'{}')
                    unknown.chmod(0o400)
                    restorations.append(unknown.unlink)
                return result
            try:
                with self.subTest(variant=variant), \
                        patch.object(storage, '_acquire_enrolled_accounting', side_effect=acquire), \
                        patch.object(evidence, '_cap_input_witnesses', side_effect=witnesses), \
                        patch.object(evidence, '_cap_input_inventory', side_effect=census), \
                        patch.object(api, '_CLOSED_DETAIL_CAP_BYTES', cap):
                    report = api._cleanup_closed_details(context)
                    self.assertTrue(reached, 'Negative control did not reach the actual enrolled callback')
                    self.assertFalse(report['project']['complete'])
                    self.assertIsNone(report['project']['cap_satisfied'])
                    self.assertFalse(report['expired'])
                    self.assertFalse(report['pending'])
                    self.assertEqual(report['cap_inputs']['potential_candidates'], 0)
                    self.assertTrue(report['cap_inputs']['protected'])
                    if variant.startswith('raw-') or variant == 'physical':
                        self.assertEqual(report['cap_inputs']['store_count'], 1,
                                         'Late failure discarded already observed truthful point counts')
                        self.assertTrue(any('changed' in reason or 'did not complete' in reason
                                            for reason in report['cap_inputs']['protected']))
            finally:
                for restore in reversed(restorations):
                    restore()
            self.assertEqual([[path.read_bytes() for path in group] for group in paths], original_details)
            self.assertIsNone(evidence._CAP_INPUT_BUDGET.get())

