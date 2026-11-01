"""Additional producer, deadline and reuse boundaries use real disposable storage."""

from contextlib import contextmanager
import copy
import json
import shutil
from pathlib import Path
import unittest
from unittest.mock import patch

from runtime import onboarding, screening, state
from runtime.startup import StartupError
from tests import test_onboarding_screening as fixtures

real_case = fixtures.real_case
actual_store = fixtures.actual_store


class OnboardingScreeningGuardTests(unittest.TestCase):
    def setUp(self):
        self.support = fixtures.OnboardingScreeningTests(methodName='runTest')

    @staticmethod
    def substitute_plan(case, change):
        directory = case['d3'].directory
        if change == 'directory':
            saved = directory.with_name('original-authenticated-directory')
            directory.rename(saved)
            shutil.copytree(saved, directory)
        else:
            plan = json.loads((directory / 'plan.json').read_text())
            if change == 'identity':
                plan['plan_id'] = 'f' * 32
            else:
                group = next(group for group in plan['screening']['payload']['coverage']['groups']
                             if group['oversized_count'])
                group.update(counted_files=9001, oversized_count=9001, inspected_files=9001)
            (directory / 'plan.json').write_text(json.dumps(plan))

    def owner_snapshot(self, case):
        status = self.support.accounting(case)
        with actual_store(case) as (_, _, db):
            metadata = state._metadata(db, status['reference']['name'])
        return copy.deepcopy((metadata['screening_result'], metadata['screening']))

    def test_publication_post_auth_swap_never_reports_substituted_evidence(self):
        for change in ('identity', 'payload', 'directory'):
            with self.subTest(change=change), real_case() as case:
                finalize = onboarding._finalize_onboarding_screening
                committed = []
                def replace(run, payload):
                    result = finalize(run, payload)
                    self.assertEqual(result['status'], 'published')
                    committed.append(self.owner_snapshot(case))
                    self.substitute_plan(case, change)
                    return result
                with patch.object(onboarding, '_finalize_onboarding_screening', side_effect=replace), \
                        patch.object(onboarding, '_collect_onboarding_screening', wraps=onboarding._collect_onboarding_screening) as collect:
                    report = self.support.inspect(case)
                self.assertEqual(report['screening']['status'], 'unavailable')
                self.assertNotIn('coverage', report['screening'])
                self.assertEqual(collect.call_count, 1)
                self.assertEqual(self.owner_snapshot(case), committed[0])
                saved = self.support.plan(case)
                for field in ('revision', 'review_digest', 'current_input_digest'):
                    self.assertEqual(report[field], saved[field])

    def test_reuse_post_auth_swap_never_reports_substituted_evidence(self):
        for change in ('identity', 'payload', 'directory'):
            with self.subTest(change=change), real_case() as case:
                self.support.inspect(case)
                original = self.owner_snapshot(case)
                begin = screening._begin_onboarding_screening
                def replace(*args, **kwargs):
                    result = begin(*args, **kwargs)
                    self.assertEqual(result['status'], 'reuse')
                    self.substitute_plan(case, change)
                    return result
                with patch.object(screening, '_begin_onboarding_screening', side_effect=replace), \
                        patch.object(onboarding, '_collect_onboarding_screening', wraps=onboarding._collect_onboarding_screening) as collect:
                    report = self.support.inspect(case)
                self.assertEqual(report['screening']['status'], 'unavailable')
                self.assertNotIn('coverage', report['screening'])
                self.assertEqual(collect.call_count, 0)
                self.assertEqual(self.owner_snapshot(case), original)
                saved = self.support.plan(case)
                for field in ('revision', 'review_digest', 'current_input_digest'):
                    self.assertEqual(report[field], saved[field])

    def test_enrolled_project_with_empty_history_cannot_report_foreign_projection(self):
        from runtime import review_storage
        from tests import test_enrolled_accounting_integration, test_project_owner_enrolled
        with real_case() as foreign:
            self.support.inspect(foreign)
            projection = copy.deepcopy(self.support.projected(foreign))
            foreign_owner = self.owner_snapshot(foreign)
            enrolled = test_enrolled_accounting_integration.EnrolledUmbrellaAccountingTests(methodName='runTest')
            enrolled.setUp()
            try:
                self.assertTrue(review_storage.prepare_storage(enrolled.private / 'temporary-state')['ok'])
                scope = test_project_owner_enrolled.ProjectOwnerEnrolledTests.scope(enrolled.record)
                ordinary = review_storage.resolve_project_owner(scope)
                self.assertTrue(ordinary['ok'])
                self.assertEqual(ordinary['status'], 'resolved')
                self.assertEqual(ordinary['owner']['kind'], 'project')
                self.assertEqual(ordinary['temporary_history'], dict(complete=True,
                    reason='authenticated_no_related_history', owners=[]))
                directory = enrolled.private / 'inspection'
                directory.mkdir(mode=0o700)
                source = directory / 'catalog.md'
                source.write_bytes(enrolled.d4.source.read_bytes())
                source.chmod(0o600)
                record = enrolled.d4.project_record(root=Path(enrolled.record['project_root']),
                    members=enrolled.members, kind='umbrella')
                record['toolkit']['files'][0]['local_path'] = str(source)
                record['project_scope'] = copy.deepcopy(scope)
                onboarding.inspect_project(Path(enrolled.record['project_root']), directory, record)
                plan = json.loads((directory / 'plan.json').read_text())
                plan['screening'] = projection
                (directory / 'plan.json').write_text(json.dumps(plan))
                from tests.test_review_storage import ReviewStorageTests
                def accounting_bytes():
                    return (ReviewStorageTests.tree_snapshot(enrolled.private / 'temporary-state'),
                            ReviewStorageTests.tree_snapshot(enrolled.storage), enrolled.authority.read_bytes())
                before = accounting_bytes()
                with patch.object(onboarding, '_collect_onboarding_screening', wraps=onboarding._collect_onboarding_screening) as collect:
                    report = onboarding.inspect_project(Path(enrolled.record['project_root']), directory, record)
                self.assertEqual(report['screening']['status'], 'unavailable')
                self.assertNotIn('coverage', report['screening'])
                self.assertEqual(collect.call_count, 0)
                self.assertEqual(review_storage.resolve_project_owner(scope), ordinary)
                self.assertTrue(accounting_bytes() == before, 'Project and temporary accounting must remain unchanged')
            finally:
                enrolled.doCleanups()
            self.assertEqual(self.owner_snapshot(foreign), foreign_owner)

    def test_directory_swap_after_commit_cannot_rebind_report_authentication(self):
        from runtime import evidence
        with real_case() as case:
            manager = evidence._context_database
            committed = []
            @contextmanager
            def replace_after_commit(context, **options):
                pending = []
                with manager(context, **options) as db:
                    yield db
                    if options.get('write'):
                        pending = [json.loads(raw) for (raw,) in db.execute('select data from evidence_metadata')
                                   if json.loads(raw).get('screening_result') is not None]
                if pending and not committed:
                    committed.extend(pending)
                    self.substitute_plan(case, 'directory')
            with patch.object(evidence, '_context_database', side_effect=replace_after_commit), \
                    patch.object(onboarding, '_collect_onboarding_screening', wraps=onboarding._collect_onboarding_screening) as collect:
                report = self.support.inspect(case)
            self.assertEqual(len(committed), 1)
            self.assertNotEqual(committed[0]['screening_result']['directory_binding'],
                                onboarding._screening_directory_binding(case['d3'].directory))
            self.assertEqual(report['screening']['status'], 'unavailable')
            self.assertNotIn('coverage', report['screening'])
            self.assertEqual(collect.call_count, 1)
            self.assertEqual(self.owner_snapshot(case), (committed[0]['screening_result'], committed[0]['screening']))
            with patch.object(onboarding, '_collect_onboarding_screening', wraps=onboarding._collect_onboarding_screening) as collect:
                repeated = self.support.inspect(case)
            self.assertEqual(repeated['screening']['status'], 'unavailable')
            self.assertEqual(collect.call_count, 0)
            self.assertEqual(self.owner_snapshot(case), (committed[0]['screening_result'], committed[0]['screening']))

    def test_failed_finalizer_response_does_not_reuse_prior_report_authentication(self):
        with real_case() as case:
            finalize = onboarding._finalize_onboarding_screening
            committed = []
            def fail(run, payload):
                result = finalize(run, payload)
                self.assertEqual(result['status'], 'published')
                committed.append(self.owner_snapshot(case))
                raise StartupError('Fixture response failed after authenticated publication')
            with patch.object(onboarding, '_finalize_onboarding_screening', side_effect=fail):
                report = self.support.inspect(case)
            self.assertEqual(report['screening']['status'], 'unavailable')
            self.assertEqual(self.owner_snapshot(case), committed[0])
            with patch.object(onboarding, '_collect_onboarding_screening', wraps=onboarding._collect_onboarding_screening) as collect:
                repeated = self.support.inspect(case)
            self.assertEqual(repeated['screening']['status'], 'complete')
            self.assertEqual(collect.call_count, 0)

    def test_record_projection_inserted_after_first_absent_read_is_unavailable(self):
        with real_case() as case:
            self.support.inspect(case)
            original = self.owner_snapshot(case)
            plan = self.support.plan(case)
            projection = plan.pop('screening')
            (case['d3'].directory / 'plan.json').write_text(json.dumps(plan))
            request = case['d3'].proposal(plan['revision'])
            load = onboarding._load
            inserted = []
            def insert(path):
                observed = load(path)
                if not inserted:
                    self.assertNotIn('screening', observed)
                    value = copy.deepcopy(observed)
                    value['screening'] = copy.deepcopy(projection)
                    (path / 'plan.json').write_text(json.dumps(value))
                    inserted.append(True)
                return observed
            with patch.object(onboarding, '_load', side_effect=insert), \
                    patch.object(onboarding, '_collect_onboarding_screening', wraps=onboarding._collect_onboarding_screening) as collect:
                report = onboarding.record_plan(case['d3'].directory, request)
            self.assertEqual(report['screening']['status'], 'unavailable')
            self.assertNotIn('coverage', report['screening'])
            self.assertEqual(self.support.plan(case)['screening']['freshness']['status'], 'unavailable')
            self.assertEqual(collect.call_count, 0)
            self.assertEqual(self.owner_snapshot(case), original)

    def test_public_settlement_during_collection_cannot_publish_coverage(self):
        with real_case() as case:
            collect = onboarding._collect_onboarding_screening

            def settle(run):
                payload = collect(run)
                receipt = case['api'].settle_screening(case['selection'], payload['ticket'])
                self.assertEqual(receipt['revision'], 2)
                return payload

            with patch.object(onboarding, '_collect_onboarding_screening', side_effect=settle):
                report = self.support.inspect(case)
            self.assertEqual(report['screening']['status'], 'unavailable')
            self.assertNotIn('screening', self.support.plan(case).keys())
            current = self.support.accounting(case)
            with actual_store(case) as (_, _, db):
                self.assertNotIn('screening_result', state._metadata(db, current['reference']['name']))
            with patch.object(onboarding, '_collect_onboarding_screening', side_effect=AssertionError('No re-admission')):
                repeated = self.support.inspect(case)
            self.assertEqual(repeated['screening']['status'], 'unavailable')
            self.assertEqual(self.support.accounting(case)['screening'], current['screening'])

    def test_mutated_live_payload_cannot_publish(self):
        with real_case() as case:
            collect = onboarding._collect_onboarding_screening

            def mutate(run):
                payload = collect(run)
                payload['coverage']['gaps'].append('caller-modified claim')
                with self.assertRaises(StartupError):
                    onboarding._finalize_onboarding_screening(run, payload)
                return payload

            with patch.object(onboarding, '_collect_onboarding_screening', side_effect=mutate):
                result = self.support.inspect(case)
            self.assertEqual(result['screening']['status'], 'unavailable')
            self.assertEqual(self.support.accounting(case)['revision'], 1)
            self.assertNotIn('screening', self.support.plan(case).keys())

    def test_consumed_repeat_reuses_required_inspect_digest_without_source_rescreening(self):
        with real_case() as case:
            self.support.inspect(case)
            match = onboarding._screening_inputs_match
            calls = []
            def observe(*args, **kwargs):
                calls.append(True)
                return match(*args, **kwargs)
            with patch.object(onboarding, '_screening_inputs_match', side_effect=observe):
                self.support.inspect(case)
                plan = self.support.plan(case)
                onboarding.record_plan(case['d3'].directory, case['d3'].proposal(plan['revision']))
            self.assertEqual(calls, [], 'Consumed screening cannot reopen source analysis on Inspect or record_plan')

    def test_acquisition_and_publication_share_aggregate_observation_budget(self):
        from runtime import review_storage
        with real_case('umbrella') as case:
            owners = review_storage._owners
            budgets = []
            def observe(*args, **kwargs):
                budget = kwargs.get('budget')
                if budget is not None:
                    budgets.append((budget, budget['bytes']))
                return owners(*args, **kwargs)
            with patch.object(review_storage, '_owners', side_effect=observe):
                report = self.support.inspect(case)
            self.assertEqual(report['screening']['status'], 'complete')
            self.assertTrue(budgets)
            self.assertTrue(all(item[0] is budgets[0][0] for item in budgets), 'Source phases must not reset read/path accounting')
            self.assertEqual([item[1] for item in budgets], sorted(item[1] for item in budgets))

    def test_many_folder_groups_roll_up_in_report_without_dropping_candidate_counts(self):
        with real_case(files=0) as case:
            for index in range(16):
                directory = case['d3'].repo / f'area_{index:02}' / 'feature'
                directory.mkdir(parents=True)
                (directory / 'large.py').write_text('value = 1\n' * 1002)
            report = self.support.inspect(case)
            groups = report['screening']['coverage']['groups']
            self.assertLessEqual(len(groups), 12)
            self.assertEqual(sum(group['oversized_count'] for group in groups), 16)
            self.assertEqual(groups[0]['ancestor'], '.')
            stored = self.support.projected(case)['payload']['coverage']['groups']
            self.assertGreater(len(stored), 12)
            self.assertEqual(sum(group['oversized_count'] for group in stored), 16)

    def test_new_candidate_during_collection_cannot_publish_old_inventory(self):
        with real_case() as case:
            collect = onboarding._collect_onboarding_screening

            def add(run):
                payload = collect(run)
                (case['d3'].repo / 'src/feature/new.py').write_text('value = 1\n' * 1002)
                return payload

            with patch.object(onboarding, '_collect_onboarding_screening', side_effect=add):
                report = self.support.inspect(case)
            self.assertEqual(report['screening']['status'], 'unavailable')
            self.assertEqual(self.support.accounting(case)['revision'], 1)

    def test_umbrella_member_alias_reuses_one_allowance_without_rescanning(self):
        with real_case('umbrella') as case:
            self.support.inspect(case)
            original = self.support.projected(case)['payload']
            before, pointer = self.support.assert_bound(case, self.support.projected(case))
            directory, record = self.support.new_plan(case)
            record.pop('project_scope')
            with patch.object(onboarding, '_collect_onboarding_screening', side_effect=AssertionError('No alias re-admission')):
                onboarding.inspect_project(case['roots'][1], directory, record)
            self.assertEqual(self.support.plan(case, directory)['screening']['payload'], original)
            self.assertEqual(self.support.accounting(case)['screening'], before['screening'])
            with actual_store(case) as (_, _, db):
                self.assertEqual(state._metadata(db, before['reference']['name'])['screening_result'], pointer)

    def test_source_change_during_unlocked_collection_cannot_bind_old_fingerprints(self):
        with real_case() as case:
            collect = onboarding._collect_onboarding_screening

            def change(run):
                payload = collect(run)
                (case['d3'].repo / 'src/feature/large_000.py').write_text('different = 2\n' * 1002)
                return payload

            with patch.object(onboarding, '_collect_onboarding_screening', side_effect=change):
                report = self.support.inspect(case)
            self.assertEqual(report['screening']['status'], 'unavailable')
            self.assertEqual(self.support.accounting(case)['revision'], 1)
            self.assertNotIn('screening', self.support.plan(case).keys())

    def test_deadline_expiry_before_serialization_does_not_save_projection(self):
        with real_case() as case:
            clock = screening.time.monotonic
            offset = [0]
            save = onboarding._save

            def expire(plan, *args, **kwargs):
                if 'screening' in plan:
                    offset[0] = 300
                return save(plan, *args, **kwargs)

            with patch.object(screening.time, 'monotonic', side_effect=lambda: clock() + offset[0]), \
                    patch.object(onboarding, '_save', side_effect=expire):
                report = self.support.inspect(case)
            self.assertEqual(report['screening']['status'], 'unavailable')
            self.assertNotIn('screening', self.support.plan(case).keys())
            self.assertEqual(self.support.accounting(case)['revision'], 1)

    def test_reporting_does_not_reopen_plan_after_original_deadline(self):
        with real_case() as case:
            clock = screening.time.monotonic
            offset = [0]
            finalize = onboarding._finalize_onboarding_screening
            load = onboarding._load
            late_reads = []

            def expire(run, payload):
                result = finalize(run, payload)
                offset[0] = 300
                return result

            def observe(path):
                if offset[0]:
                    late_reads.append(str(path))
                return load(path)

            with patch.object(screening.time, 'monotonic', side_effect=lambda: clock() + offset[0]), \
                    patch.object(onboarding, '_finalize_onboarding_screening', side_effect=expire), \
                    patch.object(onboarding, '_load', side_effect=observe):
                report = self.support.inspect(case)
            self.assertEqual(late_reads, [])
            self.assertEqual(report['screening']['status'], 'unavailable')
            self.assertEqual(self.support.accounting(case)['revision'], 2)
            self.support.assert_bound(case, self.support.projected(case))

    def test_record_plan_marks_unavailable_source_without_trusting_or_replacing_payload(self):
        with real_case() as case:
            self.support.inspect(case)
            plan = self.support.plan(case)
            plan['screening']['payload']['coverage']['gaps'].append('tampered saved claim')
            (case['d3'].directory / 'plan.json').write_text(json.dumps(plan))
            request = case['d3'].proposal(plan['revision'])
            report = onboarding.record_plan(case['d3'].directory, request)
            self.assertEqual(report.get('screening', {}).get('status'), 'unavailable')
            saved = self.support.plan(case)
            self.assertEqual(saved['screening']['freshness']['status'], 'unavailable')
            self.assertEqual(saved['screening']['payload'], plan['screening']['payload'])
            self.assertFalse(any('screening' in block['scope'] for block in report['blockers']))


if __name__ == '__main__':
    unittest.main()
