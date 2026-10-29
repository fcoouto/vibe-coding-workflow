"""Pure recovery-use contracts preserve per-root restrictions without authority grants."""
import copy
import unittest

from runtime import recovery_uses as uses


AUTHORITY = dict(directory='/state', database='/state/runtime.sqlite3',
    directory_binding=dict(device=1, inode=2), database_binding=dict(device=1, inode=3))
ARTIFACT = dict(name='a' * 32 + '.json', digest='b' * 64)
TASK = dict(authority=AUTHORITY, scope_id='c' * 64, client='codex', session_id='session', task_id='task')


class RecoveryUsesTests(unittest.TestCase):
    def roots(self):
        edge = dict(kind='task', reference=TASK)
        return [dict(purpose='historical-stop', reference=edge, task=TASK,
            proof=dict(authority=AUTHORITY, artifact=ARTIFACT), effect=dict(action_id='change', path='AGENTS.md')),
            dict(purpose='content', reference=edge)]

    def contract(self):
        roots = self.roots()
        return uses.build(roots, [dict(root=index, parent=None, dependency=root['reference'],
            purpose='retention-only' if index == 0 else 'content') for index, root in enumerate(roots)])

    def test_build_canonicalizes_without_deduplicating_distinct_reasons(self):
        value = self.contract()
        self.assertEqual(uses.validate(value), value)
        self.assertEqual(len(value['roots']), 2)
        self.assertEqual({row['purpose'] for row in value['edges']}, {'retention-only', 'content'})
        self.assertEqual(uses.merge([value, value]), value)

    def test_rejects_unknown_fields_missing_reason_and_invalid_root(self):
        value = self.contract()
        for mutate in (lambda v: v.update(complete=True),
                       lambda v: v['roots'][0].update(unknown=True),
                       lambda v: v['edges'][0].update(root=20),
                       lambda v: v['edges'][0].update(root=True),
                       lambda v: v['edges'][0].update(purpose='permission')):
            changed = copy.deepcopy(value); mutate(changed)
            with self.assertRaises(uses.UseContractError): uses.validate(changed)

    def test_content_reason_cannot_drop_content_permission(self):
        root = self.roots()[1]
        with self.assertRaises(uses.UseContractError):
            uses.build([root], [dict(root=0, parent=None, dependency=root['reference'], purpose='retention-only')])

    def test_qualification_is_exact_and_pure(self):
        edge = dict(kind='artifact', reference=ARTIFACT)
        qualified = uses.qualify_dependency(edge, AUTHORITY)
        self.assertEqual(qualified, dict(kind='artifact', reference=dict(authority=AUTHORITY, artifact=ARTIFACT)))
        self.assertEqual(edge['reference'], ARTIFACT)
        self.assertEqual(uses.qualify_dependency(qualified, AUTHORITY), qualified)

    def test_projection_cuts_only_absent_dependencies_and_never_upgrades(self):
        value = self.contract()
        direct = [value['edges'][0]['dependency']]
        self.assertEqual(uses.project(value, direct, {}), value)
        empty = uses.project(value, [], {})
        self.assertEqual(empty['edges'], [])
        self.assertEqual(empty['roots'], value['roots'])
        unknown = dict(kind='artifact', reference=dict(authority=AUTHORITY, artifact=ARTIFACT))
        with self.assertRaises(uses.UseContractError): uses.project(value, direct + [unknown], {})

    def test_legacy_inventory_is_exact_and_cannot_widen(self):
        origin = dict(authority=AUTHORITY, artifact=ARTIFACT,
            identity=dict(plan_dir='/plan', transaction_id='transaction', manifest_digest='d' * 64), journal_sha256='e' * 64)
        value = uses.build([], [], [dict(origin=origin, destinations=[AUTHORITY])])
        self.assertEqual(uses.merge([value, value]), value)
        changed = copy.deepcopy(value)
        changed['legacy_routes'][0]['destinations'] = []
        with self.assertRaises(uses.UseContractError): uses.merge([value, changed])

    def test_checks_exact_direct_and_traversed_coverage(self):
        value = self.contract()
        direct = [value['edges'][0]['dependency']]
        uses.check_coverage(value, direct, {})
        with self.assertRaises(uses.UseContractError): uses.check_coverage(value, [], {})
        with self.assertRaises(uses.UseContractError): uses.check_coverage(value, direct, {'unobserved': []})

    def test_each_duplicate_reason_needs_its_own_exact_managed_closure(self):
        roots = self.roots()
        pointer = dict(authority=AUTHORITY, artifact=ARTIFACT)
        artifact = dict(kind='artifact', reference=pointer)
        task = dict(kind='task', reference=TASK)
        edges = []
        for index in range(2):
            purpose = 'retention-only' if index == 0 else 'content'
            edges.extend([dict(root=index, parent=None, dependency=artifact, purpose=purpose),
                dict(root=index, parent=None, dependency=task, purpose=purpose),
                dict(root=index, parent=pointer, dependency=task, purpose=purpose)])
        contract = uses.build(roots, edges)
        metadata = {uses.key(pointer): [task]}
        uses.check_coverage(contract, [artifact, task], metadata)
        damaged = copy.deepcopy(contract)
        damaged['edges'] = [row for row in damaged['edges'] if not (row['root'] == 0 and row['parent'] is not None)]
        with self.assertRaises(uses.UseContractError): uses.check_coverage(damaged, [artifact, task], metadata)
        with self.assertRaises(uses.UseContractError): uses.check_coverage(contract, [artifact, task], {uses.key(pointer): []})

    def test_legacy_projection_derives_only_original_unrestricted_inventory(self):
        origin = dict(authority=AUTHORITY, artifact=ARTIFACT,
            identity=dict(plan_dir='/plan', transaction_id='transaction', manifest_digest='d' * 64), journal_sha256='e' * 64)
        content = dict(identity=origin['identity'], journal=dict(sha256=origin['journal_sha256']), authorities=[AUTHORITY])
        row = uses.legacy_projection(origin, content)
        self.assertEqual(row, dict(origin=origin, destinations=[AUTHORITY]))
        projected = uses.project(uses.build([], [], [row]), [], {})
        self.assertEqual(projected['legacy_routes'], [row])
        with self.assertRaises(uses.UseContractError):
            uses.legacy_projection(origin, dict(content, use_contract=uses.build([], [])))
        changed = copy.deepcopy(origin); changed['journal_sha256'] = 'f' * 64
        with self.assertRaises(uses.UseContractError): uses.legacy_projection(changed, content)

    def test_bounds_and_noncanonical_or_malformed_rows_reject(self):
        value = self.contract()
        for rows in ([None], list(reversed(value['roots'])), value['roots'] * (uses.MAX_ROWS + 1)):
            changed = dict(value, roots=rows)
            with self.assertRaises(uses.UseContractError): uses.validate(changed)
        with self.assertRaises(uses.UseContractError): uses.build(self.roots(), [None])
        changed = copy.deepcopy(value); changed['edges'].append(copy.deepcopy(changed['edges'][0]))
        with self.assertRaises(uses.UseContractError): uses.validate(changed)

    def shared_parent_uses(self, incoming, outgoing, flattened=None):
        pointer = dict(authority=AUTHORITY, artifact=ARTIFACT)
        artifact = dict(kind='artifact', reference=pointer)
        task = dict(kind='task', reference=TASK)
        edges = [dict(root=0, parent=None, dependency=artifact, purpose=purpose) for purpose in incoming]
        edges.extend(dict(root=0, parent=pointer, dependency=task, purpose=purpose) for purpose in outgoing)
        edges.extend(dict(root=0, parent=None, dependency=task, purpose=purpose)
            for purpose in (outgoing if flattened is None else flattened))
        return uses.build([self.roots()[0]], edges), [artifact, task], {uses.key(pointer): [task]}

    def test_content_parent_cannot_continue_only_as_retention(self):
        contract, direct, metadata = self.shared_parent_uses(['content'], ['retention-only'])
        with self.assertRaises(uses.UseContractError): uses.check_coverage(contract, direct, metadata)

    def test_shared_parent_needs_content_continuation_for_content_incoming_use(self):
        contract, direct, metadata = self.shared_parent_uses(['retention-only', 'content'], ['retention-only'])
        with self.assertRaises(uses.UseContractError): uses.check_coverage(contract, direct, metadata)
        with self.assertRaises(uses.UseContractError): uses.project(contract, direct, metadata)

    def test_dual_role_parent_preserves_both_roles_through_build_merge_and_project(self):
        contract, direct, metadata = self.shared_parent_uses(['retention-only', 'content'], ['retention-only', 'content'])
        uses.check_coverage(contract, direct, metadata)
        self.assertEqual(uses.merge([contract, contract]), contract)
        self.assertEqual(uses.project(contract, direct, metadata), contract)
        for purpose in ('retention-only', 'content'):
            self.assertTrue(any(row['parent'] is not None and row['purpose'] == purpose for row in contract['edges']))
        # A retention branch may cross an owner boundary and require content.
        crossing, direct, metadata = self.shared_parent_uses(['retention-only'], ['content'])
        uses.check_coverage(crossing, direct, metadata)

    def test_nested_content_requires_corresponding_flattened_content_use(self):
        contract, direct, metadata = self.shared_parent_uses(['content'], ['content'], ['retention-only'])
        with self.assertRaises(uses.UseContractError): uses.check_coverage(contract, direct, metadata)

    def test_retention_continuation_needs_an_actual_retention_incoming_use(self):
        contract, direct, metadata = self.shared_parent_uses(['content'], ['content', 'retention-only'])
        with self.assertRaises(uses.UseContractError): uses.check_coverage(contract, direct, metadata)


if __name__ == '__main__': unittest.main()
