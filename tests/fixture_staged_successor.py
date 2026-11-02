"""Synthetic retained D4 successors; never evidence of actual native execution."""

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from runtime import changes, setup_observation as setup, startup, state


def publish_successor(owner, fixture, journal, *, assessment=None, qualification_scope=None):
    """Publish a new retained source and return its default-reader AcceptedScope.

    Coverage stays unchanged unless the caller supplies an explicit assessment;
    the production collector checks its original observed evidence and coverage.
    """
    original_file = fixture.directory/'transaction.json'
    original_bytes = original_file.read_bytes()
    original_journal = copy.deepcopy(journal)
    record = journal['manifest']['enrollment']['record']
    key = next(iter(changes._scoped_entries(record)))
    predecessor = copy.deepcopy(changes._scoped_entries(record)[key][2]['activation']['qualification_binding']['receipt'])
    owner.assertIn('#setup:', predecessor['reference'])
    original = journal['setup_receipts'][predecessor['reference'].split('#setup:', 1)[1]]
    identity = original['identity']

    private = tempfile.TemporaryDirectory(prefix='staged-successor-')
    owner.addCleanup(private.cleanup)
    directory = Path(private.name).resolve()
    directory.chmod(0o700)
    changes._load_journal(directory)
    transaction = directory.name
    observed = setup.collect_retained_setup(predecessor, identity, transaction,
        copy.deepcopy(original['assessment'] if assessment is None else assessment))
    successor = copy.deepcopy(journal)
    successor['transaction_id'] = successor['manifest']['transaction_id'] = transaction
    # Original command claims stay in their original journal, reached by predecessor.
    successor.update(receipts={}, directories={}, observations=[], setup_receipts={})
    successor.pop('birth', None)
    if qualification_scope is not None:
        successor.pop('qualification_scope', None)
    record = successor['manifest']['enrollment']['record']
    binding = setup.receipt_binding(observed, directory)
    changes._scoped_entries(record)[key][2]['activation'].update(
        transaction_id=transaction, accepted_scope_digest=binding['accepted_scope_digest'],
        qualification_binding=binding, evidence=[binding['receipt']])
    successor['manifest_digest'] = changes.d3._digest(successor['manifest'])
    successor['approval']['manifest_digest'] = successor['manifest_digest']
    raw = json.dumps(record, sort_keys=True, ensure_ascii=True).encode()+b'\n'
    digest = hashlib.sha256(raw).hexdigest()
    enrollment = successor['enrollment']
    enrollment['temporary'] = '.d4-'+transaction+'-enrollment'
    final = copy.deepcopy(next(row for row in enrollment['postimages'] if row['phase'] == 'final'))
    final.update(raw_sha256=digest, revision=record['revision'], temporary='.d4-'+transaction+'-final')
    final['after']['sha256'] = digest
    final['target']['fingerprint']['sha256'] = digest
    enrollment['postimages'] = [final]
    setup.persist_setup(directory, successor, [observed], qualification_scope=qualification_scope)
    changes._scoped_journal_shape(successor)
    authority = Path(record['project_root'])/startup.PROJECT_FILE
    authority.write_bytes(raw)
    with patch.dict(os.environ, HOME=str(owner.home.parent), CODEX_HOME=str(owner.home)):
        acquired = startup.acquire_project_entry(SimpleNamespace(client='codex', cwd=fixture.repo), state.PACKAGE)
    owner.assertEqual(acquired.resolution.status, 'active', acquired.resolution)
    scope = acquired.resolution.scope
    owner.assertIsInstance(scope, startup.AcceptedScope)
    owner.assertEqual(startup._canonical_plain(scope.accepted_identity), identity)
    owner.assertEqual(startup._canonical_plain(scope.qualification['reference']), binding['receipt'])
    owner.assertEqual(original_file.read_bytes(), original_bytes)
    owner.assertEqual(journal, original_journal)
    return scope
