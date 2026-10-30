"""Actual history growth is current read scope, never a rewritten original capture."""
import unittest
from unittest.mock import patch


class PreparationReadContextTests(unittest.TestCase):
    def test_original_capture_survives_real_history_growth_and_full_release(self):
        from runtime import changes, evidence, state
        from tests.test_evidence import LinkedVerificationTests, _run_d4_fixture
        case = LinkedVerificationTests(methodName='test_linked_no_verifier_native_history_survives_d4_retirement_and_guidance')
        self.addCleanup(case.doCleanups)
        case.setUp()
        captured, _, contexts, references = case.no_verifier_stops()
        pointer = captured['reference']
        original_capture = evidence._linked_source(pointer)
        original_tasks = [case.task(member) for member in case.members]
        original_basis = [evidence._read(member.scope, task['writer_stop']['linked']) for member, task in zip(case.members, original_tasks)]
        self.assertEqual(len(original_capture['authorities']), 2)
        fixture, request = case.recovery_fixtures[0]
        self.assertEqual(_run_d4_fixture(fixture, request, 'resume')['exit_code'], 0)
        _, source = case.recovery_head(fixture, contexts[0])
        self.assertEqual(len(source['authorities']), 3)
        self._before_prepare_controls(case, captured, source, contexts, references, original_basis, original_capture)
        calls = []
        original = evidence._linked_bound_basis
        def checked(actual_pointer, authorities, **kwargs):
            result = original(actual_pointer, authorities, **kwargs)
            if actual_pointer == pointer:
                self.assertEqual(len(authorities), 3)
                self.assertTrue(changes._held_authority_guards(__import__('pathlib').Path(a['directory']) for a in authorities))
                self.assertEqual(result['authorities'], original_capture['authorities'])
                calls.append(True)
            return result
        with patch.object(evidence, '_linked_bound_basis', side_effect=checked):
            prepared = evidence._prepare_linked_closure(evidence._observe_linked_preparation(pointer, source['authorities']))
            self.assertTrue(prepared['complete'])
            self.assertEqual(len(prepared['preparations']), 2)
            release = changes._observe_recovery_release(source['authorities'], dict(source['identity']))
            result = changes._register_recovery_release(release)
            self.assertTrue(result['complete'], result)
        self.assertTrue(calls)
        self.assertEqual(evidence._linked_source(pointer), original_capture)
        self.assertEqual([case.task(member) for member in case.members], original_tasks)
        for member, task, basis in zip(case.members, original_tasks, original_basis):
            self.assertEqual(evidence._read(member.scope, task['writer_stop']['linked']), basis)
        self._after_release_controls(case, pointer, source, contexts, references, original_tasks, prepared)

    def _before_prepare_controls(self, case, captured, source, contexts, references, original_basis, original_capture):
        pass

    def _after_release_controls(self, case, pointer, source, contexts, references, original_tasks, prepared):
        pass


