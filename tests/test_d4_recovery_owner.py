"""Owner-boundary rejection through actual D4 publication attempts."""

from dataclasses import replace
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch

from runtime import evidence, state
from tests import test_changes


class D4RecoveryOwnerTests(unittest.TestCase):
    def test_actual_recovery_owner_forgery_is_rejected_before_registration(self):
        mutations = ('age', 'content', 'dependencies', 'previous')
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                fixture = test_changes.ScopedChangesTests(methodName='runTest')
                fixture.setUp()
                self.addCleanup(fixture.doCleanups)
                changes = fixture.changes
                request, contexts = fixture.d4_bookkeeping_request()
                self.assertEqual(len(contexts), 1)
                context = contexts[0]
                with evidence._context_database(context) as db:
                    before_baseline = evidence._canonical_plain(state._source_baseline(None, db, context=context))
                before_effects = {action['id']: changes._fingerprint(Path(action['owner']['root']), action['effects'][0]['path'])
                    for action in request['manifest']['actions']}
                intercepted = []
                original = evidence._artifact_registered

                def forge_actual_owner(scope, value, selected, owner, db):
                    if not isinstance(owner, evidence._RecoveryOwner):
                        return original(scope, value, selected, owner, db)
                    intercepted.append(owner)
                    baseline = state._source_baseline(None, db, context=selected)
                    baseline_ref = evidence._canonical_plain(baseline['reference'])
                    authority = evidence._canonical_plain(selected.authority_set[0])
                    if mutation == 'age':
                        owner = replace(owner, created_at=owner.created_at + 1)
                    elif mutation == 'content':
                        content = evidence._canonical_plain(owner.content)
                        content['journal']['observed_at'] += 1
                        owner = replace(owner, content=content)
                    elif mutation == 'dependencies':
                        owner = replace(owner, dependencies=(dict(kind='artifact',
                            reference=dict(authority=authority, artifact=baseline_ref)),))
                    else:
                        content = evidence._canonical_plain(owner.content)
                        content['previous'] = baseline_ref
                        owner = replace(owner, content=content)
                    return original(scope, value, selected, owner, db)

                class Host:
                    def acquire_d4_bookkeeping(self, facts, issue):
                        return issue(facts)

                with changes._bootstrap_d4_host(Host(), issuer=changes._D4_HOST_BOOTSTRAP_ISSUER) as host:
                    with patch.object(evidence, '_artifact_registered', side_effect=forge_actual_owner):
                        result = changes._run_scoped(fixture.directory, request, 'apply', host=host)
                self.assertEqual(len(intercepted), 1)
                self.assertEqual(result['exit_code'], 2, result)
                self.assertTrue(any('Recovery owner differs from authoritative source/head/age/dependencies' in row['reason']
                    for row in result['blocked']), result)
                with evidence._context_database(context) as db:
                    self.assertEqual(evidence._canonical_plain(state._source_baseline(None, db, context=context)), before_baseline)
                for action in request['manifest']['actions']:
                    self.assertEqual(changes._fingerprint(Path(action['owner']['root']), action['effects'][0]['path']), before_effects[action['id']])
                project_file = Path(request['manifest']['enrollment']['record']['project_root']) / changes.PROJECT_FILE
                self.assertFalse(project_file.exists())
                canonical_marker = Path(changes.LOCK_ROOT) / ('canonical-' + hashlib.sha256(
                    ('destination:' + str(project_file)).encode()).hexdigest() + '.lock')
                markers = [*changes._authority_locations([context.directory]), canonical_marker]
                self.assertTrue(all(changes._authority_owner(marker) is not None for marker in markers), markers)


if __name__ == '__main__':
    unittest.main()
