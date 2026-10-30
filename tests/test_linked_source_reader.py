"""Real foreign source admission after closing only the reader owned by _linked_source."""

from contextlib import contextmanager
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from runtime import evidence, state
from runtime.startup import StartupError
from tests import test_evidence as fixtures


class LinkedSourceReaderTests(unittest.TestCase):
    def test_real_foreign_admission_closes_owned_reader_and_revalidates_before_observation(self):
        case = fixtures.LinkedVerificationTests(methodName='test_linked_preparation_compacts_precede_d4_cut_without_closure_or_raw_retirement')
        case.setUp()
        self.addCleanup(case.doCleanups)
        consumer, _, source, contexts, references = case.preparation_fixture()
        content = evidence._linked_contract(consumer)
        member = next(member for member in content['members'] if member['task']['authority'] != consumer['authority'])
        reference = dict(authority=member['task']['authority'], reference=member['verification'])
        context = next(context for context in contexts if evidence._canonical_plain(context.authority_set[0]) == reference['authority'])
        database = evidence._context_database
        original = evidence._check_content_consumption
        active = []
        admitted = []

        @contextmanager
        def track(selected, **kwargs):
            with database(selected, **kwargs) as db:
                active.append(db)
                try:
                    yield db
                finally:
                    active.remove(db)

        def admission(actual_reference, metadata, actual_consumer):
            self.assertFalse(active, 'Owned source reader is still open at real admission')
            self.assertEqual(actual_reference, reference)
            self.assertEqual(actual_consumer, consumer)
            original(actual_reference, metadata, actual_consumer)
            self.assertFalse(active)
            admitted.append(True)

        authorities = evidence._canonical_plain(source.content['authorities'])
        with evidence._linked_stop_guards(consumer, authorities):
            expected_observed = {}
            expected = evidence._linked_source(reference, observed=expected_observed)
            key = evidence._raw(reference)
            expected_metadata = expected_observed[key][1]
            observed = {}
            with patch.object(evidence, '_context_database', side_effect=track), \
                    patch.object(evidence, '_check_content_consumption', side_effect=admission):
                self.assertEqual(evidence._linked_source(reference, consumer=consumer, require_admission=True, observed=observed), expected)
            self.assertTrue(admitted)
            self.assertEqual(observed, expected_observed)

            # Non-admission reads keep their original path, with owned or supplied readers.
            with patch.object(evidence, '_check_content_consumption', side_effect=AssertionError('Unexpected admission')):
                self.assertEqual(evidence._linked_source(reference), expected)
                with database(context) as db:
                    self.assertEqual(evidence._linked_source(reference, db=db), expected)
                    self.assertTrue(db.in_transaction)

            with database(context) as supplied:
                supplied_calls = []
                def supplied_admission(actual_reference, metadata, actual_consumer):
                    self.assertTrue(supplied.in_transaction)
                    original(actual_reference, metadata, actual_consumer)
                    supplied_calls.append(True)
                supplied_observed = {}
                with patch.object(evidence, '_check_content_consumption', side_effect=supplied_admission):
                    self.assertEqual(evidence._linked_source(reference, db=supplied, consumer=consumer,
                        require_admission=True, observed=supplied_observed), expected)
                self.assertTrue(supplied_calls)
                self.assertTrue(supplied.in_transaction)
                self.assertEqual(supplied_observed, expected_observed)

            path = context.directory / 'evidence' / reference['reference']['name']
            raw, mode = path.read_bytes(), path.stat().st_mode & 0o777
            with database(context) as db:
                metadata_raw = db.execute('select data from evidence_metadata where name=?', (path.name,)).fetchone()[0]
            for kind in ('metadata', 'body', 'inode', 'interpreter-error'):
                with self.subTest(kind=kind):
                    observed = {}
                    changed = []
                    backup = path.with_name(path.name + '.original')
                    def mutate(actual_reference, metadata, actual_consumer):
                        admission(actual_reference, metadata, actual_consumer)
                        if kind == 'metadata':
                            altered = deepcopy(expected_metadata)
                            altered['dependencies'].append(dict(kind='task', reference=content['selected']))
                            with database(context, write=True) as db:
                                db.execute('update evidence_metadata set data=? where name=?', (json.dumps(altered), path.name))
                        elif kind == 'body':
                            path.chmod(0o600)
                            path.write_bytes(b'{}')
                            path.chmod(mode)
                        elif kind == 'inode':
                            path.rename(backup)
                            path.write_bytes(raw)
                            path.chmod(mode)
                        else:
                            raise state.StateError('Original admission completed; fixture stops before observation')
                        changed.append(True)
                    try:
                        with patch.object(evidence, '_context_database', side_effect=track), \
                                patch.object(evidence, '_check_content_consumption', side_effect=mutate):
                            with self.assertRaises(StartupError):
                                evidence._linked_source(reference, consumer=consumer, require_admission=True, observed=observed)
                        self.assertEqual(observed, {})
                        if kind != 'interpreter-error':
                            self.assertTrue(changed)
                    finally:
                        if kind == 'metadata':
                            with database(context, write=True) as db:
                                db.execute('update evidence_metadata set data=? where name=?', (metadata_raw, path.name))
                        elif kind == 'body':
                            path.chmod(0o600)
                            path.write_bytes(raw)
                            path.chmod(mode)
                        elif kind == 'inode' and backup.exists():
                            path.unlink()
                            backup.rename(path)

            inconsistent = deepcopy(expected_observed)
            inconsistent[key][1]['bytes'] += 1
            unchanged = deepcopy(inconsistent)
            with patch.object(evidence, '_check_content_consumption', side_effect=admission):
                with self.assertRaisesRegex(StartupError, 'observations disagree'):
                    evidence._linked_source(reference, consumer=consumer, require_admission=True, observed=inconsistent)
            self.assertEqual(inconsistent, unchanged)
            self.assertFalse(case.preparation_receipts(contexts))
