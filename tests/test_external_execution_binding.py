"""Real disposable worktrees; native observations are explicit local fixtures."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from runtime import delegation, evidence, openrouter_settings as settings, startup, state
from tests import test_delegation as native_fixtures


class ExternalExecutionBindingTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(getattr(delegation, 'observe_execution_binding', None)),
                        'non-launching execution binding observation is missing')
        self.fixture = native_fixtures.AdmissionTests(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.root, self.source, self.scope = f.root, f.repo, f.scope
        project = self.source / startup.PROJECT_FILE
        project.parent.mkdir(exist_ok=True)
        project.write_text(json.dumps(dict(schema_version=1, project_id=self.scope.project_id,
            repository_root=str(self.source), git_common_dir=str(self.scope.git_common_dir),
            clients=['codex'], policy_digest=self.scope.policy_digest,
            runtime=dict(schema_version=2, state_dir=str(self.scope.runtime.state_dir)))))
        self.assertEqual(settings.resolve(self.source), self.scope)
        auth = self.root / 'auth'; auth.mkdir(mode=0o700)
        executable = self.root / 'opencode'
        executable.write_text('#!/bin/sh\nexit 99\n'); executable.chmod(0o700)
        configured = settings.configure(self.source, dict(expected_revision=0, routes=['workers'],
            opencode=str(executable), auth_data=str(auth)))
        self.managed = settings.enable(self.source, dict(expected_revision=configured['revision'], consent_version=2))
        f.plan()
        self.prepared = f.prepare()
        f.observe_worker(self.prepared, f.lifecycle_observation(self.prepared, turn_status='inProgress'))
        self.execution = self.root / 'execution'
        subprocess.run(['git', '-C', str(self.source), 'worktree', 'add', '--detach', '--quiet',
                        str(self.execution), 'HEAD'], check=True, capture_output=True, timeout=5)
        self.request = f.request(supervisor_attempt_id=self.prepared['attempt_id'],
            execution_root=str(self.execution), source_candidate_ref=f.raw_assignment(self.prepared['attempt_id'])['candidate'],
            settings_scope_id=self.managed['scope_id'], settings_revision=self.managed['revision'],
            selection_ref='fixture:cached-openrouter-selection')

    def observe(self, **updates):
        return delegation.observe_execution_binding(self.scope, self.request | updates)

    def durable(self):
        with state._database(self.scope) as db:
            database = list(db.iterdump())
        folder = self.scope.runtime.state_dir
        return database, {str(p.relative_to(folder)):p.read_bytes() for p in (folder / 'evidence').iterdir() if p.is_file()}

    def test_association_maps_real_scope_without_admission_or_state_changes(self):
        before = self.durable()
        first = self.observe()
        self.assertFalse(first['launch_admitted'])
        self.assertFalse(first['supported_for_dispatch'])
        self.assertIsNone(first['execution_id'])
        self.assertEqual(first['revision'], self.request['expected_revision'])
        binding = first['binding']
        self.assertEqual(binding['source_candidate_ref'], self.request['source_candidate_ref'])
        self.assertEqual(binding['supervisor_attempt_id'], self.prepared['attempt_id'])
        self.assertEqual(binding['checks'], ['unit'])
        self.assertEqual(binding['mapped_claims'][0]['path'], str(self.execution / 'app.py'))
        self.assertEqual(binding['settings']['consent_version'], 2)
        self.assertEqual(binding['execution']['root'], str(self.execution))
        self.assertEqual(len(first['blockers']), 4)
        self.assertEqual(self.observe(), first)
        self.assertEqual(self.durable(), before)
        self.assertFalse((self.execution / startup.PROJECT_FILE).exists())
        self.assertEqual(sorted(p.name for p in self.execution.iterdir()), ['.git', 'app.py'])

    def test_foreign_task_candidate_revision_and_request_fields_are_rejected(self):
        for delta in (dict(task_id='another-task'), dict(supervisor_attempt_id='f'*32),
                      dict(source_candidate_ref=self.request['source_candidate_ref'] | dict(digest='f'*64)),
                      dict(expected_revision=self.request['expected_revision']-1),
                      dict(selection_ref=''), dict(argv=['echo', 'forbidden'])):
            with self.subTest(delta=delta), self.assertRaises(state.StateError): self.observe(**delta)

    def test_changed_source_or_unobserved_supervisor_is_rejected(self):
        (self.source / 'app.py').write_text('value = 2\n')
        with self.assertRaises(state.StateError): self.observe()
        (self.source / 'app.py').write_text('value = 1\n')
        with state._database(self.scope, write=True) as db:
            row = self.fixture.raw_assignment(self.prepared['attempt_id'])
            row.update(status='prepared', observation=None)
            db.execute('update assignments set data=? where id=?', (json.dumps(row), self.prepared['attempt_id']))
        with self.assertRaises(state.StateError): self.observe()

    def test_settings_revision_disable_and_legacy_consent_are_rejected(self):
        with self.assertRaises((state.StateError, settings.SettingsError)):
            self.observe(settings_revision=self.managed['revision']-1)
        with self.assertRaises((state.StateError, settings.SettingsError)):
            self.observe(settings_scope_id='wrong-scope')
        disabled = settings.disable(self.source, dict(expected_revision=self.managed['revision']))
        with self.assertRaises((state.StateError, settings.SettingsError)):
            self.observe(settings_revision=disabled['revision'])
        with settings.guard(self.source, write=True) as owner:
            owner.save(dict(owner.record, version=1, enabled=True, revision=disabled['revision']+1))
        with self.assertRaises((state.StateError, settings.SettingsError)):
            self.observe(settings_revision=disabled['revision']+1)

    def test_foreign_source_symlink_and_replaced_private_git_are_rejected(self):
        alias = self.root / 'alias'; alias.symlink_to(self.execution, target_is_directory=True)
        foreign = self.root / 'foreign'; foreign.mkdir()
        subprocess.run(['git', 'init', '--quiet', '--template=', str(foreign)], check=True, timeout=5)
        for root in (self.source, alias, foreign):
            with self.subTest(root=root), self.assertRaises(state.StateError): self.observe(execution_root=str(root))
        private = Path(subprocess.check_output(['git', '-C', str(self.execution), 'rev-parse', '--absolute-git-dir']).decode().strip())
        held = private.with_name(private.name+'-held'); private.rename(held)
        private.symlink_to(held, target_is_directory=True)
        with self.assertRaises(state.StateError): self.observe()

    def test_routing_changes_between_observations_are_rejected(self):
        original = delegation._git_routing_paths
        changed = False
        def move(root, private, common):
            nonlocal changed
            value = original(root, private, common)
            if root == self.execution and not changed:
                changed = True
                marker = root / '.git'
                marker.write_text(marker.read_text()+'\n')
            return value
        with patch.object(delegation, '_git_routing_paths', side_effect=move):
            with self.assertRaises(state.StateError): self.observe()

    def test_task_and_mapped_file_changes_during_observation_are_rejected(self):
        original = delegation._execution_checkout
        for change in ('file', 'task'):
            changed = False
            observations = 0
            def mutate(root, common):
                nonlocal changed, observations
                value = original(root, common)
                observations += 1
                if not changed and observations == (2 if change == 'file' else 1):
                    changed = True
                    if change == 'file':
                        replacement = root / 'replacement'
                        replacement.write_text('different inode\n')
                        replacement.replace(root / 'app.py')
                    else:
                        state.update_task(self.scope, self.fixture.identity | dict(
                            expected_revision=self.request['expected_revision'], state='active',
                            reason='Concurrent native update', reference='fixture:concurrent'))
                return value
            with self.subTest(change=change), patch.object(delegation, '_execution_checkout', side_effect=mutate):
                with self.assertRaises(state.StateError): self.observe()

    def test_hardlinked_execution_routing_is_rejected(self):
        marker = self.execution / '.git'
        alias = self.root / 'marker-alias'
        os.link(marker, alias)
        with self.assertRaises(state.StateError): self.observe()

    def test_common_target_directory_aliases_are_rejected(self):
        private = Path(subprocess.check_output(['git', '-C', str(self.execution),
            'rev-parse', '--absolute-git-dir']).decode().strip())
        direct = self.root / 'common-alias'
        direct.symlink_to(self.scope.git_common_dir, target_is_directory=True)
        parent = self.root / 'source-alias'
        parent.symlink_to(self.source, target_is_directory=True)
        for target in (direct, parent / '.git'):
            with self.subTest(target=target):
                (private / 'commondir').write_text(str(target)+'\n')
                before = self.durable()
                with self.assertRaises(state.StateError): self.observe()
                self.assertEqual(self.durable(), before)

    def test_git_observations_run_outside_database_contexts(self):
        database, git = state._database, evidence._git
        depth = 0
        @contextmanager
        def tracked(*args, **kwargs):
            nonlocal depth
            with database(*args, **kwargs) as db:
                depth += 1
                try: yield db
                finally: depth -= 1
        def observed(*args):
            self.assertEqual(depth, 0, 'Git ran inside a database context')
            return git(*args)
        with patch.object(state, '_database', side_effect=tracked), patch.object(evidence, '_git', side_effect=observed):
            self.assertFalse(self.observe()['launch_admitted'])

    def test_mapped_symlink_and_nested_repository_are_rejected(self):
        (self.execution / 'app.py').unlink()
        outside = self.root / 'outside.py'; outside.write_text('outside\n')
        (self.execution / 'app.py').symlink_to(outside)
        with self.assertRaises(state.StateError): self.observe()
        (self.execution / 'app.py').unlink()
        (self.execution / 'app.py').mkdir()
        (self.execution / 'app.py/.git').mkdir()
        with self.assertRaises(state.StateError): self.observe()


if __name__ == '__main__': unittest.main()
