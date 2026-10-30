"""Fresh D4 birth uses actual stores and fixture standing decisions, never active scopes."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime import changes, evidence, onboarding, review_storage, startup, state
from scripts.onboard_coordinator import run_verified_operation
from tests import test_onboarding_host
from tests import test_changes


class CanonicalBirthTests(unittest.TestCase):
    def prepare(self, *, umbrella=False, history=True):
        f = test_changes.ScopedChangesTests(methodName='runTest')
        f.setUp(); self.addCleanup(f.doCleanups)
        private = tempfile.TemporaryDirectory(prefix='vcw-birth-private-')
        self.addCleanup(private.cleanup)
        private_root = Path(private.name).resolve()
        lock_setting = patch.object(changes, 'LOCK_ROOT', private_root / 'locks')
        lock_setting.start(); self.addCleanup(lock_setting.stop)
        machine = private_root / 'machine' / 'machine.json'
        setting = patch.object(review_storage, '_machine_config_path', return_value=machine)
        setting.start(); self.addCleanup(setting.stop)
        if history:self.assertTrue(review_storage.prepare_storage(private_root / 'private')['ok'])
        request = f.scoped_request(umbrella=umbrella)
        if not history:self.assertTrue(review_storage.prepare_storage(private_root / 'private')['ok'])
        record = request['manifest']['enrollment']['record']
        directory = private_root / 'canonical-state'
        for repository in record['repositories']:
            for checkout in repository['checkouts']:
                for client in checkout['clients']:
                    client['configuration']['runtime'] = dict(schema_version=3, state_dir=str(directory))
        request['approval']['manifest_digest'] = onboarding._digest(request['manifest'])
        decision = test_onboarding_host.OnboardingHostTests.decision(self, f, request, 'apply', ())
        with review_storage._capture_birth_history(record) as (history, reobserve):
            reobserve()
            intent = changes._birth_intent(f.plan(), request['manifest'], history, plan_dir=f.directory)
        decision['creation'] = dict(version=1, intent=intent, resume=None)
        return f, request, decision, directory

    def test_absent_standalone_birth_is_owned_before_effects_and_stays_pending(self):
        f, request, decision, directory = self.prepare()
        result = run_verified_operation(decision, f.directory, request)
        self.assertEqual(result['exit_code'], 2, result)
        self.assertFalse(result['qualified'])
        journal = changes._load_journal(f.directory)
        self.assertEqual(journal['state'], 'applied', result)
        certificate = journal['birth']['certificate']
        context = changes._recovery_context(certificate['allocation']['authority'])
        with evidence._context_database(context) as db:
            baseline = state._source_baseline(None, db, context=context)
            self.assertEqual(baseline['content']['birth_expectation']['intent_digest'], onboarding._digest(decision['creation']['intent']))
            self.assertEqual(db.execute('select count(*) from checkouts').fetchone()[0], 1)
            self.assertEqual(db.execute('select count(*) from tasks').fetchone()[0], 0)
            self.assertEqual(evidence._read_birth_handoff(context, db)['certificate'], certificate)
        self.assertNotEqual((f.repo / 'AGENTS.md').read_text(), 'product rules\nlegacy process\n')
        accounting = review_storage.acquire_enrolled_accounting(f.repo)
        self.assertTrue(accounting['ok'], accounting)
        self.assertFalse(startup.acquire_canonical_project(type('Event', (), dict(client='codex', cwd=f.repo))(), state.PACKAGE).resolution.scope)

    def invoke(self, prepared):
        f, request, decision, directory = prepared
        return run_verified_operation(decision, f.directory, copy.deepcopy(request))

    def context(self, f):
        return changes._recovery_context(changes._load_journal(f.directory)['birth']['allocation']['authority'])

    def peer_stage(self):
        """Existing peer and intent-only grant fixture; no fresh birth is executed."""
        from tests.test_state import canonical_scope
        prepared=self.prepare(history=False);f,request,decision,directory=prepared
        legacy=startup.ProjectScope(decision['creation']['intent']['project_id'],f.repo,f.repo/'.git','policy',
            startup.RuntimeSettings(2,directory.with_name('existing-peer')))
        scope=canonical_scope(legacy);context=evidence._evidence_context(scope)
        with evidence._context_database(context) as db:baseline=startup._canonical_plain(state._source_baseline(None,db,context=context))
        peer=dict(authority=startup._canonical_plain(context.authority_set[0]),baseline=baseline)
        decision['creation']['intent']['peers']=[peer]
        decision['bookkeeping_scope']['authorities']=[peer['authority']]
        decision['operation']='resume'
        intent=decision['creation']['intent']
        decision['creation']['resume']=dict(intent_digest=onboarding._digest(intent),allocation=None,baseline=None,certificate_digest=None)
        journal=dict(birth=dict(intent=intent,directories=[],allocation=None,committed=None,certificate=None))
        return prepared,context,journal

    def test_birth_grant_requires_captured_members_and_peers_before_effects(self):
        from scripts.onboard_coordinator import CoordinatorOperationOwner
        prepared,context,journal=self.peer_stage();f,request,decision,directory=prepared
        for field in ('subjects','authorities'):
            captured=copy.deepcopy(decision);captured['bookkeeping_scope'][field]=[]
            owner=CoordinatorOperationOwner(captured)
            with changes._bootstrap_d4_host(owner,issuer=changes._D4_HOST_BOOTSTRAP_ISSUER) as host, changes._authority_guards([context.directory]):
                changes._public_entry(host,f.directory,f.plan(),request,'resume')
                with self.subTest(field=field),self.assertRaises(startup.StartupError):
                    with changes._birth_grant(host,'directories',f.directory,f.plan(),request,journal):
                        self.fail('Finite birth grant escaped captured scope')
            self.assertFalse(directory.exists())

    def test_intent_only_birth_grant_rejects_replaced_peer_before_effects(self):
        import shutil
        from scripts.onboard_coordinator import CoordinatorOperationOwner
        prepared,context,journal=self.peer_stage();f,request,decision,directory=prepared
        owner=CoordinatorOperationOwner(decision)
        with changes._bootstrap_d4_host(owner,issuer=changes._D4_HOST_BOOTSTRAP_ISSUER) as host, changes._authority_guards([context.directory]):
            changes._public_entry(host,f.directory,f.plan(),request,'resume')
            replacement=context.database.with_name('replacement.sqlite3')
            shutil.copyfile(context.database,replacement);replacement.chmod(0o600);replacement.replace(context.database)
            with self.assertRaises(startup.StartupError):
                with changes._birth_grant(host,'directories',f.directory,f.plan(),request,journal):
                    self.fail('Replaced peer reached a birth effect')
        self.assertFalse(directory.exists())

    def test_birth_origin_is_captured_as_an_actual_local_comparison_source(self):
        prepared=self.prepare(history=False);f,_,_,_=prepared
        self.assertEqual(self.invoke(prepared)['exit_code'],2)
        context=self.context(f)
        with evidence._context_database(context) as db:
            handoff=evidence._read_birth_handoff(context,db)
            head=handoff['source']['artifact'];body=evidence._read(None,head,context=context,db=db)
            origin=body['birth_handoff']['origin_source']['artifact']
            inputs=evidence._recovery_use_inputs(context,db,head,body['identity'])
            captured=[row for row in inputs['local_sources'] if row['reference']==origin]
            self.assertEqual(len(captured),1)
            self.assertEqual(captured[0]['metadata'],state._metadata(db,origin['name']))

    def test_changed_history_during_host_acquisition_cannot_publish_initial_source(self):
        from scripts.onboard_coordinator import CoordinatorOperationOwner
        from runtime import screening
        prepared=self.prepare();f,_,decision,_=prepared
        history=decision['creation']['intent']['history'];temporary=changes._recovery_context(history['machine']['configuration']['authority'])
        acquire=CoordinatorOperationOwner.acquire_d4_bookkeeping;changed=[]
        def mutate(owner,facts,issue):
            grant=acquire(owner,facts,issue)
            if facts['operation']=='protective-recovery-bookkeeping' and not changed:
                with evidence._context_database(temporary,write=True) as db:
                    reference=history['related'][0];metadata=state._metadata(db,reference['name'])
                    metadata.pop('screening_result',None);metadata['screening']=screening._fresh()
                    db.execute('update evidence_metadata set data=? where name=?',(evidence._raw(metadata).decode(),reference['name']))
                changed.append(True)
            return grant
        with patch.object(CoordinatorOperationOwner,'acquire_d4_bookkeeping',mutate):result=self.invoke(prepared)
        self.assertEqual(result['exit_code'],2,result);self.assertEqual(changed,[True])
        context=self.context(f)
        with evidence._context_database(context) as db:
            baseline=state._source_baseline(None,db,context=context)
            self.assertEqual(startup._canonical_plain(baseline['dependencies']),[])

    def recovery(self, prepared, operation):
        f, request, decision, _ = prepared
        journal = changes._load_journal(f.directory); birth=journal['birth']
        decision=copy.deepcopy(decision); decision['operation']=operation
        decision['creation']['resume']=dict(intent_digest=birth['intent_digest'], allocation=birth['allocation'],
            baseline=birth['committed']['baseline'] if birth['committed'] else None,
            certificate_digest=onboarding._digest(birth['certificate']) if birth['certificate'] else None)
        return run_verified_operation(decision,f.directory,copy.deepcopy(request))

    def test_shared_umbrella_birth_retains_real_screening_result_and_original_charge(self):
        prepared=self.prepare(umbrella=True); f,request,decision,_=prepared
        history=decision['creation']['intent']['history']
        self.assertTrue(history['related']); self.assertTrue(history['screening_sources'])
        self.assertEqual(self.invoke(prepared)['exit_code'],2)
        context=self.context(f)
        with evidence._context_database(context) as db:
            self.assertEqual(db.execute('select count(*) from checkouts').fetchone()[0],2)
        current_scope=copy.deepcopy(f.plan()['project_scope'])
        current_scope['authority']['sha256']=__import__('hashlib').sha256((Path(request['manifest']['enrollment']['record']['project_root'])/startup.PROJECT_FILE).read_bytes()).hexdigest()
        current_scope['membership']['authorization']=request['manifest']['enrollment']['record']['membership']['authorization']['reference']
        accounting=review_storage.resolve_project_owner(current_scope)
        self.assertTrue(accounting['ok'],accounting)
        self.assertEqual(len(accounting['temporary_history']['owners']),len(history['related']))
        self.assertEqual(self.recovery(prepared,'resume')['exit_code'],2)
        self.assertEqual(self.recovery(prepared,'rollback')['exit_code'],0)
        with evidence._context_database(context) as db:
            baseline=state._source_baseline(None,db,context=context)
            self.assertEqual(baseline['content']['created_at'],changes._load_journal(f.directory)['birth']['allocation']['created_at'])
            self.assertIsNotNone(evidence._read_birth_handoff(context,db))
        self.assertFalse(review_storage.reserve_screening(dict(target=str(f.repo)),0).get('admitted'))

    def test_deleting_last_original_owner_cannot_become_history_free(self):
        prepared=self.prepare(); f,_,decision,_=prepared
        self.assertEqual(self.invoke(prepared)['exit_code'],2)
        history=decision['creation']['intent']['history']; self.assertTrue(history['related'])
        temporary=changes._recovery_context(history['machine']['configuration']['authority'])
        with evidence._context_database(temporary,write=True) as db:
            for ref in history['related']:
                metadata=state._metadata(db,ref['name'])
                Path(metadata['managed']['path']).unlink()
                db.execute('delete from evidence_metadata where name=?',(ref['name'],))
        self.assertFalse(review_storage.acquire_enrolled_accounting(f.repo)['ok'])

    def test_missing_expected_source_edge_stays_protected_even_with_no_owners(self):
        prepared=self.prepare(); f,_,_,_=prepared
        self.assertEqual(self.invoke(prepared)['exit_code'],2)
        context=self.context(f)
        with evidence._context_database(context,write=True) as db:
            baseline=state._source_baseline(None,db,context=context)
            metadata=state._metadata(db,baseline['reference']['name']);metadata['dependencies']=[]
            db.execute('update evidence_metadata set data=? where name=?',(evidence._raw(metadata).decode(),baseline['reference']['name']))
        self.assertFalse(review_storage.acquire_enrolled_accounting(f.repo)['ok'])

    def test_committed_birth_crash_resumes_without_new_baseline_or_ids(self):
        prepared=self.prepare();f,_,decision,directory=prepared
        def crash(stage):
            if stage=='birth-committed':raise RuntimeError('birth crash')
        with patch.object(changes,'_checkpoint',side_effect=crash), self.assertRaises(RuntimeError):self.invoke(prepared)
        journal=changes._load_journal(f.directory); allocation=copy.deepcopy(journal['birth']['allocation'])
        context=changes._recovery_context(allocation['authority'])
        with evidence._context_database(context) as db:original=evidence._canonical_plain(state._source_baseline(None,db,context=context))
        # Independently observe completed birth for the new recovery decision.
        rows=changes._birth_seed(None,decision['creation']['intent'])
        certificate=dict(version=1,intent=decision['creation']['intent'],allocation=allocation,
            baseline={key:original[key] for key in ('reference','content')},seed_digest=onboarding._digest(rows))
        recovery=copy.deepcopy(decision);recovery['operation']='resume'
        recovery['creation']['resume']=dict(intent_digest=journal['birth']['intent_digest'],allocation=allocation,
            baseline=certificate['baseline'],certificate_digest=onboarding._digest(certificate))
        result=run_verified_operation(recovery,f.directory,prepared[1]);self.assertEqual(result['exit_code'],2,result)
        self.assertEqual(changes._load_journal(f.directory)['birth']['allocation'],allocation)

    def test_unreceipted_and_uncommitted_orphans_are_not_reinitialized(self):
        for boundary in ('birth-unreceipted','birth-before-commit'):
            with self.subTest(boundary=boundary):
                prepared=self.prepare();f,request,decision,directory=prepared
                def crash(stage):
                    if stage==boundary:raise RuntimeError('orphan')
                with patch.object(changes,'_checkpoint',side_effect=crash),self.assertRaises(RuntimeError):self.invoke(prepared)
                before={str(path):path.read_bytes() for path in directory.rglob('*') if path.is_file()}
                recovery=copy.deepcopy(decision);recovery['operation']='resume'
                journal=changes._load_journal(f.directory)
                recovery['creation']['resume']=dict(intent_digest=journal['birth']['intent_digest'],allocation=journal['birth']['allocation'],baseline=None,certificate_digest=None)
                result=run_verified_operation(recovery,f.directory,request)
                self.assertNotEqual(result['exit_code'],0,result)
                self.assertEqual(before,{str(path):path.read_bytes() for path in directory.rglob('*') if path.is_file()})
                self.assertEqual((f.repo/'AGENTS.md').read_text(),'product rules\nlegacy process\n')

    def test_birth_and_all_required_sources_precede_first_effect(self):
        prepared=self.prepare();f,_,decision,_=prepared;seen=[]
        apply=changes._scoped_apply_action
        def observed(path,journal,*args,**kwargs):
            certificate=journal['birth']['certificate'];context=changes._recovery_context(certificate['allocation']['authority'])
            with evidence._context_database(context) as db:
                self.assertIsNotNone(evidence._read_birth_handoff(context,db))
                self.assertEqual(db.execute('select count(*) from tasks').fetchone()[0],0)
            self.assertEqual(journal['birth']['phase'],'registered')
            seen.append(certificate['allocation']['created_at'])
            return apply(path,journal,*args,**kwargs)
        with patch.object(changes,'_scoped_apply_action',side_effect=observed): result=self.invoke(prepared)
        self.assertEqual(result['exit_code'],2,result);self.assertTrue(seen)

    def test_missing_machine_or_changed_history_cannot_start_birth(self):
        prepared=self.prepare();f,_,decision,directory=prepared
        original=review_storage._machine_config_path()
        original.rename(original.with_suffix('.saved'))
        result=self.invoke(prepared);self.assertNotEqual(result['exit_code'],0,result)
        self.assertFalse(directory.exists());self.assertFalse((f.directory/'transaction.json').exists())

    def test_host_and_captured_scope_refusals_leave_birth_destination_absent(self):
        prepared=self.prepare();f,request,decision,directory=prepared
        self.assertEqual(changes.apply_plan(f.directory,request)['exit_code'],2)
        self.assertFalse(directory.exists());self.assertFalse((f.directory/'transaction.json').exists())
        changed=copy.deepcopy(request);changed['approval']['reference']='untrusted:new'
        result=run_verified_operation(decision,f.directory,changed)
        self.assertNotEqual(result['exit_code'],0,result)
        self.assertFalse(directory.exists());self.assertFalse((f.directory/'transaction.json').exists())

    def test_changed_screening_charge_and_missing_origin_protect_accounting(self):
        prepared=self.prepare();f,_,decision,_=prepared
        self.assertEqual(self.invoke(prepared)['exit_code'],2)
        history=decision['creation']['intent']['history'];temporary=changes._recovery_context(history['machine']['configuration']['authority'])
        ref=history['related'][0]
        with evidence._context_database(temporary,write=True) as db:
            metadata=state._metadata(db,ref['name']);metadata.pop('screening_result',None)
            metadata['screening']=__import__('runtime.screening',fromlist=['_fresh'])._fresh()
            db.execute('update evidence_metadata set data=? where name=?',(evidence._raw(metadata).decode(),ref['name']))
        self.assertFalse(review_storage.acquire_enrolled_accounting(f.repo)['ok'])
        self.assertFalse(review_storage.reserve_screening(dict(target=str(f.repo)),0).get('admitted'))

    def test_new_destination_does_not_rebase_existing_peer_baselines(self):
        prepared=self.prepare(umbrella=True);f,request,decision,directory=prepared
        # Establish a genuine old shared authority, then propose one fresh replacement.
        self.assertEqual(self.invoke(prepared)['exit_code'],2)
        old_certificate=changes._load_journal(f.directory)['birth']['certificate']
        old_context=self.context(f)
        original_journal=f.directory/'transaction.json'
        original=f.directory;catalog=f.source.read_bytes()
        temporary=tempfile.TemporaryDirectory(prefix='vcw-birth-peer-plan-');self.addCleanup(temporary.cleanup)
        f.directory=Path(temporary.name).resolve()/'plan';f.directory.mkdir(mode=0o700)
        f.source=f.directory/'catalog.md';f.source.write_bytes(catalog);f.source.chmod(0o600)
        f.record['toolkit']['files'][0]['local_path']=str(f.source)
        record=request['manifest']['enrollment']['record'];members=[Path(repo['checkouts'][0]['root']) for repo in record['repositories']]
        onboarding.inspect_project(f.base,f.directory,f.project_record(f.base,members,'umbrella',['AGENTS.md']))
        onboarding.record_plan(f.directory,f.scoped_proposal())
        update=f.scoped_request(prepared=True);update['manifest']['transaction_id']='fresh-with-peer'
        new_directory=directory.parent/'replacement'
        for index,repo in enumerate(update['manifest']['enrollment']['record']['repositories']):
            client=repo['checkouts'][0]['clients'][0]
            client['configuration']['runtime']=dict(schema_version=3,state_dir=str(directory if index==0 else new_directory))
            client['activation']['transaction_id']='fresh-with-peer'
        update['approval']['manifest_digest']=onboarding._digest(update['manifest'])
        new_decision=test_onboarding_host.OnboardingHostTests.decision(self,f,update,'apply',(old_context,))
        with review_storage._capture_birth_history(update['manifest']['enrollment']['record']) as (history,reobserve):
            intent=changes._birth_intent(f.plan(),update['manifest'],history,plan_dir=f.directory);reobserve()
        new_decision['creation']=dict(version=1,intent=intent,resume=None)
        result=run_verified_operation(new_decision,f.directory,update)
        self.assertEqual(result['exit_code'],2,result)
        journal=changes._load_journal(f.directory);self.assertEqual(journal['state'],'applied',result)
        new_context=changes._recovery_context(journal['birth']['allocation']['authority'])
        with evidence._context_database(new_context) as db:
            self.assertEqual(evidence._read_birth_handoff(new_context,db)['certificate'],journal['birth']['certificate'])
        with evidence._context_database(old_context) as db:
            retained=evidence._read_birth_handoff(old_context,db)
            self.assertEqual(retained['certificate'],old_certificate)
            baseline=state._source_baseline(None,db,context=old_context)
            edge=next(row for row in baseline['dependencies'] if row['reference']['identity']['transaction_id']=='fresh-with-peer')
            raw=evidence._read(None,evidence._canonical_plain(edge['reference']['artifact']),context=old_context,db=db)
            self.assertNotIn('birth_handoff',raw)
        self.assertTrue(original_journal.exists())

    def test_copied_and_expired_host_cannot_allocate(self):
        prepared=self.prepare();f,request,decision,directory=prepared
        from scripts.onboard_coordinator import CoordinatorOperationOwner
        owner=CoordinatorOperationOwner(decision)
        with changes._bootstrap_d4_host(owner,issuer=changes._D4_HOST_BOOTSTRAP_ISSUER) as host:
            before={str(path):path.read_bytes() for path in f.directory.rglob('*') if path.is_file()}
            result=changes.apply_plan(f.directory,request,host=copy.copy(host))
            self.assertEqual(result['exit_code'],2,result);self.assertFalse(directory.exists())
            self.assertEqual(before,{str(path):path.read_bytes() for path in f.directory.rglob('*') if path.is_file()})
        self.assertEqual(changes.apply_plan(f.directory,request,host=host)['exit_code'],2)
        self.assertFalse(directory.exists())

    def test_lost_origin_or_changed_certificate_cannot_satisfy_expectation(self):
        prepared=self.prepare();f,_,_,_=prepared
        self.assertEqual(self.invoke(prepared)['exit_code'],2)
        context=self.context(f)
        with evidence._context_database(context) as db:
            handoff=evidence._read_birth_handoff(context,db)
            _,raw=evidence._managed_artifact(None,handoff['source']['artifact'],context=context,db=db)
            body=__import__('json').loads(raw)
            origin=body['birth_handoff']['origin_source']
            self.assertIsNotNone(origin)
            metadata=state._metadata(db,origin['artifact']['name'])
        Path(metadata['managed']['path']).unlink()
        self.assertFalse(review_storage.acquire_enrolled_accounting(f.repo)['ok'])

    def test_new_history_free_birth_requires_its_expected_empty_certificate(self):
        prepared=self.prepare(history=False);f,_,decision,_=prepared
        self.assertEqual(decision['creation']['intent']['history']['related'],[])
        result=self.invoke(prepared);self.assertEqual(result['exit_code'],2,result)
        self.assertTrue(review_storage.acquire_enrolled_accounting(f.repo)['ok'])
        context=self.context(f)
        with evidence._context_database(context,write=True) as db:
            baseline=state._source_baseline(None,db,context=context)
            self.assertIn('birth_expectation',baseline['content'])
            metadata=state._metadata(db,baseline['reference']['name']);metadata['dependencies']=[]
            db.execute('update evidence_metadata set data=? where name=?',(evidence._raw(metadata).decode(),baseline['reference']['name']))
        self.assertFalse(review_storage.acquire_enrolled_accounting(f.repo)['ok'])

    def test_unknown_existing_database_cannot_be_reclassified_as_birth(self):
        prepared=self.prepare();f,_,_,directory=prepared
        directory.mkdir(mode=0o700);(directory/'runtime.sqlite3').write_bytes(b'')
        result=self.invoke(prepared);self.assertNotEqual(result['exit_code'],0,result)
        self.assertFalse((f.directory/'transaction.json').exists())
        self.assertEqual((directory/'runtime.sqlite3').read_bytes(),b'')

    def test_journal_appearing_before_first_birth_grant_is_preserved(self):
        prepared=self.prepare();f,_,_,directory=prepared
        actual=changes._birth_grant;injected=[]
        foreign=b'foreign private journal\n'
        def race(host,stage,path,plan,request,journal,**kwargs):
            if stage=='directories' and not injected:
                target=path/'transaction.json';target.write_bytes(foreign);target.chmod(0o600);injected.append(target)
            return actual(host,stage,path,plan,request,journal,**kwargs)
        with patch.object(changes,'_birth_grant',side_effect=race):result=self.invoke(prepared)
        self.assertNotEqual(result['exit_code'],0,result)
        self.assertEqual(injected[0].read_bytes(),foreign)
        self.assertFalse(directory.exists())

    def test_missing_machine_after_birth_cannot_return_resolved_accounting(self):
        prepared=self.prepare();f,_,_,_=prepared
        self.assertEqual(self.invoke(prepared)['exit_code'],2)
        report=review_storage.acquire_enrolled_accounting(f.repo)
        self.assertTrue(report['ok'],report)
        self.assertIn('handoff',report['temporary_history'])
        review_storage._machine_config_path().unlink()
        self.assertFalse(review_storage.acquire_enrolled_accounting(f.repo)['ok'])

    def test_extra_structurally_valid_related_owner_cannot_expand_retained_set(self):
        prepared=self.prepare();f,_,decision,_=prepared
        self.assertEqual(self.invoke(prepared)['exit_code'],2)
        history=decision['creation']['intent']['history'];temporary=changes._recovery_context(history['machine']['configuration']['authority'])
        reference=history['related'][0]
        with evidence._context_database(temporary,write=True) as db:
            metadata,raw=evidence._managed_artifact(None,reference,context=temporary,db=db)
            altered=copy.deepcopy(metadata);name=__import__('uuid').uuid4().hex+'.json'
            location=temporary.directory/'evidence'/name;location.write_bytes(raw);location.chmod(0o400)
            altered['managed'].update(path=str(location),binding=evidence._binding(location))
            row=(name,reference['digest'],'temporary:'+altered['owner']['id'],altered['class'],altered['created_at'],
                altered['closed_at'],altered['status'],altered['bytes'],evidence._raw(altered).decode())
            state._metadata_record(row);db.execute('insert into evidence_metadata values(?,?,?,?,?,?,?,?,?)',row)
        self.assertFalse(review_storage.acquire_enrolled_accounting(f.repo)['ok'])
        self.assertFalse(review_storage.reserve_screening(dict(target=str(f.repo)),0).get('admitted'))
        with evidence._context_database(temporary) as db:
            self.assertEqual(state._metadata(db,reference['name']),metadata)

    def test_claimed_native_qualification_cannot_activate_a_fresh_birth(self):
        prepared=self.prepare();f,request,decision,directory=prepared
        record=request['manifest']['enrollment']['record'];repo=record['repositories'][0];checkout=repo['checkouts'][0];client=checkout['clients'][0]
        identity=onboarding._digest(startup._canonical_plain(startup.canonical_scope_projection(startup.decode_project_record(record),
            repository_id=repo['repository_id'],checkout_id=checkout['checkout_id'],client='codex')))
        ref=dict(reference='fixture:unobserved-claim',sha256='e'*64);source=state.PACKAGE/'hooks/codex.json'
        binding=dict(client='codex',surface='unobserved-fixture',version='unobserved',configuration_digest='f'*64,
            hook_owner=dict(root=str(state.PACKAGE),binding=evidence._binding(state.PACKAGE),source=str(source),
                sha256=__import__('hashlib').sha256(source.read_bytes()).hexdigest()),accepted_scope_digest=identity,receipt=ref)
        client['activation'].update(status='active',qualification='qualified',accepted_scope_digest=identity,
            transaction_id=request['manifest']['transaction_id'],evidence=[ref],qualification_binding=binding)
        request['approval']['manifest_digest']=onboarding._digest(request['manifest'])
        captured=test_onboarding_host.OnboardingHostTests.decision(self,f,request,'apply',())
        with review_storage._capture_birth_history(record) as (history,reobserve):
            intent=changes._birth_intent(f.plan(),request['manifest'],history,plan_dir=f.directory);reobserve()
        captured['creation']=dict(version=1,intent=intent,resume=None)
        result=run_verified_operation(captured,f.directory,request)
        self.assertEqual(result['exit_code'],2,result);self.assertFalse(result['qualified'])
        self.assertTrue(any('configured enrollment only' in row['reason'] for row in result['blocked']),result)
        self.assertFalse(directory.exists());self.assertFalse((f.directory/'transaction.json').exists())

    def test_copied_machine_context_cannot_revive_after_descriptor_reuse(self):
        import contextvars
        import os
        prepared=self.prepare();_,request,_,_=prepared
        with review_storage._machine_guard() as (_,descriptor,_):
            copied=contextvars.copy_context();original_descriptor=descriptor
        opened=os.open(review_storage._machine_config_path().parent,os.O_RDONLY|os.O_DIRECTORY)
        try:
            if opened!=original_descriptor:os.dup2(opened,original_descriptor)
            def stale():
                with review_storage._capture_birth_history(request['manifest']['enrollment']['record']):pass
            with self.assertRaises(state.StateError):copied.run(stale)
        finally:
            if opened!=original_descriptor:os.close(original_descriptor)
            os.close(opened)