class FullPreparationReadRosterTests(unittest.TestCase):
    def test_complete_guarded_roster_survives_full_default_and_none_preparation(self):
        from runtime import changes, evidence, state
        from pathlib import Path
        from tests.test_evidence import LinkedVerificationTests, _run_d4_fixture
        case = LinkedVerificationTests(methodName='test_linked_no_verifier_native_history_survives_d4_retirement_and_guidance')
        self.addCleanup(case.doCleanups)
        case.setUp()
        captured, _, contexts, references = case.no_verifier_stops()
        pointer = captured['reference']
        capture = evidence._linked_source(pointer)
        self.assertEqual(len(capture['authorities']), 2)
        fixture, request = case.recovery_fixtures[0]
        self.assertEqual(_run_d4_fixture(fixture, request, 'resume')['exit_code'], 0)
        _, source = case.recovery_head(fixture, contexts[0])
        self.assertEqual(len(source['authorities']), 3)
        with evidence._linked_stop_guards(pointer, source['authorities']) as current:
            facts = evidence._linked_preparation_facts(pointer, current, read_context=None)
            self.assertEqual(facts['basis'], captured['basis'])
            expired = self.roster_controls(case, captured, capture, contexts, references, current)
        legacy = case.members[1].root / 'state'
        extra = dict(directory=str(legacy), database=str(legacy / 'runtime.sqlite3'),
            directory_binding=evidence._binding(legacy), database_binding=evidence._binding(legacy / 'runtime.sqlite3'))
        with changes._authority_guards(Path(authority['directory']) for authority in [*current, extra]):
            with self.assertRaises(state.StateError):
                evidence._check_linked_read_roster(expired, pointer)
            with self.assertRaisesRegex(state.StateError, 'unrelated authority'):
                with evidence._linked_preparation_read_roster(pointer, [*current, extra]):
                    self.fail('Unrelated held authority entered the component roster')
            with evidence._linked_preparation_read_roster(pointer, current) as exact:
                self.assertEqual(evidence._check_linked_read_roster(exact, pointer), current)
        with changes._authority_guards(Path(authority['directory']) for authority in captured['basis']['authorities']):
            with self.assertRaisesRegex(state.StateError, 'unheld'):
                with evidence._linked_preparation_read_roster(pointer, current):
                    self.fail('Unheld history authority entered the component roster')
        observation = evidence._observe_linked_preparation(pointer, source['authorities'])
        self.assertEqual(evidence._canonical_plain(observation.facts), facts)
        self.assertTrue(evidence._prepare_linked_closure(observation)['complete'])
        with evidence._linked_stop_guards(pointer, source['authorities']) as current:
            self.assertEqual(evidence._linked_preparation_facts(pointer, current, read_context=None), facts)
            with evidence._context_database(contexts[0]) as db:
                self.assertEqual(evidence._linked_preparation_facts(pointer, current, writer=(contexts[0], db)), facts)
        self.assertEqual(evidence._linked_source(pointer), capture)

    def roster_controls(self, case, captured, capture, contexts, references, current):
        from copy import deepcopy
        from dataclasses import replace
        import json
        import threading
        from runtime import changes, evidence, state
        pointer, basis = captured['reference'], captured['basis']
        with evidence._linked_preparation_read_roster(pointer, current) as roster:
            self.assertEqual(evidence._canonical_plain(roster.basis), basis)
            with evidence._context_database(contexts[0]) as db:
                inputs = changes._linked_live_certificate_inputs(contexts[0], db,
                    dict(reference=references[0], pins=case.task(case.members[0])['pins']), basis)
            assembly = changes._linked_live_certificate_assembly(inputs)
            job = next(assembly)
            with self.assertRaises(state.StateError):
                changes._resolve_linked_live_certificate_job(job)
            self.assertEqual(changes._resolve_linked_live_certificate_job(job, read_roster=roster)['result'], basis)
            wrong_basis = deepcopy(basis)
            wrong_basis['members'][0]['revision'] += 1
            for options in (dict(basis=wrong_basis), dict(member=dict(references[0], task_id='not-a-member'))):
                with self.assertRaises(state.StateError):
                    evidence._check_linked_read_roster(roster, pointer, **options)
            copied = replace(roster, guards=tuple(dict(guard) for guard in roster.guards))
            with self.assertRaises(state.StateError):
                evidence._check_linked_read_roster(copied, pointer)
            alias = evidence._canonical_plain(roster.authorities)
            alias[0]['database'] = alias[1]['database']
            with self.assertRaises(state.StateError):
                evidence._check_linked_read_roster(replace(roster, authorities=evidence._canonical_freeze(alias)), pointer)
            with evidence._context_database(contexts[1]) as db:
                with self.assertRaises(state.StateError):
                    evidence._check_linked_read_roster(roster, pointer, writer=(contexts[0], db))
            failures = []
            def other_thread():
                try:
                    evidence._check_linked_read_roster(roster, pointer)
                except state.StateError as error:
                    failures.append(error)
            thread = threading.Thread(target=other_thread, daemon=True)
            thread.start();thread.join(1)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(failures), 1)
            extra = next(authority for authority in current if authority not in basis['authorities'])
            extra_context = evidence._reference_context(extra)
            with evidence._context_database(extra_context) as db:
                extra_reference = evidence._canonical_plain(state._source_baseline(None, db, context=extra_context)['reference'])
            with self.assertRaises(state.StateError):
                evidence._check_linked_read_roster(roster, dict(authority=extra, reference=extra_reference))
            with self.assertRaises(state.StateError):
                with evidence._linked_preparation_read_roster(pointer, basis['authorities']):
                    self.fail('Missing current authority was accepted')
            reference = evidence._linked_source_refs(capture['content']['observations'])[0]
            context = evidence._reference_context(reference['authority'])
            name = reference['reference']['name']
            with evidence._context_database(context, write=True) as db:
                saved = db.execute('select data from evidence_metadata where name=?', (name,)).fetchone()[0]
                metadata = json.loads(saved)
                metadata['dependencies'].append(dict(kind='artifact', reference=dict(authority=extra, artifact=extra_reference)))
                metadata['dependencies'].sort(key=evidence._raw)
                db.execute('update evidence_metadata set data=? where name=?', (json.dumps(metadata), name))
            try:
                with self.assertRaises(state.StateError):
                    changes._resolve_linked_live_certificate_job(job, read_roster=roster)
            finally:
                with evidence._context_database(context, write=True) as db:
                    db.execute('update evidence_metadata set data=? where name=?', (saved, name))
        with self.assertRaisesRegex(state.StateError, 'owner expired'):
            evidence._check_linked_read_roster(roster, pointer)
        # Guards remain held here; ending lexical ownership alone must invalidate it.
        with self.assertRaises(state.StateError):
            evidence._matching_linked_read_roster(roster, basis)
        return roster


