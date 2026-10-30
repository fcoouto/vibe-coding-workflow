"""Existing-authority activation cases; no birth or hand-inserted task/metadata success."""
from copy import deepcopy
import hashlib
import json
import unittest
from unittest.mock import patch

from runtime import changes, delegation, evidence, state, startup
from tests import test_changes as fixtures


class HistoricalUseActivationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ScopedChangesTests(methodName='runTest')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)

    def host_file(self, name, value):
        path=self.fixture.directory/(name+'.json')
        raw=json.dumps(value,sort_keys=True).encode();path.write_bytes(raw);path.chmod(0o600)
        return dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest())

    def retire(self, scope, task, name):
        identity={key:task[key] for key in ('client','session_id','task_id','scope_ref')}
        proof=dict(version=1,kind='stopped-writer-reconciliation',identity=identity,
            expected_revision=task['revision'],expected_pins=task['pins'],observed_turn_id=task['turn_id'],
            stopped=True,descendants_stopped=True,attempt_ids=[],
            observation_ref='fixture:observed-stopped-writer',coordinator_ref='fixture:independent-owner')
        result=state.retire_task(scope,identity|dict(expected_revision=task['revision'],expected_pins=task['pins'],
            reason='Host observed stopped writer and descendants',reference='fixture:native-retirement',
            stop_proof=self.host_file(name,proof)))
        self.assertTrue(result['ok'],result)
        self.assertEqual(result['task']['pins'],task['pins'])
        self.assertEqual(result['task']['revision'],task['revision']+1)
        return result['task'],proof

    def historical(self,**options):
        observations=[];original=self.fixture.observe_active
        def observe(*args,**kwargs):
            result=original(*args,**kwargs);observations.append(result);return result
        # Retain the existing fixture owner's actual returned qualification facts; invent none.
        with patch.object(self.fixture,'observe_active',side_effect=observe):
            request,scope,context,task,shared=self.fixture.historical_shared_consumer(**options)
        record=json.loads((self.fixture.base/startup.PROJECT_FILE).read_text())
        facts=deepcopy(next(row['scope_observations'] for row in observations[0]['observations']['qualification']
            if row['scope_observations']['observation']['root']==str(self.fixture.repo)))
        facts['authority']['target']=changes._scoped_target(self.fixture.base,str(startup.PROJECT_FILE))
        resolved=startup.resolve_canonical_scope(startup.decode_project_record(record),**facts)
        self.assertEqual(resolved.status,'suspended' if options.get('suspend_prior') else 'active',resolved)
        self.destination_scope=resolved.scope
        retired,proof=self.retire(scope,task,'historical-stop')
        self.assertEqual(retired['state'],'cancelled')
        reference=dict(authority=evidence._canonical_plain(context.authority_set[0]),reference=retired['retirement']['proof'])
        with evidence._context_database(context) as db:
            self.assertEqual(evidence._read(None,reference['reference'],context=context,db=db),proof)
        return request,scope,context,retired,shared,reference

    def local_heads(self, contexts, request):
        rows=[]
        for context in contexts:
            _,sources=changes._recovery_sources(context)
            reference,body=next((ref,body) for ref,body in sources if body['identity']['manifest_digest']==request['approval']['manifest_digest'])
            with evidence._context_database(context) as db:
                metadata=state._metadata(db,reference['name'])
                history=evidence._recovery_source_history(context,db,reference,body['identity'])
            rows.append((reference,metadata['created_at'],body,history))
        return rows

    def bookkeeping_decision(self,request,operation,task):
        from tests import test_onboarding_host
        contexts=tuple(evidence._evidence_context(scope) for scope in self.fixture.d4_bookkeeping_scopes)
        decision=test_onboarding_host.OnboardingHostTests.decision(self,self.fixture,request,operation,contexts)
        identity=task['accepted_identity']
        subject=next(row for row in decision['bookkeeping_scope']['subjects'] if all(row[key]==identity[key]
            for key in ('project_id','repository_id','checkout_id','client')))
        subject['accepted_identity_digest']=state._digest(identity)
        return decision

    def verified_operation(self,request,operation,task):
        from scripts.onboard_coordinator import run_verified_operation
        return run_verified_operation(self.bookkeeping_decision(request,operation,task),self.fixture.directory,request)

    def test_native_stop_allows_managed_first_second_heads_and_exact_replay(self):
        request,scope,context,task,shared,proof=self.historical()
        # Existing authority baselines predate this operation; no birth certificate or fake row is supplied.
        contexts=tuple(evidence._evidence_context(existing) for existing in self.fixture.d4_bookkeeping_scopes)
        for current in contexts:
            with evidence._context_database(current) as db:
                baseline=state._source_baseline(None,db,context=current)
                self.assertEqual(baseline['content']['source_contract'],2)
                self.assertTrue(baseline['dependencies'])
        result=self.fixture.run_with_d4_host(request,'apply')
        self.assertEqual(result['exit_code'],0,result)
        heads=self.local_heads(contexts,request)
        for _,_,body,history in heads:
            self.assertIn('use_contract',body)
            self.assertGreaterEqual(len(history),2)
            self.assertTrue(all('use_contract' in old for _,old in history))
            self.assertIn(dict(authority=proof['authority'],artifact=proof['reference']),body['artifacts'])
        self.assertEqual(len({age for _,age,_,_ in heads}),1)
        resumed=self.fixture.run_with_d4_host(request,'resume')
        self.assertEqual(resumed['exit_code'],0,resumed)
        again=self.local_heads(contexts,request)
        self.assertEqual([(ref,age,body) for ref,age,body,_ in again],[(ref,age,body) for ref,age,body,_ in heads])
        self.assertTrue(changes.inspect_lifecycle_recovery(context.authority_set,())['complete'])
        self.assertEqual(shared.read_text(),'product rules\nchanged shared process\n')
        with evidence._context_database(context) as db:
            self.assertEqual(state._task(db,state._scope_id(scope),'codex','historical-consumer','historical-consumer'),task)

    def test_real_finite_consent_registers_heads_replays_and_rolls_back_without_qualification_claim(self):
        request,scope,context,task,shared,proof=self.historical(suspend_prior=True);before=shared.read_bytes()
        contexts=tuple(evidence._evidence_context(existing) for existing in self.fixture.d4_bookkeeping_scopes)
        result=self.verified_operation(request,'apply',task)
        self.assertEqual(result['state'],'applied',result)
        self.assertEqual(result['exit_code'],2,result)
        self.assertEqual([row['id'] for row in result['blocked']],['qualification'],result)
        self.assertFalse(result['qualified'])
        heads=self.local_heads(contexts,request)
        for _,_,body,history in heads:
            self.assertGreaterEqual(len(history),2)
            self.assertTrue(all('use_contract' in old for _,old in history))
            self.assertIn(dict(authority=proof['authority'],artifact=proof['reference']),body['artifacts'])
        self.assertEqual(len({age for _,age,_,_ in heads}),1)
        replay=self.verified_operation(request,'resume',task)
        self.assertEqual(replay['state'],'applied',replay)
        self.assertEqual([row['id'] for row in replay['blocked']],['qualification'],replay)
        self.assertEqual([(ref,age,body) for ref,age,body,_ in self.local_heads(contexts,request)],
            [(ref,age,body) for ref,age,body,_ in heads])
        rollback=self.verified_operation(request,'rollback',task)
        self.assertEqual(rollback['exit_code'],0,rollback)
        self.assertEqual(shared.read_bytes(),before)
        self.assertEqual({age for _,age,_,_ in self.local_heads(contexts,request)},{age for _,age,_,_ in heads})
        with evidence._context_database(context) as db:
            self.assertEqual(state._task(db,state._scope_id(scope),'codex','historical-consumer','historical-consumer'),task)

    def test_finite_consent_omissions_and_copied_or_expired_grants_leave_heads_and_effects_unchanged(self):
        from dataclasses import replace
        from scripts import onboard_coordinator
        request,_,_,task,shared,_=self.historical();before=shared.read_bytes()
        contexts=tuple(evidence._evidence_context(scope) for scope in self.fixture.d4_bookkeeping_scopes)
        baselines={}
        for context in contexts:
            with evidence._context_database(context) as db:baselines[str(context.database)]=evidence._canonical_plain(state._source_baseline(None,db,context=context))
        for case in ('authority','subject','identity','copied-grant','expired-host'):
            with self.subTest(case=case):
                operation='resume' if changes._load_journal(self.fixture.directory) else 'apply'
                decision=self.bookkeeping_decision(request,operation,task)
                scope=decision['bookkeeping_scope'];identity=task['accepted_identity']
                match=lambda row:all(row[key]==identity[key] for key in ('project_id','repository_id','checkout_id','client'))
                if case=='authority':scope['authorities']=[row for row in scope['authorities'] if row['database']!=contexts[1].authority_set[0]['database']]
                elif case=='subject':scope['subjects']=[row for row in scope['subjects'] if not match(row)]
                elif case=='identity':
                    current=startup.canonical_scope_projection(startup.decode_project_record(request['manifest']['enrollment']['record']),
                        repository_id=identity['repository_id'],checkout_id=identity['checkout_id'],client=identity['client'])
                    digest=state._digest(evidence._canonical_plain(current))
                    self.assertNotEqual(digest,task['pins']['accepted_scope_digest'])
                    next(row for row in scope['subjects'] if match(row))['accepted_identity_digest']=digest
                if case=='copied-grant':
                    original=onboard_coordinator.CoordinatorOperationOwner.acquire_d4_bookkeeping
                    def copy(owner,facts,issue):return replace(original(owner,facts,issue))
                    with patch.object(onboard_coordinator.CoordinatorOperationOwner,'acquire_d4_bookkeeping',copy):
                        result=onboard_coordinator.run_verified_operation(decision,self.fixture.directory,request)
                elif case=='expired-host':
                    owner=onboard_coordinator.CoordinatorOperationOwner(decision)
                    with changes._bootstrap_d4_host(owner,issuer=changes._D4_HOST_BOOTSTRAP_ISSUER) as host:pass
                    result=getattr(changes,operation+'_plan')(self.fixture.directory,request,host=host)
                    self.assertIn('Actual trusted coordinator operation authority',str(result))
                else:result=onboard_coordinator.run_verified_operation(decision,self.fixture.directory,request)
                self.assertNotEqual(result['exit_code'],0,result)
                self.assertNotEqual(result['state'],'applied',result)
                self.assertEqual(shared.read_bytes(),before)
                for context in contexts:
                    with evidence._context_database(context) as db:
                        self.assertEqual(evidence._canonical_plain(state._source_baseline(None,db,context=context)),baselines[str(context.database)])

    def test_unadmitted_linked_read_denies_before_acquiring_native_proof_bytes(self):
        _,_,_,_,_,proof=self.historical()
        original=evidence._managed_content
        for consumer in (None,proof):
            with self.subTest(consumer=consumer):
                reads=[]
                def observe(context,reference,metadata):
                    if reference==proof['reference']:reads.append(reference)
                    return original(context,reference,metadata)
                with patch.object(evidence,'_managed_content',side_effect=observe):
                    with self.assertRaises(state.StateError):
                        evidence._linked_source(proof,consumer=consumer,require_admission=True)
                self.assertEqual(reads,[],'Unadmitted prospective content was read before permission denial')

    def test_real_legacy_consumer_admission_finishes_before_proof_body_read(self):
        _,_,_,_,_,proof=self.historical();destination=self.destination_scope
        task=state.start_task(destination,dict(client='codex',session_id='read-order',task_id='read-order',
            scope_ref='fixture:legacy-read-order',mode='read-only',decision_ref='fixture:accepted'))['task']
        imported=evidence._artifact(destination,dict(kind='fixture:independent-legacy-import',source=proof),
            owner=evidence._artifact_owner(destination,task))
        consumer=dict(authority=evidence._canonical_plain(evidence._evidence_context(destination).authority_set[0]),reference=imported)
        admission=evidence._check_content_consumption;read=evidence._managed_content;phase=['before'];observed=[]
        def check(*args,**kwargs):
            phase[0]='during';result=admission(*args,**kwargs);phase[0]='after';return result
        def content(context,reference,metadata):
            if reference==proof['reference']:observed.append(phase[0])
            return read(context,reference,metadata)
        with patch.object(evidence,'_check_content_consumption',side_effect=check),patch.object(evidence,'_managed_content',side_effect=content):
            result=evidence._linked_source(proof,consumer=consumer,require_admission=True)
        self.assertEqual(result['kind'],'stopped-writer-reconciliation')
        self.assertTrue(observed)
        self.assertEqual(set(observed),{'after'},observed)

    def test_existing_independent_legacy_route_still_allows_actual_import(self):
        request,scope,context,task,shared,proof=self.historical()
        destination=self.destination_scope
        consumer=state.start_task(destination,dict(client='codex',session_id='legacy-consumer',task_id='legacy-consumer',
            scope_ref='fixture:existing-legacy-route',mode='read-only',decision_ref='fixture:accepted'))['task']
        owner=evidence._artifact_owner(destination,consumer)
        with evidence._context_database(context) as db:
            metadata,_=evidence._managed_artifact(None,proof['reference'],context=context,db=db)
            self.assertIn(evidence._canonical_plain(evidence._evidence_context(destination).authority_set[0]),
                evidence._reverse_source_authorities(context,db,metadata,include_intents=False))
        imported=evidence._artifact(destination,dict(kind='fixture:independent-legacy-import',source=proof),owner=owner)
        consumer_ref=dict(authority=evidence._canonical_plain(evidence._evidence_context(destination).authority_set[0]),reference=imported)
        read=evidence._linked_source(proof,consumer=consumer_ref,require_admission=True)
        self.assertEqual(read['kind'],'stopped-writer-reconciliation')
        self.assertEqual(read['expected_pins'],task['pins'])
        self.assertEqual(read['identity']['task_id'],'historical-consumer')

    def test_changed_issued_mandate_propagates_integrity_failure_despite_legacy_route(self):
        from pathlib import Path
        _,_,context,_,_,proof=self.historical()
        with evidence._context_database(context) as db:
            metadata=state._metadata(db,proof['reference']['name'])
            issued=evidence._source_mandate(context,proof['reference'],db=db)
            self.assertIn(evidence._canonical_plain(evidence._evidence_context(self.destination_scope).authority_set[0]),
                evidence._admitted_source_authorities(context,db,metadata))
        path=Path(issued['metadata']['managed']['path']);raw=path.read_bytes()
        path.rename(path.with_suffix('.held'));path.write_bytes(raw);path.chmod(0o400)
        with evidence._context_database(context) as db:
            with self.assertRaises(state.StateError):
                evidence._admitted_source_authorities(context,db,metadata)

    def test_real_native_operation_keeps_same_owner_content_use_separate_from_stop(self):
        request,scope,context,task,shared,proof=self.historical()
        destination=self.destination_scope
        identity=dict(client='codex',session_id='mixed-consumer',task_id='mixed-consumer',scope_ref='fixture:independent-content')
        consumer=state.start_task(destination,identity|dict(mode='editable',decision_ref='fixture:accepted-native-operation'))['task']
        prepared=delegation._reserve_operation(destination,identity|dict(expected_revision=consumer['revision'],dispatch_id='mixed-consumption',
            claims=[dict(kind='path',key=str(self.fixture.repo/'AGENTS.md'),mode='write')],
            operation=dict(id='mixed-consumption',kind='coordinator-work'),reason='Actual independent source consumption',
            ownership_ref='fixture:consumer',stop_conditions=['Stop after source observation']),role='coordinator')
        with state._database(destination) as db:
            consumer=state._task(db,state._scope_id(destination),'codex','mixed-consumer','mixed-consumer')
            record=next(row for row in delegation._ledger(destination,db) if row['id']==prepared['attempt_id'])
        facts=dict(operation_id='mixed-consumption',operation_digest=record['body']['operation']['digest'],claims_digest=evidence._digest(record['data']['claims']))
        observation=evidence._artifact(destination,dict(facts,source=proof),owner=evidence._artifact_owner(destination,consumer))
        stop=dict(version=2,kind='coordinator-operation-reconciliation',identity=identity,expected_pins=consumer['pins'],
            expected_revision=consumer['revision'],scope_id=record['owner']['scope_id'],attempt_id=record['id'],dispatch_id=record['owner']['dispatch_id'],
            assignment_digest=record['data']['assignment']['digest'],decision_ref=consumer['decision_ref'],operation_evidence=observation,
            resource_observations=observation,operation_stopped=True,operation_descendants_stopped=True,
            observation_ref='fixture:independent-native-observation',coordinator_ref='fixture:independent-owner',**facts)
        delegation.reconcile_assignment(destination,identity|dict(expected_revision=consumer['revision'],attempt_id=prepared['attempt_id'],
            host_proof=self.host_file('native-operation-stop',stop),assessment=dict(outcome='cancelled',changed_paths=[],
                result_assessment='Observed stopped operation',partial_change_assessment='No remaining effects',
                evidence=['fixture:actual-source-observation'],coordinator_ref='fixture:owner')))
        consumer=state.task_status(destination,'codex','mixed-consumer')['task']
        self.retire(destination,consumer,'mixed-consumer-stop')
        before=shared.read_bytes();observed=[];original=changes._observe_recovery_source
        def observe(*args,**kwargs):
            result=original(*args,**kwargs);observed.append(result);return result
        # Observe the real owner's unchanged output; never inject roots or admission metadata.
        with patch.object(changes,'_observe_recovery_source',side_effect=observe):
            denied=self.fixture.run_with_d4_host(request,'apply')
        self.assertNotEqual(denied['exit_code'],0,denied)
        self.assertIn('Current D4 source subject enrollment changed',str(denied))
        self.assertEqual(shared.read_bytes(),before)
        self.assertTrue(observed,denied)
        content=evidence._canonical_plain(observed[-1].content)
        uses=content['use_contract']
        self.assertEqual({row['purpose'] for row in uses['roots']},{'historical-stop','content'})
        edge=dict(kind='artifact',reference=dict(authority=proof['authority'],artifact=proof['reference']))
        self.assertEqual({row['purpose'] for row in uses['edges'] if row['dependency']==edge},{'retention-only','content'})


