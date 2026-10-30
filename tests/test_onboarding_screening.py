"""D3 pre-assessment screening uses genuine private plans and temporary producers."""

from contextlib import contextmanager
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import patch

from runtime import evidence, screening, state
from runtime.startup import StartupError
from tests import test_onboarding, test_review_storage


@contextmanager
def real_case(mode='legacy', *, files=1):
    onboarding = test_onboarding.OnboardingTests(methodName='runTest')
    storage = test_review_storage.ReviewStorageTests(methodName='runTest')
    onboarding.setUp()
    storage.setUp()
    try:
        api = storage.load_api()
        storage.prepare()
        roots = [onboarding.repo]
        if mode == 'umbrella':
            roots.append(onboarding.second_repository())
            (onboarding.base / 'AGENTS.md').write_text('shared product instructions\n')
            record = onboarding.project_record(onboarding.base, roots, 'umbrella', ['AGENTS.md'])
            cwd = onboarding.base
            selection = {'project_scope': copy.deepcopy(record['project_scope'])}
        else:
            cwd, record = onboarding.repo, copy.deepcopy(onboarding.record)
            selection = {'target': str(onboarding.repo)}
        for root in roots:
            source = root / 'src' / 'feature'
            source.mkdir(parents=True)
            for index in range(files):
                (source / f'large_{index:03}.py').write_text('value = 1\n' * 1002)
            (root / '.env').write_text('PRIVATE_FIXTURE_SENTINEL=never-report\n')
            (root / 'binary.bin').write_bytes(b'\x00\xff\x01')
        yield dict(d3=onboarding, storage=storage, api=api, module=onboarding.module(),
                   roots=roots, cwd=cwd, record=record, selection=selection)
    finally:
        storage.doCleanups()
        onboarding.doCleanups()


@contextmanager
def actual_store(case, *, write=False):
    api = case['api']
    with api._machine_guard() as (path, descriptor, parents):
        config = api._configuration(path, descriptor)
        context = api._ready_context(config, parents)
        with evidence._context_database(context, write=write, durable=write) as db:
            yield config, context, db


