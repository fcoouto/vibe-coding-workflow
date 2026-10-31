"""Pure comparisons of supplied identity/projection/actions; no source-authentication claim."""
import copy
import unittest

from runtime import changes

BINDING = dict(device=1, inode=2)
RETAINED = dict(path='/project/AGENTS.md', sha256='b' * 64)
REMOVED = dict(path='/project/shared.md', sha256='c' * 64)
BEFORE = dict(sha256='d' * 64, mode=0o644)
AFTER = dict(sha256='e' * 64, mode=0o644)


class HistoricalEffectTests(unittest.TestCase):
    def fixture(self, *, effects=None):
        identity = dict(version=1, project_id='project', repository_id='repository', checkout_id='checkout',
            project_root='/project', project_binding=BINDING, primary_root='/project/repo',
            repository_root='/project/repo', git_dir='/project/repo/.git', git_common_dir='/project/repo/.git',
            bindings=dict(root=BINDING, primary_root=BINDING, git_dir=BINDING, git_common_dir=BINDING),
            client='codex', membership=dict(included=True,
                authorization=dict(reference='fixture:standing', sha256='f' * 64)),
            configuration=dict(policy_digest='1' * 64, runtime_digest='2' * 64,
                runtime=dict(schema_version=3, state_dir='/state/tasks')),
            shared_policy=[copy.deepcopy(RETAINED), copy.deepcopy(REMOVED)])
        projection = copy.deepcopy(identity)
        projection['shared_policy'] = [copy.deepcopy(RETAINED)]
        actions = [dict(id='change-shared', owner=dict(root='/project'), effects=[dict(
            path='shared.md', before=copy.deepcopy(BEFORE), after=copy.deepcopy(AFTER))])]
        if effects is not None:
            actions[0]['effects'] = effects
        return identity, projection, actions

    def compare(self, identity, projection, actions):
        helper = getattr(changes, '_historical_effects', None)
        self.assertTrue(callable(helper), 'historical effect comparator is missing')
        return helper(identity, projection, actions)

    def test_exact_removed_dependency_and_changed_effect_match(self):
        identity, projection, actions = self.fixture()
        self.assertEqual(self.compare(identity, projection, actions),
            [dict(action_id='change-shared', path='shared.md')])

    def test_retained_row_equality_and_missing_projection_are_required(self):
        identity, projection, actions = self.fixture()
        changed = copy.deepcopy(projection)
        changed['shared_policy'][0]['sha256'] = '9' * 64
        self.assertEqual(self.compare(identity, changed, actions), [])
        removed_retained = copy.deepcopy(projection)
        removed_retained['shared_policy'] = []
        self.assertEqual(self.compare(identity, removed_retained, actions),
            [dict(action_id='change-shared', path='shared.md')])
        self.assertEqual(self.compare(identity, None, actions), [])

    def test_full_identity_may_differ_only_by_shared_policy_removal(self):
        for field, value in (
            ('project_id', 'other-project'), ('project_root', '/other-project'),
            ('repository_id', 'other-repository'), ('checkout_id', 'other-checkout'),
            ('client', 'other-client'),
        ):
            with self.subTest(field=field):
                identity, projection, actions = self.fixture()
                projection[field] = value
                self.assertEqual(self.compare(identity, projection, actions), [])
        identity, projection, actions = self.fixture()
        projection['configuration']['policy_digest'] = '9' * 64
        self.assertEqual(self.compare(identity, projection, actions), [])

    def test_effect_fingerprint_uses_full_value_and_owner_path_must_match(self):
        identity, projection, actions = self.fixture(effects=[dict(path='shared.md',
            before=copy.deepcopy(BEFORE), after=dict(sha256=BEFORE['sha256'], mode=0o600))])
        self.assertEqual(self.compare(identity, projection, actions),
            [dict(action_id='change-shared', path='shared.md')])
        actions[0]['effects'][0]['after'] = copy.deepcopy(BEFORE)
        self.assertEqual(self.compare(identity, projection, actions), [])
        actions[0]['effects'][0]['after'] = copy.deepcopy(AFTER)
        actions[0]['effects'][0]['path'] = 'unrelated.md'
        self.assertEqual(self.compare(identity, projection, actions), [])
        actions[0]['effects'][0]['path'] = 'shared.md'
        actions[0]['owner']['root'] = '/elsewhere'
        self.assertEqual(self.compare(identity, projection, actions), [])

    def test_effect_results_keep_manifest_order_and_duplicates(self):
        identity, projection, actions = self.fixture()
        second = dict(path='/project/second.md', sha256='6' * 64)
        first = dict(path='/project/first.md', sha256='7' * 64)
        identity['shared_policy'] = [copy.deepcopy(RETAINED), second, first]
        identity['shared_policy'].sort(key=lambda row: row['path'])
        projection['shared_policy'] = [copy.deepcopy(RETAINED)]
        actions = [
            dict(id='second-action', owner=dict(root='/project'), effects=[dict(
                path='second.md', before=copy.deepcopy(BEFORE), after=copy.deepcopy(AFTER))]),
            dict(id='first-action', owner=dict(root='/project'), effects=[dict(
                path='first.md', before=copy.deepcopy(BEFORE), after=copy.deepcopy(AFTER))]),
            dict(id='second-action', owner=dict(root='/project'), effects=[dict(
                path='second.md', before=copy.deepcopy(BEFORE), after=copy.deepcopy(AFTER))]),
        ]
        self.assertEqual(self.compare(identity, projection, actions), [
            dict(action_id='second-action', path='second.md'),
            dict(action_id='first-action', path='first.md'),
            dict(action_id='second-action', path='second.md'),
        ])


if __name__ == '__main__': unittest.main()
