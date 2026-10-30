"""Genuine release/preparation owner reader lifetimes; no successful resolver substitutes."""
from contextlib import closing, contextmanager, nullcontext
from copy import deepcopy
import ast
import inspect
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import textwrap
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class PreparationMemberReaderTests(unittest.TestCase):
    def test_original_guidance_jobs_outlive_member_and_previous_job_readers(self):
        from runtime import changes, delegation, evidence
        from tests.test_release_source_preflight import ReleaseSourcePreflightTests
        outer = set()
        member_handles = []
        jobs = []
        read_calls = []
        original_database = evidence._preparation_database
        original_resolve = delegation._resolve_closure_guidance_job
        original_read = evidence._linked_preparation_read_facts
        source, first_line = inspect.getsourcelines(evidence._linked_preparation_steps)
        member_reader_line = next(first_line + node.lineno - 1
            for node in ast.walk(ast.parse(textwrap.dedent(''.join(source))))
            if isinstance(node, ast.With) and any(
                isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr == '_closure_assignments' for call in ast.walk(node)))
        case = ReleaseSourcePreflightTests(methodName='test_actual_release_owner_closes_outer_reader_before_original_jobs')
        def active():
            lifetime = getattr(changes._authority_context, 'publication', None)
            return lifetime and lifetime['active'] and lifetime['kind'] == 'release'
        @contextmanager
        def tracked(*args, **kwargs):
            frame = inspect.currentframe().f_back
            while frame and frame.f_code.co_filename != evidence.__file__:
                frame = frame.f_back
            owned = active() and frame and (
                frame.f_code.co_name == '_linked_preparation_member_inputs'
                or frame.f_code.co_name == '_linked_preparation_steps'
                and frame.f_lineno == member_reader_line)
            if owned and frame.f_code.co_name == '_linked_preparation_member_inputs':
                for previous, _ in jobs:
                    with self.assertRaises(sqlite3.ProgrammingError):
                        previous.execute('select 1')
            with original_database(*args, **kwargs) as db:
                if owned:
                    outer.add(db)
                    member_handles.append(db)
                try:
                    yield db
                finally:
                    if owned:
                        outer.remove(db)
        def read(*args, **kwargs):
            if active():
                read_calls.append(True)
            return original_read(*args, **kwargs)
        def resolve(context, db, job, *, read_context=None, read_roster=None):
            frame = inspect.currentframe().f_back
            member_job = False
            while frame:
                if frame.f_code.co_filename == evidence.__file__ and frame.f_code.co_name in (
                        '_linked_preparation_steps', '_observe_linked_preparation_member'):
                    member_job = True
                    break
                frame = frame.f_back
            if active() and read_calls and member_job:
                self.assertFalse(outer, 'Original guidance job entered with owned preparation member reader open')
                for previous, _ in jobs:
                    with self.assertRaises(sqlite3.ProgrammingError):
                        previous.execute('select 1')
                jobs.append((db, job['kind']))
            return original_resolve(context, db, job, read_context=read_context, read_roster=read_roster)
        with patch.object(evidence, '_preparation_database', side_effect=tracked), \
                patch.object(evidence, '_linked_preparation_read_facts', side_effect=read), \
                patch.object(delegation, '_resolve_closure_guidance_job', side_effect=resolve):
            try:
                case.test_actual_release_owner_closes_outer_reader_before_original_jobs()
            finally:
                self.assertTrue(case.doCleanups())
        self.assertTrue(read_calls, 'Genuine release did not reach the eligible read-only preparation path')
        self.assertGreaterEqual(len(jobs), 2)
        self.assertIn('bookkeeping', [kind for _, kind in jobs])
        self.assertFalse(outer)
        for db in member_handles + [db for db, _ in jobs]:
            with self.assertRaises(sqlite3.ProgrammingError):
                db.execute('select 1')


