"""Source-only settlement is explicit; fake CLI execution is not client qualification."""

import copy
import hashlib
import json
import os
import sys
import time
import unittest
from unittest.mock import patch

from runtime import changes, setup_observation as source, startup
from runtime.adapters import codex
from scripts.onboard_coordinator import CoordinatorOperationOwner
from tests import test_native_bootstrap as bootstrap


class NativeSourceReconciliationTests(unittest.TestCase):
    def observe(self, *, limited=True, failed=False):
        fixture,identity,reference,home,old=bootstrap.NativeBootstrapTests.owner(self)
        executable=home/'fake-native'
        executable.write_text(f'#!{sys.executable}\nimport json\nprint(json.dumps(dict(type="thread.started",thread_id="fixture-thread")),flush=True)\n')
        executable.chmod(0o700)
        decision=startup._canonical_plain(old._decision)
        attempt=decision['qualification_scope']['attempts'][0]
        attempt['native_execution']['argv']=[str(executable),'exec','--json']
        if limited:attempt['native_execution']['source_contract']='bounded-native-source-v1'
        owner=CoordinatorOperationOwner(decision)
        def observer(process,admission):
            result=codex.observe_cli_basic(process,admission)
            if failed:raise startup.StartupError('fixture failed observation')
            return result
        with patch.dict(os.environ,CODEX_HOME=str(home)):
            if failed:
                with self.assertRaises(changes.Pending):owner.observe_native_source(identity,reference,observer)
            else:owner.observe_native_source(identity,reference,observer)
        row=changes._load_journal(fixture.directory)['native_observations'][startup._canonical_digest(reference)]
        return fixture,reference,owner,row,source._native_reference(fixture.directory,row)

    def proof(self,row):
        return dict(claim_id=row['claim_id'],pid=row['pid'],returncode=row['returncode'],stopped=True,reaped=True,
            process_evidence=dict(reference='fixture:independently-observed-original-reap',sha256='c'*64),
            writer_assessment_evidence=dict(reference='fixture:independent-writer-effect-assessment',sha256='d'*64),
            identified_writers_reconciled=True,pending_workflow_hooks=False,unexpected_tool_or_spawn=False,
            unexplained_project_effects=False,ownership_conflicts=False)

    def test_limited_source_can_be_read_with_unknown_background_closure_and_visible_risk(self):
        fixture,reference,owner,row,claim=self.observe()
        self.assertIn('source_contract',row)
        self.assertIn('unknown',json.dumps(row['source_contract']))
        self.assertIn('late',json.dumps(row['source_contract']))
        self.assertEqual(claim,startup._canonical_plain(owner.reconcile_native_source(reference,claim,self.proof(row))))
        retained,_,_=source._read_native_reference(claim,source._budget())
        self.assertEqual(retained['source_contract'],row['source_contract'])
        self.assertNotIn('descendants_stopped',retained['reconciliation'])
        self.assertIsNone(changes._command_owner(row['identity']['git_dir']))

    def test_live_unknown_direct_process_and_duplicate_evidence_do_not_release_claim(self):
        fixture,reference,owner,row,claim=self.observe()
        for field,value in [('stopped',False),('reaped',False),('pid',None),('returncode',None),('returncode',False),
                ('writer_assessment_evidence',self.proof(row)['process_evidence'])]:
            proof=self.proof(row);proof[field]=value
            with self.subTest(field=field),self.assertRaises(startup.StartupError):owner.reconcile_native_source(reference,claim,proof)
        self.assertIsNotNone(changes._command_owner(row['identity']['git_dir']))

    def test_identified_uncertain_writers_hooks_conflicts_and_unexpected_effects_block(self):
        fixture,reference,owner,row,claim=self.observe()
        for field,value in [('identified_writers_reconciled',False),('pending_workflow_hooks',True),
                ('unexpected_tool_or_spawn',True),('unexplained_project_effects',True),('ownership_conflicts',True),
                ('descendants_stopped',True)]:
            proof=self.proof(row);proof[field]=value
            with self.subTest(field=field),self.assertRaises(startup.StartupError):owner.reconcile_native_source(reference,claim,proof)
        self.assertIsNotNone(changes._command_owner(row['identity']['git_dir']))

    def test_copied_claim_pid_proof_and_changed_reference_are_rejected_by_owner_and_reader(self):
        fixture,reference,owner,row,claim=self.observe()
        for field,value in [('claim_id','another-claim'),('pid',row['pid']+1),('returncode',row['returncode']+1)]:
            proof=self.proof(row);proof[field]=value
            with self.subTest(field=field),self.assertRaises(startup.StartupError):owner.reconcile_native_source(reference,claim,proof)
        owner.reconcile_native_source(reference,claim,self.proof(row))
        journal=changes._load_journal(fixture.directory)
        journal['native_observations'][startup._canonical_digest(reference)]['reconciliation']['pid']+=1
        changes._save(fixture.directory,journal)
        with self.assertRaises(startup.StartupError):source._read_native_reference(claim,source._budget())

    def test_source_settlement_never_clears_another_known_writer_claim(self):
        fixture,reference,owner,row,claim=self.observe()
        marker=dict(schema_version=1,plan_dir=str(fixture.directory),transaction_id='another-writer',id='known-writer',attempt_id='still-uncertain')
        location=changes._owner_path(row['identity']['git_dir'])
        changes._atomic(location.parent,location.name,json.dumps(marker,sort_keys=True).encode())
        with self.assertRaises(startup.StartupError):owner.reconcile_native_source(reference,claim,self.proof(row))
        self.assertEqual(changes._command_owner(row['identity']['git_dir']),marker)
        self.assertFalse(changes._load_journal(fixture.directory)['native_observations'][startup._canonical_digest(reference)]['stopped'])

    def test_expiry_and_failure_do_not_create_replay_or_usable_failed_source(self):
        fixture,reference,owner,row,claim=self.observe(failed=True)
        with patch('time.time',return_value=time.time()+60):owner.reconcile_native_source(reference,claim,self.proof(row))
        self.assertEqual(changes._load_journal(fixture.directory)['native_observations'][startup._canonical_digest(reference)]['status'],'failed')
        with self.assertRaises(startup.StartupError):source._read_native_reference(claim,source._budget())
        with self.assertRaises(startup.StartupError):owner.observe_native_source(row['identity'],reference,lambda p,a:None)

    def test_legacy_hash_and_full_stop_proof_stay_compatible_without_limited_downgrade(self):
        fixture,reference,owner,row,claim=self.observe(limited=False)
        body={key:row[key] for key in ('claim_id','attempt_ref','identity','allocation_digest','result')}
        self.assertEqual(claim['sha256'],hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest())
        with self.assertRaises(startup.StartupError):owner.reconcile_native_source(reference,claim,self.proof(row))
        proof=dict(claim_id=row['claim_id'],pid=row['pid'],returncode=row['returncode'],stopped=True,descendants_stopped=True,
            evidence=[self.proof(row)['process_evidence'],self.proof(row)['writer_assessment_evidence']])
        owner.reconcile_native_source(reference,claim,proof)
        self.assertNotIn('source_contract',source._read_native_reference(claim,source._budget())[0])

    def test_limited_contract_is_bound_to_original_allocation_and_all_fact_hashes(self):
        fixture,reference,owner,row,claim=self.observe()
        for part in (None,'before','after','context'):
            candidate=copy.deepcopy(row)
            if part is not None:candidate[part]={'fixture':'observed fact'}
            bound=source._native_reference(fixture.directory,candidate,part)
            candidate.pop('source_contract')
            self.assertNotEqual(bound,source._native_reference(fixture.directory,candidate,part))
        journal=changes._load_journal(fixture.directory)
        journal['qualification_scope']['attempts'][0]['native_execution'].pop('source_contract')
        changes._save(fixture.directory,journal)
        with self.assertRaises(startup.StartupError):source._read_native_reference(claim,source._budget())

    def test_source_proof_does_not_satisfy_managed_command_reconciliation(self):
        fixture,reference,owner,row,claim=self.observe()
        owner.reconcile_native_source(reference,claim,self.proof(row))
        journal=changes._load_journal(fixture.directory)
        with self.assertRaises(startup.StartupError):
            source._stopped_source(journal,dict(transaction_id=journal['transaction_id'],action_id='unreconciled-command',attempt_id=row['claim_id']))


if __name__=='__main__':unittest.main()
