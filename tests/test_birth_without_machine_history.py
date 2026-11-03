"""Fresh D4 birth needs no unrelated temporary-review storage."""
import copy
import os
import json
from pathlib import Path
from unittest.mock import patch

from runtime import changes, evidence, onboarding, review_storage, state
from scripts.onboard_coordinator import run_verified_operation
from tests.fixture_canonical_birth import CanonicalBirthFixture


class BirthWithoutMachineHistoryTests(CanonicalBirthFixture):
    def recapture(self, prepared):
        fixture, request, decision, _ = prepared
        with review_storage._capture_birth_history(request['manifest']['enrollment']['record']) as (history, reobserve):
            reobserve()
            decision['creation']['intent'] = changes._birth_intent(fixture.plan(), request['manifest'],
                history, plan_dir=fixture.directory)

    def test_fresh_birth_and_undo_without_machine_storage(self):
        with patch.object(review_storage, 'prepare_storage', side_effect=AssertionError('Unrelated storage creation')):
            prepared = self.prepare(history=False)
            fixture, request, decision, directory = prepared
            machine = Path(review_storage._machine_config_path())
            self.assertFalse(os.path.lexists(machine.parent))
            original_request = copy.deepcopy(request)
            result = self.invoke(prepared)
        self.assertEqual(result['state'], 'applied', result)
        self.assertEqual(result['exit_code'], 2, result)
        self.assertFalse(result['qualified'])
        self.assertFalse(os.path.lexists(machine.parent))
        self.assertEqual(request, original_request)
        journal = changes._load_journal(fixture.directory)
        context = self.context(fixture)
        with evidence._context_database(context) as db:
            baseline = state._source_baseline(None, db, context=context)
            self.assertEqual(baseline['content']['runtime_digest'], request['manifest']['pins']['package_pins']['runtime_digest'])
            self.assertEqual(db.execute('select count(*) from checkouts').fetchone()[0], 1)
            self.assertEqual(db.execute('select count(*) from tasks').fetchone()[0], 0)
            self.assertEqual(evidence._read_birth_handoff(context, db)['certificate'], journal['birth']['certificate'])
        database_before = (directory / 'runtime.sqlite3').read_bytes()
        rollback = self.decision(fixture, request, 'rollback', (context,))
        result = run_verified_operation(rollback, fixture.directory, request)
        self.assertEqual(result['state'], 'rolled_back', result)
        self.assertEqual(result['exit_code'], 0, result)
        self.assertEqual((fixture.repo / 'AGENTS.md').read_text(), 'product rules\nlegacy process\n')
        self.assertEqual((directory / 'runtime.sqlite3').read_bytes(), database_before)
        self.assertFalse(os.path.lexists(machine.parent))
        recovered = changes._load_journal(fixture.directory)
        for name in ('manifest', 'plan', 'approval'):
            self.assertEqual(recovered[name], journal[name])
        self.assertEqual(recovered['birth']['certificate'], journal['birth']['certificate'])

    def test_existing_empty_machine_parent_needs_no_configuration(self):
        prepared = self.prepare(history=False)
        machine = Path(review_storage._machine_config_path())
        machine.parent.mkdir(mode=0o700)
        self.recapture(prepared)
        result = self.invoke(prepared)
        self.assertEqual(result['state'], 'applied', result)
        self.assertEqual(list(machine.parent.iterdir()), [])

    def test_destination_cannot_create_missing_machine_history_parents(self):
        fixture, request, _, _ = self.prepare(history=False)
        machine = Path(review_storage._machine_config_path())
        record = request['manifest']['enrollment']['record']
        record['repositories'][0]['checkouts'][0]['clients'][0]['configuration']['runtime']['state_dir'] = str(machine.parent / 'canonical-state')
        with review_storage._capture_birth_history(record) as (history, _):
            with self.assertRaisesRegex(state.StartupError, 'machine.*parent'):
                changes._birth_intent(fixture.plan(), request['manifest'], history, plan_dir=fixture.directory)
        self.assertFalse(machine.parent.exists())
        self.assertFalse((fixture.directory / 'transaction.json').exists())

    def test_destination_beneath_existing_machine_parent_is_supported(self):
        prepared = self.prepare(history=False)
        machine = Path(review_storage._machine_config_path())
        machine.parent.mkdir(mode=0o700)
        directory = machine.parent / 'canonical-state'
        record = prepared[1]['manifest']['enrollment']['record']
        record['repositories'][0]['checkouts'][0]['clients'][0]['configuration']['runtime']['state_dir'] = str(directory)
        prepared[1]['approval']['manifest_digest'] = onboarding._digest(prepared[1]['manifest'])
        prepared[2].update(self.decision(prepared[0], prepared[1], 'apply', ()))
        self.recapture(prepared)
        result = self.invoke(prepared)
        self.assertEqual(result['state'], 'applied', result)
        self.assertTrue((directory / 'runtime.sqlite3').exists())
        self.assertFalse(os.path.lexists(machine))

    def test_absence_callback_expires_and_cannot_escape(self):
        prepared = self.prepare(history=False)
        record = prepared[1]['manifest']['enrollment']['record']
        original_budget = review_storage._budget
        budgets = []
        def budget():
            result = original_budget()
            budgets.append(result)
            return result
        with patch.object(review_storage, '_budget', side_effect=budget):
            with review_storage._capture_birth_history(record) as (history, reobserve):
                self.assertEqual(history['version'], 2)
                captured = copy.deepcopy(history)
                deadline = budgets[0]['deadline']
                with patch.object(review_storage.time, 'monotonic', return_value=deadline + 1):
                    with self.assertRaisesRegex(state.StartupError, 'deadline'):
                        reobserve()
                self.assertEqual(history, captured)
            with self.assertRaises(state.StateError):
                reobserve()
            self.assertEqual(len(budgets), 1)
            self.assertEqual(budgets[0]['deadline'], deadline)

    def test_appearing_machine_parent_or_configuration_invalidates_capture(self):
        prepared = self.prepare(history=False)
        machine = Path(review_storage._machine_config_path())
        record = prepared[1]['manifest']['enrollment']['record']
        with review_storage._capture_birth_history(record) as (_, reobserve):
            machine.parent.mkdir(mode=0o700)
            with self.assertRaises(state.StateError):
                reobserve()
        with review_storage._capture_birth_history(record) as (_, reobserve):
            machine.write_text('{}')
            machine.chmod(0o600)
            with self.assertRaises(state.StateError):
                reobserve()

    def test_absence_witness_cannot_be_mutated_to_accept_replaced_parent(self):
        prepared = self.prepare(history=False)
        machine = Path(review_storage._machine_config_path())
        machine.parent.mkdir(mode=0o700)
        record = prepared[1]['manifest']['enrollment']['record']
        with review_storage._capture_birth_history(record) as (history, reobserve):
            moved = machine.parent.with_name('old-machine-parent')
            machine.parent.rename(moved)
            machine.parent.mkdir(mode=0o700)
            try:
                history['machine']['parents'][str(machine.parent)] = evidence._binding(machine.parent)
                with self.assertRaises(state.StateError):
                    reobserve()
            finally:
                machine.parent.rmdir()
                moved.rename(machine.parent)

    def test_configuration_appearing_during_checkout_observation_is_refused(self):
        prepared = self.prepare(history=False)
        machine = Path(review_storage._machine_config_path())
        machine.parent.mkdir(mode=0o700)
        original_observe = onboarding._checkout_observation
        def observe(*args):
            result = original_observe(*args)
            machine.write_text('{}')
            machine.chmod(0o600)
            return result
        with patch.object(onboarding, '_checkout_observation', side_effect=observe):
            with self.assertRaises(state.StateError):
                with review_storage._capture_birth_history(prepared[1]['manifest']['enrollment']['record']):
                    self.fail('Appearing machine configuration acquired')

    def test_invalid_machine_configuration_is_not_absence(self):
        prepared = self.prepare(history=False)
        machine = Path(review_storage._machine_config_path())
        machine.parent.mkdir(mode=0o700)
        record = prepared[1]['manifest']['enrollment']['record']
        for value in ('{', '{}', json.dumps(dict(version=1, state='initializing'))):
            with self.subTest(value=value):
                machine.write_text(value)
                machine.chmod(0o600)
                with self.assertRaises(review_storage._ERRORS):
                    with review_storage._capture_birth_history(record):
                        self.fail('Invalid history acquired')
        machine.unlink()
        machine.symlink_to(machine.with_name('missing-machine'))
        with self.assertRaises(review_storage._ERRORS):
            with review_storage._capture_birth_history(record):
                self.fail('Broken machine link acquired')

    def test_missing_ready_store_is_not_absence(self):
        prepared = self.prepare()
        machine = Path(review_storage._machine_config_path())
        original = json.loads(machine.read_text())
        database = Path(original['authority']['database'])
        database.rename(database.with_suffix('.missing'))
        with self.assertRaises(review_storage._ERRORS):
            with review_storage._capture_birth_history(prepared[1]['manifest']['enrollment']['record']):
                self.fail('Missing original ready store acquired')
        self.assertEqual(json.loads(machine.read_text()), original)
        self.assertFalse(database.exists())

    def test_later_unrelated_machine_storage_preserves_birth_and_accounting(self):
        prepared = self.prepare(history=False)
        fixture = prepared[0]
        self.assertEqual(self.invoke(prepared)['state'], 'applied')
        journal = changes._load_journal(fixture.directory)
        certificate = copy.deepcopy(journal['birth']['certificate'])
        before = (prepared[3] / 'runtime.sqlite3').read_bytes()
        resolved = review_storage.resolve_owner(fixture.repo)
        self.assertTrue(resolved['ok'], resolved)
        self.assertEqual(resolved['owner']['kind'], 'project')
        self.assertTrue(review_storage.prepare_storage(prepared[3].parent / 'later-private')['ok'])
        review_storage._retained_birth_history(certificate)
        resolved = review_storage.resolve_owner(fixture.repo)
        self.assertTrue(resolved['ok'], resolved)
        self.assertEqual((prepared[3] / 'runtime.sqlite3').read_bytes(), before)
        self.assertEqual(changes._load_journal(fixture.directory)['birth']['certificate'], certificate)

    def test_absent_history_cannot_claim_related_owners(self):
        prepared = self.prepare(history=False)
        history = prepared[2]['creation']['intent']['history']
        for name in ('inventory', 'related', 'screening_sources'):
            invalid = copy.deepcopy(history)
            invalid[name].append({})
            with self.subTest(name=name), self.assertRaises(state.StateError):
                review_storage._birth_history_shape(invalid)

    def test_later_related_history_blocks_without_changing_original_receipts(self):
        prepared = self.prepare(history=False)
        fixture = prepared[0]
        self.assertTrue(review_storage.prepare_storage(prepared[3].parent / 'retained-private')['ok'])
        owner = review_storage.resolve_owner(fixture.repo)
        self.assertTrue(owner['ok'], owner)
        machine = Path(review_storage._machine_config_path())
        retained_machine = machine.with_name('retained-machine.json')
        original = machine.read_bytes()
        config = json.loads(original)
        database = Path(config['authority']['database'])
        database_before = database.read_bytes()
        machine.rename(retained_machine)
        self.recapture(prepared)
        self.assertEqual(self.invoke(prepared)['state'], 'applied')
        certificate = changes._load_journal(fixture.directory)['birth']['certificate']
        retained_machine.rename(machine)
        with self.assertRaises(state.StateError):
            review_storage._retained_birth_history(certificate)
        resolved = review_storage.resolve_owner(fixture.repo)
        self.assertFalse(resolved['ok'], resolved)
        self.assertEqual(machine.read_bytes(), original)
        self.assertEqual(database.read_bytes(), database_before)
        self.assertEqual(changes._load_journal(fixture.directory)['birth']['certificate'], certificate)

    def test_committed_birth_crash_resumes_original_no_history_allocation(self):
        prepared = self.prepare(history=False)
        fixture, request, decision, directory = prepared
        def crash(stage):
            if stage == 'birth-committed':
                raise RuntimeError('birth crash')
        with patch.object(changes, '_checkpoint', side_effect=crash), self.assertRaises(RuntimeError):
            self.invoke(prepared)
        journal = changes._load_journal(fixture.directory)
        allocation = copy.deepcopy(journal['birth']['allocation'])
        context = self.context(fixture)
        with evidence._context_database(context) as db:
            baseline = evidence._canonical_plain(state._source_baseline(None, db, context=context))
        certificate = dict(version=1, intent=decision['creation']['intent'], allocation=allocation,
            baseline={key: baseline[key] for key in ('reference', 'content')},
            seed_digest=onboarding._digest(changes._birth_seed(None, decision['creation']['intent'])))
        recovery = copy.deepcopy(decision)
        recovery['operation'] = 'resume'
        recovery['creation']['resume'] = dict(intent_digest=journal['birth']['intent_digest'], allocation=allocation,
            baseline=certificate['baseline'], certificate_digest=onboarding._digest(certificate))
        result = run_verified_operation(recovery, fixture.directory, request)
        self.assertEqual(result['state'], 'applied', result)
        resumed = changes._load_journal(fixture.directory)
        self.assertEqual(resumed['birth']['allocation'], allocation)
        self.assertEqual(resumed['birth']['certificate'], certificate)
        self.assertTrue((directory / 'runtime.sqlite3').exists())
        self.assertFalse(os.path.lexists(Path(review_storage._machine_config_path()).parent))
