"""Admission bounds apply to current ownership and the requesting task's replay history."""
import json
from contextlib import closing
import sqlite3
import unittest
from unittest.mock import patch

from runtime import delegation, state


class CurrentLedgerTests(unittest.TestCase):
    def test_unrelated_settled_history_is_excluded_but_live_owners_and_own_replays_remain(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('create table assignments(id,scope_id,client,session_id,task_id,dispatch_id,data)')
            for identity, session, status in (('old', 'other', 'settled'), ('replay', 'mine', 'settled'), ('live', 'other', 'uncertain')):
                db.execute('insert into assignments values(?,?,?,?,?,?,?)',
                    (identity, 'scope', 'codex', session, 'task', identity, json.dumps(dict(status=status))))
            def record(scope, row, **kwargs):
                return dict(id=row[0], owner=dict(zip(('scope_id', 'client', 'session_id', 'task_id', 'dispatch_id'), row[1:6])),
                    body=dict(pins=dict(schema_version=2)), data=dict(candidate=None))
            with patch.object(delegation, 'MAX_ASSIGNMENTS', 2), patch.object(delegation, '_record', side_effect=record), \
                    patch.object(state, '_scope_id', return_value='scope'), patch.object(state, '_retired', return_value=None), \
                    patch.object(state, '_retired_assignment', return_value=None), \
                    patch.object(state, '_task', return_value=dict(pins=dict(schema_version=2))):
                selected = delegation._ledger(object(), db, task=dict(client='codex', session_id='mine', task_id='task'))
                self.assertEqual({item['id'] for item in selected}, {'replay', 'live'})
                with self.assertRaisesRegex(state.StateError, 'history.*bound'):
                    delegation._ledger(object(), db)
