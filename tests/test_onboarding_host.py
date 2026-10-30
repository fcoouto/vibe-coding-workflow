"""Public bridge contract tests; fixture birth is not production authorization."""

import copy
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import unittest

from runtime import changes, evidence, onboarding, review_storage, startup, state
from tests import test_changes


class OnboardingHostTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_changes.ScopedChangesTests(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        initial, contexts = f.d4_bookkeeping_request()
        self.context = contexts[0]
        # Existing accepted fixture factories create the real store/baseline first.
        with evidence._context_database(self.context) as db:
            baseline = state._source_baseline(None, db, context=self.context)
            self.assertEqual(baseline['content']['source_contract'], 2)
        result = f.run_with_d4_host(initial, 'apply')
        self.assertEqual(result['exit_code'], 0, result)
        self.original = (f.repo / 'AGENTS.md').read_bytes()
        catalog = f.source.read_bytes()
        temporary = tempfile.TemporaryDirectory(prefix='vcw-public-host-')
        self.addCleanup(temporary.cleanup)
        f.directory = Path(temporary.name).resolve() / 'plan'
        f.directory.mkdir(mode=0o700)
        f.source = f.directory / 'catalog.md'
        f.source.write_bytes(catalog)
        f.source.chmod(0o600)
        f.record['toolkit']['files'][0]['local_path'] = str(f.source)
        onboarding.inspect_project(f.repo, f.directory, f.project_record())
        proposal = f.scoped_proposal()
        action = proposal['assessments']['repositories'][0]['actions'][0]
        action['text'] += 'Additional approved canonical rule.\n'
        action['after'] = hashlib.sha256(action['text'].encode()).hexdigest()
        onboarding.record_plan(f.directory, proposal)
        self.approved = f.scoped_request(prepared=True)
        client = self.approved['manifest']['enrollment']['record']['repositories'][0]['checkouts'][0]['clients'][0]
        client['configuration']['runtime'] = dict(schema_version=3, state_dir=str(self.context.directory))
        self.approved['manifest']['transaction_id'] = 'public-update'
        client['activation']['transaction_id'] = 'public-update'
        self.approved['approval']['manifest_digest'] = onboarding._digest(self.approved['manifest'])
        self.plan = f.plan()
        # This independent fixture decision precedes each untrusted proposal copy.
        self.verified = self.decision(f, self.approved, 'apply', (self.context,))

    def module(self):
        return importlib.import_module('scripts.onboard_coordinator')

    def decision(self, fixture, approved, operation, contexts):
        record = approved['manifest']['enrollment']['record']
        subjects = []
        for repository in record['repositories']:
            for checkout in repository['checkouts']:
                for client in checkout['clients']:
                    identity = startup.canonical_scope_projection(startup.decode_project_record(record),
                        repository_id=repository['repository_id'], checkout_id=checkout['checkout_id'], client=client['client'])
                    subjects.append(dict(project_id=record['project_id'], repository_id=repository['repository_id'],
                        checkout_id=checkout['checkout_id'], client=client['client'],
                        accepted_identity_digest=startup._canonical_digest(evidence._canonical_plain(identity))))
        return dict(decision_reference=dict(reference='fixture:prior-reviewed-standing-decision', sha256='c' * 64),
            operation=operation, plan_directory=dict(path=str(fixture.directory),
                binding=onboarding._filesystem_binding(fixture.directory), parents=review_storage._parents(fixture.directory)),
            plan_digest=onboarding._digest(fixture.plan()),
            approved=copy.deepcopy({key: approved[key] for key in ('manifest', 'approval')}),
            bookkeeping_scope=dict(subjects=subjects,
                authorities=[evidence._canonical_plain(context.authority_set[0]) for context in contexts]))

    def entry(self, request=None, operation='apply'):
        return dict(operation=operation, plan_directory=copy.deepcopy(self.verified['plan_directory']),
            plan=copy.deepcopy(self.plan), request=copy.deepcopy(request or self.approved))

    def snapshot(self, fixture=None, extra_roots=()):
        f = fixture or self.fixture
        roots = [Path(f.plan()['identity']['project_root']), f.directory, changes.LOCK_ROOT, *extra_roots]
        if fixture is None:
            roots.append(self.context.directory)
        return {str(path): (path.read_bytes(), path.stat().st_mode & 0o777, path.stat().st_ino)
            for root in roots for path in root.rglob('*') if path.is_file()}

    def assert_completeness_denial(self, before, result, events, reason, *, fixture=None, contexts=()):
        import unicodedata
        f = fixture or self.fixture
        self.assertEqual(result['exit_code'], 2, result)
        self.assertIn(reason, [row['reason'] for row in result['blocked']])
        self.assertGreaterEqual(sum(kind == 'entry' for kind, _ in events), 2)
        self.assertFalse(any(kind == 'bookkeeping' for kind, _ in events))
        plan = f.plan()
        root = Path(plan['identity']['project_root'])
        authority, _ = changes._scoped_prior(plan)
        keys = {'destination:' + str(root / startup.PROJECT_FILE),
            'parent:' + str(root) + ':' + onboarding._digest(plan['identity']['binding'])}
        if authority['binding']:
            keys.add('inode:' + onboarding._digest(authority['binding']))
        allowed = {f.directory / '.d4-journal.lock'}
        allowed.update(changes.LOCK_ROOT / ('canonical-' + hashlib.sha256(key.encode()).hexdigest() + '.lock') for key in keys)
        for assessment in onboarding._assessments(plan['assessments']):
            owner = assessment['owner']
            if owner['kind'] == 'repository':
                allowed.update(changes.LOCK_ROOT / (hashlib.sha256(owner[key].encode()).hexdigest() + '.lock')
                    for key in ('git_dir', 'git_common_dir'))
        for context in contexts:
            directory = context.directory
            info = directory.stat()
            for key in ('path:' + unicodedata.normalize('NFC', str(directory)).casefold(),
                        'inode:' + str(info.st_dev) + ':' + str(info.st_ino)):
                allowed.add(changes.LOCK_ROOT / ('authority-' + hashlib.sha256(key.encode()).hexdigest()))
        after = self.snapshot(fixture, extra_roots=[context.directory for context in contexts])
        added = set(after) - set(before)
        self.assertLessEqual(added, {str(path) for path in allowed})
        self.assertEqual({key: value for key, value in after.items() if key not in added}, before)
        for name in added:
            self.assertEqual(after[name][:2], (b'', 0o600))
            with changes._lock(Path(name)):
                pass
        print('Authorized completeness denial:', self._testMethodName, 'allowed additions:', sorted(added))

    def owner(self, verified=None, events=None, alter_bookkeeping=None):
        base = self.module().CoordinatorOperationOwner
        events = events if events is not None else []
        class ObservedOwner(base):
            def authorize_d4_operation(owner, facts):
                events.append(('entry', facts))
                return super().authorize_d4_operation(facts)
            def acquire_d4_bookkeeping(owner, facts, issue):
                events.append(('bookkeeping', facts))
                if alter_bookkeeping is not None:
                    changed = evidence._canonical_plain(facts)
                    alter_bookkeeping(changed)
                    facts = startup._canonical_freeze(changed)
                def observed_issue(approved):
                    events.append(('issue', approved))
                    return issue(approved)
                return super().acquire_d4_bookkeeping(facts, observed_issue)
        return ObservedOwner(verified or self.verified)

    def invoke(self, owner, operation='apply', request=None, fixture=None):
        f = fixture or self.fixture
        function = {'apply': changes.apply_plan, 'resume': changes.resume_plan, 'rollback': changes.rollback_plan}[operation]
        with changes._bootstrap_d4_host(owner, issuer=changes._D4_HOST_BOOTSTRAP_ISSUER) as host:
            return function(f.directory, copy.deepcopy(request or self.approved), host=host)

    def test_owner_accepts_exact_preverified_core_and_rejects_untrusted_core_changes(self):
        owner = self.owner()
        self.assertIsNone(owner.authorize_d4_operation(startup._canonical_freeze(self.entry())))
        for field in ('operation', 'directory', 'plan', 'manifest', 'approval'):
            with self.subTest(field=field):
                facts = self.entry()
                if field == 'operation': facts['operation'] = 'rollback'
                elif field == 'directory': facts['plan_directory']['binding']['inode'] += 1
                elif field == 'plan': facts['plan']['revision'] += 1
                elif field == 'manifest': facts['request']['manifest']['approved_scope'] = []
                else: facts['request']['approval']['reference'] = 'untrusted:replacement'
                with self.assertRaises(startup.StartupError):
                    owner.authorize_d4_operation(startup._canonical_freeze(facts))

    def test_owner_captures_decision_before_caller_mutation(self):
        captured = copy.deepcopy(self.verified)
        owner = self.owner(captured)
        captured['approved']['manifest']['approved_scope'] = []
        self.assertIsNone(owner.authorize_d4_operation(startup._canonical_freeze(self.entry())))
        changed = self.entry()
        changed['request']['manifest']['approved_scope'] = []
        with self.assertRaises(startup.StartupError):
            owner.authorize_d4_operation(startup._canonical_freeze(changed))

    def test_public_nohost_does_not_mutate_existing_authority(self):
        before = self.snapshot()
        result = changes.apply_plan(self.fixture.directory, copy.deepcopy(self.approved))
        self.assertEqual(result['exit_code'], 2, result)
        self.assertFalse(result.get('qualified', False))
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.fixture.directory / 'transaction.json').exists())

    def test_denied_missing_plan_directory_is_not_created(self):
        missing = self.fixture.directory.parent / 'never-created-plan'
        before = self.snapshot()
        result = changes.apply_plan(missing, copy.deepcopy(self.approved))
        self.assertNotEqual(result['exit_code'], 0, result)
        self.assertFalse(missing.exists())
        self.assertEqual(self.snapshot(), before)

    def test_readonly_plan_validation_never_recreates_a_disappearing_directory(self):
        from unittest.mock import patch
        directory = self.fixture.directory.parent / 'disappearing-review'
        directory.mkdir(mode=0o700)
        def disappeared(*args, **kwargs):
            directory.rmdir()
            return 1, b''
        with patch.object(onboarding, '_git', side_effect=disappeared), patch.object(
                Path, 'mkdir', side_effect=AssertionError('Read-only admission attempted directory creation')):
            with self.assertRaisesRegex(startup.StartupError, 'An existing private reviewed plan is required'):
                onboarding._plan_path(directory, create=False)
        self.assertFalse(directory.exists())

    def add_genuine_git_membership(self):
        directory = self.fixture.directory
        binding = onboarding._filesystem_binding(directory)
        parents = review_storage._parents(directory)
        marker = directory / '.git'
        marker.write_text('gitdir: ' + str(self.fixture.repo / '.git') + '\n')
        marker.chmod(0o600)
        code, _ = onboarding._git(directory, '-c', 'safe.bareRepository=all',
            'rev-parse', '--absolute-git-dir')
        self.assertEqual(code, 0)
        self.assertEqual(onboarding._filesystem_binding(directory), binding)
        self.assertEqual(review_storage._parents(directory), parents)

    def test_git_membership_added_after_review_rejects_without_transaction_mutation(self):
        self.add_genuine_git_membership()
        before = self.snapshot()
        events = []
        result = self.invoke(self.owner(events=events))
        self.assertNotEqual(result['exit_code'], 0, result)
        self.assertIn('Plan directory must be outside repositories, plugin caches and instruction discovery paths',
            [row['reason'] for row in result['blocked']])
        self.assertEqual(events, [])
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.fixture.directory / 'transaction.json').exists())

    def test_git_membership_added_at_locked_reload_rejects_without_owned_failure_persistence(self):
        base = self.module().CoordinatorOperationOwner
        entries = []
        expected = []
        class RacingOwner(base):
            def authorize_d4_operation(owner, facts):
                result = super().authorize_d4_operation(facts)
                entries.append(facts)
                if len(entries) == 2:
                    self.add_genuine_git_membership()
                    expected.append(self.snapshot())
                return result
        result = self.invoke(RacingOwner(self.verified))
        self.assertNotEqual(result['exit_code'], 0, result)
        self.assertIn('Plan directory must be outside repositories, plugin caches and instruction discovery paths',
            [row['reason'] for row in result['blocked']])
        self.assertEqual(len(entries), 2)
        self.assertEqual(self.snapshot(), expected[0])
        self.assertFalse((self.fixture.directory / 'transaction.json').exists())
        with changes._public_plan_lock(self.fixture.directory):
            pass

    def test_changed_plan_after_entry_callback_is_rechecked_before_mutation(self):
        base = self.module().CoordinatorOperationOwner
        expected = []
        fixture = self.fixture
        class RacingOwner(base):
            def authorize_d4_operation(owner, facts):
                result = super().authorize_d4_operation(facts)
                if not expected:
                    changed = copy.deepcopy(self.plan)
                    changed['created_at'] = '2001-01-01T00:00:00+00:00'
                    (fixture.directory / 'plan.json').write_text(json.dumps(changed))
                    expected.append(self.snapshot())
                return result
        result = self.invoke(RacingOwner(self.verified))
        self.assertEqual(result['exit_code'], 2, result)
        self.assertEqual(len(expected), 1)
        self.assertEqual(self.snapshot(), expected[0])
        self.assertFalse((fixture.directory / 'transaction.json').exists())

    def test_request_fields_cannot_mint_a_host_or_verified_decision(self):
        for field in ('host', 'verified_decision', 'issuer'):
            with self.subTest(field=field):
                request = copy.deepcopy(self.approved)
                request[field] = 'untrusted:authorization'
                before = self.snapshot()
                result = changes.apply_plan(self.fixture.directory, request)
                self.assertNotEqual(result['exit_code'], 0, result)
                self.assertEqual(self.snapshot(), before)

    def test_copied_and_expired_capabilities_cannot_enter_public_mutation(self):
        owner = self.owner()
        with changes._bootstrap_d4_host(owner, issuer=changes._D4_HOST_BOOTSTRAP_ISSUER) as host:
            copied = copy.copy(host)
            before = self.snapshot()
            result = changes.apply_plan(self.fixture.directory, copy.deepcopy(self.approved), host=copied)
            self.assertEqual(result['exit_code'], 2, result)
            self.assertEqual(self.snapshot(), before)
        result = changes.apply_plan(self.fixture.directory, copy.deepcopy(self.approved), host=host)
        self.assertEqual(result['exit_code'], 2, result)
        self.assertEqual(self.snapshot(), before)

    def test_bookkeeping_only_fixture_owner_is_not_public_operation_authority(self):
        class BookkeepingOnly:
            def acquire_d4_bookkeeping(owner, facts, issue): return issue(facts)
        before = self.snapshot()
        result = self.invoke(BookkeepingOnly())
        self.assertEqual(result['exit_code'], 2, result)
        self.assertEqual(self.snapshot(), before)

    def test_changed_scope_and_cross_operation_reject_before_new_journal(self):
        for operation, change in (('rollback', False), ('apply', True)):
            with self.subTest(operation=operation, changed_scope=change):
                request = copy.deepcopy(self.approved)
                if change:
                    request['manifest']['actions'][0]['effects'][0]['after']['sha256'] = 'd' * 64
                    request['approval']['manifest_digest'] = onboarding._digest(request['manifest'])
                before = self.snapshot()
                result = self.invoke(self.owner(), operation=operation, request=request)
                self.assertEqual(result['exit_code'], 2, result)
                self.assertEqual(self.snapshot(), before)
                self.assertFalse((self.fixture.directory / 'transaction.json').exists())

    def test_uncovered_acquired_subject_is_rejected_by_owner_before_issue(self):
        events = []
        def change(facts): facts['permissions']['subjects'][0]['checkout_id'] = 'uncovered-checkout'
        before = (self.fixture.repo / 'AGENTS.md').read_bytes()
        with evidence._context_database(self.context) as db:
            baseline = evidence._canonical_plain(state._source_baseline(None, db, context=self.context))
        result = self.invoke(self.owner(events=events, alter_bookkeeping=change))
        self.assertEqual(result['exit_code'], 2, result)
        self.assertTrue(any(kind == 'entry' for kind, _ in events))
        self.assertTrue(any(kind == 'bookkeeping' for kind, _ in events))
        self.assertFalse(any(kind == 'issue' for kind, _ in events))
        self.assertEqual((self.fixture.repo / 'AGENTS.md').read_bytes(), before)
        with evidence._context_database(self.context) as db:
            self.assertEqual(evidence._canonical_plain(state._source_baseline(None, db, context=self.context)), baseline)

    def test_real_public_callbacks_keep_configured_output_pending(self):
        events = []
        result = self.invoke(self.owner(events=events))
        self.assertEqual(result['exit_code'], 2, result)
        self.assertEqual(result['activation_status'], 'configured')
        self.assertFalse(result['qualified'])
        self.assertNotEqual((self.fixture.repo / 'AGENTS.md').read_bytes(), self.original)
        journal = changes._load_journal(self.fixture.directory)
        self.assertEqual(journal['state'], 'applied')
        self.assertEqual(journal['manifest'], self.approved['manifest'])
        self.assertTrue(any(kind == 'entry' for kind, _ in events))
        self.assertGreaterEqual(sum(kind == 'bookkeeping' for kind, _ in events), 2)
        self.assertEqual(sum(kind == 'issue' for kind, _ in events), sum(kind == 'bookkeeping' for kind, _ in events))
        _, sources = changes._recovery_sources(self.context)
        self.assertTrue(any(body['identity']['plan_dir'] == str(self.fixture.directory) for _, body in sources))
        acquired = startup.acquire_canonical_project(type('Event', (), dict(client='codex', cwd=self.fixture.repo))(), state.PACKAGE)
        self.assertIsNone(acquired.resolution.scope)
        self.assertNotEqual(acquired.resolution.status, 'active')

    def test_callable_runner_applies_resumes_and_rolls_back_same_approved_core(self):
        module = self.module()
        request = copy.deepcopy(self.approved)
        result = module.run_verified_operation(self.verified, self.fixture.directory, request)
        self.assertEqual(result['exit_code'], 2, result)
        self.assertFalse(result['qualified'])
        for operation in ('resume', 'rollback'):
            decision = copy.deepcopy(self.verified)
            decision['operation'] = operation
            result = module.run_verified_operation(decision, self.fixture.directory, copy.deepcopy(request))
            self.assertEqual(result['exit_code'], 0 if operation == 'rollback' else 2, result)
        self.assertEqual((self.fixture.repo / 'AGENTS.md').read_bytes(), self.original)
        self.assertEqual(changes._load_journal(self.fixture.directory)['state'], 'rolled_back')

    def test_existing_journal_is_unchanged_when_recovery_entry_is_denied(self):
        self.assertEqual(self.invoke(self.owner())['exit_code'], 2)
        before = self.snapshot()
        decision = copy.deepcopy(self.verified)
        decision['operation'] = 'resume'
        decision['approved']['approval']['reference'] = 'uncovered:recovery'
        result = self.invoke(self.owner(decision), operation='resume')
        self.assertEqual(result['exit_code'], 2, result)
        self.assertEqual(self.snapshot(), before)

    def test_fresh_resume_observations_do_not_require_changed_effect_approval(self):
        self.assertEqual(self.invoke(self.owner())['exit_code'], 2)
        request = copy.deepcopy(self.approved)
        request['observations'] = dict(manifest_digest=onboarding._digest(request['manifest']),
            input_digest=changes._scoped_input_digest(request['manifest']), qualification=[],
            task_reconciliation=[], prior_compatibility=[], command_reconciliation=[])
        decision = copy.deepcopy(self.verified)
        decision['operation'] = 'resume'
        result = self.invoke(self.owner(decision), operation='resume', request=request)
        self.assertEqual(result['exit_code'], 2, result)
        journal = changes._load_journal(self.fixture.directory)
        self.assertEqual(journal['observations'][-1], request['observations'])
        self.assertEqual(journal['manifest'], self.approved['manifest'])

    def test_authorized_fresh_empty_context_still_requires_real_state_birth(self):
        fresh = test_changes.ScopedChangesTests(methodName='runTest')
        fresh.setUp()
        self.addCleanup(fresh.doCleanups)
        request = fresh.scoped_request()
        decision = self.decision(fresh, request, 'apply', ())
        events = []
        before = self.snapshot(fresh)
        result = self.invoke(self.owner(decision, events), request=request, fixture=fresh)
        self.assert_completeness_denial(before, result, events,
            'Canonical runtime preparation is required before mutation', fixture=fresh)
        self.assertFalse((fresh.repo / startup.PROJECT_FILE).exists())

    def test_missing_existing_database_is_not_reinitialized(self):
        saved = self.context.database.with_suffix('.saved')
        self.context.database.rename(saved)
        before = self.snapshot()
        events = []
        result = self.invoke(self.owner(events=events))
        self.assert_completeness_denial(before, result, events,
            'Complete existing canonical runtime authorities are required before mutation', contexts=(self.context,))
        self.assertFalse(self.context.database.exists())

    def test_missing_original_baseline_is_not_retrofitted(self):
        with evidence._context_database(self.context, write=True) as db:
            baseline = state._source_baseline(None, db, context=self.context)
            db.execute('delete from evidence_metadata where name=?', (baseline['reference']['name'],))
        before = self.snapshot()
        events = []
        result = self.invoke(self.owner(events=events))
        self.assert_completeness_denial(before, result, events,
            'An original source-contract-2 baseline is required before mutation', contexts=(self.context,))

    def test_one_existing_peer_does_not_hide_another_missing_required_authority(self):
        fixture = test_changes.ScopedChangesTests(methodName='runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        request, contexts = fixture.d4_bookkeeping_request(umbrella=True)
        applied = fixture.run_with_d4_host(request, 'apply')
        self.assertEqual(applied['exit_code'], 0, applied)
        prior_journal = fixture.directory / 'transaction.json'
        prior_journal_bytes = prior_journal.read_bytes()
        member_roots = [Path(repository['checkouts'][0]['root']) for repository in request['manifest']['enrollment']['record']['repositories']]
        catalog = fixture.source.read_bytes()
        temporary = tempfile.TemporaryDirectory(prefix='vcw-public-peers-')
        self.addCleanup(temporary.cleanup)
        fixture.directory = Path(temporary.name).resolve() / 'plan'
        fixture.directory.mkdir(mode=0o700)
        fixture.source = fixture.directory / 'catalog.md'
        fixture.source.write_bytes(catalog)
        fixture.source.chmod(0o600)
        fixture.record['toolkit']['files'][0]['local_path'] = str(fixture.source)
        onboarding.inspect_project(fixture.base, fixture.directory,
            fixture.project_record(fixture.base, member_roots, 'umbrella', ['AGENTS.md']))
        onboarding.record_plan(fixture.directory, fixture.scoped_proposal())
        request = fixture.scoped_request(prepared=True)
        request['manifest']['transaction_id'] = 'public-peers-update'
        for repository, context in zip(request['manifest']['enrollment']['record']['repositories'], contexts):
            client = repository['checkouts'][0]['clients'][0]
            client['configuration']['runtime'] = dict(schema_version=3, state_dir=str(context.directory))
            client['activation']['transaction_id'] = 'public-peers-update'
        request['approval']['manifest_digest'] = onboarding._digest(request['manifest'])
        verified = self.decision(fixture, request, 'apply', contexts)
        contexts[1].database.rename(contexts[1].database.with_suffix('.saved'))
        self.assertTrue(contexts[0].database.exists())
        before = self.snapshot(fixture, extra_roots=[context.directory for context in contexts])
        events = []
        result = self.invoke(self.owner(verified, events), request=request, fixture=fixture)
        self.assert_completeness_denial(before, result, events,
            'Complete existing canonical runtime authorities are required before mutation',
            fixture=fixture, contexts=contexts)
        self.assertFalse(contexts[1].database.exists())
        self.assertEqual(prior_journal.read_bytes(), prior_journal_bytes)
