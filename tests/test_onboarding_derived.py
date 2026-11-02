"""Onboarding derives observed bindings and hashes, leaving decisions with the coordinator."""
import unittest
from runtime import onboarding
from tests.fixture_canonical_birth import OnboardingFixture


class DerivedProposalTests(unittest.TestCase):
    def test_semantic_proposal_retains_complete_catalog_and_derives_repeated_facts(self):
        fixture = OnboardingFixture('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.scoped_inspect()
        request = fixture.scoped_proposal()
        assessment = request['assessments']['repositories'][0]
        expected = assessment.copy()
        del assessment['identity']
        for action in assessment['actions']:
            for key in ('before', 'after', 'owner'):
                del action[key]
        for item in assessment['evidence']:
            del item['input_digest']
        result = onboarding.record_plan(fixture.directory, request)
        self.assertEqual(result['exit_code'], 0, result)
        recorded = fixture.plan()['assessments']['repositories'][0]
        self.assertEqual(recorded['identity']['binding'], expected['identity']['binding'])
        self.assertEqual(recorded['identity']['root'], expected['identity']['root'])
        self.assertEqual(len(recorded['coverage']), len(fixture.plan()['requirements']))
        self.assertEqual(recorded['actions'][0]['after'], onboarding.hashlib.sha256(recorded['actions'][0]['text'].encode()).hexdigest())