class FullReadRosterBoundaryTests(unittest.TestCase):
    def test_explicit_retained_basis_scope_survives_real_raw_retirement(self):
        from runtime import delegation, evidence, state
        from tests.test_evidence import LinkedVerificationTests
        case = LinkedVerificationTests(methodName='runTest')
        self.addCleanup(case.doCleanups)
        case.setUp()
        captured, originals, contexts, references = case.no_verifier_stops()
        pointer, authorities = captured['reference'], captured['basis']['authorities']
        prepared = evidence._prepare_linked_closure(evidence._observe_linked_preparation(pointer, authorities))
        self.assertTrue(prepared['complete'])
        closed = [evidence.close_task(member.scope, case.linked_closure_request(index),
            evidence._observe_closure(contexts, reference))['task']
            for index, (member, reference) in enumerate(zip(case.members, references))]
        for context, reference in zip(contexts, references):
            self.assertTrue(evidence._retire_closed_task(context, reference)['retired'])
        with evidence._linked_stop_guards(pointer, authorities) as current:
            component = evidence._linked_retained_component(pointer, current)
            self.assertEqual(component['basis'], captured['basis'])
            with evidence._linked_preparation_read_roster(pointer, current, basis=component['basis']) as roster:
                for index, (context, reference) in enumerate(zip(contexts, references)):
                    with evidence._context_database(context) as db:
                        self.assertIsNone(evidence._linked_raw_task(db, reference))
                        marker = state._retired(db, 'task', {key: reference[key]
                            for key in ('scope_id', 'client', 'session_id', 'task_id')})
                        self.assertEqual(marker['created_at'], originals[index]['lifecycle']['created_at'])
                        self.assertEqual(marker['outcome'], originals[index]['state'])
                        self.assertEqual(marker['pins_digest'], state._digest(originals[index]['pins']))
                        guidance = delegation._closure_guidance(context, db,
                            delegation._ledger(None, db, context=context), read_roster=roster)
                        self.assertEqual(len(guidance['retained']), 1)
                        self.assertEqual(guidance['retained'][0]['identity'], reference)
                        self.assertEqual(guidance['retained'][0]['reference'], closed[index]['lifecycle']['compact'])
            with self.assertRaises(state.StateError):
                evidence._check_linked_read_roster(roster, pointer)

    def test_real_history_growth_after_first_closure_keeps_recovery_complete(self):
        self.partialclosed_fixture()

    def test_real_history_growth_continues_through_real_retirement(self):
        import json
        from runtime import changes, delegation, evidence, state
        case, captured, originals, contexts, references, source, first, capture = self.partialclosed_fixture()
        pointer = captured['reference']
        second = evidence.close_task(case.members[1].scope, case.linked_closure_request(1),
            evidence._observe_closure(contexts, references[1]))['task']
        print(json.dumps(dict(event='full-roster-boundary', phase='actual-second-closure-under-current-three')), flush=True)
        with patch.object(evidence, '_linked_capture_record',
                side_effect=AssertionError('Closed or retired member selected strict open capture')):
            for index, (context, reference) in enumerate(zip(contexts, references)):
                retired = evidence._retire_closed_task(context, reference)
                self.assertTrue(retired['retired'], retired)
                with evidence._linked_stop_guards(pointer, source['authorities']) as current:
                    component = evidence._linked_retained_component(pointer, current)
                    self.assertEqual(component['basis'], captured['basis'])
                    with evidence._linked_preparation_read_roster(pointer, current, basis=component['basis']) as roster:
                        with evidence._context_database(context) as db:
                            self.assertIsNone(evidence._linked_raw_task(db, reference))
                            marker = state._retired(db, 'task', {key: reference[key]
                                for key in ('scope_id', 'client', 'session_id', 'task_id')})
                            self.assertEqual(marker['created_at'], originals[index]['lifecycle']['created_at'])
                            self.assertEqual(marker['outcome'], originals[index]['state'])
                            self.assertEqual(marker['pins_digest'], state._digest(originals[index]['pins']))
                            self.assertGreaterEqual(marker['retired_at'], (first, second)[index]['lifecycle']['safe_closed_at'])
                            records = delegation._ledger(None, db, context=context)
                            with self.assertRaises(state.StateError):
                                delegation._closure_guidance(context, db, records)
                            guidance = delegation._closure_guidance(context, db, records, read_roster=roster)
                            self.assertEqual(len(guidance['retained']), 1)
                            self.assertEqual(guidance['retained'][0]['identity'], reference)
                public = evidence._canonical_plain(changes.inspect_lifecycle_recovery(source['authorities'], references))
                self.assertTrue(public['complete'], public)
                self.assertFalse(public['blockers'], public)
                print(json.dumps(dict(event='full-roster-boundary', phase='actual-retirement-with-marker-and-guidance', member=index)), flush=True)
        self.assertEqual(evidence._linked_source(pointer), capture)
        self.assertEqual(len(evidence._linked_source(pointer)['authorities']), 2)

    def partialclosed_fixture(self):
        from dataclasses import replace
        import json
        from runtime import changes, delegation, evidence, state
        from tests.test_evidence import LinkedVerificationTests, _run_d4_fixture
        case = LinkedVerificationTests(methodName='test_linked_no_verifier_native_history_survives_d4_retirement_and_guidance')
        self.addCleanup(case.doCleanups)
        case.setUp()
        captured, originals, contexts, references = case.no_verifier_stops()
        pointer, authorities = captured['reference'], captured['basis']['authorities']
        self.assertEqual(len(authorities), 2)
        capture = evidence._linked_source(pointer)
        print(json.dumps(dict(event='full-roster-boundary', phase='original-two-actual-stops')), flush=True)
        self.assertTrue(evidence._prepare_linked_closure(evidence._observe_linked_preparation(pointer, authorities))['complete'])
        print(json.dumps(dict(event='full-roster-boundary', phase='original-complete-preparation')), flush=True)
        first = evidence.close_task(case.members[0].scope, case.linked_closure_request(0),
            evidence._observe_closure(contexts, references[0]))['task']
        self.assertIsNotNone(first['lifecycle']['safe_closed_at'])
        self.assertIsNone(case.task(case.members[1])['lifecycle']['safe_closed_at'])
        print(json.dumps(dict(event='full-roster-boundary', phase='actual-first-closure-under-original-two')), flush=True)
        fixture, request = case.recovery_fixtures[0]
        result = _run_d4_fixture(fixture, request, 'resume')
        self.assertEqual(result['exit_code'], 0, result)
        _, source = case.recovery_head(fixture, contexts[0])
        self.assertEqual(len(source['authorities']), 3)
        print(json.dumps(dict(event='full-roster-boundary', phase='actual-partialclosed-history-three')), flush=True)
        with evidence._linked_stop_guards(pointer, source['authorities']) as current:
            self.assertIsNone(evidence._bind_linked_read_context(pointer, current, basis=captured['basis']))
            with evidence._linked_preparation_read_roster(pointer, current, basis=captured['basis']) as roster:
                with self.assertRaises(state.StateError):
                    evidence._linked_stopped_basis(pointer, captured['basis']['authorities'])
                copied = replace(roster, guards=tuple(dict(guard) for guard in roster.guards))
                with self.assertRaises(state.StateError):
                    changes._inspect_lifecycle_recovery_guarded(current, references, read_roster=copied)
                with self.assertRaises(state.StateError):
                    evidence._check_linked_read_roster(roster, pointer,
                        member=dict(references[0], task_id='unrelated-task'))
                with evidence._context_database(contexts[1]) as db:
                    with self.assertRaises(state.StateError):
                        evidence._check_linked_read_roster(roster, pointer, writer=(contexts[0], db))
                inspected = evidence._canonical_plain(changes._inspect_lifecycle_recovery_guarded(
                    current, references, read_roster=roster))
                self.assertTrue(inspected['complete'], inspected)
                self.assertFalse(inspected['blockers'])
            with self.assertRaises(state.StateError):
                changes._inspect_lifecycle_recovery_guarded(current, references, read_roster=roster)
        public = evidence._canonical_plain(changes.inspect_lifecycle_recovery(current, references))
        self.assertTrue(public['complete'], public)
        self.assertFalse(public['blockers'], public)
        self.assertEqual(public, inspected)
        self.assertEqual(case.task(case.members[0]), first)
        self.assertEqual(evidence._linked_source(pointer), capture)
        return case, captured, originals, contexts, references, source, first, capture