class ExactForeignConsumerTests(unittest.TestCase):
    def foreign(self):
        from tests import test_foreign_admission
        fixture=test_foreign_admission.ForeignAdmissionTests(methodName='runTest')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        source,reference,observations,_=fixture.source_for(fixture.fixture)
        return fixture,source,reference,observations

    def test_real_publishers_and_verify_deny_before_foreign_target_body_read(self):
        fixture,source,reference,observations=self.foreign();selected=fixture.fixture
        destination=selected.selected.scope;task=selected.task(selected.selected)
        contexts=[evidence._evidence_context(row.scope) for row in selected.members]+[evidence._evidence_context(source.scope)]
        original=evidence._managed_content
        for held in (False,True):
            with self.subTest(held=held):
                reads=[]
                def observe(context,ref,metadata):
                    if ref==reference['reference']:reads.append(ref)
                    return original(context,ref,metadata)
                def publish():
                    with self.assertRaises(state.StateError):
                        evidence._artifact(destination,dict(kind='fixture:unadmitted-wrapper',source=reference),owner=evidence._artifact_owner(destination,task))
                with patch.object(evidence,'_managed_content',side_effect=observe):
                    if held:
                        with changes._authority_guards([context.directory for context in contexts]):publish()
                    else:publish()
                self.assertEqual(reads,[],'Publisher acquired denied foreign target content')
        source.scope.authority_path.unlink();reads=[]
        with patch.object(evidence,'_managed_content',side_effect=observe):
            try:result=selected.verify(observations)
            except state.StateError:pass
            else:self.assertFalse(result['verified'],result)
        self.assertEqual(reads,[],'verify_linked acquired denied foreign target content')

    def test_real_compact_legacy_and_source_plan_alias_acquire_only_after_permission(self):
        case=HistoricalUseActivationTests(methodName='runTest');case.setUp();self.addCleanup(case.doCleanups)
        _,_,context,_,_,proof=case.historical();destination=case.destination_scope
        identity=dict(client='codex',session_id='compact-reader',task_id='compact-reader',scope_ref='fixture:compact-current-reader')
        task=state.start_task(destination,identity|dict(mode='read-only',decision_ref='fixture:accepted'))['task']
        with evidence._context_database(context) as db:
            _,sources=changes._recovery_sources(context)
            compact=sources[0][0];mandate=evidence._source_mandate(context,proof['reference'],db=db)['reference']
        guards=[evidence._evidence_context(scope).directory for scope in case.fixture.d4_bookkeeping_scopes]
        for reference in (compact,mandate):
            with self.subTest(reference=reference):
                with changes._authority_guards(guards),evidence._current_content_acquisition(destination,identity|dict(expected_revision=task['revision'])):
                    try:body=evidence._linked_source(dict(authority=evidence._canonical_plain(context.authority_set[0]),reference=reference),require_admission=True)
                    except state.StateError as error:self.fail(str(error))
                    self.assertIn(body['kind'],('d4-recovery-source','source-import-mandate'))
        from tests import test_foreign_admission
        fixture=test_foreign_admission.ForeignAdmissionTests(methodName='runTest');fixture.setUp();self.addCleanup(fixture.doCleanups)
        selected=fixture.fixture;peer=selected.members[1]
        reference=dict(authority=selected.reference(peer)['authority'],reference=selected.task(peer)['evidence']['plan'])
        directories=[evidence._evidence_context(member.scope).directory for member in selected.members]
        with changes._authority_guards(directories),evidence._current_content_acquisition(selected.selected.scope,selected.selected.request()):
            try:body=evidence._linked_source(reference,require_admission=True)
            except state.StateError as error:self.fail(str(error))
            self.assertEqual(body['version'],2)

    def test_existing_source_intent_does_not_admit_another_body_in_same_destination(self):
        from tests import test_foreign_admission
        fixture=test_foreign_admission.ForeignAdmissionTests(methodName='runTest')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        selected=fixture.fixture
        source,reference,observations,_=fixture.source_for(selected)
        result=selected.verify(observations)
        self.assertTrue(result['ok'] and result['verified'],result)
        self.assertEqual(len(source.api._source_intents(source.api._evidence_context(source.scope),reference['reference'])),1)
        original=selected.api._linked_source(reference,consumer=result['verification'],require_admission=True)
        self.assertEqual(original['kind'],'linked-integration-observation')
        destination=selected.selected.scope
        fresh=state.start_task(destination,dict(client='codex',session_id='fresh-consumer',task_id='fresh-consumer',
            scope_ref='fixture:independently-accepted',mode='read-only',decision_ref='fixture:accepted'))['task']
        peer=selected.members[1]
        participant=dict(authority=selected.reference(peer)['authority'],reference=selected.task(peer)['evidence']['verification'])
        for task in (selected.task(selected.selected),fresh):
            for route,pointer in (('intent',reference),('participant',participant)):
                with self.subTest(route=route,task=task['task_id']):
                    with self.assertRaises(state.StateError):
                        selected.api._artifact(destination,dict(kind='fixture:fresh-wrapper',source=pointer),owner=selected.api._artifact_owner(destination,task))
        self.assertEqual(selected.api._linked_source(reference,consumer=result['verification'],require_admission=True),original)


