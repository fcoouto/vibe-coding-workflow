"""Synthetic owner facts exercise the consumer; never native setup qualification."""

import copy
import json
from types import SimpleNamespace
import unittest

from runtime import startup, state
from tests.fixture_canonical_birth import CanonicalBirthFixture


class SetupObservationTests(unittest.TestCase):
    def setUp(self):
        owner = CanonicalBirthFixture('runTest')
        self.addCleanup(owner.doCleanups)
        self.fixture, self.original, self.observation = owner.accepted_birth()
        self.event = SimpleNamespace(client='codex', cwd=self.fixture.repo)
        self.authority = self.original.authority_path
        self.authority_before = self.authority.read_bytes()
        self.historical = copy.deepcopy(self.observation['binding'])

    def acquire(self, observation):
        return startup.acquire_project_entry(self.event, state.PACKAGE,
            qualifier=lambda record, facts: observation)

    def current_configuration(self):
        self.observation['current'] = {key: self.observation['current'][key]
            for key in ('client', 'configuration_digest', 'hook_owner')}
        return self.observation

    def assert_active_unchanged(self, acquired):
        self.assertEqual(acquired.resolution.status, 'active', acquired.resolution)
        self.assertEqual(acquired.resolution.scope.accepted_scope_digest,
            self.original.resolution.scope.accepted_scope_digest)
        self.assertEqual(acquired.resolution.scope.qualification_provenance,
            self.original.resolution.scope.qualification_provenance)
        self.assertEqual(self.observation['binding'], self.historical)
        self.assertEqual(self.authority.read_bytes(), self.authority_before)

    def test_current_configuration_does_not_require_current_surface_or_version(self):
        self.assert_active_unchanged(self.acquire(self.current_configuration()))

    def test_legacy_current_surface_and_version_are_not_later_session_proof(self):
        self.observation['current'].update(surface='another-observed-surface', version='another-release')
        self.assert_active_unchanged(self.acquire(self.observation))

    def test_other_clients_keep_current_surface_requirement_and_comparison(self):
        captured = []
        startup.acquire_project_entry(self.event, state.PACKAGE,
            qualifier=lambda record, facts: captured.append(startup._canonical_plain(facts)) or self.observation)
        facts = {key: captured[0][key] for key in ('authority', 'observation', 'client', 'installed')}
        record = json.loads(self.authority_before)
        repository = record['repositories'][0]
        checkout = repository['checkouts'][0]
        entry = checkout['clients'][0]
        # Only in-memory comparison facts change; no other client is executed or enrolled.
        entry['client'] = facts['client'] = 'claude-code'
        facts['installed']['clients'] = ['claude-code']
        qualification = copy.deepcopy(self.observation)
        qualification['current']['client'] = qualification['binding']['client'] = 'claude-code'
        projection = startup.canonical_scope_projection(startup.decode_project_record(record),
            repository_id=repository['repository_id'], checkout_id=checkout['checkout_id'], client='claude-code')
        digest = startup._canonical_digest(startup._canonical_plain(projection))
        qualification['binding']['accepted_scope_digest'] = entry['activation']['accepted_scope_digest'] = digest
        entry['activation']['qualification_binding'] = copy.deepcopy(qualification['binding'])
        facts['observation']['qualification'] = qualification
        decoded = startup.decode_project_record(record)
        self.assertEqual(startup.resolve_canonical_scope(decoded, **facts).status, 'active')
        with self.subTest(current='three-fields'):
            candidate = copy.deepcopy(facts)
            candidate['observation']['qualification']['current'] = {key: qualification['current'][key]
                for key in ('client', 'configuration_digest', 'hook_owner')}
            with self.assertRaises(startup.StartupError):
                startup.resolve_canonical_scope(decoded, **candidate)
        with self.subTest(current='changed-surface'):
            candidate = copy.deepcopy(facts)
            candidate['observation']['qualification']['current']['surface'] = 'another-surface'
            result = startup.resolve_canonical_scope(decoded, **candidate)
            self.assertEqual((result.status, result.reason), ('suspended', 'qualification_changed'))
            self.assertIsNone(result.scope)
        candidate = copy.deepcopy(facts)
        candidate['observation']['qualification']['current']['version'] = 'another-release'
        self.assertEqual(startup.resolve_canonical_scope(decoded, **candidate).status, 'active')
        self.assertEqual(self.observation['binding'], self.historical)
        self.assertEqual(self.authority.read_bytes(), self.authority_before)

    def test_changed_current_configuration_client_or_hook_owner_suspends(self):
        original = copy.deepcopy(self.current_configuration())
        for field in ('client', 'configuration_digest', 'hook_owner'):
            with self.subTest(changed=field):
                changed = copy.deepcopy(original)
                if field == 'hook_owner':
                    changed['current'][field]['sha256'] = 'a' * 64
                else:
                    changed['current'][field] = 'another-client' if field == 'client' else 'a' * 64
                result = self.acquire(changed).resolution
                self.assertEqual((result.status, result.reason), ('suspended', 'qualification_changed'))
                self.assertIsNone(result.scope)
        self.assertEqual(self.authority.read_bytes(), self.authority_before)

    def test_historical_surface_version_and_receipt_bindings_still_must_match(self):
        original = copy.deepcopy(self.current_configuration())
        for field in ('surface', 'version', 'receipt', 'accepted_scope_digest'):
            with self.subTest(changed=field):
                changed = copy.deepcopy(original)
                changed['binding'][field] = (dict(reference='fixture:copied-label',sha256='a'*64)
                    if field == 'receipt' else 'a'*64 if field == 'accepted_scope_digest' else 'another-value')
                result = self.acquire(changed).resolution
                self.assertEqual((result.status, result.reason), ('suspended', 'qualification_changed'))
                self.assertIsNone(result.scope)
        self.assertEqual(self.authority.read_bytes(), self.authority_before)

    def test_copied_label_or_missing_owner_observation_does_not_activate(self):
        self.current_configuration()
        for observation in (None, dict(self.observation, provenance=None), dict(self.observation, binding=None)):
            with self.subTest(observation=observation):
                result = self.acquire(observation).resolution
                self.assertEqual((result.status, result.reason), ('configured', 'qualification_unobserved'))
                self.assertIsNone(result.scope)
        copied = startup.acquire_project_entry(self.event, state.PACKAGE).resolution
        self.assertEqual((copied.status, copied.reason), ('configured', 'qualification_unobserved'))
        self.assertIsNone(copied.scope)
        self.assertEqual(self.authority.read_bytes(), self.authority_before)