class OnboardingScreeningTests(unittest.TestCase):
    def inspect(self, case, directory=None, record=None):
        return case['module'].inspect_project(case['cwd'], directory or case['d3'].directory,
                                              record or copy.deepcopy(case['record']))

    def plan(self, case, directory=None):
        return json.loads(((directory or case['d3'].directory) / 'plan.json').read_text())

    def projected(self, case, report=None):
        plan = self.plan(case)
        self.assertIn('screening', plan.keys(), 'real Inspect must publish helper-owned screening before assessment')
        projection = plan['screening']
        self.assertEqual(set(projection), {'version', 'payload', 'freshness'})
        self.assertEqual(projection['version'], 1)
        self.assertEqual(set(projection['payload']),
            {'version', 'accounting', 'ticket', 'repositories', 'inputs', 'coverage', 'timing'})
        if report is not None:
            self.assertIn('screening', report)
            self.assertEqual(report['revision'], plan['revision'])
            self.assertEqual(report['review_digest'], plan['review_digest'])
            self.assertEqual(report['current_input_digest'], plan['current_input_digest'])
        return projection

    def accounting(self, case):
        return case['api'].screening_status(copy.deepcopy(case['selection']))

    def assert_bound(self, case, projection):
        status = self.accounting(case)
        self.assertTrue(status.get('ok'), status)
        self.assertEqual(status['revision'], 2)
        payload = projection['payload']
        for key in ('owner', 'reference', 'created_at'):
            self.assertEqual(payload['accounting'][key], status[key])
        self.assertEqual(status['screening']['last_receipt']['ticket'], payload['ticket'])
        with actual_store(case) as (_, _, db):
            metadata = state._metadata(db, status['reference']['name'])
        self.assertIn('screening_result', metadata)
        pointer = metadata['screening_result']
        self.assertEqual(set(pointer), {'version', 'ticket', 'plan_directory', 'directory_binding',
                                        'plan_id', 'projection_digest'})
        self.assertEqual(pointer['ticket'], payload['ticket'])
        self.assertEqual(pointer['projection_digest'], evidence._digest(payload))
        self.assertEqual(pointer['plan_directory'], str(case['d3'].directory))
        self.assertEqual(pointer['plan_id'], self.plan(case)['plan_id'])
        return status, pointer

    def new_plan(self, case):
        directory = case['d3'].directory.with_name('new-screening-plan')
        directory.mkdir(mode=0o700)
        source = directory / 'catalog.md'
        source.write_bytes(case['d3'].source.read_bytes())
        source.chmod(0o600)
        record = copy.deepcopy(case['record'])
        record['toolkit']['files'][0]['local_path'] = str(source)
        return directory, record

    def test_existing_both_format_fixtures_reach_real_plan_and_owner_boundaries(self):
        for mode in ('legacy', 'umbrella'):
            with self.subTest(mode=mode), real_case(mode) as case:
                report = self.inspect(case)
                plan = self.plan(case)
                self.assertEqual(plan['schema_version'], 1 if mode == 'legacy' else 2)
                self.assertEqual(report['revision'], plan['revision'])
                api = case['api']
                owner = (api.resolve_owner(case['d3'].repo) if mode == 'legacy'
                         else api.resolve_project_owner(case['selection']['project_scope']))
                self.assertTrue(owner.get('ok'), owner)
                self.assertEqual(owner['owner']['kind'], 'temporary')
                with actual_store(case) as (_, context, db):
                    metadata = state._metadata(db, owner['reference']['name'])
                    body = evidence._read(None, owner['reference'], context=context, db=db)
                self.assertEqual(metadata['owner'], owner['owner'])
                self.assertEqual(body['kind'], 'temporary-target-owner' if mode == 'legacy'
                                 else 'temporary-project-owner')

    def test_both_formats_publish_reserve_collect_before_authored_assessment(self):
        for mode in ('legacy', 'umbrella'):
            with self.subTest(mode=mode), real_case(mode) as case:
                targets = [case['storage'].tree_snapshot(root) for root in case['roots']]
                with actual_store(case) as (_, _, db):
                    self.assertEqual(db.execute('select count(*) from evidence_metadata').fetchone()[0], 1)
                report = self.inspect(case)
                projection = self.projected(case, report)
                self.assert_bound(case, projection)
                plan = self.plan(case)
                assessments = ([plan] if mode == 'legacy' else plan['assessments']['repositories'])
                self.assertTrue(all(not item['semantic_assessment'] for item in assessments))
                self.assertEqual([case['storage'].tree_snapshot(root) for root in case['roots']], targets)
                self.assertNotIn('PRIVATE_FIXTURE_SENTINEL', json.dumps(plan))

    def test_first_existing_anchor_is_reserved_once_without_rebirth(self):
        with real_case() as case:
            owner = case['api'].resolve_owner(case['d3'].repo)
            before = self.accounting(case)
            self.assertEqual(before.get('revision'), 0, before)
            report = self.inspect(case)
            after = self.accounting(case)
            self.assertEqual(after.get('revision'), 2, 'Inspect must execute and settle the real allowance')
            for key in ('owner', 'reference', 'created_at'):
                self.assertEqual(after[key], owner[key])
            self.assert_bound(case, self.projected(case, report))

    def test_umbrella_repeat_resume_and_new_plan_reuse_exact_payload_and_pointer(self):
        with real_case('umbrella') as case:
            self.inspect(case)
            projection = self.projected(case)
            original, pointer = self.assert_bound(case, projection)
            repeated = self.inspect(case)
            self.assertEqual(self.projected(case, repeated)['payload'], projection['payload'])
            directory, record = self.new_plan(case)
            report = self.inspect(case, directory, record)
            copied = self.plan(case, directory)['screening']
            self.assertEqual(copied['payload'], projection['payload'])
            self.assertIn('screening', report)
            with actual_store(case) as (_, _, db):
                self.assertEqual(state._metadata(db, original['reference']['name'])['screening_result'], pointer)
            replay = case['api'].reserve_screening(case['selection'], 0)
            self.assertFalse(replay['admitted'])
            self.assertNotIn('deadline_monotonic', replay)

    def test_authored_screening_is_rejected_without_changing_real_accounting(self):
        with real_case() as case:
            self.inspect(case)
            before = self.plan(case)
            request = case['d3'].proposal(before['revision'])
            request['screening'] = {'version': 1, 'payload': {'coverage': 'caller assertion'}}
            with actual_store(case) as (_, _, db):
                database = list(db.iterdump())
            with self.assertRaises(StartupError):
                case['module'].record_plan(case['d3'].directory, request)
            self.assertEqual(self.plan(case), before)
            with actual_store(case) as (_, _, db):
                self.assertEqual(list(db.iterdump()), database)

    def test_copied_capability_ticket_and_authored_payload_cannot_publish(self):
        with real_case() as case:
            owner = case['api'].resolve_owner(case['d3'].repo)
            self.assertTrue(owner.get('ok'), owner)
            collect = getattr(case['module'], '_collect_onboarding_screening', None)
            finalize = getattr(case['module'], '_finalize_onboarding_screening', None)
            self.assertTrue(callable(collect), 'the real controlled collector is required')
            self.assertTrue(callable(finalize), 'the one-shot real finalizer is required')
            captured = []

            def capture(run):
                payload = collect(run)
                captured.append((run, payload))
                for forged in (copy.copy(run), {}, {'ticket': payload['ticket']}):
                    with self.assertRaises(StartupError):
                        finalize(forged, payload)
                with self.assertRaises(StartupError):
                    finalize(run, copy.deepcopy(payload))
                return payload

            with patch.object(case['module'], '_collect_onboarding_screening', side_effect=capture):
                self.inspect(case)
            self.assertEqual(len(captured), 1)
            self.assert_bound(case, self.projected(case))
            run, payload = captured[0]
            before = case['storage'].tree_snapshot(case['storage'].private)
            finalize(run, payload)
            self.assertEqual(case['storage'].tree_snapshot(case['storage'].private), before)

    def test_source_plan_missing_moved_replaced_or_tampered_never_rescans_or_creates_it(self):
        for change in ('missing', 'moved', 'replaced', 'tampered'):
            with self.subTest(change=change), real_case() as case:
                self.inspect(case)
                projection = self.projected(case)
                original, pointer = self.assert_bound(case, projection)
                directory, record = self.new_plan(case)
                source = case['d3'].directory
                saved = source.with_name('saved-original-plan')
                if change in ('missing', 'moved', 'replaced'):
                    source.rename(saved)
                    if change == 'missing':
                        shutil.rmtree(saved)
                    elif change == 'replaced':
                        shutil.copytree(saved, source)
                else:
                    value = self.plan(case)
                    value['screening']['payload']['coverage']['gaps'].append('forged coverage')
                    (source / 'plan.json').write_text(json.dumps(value))
                source_before = case['storage'].tree_snapshot(source)
                result = self.inspect(case, directory, record)
                self.assertEqual(result['screening']['status'], 'unavailable', result)
                self.assertEqual(case['storage'].tree_snapshot(source), source_before)
                self.assertEqual(self.accounting(case)['screening'], original['screening'])
                with actual_store(case) as (_, _, db):
                    self.assertEqual(state._metadata(db, original['reference']['name'])['screening_result'], pointer)

    def test_crash_before_or_after_projection_save_keeps_reserved_unbound_allowance(self):
        for after_save in (False, True):
            with self.subTest(after_save=after_save), real_case() as case:
                save = case['module']._save
                seen = []

                def interrupted(plan, *args, **kwargs):
                    if 'screening' in plan:
                        seen.append(copy.deepcopy(plan['screening']))
                        if after_save:
                            save(plan, *args, **kwargs)
                        raise OSError('fixture projection publication interruption')
                    return save(plan, *args, **kwargs)

                with patch.object(case['module'], '_save', side_effect=interrupted):
                    report = self.inspect(case)
                self.assertEqual(len(seen), 1, 'real screen must attempt projection publication')
                current = self.accounting(case)
                self.assertEqual(current.get('revision'), 1, current)
                with actual_store(case) as (_, _, db):
                    self.assertNotIn('screening_result', state._metadata(db, current['reference']['name']))
                self.assertEqual(report['screening']['status'], 'unavailable')
                replay = self.inspect(case)
                self.assertEqual(replay['screening']['status'], 'unavailable')
                self.assertEqual(self.accounting(case)['screening'], current['screening'])

    def test_failed_settlement_commit_leaves_saved_projection_unbound(self):
        with real_case() as case:
            connect = sqlite3.connect
            pending = []

            class FailingPointerCommit(sqlite3.Connection):
                def commit(db):
                    for (raw,) in db.execute('select data from evidence_metadata'):
                        metadata = json.loads(raw)
                        if metadata.get('screening_result') is not None:
                            pending.append(copy.deepcopy(metadata))
                            raise sqlite3.OperationalError('fixture pointer commit failure')
                    return super().commit()

            def connection(*args, **kwargs):
                return connect(*args, factory=FailingPointerCommit, **kwargs)

            with patch.object(evidence.sqlite3, 'connect', side_effect=connection):
                report = self.inspect(case)
            self.assertEqual(len(pending), 1, 'observe actual pending pointer and terminal receipt')
            self.assertEqual(pending[0]['screening']['revision'], 2)
            self.assertIn('screening', self.plan(case))
            current = self.accounting(case)
            self.assertEqual(current.get('revision'), 1, current)
            self.assertEqual(report['screening']['status'], 'unavailable')
            with actual_store(case) as (_, _, db):
                self.assertNotIn('screening_result', state._metadata(db, current['reference']['name']))

    def test_post_commit_response_interruption_keeps_reusable_pointer(self):
        with real_case() as case:
            manager = evidence._context_database
            committed = []

            @contextmanager
            def interrupt_response(context, **options):
                with manager(context, **options) as db:
                    yield db
                    if options.get('write'):
                        committed.extend(json.loads(raw) for (raw,) in db.execute('select data from evidence_metadata')
                                         if json.loads(raw).get('screening_result') is not None)
                if committed:
                    raise OSError('fixture response lost after real pointer commit')

            with patch.object(evidence, '_context_database', side_effect=interrupt_response):
                self.inspect(case)
            self.assertEqual(len(committed), 1, 'pointer must commit before response interruption')
            projection = self.projected(case)
            original, pointer = self.assert_bound(case, projection)
            replay = self.inspect(case)
            self.assertEqual(self.projected(case, replay)['payload'], projection['payload'])
            with actual_store(case) as (_, _, db):
                self.assertEqual(state._metadata(db, original['reference']['name'])['screening_result'], pointer)

    def test_revision_change_during_unlocked_collection_cannot_publish_pointer(self):
        with real_case() as case:
            collect = getattr(case['module'], '_collect_onboarding_screening', None)
            self.assertTrue(callable(collect), 'real controlled collector must run outside plan lock')
            changed = []

            def competing_revision(run):
                payload = collect(run)
                with case['module']._locked(case['d3'].directory) as (path, descriptor):
                    plan = case['module']._load(path)
                    plan['revision'] += 1
                    changed.append(plan['revision'])
                    case['module']._save(plan, path, descriptor)
                return payload

            with patch.object(case['module'], '_collect_onboarding_screening', side_effect=competing_revision):
                result = self.inspect(case)
            self.assertEqual(len(changed), 1)
            self.assertEqual(self.plan(case)['revision'], changed[0])
            self.assertEqual(result['revision'], changed[0])
            self.assertEqual(result['screening']['status'], 'unavailable')
            current = self.accounting(case)
            self.assertEqual(current['revision'], 1)
            with actual_store(case) as (_, _, db):
                self.assertNotIn('screening_result', state._metadata(db, current['reference']['name']))

    def test_many_candidates_have_no_count_cap_and_groups_stay_repository_scoped(self):
        with real_case('umbrella', files=130) as case:
            report = self.inspect(case)
            payload = self.projected(case, report)['payload']
            groups = payload['coverage']['groups']
            for root in case['roots']:
                selected = [group for group in groups if group['repository_root'] == str(root)]
                self.assertTrue(selected)
                self.assertEqual(sum(group['oversized_count'] for group in selected), 130)
                self.assertTrue(all(not Path(group['ancestor']).is_absolute() for group in selected))
            self.assertFalse(payload['coverage']['partial'])
            self.assertNotIn('PRIVATE_FIXTURE_SENTINEL', json.dumps(payload))
            self.assertTrue(all(group['effort'] == group['risk'] == 'unknown' for group in groups))

    def test_original_entry_deadline_bounds_acquisition_collection_and_partial_reporting(self):
        with real_case('umbrella') as case:
            begin = getattr(screening, '_begin_onboarding_screening', None)
            collect = getattr(case['module'], '_collect_onboarding_screening', None)
            self.assertTrue(callable(begin), 'combined real publication/reservation must share entry clock')
            self.assertTrue(callable(collect))
            clock = screening.time.monotonic
            offset = [0.0]
            observed = []

            def now():
                return clock() + offset[0]

            def acquire(run, *args, **kwargs):
                observed.append(run.deadline_monotonic)
                offset[0] += 299.9
                return begin(run, *args, **kwargs)

            with patch.object(screening.time, 'monotonic', side_effect=now), \
                    patch.object(screening, '_begin_onboarding_screening', side_effect=acquire):
                report = self.inspect(case)
            self.assertEqual(len(observed), 1)
            view = report['screening']
            self.assertIn(view['status'], ('partial', 'unavailable'))
            self.assertFalse(view.get('admitted', False))
            self.assertNotIn('deadline_monotonic', view)
            self.assertFalse(any('screening' in block['scope'].lower() for block in report['blockers']))
            current = self.accounting(case)
            if current.get('revision') is not None:
                self.assertIn(current['revision'], (1, 2))
            self.assertNotIn('native timing qualified', json.dumps(report).lower())

    def test_reconciliation_keeps_hashed_payload_and_changes_only_freshness(self):
        with real_case() as case:
            self.inspect(case)
            original = self.projected(case)
            _, pointer = self.assert_bound(case, original)
            (case['d3'].repo / 'README.md').write_text('changed ordinary input\n')
            report = self.inspect(case)
            changed = self.projected(case, report)
            self.assertEqual(changed['payload'], original['payload'])
            self.assertEqual(changed['freshness']['status'], 'stale')
            self.assertEqual(evidence._digest(changed['payload']), pointer['projection_digest'])
            proposal = case['d3'].proposal(self.plan(case)['revision'])
            proposal['reconcile'] = {'input_digest': report['current_input_digest'], 'reason': 'fixture current inputs'}
            case['module'].record_plan(case['d3'].directory, proposal)
            self.assertEqual(self.projected(case)['payload'], original['payload'])


if __name__ == '__main__':
    unittest.main()
