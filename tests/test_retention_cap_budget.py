"""Resource fences over real private managed sources; no payload-release qualification."""

from contextlib import closing, contextmanager
from copy import deepcopy
import sqlite3
import stat
import time
import unittest
from unittest.mock import patch


class RetentionCapBudgetTests(unittest.TestCase):
    def test_nonlive_census_preserves_replacement_and_rejects_foreign_managed_path(self):
        from runtime import evidence, review_storage as storage, state
        from tests.test_review_storage import ReviewStorageTests
        fixture = ReviewStorageTests(methodName='runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.prepare()
        with storage._machine_guard() as (path, descriptor, parents):
            config = storage._configuration(path, descriptor)
            context = storage._ready_context(config, parents)
        reference = config['provenance']
        with evidence._context_database(context) as db:
            metadata = state._metadata(db, reference['name'])
        pending = dict(metadata, status='delete_pending')
        with evidence._context_database(context, write=True) as db:
            db.execute('update evidence_metadata set status=?,data=? where name=?',
                       ('delete_pending', evidence._raw(pending).decode(), reference['name']))
        original = context.directory / 'evidence' / reference['name']
        saved = fixture.private / 'original-provenance.json'
        original.rename(saved)
        original.mkdir(mode=0o700)
        budget = storage._budget()
        token = evidence._CAP_INPUT_BUDGET.set(budget)
        try:
            result = evidence._cap_input_inventory(context, budget, 'unrelated-project')
        finally:
            evidence._CAP_INPUT_BUDGET.reset(token)
        self.assertEqual(len(result['entries']), 1)
        entry = result['entries'][0]
        self.assertEqual(entry['reference'], reference)
        self.assertEqual(entry['metadata'], pending)
        self.assertTrue(stat.S_ISDIR(entry['stat'][2]))
        self.assertTrue(any('replacement' in reason for reason in entry['protected']))
        self.assertEqual(result['physical_bytes'], 0)
        outside = fixture.base / 'outside'
        outside.mkdir(mode=0o700)
        foreign = outside / reference['name']
        foreign.write_bytes(b'foreign file must remain unobserved')
        escaped = deepcopy(pending)
        escaped['managed'].update(path=str(foreign), parents=storage._parents(foreign))
        with evidence._context_database(context, write=True) as db:
            db.execute('update evidence_metadata set data=? where name=?',
                       (evidence._raw(escaped).decode(), reference['name']))
        budget = storage._budget()
        token = evidence._CAP_INPUT_BUDGET.set(budget)
        try:
            with self.assertRaisesRegex(state.StartupError, 'outside its original physical authority'):
                evidence._cap_input_inventory(context, budget, 'unrelated-project')
        finally:
            evidence._CAP_INPUT_BUDGET.reset(token)

    def test_real_managed_reads_and_unrelated_owner_use_exact_shared_charges(self):
        from runtime import evidence, onboarding, review_storage as storage, state
        from tests.test_review_storage import ReviewStorageTests
        fixture = ReviewStorageTests(methodName='runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.prepare()
        resolved = fixture.resolve(fixture.repo)
        self.assertTrue(resolved['ok'], resolved)
        before = ReviewStorageTests.tree_snapshot(fixture.private)
        limit = 8 * 1024 * 1024
        self.assertIsNone(evidence._CAP_INPUT_BUDGET.get())
        with storage._machine_guard() as (path, descriptor, parents):
            config = storage._configuration(path, descriptor)
            context = storage._ready_context(config, parents)
            with evidence._context_database(context) as db:
                owners = storage._owners(config, context, db)
                self.assertEqual(len(owners), 1)
                self.assertEqual(owners[0]['reference'], resolved['reference'])
                reference = owners[0]['reference']
                metadata = state._metadata(db, reference['name'])
                original_rows = evidence._evidence_inventory_rows(db)
                raw = evidence._managed_content(context, reference, metadata)

                budget = storage._budget()
                token = evidence._CAP_INPUT_BUDGET.set(budget)
                try:
                    self.assertEqual(evidence._managed_content(context, reference, metadata), raw)
                    self.assertEqual(budget['bytes'], len(raw))
                    self.assertEqual(budget['paths'], len((context.directory / 'evidence' / reference['name']).parts)
                                     + len(metadata['managed']['parents']))
                finally:
                    evidence._CAP_INPUT_BUDGET.reset(token)

                budget = storage._budget()
                returned = []
                original_content = evidence._managed_content
                def content(*args, **kwargs):
                    value = original_content(*args, **kwargs)
                    returned.append(len(value))
                    return value
                token = evidence._CAP_INPUT_BUDGET.set(budget)
                try:
                    with patch.object(evidence, '_managed_content', side_effect=content):
                        self.assertEqual(storage._owners(config, context, db, budget=budget), owners)
                    self.assertEqual(budget['bytes'], sum(returned), 'Temporary owner payload was charged twice')
                    self.assertGreater(len(returned), 1, 'Provenance must also pass the managed fence')
                finally:
                    evidence._CAP_INPUT_BUDGET.reset(token)
                unbound = storage._budget()
                self.assertEqual(storage._owners(config, context, db, budget=unbound), owners)
                self.assertEqual(unbound['bytes'], sum(owner['bytes'] for owner in owners),
                                 'Unbound temporary-owner accounting changed')
                active_budget = storage._budget()
                other_budget = dict(active_budget)
                self.assertEqual(active_budget, other_budget)
                returned.clear()
                token = evidence._CAP_INPUT_BUDGET.set(active_budget)
                try:
                    with patch.object(evidence, '_managed_content', side_effect=content):
                        self.assertEqual(storage._owners(config, context, db, budget=other_budget), owners)
                    self.assertEqual(active_budget['bytes'], sum(returned))
                    self.assertEqual(other_budget['bytes'], sum(owner['bytes'] for owner in owners),
                                     'Distinct equal counters suppressed the original manual charge')
                finally:
                    evidence._CAP_INPUT_BUDGET.reset(token)

                rows = db.execute('select name,digest,owner_key,class,created_at,closed_at,status,bytes,data '
                                  'from evidence_metadata order by name limit 4097').fetchall()
                material = sum(sum(len(str(value).encode()) for value in row if value is not None) for row in rows)
                budget = storage._budget()
                token = evidence._CAP_INPUT_BUDGET.set(budget)
                try:
                    self.assertEqual(evidence._evidence_inventory_rows(db), original_rows)
                    self.assertEqual(budget['bytes'], material)
                    self.assertEqual(budget['paths'], len(rows))
                finally:
                    evidence._CAP_INPUT_BUDGET.reset(token)

                original_open = onboarding._open_path
                for failure in ('allowance', 'deadline', 'late-deadline', 'partial-read'):
                    budget = storage._budget()
                    if failure == 'allowance':
                        budget['bytes'] = limit - len(raw)
                    elif failure == 'deadline':
                        budget['deadline'] = time.monotonic() - 1
                    original_fdopen = evidence.os.fdopen
                    reads = []
                    def open_path(*args, **kwargs):
                        descriptor = original_open(*args, **kwargs)
                        if failure == 'late-deadline':
                            budget['deadline'] = time.monotonic() - 1
                        return descriptor
                    @contextmanager
                    def partial(descriptor, mode):
                        with original_fdopen(descriptor, mode) as stream:
                            class Interrupted:
                                fileno = stream.fileno
                                def read(inner, amount):
                                    reads.append(amount)
                                    if failure == 'partial-read':
                                        stream.read(1)
                                        raise OSError('Actual partial managed read interrupted')
                                    return stream.read(amount)
                            yield Interrupted()
                    token = evidence._CAP_INPUT_BUDGET.set(budget)
                    try:
                        with self.subTest(failure=failure), \
                                patch.object(onboarding, '_open_path', side_effect=open_path) as opened, \
                                patch.object(evidence.os, 'fdopen', side_effect=partial):
                            with self.assertRaises((state.StartupError, OSError)):
                                evidence._managed_content(context, reference, metadata)
                            if failure in ('allowance', 'deadline'):
                                opened.assert_not_called()
                            if failure == 'late-deadline':
                                self.assertFalse(reads, 'Managed bytes were read after the shared deadline')
                            self.assertGreaterEqual(budget['bytes'], limit, 'Unknown remaining allowance was reusable')
                    finally:
                        evidence._CAP_INPUT_BUDGET.reset(token)
                    self.assertIsNone(evidence._CAP_INPUT_BUDGET.get())
                    self.assertEqual(evidence._managed_content(context, reference, metadata), raw)
        self.assertEqual(ReviewStorageTests.tree_snapshot(fixture.private), before)

    def test_metadata_budget_and_4097_sentinel_reject_before_full_row_fetch(self):
        from runtime import evidence, review_storage as storage, state
        full_query = 'select name,digest,owner_key,class,created_at,closed_at,status,bytes,data from evidence_metadata'
        for variant in ('material', 'count', 'deadline'):
            with self.subTest(variant=variant), closing(sqlite3.connect(':memory:')) as db:
                db.execute('create table evidence_metadata(name,digest,owner_key,class,created_at,closed_at,status,bytes,data)')
                row = ('name', 'digest', 'owner', 'detail', 1, None, 'live', 2, '{}')
                db.executemany('insert into evidence_metadata values(?,?,?,?,?,?,?,?,?)',
                               [row] * (4097 if variant == 'count' else 1))
                queries = []
                db.set_trace_callback(queries.append)
                budget = storage._budget()
                if variant == 'material':
                    budget['bytes'] = 8 * 1024 * 1024 - 4
                elif variant == 'deadline':
                    budget['deadline'] = time.monotonic() - 1
                token = evidence._CAP_INPUT_BUDGET.set(budget)
                try:
                    with self.assertRaises(state.StartupError):
                        evidence._evidence_inventory_rows(db)
                    self.assertFalse(any(query.lower().startswith(full_query) for query in queries),
                                     'Full metadata rows were fetched before their bound')
                    self.assertGreaterEqual(budget['bytes'], 8 * 1024 * 1024)
                finally:
                    evidence._CAP_INPUT_BUDGET.reset(token)

    def test_null_name_metadata_exhausts_allowance_before_full_row_fetch(self):
        from runtime import evidence, review_storage as storage, state
        full_query = 'select name,digest,owner_key,class,created_at,closed_at,status,bytes,data from evidence_metadata'
        with closing(sqlite3.connect(':memory:')) as db:
            schema = state.CANONICAL_TABLE_SQL['evidence_metadata']
            db.execute(schema)
            self.assertEqual(db.execute("select sql from sqlite_master where name='evidence_metadata'").fetchone()[0], schema)
            row = (None, 'digest', 'owner', 'detail', 1, None, 'live', 2,
                   evidence._raw(dict(padding='x' * 4096)).decode())
            db.execute('insert into evidence_metadata values(?,?,?,?,?,?,?,?,?)', row)
            before = db.execute('select rowid,* from evidence_metadata').fetchall()
            self.assertIsNone(before[0][1], 'Accepted SQLite schema did not retain the NULL name')
            queries = []
            db.set_trace_callback(queries.append)
            budget = storage._budget()
            budget['bytes'] = 8 * 1024 * 1024 - 128
            token = evidence._CAP_INPUT_BUDGET.set(budget)
            try:
                with self.assertRaises(state.StartupError):
                    evidence._evidence_inventory_rows(db)
                self.assertFalse(any(query.lower().startswith(full_query) for query in queries),
                                 'NULL-name metadata reached full-row fetch before material admission')
                self.assertGreaterEqual(budget['bytes'], 8 * 1024 * 1024)
            finally:
                evidence._CAP_INPUT_BUDGET.reset(token)
                db.set_trace_callback(None)
            self.assertEqual(db.execute('select rowid,* from evidence_metadata').fetchall(), before)

