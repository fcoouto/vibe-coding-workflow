"""Configuration transactions need file safety, not runtime qualification."""
import copy
import hashlib
from contextlib import contextmanager
from unittest.mock import patch

from runtime import changes, onboarding, review_storage, startup, state
from scripts.onboard_coordinator import run_verified_operation
from tests.fixture_canonical_birth import CanonicalBirthFixture, OnboardingFixture, ScopedBirthFixture


class PilotFilesFixture(ScopedBirthFixture):
    def setUp(self):
        super().setUp()
        (self.repo / 'docs').mkdir()

    def scoped_proposal(self):
        proposal = super().scoped_proposal()
        action = proposal['assessments']['repositories'][0]['actions'][0]
        action.update(target='docs/setup.md', before='absent', text='Pilot configuration\n',
            after=hashlib.sha256(b'Pilot configuration\n').hexdigest())
        return proposal


class FileConfigurationTests(CanonicalBirthFixture):
    def configuration(self, fixture_type=ScopedBirthFixture):
        fixture = fixture_type('runTest')
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        request = fixture.scoped_request()
        return fixture, request

    def operate(self, fixture, request, operation):
        decision = self.decision(fixture, request, operation, ())
        return run_verified_operation(decision, fixture.directory, request)

    def test_configuration_succeeds_without_runtime_or_qualification(self):
        fixture, request = self.configuration()
        with patch.object(changes, '_prepare_birth', side_effect=AssertionError('Unexpected runtime birth')):
            result = self.operate(fixture, request, 'apply')
        self.assertEqual(result['exit_code'], 0, result)
        self.assertEqual(result['activation_status'], 'configured')
        self.assertFalse(result['qualified'])
        self.assertNotIn('birth', changes._load_journal(fixture.directory))

    def test_configuration_checks_effects_without_revalidating_unrelated_inputs(self):
        fixture, request = self.configuration()
        fixture.source.unlink()
        (fixture.repo / 'README.md').write_text('unrelated edit\n')
        with patch.object(onboarding, '_package_pins', return_value=dict(onboarding._package_pins(), runtime_digest='e' * 64)):
            result = self.operate(fixture, request, 'apply')
        self.assertEqual(result['exit_code'], 0, result)
        self.assertEqual((fixture.repo / 'README.md').read_text(), 'unrelated edit\n')

    def test_rollback_ignores_new_package_missing_sources_and_unrelated_edits(self):
        fixture, request = self.configuration()
        original = (fixture.repo / 'AGENTS.md').read_bytes()
        self.assertEqual(self.operate(fixture, request, 'apply')['state'], 'applied')
        frozen = copy.deepcopy(changes._load_journal(fixture.directory))
        fixture.source.unlink()
        (fixture.repo / 'README.md').write_text('unrelated development\n')
        newer = dict(onboarding._package_pins(), runtime_digest='f' * 64)
        with patch.object(onboarding, '_package_pins', return_value=newer):
            for _ in range(2):
                result = self.operate(fixture, request, 'rollback')
                self.assertEqual(result['exit_code'], 0, result)
        self.assertEqual((fixture.repo / 'AGENTS.md').read_bytes(), original)
        self.assertEqual((fixture.repo / 'README.md').read_text(), 'unrelated development\n')
        self.assertFalse((fixture.repo / changes.PROJECT_FILE).exists())
        recovered = changes._load_journal(fixture.directory)
        for name in ('manifest', 'plan', 'approval'):
            self.assertEqual(recovered[name], frozen[name])

    def test_old_birth_history_is_retained_without_republication(self):
        prepared = self.prepare()
        fixture, request, _, directory = prepared
        result = self.invoke(prepared)
        self.assertEqual(result['state'], 'applied')
        self.assertIn('separately authorized operation', result['next_step'])
        database = directory / 'runtime.sqlite3'
        before = database.read_bytes()
        with patch.object(changes, '_birth_current_history', side_effect=AssertionError('Unrelated history gate')):
            result = self.operate(fixture, request, 'rollback')
        self.assertEqual(result['exit_code'], 0, result)
        self.assertEqual(database.read_bytes(), before)

    def test_pilot_two_created_files_recover_after_unrelated_history_growth(self):
        with patch('tests.fixture_canonical_birth.ScopedBirthFixture', PilotFilesFixture):
            prepared = self.prepare()
        fixture, request, _, directory = prepared
        self.assertEqual(self.invoke(prepared)['state'], 'applied')
        original = copy.deepcopy(changes._load_journal(fixture.directory))
        database = directory / 'runtime.sqlite3'
        retained = database.read_bytes()
        unrelated = OnboardingFixture('runTest')
        self.addCleanup(unrelated.doCleanups)
        unrelated.setUp()
        unrelated.scoped_inspect()
        onboarding.record_plan(unrelated.directory, unrelated.scoped_proposal())
        with review_storage._capture_birth_history(request['manifest']['enrollment']['record']) as (history, _):
            self.assertNotEqual(history['inventory'], original['birth']['intent']['history']['inventory'])
        with patch.object(onboarding, '_package_pins', return_value=dict(onboarding._package_pins(), runtime_digest='d' * 64)):
            result = self.operate(fixture, request, 'rollback')
        self.assertEqual(result['exit_code'], 0, result)
        for path in ('docs/setup.md', str(changes.PROJECT_FILE)):
            self.assertFalse((fixture.repo / path).exists())
        self.assertEqual(database.read_bytes(), retained)
        final = changes._load_journal(fixture.directory)
        for key in ('manifest', 'approval', 'plan'):
            self.assertEqual(final[key], original[key])
        self.assertEqual(final['birth']['certificate'], original['birth']['certificate'])

    def test_edited_or_replaced_output_is_preserved(self):
        for replace_inode in (False, True):
            with self.subTest(replace_inode=replace_inode):
                fixture, request = self.configuration()
                self.operate(fixture, request, 'apply')
                target = fixture.repo / 'AGENTS.md'
                raw = target.read_bytes() if replace_inode else b'user edit\n'
                if replace_inode:
                    replacement = target.with_suffix('.new')
                    replacement.write_bytes(raw)
                    replacement.replace(target)
                else:
                    target.write_bytes(raw)
                result = self.operate(fixture, request, 'rollback')
                self.assertEqual(result['exit_code'], 2, result)
                self.assertEqual(target.read_bytes(), raw)

    def test_corrupt_backup_blocks_restoration(self):
        fixture, request = self.configuration()
        self.operate(fixture, request, 'apply')
        journal = changes._load_journal(fixture.directory)
        receipt = next(iter(journal['receipts'].values()))
        (fixture.directory / receipt['files'][0]['backup']).write_bytes(b'corrupt')
        target = fixture.repo / 'AGENTS.md'
        before = target.read_bytes()
        result = self.operate(fixture, request, 'rollback')
        self.assertEqual(result['exit_code'], 2, result)
        self.assertEqual(target.read_bytes(), before)

    def test_approval_cannot_expand_effects(self):
        fixture, request = self.configuration()
        self.operate(fixture, request, 'apply')
        decision = self.decision(fixture, request, 'rollback', ())
        changed = copy.deepcopy(request)
        changed['manifest']['actions'][0]['effects'][0]['path'] = 'README.md'
        result = run_verified_operation(decision, fixture.directory, changed)
        self.assertNotEqual(result['exit_code'], 0, result)
        self.assertEqual((fixture.repo / 'README.md').read_text(), 'product\n')

    def test_missing_allocated_runtime_is_not_an_empty_store(self):
        prepared = self.prepare()
        fixture, request, _, directory = prepared
        self.assertEqual(self.invoke(prepared)['state'], 'applied')
        database = directory / 'runtime.sqlite3'
        database.rename(directory / 'retained.sqlite3')
        before = (fixture.repo / 'AGENTS.md').read_bytes()
        result = self.operate(fixture, request, 'rollback')
        self.assertEqual(result['exit_code'], 2, result)
        self.assertEqual((fixture.repo / 'AGENTS.md').read_bytes(), before)

    def test_runtime_disappearance_during_lock_acquisition_blocks_recovery(self):
        prepared = self.prepare()
        fixture, request, _, directory = prepared
        self.assertEqual(self.invoke(prepared)['state'], 'applied')
        database = directory / 'runtime.sqlite3'
        original_guard = changes._authority_guards
        @contextmanager
        def changed_under_guard(*args, **kwargs):
            with original_guard(*args, **kwargs) as guards:
                if database.exists():
                    database.rename(directory / 'retained.sqlite3')
                yield guards
        before = (fixture.repo / 'AGENTS.md').read_bytes()
        with patch.object(changes, '_authority_guards', changed_under_guard):
            result = self.operate(fixture, request, 'rollback')
        self.assertEqual(result['exit_code'], 2, result)
        self.assertEqual((fixture.repo / 'AGENTS.md').read_bytes(), before)

    def test_live_writer_blocks_file_recovery(self):
        prepared = self.prepare()
        fixture, request, _, directory = prepared
        self.assertEqual(self.invoke(prepared)['state'], 'applied')
        authority = fixture.repo / changes.PROJECT_FILE
        configured = authority.read_bytes()
        _, acquisition, _ = self.qualify_members(fixture, authority)
        scope = startup._entry_scope(acquisition)
        state.start_task(scope, dict(client='codex', session_id='live', task_id='live',
            scope_ref='fixture:live', mode='editable', decision_ref='fixture:authorized'))
        authority.write_bytes(configured)
        before = (fixture.repo / 'AGENTS.md').read_bytes()
        result = self.operate(fixture, request, 'rollback')
        self.assertEqual(result['exit_code'], 2, result)
        self.assertIn('writer', str(result['blocked']).lower())
        self.assertEqual((fixture.repo / 'AGENTS.md').read_bytes(), before)

    def test_substituted_authority_parent_is_preserved(self):
        fixture, request = self.configuration()
        self.assertEqual(self.operate(fixture, request, 'apply')['exit_code'], 0)
        parent = fixture.repo / changes.PROJECT_FILE.parent
        retained = fixture.repo / 'retained-config'
        parent.rename(retained)
        parent.symlink_to(retained, target_is_directory=True)
        before = (retained / changes.PROJECT_FILE.name).read_bytes()
        result = self.operate(fixture, request, 'rollback')
        self.assertEqual(result['exit_code'], 2, result)
        self.assertEqual((retained / changes.PROJECT_FILE.name).read_bytes(), before)

    def test_crashed_restore_reconciles_durable_receipts(self):
        for fixture_type in (ScopedBirthFixture, PilotFilesFixture):
            for checkpoint in ('rename', 'parent_fsync'):
                with self.subTest(fixture=fixture_type.__name__, checkpoint=checkpoint):
                    fixture, request = self.configuration(fixture_type)
                    original = (fixture.repo / 'AGENTS.md').read_bytes()
                    self.assertEqual(self.operate(fixture, request, 'apply')['exit_code'], 0)
                    reached = []
                    def crash(name):
                        if name == checkpoint and not reached:
                            reached.append(name)
                            raise RuntimeError('fixture: interrupted restore')
                    with patch.object(changes, '_checkpoint', side_effect=crash):
                        with self.assertRaisesRegex(RuntimeError, 'interrupted restore'):
                            self.operate(fixture, request, 'rollback')
                    self.assertEqual(reached, [checkpoint])
                    result = self.operate(fixture, request, 'rollback')
                    self.assertEqual(result['exit_code'], 0, result)
                    self.assertEqual((fixture.repo / 'AGENTS.md').read_bytes(), original)
                    self.assertFalse((fixture.repo / 'docs/setup.md').exists())
                    self.assertFalse((fixture.repo / changes.PROJECT_FILE).exists())

    def test_overlapping_operation_retains_ownership(self):
        fixture, request = self.configuration()
        self.assertEqual(self.operate(fixture, request, 'apply')['exit_code'], 0)
        before = (fixture.repo / 'AGENTS.md').read_bytes()
        git_dir = request['manifest']['owners'][0]['owner']['git_dir']
        with changes._worktree_lock(git_dir):
            result = self.operate(fixture, request, 'rollback')
        self.assertEqual(result['exit_code'], 2, result)
        self.assertEqual((fixture.repo / 'AGENTS.md').read_bytes(), before)