class PreparationMemberReaderControlTests(unittest.TestCase):
    """Bounded scheduling/input seams; the genuine release test exercises original validators."""

    def test_missing_mismatched_response_and_original_resolver_failure_deny(self):
        from runtime import delegation, evidence, state
        job = dict(kind='bookkeeping', reference=dict(name='control', digest='control'), body={})
        handles = []
        @contextmanager
        def database(context):
            db = sqlite3.connect(':memory:')
            handles.append(db)
            try:
                yield db
            finally:
                db.close()
        read_context, read_roster = object(), object()
        for response in (None, dict(job={}, result=False), state.StateError('Original resolver failed')):
            with self.subTest(response=response), \
                    patch.object(evidence, '_linked_preparation_member_inputs', return_value=dict(guidance={})), \
                    patch.object(evidence, '_context_database', side_effect=database), \
                    patch.object(delegation, '_closure_guidance_assembly', side_effect=lambda inputs: delegation._closure_guidance_job(job)), \
                    patch.object(delegation, '_resolve_closure_guidance_job',
                        **({'side_effect': response} if isinstance(response, Exception) else {'return_value': response})) as resolve:
                with self.assertRaises(state.StateError):
                    evidence._observe_linked_preparation_member(None, None, None, None, None,
                        read_context=read_context, read_roster=read_roster)
                resolve.assert_called_once_with(None, handles[-1], job,
                    read_context=read_context, read_roster=read_roster)
                with self.assertRaises(sqlite3.ProgrammingError):
                    handles[-1].execute('select 1')

    def test_recollection_rejects_new_unsupported_family(self):
        from runtime import evidence, state
        guidance = dict(authority={}, records=[], rows=[], cache=dict(references=[], files={}, folder=None))
        inputs = dict(guidance=guidance, records=[], projection={})
        with patch.object(evidence, '_linked_preparation_member_inputs', side_effect=[inputs, None]) as collect:
            with self.assertRaisesRegex(state.StateError, 'inputs changed during guidance'):
                evidence._observe_linked_preparation_member(None, None, None, None, None)
            self.assertEqual(collect.call_count, 2)

    def test_storage_changes_during_original_bookkeeping_reject_recollection(self):
        """Collector seam, real raw generations/files and original False bookkeeping; no certificate qualification."""
        from runtime import changes, delegation, evidence, state
        reference = dict(scope_id='scope', client='client', session_id='session', task_id='task')
        assignments = [dict(id='assignment')]
        original_resolve = delegation._resolve_closure_guidance_job
        original_assembly = delegation._closure_guidance_assembly
        job = dict(kind='bookkeeping', reference=dict(name='receipt.json', digest='control'),
            body=dict(kind='linked-closure-preparation'))
        guidance = dict(authority={}, records=[], rows=[], cache=dict(references=[], files={}, folder=None))
        for change in ('task-generation', 'assignment-generation', 'new-ledger-owner', 'receipt', 'physical-membership'):
            with self.subTest(change=change), TemporaryDirectory() as directory:
                root = Path(directory)
                database_path = root / 'runtime.sqlite3'
                folder = root / 'evidence'
                folder.mkdir()
                receipt = folder / 'receipt.json'
                receipt.write_text('{}')
                with closing(sqlite3.connect(database_path)) as db, db:
                    db.execute('create table tasks(scope_id,client,session_id,task_id,data)')
                    db.execute('create table assignments(id,data)')
                    db.execute('insert into tasks values(?,?,?,?,?)', (*reference.values(), '{}'))
                    db.execute('insert into assignments values(?,?)', ('assignment', '{}'))
                job_handles, reads = [], []
                @contextmanager
                def database(context):
                    db = sqlite3.connect(database_path.as_uri() + '?mode=ro', uri=True)
                    try:
                        yield db
                    finally:
                        db.close()
                def collect(*args, **kwargs):
                    for previous in job_handles:
                        with self.assertRaises(sqlite3.ProgrammingError):
                            previous.execute('select 1')
                    reads.append(True)
                    with database(None) as db:
                        generation = changes._recovery_generation(db, [dict(reference=reference)], assignments)
                        ledger = db.execute('select id,data from assignments order by id').fetchall()
                    return dict(guidance=deepcopy(guidance), records=[], projection={}, generation=generation,
                        ledger=ledger, physical=evidence._closure_file_stat(receipt), files=sorted(path.name for path in folder.iterdir()))
                def assembly(inputs):
                    self.assertIs((yield from delegation._closure_guidance_job(job)), False)
                    return (yield from original_assembly(inputs))
                def resolve(context, db, actual, **kwargs):
                    result = original_resolve(context, db, actual, **kwargs)
                    job_handles.append(db)
                    if change in ('task-generation', 'assignment-generation', 'new-ledger-owner'):
                        with closing(sqlite3.connect(database_path)) as writer, writer:
                            if change == 'new-ledger-owner':
                                writer.execute('insert into assignments values(?,?)', ('other-owner', '{}'))
                            else:
                                table = 'tasks' if change == 'task-generation' else 'assignments'
                                writer.execute('update ' + table + ' set data=?', (json.dumps({}, indent=2) + ' ',))
                    elif change == 'receipt':
                        receipt.rename(folder / 'moved-receipt.json')
                    else:
                        (folder / 'unregistered.json').write_text('{}')
                    return result
                with patch.object(evidence, '_linked_preparation_member_inputs', side_effect=collect), \
                        patch.object(evidence, '_context_database', side_effect=database), \
                        patch.object(delegation, '_closure_guidance_assembly', side_effect=assembly), \
                        patch.object(delegation, '_resolve_closure_guidance_job', side_effect=resolve) as resolve_job:
                    with self.assertRaises(state.StateError):
                        evidence._observe_linked_preparation_member(None, None, None, None, None)
                    self.assertEqual(len(reads), 2)
                    resolve_job.assert_called_once()
                for db in job_handles:
                    with self.assertRaises(sqlite3.ProgrammingError):
                        db.execute('select 1')

    def test_complete_unsupported_ledger_and_cache_inputs_select_initial_fallback(self):
        from runtime import changes, delegation, evidence, state
        task = dict(writer_stop=dict(linked={}), lifecycle=dict(safe_closed_at=None),
            evidence=dict(attempts=[dict(id='ordinary', kind='check', status='passed')]))
        ref = dict(authority={}, scope_id='scope', client='client', session_id='session', task_id='task')
        ordinary = dict(id='ordinary', owner=ref, data=dict(role='check', status='settled',
            result=dict(outcome='completed'), reconciliation={}, lifecycle={}, observation={}))
        foreign = dict(owner=dict(ref, task_id='other'), data=dict(role='worker', status='settled', result=dict(outcome='completed')))
        basis = dict(version=2, members=[dict(task=dict(ref, authority={}))])
        for family in ('whole-ledger', 'cache', 'orphan-control', 'malformed-guidance'):
            with self.subTest(family=family), TemporaryDirectory() as directory:
                context = SimpleNamespace(directory=Path(directory))
                if family == 'orphan-control':
                    folder = context.directory / 'model-guidance'
                    folder.mkdir()
                    (folder / 'control.control.json').write_text('{}')
                records = [ordinary, foreign] if family == 'whole-ledger' else [ordinary]
                guidance = dict(cache=dict(references=[], files={}, folder=None))
                if family == 'cache':
                    guidance['cache'] = dict(references=[], files={'control': {}}, folder={'path': 'cache'})
                db = Mock()
                db.execute.return_value.fetchone.return_value = None
                def read(scope, reference, **kwargs):
                    return (dict(version=2, proof=dict(kind='check-writer-reconciliation'), current_candidate={})
                        if reference is ordinary['data']['reconciliation'] else basis)
                ordinary['data']['lifecycle'] = dict(created_at=1)
                with patch.object(evidence, '_preparation_database', return_value=nullcontext(db)), \
                        patch.object(state, '_task', return_value=task), \
                        patch.object(evidence, '_read', side_effect=read), \
                        patch.object(changes, '_stopped_certificate_shape'), \
                        patch.object(delegation, '_ledger', return_value=records), \
                        patch.object(delegation, '_closure_guidance_inputs',
                            **({'side_effect': state.StateError('Malformed original guidance')} if family == 'malformed-guidance'
                                else {'return_value': guidance})) as capture, \
                        patch.object(evidence, '_evidence_inventory_rows', return_value=[]), \
                        patch.object(delegation, '_resolve_closure_guidance_job') as resolve:
                    if family == 'malformed-guidance':
                        with self.assertRaisesRegex(state.StateError, 'Malformed original guidance'):
                            evidence._observe_linked_preparation_member(context, ref, task, basis, {})
                    else:
                        self.assertIsNone(evidence._observe_linked_preparation_member(context, ref, task, basis, {}))
                    capture.assert_called_once_with(context, db, records)
                    resolve.assert_not_called()

    def test_same_component_mandate_reaches_later_validation_without_authenticating_it(self):
        """Classification only; later original certificate and bookkeeping validation must still run."""
        from runtime import changes, delegation, evidence, state
        ref = dict(authority={}, scope_id='scope', client='client', session_id='session', task_id='task')
        linked, reconciliation = {}, {}
        task = dict(writer_stop=dict(linked=linked), pins={}, lifecycle=dict(safe_closed_at=None),
            evidence=dict(attempts=[dict(id='ordinary', kind='check', status='passed')]))
        basis = dict(version=2, members=[dict(task=ref)])
        ordinary = dict(id='ordinary', owner=ref, data=dict(role='check', status='settled',
            result=dict(outcome='completed'), reconciliation=reconciliation,
            lifecycle=dict(created_at=1), observation={}))
        compact = dict(name='compact.json', digest='control')
        class LaterValidationReached(Exception):
            pass
        for kind, owner, allowed in (
                ('linked-closure-preparation', ref, True), ('source-import-mandate', ref, True),
                ('source-import-mandate', dict(ref, task_id='other'), False),
                ('foreign-content-intent', ref, False), ('retained-task-closure', ref, False),
                ('unknown', ref, False)):
            with self.subTest(kind=kind, owner=owner['task_id']), TemporaryDirectory() as directory:
                context = SimpleNamespace(directory=Path(directory))
                db = Mock()
                db.execute.return_value.fetchone.return_value = None
                guidance = dict(cache=dict(references=[], files={}, folder=None),
                    rows=[(compact['name'], compact['digest'])],
                    metadata={compact['name']: dict(owner=dict(task=owner))},
                    bodies={evidence._raw(compact).decode(): dict(kind=kind)})
                def read(scope, reference, **kwargs):
                    return (basis if reference is linked else
                        dict(version=2, proof=dict(kind='check-writer-reconciliation'), current_candidate={}))
                with patch.object(evidence, '_preparation_database', return_value=nullcontext(db)), \
                        patch.object(state, '_task', return_value=task), \
                        patch.object(evidence, '_read', side_effect=read), \
                        patch.object(changes, '_stopped_certificate_shape'), \
                        patch.object(delegation, '_ledger', return_value=[ordinary]), \
                        patch.object(delegation, '_closure_guidance_inputs', return_value=guidance) as capture, \
                        patch.object(evidence, '_evidence_inventory_rows', return_value=[]), \
                        patch.object(changes, '_linked_live_certificate_inputs', side_effect=LaterValidationReached) as later, \
                        patch.object(delegation, '_resolve_closure_guidance_job') as resolve:
                    if allowed:
                        with self.assertRaises(LaterValidationReached):
                            evidence._linked_preparation_member_inputs(context, ref, task, basis, {})
                        later.assert_called_once_with(context, db, dict(reference=ref, pins=task['pins']), basis)
                    else:
                        self.assertIsNone(evidence._linked_preparation_member_inputs(context, ref, task, basis, {}))
                        later.assert_not_called()
                    capture.assert_called_once_with(context, db, [ordinary])
                    resolve.assert_not_called()

    def test_supplied_writer_keeps_original_semantic_dispatch(self):
        from runtime import changes, evidence
        context, writer = object(), object()
        supplied = (context, writer)
        job = dict(item=dict(reference=dict(authority={})))
        class OriginalWriterReached(Exception):
            pass
        def steps(*args, **kwargs):
            self.assertIs(kwargs['writer'], supplied)
            self.assertNotIn('serial_members', kwargs)
            yield job
        with patch.object(evidence, '_linked_preparation_steps', side_effect=steps), \
                patch.object(evidence, '_reference_context', return_value=context), \
                patch.object(evidence, '_preparation_database', return_value=nullcontext(writer)) as database, \
                patch.object(changes, '_stopped_certificate', side_effect=OriginalWriterReached) as resolve, \
                patch.object(evidence, '_observe_linked_preparation_member') as serial:
            with self.assertRaises(OriginalWriterReached):
                evidence._linked_preparation_facts({}, [], writer=supplied, read_roster=object())
            database.assert_called_once_with(context, supplied)
            resolve.assert_called_once()
            serial.assert_not_called()