class FactualCaptureBindingTests(unittest.TestCase):
    def fixture(self):
        from tests import test_evidence
        case=test_evidence.LinkedVerificationTests(methodName='runTest')
        case.setUp();self.addCleanup(case.doCleanups)
        return case

    def test_genuine_factual_capture_and_open_replay_have_no_publication_or_legacy_route(self):
        case=self.fixture()
        for member in case.members:
            context=evidence._evidence_context(member.scope)
            with evidence._context_database(context) as db:
                baseline=state._source_baseline(None,db,context=context)
                self.assertEqual(list(baseline['dependencies']),[])
            self.assertNotIn('verification',case.task(member)['evidence'])
            self.assertNotIn('linked_verification',case.task(member)['evidence'])
        with patch.object(evidence,'_linked_publication_plan',side_effect=AssertionError('Factual capture fabricated publication')):
            captured,originals,_=case.no_verifier_capture()
        pointer=captured['reference'];body=evidence._linked_source(pointer)
        self.assertIsNone(evidence._CONTENT_ACQUISITION.get())
        self.assertEqual(body['content']['observations']['shared'][0]['status'],'unknown')
        self.assertIsNone(body['aggregate']);self.assertIsNone(body['basis'])
        with changes._authority_guards([__import__('pathlib').Path(authority['directory']) for authority in body['authorities']]):
            self.assertEqual(evidence._linked_bound_basis(pointer,body['authorities']),captured['basis'])
            self.assertEqual(evidence._linked_stop_basis(pointer,body['authorities']),captured['basis'])
        self.assertEqual(evidence._linked_source(pointer),body)
        self.assertEqual([case.task(member) for member in case.members],originals)

    def test_factual_frame_rejects_wrappers_copied_owners_changed_value_and_expired_frame(self):
        from dataclasses import replace
        case=self.fixture();artifact=evidence._artifact;captured_owners=[];checked=[]
        def intercept(scope,value,**kwargs):
            if value.get('kind')=='linked-complete-stop' and value.get('version')==2 and value.get('basis') is None:
                owner=kwargs['owner'];captured_owners.append(owner)
                foreign=next(row['reference'] for row in value['sources'] if row['reference']['authority']!=case.reference(case.selected)['authority'])
                changed=deepcopy(value);changed['members'][0]['created_at']+=1
                attempts=[('ordinary-wrapper',dict(kind='fixture:ordinary-wrapper',source=foreign),owner.task_owner),
                    ('unbound-owner',value,evidence._LinkedOwner(owner.task_owner,owner.dependencies)),
                    ('copied-owner',value,replace(owner)),('changed-value',changed,owner),
                    ('bound-owner-other-body',dict(kind='fixture:other-body'),owner)]
                for name,payload,publisher in attempts:
                    reads=[];content=evidence._managed_content
                    def observe(context,reference,metadata):
                        if reference==foreign['reference']:reads.append(reference)
                        return content(context,reference,metadata)
                    with self.subTest(route=name),patch.object(evidence,'_managed_content',side_effect=observe):
                        with self.assertRaises(state.StateError):artifact(scope,payload,**dict(kwargs,owner=publisher))
                        self.assertEqual(reads,[],'Denied target was read during factual registration')
                    checked.append(name)
            return artifact(scope,value,**kwargs)
        with patch.object(evidence,'_artifact',side_effect=intercept):
            captured,_,_=case.no_verifier_capture()
        self.assertEqual(len(checked),5)
        body=evidence._linked_source(captured['reference']);destination=case.selected.scope
        with self.assertRaises(state.StateError):artifact(destination,body,owner=captured_owners[0])
        with evidence._current_content_acquisition(destination,case.selected.request(purpose='completion')):
            with self.assertRaises(state.StateError):artifact(destination,body,owner=evidence._artifact_owner(destination,case.task(case.selected)))
        inventory=next(row['reference'] for row in body['sources'] if row['reference']['authority']!=captured['reference']['authority'])
        reads=[];content=evidence._managed_content
        def observe(context,reference,metadata):
            if reference==inventory['reference']:reads.append(reference)
            return content(context,reference,metadata)
        with changes._authority_guards([__import__('pathlib').Path(a['directory']) for a in body['authorities']]),patch.object(evidence,'_managed_content',side_effect=observe):
            with self.assertRaises(state.StateError):evidence._linked_source(inventory,consumer=captured['reference'],require_admission=True)
        self.assertEqual(reads,[],'Factual inventory supplied prospective content permission')

    def test_factual_original_foreign_content_rechecks_current_permission_metadata_and_guards(self):
        from pathlib import Path
        from tests import test_foreign_admission
        case=self.fixture();source=test_foreign_admission.ForeignAdmissionTests.third_source(self)
        task=state.task_status(source.scope,'codex','parent')['task']
        value=dict(version=1,kind='linked-integration-observation',inputs_digest=evidence._digest(case.input_rows()),
            criteria=dict(together='unknown'),observed_at=103,reference='fixture:actual foreign unknown factual result')
        local=evidence._artifact(source.scope,value,owner=evidence._artifact_owner(source.scope,task))
        reference=dict(authority=evidence._canonical_plain(evidence._evidence_context(source.scope).authority_set[0]),reference=local)
        observations=case.observations(shared_status='unknown');observe=observations['observe']
        def actual(facts):
            result=observe(facts);result['shared'][0]['evidence']=[reference];return result
        observations['observe']=actual
        captured,_,_=case.no_verifier_capture(observations)
        pointer=captured['reference'];body=evidence._linked_source(pointer)
        self.assertEqual(evidence._source_intents(evidence._evidence_context(source.scope),local),[])
        self.assertIsNone(evidence._CONTENT_ACQUISITION.get())
        guards=[Path(a['directory']) for a in body['authorities']]
        with changes._authority_guards(guards):
            self.assertEqual(evidence._linked_source(reference,consumer=pointer,require_admission=True),value)
            self.assertEqual(evidence._linked_bound_basis(pointer,body['authorities']),captured['basis'])
        reads=[];content=evidence._managed_content
        def tracked(context,ref,metadata):
            if ref==local:reads.append(ref)
            return content(context,ref,metadata)
        with patch.object(evidence,'_managed_content',side_effect=tracked):
            with self.assertRaises(state.StateError):evidence._linked_source(reference,consumer=pointer,require_admission=True)
        self.assertEqual(reads,[],'Missing guards acquired factual target content')
        context=evidence._evidence_context(source.scope)
        with evidence._context_database(context,write=True) as db:
            metadata=state._metadata(db,local['name']);changed=deepcopy(metadata);changed['created_at']+=1
            db.execute('update evidence_metadata set created_at=?,data=? where name=?',(changed['created_at'],evidence._raw(changed).decode(),local['name']))
        try:
            with changes._authority_guards(guards),patch.object(evidence,'_managed_content',side_effect=tracked):
                with self.assertRaises(state.StateError):evidence._linked_source(reference,consumer=pointer,require_admission=True)
            self.assertEqual(reads,[],'Changed metadata acquired factual target content')
        finally:
            with evidence._context_database(context,write=True) as db:
                db.execute('update evidence_metadata set created_at=?,data=? where name=?',(metadata['created_at'],evidence._raw(metadata).decode(),local['name']))
        record=json.loads(source.scope.authority_path.read_text())
        record['repositories'][0]['checkouts'][0]['clients'][0]['activation']['status']='suspended'
        source.scope.authority_path.write_text(json.dumps(record))
        with changes._authority_guards(guards),patch.object(evidence,'_managed_content',side_effect=tracked):
            with self.assertRaisesRegex(state.StateError,'suspended'):evidence._linked_source(reference,consumer=pointer,require_admission=True)
        self.assertEqual(reads,[],'Suspended current source permission acquired factual target content')

    def test_real_source_metadata_change_at_factual_write_denies_before_target_bytes(self):
        case=self.fixture();artifact=evidence._artifact;changed=[];reads=[];content=evidence._managed_content
        def intercept(scope,value,**kwargs):
            if value.get('kind')!='linked-complete-stop' or value.get('basis') is not None:return artifact(scope,value,**kwargs)
            foreign=next(row for row in value['sources'] if row['reference']['authority']!=case.reference(case.selected)['authority'])
            pointer=foreign['reference'];context=evidence._reference_context(pointer['authority']);metadata=foreign['metadata']
            moved=deepcopy(metadata);moved['created_at']+=1
            with evidence._context_database(context,write=True) as db:
                db.execute('update evidence_metadata set created_at=?,data=? where name=?',(moved['created_at'],evidence._raw(moved).decode(),pointer['reference']['name']))
            def observe(selected,reference,actual):
                if reference==pointer['reference']:reads.append(reference)
                return content(selected,reference,actual)
            try:
                changed.append(True)
                with patch.object(evidence,'_managed_content',side_effect=observe):return artifact(scope,value,**kwargs)
            finally:
                with evidence._context_database(context,write=True) as db:
                    db.execute('update evidence_metadata set created_at=?,data=? where name=?',(metadata['created_at'],evidence._raw(metadata).decode(),pointer['reference']['name']))
        with patch.object(evidence,'_artifact',side_effect=intercept):
            with self.assertRaisesRegex(state.StateError,'exact captured observation'):case.no_verifier_capture()
        self.assertEqual(changed,[True]);self.assertEqual(reads,[])

    def test_native_bound_stop_preparation_partial_closure_and_retired_replay_preserve_unknown(self):
        from dataclasses import replace
        from pathlib import Path
        case=self.fixture();artifact=evidence._artifact;bound=[]
        def inspect(scope,value,**kwargs):
            owner=kwargs.get('owner')
            if isinstance(owner,evidence._LinkedOwner) and owner.bound_stop is not None:
                self.assertIsNone(evidence._CONTENT_ACQUISITION.get())
                for publisher,payload in ((replace(owner),value),(evidence._LinkedOwner(owner.task_owner,owner.dependencies),value),
                        (owner,dict(kind='fixture:wrong-native-bound-body'))):
                    with self.assertRaises(state.StateError):artifact(scope,payload,**dict(kwargs,owner=publisher))
                bound.append(True)
            return artifact(scope,value,**kwargs)
        with patch.object(evidence,'_artifact',side_effect=inspect):
            captured,originals,contexts,refs=case.no_verifier_stops()
        print('native bound stops complete',flush=True)
        self.assertEqual(bound,[True,True]);self.assertIsNone(evidence._BOUND_STOP_REGISTRATION.get())
        pointer=captured['reference'];original=evidence._linked_source(pointer);authorities=captured['basis']['authorities']
        prepared=evidence._prepare_linked_closure(evidence._observe_linked_preparation(pointer,authorities))
        self.assertTrue(prepared['complete'],prepared);print('native preparations complete',flush=True)
        for index,reference in enumerate(refs):
            closed=evidence.close_task(case.members[index].scope,case.linked_closure_request(index),evidence._observe_closure(contexts,reference))['task']
            self.assertEqual(closed['state'],originals[index]['state']);self.assertEqual(closed['pins'],originals[index]['pins'])
            with changes._authority_guards([Path(a['directory']) for a in authorities]):
                self.assertEqual(evidence._linked_stopped_basis(pointer,authorities),captured['basis'])
            print('native closure complete '+str(index),flush=True)
        for context,reference in zip(contexts,refs):
            self.assertTrue(evidence._retire_closed_task(context,reference)['retired'])
            with changes._authority_guards([Path(a['directory']) for a in authorities]):
                self.assertEqual(evidence._linked_stopped_basis(pointer,authorities),captured['basis'])
            print('native raw retirement complete',flush=True)
        self.assertEqual(evidence._linked_source(pointer),original)
        self.assertEqual(original['content']['observations']['shared'][0]['status'],'unknown')

    def test_native_bound_frame_denies_copies_changed_task_other_body_and_expiry(self):
        from dataclasses import replace
        case=self.fixture();captured,_,_=case.no_verifier_capture();member=case.members[1]
        artifact=evidence._artifact;retained=[];reads=[];content=evidence._managed_content
        def intercept(scope,value,**kwargs):
            owner=kwargs.get('owner')
            if isinstance(owner,evidence._LinkedOwner) and owner.bound_stop is not None:
                retained.append(owner);self.assertIsNone(evidence._CONTENT_ACQUISITION.get())
                def tracked(context,reference,metadata):
                    if reference==captured['reference']['reference']:reads.append(reference)
                    return content(context,reference,metadata)
                with patch.object(evidence,'_managed_content',side_effect=tracked):
                    for publisher,payload in ((replace(owner),value),(evidence._LinkedOwner(owner.task_owner,owner.dependencies),value),
                            (owner,dict(kind='fixture:other-bound-body'))):
                        with self.assertRaises(state.StateError):artifact(scope,payload,**dict(kwargs,owner=publisher))
                    reference=evidence._canonical_plain(owner.task_owner.task);db=kwargs['db']
                    task=evidence._linked_raw_task(db,reference);changed=deepcopy(task);changed['reason']='Changed native original owner during registration'
                    state._save(db,reference['scope_id'],changed)
                    try:
                        with self.assertRaises(state.StateError):artifact(scope,value,**kwargs)
                    finally:state._save(db,reference['scope_id'],task)
                self.assertEqual(reads,[])
            return artifact(scope,value,**kwargs)
        with patch.object(evidence,'_artifact',side_effect=intercept):
            result=state._retain_ready_stop(member.scope,case.no_verifier_stop_request(member,captured),linked_basis=captured['reference'])
        self.assertTrue(result['ok']);self.assertEqual(len(retained),1);self.assertIsNone(evidence._BOUND_STOP_REGISTRATION.get())
        with self.assertRaises(state.StateError):artifact(member.scope,captured['basis'],owner=retained[0])

    def test_native_bound_registration_rechecks_real_suspended_source_before_bytes(self):
        case=self.fixture();captured,_,_=case.no_verifier_capture();member=case.members[1]
        artifact=evidence._artifact;reads=[];changed=[];content=evidence._managed_content
        def intercept(scope,value,**kwargs):
            owner=kwargs.get('owner')
            if isinstance(owner,evidence._LinkedOwner) and owner.bound_stop is not None:
                path=case.selected.scope.authority_path;record=json.loads(path.read_text())
                record['repositories'][0]['checkouts'][0]['clients'][0]['activation']['status']='suspended'
                path.write_text(json.dumps(record));changed.append(True)
                def tracked(context,reference,metadata):
                    if reference==captured['reference']['reference']:reads.append(reference)
                    return content(context,reference,metadata)
                with patch.object(evidence,'_managed_content',side_effect=tracked):return artifact(scope,value,**kwargs)
            return artifact(scope,value,**kwargs)
        with patch.object(evidence,'_artifact',side_effect=intercept):
            with self.assertRaisesRegex(state.StateError,'suspended'):
                state._retain_ready_stop(member.scope,case.no_verifier_stop_request(member,captured),linked_basis=captured['reference'])
        self.assertEqual(changed,[True]);self.assertEqual(reads,[]);self.assertIsNone(evidence._BOUND_STOP_REGISTRATION.get())
        self.assertNotIn('writer_stop',case.task(member))


