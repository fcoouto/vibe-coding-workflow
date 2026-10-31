"""Pure supplied-graph comparisons; these tests do not authenticate stored sources."""
import copy
import unittest
from runtime import recovery_uses as uses
from tests.test_recovery_uses import AUTHORITY, ARTIFACT, TASK
PROOF = dict(authority=AUTHORITY, artifact=ARTIFACT)
TASK_EDGE = dict(kind='task', reference=TASK)
PROOF_EDGE = dict(kind='artifact', reference=PROOF)
PENDING_POINTER = dict(authority=AUTHORITY, artifact=dict(name='e' * 32 + '.json', digest='f' * 64))
HISTORICAL = dict(purpose='historical-stop', reference=TASK_EDGE, task=TASK, proof=PROOF, effect=dict(action_id='change', path='AGENTS.md'))
CONTENT = dict(purpose='content', reference=TASK_EDGE)
LEGACY = dict(origin=dict(authority=AUTHORITY, artifact=ARTIFACT,
    identity=dict(plan_dir='/plan', transaction_id='transaction', manifest_digest='e' * 64), journal_sha256='f' * 64), destinations=[AUTHORITY])

class IssuedProgramComparisonTests(unittest.TestCase):
    def fixture(self, *, starts=True, shared_pointer=False):
        pointer = dict(authority=AUTHORITY, artifact=dict(name='c' * 32 + '.json', digest='d' * 64))
        start_edge = dict(kind='recovery', reference=pointer)
        child = dict(kind='task', reference=TASK)
        roots = [HISTORICAL, CONTENT]
        edges = [
            dict(root=0, parent=None, dependency=TASK_EDGE, purpose='retention-only'),
            dict(root=0, parent=None, dependency=PROOF_EDGE, purpose='retention-only'),
            dict(root=1, parent=None, dependency=TASK_EDGE, purpose='content'),
        ]
        payload_direct = [TASK_EDGE, PROOF_EDGE]
        history_metadata = {}
        payload_metadata = {uses.key(PROOF): []}
        pending_starts = [pointer] if starts else []
        if starts:
            edges.extend([dict(root=0, parent=None, dependency=start_edge, purpose='retention-only'),
                dict(root=0, parent=pointer, dependency=child, purpose='retention-only')])
            history_metadata[uses.key(pointer)] = [child]
            if shared_pointer:
                edges.extend([
                    dict(root=1, parent=None, dependency=start_edge, purpose='content'),
                    dict(root=1, parent=pointer, dependency=child, purpose='content'),
                ])
                payload_direct.append(start_edge)
                payload_metadata.update(copy.deepcopy(history_metadata))
        program = uses.build(roots, edges)
        anchor = dict(root=HISTORICAL, support=[TASK_EDGE, PROOF_EDGE])
        direct = list({uses.key(row): row for row in payload_direct + ([start_edge] if starts else [])}.values())
        return dict(program=program, direct=direct,
            legacy_routes=copy.deepcopy(program['legacy_routes']),
            payload_direct=payload_direct,
            payload_metadata=payload_metadata,
            history_metadata=history_metadata, starts=pending_starts, anchors=[anchor],
            pending_jobs=[], pending_parents=[], budget=uses.CaptureBudget())
    def compare(self, value):
        comparator = self.comparator()
        inputs = dict(value)
        program = inputs.pop('program')
        return comparator(program, **inputs), program
    def comparator(self):
        helper = getattr(uses, 'compare_issued_program', None)
        self.assertTrue(callable(helper), 'issued-program comparator is missing')
        return helper
    def assert_complete_obligations(self, result, program):
        self.assertTrue(result['comparison_only'])
        self.assertEqual(result['pending_jobs'], [])
        self.assertEqual(result['pending_parents'], [])
        self.assertEqual({uses.key({k: v for k, v in row.items() if k != 'requirement'})
            for row in result['obligations']}, {uses.key(row) for row in program['edges']})
    def test_payload_only_and_generated_start_are_compared_as_exact_union(self):
        only = self.fixture(starts=False)
        only['program'] = uses.build([CONTENT], [dict(root=0, parent=None,
            dependency=TASK_EDGE, purpose='content')])
        only['direct'] = only['payload_direct'] = [TASK_EDGE]
        only['payload_metadata'] = {}; only['history_metadata'] = {}; only['anchors'] = []
        result, program = self.compare(only)
        self.assert_complete_obligations(result, program)
        value = self.fixture()
        result, program = self.compare(value)
        self.assert_complete_obligations(result, program)
        supported = [row for row in result['obligations'] if row['purpose'] == 'retention-only']
        self.assertTrue(any(row['dependency'] == dict(kind='recovery', reference=value['starts'][0])
            for row in supported))
        self.assertTrue(any(row['requirement'] == 'validated-stop-support' for row in supported))
        self.assertTrue(any(row['requirement'] == 'current-permission' for row in supported))
    def test_coincident_and_shared_pointer_occurrences_keep_both_reasons(self):
        value = self.fixture(shared_pointer=True)
        result, program = self.compare(value)
        self.assert_complete_obligations(result, program)
        rows = [row for row in result['obligations'] if row['parent'] is not None]
        self.assertEqual({row['purpose'] for row in rows}, {'content', 'retention-only'})
        self.assertEqual({row['requirement'] for row in rows}, {'current-permission', 'validated-stop-support'})
    def test_same_root_parent_requires_content_continuation_even_with_retention(self):
        value = self.fixture()
        pointer = value['starts'][0]
        start_edge = dict(kind='recovery', reference=pointer)
        child = dict(kind='task', reference=TASK)
        root = value['program']['roots'].index(HISTORICAL)
        rows = value['program']['edges'] + [
            dict(root=root, parent=None, dependency=start_edge, purpose='content'),
            dict(root=root, parent=None, dependency=TASK_EDGE, purpose='content'),
            dict(root=root, parent=pointer, dependency=child, purpose='content'),
        ]
        value['payload_direct'].append(start_edge)
        value['payload_metadata'][uses.key(pointer)] = [child]
        value['program'] = uses.build(value['program']['roots'], rows)
        value['budget'] = uses.CaptureBudget()
        complete, complete_program = self.compare(copy.deepcopy(value))
        self.assert_complete_obligations(complete, complete_program)
        rows = [row for row in value['program']['edges'] if not (
            row['root'] == root and row['parent'] == pointer and row['purpose'] == 'content')]
        self.assertTrue(any(row['root'] == root and row['parent'] == pointer and
            row['purpose'] == 'retention-only' for row in rows))
        value['program'] = uses.build(value['program']['roots'], rows)
        comparator = self.comparator()
        program = value.pop('program')
        pending = copy.deepcopy(value)
        pending['pending_jobs'] = [dict(kind='managed-source', reference=PENDING_POINTER)]
        pending['budget'] = uses.CaptureBudget()
        with self.assertRaises(uses.UseContractError): comparator(program, **pending)
        partial = copy.deepcopy(pending)
        partial['pending_jobs'] = []
        partial['pending_parents'] = [PENDING_POINTER]
        partial['budget'] = uses.CaptureBudget()
        with self.assertRaises(uses.UseContractError): comparator(program, **partial)
    def test_pending_job_does_not_hide_wrong_historical_seed_root_or_purpose(self):
        for change in ('root', 'purpose'):
            with self.subTest(change=change):
                value = self.fixture()
                start = next(row for row in value['program']['edges'] if row['parent'] is None and
                    row['dependency']['kind'] == 'recovery')
                if change == 'root':
                    start['root'] = value['program']['roots'].index(CONTENT)
                    start['purpose'] = 'content'
                else: start['purpose'] = 'content'
                value['program'] = uses.build(value['program']['roots'], value['program']['edges'])
                value['pending_jobs'] = [dict(kind='managed-source', reference=PENDING_POINTER)]
                comparator = self.comparator()
                program = value.pop('program')
                with self.assertRaises(uses.UseContractError): comparator(program, **value)
    def test_legacy_inventory_must_match_supplied_canonical_rows_exactly(self):
        comparator = self.comparator()
        value = self.fixture(); value['legacy_routes'] = [copy.deepcopy(LEGACY)]
        program = uses.build(value['program']['roots'], value['program']['edges'], [LEGACY])
        value.pop('program')
        result = comparator(program, **value)
        self.assert_complete_obligations(result, program)
        for supplied, candidate in (([], [LEGACY]), ([LEGACY], [])):
            with self.subTest(supplied=bool(supplied), candidate=bool(candidate)):
                value = self.fixture(); value['legacy_routes'] = copy.deepcopy(supplied)
                program = uses.build(value['program']['roots'], value['program']['edges'], candidate)
                value.pop('program')
                with self.assertRaises(uses.UseContractError): comparator(program, **value)
    def test_wrong_root_parent_purpose_and_missing_or_extra_edges_reject(self):
        for change in ('parent', 'missing', 'extra'):
            with self.subTest(change=change):
                value = self.fixture()
                rows = value['program']['edges']
                generated = next(row for row in rows if row['parent'] is None and row['dependency']['kind'] == 'recovery')
                if change == 'parent': next(row for row in rows if row['parent'] is not None)['parent'] = dict(
                    authority=AUTHORITY, artifact=dict(name='e' * 32 + '.json', digest='f' * 64))
                elif change == 'missing': rows.remove(generated)
                else: rows.append(dict(root=value['program']['roots'].index(CONTENT), parent=None,
                    dependency=dict(kind='artifact', reference=dict(authority=AUTHORITY,
                        artifact=dict(name='e' * 32 + '.json', digest='f' * 64))), purpose='content'))
                value['program'] = uses.build(value['program']['roots'], rows)
                comparator = self.comparator()
                value.pop('program')
                with self.assertRaises(uses.UseContractError): comparator(uses.build(
                    [HISTORICAL, CONTENT], rows), **value)
    def test_pending_jobs_or_parents_leave_comparison_incomplete(self):
        for field, pending in (
            ('pending_jobs', [dict(kind='managed-source', reference=PENDING_POINTER)]),
            ('pending_parents', None),
        ):
            with self.subTest(field=field):
                value = self.fixture()
                if field == 'pending_parents':
                    pointer = value['starts'][0]
                    value[field] = [pointer]
                    value['history_metadata'] = {}
                    rows = [row for row in value['program']['edges'] if row['parent'] != pointer]
                    value['program'] = uses.build(value['program']['roots'], rows)
                else: value[field] = pending
                result, _ = self.compare(value)
                self.assertTrue(result['comparison_only'])
                self.assertIsNone(result['obligations'])
                self.assertEqual(result[field], value[field])
    def test_declared_present_malformed_and_undeclared_missing_parent_reject(self):
        comparator = self.comparator()
        pointer = self.fixture()['starts'][0]
        present = self.fixture(); present['pending_parents'] = [pointer]
        present['history_metadata'][uses.key(pointer)] = [None]
        program = present.pop('program')
        with self.assertRaises(uses.UseContractError): comparator(program, **present)
        missing = self.fixture(); missing['history_metadata'] = {}
        program = missing.pop('program')
        with self.assertRaises(uses.UseContractError): comparator(program, **missing)
    def test_partial_graph_rejects_missing_seed_or_known_child(self):
        comparator = self.comparator()
        for missing in ('seed', 'child'):
            with self.subTest(missing=missing):
                value = self.fixture(); value['pending_parents'] = [PENDING_POINTER]
                rows = value['program']['edges']
                if missing == 'seed':
                    rows = [row for row in rows if not (row['parent'] is None and
                        row['dependency']['kind'] == 'recovery')]
                else: rows = [row for row in rows if not (row['parent'] is not None and
                    row['purpose'] == 'retention-only')]
                value['program'] = uses.build(value['program']['roots'], rows)
                program = value.pop('program')
                with self.assertRaises(uses.UseContractError): comparator(program, **value)
    def test_disconnected_known_component_waits_for_unresolved_parent_closure(self):
        value = self.fixture(); start = value['starts'][0]
        value['history_metadata'] = {uses.key(PENDING_POINTER): []}
        value['pending_parents'] = [start]
        partial, _ = self.compare(value)
        self.assertIsNone(partial['obligations'])
        complete = copy.deepcopy(value); complete['pending_parents'] = []
        complete['history_metadata'][uses.key(start)] = [TASK_EDGE]
        program = complete.pop('program')
        with self.assertRaises(uses.UseContractError): self.comparator()(program, **complete)
    def test_reached_partial_content_frontier_requires_flattened_known_child(self):
        value = self.fixture()
        a = PENDING_POINTER
        b = dict(authority=AUTHORITY, artifact=dict(name='9' * 32 + '.json', digest='8' * 64))
        other_task = dict(TASK, task_id='other-task')
        a_edge = dict(kind='recovery', reference=a)
        b_edge = dict(kind='recovery', reference=b)
        other_edge = dict(kind='task', reference=other_task)
        roots = copy.deepcopy(value['program']['roots'])
        content_root = roots.index(CONTENT)
        roots[content_root] = dict(purpose='content', reference=a_edge)
        rows = [row for row in value['program']['edges'] if not (
            row['root'] == content_root and row['parent'] is None)]
        rows.extend([dict(root=content_root, parent=None, dependency=a_edge, purpose='content'),
            dict(root=content_root, parent=a, dependency=b_edge, purpose='content'),
            dict(root=content_root, parent=b, dependency=other_edge, purpose='content')])
        value['program'] = uses.build(roots, rows)
        value['payload_direct'].append(a_edge)
        value['payload_metadata'][uses.key(b)] = [other_edge]
        value['direct'] = list({uses.key(row): row for row in value['payload_direct'] + [
            dict(kind='recovery', reference=pointer) for pointer in value['starts']]}.values())
        value['pending_parents'] = [a]
        program = value.pop('program')
        with self.assertRaises(uses.UseContractError): self.comparator()(program, **value)
    def test_empty_parent_is_observed_but_missing_or_disconnected_parent_rejects(self):
        value = self.fixture(starts=False)
        result, program = self.compare(value)
        self.assert_complete_obligations(result, program)
        missing = copy.deepcopy(value)
        del missing['payload_metadata'][uses.key(PROOF)]
        comparator = self.comparator()
        program = missing.pop('program')
        with self.assertRaises(uses.UseContractError): comparator(program, **missing)
        disconnected = self.fixture()
        extra = dict(authority=AUTHORITY,
            artifact=dict(name='e' * 32 + '.json', digest='f' * 64))
        disconnected['history_metadata'][uses.key(extra)] = []
        program = disconnected.pop('program')
        with self.assertRaises(uses.UseContractError): comparator(program, **disconnected)
    def test_cycles_and_unequal_intersecting_metadata_reject(self):
        cyclic = self.fixture(shared_pointer=True)
        pointer = cyclic['starts'][0]
        cycle = dict(kind='recovery', reference=pointer)
        for graph in ('payload_metadata', 'history_metadata'):
            cyclic[graph][uses.key(pointer)] = [cycle]
        rows = [row for row in cyclic['program']['edges'] if row['parent'] != pointer]
        for root, purpose in ((cyclic['program']['roots'].index(HISTORICAL), 'retention-only'),
            (cyclic['program']['roots'].index(CONTENT), 'content')):
            rows.append(dict(root=root, parent=pointer, dependency=cycle, purpose=purpose))
        cyclic['program'] = uses.build(cyclic['program']['roots'], rows)
        comparator = self.comparator()
        program = cyclic.pop('program')
        with self.assertRaises(uses.UseContractError): comparator(program, **cyclic)
        unequal = self.fixture(shared_pointer=True)
        other = dict(TASK, task_id='other-task')
        unequal['history_metadata'][uses.key(pointer)] = [dict(kind='task', reference=other)]
        program = unequal.pop('program')
        with self.assertRaises(uses.UseContractError): comparator(program, **unequal)
    def test_duplicate_nonmember_anchor_and_wrong_task_support_reject(self):
        comparator = self.comparator()
        for change in ('duplicate', 'nonmember', 'task-support'):
            with self.subTest(change=change):
                value = self.fixture()
                if change == 'duplicate': value['anchors'].append(copy.deepcopy(value['anchors'][0]))
                elif change == 'nonmember':
                    value['anchors'][0]['root'] = dict(HISTORICAL,
                        effect=dict(action_id='other', path='other.md'))
                else:
                    wrong = dict(TASK, task_id='other-task')
                    value['anchors'][0]['support'][0] = dict(kind='task', reference=wrong)
                program = value.pop('program')
                with self.assertRaises(uses.UseContractError): comparator(program, **value)
    def test_every_edge_gets_its_exact_independent_requirement_label(self):
        value = self.fixture()
        result, program = self.compare(value)
        pointer = value['starts'][0]
        history_root = program['roots'].index(HISTORICAL)
        content_root = program['roots'].index(CONTENT)
        expected = {
            uses.key(dict(root=history_root, parent=None, dependency=TASK_EDGE, purpose='retention-only')):
                'validated-stop-support',
            uses.key(dict(root=history_root, parent=None, dependency=PROOF_EDGE, purpose='retention-only')):
                'validated-stop-support',
            uses.key(dict(root=history_root, parent=None, dependency=dict(kind='recovery', reference=pointer),
                purpose='retention-only')): 'current-permission',
            uses.key(dict(root=history_root, parent=pointer, dependency=TASK_EDGE, purpose='retention-only')):
                'validated-stop-support',
            uses.key(dict(root=content_root, parent=None, dependency=TASK_EDGE, purpose='content')):
                'current-permission',
        }
        labels = {uses.key({key: item for key, item in row.items() if key != 'requirement'}): row['requirement']
            for row in result['obligations']}
        self.assertEqual(labels, expected)
    def test_shared_budget_bounds_generated_rows(self):
        value = self.fixture()
        value['budget'] = uses.CaptureBudget(edges=len(value['program']['edges']) + 1)
        comparator = self.comparator()
        program = value.pop('program')
        with self.assertRaises(uses.UseContractError): comparator(program, **value)
        self.assertEqual(value['budget'].used['edges'], value['budget'].limits['edges'])
    def test_preconsumed_budget_is_shared_and_pending_does_not_enqueue_jobs(self):
        comparator = self.comparator()
        complete = self.fixture()
        complete['budget'].take(jobs=2, bytes=100)
        before = dict(complete['budget'].used)
        result, _ = self.compare(complete)
        self.assertIsNotNone(result['obligations'])
        self.assertGreater(complete['budget'].used['bytes'], before['bytes'])
        self.assertEqual(complete['budget'].used['jobs'], before['jobs'])
        pending = self.fixture()
        pending['pending_jobs'] = [dict(kind='managed-source', reference=PENDING_POINTER)]
        pending['budget'].take(jobs=3, bytes=100)
        before = dict(pending['budget'].used)
        incomplete, _ = self.compare(pending)
        self.assertIsNone(incomplete['obligations'])
        self.assertGreater(pending['budget'].used['bytes'], before['bytes'])
        self.assertEqual(pending['budget'].used['jobs'], before['jobs'])
    def test_preconsumed_budget_exhaustion_cannot_be_reset(self):
        value = self.fixture()
        value['budget'] = uses.CaptureBudget(bytes=256)
        value['budget'].take(bytes=255)
        comparator = self.comparator()
        program = value.pop('program')
        with self.assertRaises(uses.UseContractError): comparator(program, **value)
        self.assertEqual(value['budget'].used['bytes'], 255)

if __name__ == '__main__': unittest.main()
