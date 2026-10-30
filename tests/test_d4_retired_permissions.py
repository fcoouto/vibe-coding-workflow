"""Retained ownership is bookkeeping permission, never a new raw-task route."""
from contextlib import contextmanager
import json
import unittest
from unittest.mock import patch

from runtime import changes, evidence, state
from runtime.startup import StartupError
from tests import test_evidence


_METHOD = 'test_linked_no_verifier_native_history_survives_d4_retirement_and_guidance'


class _RetiredBoundary(Exception):
    pass


class _RollbackFaults(Exception):
    pass


class D4RetiredPermissionTests(unittest.TestCase):
    def retired_fixture(self):
        scenario = test_evidence.LinkedVerificationTests(methodName=_METHOD)
        scenario.setUp(); self.addCleanup(scenario.doCleanups)
        original = test_evidence._run_d4_fixture
        reached = {}

        def stop_before_retired_resume(fixture, request, operation):
            contexts = tuple(evidence._evidence_context(member.scope) for member in scenario.members)
            counts = []
            for context in contexts:
                with evidence._context_database(context) as db:
                    counts.append(db.execute('select count(*) from tasks').fetchone()[0])
            if operation == 'resume' and counts == [0, 0]:
                reached.update(fixture=fixture, request=request)
                raise _RetiredBoundary
            return original(fixture, request, operation)

        with patch.object(test_evidence, '_run_d4_fixture', side_effect=stop_before_retired_resume):
            with self.assertRaises(_RetiredBoundary):
                getattr(scenario, _METHOD)()
        self.assertTrue(reached, 'original lifecycle must pass both actual retirements')
        return scenario, reached['fixture'], reached['request']

    @contextmanager
    def successor(self, scenario, fixture, request):
        journal = changes._load_journal(fixture.directory)
        self.assertEqual(journal['manifest'], request['manifest'])
        self.assertEqual(journal['approval'], request['approval'])
        manifest = journal['manifest']; _, prior = changes._scoped_prior(journal['plan'])
        locations = changes._scoped_runtime_locations([prior, manifest['enrollment']['record']])
        owner = dict(schema_version=1, plan_dir=str(fixture.directory),
            transaction_id=journal['transaction_id'], manifest_digest=journal['manifest_digest'])
        with changes._scoped_source_guards(locations, owner, manifest) as (_, contexts):
            source = changes._observe_recovery_source(fixture.directory, journal, contexts, ())
            self.assertIs(source.issuer, changes._RECOVERY_ISSUER)
            self.assertEqual(source.content['tasks'], ())
            yield journal, contexts, source

    def test_retained_owner_permission_never_admits_raw_task_or_missing_support(self):
        scenario, fixture, request = self.retired_fixture()
        with self.successor(scenario, fixture, request) as (journal, contexts, source):
            facts = changes._d4_permission_facts(journal, source)
            retained = []
            for item in facts['sources']:
                context = next(c for c in contexts if evidence._canonical_plain(c.authority_set[0]) == item['reference']['authority'])
                with evidence._context_database(context) as db:
                    body = evidence._read(None, item['reference']['artifact'], context=context, db=db)
                    if body.get('kind') != 'linked-closure-preparation':
                        continue
                    metadata = item['metadata']; owner = metadata['owner']['task']
                    subject = evidence._source_subject(context, db, metadata)
                    marker = state._retired(db, 'task', {key: owner[key] for key in ('scope_id', 'client', 'session_id', 'task_id')})
                    self.assertFalse(subject['live']); self.assertFalse(marker['evidence_expired'])
                    self.assertEqual(marker['pins_digest'], evidence._digest(subject['pins']))
                    self.assertGreaterEqual(subject['closed_at'], metadata['created_at'])
                    permission = evidence._source_current_permission(context, dict(artifact=item['reference']['artifact'],
                        owner=metadata['owner'], created_at=metadata['created_at'], pins=subject['pins']), db=db)
                    self.assertEqual(permission['projection'], subject['identity'])
                self.assertIn({key: subject['identity'][key] for key in ('project_id', 'repository_id', 'checkout_id', 'client')}, facts['subjects'])
                retained.append((context, metadata, subject))
            self.assertEqual(len(retained), 2)
            self.assertEqual({str(row[0].database) for row in retained}, {str(c.database) for c in contexts})

            context, metadata, subject = retained[0]; owner = metadata['owner']['task']
            with self.assertRaisesRegex(StartupError, 'Named recovery task unavailable'):
                changes._observe_recovery_source(fixture.directory, journal, contexts, (owner,))
            member = next(member for member in scenario.members if member.scope.runtime.state_dir == context.directory)
            before = sorted(path.name for path in (context.directory / 'evidence').iterdir())
            with self.assertRaisesRegex(state.StateError, 'Retired task evidence is unavailable'):
                evidence._artifact(member.scope, dict(kind='fixture:new-publication-as-retired-task'),
                    owner=evidence._ArtifactOwner(member.scope.project_id, evidence._canonical_freeze(owner),
                        evidence._canonical_freeze(subject['pins'])))
            self.assertEqual(sorted(path.name for path in (context.directory / 'evidence').iterdir()), before)

            # Negative-only row faults run last and roll back; no later positive provenance claim.
            with self.assertRaises(_RollbackFaults):
                with evidence._context_database(context, write=True) as db:
                    marker_key = state._retired_identity('task', {key: owner[key] for key in ('scope_id', 'client', 'session_id', 'task_id')})
                    for fault in ('missing-marker', 'expired-marker', 'missing-closure'):
                        with self.subTest(fault=fault):
                            db.execute('savepoint missing_support')
                            if fault == 'missing-marker':
                                db.execute("delete from retired_identities where kind='task' and identity_digest=?", (marker_key,))
                            elif fault == 'expired-marker':
                                row = db.execute("select data from retired_identities where kind='task' and identity_digest=?", (marker_key,)).fetchone()
                                expired = json.loads(row[0]); expired.update(evidence_expired=True, outcome='unknown')
                                db.execute("update retired_identities set data=? where kind='task' and identity_digest=?", (json.dumps(expired), marker_key))
                            else:
                                for name, digest in db.execute("select name,digest from evidence_metadata where class='compact' and status='live'").fetchall():
                                    value = evidence._read(None, dict(name=name, digest=digest), context=context, db=db)
                                    if value.get('kind') == 'task-closure' and value['identity'] == owner:
                                        db.execute('delete from evidence_metadata where name=?', (name,))
                            with self.assertRaisesRegex(state.StateError, 'Source (retired owner|bookkeeping owner)'):
                                evidence._source_subject(context, db, metadata)
                            db.execute('rollback to missing_support'); db.execute('release missing_support')
                    raise _RollbackFaults

    def foreign_permission_loss(self, change, message):
        scenario, fixture, request = self.retired_fixture()
        with self.successor(scenario, fixture, request) as (journal, _, source):
            self.assertTrue(changes._d4_permission_facts(journal, source)['subjects'])
            path = scenario.members[1].scope.authority_path
            record = json.loads(path.read_text()); change(record)
            path.write_text(json.dumps(record))
            with self.assertRaisesRegex(StartupError, message):
                changes._d4_permission_facts(journal, source)
            self.assertEqual(json.loads(path.read_text()), record)

    def test_retired_foreign_owner_excluded_membership_still_blocks(self):
        self.foreign_permission_loss(lambda row: row['membership'].update(exclude=['.']),
            'Current D4 source subject enrollment changed')

    def test_retired_foreign_owner_changed_configuration_still_blocks(self):
        self.foreign_permission_loss(lambda row: row['repositories'][0]['checkouts'][0]['clients'][0]['configuration'].update(policy_digest='0' * 64),
            'Current D4 source subject enrollment changed')

    def test_retired_foreign_owner_suspension_still_blocks(self):
        self.foreign_permission_loss(lambda row: row['repositories'][0]['checkouts'][0]['clients'][0]['activation'].update(status='suspended'),
            'Current D4 source bookkeeping permission is suspended')