class BirthRecoveryCutTests(unittest.TestCase):
    def test_real_historical_birth_composes_origin_before_permission_and_replays(self):
        from pathlib import Path
        import tempfile
        from runtime import onboarding,review_storage
        from tests import test_onboarding_host
        from scripts.onboard_coordinator import run_verified_operation
        case=HistoricalUseActivationTests(methodName='runTest');case.setUp();self.addCleanup(case.doCleanups)
        request,_,_,task,_,_=case.historical(suspend_prior=True);fixture=case.fixture
        temporary=tempfile.TemporaryDirectory(prefix='vcw-annotated-birth-');self.addCleanup(temporary.cleanup)
        private=Path(temporary.name).resolve()
        self.enterContext(patch.object(review_storage,'_machine_config_path',return_value=private/'machine'/'machine.json'))
        self.assertTrue(review_storage.prepare_storage(private/'private')['ok'])
        record=request['manifest']['enrollment']['record'];destination=private/'born'
        record['repositories'][0]['checkouts'][0]['clients'][0]['configuration']['runtime']=dict(schema_version=3,state_dir=str(destination))
        request['approval']['manifest_digest']=onboarding._digest(request['manifest'])
        contexts=tuple(evidence._evidence_context(scope) for scope in fixture.d4_bookkeeping_scopes)
        decision=test_onboarding_host.OnboardingHostTests.decision(self,fixture,request,'apply',contexts)
        subject=next(row for row in decision['bookkeeping_scope']['subjects'] if all(row[key]==task['accepted_identity'][key]
            for key in ('project_id','repository_id','checkout_id','client')))
        subject['accepted_identity_digest']=state._digest(task['accepted_identity'])
        with review_storage._capture_birth_history(record) as (history,reobserve):
            intent=changes._birth_intent(fixture.plan(),request['manifest'],history,plan_dir=fixture.directory);reobserve()
        decision['creation']=dict(version=1,intent=intent,resume=None)
        result=run_verified_operation(decision,fixture.directory,request)
        self.assertEqual(changes._load_journal(fixture.directory)['state'],'applied',result)
        self.assertEqual(result['exit_code'],2,result);self.assertFalse(result['qualified'])
        journal=changes._load_journal(fixture.directory);context=changes._recovery_context(journal['birth']['allocation']['authority'])
        heads=case.local_heads((context,),request);head,age,body,history=heads[0]
        self.assertGreaterEqual(len(history),2);self.assertIn('use_contract',body)
        origin=body['birth_handoff']['origin_source'];self.assertIsNotNone(origin)
        self.assertIn(dict(kind='recovery',reference=origin),evidence._recovery_source_dependencies(body,origin['authority']))
        from tests import test_canonical_birth
        birth=test_canonical_birth.CanonicalBirthTests(methodName='runTest');self.addCleanup(birth.doCleanups)
        prepared=(fixture,request,decision,destination)
        replay=birth.recovery(prepared,'resume');self.assertEqual(replay['exit_code'],2,replay)
        self.assertEqual(case.local_heads((context,),request)[0][0],head)
        cut=changes._register_recovery_release(changes._observe_recovery_release(context.authority_set,body['identity']))
        self.assertTrue(cut['complete'],cut)
        current=case.local_heads((context,),request)[0]
        self.assertEqual(current[2]['version'],2);self.assertEqual(current[1],age)
        self.assertEqual(current[2]['birth_handoff'],body['birth_handoff'])
        rollback=birth.recovery(prepared,'rollback');self.assertEqual(rollback['exit_code'],0,rollback)

    def test_real_new_birth_cut_preserves_existing_peer_certificate_and_replays(self):
        from pathlib import Path
        from tests import test_canonical_birth
        fixture=test_canonical_birth.CanonicalBirthTests(methodName='runTest')
        self.addCleanup(fixture.doCleanups)
        prepared=[];calls=[];prepare=fixture.prepare;invoke=test_canonical_birth.run_verified_operation
        def capture_prepare(*args,**kwargs):
            result=prepare(*args,**kwargs);prepared.append(result);return result
        def capture_invoke(decision,path,request):
            result=invoke(decision,path,request)
            calls.append((deepcopy(decision),Path(path),deepcopy(request),result))
            return result
        with patch.object(fixture,'prepare',side_effect=capture_prepare),patch.object(test_canonical_birth,'run_verified_operation',side_effect=capture_invoke):
            fixture.test_new_destination_does_not_rebase_existing_peer_baselines()
        self.assertEqual(len(calls),2)
        f=prepared[0][0];decision,_,request,_=calls[-1]
        journal=changes._load_journal(f.directory);identity=journal['birth']['intent']['identity']
        destination=fixture.context(f)
        peer=changes._recovery_context(journal['birth']['intent']['peers'][0]['authority'])
        prior={}
        for context in (destination,peer):
            with evidence._context_database(context) as db:
                baseline=evidence._canonical_plain(state._source_baseline(None,db,context=context))
                head=next(row['reference']['artifact'] for row in baseline['dependencies'] if row['reference']['identity']==identity)
                prior[str(context.database)]=dict(baseline=baseline,head=head,body=evidence._read(None,head,context=context,db=db),
                    certificate=evidence._read_birth_handoff(context,db)['certificate'],age=state._metadata(db,head['name'])['created_at'])
        self.assertNotEqual(prior[str(destination.database)]['certificate'],prior[str(peer.database)]['certificate'])
        result=changes._register_recovery_release(changes._observe_recovery_release(destination.authority_set,identity))
        self.assertTrue(result['complete'],result)
        self.assertEqual(len(result['replacements']),2)
        for context in (destination,peer):
            original=prior[str(context.database)]
            with evidence._context_database(context) as db:
                baseline=evidence._canonical_plain(state._source_baseline(None,db,context=context))
                head=next(row['reference']['artifact'] for row in baseline['dependencies'] if row['reference']['identity']==identity)
                body=evidence._read(None,head,context=context,db=db)
                self.assertEqual(body['version'],2);self.assertIsNone(body['previous'])
                self.assertEqual(body.get('birth_handoff'),original['body'].get('birth_handoff'))
                self.assertEqual(evidence._read_birth_handoff(context,db)['certificate'],original['certificate'])
                self.assertEqual(state._metadata(db,head['name'])['created_at'],original['age'])
                self.assertEqual({key:baseline[key] for key in ('reference','content')},{key:original['baseline'][key] for key in ('reference','content')})
        replay=changes._register_recovery_release(changes._observe_recovery_release(destination.authority_set,identity))
        self.assertTrue(replay['complete'],replay);self.assertEqual(replay['replacements'],result['replacements'])
        rollback=fixture.recovery((f,request,decision,destination.directory),'rollback')
        self.assertEqual(rollback['exit_code'],0,rollback)
        for context in (destination,peer):
            with evidence._context_database(context) as db:
                self.assertEqual(evidence._read_birth_handoff(context,db)['certificate'],prior[str(context.database)]['certificate'])

    def born(self):
        from tests import test_canonical_birth
        fixture=test_canonical_birth.CanonicalBirthTests(methodName='runTest')
        self.addCleanup(fixture.doCleanups)
        prepared=fixture.prepare(history=False)
        result=fixture.invoke(prepared)
        self.assertEqual(result['exit_code'],2,result)
        f,request,decision,directory=prepared
        context=fixture.context(f)
        with evidence._context_database(context) as db:
            baseline=evidence._canonical_plain(state._source_baseline(None,db,context=context))
            head=baseline['dependencies'][0]['reference']
            body=evidence._read(None,head['artifact'],context=context,db=db)
            origin=body['birth_handoff']['origin_source']
            self.assertIsNotNone(origin)
        return fixture,prepared,context,baseline,head,body,origin

    def test_real_birth_v2_cut_keeps_origin_age_replay_and_rollback(self):
        fixture,prepared,context,baseline,head,body,origin=self.born()
        observation=changes._observe_recovery_release(context.authority_set,head['identity'])
        result=changes._register_recovery_release(observation)
        self.assertTrue(result['complete'],result)
        with evidence._context_database(context) as db:
            after=evidence._canonical_plain(state._source_baseline(None,db,context=context))
            reference=after['dependencies'][0]['reference']['artifact']
            cut=evidence._read(None,reference,context=context,db=db)
            self.assertEqual(cut['version'],2)
            self.assertIsNone(cut['previous'])
            self.assertEqual(cut['birth_handoff'],body['birth_handoff'])
            self.assertEqual(state._metadata(db,reference['name'])['created_at'],state._metadata(db,head['artifact']['name'])['created_at'])
            self.assertEqual(evidence._read_birth_handoff(context,db)['certificate'],body['birth_handoff']['certificate'])
        replay=changes._register_recovery_release(changes._observe_recovery_release(context.authority_set,head['identity']))
        self.assertEqual(replay['replacements'],result['replacements'],replay)
        self.assertTrue(replay['complete'],replay)
        rollback=fixture.recovery(prepared,'rollback')
        self.assertEqual(rollback['exit_code'],0,rollback)
        with evidence._context_database(context) as db:
            self.assertEqual(evidence._read_birth_handoff(context,db)['certificate'],body['birth_handoff']['certificate'])

    def test_origin_substitution_or_deletion_after_cut_artifact_aborts_registration(self):
        from pathlib import Path
        from runtime import review_storage
        for operation in ('replace','delete'):
            with self.subTest(operation=operation):
                fixture,prepared,context,baseline,head,body,origin=self.born()
                observation=changes._observe_recovery_release(context.authority_set,head['identity'])
                with evidence._context_database(context) as db:
                    metadata=state._metadata(db,origin['artifact']['name'])
                path=Path(metadata['managed']['path']);raw=path.read_bytes()
                before=(prepared[0].repo/'AGENTS.md').read_bytes()
                original=evidence._artifact;changed=[]
                def mutate(*args,**kwargs):
                    reference=original(*args,**kwargs)
                    value=args[1]
                    if value.get('kind')=='d4-recovery-source' and value.get('version')==2 and not changed:
                        path.rename(path.with_suffix('.held'))
                        if operation=='replace':path.write_bytes(raw);path.chmod(0o400)
                        changed.append(True)
                    return reference
                with patch.object(evidence,'_artifact',side_effect=mutate):
                    result=changes._register_recovery_release(observation)
                self.assertEqual(changed,[True],result)
                self.assertFalse(result['complete'],result)
                self.assertFalse(result['replacements'],result)
                with evidence._context_database(context) as db:
                    self.assertEqual(evidence._canonical_plain(state._source_baseline(None,db,context=context)),baseline)
                self.assertEqual((prepared[0].repo/'AGENTS.md').read_bytes(),before)
                self.assertFalse(review_storage.acquire_enrolled_accounting(prepared[0].repo)['ok'])
