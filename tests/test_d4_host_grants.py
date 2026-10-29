"""D4 host grant origin and exact-issuance tests."""
from dataclasses import replace
from pathlib import Path
import unittest

from runtime import evidence, state
from tests import test_changes


class D4HostGrantTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_changes.ScopedChangesTests(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_cloned_issued_grant_is_rejected_before_markers_or_effects(self):
        changes = self.fixture.changes
        request, contexts = self.fixture.d4_bookkeeping_request(umbrella=True)
        original_effects = {action['id']: changes._fingerprint(Path(action['owner']['root']), action['effects'][0]['path'])
            for action in request['manifest']['actions']}
        with_baselines = {}
        for context in contexts:
            with evidence._context_database(context) as db:
                with_baselines[str(context.database)] = evidence._canonical_plain(state._source_baseline(None, db, context=context))
        issued, clones, seen = [], [], []

        class Host:
            def acquire_d4_bookkeeping(self, facts, issue):
                seen.append(evidence._canonical_plain(facts))
                grant = issue(facts)
                issued.append(grant)
                self_outer.assertIsInstance(grant, changes._D4HostGrant)
                clone = replace(grant)
                clones.append(clone)
                return clone

        self_outer = self
        with changes._bootstrap_d4_host(Host(), issuer=changes._D4_HOST_BOOTSTRAP_ISSUER) as host:
            result = changes._run_scoped(self.fixture.directory, request, 'apply', host=host)

        self.assertEqual(len(seen), 1)
        self.assertEqual(len(issued), 1)
        self.assertEqual(len(clones), 1)
        self.assertIsInstance(issued[0], changes._D4HostGrant)
        self.assertIsNot(clones[0], issued[0])
        self.assertEqual(result['exit_code'], 2, result)
        self.assertTrue(any('D4 host grant is foreign, reconstructed or expired' in row['reason']
            for row in result['blocked']), result)
        self.assertEqual(result['activation_status'], 'configured')
        self.assertFalse(result['qualified'])
        self.assertFalse((self.fixture.repo / changes.PROJECT_FILE).exists())
        for action in request['manifest']['actions']:
            self.assertEqual(changes._fingerprint(Path(action['owner']['root']), action['effects'][0]['path']), original_effects[action['id']])
        for context in contexts:
            with evidence._context_database(context) as db:
                self.assertEqual(evidence._canonical_plain(state._source_baseline(None, db, context=context)),
                    with_baselines[str(context.database)])
            self.assertTrue(all(changes._authority_owner(location) is None
                for location in changes._authority_locations([context.directory])))


if __name__ == '__main__':
    unittest.main()