class RecoveryRosterSelectorRoutingTests(unittest.TestCase):
    """Controlled adapter routing only; these stubs prove no lifecycle semantics."""

    def routing(self):
        from contextlib import ExitStack, contextmanager
        from copy import deepcopy
        from types import SimpleNamespace
        from runtime import changes, evidence, state
        authority = lambda name: dict(directory='/routing/' + name)
        a, b, c, d, extra = [authority(name) for name in 'abcde']
        pointers = {name: dict(reference=name) for name in ('A', 'B')}
        bases = {name: dict(root=pointers[name], authorities=[start])
            for name, start in (('A', a), ('B', b))}
        certificates = {name: dict(reference=dict(task_id=name), linked=bases[name]) for name in bases}
        expected = {'A': [a, c], 'B': [b, d]}
        held = {row['directory'] for row in (a, b, c, d, extra)}
        history_reads, bindings = [], []

        def history(pointer, pending):
            history_reads.append((pointer['reference'], deepcopy(pending)))
            self.assertLessEqual({row['directory'] for row in pending}, held)
            return {}, expected[pointer['reference']], {}

        def matching(token, basis):
            if token is None:
                return None
            if not token.active:
                raise state.StateError('Expired controlled routing token')
            if basis is None or token.pointer != basis['root']:
                return None
            if token.basis != basis:
                raise state.StateError('Changed controlled same-root basis')
            return token

        def check(token, pointer, *, basis=None, member=None, writer=None):
            if not token.active or token.pointer != pointer:
                raise state.StateError('Invalid controlled routing token')
            if basis is not None:
                matching(token, basis)
            return token.authorities

        @contextmanager
        def bind(pointer, authorities, *, basis, writer=None):
            selected = expected[pointer['reference']]
            if authorities != selected:
                raise state.StateError('Controlled exact binder rejected unrelated authority')
            token = SimpleNamespace(pointer=pointer, basis=deepcopy(basis), authorities=authorities, active=True)
            bindings.append((pointer['reference'], deepcopy(authorities)))
            try:
                yield token
            finally:
                token.active = False

        @contextmanager
        def controlled():
            with ExitStack() as patches, ExitStack() as scopes:
                for target, name, value in (
                    (evidence, '_linked_basis_root', lambda basis: basis['root']),
                    (evidence, '_linked_stop_sources', history),
                    (evidence, '_matching_linked_read_roster', matching),
                    (evidence, '_check_linked_read_roster', check),
                    (evidence, '_linked_preparation_read_roster', bind),
                    (evidence, '_reference_context', lambda value: value),
                    (evidence, '_check_context', lambda *args: None),
                    (changes, '_held_authority_guards', lambda directories: {str(path) for path in directories} <= held),
                ):
                    patches.enter_context(patch.object(target, name, side_effect=value))
                yield SimpleNamespace(changes=changes, evidence=evidence, state=state, scopes=scopes,
                    authorities=[a, b, c, d, extra], certificates=certificates, expected=expected,
                    held=held, history_reads=history_reads, bindings=bindings, bind=bind)
        return controlled()

    def test_global_inspection_superset_binds_only_exact_component(self):
        with self.routing() as case:
            roster = case.changes._content_linked_read_roster(
                dict(stopped=[case.certificates['A']]), case.authorities, case.scopes, {})
            self.assertEqual(roster.authorities, case.expected['A'])
            self.assertEqual(case.bindings, [('A', case.expected['A'])])

    def test_distinct_certificates_route_independently_in_both_orders(self):
        for order in (('A', 'B'), ('B', 'A')):
            with self.subTest(order=order), self.routing() as case:
                owner = case.changes._RecoveryReadRosters(case.authorities, case.scopes)
                selected = {name: owner.select(case.certificates[name]) for name in order}
                self.assertIsNot(selected['A'], selected['B'])
                self.assertEqual({name: token.authorities for name, token in selected.items()}, case.expected)
                self.assertEqual([name for name, _ in case.bindings], list(order))
                for name in order:
                    self.assertIs(owner.select(case.certificates[name]), selected[name])

    def test_supplied_component_does_not_replace_another_component(self):
        with self.routing() as case:
            cert = case.certificates['A']
            supplied = case.scopes.enter_context(case.bind(cert['linked']['root'], case.expected['A'], basis=cert['linked']))
            owner = case.changes._RecoveryReadRosters(case.authorities, case.scopes, read_roster=supplied)
            self.assertIs(owner.select(cert), supplied)
            other = owner.select(case.certificates['B'])
            self.assertEqual(other.authorities, case.expected['B'])
            self.assertEqual([name for name, _ in case.bindings], ['A', 'B'])

    def test_missing_unheld_changed_and_expired_scopes_reject(self):
        from copy import deepcopy
        from runtime.startup import StartupError
        with self.routing() as case:
            owner = case.changes._RecoveryReadRosters(case.authorities, case.scopes)
            first = owner.select(case.certificates['A'])
            changed = deepcopy(case.certificates['A'])
            changed['linked']['changed'] = True
            with self.assertRaises(case.state.StateError):
                owner.select(changed)
            first.active = False
            with self.assertRaises(case.state.StateError):
                owner.select(case.certificates['A'])
            supplied_owner = case.changes._RecoveryReadRosters(case.authorities, case.scopes, read_roster=first)
            reads = len(case.history_reads)
            with self.assertRaises(case.state.StateError):
                supplied_owner.select(case.certificates['B'])
            self.assertEqual(len(case.history_reads), reads)
        for missing_global, missing_held in ((True, False), (False, True)):
            with self.subTest(global_missing=missing_global, held_missing=missing_held), self.routing() as case:
                if missing_held:
                    case.held.remove('/routing/c')
                allowed = [row for row in case.authorities if not missing_global or row['directory'] != '/routing/c']
                owner = case.changes._RecoveryReadRosters(allowed, case.scopes)
                with self.assertRaises(StartupError):
                    owner.select(case.certificates['A'])
                self.assertEqual(len(case.history_reads), 1)
                self.assertEqual(case.bindings, [])

    def test_existing_reader_uses_checked_subset_and_rechecks_it(self):
        from types import SimpleNamespace
        with self.routing() as case:
            cert = dict(case.certificates['A'], preparation=dict(authorities=case.expected['A']))
            owner = case.changes._RecoveryReadRosters(case.authorities, case.scopes)
            roster = owner.select(cert)
            reader = case.evidence._PreparationReader(case.authorities)
            context = SimpleNamespace(authority_set=[case.expected['A'][0]])
            def retained(pointer, authorities, **kwargs):
                self.assertEqual(authorities, case.expected['A'])
                return dict(aggregate=pointer, authorities=authorities)
            token = case.evidence._PREPARATION_READER.set(reader)
            try:
                with patch.object(case.evidence, '_linked_component_closed', return_value=True), \
                        patch.object(case.evidence, '_linked_retained_component', side_effect=retained) as full, \
                        patch.object(case.evidence, '_check_retained_linked_certificate') as correspondence:
                    reader.check(context, None, cert, read_roster=roster)
                    correspondence.assert_called_once()
                    reader.finish()
                    self.assertEqual(full.call_count, 2)
                    roster.active = False
                    with self.assertRaises(case.state.StateError):
                        reader.finish()
                    self.assertEqual(full.call_count, 2)
            finally:
                case.evidence._PREPARATION_READER.reset(token)

    def test_routing_owner_expiry_and_full_validator_seams_are_preserved(self):
        import ast
        from pathlib import Path
        from runtime.startup import StartupError
        with self.routing() as case:
            owner = case.changes._RecoveryReadRosters(case.authorities, case.scopes)
            owner.active = False
            with self.assertRaises(StartupError):
                owner.select(case.certificates['A'])
            self.assertEqual(case.history_reads, [])
        root = Path(__file__).resolve().parents[1]
        modules = {name: ast.parse((root / 'runtime' / (name + '.py')).read_bytes())
            for name in ('changes', 'evidence')}
        functions = {node.name: node for tree in modules.values() for node in tree.body if isinstance(node, ast.FunctionDef)}
        for name in ('_validate_recovery_references', '_recovery_source_history'):
            checks = [node for node in ast.walk(functions[name]) if isinstance(node, ast.Call)
                and (node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else None)
                == '_check_stopped_certificate']
            self.assertTrue(checks)
            self.assertTrue(all(any(keyword.arg == 'read_roster' for keyword in node.keywords) for node in checks))
        calls = {(node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else None)
            for node in ast.walk(functions['_check_stopped_certificate']) if isinstance(node, ast.Call)}
        self.assertLessEqual({'_stopped_certificate_shape', '_check_linked_preparation_certificate',
            '_linked_retained_component', '_check_retained_linked_certificate', '_check_stopped_task_identity',
            '_ready_stop', '_assignment_certificate'}, calls)


