"""Positive ordinary closure coverage for an issued historical consumer."""
import json
import os
import sqlite3
import unittest
from pathlib import Path

from runtime import evidence, state
from tests import test_recovery_release_contexts


def _cold_peer_journal(testcase, peer):
    connection = sqlite3.connect(peer.database, timeout=0.1)
    try:
        testcase.assertEqual(connection.execute('pragma journal_mode=PERSIST').fetchone()[0], 'persist')
        connection.execute('begin immediate')
        row = connection.execute('select scope_id,generation from checkouts limit 1').fetchone()
        testcase.assertIsNotNone(row)
        connection.execute('update checkouts set generation=? where scope_id=?', (row[1] + 1, row[0]))
        connection.execute('update checkouts set generation=? where scope_id=?', (row[1], row[0]))
        connection.commit()
    finally:
        connection.close()

    journal = Path(str(peer.database) + '-journal')
    with evidence._context_database(peer) as db:
        testcase.assertEqual(db.execute('pragma journal_mode').fetchone()[0], 'delete')
    testcase.assertTrue(os.path.lexists(journal))
    state._private(journal)
    return journal


def ordinary_retired_historical_consumer(testcase, *, cold_journal=False):
    (fixture, request, contexts, authorities, identity, scope, task_context,
     stopped_task, proof) = test_recovery_release_contexts.RecoveryReleaseContextTests.fixture(testcase)
    changes = fixture.changes
    observation = changes._observe_recovery_release(authorities, identity)
    captured = evidence._canonical_plain(observation.content)
    release = evidence._canonical_plain(changes._register_recovery_release(observation))
    testcase.assertTrue(release['complete'], release)
    task_ref = next(row['reference'] for row in captured['stopped']
        if row['reference']['task_id'] == 'historical-consumer')

    source_certificate = None
    for context in contexts:
        _, sources = changes._recovery_sources(context)
        _, body = next((ref, body) for ref, body in sources if body['identity'] == identity)
        if evidence._canonical_plain(context.authority_set[0]) == task_ref['authority']:
            source_certificate = evidence._canonical_plain(body)
    testcase.assertIsNotNone(source_certificate)
    stopped_certificate = next(row for row in source_certificate['stopped'] if row['reference'] == task_ref)

    inspection = evidence._canonical_plain(changes.inspect_lifecycle_recovery(authorities, (task_ref,)))
    testcase.assertTrue(inspection['complete'], inspection)
    testcase.assertEqual(inspection['blockers'], [], inspection)
    testcase.assertFalse(any(row.get('need') == 'raw' and row.get('reference') == task_ref
        for row in inspection['requirements']))

    owner = next(context for context in contexts
        if evidence._canonical_plain(context.authority_set[0]) == task_ref['authority'])
    peer = next(context for context in contexts if context is not owner)
    journal_path = Path(str(peer.database) + '-journal')
    if cold_journal:
        _cold_peer_journal(testcase, peer)
    else:
        testcase.assertFalse(os.path.lexists(journal_path))
    with evidence._context_database(peer) as db:
        peer_rows = tuple(db.iterdump())
    peer_evidence = {path.name: path.read_bytes() for path in sorted((peer.directory / 'evidence').iterdir())}

    observations = evidence._observe_closure((owner,), task_ref)
    owner_identity = {key: task_ref[key] for key in ('scope_id', 'client', 'session_id', 'task_id')}
    close_request = dict(client=stopped_task['client'], session_id=stopped_task['session_id'],
        task_id=stopped_task['task_id'], scope_ref=stopped_task['scope_ref'],
        expected_revision=stopped_task['revision'], expected_pins=stopped_task['pins'])
    closed = evidence.close_task(scope, close_request, observations)
    compact = closed['task']['lifecycle']['compact']
    testcase.assertEqual(closed['task']['pins'], stopped_task['pins'])
    testcase.assertEqual(closed['task']['lifecycle']['created_at'], stopped_task['lifecycle']['created_at'])
    first_safe_closed_at = closed['task']['lifecycle']['safe_closed_at']
    testcase.assertIsNotNone(first_safe_closed_at)
    testcase.assertNotIn('linked', closed['task'].get('writer_stop', {}))

    with evidence._context_database(owner) as db:
        testcase.assertIsNotNone(state._task(db, task_ref['scope_id'], task_ref['client'],
            task_ref['session_id'], task_ref['task_id']), 'Raw B owner disappeared before normal retirement')
        testcase.assertEqual(state._metadata(db, compact['name'])['class'], 'compact')
        testcase.assertEqual(evidence._read(None, compact, context=owner, db=db)['stopped'], stopped_certificate)
        compact_metadata = state._metadata(db, compact['name'])
        compact_created_at = compact_metadata['created_at']
        compact_closed_at = compact_metadata['closed_at']
        testcase.assertEqual(compact_created_at, stopped_task['lifecycle']['created_at'])
        _, proof_raw = evidence._managed_artifact(None, stopped_task['retirement']['proof'], context=owner, db=db)
        testcase.assertEqual(json.loads(proof_raw), proof)

    repeated_request = dict(client=closed['task']['client'], session_id=closed['task']['session_id'],
        task_id=closed['task']['task_id'], scope_ref=closed['task']['scope_ref'],
        expected_revision=closed['task']['revision'], expected_pins=closed['task']['pins'])
    repeated = evidence.close_task(scope, repeated_request, evidence._observe_closure((owner,), task_ref))
    testcase.assertEqual(repeated['task']['lifecycle']['safe_closed_at'], first_safe_closed_at)
    testcase.assertEqual(repeated['task']['lifecycle']['compact'], compact)
    with evidence._context_database(owner) as db:
        compact_metadata = state._metadata(db, compact['name'])
        testcase.assertEqual(compact_metadata['created_at'], compact_created_at)
        testcase.assertEqual(compact_metadata['closed_at'], compact_closed_at)
        dependencies = state.inspect_dependencies(db, task_ref)
        task_prefix = tuple(owner_identity[key] for key in ('scope_id', 'client', 'session_id'))
        turns = [row for row in dependencies['turns']
            if tuple(row[:3]) == task_prefix and row[4] == owner_identity['task_id']]
        receipts = [row for row in dependencies['receipts']
            if any(tuple(row[:4]) == tuple(turn[:4]) for turn in turns)]

    retired = evidence._retire_closed_task(owner, task_ref)
    testcase.assertTrue(retired['retired'], retired)
    testcase.assertEqual(retired['identity'], owner_identity)
    testcase.assertEqual(retired['outcome'], stopped_task['state'])
    with evidence._context_database(owner) as db:
        raw = db.execute('select 1 from tasks where scope_id=? and client=? and session_id=? and task_id=?',
            tuple(owner_identity.values())).fetchone()
        testcase.assertIsNone(raw, 'Raw B owner survived normal retirement')
        marker = state._retired(db, 'task', owner_identity)
        testcase.assertIsNotNone(marker)
        testcase.assertEqual(marker['identity'], owner_identity)
        testcase.assertEqual(marker['pins_digest'], state._digest(stopped_task['pins']))
        testcase.assertEqual(marker['created_at'], stopped_task['lifecycle']['created_at'])
        testcase.assertEqual(marker['outcome'], stopped_task['state'])
        testcase.assertFalse(marker['evidence_expired'])
        testcase.assertGreaterEqual(marker['retired_at'], first_safe_closed_at)
        compact_metadata = state._metadata(db, compact['name'])
        testcase.assertEqual(compact_metadata['class'], 'compact')
        testcase.assertEqual(compact_metadata['created_at'], compact_created_at)
        testcase.assertEqual(compact_metadata['closed_at'], first_safe_closed_at)
        testcase.assertEqual(evidence._read(None, compact, context=owner, db=db)['stopped'], stopped_certificate)
        _, proof_raw = evidence._managed_artifact(None, stopped_task['retirement']['proof'], context=owner, db=db)
        testcase.assertEqual(json.loads(proof_raw), proof)
        for row in turns:
            key = dict(zip(('scope_id', 'client', 'session_id', 'turn_id'), row[:4]))
            turn_marker = state._retired(db, 'turn', key)
            testcase.assertEqual(turn_marker['identity'], key)
            testcase.assertEqual(turn_marker['pins_digest'], state._digest(stopped_task['pins']))
            testcase.assertIsNone(turn_marker['request_digest'])
            testcase.assertEqual(turn_marker['created_at'], stopped_task['lifecycle']['created_at'])
            testcase.assertEqual(turn_marker['outcome'], stopped_task['state'])
            testcase.assertGreaterEqual(turn_marker['retired_at'], first_safe_closed_at)
            testcase.assertFalse(turn_marker['evidence_expired'])
            testcase.assertIsNone(db.execute('select 1 from turns where scope_id=? and client=? and session_id=? and turn_id=?',
                row[:4]).fetchone())
        for row in receipts:
            key = dict(zip(('scope_id', 'client', 'session_id', 'turn_id', 'tool_call_id', 'kind'), row[:6]))
            receipt_marker = state._retired(db, 'receipt', key)
            testcase.assertEqual(receipt_marker['identity'], key)
            testcase.assertEqual(receipt_marker['pins_digest'], state._digest(stopped_task['pins']))
            testcase.assertEqual(receipt_marker['request_digest'], state._digest(row[6]))
            testcase.assertEqual(receipt_marker['created_at'], stopped_task['lifecycle']['created_at'])
            testcase.assertEqual(receipt_marker['outcome'], stopped_task['state'])
            testcase.assertGreaterEqual(receipt_marker['retired_at'], first_safe_closed_at)
            testcase.assertFalse(receipt_marker['evidence_expired'])
            testcase.assertIsNone(db.execute('select 1 from receipts where scope_id=? and client=? and session_id=? and turn_id=? and tool_call_id=? and kind=?',
                row[:6]).fetchone())
    with evidence._context_database(peer) as db:
        testcase.assertEqual(tuple(db.iterdump()), peer_rows)
    testcase.assertEqual({path.name: path.read_bytes() for path in sorted((peer.directory / 'evidence').iterdir())},
        peer_evidence)
    return dict(fixture=fixture, request=request, scope=scope, task_context=task_context,
        contexts=contexts, authorities=authorities, source_identity=identity, reference=task_ref,
        closure_request=close_request, repeated_request=repeated_request,
        stopped_task=stopped_task, proof=proof, stopped_certificate=stopped_certificate,
        compact=compact, source_certificate=source_certificate, turns=turns, receipts=receipts,
        cold_journal=journal_path if cold_journal else None, closed=closed, repeated=repeated, retired=retired)


class OrdinaryClosureAuthorityTests(unittest.TestCase):
    def test_ordinary_historical_consumer_closes_and_retires_from_complete_authorities(self):
        result = ordinary_retired_historical_consumer(self)
        self.assertIsNone(result['cold_journal'])
        self.assertTrue(any(evidence._canonical_plain(context.authority_set[0]) == result['reference']['authority']
            for context in result['contexts']))
        self.assertTrue(result['compact'])

    def test_ordinary_historical_consumer_closes_and_retires_with_cold_peer_journal(self):
        result = ordinary_retired_historical_consumer(self, cold_journal=True)
        self.assertTrue(result['cold_journal'])
        self.assertTrue(result['compact'])
