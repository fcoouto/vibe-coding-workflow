"""Basic adoption observes its selected inputs without a repository census."""
import copy
import hashlib
from pathlib import Path
from unittest.mock import patch

from runtime import changes, onboarding
from runtime.startup import StartupError
from tests.fixture_canonical_birth import CanonicalBirthFixture, ScopedBirthFixture
from tests import test_file_configuration as file_configuration


class RelevantFixture(ScopedBirthFixture):
    def setUp(self):
        super().setUp()
        (self.repo / 'config.json').write_text('{}\n')

    def scoped_inspect(self, **_):
        record = self.project_record(files=['README.md', 'config.json'])
        record['project_scope']['inspection_scope'] = 'relevant'
        report = onboarding.inspect_project(self.repo, self.directory, record)
        self.assertTrue(all(row['scope'].endswith('/proposal') for row in report['blockers']), report)
        return self.repo, record


class RelevantOnboardingTests(CanonicalBirthFixture):
    operate = file_configuration.FileConfigurationTests.operate

    def configuration(self):
        fixture = RelevantFixture('runTest')
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        return fixture

    def test_large_unrelated_repository_inspect_record_apply_and_undo(self):
        fixture = self.configuration()
        unrelated = fixture.repo / 'unrelated'
        unrelated.mkdir()
        for index in range(4100):
            (unrelated / str(index)).write_bytes(b'x' * 3072)
        original = (fixture.repo / 'AGENTS.md').read_bytes()
        actual_read = onboarding._read_file

        def selected_only(path, *args, **kwargs):
            self.assertFalse(Path(path).is_relative_to(unrelated), 'Unrelated content was opened')
            return actual_read(path, *args, **kwargs)

        with patch.object(onboarding, '_read_file', side_effect=selected_only):
            request = fixture.scoped_request()
            plan = fixture.plan()
            self.assertEqual(plan['status'], 'ready_for_review', plan['blockers'])
            snapshot = plan['assessments']['repositories'][0]['identity']['snapshot']
            self.assertFalse({'head', 'index_digest', 'dirty_inventory', 'inventory_version'} & snapshot.keys())
            self.assertEqual(set(snapshot['paths']), {'README.md', 'config.json', 'AGENTS.md'})
            self.assertEqual(len(plan['requirements']), len(onboarding._requirements(fixture.record)))
            (unrelated / '0').write_text('later unrelated edit\n')
            self.assertEqual(self.operate(fixture, request, 'apply')['state'], 'applied')
            self.assertEqual(self.operate(fixture, request, 'resume')['state'], 'applied')
            (fixture.repo / 'config.json').write_text('later selected input edit\n')
            self.assertEqual(self.operate(fixture, request, 'rollback')['state'], 'rolled_back')
        self.assertEqual((fixture.repo / 'AGENTS.md').read_bytes(), original)
        self.assertEqual((unrelated / '0').read_text(), 'later unrelated edit\n')
        self.assertFalse((fixture.repo / changes.PROJECT_FILE).exists())

    def test_changed_selected_input_or_instruction_blocks_forward_effects(self):
        for name in ('config.json', '../AGENTS.md', 'AGENTS.md'):
            with self.subTest(name=name):
                fixture = self.configuration()
                if name.startswith('../'):
                    (fixture.repo / name).write_text('ancestor instructions\n')
                request = fixture.scoped_request()
                original = (fixture.repo / 'AGENTS.md').read_bytes()
                (fixture.repo / name).write_text('changed selected input\n')
                result = self.operate(fixture, request, 'apply')
                self.assertNotEqual(result['exit_code'], 0, result)
                expected = b'changed selected input\n' if name == 'AGENTS.md' else original
                self.assertEqual((fixture.repo / 'AGENTS.md').read_bytes(), expected)
                self.assertFalse((fixture.repo / changes.PROJECT_FILE).exists())

    def test_new_named_references_are_captured_without_rebinding_supplied_evidence(self):
        fixture = self.configuration()
        fixture.scoped_inspect()
        (fixture.repo / 'commands.json').write_text('{"check": "python3 check.py"}\n')
        proposal = fixture.scoped_proposal()
        assessment = proposal['assessments']['repositories'][0]
        assessment['inventory']['documents']['0']['path'] = 'commands.json'
        item = assessment['evidence'][0]
        item['inputs'] = ['commands.json']
        item.pop('input_digest')
        report = onboarding.record_plan(fixture.directory, proposal)
        self.assertEqual(report['status'], 'ready_for_review', report)
        snapshot = fixture.plan()['assessments']['repositories'][0]['identity']['snapshot']
        self.assertIn('commands.json', snapshot['paths'])
        self.assertEqual(snapshot['fingerprints']['commands.json']['sha256'],
                         hashlib.sha256((fixture.repo / 'commands.json').read_bytes()).hexdigest())
        proposal = fixture.scoped_proposal()
        item = proposal['assessments']['repositories'][0]['evidence'][0]
        item['input_digest'] = 'f' * 64
        report = onboarding.record_plan(fixture.directory, proposal)
        self.assertNotEqual(report['status'], 'ready_for_review', report)
        saved = fixture.plan()['assessments']['repositories'][0]['evidence'][0]
        self.assertEqual(saved['input_digest'], 'f' * 64)

    def test_basic_created_guidance_and_record_recover_with_later_edits(self):
        fixture = self.configuration()
        fixture.scoped_inspect()
        proposal = fixture.scoped_proposal()
        action = proposal['assessments']['repositories'][0]['actions'][0]
        action.update(target='docs/setup.md', before='absent', text='Project check: python3 check.py\n',
            after=hashlib.sha256(b'Project check: python3 check.py\n').hexdigest())
        report = onboarding.record_plan(fixture.directory, proposal)
        self.assertEqual(report['status'], 'ready_for_review', report)
        request = fixture.scoped_request(prepared=True)
        self.assertEqual(self.operate(fixture, request, 'apply')['state'], 'applied')
        self.assertEqual(self.operate(fixture, request, 'resume')['state'], 'applied')
        (fixture.repo / 'config.json').write_text('later selected input edit\n')
        self.assertEqual(self.operate(fixture, request, 'rollback')['state'], 'rolled_back')
        self.assertFalse((fixture.repo / 'docs/setup.md').exists())
        self.assertFalse((fixture.repo / changes.PROJECT_FILE).exists())

    def test_selected_canonical_record_resumes_and_preserves_external_edits(self):
        for external in (None, 'before', 'after'):
            with self.subTest(external=external):
                fixture = self.configuration()
                record = fixture.project_record(files=['README.md', str(changes.PROJECT_FILE)])
                record['project_scope']['inspection_scope'] = 'relevant'
                onboarding.inspect_project(fixture.repo, fixture.directory, record)
                request = fixture.scoped_request(existing=True)
                authority = fixture.repo / changes.PROJECT_FILE
                if external == 'before':
                    authority.parent.mkdir(exist_ok=True)
                    authority.write_text('{"later": "user record"}\n')
                    self.assertNotEqual(self.operate(fixture, request, 'apply')['exit_code'], 0)
                    self.assertEqual(authority.read_text(), '{"later": "user record"}\n')
                    continue
                self.assertEqual(self.operate(fixture, request, 'apply')['state'], 'applied')
                self.assertEqual(self.operate(fixture, request, 'resume')['state'], 'applied')
                if external == 'after':
                    later = authority.read_bytes() + b'\n'
                    authority.write_bytes(later)
                    self.assertNotEqual(self.operate(fixture, request, 'resume')['exit_code'], 0)
                    self.assertEqual(authority.read_bytes(), later)
                    self.assertNotEqual(self.operate(fixture, request, 'rollback')['exit_code'], 0)
                    self.assertEqual(authority.read_bytes(), later)
                else:
                    self.assertEqual(self.operate(fixture, request, 'rollback')['state'], 'rolled_back')
                    self.assertFalse(authority.exists())

    def test_selected_input_link_and_replaced_target_parent_are_denied(self):
        for substitute_parent in (False, True):
            with self.subTest(substitute_parent=substitute_parent):
                fixture = self.configuration()
                if substitute_parent:
                    (fixture.repo / 'docs').mkdir()
                    fixture.scoped_inspect()
                    proposal = fixture.scoped_proposal()
                    action = proposal['assessments']['repositories'][0]['actions'][0]
                    action.update(target='docs/setup.md', before='absent', text='setup\n',
                        after=hashlib.sha256(b'setup\n').hexdigest())
                    onboarding.record_plan(fixture.directory, proposal)
                    request = fixture.scoped_request(prepared=True)
                    (fixture.repo / 'docs').rename(fixture.repo / 'old-docs')
                    (fixture.repo / 'docs').symlink_to(fixture.repo / 'old-docs', target_is_directory=True)
                else:
                    request = fixture.scoped_request()
                    (fixture.repo / 'config.json').unlink()
                    (fixture.repo / 'config.json').symlink_to(fixture.repo / 'README.md')
                result = self.operate(fixture, request, 'apply')
                self.assertNotEqual(result['exit_code'], 0, result)
                self.assertFalse((fixture.repo / changes.PROJECT_FILE).exists())

    def test_relevant_scope_cannot_authorize_managed_execution(self):
        fixture = self.configuration()
        request = fixture.scoped_request()
        plan = fixture.plan()
        for managed in ('command', 'runtime', 'active'):
            with self.subTest(managed=managed):
                proposed = copy.deepcopy(request)
                if managed == 'command':
                    proposed['manifest']['actions'][0]['execution'] = {'argv': ['false']}
                else:
                    entry = proposed['manifest']['enrollment']['record']['repositories'][0]['checkouts'][0]['clients'][0]
                    if managed == 'runtime':
                        entry['configuration']['runtime'] = {'schema_version': 3, 'state_dir': '/not-selected'}
                    else:
                        entry['activation']['status'] = 'active'
                with self.assertRaisesRegex(StartupError, 'Relevant inspection supports only file configuration'):
                    changes._validate_scoped(proposed, plan, operation='apply')

    def test_missing_checkout_fields_cannot_be_evidence(self):
        fixture = self.configuration()
        fixture.scoped_inspect()
        proposal = fixture.scoped_proposal()
        item = proposal['assessments']['repositories'][0]['evidence'][0]
        item['inputs'] = ['checkout:head']
        item.pop('input_digest')
        with self.assertRaisesRegex(StartupError, 'Unknown evidence input fingerprint'):
            onboarding.record_plan(fixture.directory, proposal)