class BorrowedReadHelperContractTests(unittest.TestCase):
    def test_static_helper_calls_match_signatures_and_preserve_tuple_value(self):
        import ast
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        modules = {name: ast.parse((root / 'runtime' / (name + '.py')).read_text())
            for name in ('evidence', 'changes', 'state', 'delegation')}
        names = {'_bind_linked_read_context', '_check_linked_read_context', '_open_linked_read_context_members',
            '_linked_read_authorities', '_finish_linked_read_context', '_matching_linked_read_context',
            '_source_linked_read_context', '_content_linked_read_context', '_check_linked_read_scope',
            '_check_linked_read_roster', '_bind_linked_read_roster', '_linked_preparation_read_roster', '_matching_linked_read_roster',
            '_content_linked_read_roster'}
        signatures = {node.name: node.args for tree in modules.values() for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in names}
        self.assertEqual(set(signatures), names)
        count = 0
        for module, tree in modules.items():
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else None
                if name not in signatures:
                    continue
                count += 1
                with self.subTest(module=module, line=node.lineno, helper=name):
                    arguments = signatures[name]
                    positional = arguments.posonlyargs + arguments.args
                    self.assertFalse(any(isinstance(arg, ast.Starred) for arg in node.args))
                    self.assertFalse(any(keyword.arg is None for keyword in node.keywords))
                    self.assertLessEqual(len(node.args), len(positional))
                    keywords = {keyword.arg for keyword in node.keywords}
                    valid = {arg.arg for arg in positional + arguments.kwonlyargs}
                    self.assertLessEqual(keywords, valid)
                    provided = {arg.arg for arg in positional[:len(node.args)]}
                    self.assertFalse(provided & keywords)
                    required = {arg.arg for arg in positional[:len(positional) - len(arguments.defaults)]}
                    self.assertLessEqual(required, provided | keywords)
        self.assertGreater(count, 0)
        replacements = next(node for node in modules['evidence'].body if isinstance(node, ast.FunctionDef)
            and node.name == '_linked_prepared_replacements')
        returned = next(node.value for node in ast.walk(replacements) if isinstance(node, ast.Return))
        self.assertIsInstance(returned, ast.Call)
        self.assertEqual(returned.func.id, '_finish_linked_read_context')
        self.assertEqual(len(returned.args), 2)
        self.assertIsInstance(returned.args[0], ast.Tuple)
        self.assertEqual([node.id for node in returned.args[0].elts], ['result', 'extra', 'routes'])
