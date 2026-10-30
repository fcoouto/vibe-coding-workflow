"""Real ordinary A/B writer vetoes; SQL ordering is same-process evidence only."""
import json
import os
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime import closure_witness, evidence, state
from tests.test_ordinary_closure_authorities import ordinary_retired_historical_consumer


def _owner_snapshot(context, reference):
    with evidence._context_database(context) as db:
        return dict(sql=tuple(db.iterdump()),
            task=state._task(db, *(reference[key] for key in ('scope_id', 'client', 'session_id', 'task_id'))),
            metadata=tuple(db.execute('select name,class,created_at,closed_at from evidence_metadata order by name')),
            markers=tuple(db.execute('select kind,identity_digest,data,assignment_id from retired_identities '
                'order by kind,identity_digest')))


def _files(context):
    return {path.name: path.read_bytes() for path in sorted((context.directory / 'evidence').iterdir())}


def _database_is(value, path):
    return value.split('?', 1)[0] in {str(path), path.as_uri(), 'file:' + str(path)}


class OrdinaryClosureRaceTests(unittest.TestCase):
    def _assert_reader_order(self, events, owner, peer, requested_pass):
        live = {}
        writers = set()
        begins = 0
        peer_opens = 0
        passes = []
        for event in events:
            kind, *details = event
            if kind == 'open':
                identity, database = details
                if _database_is(database, peer):
                    self.assertFalse(writers, 'Peer SQLite opened during B writer')
                    self.assertNotIn(2, passes, 'Peer SQLite reopened after the serial bracket')
                    peer_opens += 1
                live[identity] = database
                self.assertLessEqual(len(live), 1, 'Target SQL connection lifetimes were not serial')
            elif kind == 'begin':
                identity, statement = details
                if _database_is(live[identity], owner) and statement == 'BEGIN IMMEDIATE':
                    self.assertFalse(any(_database_is(database, peer) for database in live.values()),
                        'Peer SQLite reader remained open at B writer entry')
                    writers.add(identity)
                    begins += 1
            elif kind == 'close':
                identity, = details
                del live[identity]
                writers.discard(identity)
            elif kind == 'pass':
                number, = details
                passes.append(number)
                self.assertEqual(len(writers), 1 if number >= 3 else 0)
                if number >= 2:
                    self.assertFalse(any(_database_is(database, peer) for database in live.values()))
        self.assertEqual(begins, 1)
        self.assertGreater(peer_opens, 0, 'The real peer semantic readers were not traced')
        self.assertEqual(passes, list(range(1, requested_pass + 1)))
        self.assertEqual(live, {})

    def _race(self, operation, requested_pass):
        capture = {}
        mutation = {}
        original_connect = sqlite3.connect
        original_pass = closure_witness.PeerWitness.read_pass
        original_operation = getattr(evidence, operation)

        def target(*args, **kwargs):
            self.assertFalse(capture, 'Only the first actual target operation is intercepted')
            if operation == 'close_task':
                context = args[2].context
                reference = evidence._issued_closure(context, args[2])['task_ref']
            else:
                context, reference = args
            capture.update(context=context, reference=reference, before=_owner_snapshot(context, reference),
                files=_files(context), events=[])
            events = capture['events']
            connections = []

            class TracedConnection(sqlite3.Connection):
                def __init__(connection, *connection_args, **connection_kwargs):
                    super().__init__(*connection_args, **connection_kwargs)
                    connection.trace_identity = len(connections)
                    connections.append(connection)
                    events.append(('open', connection.trace_identity, str(connection_args[0])))

                def execute(connection, statement, *execute_args, **execute_kwargs):
                    result = super().execute(statement, *execute_args, **execute_kwargs)
                    normalized = statement.strip().upper()
                    if normalized.startswith('BEGIN'):
                        events.append(('begin', connection.trace_identity, normalized))
                    return result

                def close(connection):
                    result = super().close()
                    events.append(('close', connection.trace_identity))
                    return result

            def connect(*connection_args, **connection_kwargs):
                self.assertNotIn('factory', connection_kwargs)
                return original_connect(*connection_args, factory=TracedConnection, **connection_kwargs)

            def read_pass(witness, number):
                events.append(('pass', number))
                if 'peer' not in capture:
                    capture['peer'] = witness.path
                    capture['witness'] = witness
                    capture['peer_bytes'] = witness.path.read_bytes()
                self.assertIs(witness, capture['witness'])
                self.assertNotEqual(witness.path, context.database)
                if number == requested_pass:
                    self.assertFalse(mutation)
                    descriptor = os.open(witness.path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
                    mutation['descriptor'] = descriptor
                    retained = witness.files[witness.path.name]['descriptor']
                    actual, pinned = os.fstat(descriptor), os.fstat(retained)
                    self.assertEqual((actual.st_dev, actual.st_ino), (pinned.st_dev, pinned.st_ino))
                    original = os.pread(descriptor, actual.st_size, 0)
                    self.assertEqual(len(original), actual.st_size)
                    self.assertTrue(original)
                    self.assertEqual(original, capture['peer_bytes'], 'Peer changed before test injection')
                    mutation.update(path=witness.path, original=original, byte=bytes([original[0] ^ 1]),
                        files=_files(context), reached=number)
                    self.assertEqual(os.pwrite(descriptor, mutation['byte'], 0), 1)
                return original_pass(witness, number)

            with patch.object(sqlite3, 'connect', new=connect), \
                    patch.object(closure_witness.PeerWitness, 'read_pass', new=read_pass):
                return original_operation(*args, **kwargs)

        try:
            with patch.object(evidence, operation, new=target):
                with self.assertRaisesRegex(state.StateError,
                        'Ordinary closure (peer file identity changed|live descriptor changed|peer bytes changed)'):
                    ordinary_retired_historical_consumer(self)

            self.assertEqual(mutation.get('reached'), requested_pass)
            context, reference = capture['context'], capture['reference']
            after = _owner_snapshot(context, reference)
            self.assertEqual(after['sql'], capture['before']['sql'], 'B SQL did not completely roll back')
            self.assertEqual(after['task'], capture['before']['task'], 'Raw B task changed')
            self.assertEqual(after['metadata'], capture['before']['metadata'], 'B metadata or ages changed')
            self.assertEqual(after['markers'], capture['before']['markers'], 'B task/turn/receipt markers changed')
            self.assertEqual(mutation['path'].read_bytes(), mutation['byte'] + mutation['original'][1:],
                'Peer mutation must be the test byte write alone')
            self.assertFalse(os.path.lexists(Path(str(capture['peer']) + '-journal')))
            self._assert_reader_order(capture['events'], context.database, capture['peer'], requested_pass)
            self.assertEqual(capture['witness'].files, {})
            self.assertIsNone(capture['witness'].stack)
            self.assertEqual(capture['witness'].passes, requested_pass - 1)

            files_after = _files(context)
            self.assertEqual(files_after, mutation['files'], 'Veto changed files after the injection point')
            for name, raw in capture['files'].items():
                self.assertEqual(files_after[name], raw)
            if operation == '_retire_closed_task':
                self.assertEqual(files_after, capture['files'])
                task = capture['before']['task']
                compact = task['lifecycle']['compact']
                ages = next(row for row in after['metadata'] if row[0] == compact['name'])
                original_ages = next(row for row in capture['before']['metadata'] if row[0] == compact['name'])
                self.assertEqual(ages, original_ages)
                self.assertEqual(ages[1:3], ('compact', task['lifecycle']['created_at']))
                self.assertEqual(after['task']['lifecycle']['safe_closed_at'], task['lifecycle']['safe_closed_at'])
            elif requested_pass == 3:
                self.assertEqual(files_after, capture['files'], 'Entry failure published a compact')
                self.assertIsNone(after['task']['lifecycle']['safe_closed_at'])
            else:
                orphan_names = set(files_after) - set(capture['files'])
                self.assertEqual(len(orphan_names), 1)
                orphan_name, = orphan_names
                orphan = json.loads(files_after[orphan_name])
                self.assertEqual(orphan['kind'], 'task-closure')
                self.assertEqual(orphan['identity'], reference)
                self.assertNotIn(orphan_name, {row[0] for row in after['metadata']})
                self.assertIsNone(after['task']['lifecycle']['safe_closed_at'])
                # Restore only the injected A byte before asking the normal API to protect B's orphan.
                self.assertEqual(os.pwrite(mutation['descriptor'], mutation['original'][:1], 0), 1)
                self.assertEqual(mutation['path'].read_bytes(), mutation['original'])
                with self.assertRaisesRegex(state.StateError, 'Unaccounted evidence content remains protected'):
                    evidence._observe_closure((context,), reference)
                self.assertEqual(_owner_snapshot(context, reference), after)
                self.assertEqual(_files(context), files_after)
        finally:
            descriptor = mutation.get('descriptor')
            if descriptor is not None:
                try:
                    if 'original' in mutation:
                        self.assertEqual(os.pwrite(descriptor, mutation['original'][:1], 0), 1)
                finally:
                    os.close(descriptor)

    def test_close_entry_peer_mutation_rolls_back_without_compact_publication(self):
        self._race('close_task', 3)

    def test_close_commit_peer_mutation_rolls_back_and_protects_compact_orphan(self):
        self._race('close_task', 4)

    def test_retire_entry_peer_mutation_keeps_raw_owner_compact_and_ages(self):
        self._race('_retire_closed_task', 3)

    def test_retire_commit_peer_mutation_rolls_back_markers_and_keeps_ages(self):
        self._race('_retire_closed_task', 4)


if __name__ == '__main__':
    unittest.main()
