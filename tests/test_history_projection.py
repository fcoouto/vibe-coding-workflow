"""Closed-gate candidate comparisons; literal graphs do not authenticate stored history."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from runtime import changes, evidence, recovery_uses as uses, state
from tests import test_recovery_uses as graph
from tests import test_changes as fixtures

A = graph.AUTHORITY
TASK = graph.TASK
PROOF = dict(authority=A, artifact=graph.ARTIFACT)
ROOT = dict(purpose='historical-stop', reference=dict(kind='task', reference=TASK), task=TASK,
    proof=PROOF, effect=dict(action_id='change', path='AGENTS.md'))
IDENTITY = dict(plan_dir='/plan', transaction_id='transaction', manifest_digest='d'*64)
HEAD = dict(name='e'*32+'.json', digest='f'*64)
CHILD = dict(authority=A, artifact=dict(name='1'*32+'.json', digest='2'*64))


class HistoryProjectionTests(unittest.TestCase):
    def inputs(self):
        task_edge = dict(kind='task', reference=TASK)
        content_root = dict(purpose='content', reference=task_edge)
        program = uses.build([ROOT, content_root], [dict(root=0,parent=None,dependency=task_edge,purpose='retention-only'),
            dict(root=1,parent=None,dependency=task_edge,purpose='content')])
        template = dict(version=1,kind='d4-recovery-source',identity=IDENTITY,
            journal=dict(sha256='3'*64,observed_at=20,state='applied'),authorities=[A],
            tasks=[dict(reference=TASK,revision=2,pins={},turn_id=None)],assignments=[],artifacts=[],previous=None,use_contract=program)
        prior = dict(version=1,kind='d4-recovery-source',identity=IDENTITY,
            journal=dict(sha256='4'*64,observed_at=10,state='prepared'),authorities=[A],tasks=[],assignments=[],artifacts=[CHILD],previous=None)
        head_pointer = dict(authority=A,artifact=HEAD)
        dependencies = [dict(kind='artifact',reference=CHILD)]
        return dict(authority=A,identity=IDENTITY,reference=HEAD,template=template,
            baseline=dict(content=dict(project_id='project'),dependencies=[dict(kind='recovery',reference=dict(identity=IDENTITY,artifact=HEAD))]),
            history=[dict(reference=HEAD,content=prior,metadata=dict(created_at=7,**{'class':'compact'},
                dependencies=dependencies,owner=dict(kind='project',project_id='project',task=None)))],
            metadata={},history_metadata={uses.key(head_pointer):dependencies,uses.key(CHILD):[]},
            anchors=[dict(root=ROOT,support=[task_edge,dict(kind='artifact',reference=PROOF)])],jobs=[])

    def project(self, inputs=None):
        self.assertTrue(callable(getattr(uses,'project_history',None)), 'history-aware projection is missing')
        return uses.project_history(self.inputs() if inputs is None else inputs, 7, uses.CaptureBudget())

    def test_previous_is_nested_without_new_direct_raw_demands(self):
        result = self.project()
        self.assertTrue(result['comparison_only'])
        self.assertEqual(result['content']['previous'], HEAD)
        self.assertEqual(result['content']['artifacts'], [])
        self.assertEqual(len(result['dependencies']), 2)
        rows = result['content']['use_contract']['edges']
        self.assertTrue(any(row['parent']==dict(authority=A,artifact=HEAD) and row['dependency']==dict(kind='artifact',reference=CHILD) for row in rows))
        self.assertFalse(any(row['parent'] is None and row['dependency']==dict(kind='artifact',reference=CHILD) for row in rows))
        self.assertEqual({row['purpose'] for row in rows if row['parent'] is None and row['dependency']==dict(kind='task',reference=TASK)}, {'content','retention-only'})
        self.assertTrue(any(row['dependency']==dict(kind='artifact',reference=CHILD) and row['requirement']=='current-permission' for row in result['obligations']))

    def test_candidate_exactness_and_every_parent_are_checked(self):
        original = self.inputs()
        for change in ('head','identity','authority','empty-parent','extra-parent','cycle','anchor','age'):
            value = deepcopy(original)
            if change=='head':value['reference']=dict(name='5'*32+'.json',digest='6'*64)
            elif change=='identity':value['identity']=dict(value['identity'],transaction_id='other')
            elif change=='authority':value['authority']['directory_binding']['inode']+=1
            elif change=='empty-parent':del value['history_metadata'][uses.key(CHILD)]
            elif change=='extra-parent':value['history_metadata'][uses.key(PROOF)]=[]
            elif change=='cycle':value['history_metadata'][uses.key(CHILD)]=[dict(kind='recovery',reference=dict(authority=A,artifact=HEAD))]
            elif change=='anchor':value['anchors'][0]['root']['effect']['path']='other'
            else:value['history'][0]['metadata']['created_at']=8
            with self.subTest(change=change),self.assertRaises(uses.UseContractError):self.project(value)

    def test_checker_rejects_changed_rows_and_keeps_payload_aliases(self):
        value = self.inputs(); result = self.project(value)
        self.assertTrue(callable(getattr(uses,'check_history_coverage',None)), 'history coverage checker is missing')
        for change in ('remove-history','upgrade-history','remove-content','wrong-previous'):
            body = deepcopy(result['content'])
            rows=body['use_contract']['edges']
            if change=='remove-history':rows[:]=[row for row in rows if row['parent'] is None]
            elif change=='upgrade-history':next(row for row in rows if row['parent'] is not None)['purpose']='content'
            elif change=='remove-content':rows[:]=[row for row in rows if row['purpose']!='content']
            else:body['previous']=None
            with self.subTest(change=change),self.assertRaises(uses.UseContractError):uses.check_history_coverage(body,7,value,uses.CaptureBudget())

    def test_replay_rederives_whole_body_and_new_head_preserves_age(self):
        value = self.inputs(); first=self.project(value)
        value['history'].insert(0,dict(reference=dict(name='5'*32+'.json',digest='6'*64),content=deepcopy(first['content']),
            metadata=dict(created_at=7,**{'class':'compact'},dependencies=first['dependencies'],owner=dict(kind='project',project_id='project',task=None))))
        value['reference']=dict(name='5'*32+'.json',digest='6'*64)
        value['baseline']['dependencies'][0]['reference']['artifact']=value['reference']
        value['history_metadata'][uses.key(dict(authority=A,artifact=value['reference']))]=first['dependencies']
        repeated=self.project(value)
        self.assertEqual(repeated['reference'],value['reference'])
        self.assertEqual(repeated['content'],first['content'])
        value['template']['journal']['state']='blocked'
        newer=self.project(value)
        self.assertIsNone(newer['reference'])
        self.assertEqual(newer['content']['previous'],value['reference'])
        self.assertEqual(newer['created_at'],7)

    def test_pending_jobs_and_shared_capture_budget_never_issue_permission(self):
        value=self.inputs();value['jobs']=[dict(kind='managed-source',reference=CHILD)]
        result=self.project(value)
        self.assertIsNone(result['content']);self.assertEqual(result['pending_jobs'],value['jobs'])
        self.assertTrue(result['comparison_only'])
        budget=uses.CaptureBudget(parents=1,edges=2,jobs=1,bytes=20)
        budget.take(parents=1,edges=1,bytes=10)
        with self.assertRaises(uses.UseContractError):budget.take(parents=1)
        with self.assertRaises(uses.UseContractError):budget.take(edges=2)
        with self.assertRaises(uses.UseContractError):budget.take(bytes=11)
        with self.assertRaises(uses.UseContractError):budget.take(jobs=2)
        with self.assertRaises(uses.UseContractError):uses.CaptureBudget(bytes=uses.MAX_BYTES+1)

    def test_same_parent_needs_both_payload_and_history_occurrences(self):
        value=self.inputs();program=value['template']['use_contract']
        index=next(i for i,root in enumerate(program['roots']) if root['purpose']=='content')
        edge=dict(kind='artifact',reference=CHILD)
        program['edges'].append(dict(root=index,parent=None,dependency=edge,purpose='content'))
        value['template']['use_contract']=uses.build(program['roots'],program['edges'])
        value['template']['artifacts']=[CHILD];value['metadata']={uses.key(CHILD):[]}
        result=self.project(value)
        rows=result['content']['use_contract']['edges']
        self.assertTrue(any(row['dependency']==edge and row['purpose']=='content' for row in rows))
        self.assertTrue(any(row['dependency']==edge and row['purpose']=='retention-only' for row in rows))
        for field in ('metadata','history_metadata'):
            damaged=deepcopy(value);del damaged[field][uses.key(CHILD)]
            with self.subTest(field=field),self.assertRaises(uses.UseContractError):self.project(damaged)

    def test_cut_drops_only_history_and_keeps_current_content_raw_demand(self):
        value=self.inputs();value['template'].update(version=2,stopped=[],supersedes=[])
        result=self.project(value)
        self.assertIsNone(result['content']['previous'])
        self.assertEqual(result['dependencies'],[dict(kind='task',reference=TASK)])
        self.assertEqual(result['content']['tasks'],value['template']['tasks'])
        self.assertTrue(all(row['parent'] is None for row in result['content']['use_contract']['edges']))
        self.assertTrue(result['content']['use_contract']['legacy_routes'])

    def test_deep_typed_children_and_each_store_head_remain_distinct(self):
        value=self.inputs()
        other=dict(TASK,task_id='other')
        value['history_metadata'][uses.key(CHILD)]=[dict(kind='task',reference=other)]
        result=self.project(value)
        self.assertTrue(any(row['dependency']==dict(kind='task',reference=other) and row['requirement']=='current-permission' for row in result['obligations']))
        peer=deepcopy(value);authority=deepcopy(A);authority['directory_binding']['inode']+=10
        peer['authority']=authority;peer['template']['authorities'].append(authority)
        peer_head=dict(name='7'*32+'.json',digest='8'*64)
        peer['reference']=peer_head;peer['baseline']['dependencies'][0]['reference']['artifact']=peer_head
        peer['history'][0]['reference']=peer_head
        peer['history'][0]['content']['authorities'].append(authority)
        deps=peer['history_metadata'].pop(uses.key(dict(authority=A,artifact=HEAD)))
        peer['history_metadata'][uses.key(dict(authority=authority,artifact=peer_head))]=deps
        projected=self.project(peer)
        self.assertEqual(projected['content']['previous'],peer_head)
        self.assertEqual(result['content']['previous'],HEAD)
        self.assertEqual(projected['created_at'],result['created_at'])

    def test_checker_cannot_reset_an_exhausted_shared_budget(self):
        value=self.inputs();budget=uses.CaptureBudget()
        candidate=uses.project_history(value,7,budget)['content']
        before=dict(budget.used)
        uses.check_history_coverage(candidate,7,value,budget)
        self.assertGreater(budget.used['bytes'],before['bytes'])
        budget.take(bytes=budget.limits['bytes']-budget.used['bytes'])
        with self.assertRaises(uses.UseContractError):uses.check_history_coverage(candidate,7,value,budget)
        with self.assertRaises(TypeError):uses.check_history_coverage(candidate,7,value)

    def test_empty_budget_stops_legacy_projection_before_materialization(self):
        value=self.inputs();budget=uses.CaptureBudget(bytes=0)
        with patch.object(uses,'legacy_projection',side_effect=AssertionError('legacy projection materialized before budget')):
            with self.assertRaises(uses.UseContractError):uses.project_history(value,7,budget)

    def test_merged_legacy_origin_limit_precedes_route_copy_and_contract_build(self):
        value=self.inputs()
        def routes(start):
            return [dict(origin=dict(authority=dict(A,directory='/s',database='/s/runtime.sqlite3'),artifact=dict(name=format(i,'032x')+'.json',digest=format(i,'064x')),
                identity=dict(IDENTITY,plan_dir='/p',transaction_id='t'),journal_sha256=format(i,'064x')),destinations=[]) for i in range(start,start+2)]
        older=value['history'][0]
        older['content']['use_contract']=uses.build([],[],routes(1))
        newer=deepcopy(older);newer['reference']=dict(name='9'*32+'.json',digest='a'*64)
        newer['content']['previous']=HEAD;newer['content']['use_contract']=uses.build([],[],routes(3))
        newer['metadata']['dependencies'].append(dict(kind='recovery',reference=dict(authority=A,artifact=HEAD)))
        value['history'].insert(0,newer);value['reference']=newer['reference']
        value['baseline']['dependencies'][0]['reference']['artifact']=newer['reference']
        value['history_metadata'][uses.key(dict(authority=A,artifact=newer['reference']))]=newer['metadata']['dependencies']
        original=uses.deepcopy;copies=[]
        def copy(item):
            if type(item) is dict and set(item)=={'origin','destinations'}:
                copies.append(item['origin'])
                if len(copies)>3:raise AssertionError('over-count route copied')
            return original(item)
        budget=uses.CaptureBudget()
        # Scale the independent count limit while every source/graph stays individually valid.
        with patch.object(uses,'MAX_ROWS',3),patch.object(uses,'deepcopy',side_effect=copy),patch.object(uses,'build',side_effect=AssertionError('late merged contract build')):
            with self.assertRaisesRegex(uses.UseContractError,'legacy origin bound'):
                uses.project_history(value,7,budget)
        self.assertEqual(len(copies),3)


class ActualHistoryCaptureTests(unittest.TestCase):
    def test_actual_old_heads_use_supplied_connection_and_shared_budget(self):
        self.assertTrue(callable(getattr(evidence,'_recovery_history_inputs',None)), 'bounded local capture is missing')
        fixture=fixtures.ScopedChangesTests(methodName='runTest');fixture.setUp();self.addCleanup(fixture.doCleanups)
        request,contexts=fixture.d4_bookkeeping_request(umbrella=True)
        observed=[];original=changes._observe_recovery_source
        def observe(*args,**kwargs):
            result=original(*args,**kwargs);observed.append(result);return result
        with patch.object(changes,'_observe_recovery_source',side_effect=observe):
            self.assertEqual(fixture.run_with_d4_host(request,'apply')['exit_code'],0)
        source=observed[-1];context=source.contexts[0]
        with evidence._context_database(context) as db:
            baseline=state._source_baseline(None,db,context=context)
            head=next(edge['reference']['artifact'] for edge in baseline['dependencies'] if edge['reference']['identity']==evidence._canonical_plain(source.content['identity']))
            budget=uses.CaptureBudget()
            with patch.object(evidence.sqlite3,'connect',side_effect=AssertionError('capture opened another database')):
                captured=evidence._recovery_history_inputs(context,db,head,source,request['manifest'],budget)
            self.assertEqual(captured['reference'],head)
            self.assertGreaterEqual(len(captured['history']),2)
            self.assertIn(uses.key(dict(authority=captured['authority'],artifact=evidence._canonical_plain(head))),captured['history_metadata'])
            self.assertGreater(budget.used['parents'],0)
            parents=budget.used['parents']
            exhausted=uses.CaptureBudget(parents=parents)
            evidence._recovery_history_inputs(context,db,head,source,request['manifest'],exhausted)
            with self.assertRaises(uses.UseContractError):evidence._recovery_history_inputs(context,db,head,source,request['manifest'],exhausted)
            self.assertEqual(evidence._canonical_plain(state._source_baseline(None,db,context=context)),evidence._canonical_plain(baseline))
            with self.assertRaises(uses.UseContractError):
                evidence._recovery_history_inputs(context,db,graph.ARTIFACT,source,request['manifest'],budget)
