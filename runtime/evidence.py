"""Bounded D5 evidence: private immutable artifacts, actual inputs and native receipts.

Coordinator decisions describe semantic coverage and existing authorization. They do
not authenticate review execution or grant permission for a command's effects.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import selectors
import shutil
import signal
import stat
import sqlite3
import subprocess
import sys
import time
import uuid

from runtime import state
from runtime.startup import MAX_INPUT, StartupError, AcceptedScope, ProjectScope, RuntimeSettings, json_object, policy_digest, _canonical_freeze, _canonical_plain

VERSION = 1
MAX_ATTEMPTS = 32
MAX_CHECKS = 32
MAX_LIST_ITEMS = 64
MAX_ARTIFACT = 4 * 1024 * 1024
MAX_OUTPUT = 128 * 1024
COVERAGE = {'general', 'security', 'behavior'}
IDENTITY = ('client', 'session_id', 'task_id', 'scope_ref', 'expected_revision')
_CONTENT_ACQUISITION=ContextVar('content_acquisition',default=None)
_DIAGNOSTIC_CLEANUP=ContextVar('diagnostic_cleanup',default=False)
_SOURCE_BIRTH=ContextVar('source_publication_birth',default=None)
_SOURCE_BIRTH_ISSUER=object()
_FOREIGN_PLAN_ISSUER=object()


def _require(value, message):
    if not value:
        raise state.StateError(message)


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def _bounded(value, limit=MAX_INPUT):
    try:
        _require(len(_raw(value)) <= limit, 'Evidence JSON size limit exceeded')
    except (ValueError, TypeError, RecursionError):
        raise state.StateError('Invalid bounded evidence JSON') from None


def _strings(value, field, choices=None):
    _require(isinstance(value, list) and len(value) <= MAX_LIST_ITEMS and all(isinstance(v, str) for v in value)
             and len(value) == len(set(value)), 'Invalid ' + field)
    for v in value:
        state._text(v, field, 4096)
    _require(choices is None or set(value) <= set(choices), 'Unsupported ' + field)
    return value


def _request(request, required=(), optional=(), *, limit=MAX_INPUT):
    _bounded(request, limit)
    state._fields(request, (*IDENTITY, *required), optional)
    state._identity(request)
    state._integer(request['expected_revision'], 'expected_revision', 1)


def _task(db, scope, request, revision=True, *, allow_cancelled=False):
    _require(db is not None, 'Task state has not been initialized')
    task = state._task(db, state._scope_id(scope), request['client'], request['session_id'])
    _require(task is not None and all(task[k] == request[k] for k in IDENTITY[:4]), 'Evidence task binding changed')
    state._compatible(scope, task)
    state._assert_open(task)
    _require(not revision or task['revision'] == request['expected_revision'], 'Task revision conflict')
    _require(allow_cancelled or task['state'] != 'cancelled', 'Cancelled tasks cannot collect or verify evidence')
    return task


def _folder(scope, create=False):
    parent = state._path(scope).parent
    state._private(parent, True)
    path = parent / 'evidence'
    if create:
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
    state._private(path, True)
    return path


@dataclass(frozen=True)
class EvidenceAuthorityContext:
    """Internal observed existing store; request JSON cannot authorize an authority set."""
    directory: Path
    database: Path
    directory_binding: object
    database_binding: object
    authority_set: tuple
    authorization: str


@dataclass(frozen=True)
class _ArtifactOwner:
    project_id: str
    task: object
    pins: object
    purpose: str = 'task'


@dataclass(frozen=True)
class _SourceMandateOwner:
    birth: object


@dataclass(frozen=True)
class _ForeignIntentOwner:
    plan: object
    source: object
    content: object
    created_at: int


@dataclass(frozen=True)
class _LinkedPublicationPlan:
    scope: object
    request: object
    content: object
    snapshots: object
    acquired: object
    observed: object
    dependencies: object
    producer: object
    issuer: object
    state: object


@dataclass(frozen=True)
class _BaselineOwner:
    project_id: str
    creation: object


@dataclass(frozen=True)
class _RecoveryOwner:
    project_id: str
    source: object
    created_at: int
    dependencies: tuple
    content: object


def _recovery_source_shape(value, identity):
    version=value.get('version')
    state._fields(value,('version','kind','identity','journal','authorities','tasks','assignments','artifacts','previous',
        *(['stopped','supersedes'] if version==2 else [])))
    _require(type(version) is int and version in (1,2) and value['kind']=='d4-recovery-source'
        and value['identity']==identity,'Recovery source history binding changed')
    state._fields(identity,('plan_dir','transaction_id','manifest_digest'))
    state._canonical_path(identity['plan_dir']); state._text(identity['transaction_id'],'recovery transaction'); state._canonical_hash(identity['manifest_digest'])
    state._fields(value['journal'],('sha256','observed_at','state'))
    state._canonical_hash(value['journal']['sha256']); state._integer(value['journal']['observed_at'],'journal observation time')
    _require(value['journal']['state'] in ('prepared','applying','interrupted','applied','blocked','rollback_partial','rolled_back'),'Recovery journal state differs')
    for key in ('authorities','tasks','assignments','artifacts',*(['stopped','supersedes'] if version==2 else [])):
        _require(isinstance(value[key],list) and len(value[key])<=4096,'Recovery source reference bound exceeded')
    if value['previous'] is not None: state._artifact_reference(value['previous'])
    if version==2:
        _require(value['previous'] is None,'Compact recovery cut cannot retain a previous raw route')
        from runtime import changes
        for certificate in value['stopped']:
            changes._stopped_certificate_shape(certificate)
            issued={a['reference']['id']:a['reference'] for a in certificate.get('assignments',[])}
            for reference in value['assignments']:
                if reference['authority']==certificate['reference']['authority'] and reference['id'] in issued:
                    changes._stopped_assignment_certificate(certificate,reference)
        for prior in value['supersedes']:
            state._fields(prior,('authority','artifact','identity','journal_sha256'))
            state._artifact_reference(prior['artifact']); state._canonical_hash(prior['journal_sha256'])
            _require(prior['identity']==identity and prior['authority'] in value['authorities'],'Recovery supersession identity differs')
    return value


def _recovery_source_dependencies(content,authority):
    dependencies = [dict(kind='task',reference=t['reference']) for t in content['tasks']]
    dependencies += [dict(kind='assignment',reference=a) for a in content['assignments']]
    dependencies += [dict(kind='artifact',reference=a) for a in content['artifacts']]
    if content['previous']:
        dependencies.append(dict(kind='recovery',reference=dict(authority=authority,artifact=content['previous'])))
    _require(len(dependencies)<=4096,'Recovery source dependency bound exceeded')
    return dependencies


def _recovery_source_history(context,db,reference,identity,*,validate_stops=True,preparation_reader=None):
    """Point-follow owned snapshots; missing prior support cannot be silently replaced."""
    history=[]; seen=set(); age=None; owner=None
    while reference is not None:
        key=_raw(reference)
        _require(key not in seen and len(seen)<4096,'Recovery source history is cyclic or excessive')
        seen.add(key)
        metadata,raw=_managed_artifact(None,reference,context=context,db=db)
        value=json.loads(raw)
        _recovery_source_shape(value,identity)
        _require(metadata['class']=='compact','Recovery source history binding changed')
        _require(metadata['dependencies']==_recovery_source_dependencies(value,_canonical_plain(context.authority_set[0])),
            'Recovery typed metadata dependencies differ from owner source')
        if age is None: age=metadata['created_at']; owner=metadata['owner']
        _require(metadata['created_at']==age and metadata['owner']==owner,'Recovery source history original age or owner changed')
        if value['version']==2 and validate_stops:
            from runtime import changes
            for certificate in value['stopped']:
                if certificate['reference']['authority']==_canonical_plain(context.authority_set[0]):
                    changes._check_stopped_certificate(context,db,certificate,preparation_reader=preparation_reader)
        history.append((dict(reference),value))
        reference=value['previous']
        if reference is not None: state._artifact_reference(reference)
    return history


def _register_recovery_source(scope, db, source, *, context=None):
    """Retain an inspected D4 source and its reverse edge in one existing transaction."""
    from runtime import changes
    _require((scope is None) != (context is None), 'Select exactly one existing evidence authority')
    selected = context or _evidence_context(scope)
    _check_context(selected, db)
    lifetime=changes._check_d4_publication(source, selected, db)
    prior_registration=lifetime['registrations'].get(str(selected.database))
    if prior_registration is not None:
        _check_recovery_registration(selected,db,source)
        _require(prior_registration['reference'] is not None,'Recovery registration is already in progress')
        return _canonical_freeze(prior_registration['reference'])
    baseline = state._source_baseline(None, db, context=selected)
    _require(baseline is not None, 'Recovery source baseline is unavailable; preserve operation markers')
    baseline = _canonical_plain(baseline)
    _require(baseline==lifetime['baselines'][str(selected.database)],'Recovery original baseline changed after authenticated acquisition')
    content = _canonical_plain(source.content)
    identity = content['identity']
    edges = baseline['dependencies']
    matches = [e for e in edges if e['reference']['identity'] == identity]
    _require(len(matches) <= 1, 'Conflicting stable recovery source edges')
    previous = matches[0]['reference']['artifact'] if matches else None
    created = source.created_at
    state._integer(created,'original D4 source creation time')
    if previous is not None:
        metadata, raw = _managed_artifact(None, previous, context=selected, db=db)
        prior = _recovery_source_history(selected,db,previous,identity)[0][1]
        _require(prior.get('kind') == 'd4-recovery-source' and prior.get('identity') == identity
            and metadata['class'] == 'compact' and metadata['owner'] == dict(kind='project',project_id=baseline['content']['project_id'],task=None),
            'Prior recovery source ownership changed')
        _require(metadata['created_at']==created,'Original D4 source age differs from observed first source')
        comparable = dict(content, previous=prior.get('previous'))
        comparable['journal'] = dict(comparable['journal'], observed_at=prior['journal']['observed_at'])
        if comparable == prior:
            lifetime['registrations'][str(selected.database)]=dict(baseline=baseline,expected=baseline,
                content=prior,created_at=created,dependencies=_recovery_source_dependencies(prior,_canonical_plain(selected.authority_set[0])),reference=previous)
            _check_recovery_registration(selected,db,source)
            return _canonical_freeze(previous)
    content['previous'] = previous if content['version']==1 else None
    dependencies = _recovery_source_dependencies(content,_canonical_plain(selected.authority_set[0]))
    registration=dict(baseline=baseline,expected=baseline,content=content,created_at=created,dependencies=dependencies,reference=None)
    lifetime['registrations'][str(selected.database)]=registration
    owner = _RecoveryOwner(baseline['content']['project_id'], source, created, tuple(_canonical_freeze(d) for d in dependencies), _canonical_freeze(content))
    reference = _artifact(None, content, context=selected, owner=owner, db=db)
    registration['reference']=reference
    edges = [e for e in edges if e['reference']['identity'] != identity]
    edges.append(dict(kind='recovery',reference=dict(identity=identity,artifact=reference)))
    edges.sort(key=lambda e: _raw(e))
    _require(len(edges) <= 4096, 'Recovery baseline source bound exceeded')
    metadata = state._metadata(db, baseline['reference']['name'])
    metadata['dependencies'] = edges
    db.execute('update evidence_metadata set data=? where name=?', (_raw(metadata).decode(),baseline['reference']['name']))
    registration['expected']=dict(baseline,dependencies=edges)
    _check_recovery_registration(selected,db,source)
    return _canonical_freeze(reference)


def _check_recovery_registration(context,db,source,owner=None):
    from runtime import changes
    lifetime=changes._check_d4_publication(source,context,db)
    registration=lifetime['registrations'].get(str(context.database))
    _require(registration is not None,'Recovery owner has no actual registration acquisition')
    baseline=registration['baseline'];content=_canonical_plain(source.content)
    matches=[edge for edge in baseline['dependencies'] if edge['reference']['identity']==content['identity']]
    _require(len(matches)<=1,'Recovery original baseline head is ambiguous')
    previous=matches[0]['reference']['artifact'] if matches else None
    content['previous']=previous if content['version']==1 else None
    if registration['reference']==previous and previous is not None:
        prior=_recovery_source_history(context,db,previous,content['identity'])[0][1]
        content['previous']=prior.get('previous');content['journal']['observed_at']=prior['journal']['observed_at']
    dependencies=_recovery_source_dependencies(content,_canonical_plain(context.authority_set[0]))
    _require(content==registration['content'] and dependencies==registration['dependencies'] and source.created_at==registration['created_at'],
        'Recovery content, true previous head, original age or dependencies changed')
    actual=_canonical_plain(state._source_baseline(None,db,context=context))
    _require(actual==registration['expected'],'Recovery baseline differs from its exact owned overlay')
    if owner is not None:
        _require(owner.project_id==baseline['content']['project_id'] and owner.created_at==source.created_at and
            _canonical_plain(owner.content)==content and [_canonical_plain(d) for d in owner.dependencies]==dependencies,
            'Recovery owner differs from authoritative source/head/age/dependencies')
    reference=registration['reference']
    if reference is not None:
        metadata,raw=_managed_artifact(None,reference,context=context,db=db)
        _require(json.loads(raw)==content and metadata['class']=='compact' and metadata['version']==2 and
            metadata['owner']==dict(kind='project',project_id=baseline['content']['project_id'],task=None) and
            metadata['created_at']==source.created_at and metadata['closed_at'] is None and not metadata['targets'] and
            metadata['export'] is None and metadata['dependencies']==dependencies,'Recovery registered source overlay changed')
    return registration


def _register_source_baseline(scope, db, creation):
    """Initializer-only compact provenance; no D4 source completeness is implied."""
    path = state._path(scope)
    state._check_creation(path, creation, db)
    _require(db.in_transaction and state._scope_version(scope) == 3, 'Baseline requires the fresh schema3 transaction')
    for table in state.CANONICAL_TABLE_SQL:
        _require(db.execute('select 1 from ' + table + ' limit 1').fetchone() is None,
                 'Existing authority records cannot acquire a creation baseline')
    folder = path.parent / 'evidence'
    if os.path.lexists(folder):
        state._private(folder, True)
        _require(next(folder.iterdir(), None) is None, 'Unknown evidence content protects this authority from bootstrap')
    content = dict(version=1, kind='authority-source-baseline', source_contract=2,
        authority=_canonical_plain(creation.authority), project_id=scope.project_id,
        created_at=creation.created_at, runtime_digest=state.runtime_fingerprint())
    reference = _artifact(scope, content, owner=_BaselineOwner(scope.project_id, creation), db=db)
    state._check_creation(path, creation, db)
    os.fsync(creation.descriptor)
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return reference


def _binding(path):
    info = path.lstat()
    return dict(device=info.st_dev, inode=info.st_ino)


def _evidence_context(scope):
    path = state._path(scope)
    state._sidecars(path)
    authority = dict(directory=str(path.parent), database=str(path),
        directory_binding=_binding(path.parent), database_binding=_binding(path))
    return EvidenceAuthorityContext(path.parent, path, _canonical_freeze(authority['directory_binding']),
        _canonical_freeze(authority['database_binding']), (_canonical_freeze(authority),),
        'existing accepted Project evidence authority')


def _existing_authority_context(authority, *, db):
    """D4 existing-store read/registration selection; no enumeration or eligibility proof."""
    authority = _canonical_plain(_canonical_freeze(authority))
    state._fields(authority, ('directory','database','directory_binding','database_binding'))
    directory = state._canonical_path(authority['directory'])
    database = state._canonical_path(authority['database'])
    state._canonical_binding(authority['directory_binding']); state._canonical_binding(authority['database_binding'])
    context = EvidenceAuthorityContext(directory, database, _canonical_freeze(authority['directory_binding']),
        _canonical_freeze(authority['database_binding']), (_canonical_freeze(authority),), 'D4 existing physical authority')
    _check_context(context, db)
    return context


def _check_context(context, db=None):
    _require(isinstance(context, EvidenceAuthorityContext), 'Existing authorized evidence context is required')
    _require(context.database == context.directory / 'runtime.sqlite3' and context.database.is_absolute()
        and context.database.resolve() == context.database, 'Evidence authority path changed')
    state._private(context.directory, True)
    state._sidecars(context.database)
    _require(_binding(context.directory) == _canonical_plain(context.directory_binding)
        and _binding(context.database) == _canonical_plain(context.database_binding), 'Evidence authority physical identity changed')
    if db is not None:
        names = db.execute('pragma database_list').fetchall()
        _require(len(names) == 1 and names[0][1:] == ('main', str(context.database)), 'Artifact connection is not its evidence authority')
        state._schema(db, version=3)
        _require(db.in_transaction, 'Artifact registration requires its existing transaction')


@contextmanager
def _context_database(context, *, write=False,durable=False,before_commit=None):
    _check_context(context)
    db = None
    try:
        db = sqlite3.connect(context.database.as_uri() + ('?mode=rw' if write else '?mode=ro'), uri=True, timeout=0.1)
        db.execute('pragma trusted_schema=off')
        if durable:
            _require(write,'Durable publication requires its source write transaction')
            mode=db.execute('pragma journal_mode').fetchone()[0]
            _require(mode in {'delete','truncate','persist','wal'},'Source intent journal mode cannot establish durable publication')
            expected=2 if mode=='wal' else 3
            db.execute('pragma synchronous='+str(expected))
            _require(db.execute('pragma synchronous').fetchone()[0]==expected,'Source intent durability setting is unavailable')
        db.execute('begin immediate' if write else 'begin')
        _check_context(context, db)
        yield db
        _check_context(context, db)
        if write:
            if before_commit is not None:before_commit(db)
            db.commit()
    except sqlite3.Error:
        raise state.StateError('Evidence authority registration unavailable or locked') from None
    finally:
        if db is not None:
            db.close()


def _artifact_owner(scope, task):
    if state._scope_version(scope) != 3:
        return None
    _require(task["pins"]["schema_version"] == 3 and
        state._physical_identity(task["accepted_identity"]) == state._physical_identity(_canonical_plain(scope.accepted_identity)),
        "Artifact task physical owner differs from scope")
    context = _evidence_context(scope)
    reference = dict(authority=_canonical_plain(context.authority_set[0]), scope_id=state._scope_id(scope),
        **{key: task[key] for key in ('client', 'session_id', 'task_id')})
    return _ArtifactOwner(scope.project_id, _canonical_freeze(reference), _canonical_freeze(task['pins']))


def _guidance_artifact_owner(scope):
    if state._scope_version(scope) != 3:
        return None
    return _ArtifactOwner(scope.project_id, None, _canonical_freeze(state._pins(scope)), 'guidance')


_CLOSURE_ISSUER=object()


@dataclass(frozen=True)
class _ClosureObservation:
    """Acquisition provenance, not authentication of native/operator stop authority."""
    facts: object
    context: EvidenceAuthorityContext
    issuer: object


def _issued_closure(context, observations):
    _require(isinstance(observations,_ClosureObservation) and observations.issuer is _CLOSURE_ISSUER
        and all(getattr(observations.context,key)==getattr(context,key) for key in
            ('directory','database','directory_binding','database_binding','authority_set'))
        and state._frozen_snapshot(observations.facts),
        'Closure needs an immutable observation issued by actual owner acquisition')
    return _canonical_plain(observations.facts)


@dataclass(frozen=True)
class _ClosureOwner:
    reference: object
    facts: object
    content: object
    dependencies: tuple
    created_at: int


def _closure_task_artifacts(task):
    _require('linked_verification' not in task.get('evidence',{}) and not task.get('writer_stop',{}).get('linked'),
        'Linked closure requires exact stopped participant/delivery composition')
    return [edge['reference'] for edge in _artifact_dependencies({key:value for key,value in task.items() if key!='lifecycle'})]


def _closure_assignment_projection(context,db,task,records):
    """Project original managed facts, never native transcripts or inferred usage."""
    from runtime import delegation
    read=lambda ref:_read(None,ref,context=context,db=db)
    outcomes=[];numerical=[];reviews=[];workers=[]
    attempts=task.get('evidence',{}).get('attempts',[])
    for attempt in attempts:
        record=delegation._linked_attempt(None,_task_scope_id(task),task,attempt,records,context=context,db=db)
        _require(record is not None and record['data']['status']=='settled',
            'Historical evidence attempt lacks its exact settled owner certificate')
        _require(attempt['status'] not in {'reserved','running','uncertain'},'Unresolved evidence attempt remains protected')
        outcome=dict(attempt=deepcopy(attempt),assignment_id=record['id'],outcome=record['data']['result']['outcome'])
        if attempt['kind']=='check' and attempt.get('execution'):
            source=attempt['execution'];execution=read(source);result=execution['result']
            metadata=state._metadata(db,source['name'])
            _require(metadata is not None and metadata['owner']['task']==dict(authority=_canonical_plain(context.authority_set[0]),
                scope_id=_task_scope_id(task),**{key:task[key] for key in ('client','session_id','task_id')}),
                'Execution needs its exact original managed owner/age/provenance')
            for field,unit in (('exit_code','exit-code'),('output_bytes','bytes')):
                value=result.get(field)
                _require(value==attempt.get(field) and (type(value) is int or field=='exit_code' and value is None),
                    'Execution numerical fact differs from original attempt')
                if field=='output_bytes':_require(value>=0,'Invalid original output byte count')
                numerical.append(dict(field=field,value=value,unit=unit,source=source,created_at=metadata['created_at'],
                    assignment_id=record['id'],owner=record['owner'],status=result['status'],
                    semantics='bounded-observed-output' if field=='output_bytes' else 'observed-process-exit'))
            outcome['execution']=dict(command=execution['command'],tool=execution['tool'],output=execution['output'],
                result={k:v for k,v in result.items() if k!='private_output'})
        if attempt['kind']=='review':
            review=dict(assignment_id=record['id'],status=attempt['status'],coverage=attempt['coverage'],criteria=attempt['criteria'])
            if 'collected' in attempt:
                collected=read(attempt['collected']);_report(collected['report'],attempt)
                if record['data']['result']['outcome']=='completed':
                    _require(_review_quality_matches(None,attempt,record,collected,context=context),
                        'Completed historical review lacks its exact bound native report')
                review.update(source=attempt['collected'],report=collected['report'],receipt=collected['receipt'])
            assessments=[]
            for source in attempt.get('assessment_history',[])+([attempt['assessment']] if 'assessment' in attempt else []):
                assessed=read(source)
                state._fields(assessed,('collected_digest','assessment'))
                _require(assessed['collected_digest']==attempt['collected']['digest'],'Review assessment source changed')
                assessment=assessed['assessment']
                state._fields(assessment,('coverage','criteria','qualification','independence','semantic_coverage','dispositions','decision_refs'),
                    ('rechecked_findings',))
                _require(isinstance(assessment['dispositions'],list) and len(assessment['dispositions'])<=64,
                    'Original review finding dispositions are unavailable')
                finding_ids={finding['id'] for finding in collected['report']['findings']};seen=set()
                for disposition in assessment['dispositions']:
                    state._fields(disposition,('finding_id','status','reference'))
                    _require(disposition['finding_id'] in finding_ids and disposition['finding_id'] not in seen
                        and disposition['status'] in {'resolved','accepted','open'},'Original finding disposition changed')
                    state._text(disposition['reference'],'original finding disposition reference');seen.add(disposition['finding_id'])
                assessments.append(dict(source=source,assessment=assessed['assessment']))
            review['assessments']=assessments;reviews.append(review)
        outcomes.append(outcome)
    for record in records:
        if record['data']['role'] not in {'worker','review'}:continue
        history=delegation._worker_history(None,record['data']['observation'],context=context)
        if record['data']['role']=='worker':
            for _,value in history:
                if value['report'] is not None:
                    _require(delegation._worker_report(None,record,value['result'])==value['report'],
                        'Historical worker report differs from actual bound result')
        workers.append(dict(assignment_id=record['id'],role=record['data']['role'],outcome=record['data']['result']['outcome'],
            observations=[dict(source=ref,status=value['status'],report=value['report'],receipt=value['receipt'],
                error=value['error'],conflict=value['conflict'],revision=value['revision']) for ref,value in history]))
    verification_refs={_raw(entry['verification']):entry['verification'] for entry in
        task.get('evidence',{}).get('history',[])+[task.get('evidence',{})] if 'verification' in entry}
    for record in records:
        if record['data']['role']=='coordinator':
            reconciled=read(record['data']['reconciliation'])
            if reconciled.get('kind')=='synchronous-verification':
                reference=reconciled['verification'];verification_refs[_raw(reference)]=reference
    verifications=[dict(source=ref,result=read(ref),created_at=state._metadata(db,ref['name'])['created_at'])
        for _,ref in sorted(verification_refs.items())]
    return dict(outcomes=outcomes,reviews=reviews,workers=workers,numerical=numerical,verifications=verifications)


def _lifecycle_requirements(context, roots, *, db):
    """Follow typed managed-content consumers; exact inserted owner edges are attribution."""
    authority=_canonical_plain(context.authority_set[0]);pending=[(edge,edge['owner']) for edge in roots];seen=set();requirements=[]
    while pending:
        edge,origin=pending.pop(0);key=_raw([edge,origin])
        if key in seen:continue
        seen.add(key);_require(len(seen)<=4096,'Lifecycle dependency traversal exceeds bound')
        kind=edge['kind'];reference=edge['reference'];need=edge['need']
        requirements.append(edge)
        if kind=='task':
            state._task_reference(reference)
            _require(reference['authority']==authority,'Foreign task consumer remains protected')
            identity=state._lifecycle_identity(db,'task',reference)
            if identity['status']!='live':
                from runtime import changes
                rows=db.execute("select name,digest,owner_key,class,created_at,closed_at,status,bytes,data from evidence_metadata where class='compact' and status='live' limit 4097").fetchall()
                _require(len(rows)<=4096,'Retained attribution support exceeds its bound')
                support=[]
                for row in rows:
                    metadata=state._metadata_record(row)
                    if metadata['owner'].get('task')!=reference:continue
                    value=_read(None,dict(name=row[0],digest=row[1]),context=context,db=db)
                    if value.get('kind')!='task-closure':continue
                    _require(value['identity']==reference and state._digest(value['pins'])==identity['pins_digest']
                        and value['created_at']==metadata['created_at']==identity['created_at'],
                        'Retained compact attribution differs from original marker identity/age')
                    changes._check_stopped_certificate(context,db,value['stopped'])
                    support.append(value)
                _require(len(support)==1,'Retired attribution requires exact retained owned compact support')
        elif kind=='artifact':
            selected=reference.get('authority',authority)
            _require(selected==authority,'Foreign content consumer remains protected')
            ref=reference.get('artifact',reference)
            metadata=state._metadata(db,ref['name'])
            if metadata is not None and metadata['status']!='live':
                proof=_diagnostic_proof(context,db,ref)
                parent=edge['owner'].get('artifact') if edge['owner'].get('authority')==authority else None
                original=origin.get('artifact') if origin.get('authority')==authority else None
                historical=[proof['execution'],proof['closure'],proof['mandate']['reference'],proof['execution_mandate']['reference']]
                _require((origin==proof['owner'] or original in historical)
                    and parent in (proof['execution'],proof['closure'],proof['mandate']['reference']),
                    'Independent current consumer requires unavailable diagnostic content')
                requirements[-1]=dict(edge,need='diagnostic-provenance')
                pending.append((dict(owner=dict(authority=authority,artifact=ref),kind='task',reference=proof['owner'],need='identity'),origin))
                continue
            metadata,raw=_managed_artifact(None,ref,context=context,db=db)
            value=json.loads(raw)
            for dependency in metadata['dependencies']:
                child=dict(dependency);child_need='content' if child['kind']=='artifact' else 'raw'
                if child['kind']=='task' and child['reference']==metadata['owner'].get('task') and value.get('kind')!='linked-verification':
                    child_need='identity'
                _require(child['kind'] in {'task','artifact'},'Unknown owner dependency requires its original raw support')
                pending.append((dict(owner=dict(authority=authority,artifact=ref),**child,need=child_need),origin))
        else:
            raise state.StateError('Assignment, delivery or recovery body needs owner-specific closure support')
    return sorted({_raw(edge):edge for edge in requirements}.values(),key=_raw)


def _closure_file_stat(path):
    try:info=path.lstat()
    except OSError:raise state.StateError('Closure source is unavailable') from None
    _require(stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode),'Closure source is not a physical file/directory')
    return [info.st_dev,info.st_ino,info.st_mode,info.st_uid,info.st_nlink,info.st_size,info.st_mtime_ns,info.st_ctime_ns]


def _closure_recovery_files(recovery):
    """Freshness only: D4 owns interpretation of these exact approved source trees."""
    files={};pending=sorted({Path(row['plan_dir']) for row in recovery['dependencies'] if 'plan_dir' in row})
    while pending:
        path=pending.pop();_require(len(files)<4096,'Closure recovery file observation exceeds bound')
        files[str(path)]=_closure_file_stat(path)
        if path.is_dir():pending.extend(sorted(path.iterdir()))
    return files


def _closure_recovery(context,task_ref=None):
    """Inspect all current D4 roots, with optional named-task D4 stop correspondence."""
    from runtime import changes
    authorities=[_canonical_plain(context.authority_set[0])]
    task_refs=[] if task_ref is None else [task_ref]
    result=_canonical_plain(changes._inspect_lifecycle_recovery_guarded(authorities,task_refs))
    before=_closure_recovery_files(result)
    latest=_canonical_plain(changes._inspect_lifecycle_recovery_guarded(authorities,task_refs))
    _require(latest==result and _closure_recovery_files(latest)==before,'Recovery source moved during closure observation')
    return result,before


def _ready_stop_shape(proof):
    _bounded(proof)
    state._fields(proof,('version','kind','identity','expected_revision','expected_pins','observed_turn_id','stopped','descendants_stopped',
        'attempt_ids','observation_ref','coordinator_ref','candidate_digest','verification_digest','task_digest','attempts_digest','assignments_digest','generation'),('linked_digest',))
    state._integer(proof['expected_revision'],'ready proof revision',1);state._validate_pins(proof['expected_pins'])
    state._fields(proof['identity'],IDENTITY[:4]);state._identity(proof['identity'])
    _require(isinstance(proof['attempt_ids'],list) and len(proof['attempt_ids'])<=MAX_ATTEMPTS and
        all(isinstance(item,str) for item in proof['attempt_ids']) and len(set(proof['attempt_ids']))==len(proof['attempt_ids']),
        'Ready stop attempt identity set is malformed')
    if proof['observed_turn_id'] is not None:state._text(proof['observed_turn_id'],'ready stop turn',4096)
    for key in ('observation_ref','coordinator_ref'):state._text(proof[key],key)
    for key in ('candidate_digest','verification_digest','task_digest','attempts_digest','assignments_digest'):
        if key=='verification_digest' and proof[key] is None and 'linked_digest' in proof:continue
        state._canonical_hash(proof[key])
    if 'linked_digest' in proof:state._canonical_hash(proof['linked_digest'])
    state._integer(proof['generation'],'ready proof generation')
    _require(type(proof['version']) is int and proof['version']==2 and proof['kind']=='stopped-writer-reconciliation' and
        proof['stopped'] is True and proof['descendants_stopped'] is True,'Independent complete ready stop remains missing')


def _ready_stop_proof(task,proof,bindings,candidate,verification,linked=None):
    _ready_stop_shape(proof)
    if linked is not None:
        own=[row for row in linked['members'] if all(row['task'][k]==task[k] for k in ('client','session_id','task_id')) and
            row['task']['scope_id']==_task_scope_id(task) and row['pins']==task['pins']]
        _require(len(own)==1 and own[0]['bindings']==bindings and own[0]['state']==task['state'] and
            own[0]['revision']==task['revision'] and own[0]['pins']==task['pins'] and
            own[0]['candidate_digest']==_digest(candidate) and own[0]['verification']==verification,
            'Independent stop differs from its exact linked-member snapshot')
    attempts=task.get('evidence',{}).get('attempts',[])
    _require(task['state'] in ({'ready','verifying','cancelled'} if linked is not None else {'ready','cancelled'}) and
        (linked is not None)==('linked_digest' in proof) and (linked is None or proof['linked_digest']==_digest(linked)) and
        task['pins']['schema_version']==3 and type(proof['version']) is int and proof['version']==2 and
        proof['kind']=='stopped-writer-reconciliation' and proof['stopped'] is True and proof['descendants_stopped'] is True and
        proof['identity']=={k:task[k] for k in ('client','session_id','task_id','scope_ref')} and
        proof['expected_revision']==task['revision'] and proof['expected_pins']==task['pins'] and proof['observed_turn_id']==task['turn_id'] and
        proof['attempt_ids']==[a['id'] for a in attempts] and not any(a['status'] in {'reserved','running','uncertain'} for a in attempts) and
        all(proof[k]==v for k,v in bindings.items()) and proof['candidate_digest']==_digest(candidate) and
        proof['verification_digest']==(verification['digest'] if verification is not None else None) and
        (verification is not None or linked is not None and linked['version']==2 and own[0]['verification'] is None),
        'Independent ready stop does not bind the complete current original owner snapshot')


def _check_ready_inputs(files,*,directory_identity=False):
    for path,value in files.items():
        current=_closure_file_stat(Path(path)) if os.path.lexists(path) else None
        if value is not None and stat.S_ISDIR(value[2]) and (directory_identity or len(value)==4):
            _require(current is not None and current[:4]==value[:4],'Ready input directory identity changed')
        else:_require(current==value,'Ready candidate inputs changed before owner commit')


def _stop_verification(context,db,task,*,allow_absent=False):
    """Preserve every actual historical verifier; absence is only factual v2 compatibility."""
    if task['state'] in {'ready','verifying'} and not allow_absent:return task['evidence']['verification']
    from runtime import changes,delegation
    ref=dict(authority=_canonical_plain(context.authority_set[0]),scope_id=_task_scope_id(task),
        **{k:task[k] for k in ('client','session_id','task_id')})
    if task['state']=='cancelled':
        _require(task.get('retirement'),'Complete cancelled stop needs original retirement')
        legacy=dict(reference=ref,created_at=task['lifecycle']['created_at'],**{k:task[k] for k in
            ('revision','pins','accepted_identity','scope_ref','turn_id','retirement')},proof=_read(None,task['retirement']['proof'],context=context,db=db))
        changes._stopped_certificate_shape(legacy)
        attempts=[a['id'] for a in task.get('evidence',{}).get('attempts',[]) if a['status'] in {'reserved','running','uncertain'}]
        _require(legacy['proof']['attempt_ids']==attempts,'Original cancellation attempt membership changed')
    else:_require(allow_absent and task['state'] in {'ready','verifying'},'Complete stop lacks terminal task authority')
    barriers=[]
    for record in delegation._ledger(None,db,context=context):
        if not all(record['owner'][k]==ref[k] for k in ('scope_id','client','session_id','task_id')):continue
        if record['data']['role']!='coordinator' or record['data']['status']!='settled':continue
        rec=_read(None,record['data']['reconciliation'],context=context,db=db)
        if rec.get('kind')=='synchronous-verification':
            changes._barrier_facts(context,db,task,record,rec);barriers.append(rec)
    if not barriers:
        references=[e.get('verification') for e in task['evidence'].get('history',[])+[task['evidence']]]
        _require(allow_absent and not any(references),'Cancelled complete stop requires an actual original synchronous barrier')
        return None
    return max(barriers,key=lambda rec:rec['revision'])['verification']


def _ready_stop_candidate(context,task,candidate):
    """Read-only freshness from original pinned context; never reserve another verifier."""
    if task.get('writer_stop',{}).get('linked'):
        with _context_database(context) as db:linked=_read(None,task['writer_stop']['linked'],context=context,db=db)
        _require(_linked_stopped_basis(_linked_basis_root(linked),linked['authorities'],fresh=True)==linked,'Linked complete-stop basis changed')
        return next(row['inputs'] for row in linked['members'] if row['task']['authority']==_canonical_plain(context.authority_set[0])
            and row['task']['scope_id']==_task_scope_id(task) and all(row['task'][k]==task[k] for k in ('client','session_id','task_id')))
    with _context_database(context) as db:
        plan=_read(None,task['evidence']['plan'],context=context,db=db)
        verification_ref=_stop_verification(context,db,task)
        verification=_read(None,verification_ref,context=context,db=db)
    _require(task['state'] in {'ready','cancelled'} and plan['version']==1 and 'linked_verification' not in task['evidence'] and
        (task['state']=='cancelled' or verification['purpose']=='completion' and not verification['blockers'] and
        verification['plan_digest']==_digest(plan) and verification['candidate_digest']==_digest(candidate)),
        'Ready verification is missing, linked or stale')
    _candidate_projection(candidate,task)
    _require(state.runtime_fingerprint()==task['pins']['runtime_digest'] and policy_digest(state.PACKAGE)==task['pins']['policy_digest'],
        'Installed ready source pins changed')
    locator=_pinned_locator(task,context)
    first=_capture(locator,plan,pinned=(task['accepted_identity'],task['pins']))
    second=_capture(locator,plan,pinned=(task['accepted_identity'],task['pins']))
    _require(first==second==candidate,'Ready candidate changed after independent stop')
    if task['state']=='ready':
        _require(not _blockers(locator,task,plan,candidate,'completion',verification.get('reuse',[]),verification.get('security_impact'),
            resource_closure=verification['resource_closure'],context=context),'Ready findings/resources remain blocked')
    return _stop_input_files(task,candidate)


def _stop_input_files(task,candidate):
    # Stat snapshots supplement the complete capture at the last short writer.
    root=Path(task['accepted_identity']['repository_root']);git=Path(task['accepted_identity']['git_dir'])
    common=Path(task['accepted_identity']['git_common_dir'])
    accepted=task['accepted_identity']
    bindings={Path(accepted['project_root']):accepted['project_binding'],Path(accepted['primary_root']):accepted['bindings']['primary_root']}
    paths={root,root/'.git',git,common,git/'HEAD',git/'index',git/'commondir',common/'HEAD',common/'packed-refs',*bindings}
    policy=state.PACKAGE/'policies';runtime=state.PACKAGE/'runtime';adapters=runtime/'adapters'
    paths.update((policy,runtime,adapters,*state._runtime_sources(),*policy.glob('*.md')))
    for dependency in task['accepted_identity']['shared_policy']:
        path=Path(dependency['path']);paths.update((path,path.parent))
    for name in candidate['fingerprints']:
        path=Path(name[len('instruction:'):]) if name.startswith('instruction:') else root/name
        paths.update((path,path.parent))
        paths.update(parent for parent in path.parents if parent==root or parent.is_relative_to(root))
    for tool in candidate['tools'].values():paths.update((Path(tool['path']),Path(tool['path']).parent))
    pending=list({git/'refs',common/'refs'})
    while pending:
        path=pending.pop();paths.add(path)
        if path.is_dir():pending.extend(path.iterdir())
        _require(len(paths)<4096,'Ready physical input observation exceeds bound')
    files={}
    for path in sorted(paths):
        value=_closure_file_stat(path) if os.path.lexists(path) else None
        if path in bindings:
            _require(value is not None and stat.S_ISDIR(value[2]) and dict(device=value[0],inode=value[1])==bindings[path],
                'Accepted Project or primary-root physical binding changed')
        # Ancestor/tool sibling activity is not a candidate change; their identity still binds lookup.
        if value is not None and stat.S_ISDIR(value[2]) and not any(path.is_relative_to(base) for base in (root,git,common,policy,runtime)):
            value=value[:4]
        files[str(path)]=value
    return files


def _closure_facts(context, task_ref, db, recovery, *, recovery_files=None):
    from runtime import changes,delegation
    _check_context(context,db)
    state._fields(recovery,('complete','dependencies','blockers','roots','requirements','authorities','discovered_authorities'))
    authority=_canonical_plain(context.authority_set[0])
    _require(recovery['complete'] is True and not recovery['blockers'] and not recovery['discovered_authorities']
        and recovery['authorities']==[authority],'Recovery current source coverage is incomplete or foreign')
    observed=state.inspect_dependencies(db,task_ref);task=observed['task']
    assignment_blocker='Assignment body requires original task; exact assignment certificate integration is required'
    _require(not [blocker for blocker in observed['blockers'] if blocker!=assignment_blocker],'; '.join(observed['blockers']))
    ready=task['state']=='ready'
    _require(task['pins']['schema_version']==3 and task.get('lifecycle') and
        (ready and task.get('writer_stop') or task['state']=='cancelled' and task.get('retirement')),
        'Closure needs a dated independently stopped owner')
    ready_files=_ready_stop_candidate(context,task,_read(None,task['writer_stop']['candidate'],context=context,db=db)) if task.get('writer_stop') else {}
    certificate=changes._stopped_certificate(context,db,dict(reference=task_ref,pins=task['pins']))
    _require(task.get('writer_stop') or not certificate['proof']['attempt_ids'],'Stopped unresolved attempts require assignment certificate integration')
    records=delegation._closure_assignments(context,db,task_ref,task,certificate)
    all_records=delegation._ledger(None,db,context=context)
    guidance=delegation._closure_guidance(context,db,all_records)
    projection=_closure_assignment_projection(context,db,task,records)
    own_ids={record['id'] for record in records}
    projection.update(native_guidance=[item for item in guidance['native'] if item['reference']['id'] in own_ids],
        scope_guidance=guidance['sources'])
    own_refs=_closure_task_artifacts(task)
    own_refs.extend(guidance['references'])
    for record in records:
        own_refs.extend(edge['reference'] for edge in _artifact_dependencies(record))
    visited={};pending=own_refs
    while pending:
        ref=pending.pop()
        if _raw(ref) in visited:continue
        _require(len(visited)<4096,'Original closure artifact support exceeds bound')
        body=_read(None,ref,context=context,db=db)
        _require(body.get('version')!=2 or 'linked' not in body,'Linked closure requires exact stopped participant/delivery composition')
        visited[_raw(ref)]=ref
        pending.extend(edge['reference'] for edge in _artifact_dependencies(body))
    own_refs=list(visited.values())
    roots=[]
    for row in observed['tasks']:
        if row['reference']==task_ref:continue
        for ref in _artifact_dependencies(row['task']):
            roots.append(dict(owner=row['reference'],**ref,need='content'))
        linked=row['task'].get('evidence',{}).get('linked_verification')
        if linked:
            roots.append(dict(owner=row['reference'],kind='artifact',reference=dict(authority=linked['authority'],artifact=linked['reference']),need='content'))
    for record in all_records:
        if record['id'] in own_ids:continue
        roots.extend(dict(owner=dict(authority=authority,id=record['id']),**edge,need='content')
            for edge in _artifact_dependencies(record))
    roots.extend(dict(owner=dict(authority=authority,source='native-guidance'),kind='artifact',reference=ref,need='content')
        for ref in guidance['references'])
    # D4 already classified its current roots, including independent old proof routes.
    requirements=list(recovery['requirements'])+_lifecycle_requirements(context,roots,db=db)
    _require(not any(edge['kind']=='task' and edge['reference']==task_ref and edge['need']=='raw' for edge in requirements),
        'An independent current consumer still requires the raw task body')
    # Every existing managed file is accounted and physically bound; unregistered orphans protect.
    physical=_historical_inventory(context,db,observed['metadata']);compact=task['lifecycle']['compact']
    for item in physical:
        ref=item['reference'];metadata=item['metadata'];owner=metadata['owner']
        _require(owner.get('kind')=='project' and owner.get('project_id')==task['accepted_identity']['project_id'],
            'Unknown or foreign evidence owner remains protected')
        _require(owner['task'] is None or owner['task']['authority']==authority,'Foreign evidence task owner remains protected')
        if owner['task'] is None:
            body=_read(None,ref,context=context,db=db)
            _require(metadata['class']=='compact' and body.get('kind') in {'authority-source-baseline','d4-recovery-source'}
                or metadata['class']=='detail' and ref in guidance['references'],
                'Scope-owned consumer dependencies require existing guidance/review owner integration')
    folder=context.directory/'evidence'
    names=sorted(p.name for p in folder.iterdir()) if folder.exists() else []
    _require(len(names)<=4096 and names==sorted(item['reference']['name'] for item in physical if item['stat'] is not None),
        'Unaccounted evidence content remains protected')
    # Normalize only the owner-written closure envelope and its one retained compact artifact.
    task=dict(task,lifecycle=dict(created_at=task['lifecycle']['created_at'],safe_closed_at=None,closure=None,compact=None))
    normalized=dict(observed,task=task)
    normalized['tasks']=[dict(row,task=task) if row['reference']==task_ref else row for row in observed['tasks']]
    normalized['metadata']=[item for item in observed['metadata'] if item['reference']!=compact]
    normalized.pop('digest')
    physical=[item for item in physical if item['reference']!=compact]
    projection['sources']=[dict(reference=item['reference'],created_at=item['metadata']['created_at'],
        owner=item['metadata']['owner'],bytes=item['metadata']['bytes'],unit='bytes')
        for item in physical if item['reference'] in own_refs]
    original=task['accepted_identity']
    bindings={original['project_root']:original['project_binding']}
    bindings.update({original[k]:original['bindings'][label] for k,label in (('repository_root','root'),('primary_root','primary_root'),('git_dir','git_dir'),('git_common_dir','git_common_dir'))})
    _require(all(_binding(Path(path))==binding for path,binding in bindings.items()),'Historical checkout physical identity changed')
    return dict(version=1,task_ref=task_ref,task=task,certificate=certificate,bindings=bindings,recovery_files=recovery_files or {},
        observed=normalized,physical=physical,ready_files=ready_files,requirements=sorted(requirements,key=_raw),recovery=recovery,
        artifacts=sorted(own_refs,key=_raw),projection=projection,guidance=guidance)


def _linked_closure_recovery_heads(authorities,*,writer=None):
    heads=[]
    for authority in authorities:
        context=_reference_context(authority)
        with _preparation_database(context,writer) as db:
            baseline=state._source_baseline(None,db,context=context)
            _require(baseline is not None and baseline['content']['source_contract']==2,'Linked closure recovery coverage is unknown')
            for edge in baseline['dependencies']:
                ref=_canonical_plain(edge['reference']['artifact']);identity=_canonical_plain(edge['reference']['identity'])
                metadata,raw=_managed_artifact(None,ref,context=context,db=db)
                _require(metadata['class']=='compact' and metadata['owner']==dict(kind='project',project_id=baseline['content']['project_id'],task=None) and
                    metadata['status']=='live' and metadata['closed_at'] is None and not metadata['targets'] and metadata['export'] is None,
                    'Linked closure recovery source owner changed')
                _recovery_source_history(context,db,ref,identity,validate_stops=False)
                heads.append(dict(authority=authority,identity=identity,source_artifact=ref))
    return sorted(heads,key=_raw)


def _linked_closure_facts(context,task_ref,pointer,authorities,recovery,files,*,writer=None,new_compact=None):
    """Fresh pending closure; normalize only authenticated component support."""
    from runtime import delegation
    component=_linked_preparation_facts(pointer,authorities,writer=writer)
    _require(not component.get('discovered_authorities'),'Linked closure source guards are incomplete')
    _require(_linked_stopped_basis(pointer,component['basis']['authorities'],writer=writer,fresh=True)==component['basis'],
        'Linked closure participant basis changed')
    receipts={_raw(m['reference']):_preparation_receipt(component,m['reference'],writer=writer) for m in component['members']}
    _require(all(receipts.values()),'Linked closure needs every authoritative prepared replacement')
    owners=set(receipts);observations={};physicals={};candidates={};published=set()
    _require(recovery['complete'] and not recovery['blockers'] and not recovery['discovered_authorities'] and
        sorted(recovery['authorities'],key=_raw)==sorted(authorities,key=_raw),'Linked closure recovery is incomplete')
    _require(_linked_closure_recovery_heads(authorities,writer=writer)==sorted(recovery['roots'],key=_raw),
        'Linked closure current recovery source heads changed')
    requirements=list(recovery['requirements'])
    for authority in authorities:
        other=_reference_context(authority)
        with _preparation_database(other,writer) as db:
            local_members=[m for m in component['members'] if m['reference']['authority']==authority];excluded=[]
            for member in local_members:
                ref=member['reference'];task=state._task(db,ref['scope_id'],ref['client'],ref['session_id'],ref['task_id'])
                prepared=_linked_owned_preparation(other,db,ref)
                candidate=_linked_closure_candidate(other,db,ref,task,prepared)
                if task['lifecycle']['safe_closed_at'] is not None:
                    _linked_closed_member(other,db,ref,task,prepared);published.add(_raw(ref))
                if candidate is not None:candidates[_raw(ref)]=candidate;excluded.append(candidate['reference'])
            current=[]
            for member in local_members:
                observed=state.inspect_dependencies(db,member['reference'])
                _require(not [b for b in observed['blockers'] if b!='Assignment body requires original task; exact assignment certificate integration is required'],
                    'Linked original event/assignment ownership remains uncertain')
                current=observed['tasks']
                for row in observed['tasks']:
                    if _raw(row['reference']) in owners:row['task']=_preparation_member(component,row['reference'])['task']
                observed['task']=member['task'];observed['metadata']=[row for row in observed['metadata'] if row['reference'] not in excluded];observed.pop('digest')
                observations[_raw(member['reference'])]=observed
            if not local_members:
                rows=db.execute('select scope_id,client,session_id,task_id from tasks order by scope_id,client,session_id,task_id limit 4097').fetchall()
                _require(len(rows)<=4096,'Linked closure foreign task history exceeds bound')
                current=[dict(reference=dict(authority=authority,scope_id=row[0],client=row[1],session_id=row[2],task_id=row[3]),task=state._task(db,*row)) for row in rows]
            records=delegation._ledger(None,db,context=other);guidance=delegation._closure_guidance(other,db,records);roots=[]
            for row in current:
                if _raw(row['reference']) in owners:continue
                roots.extend(dict(owner=row['reference'],**edge,need='content') for edge in _artifact_dependencies(row['task']))
                linked=row['task'].get('evidence',{}).get('linked_verification')
                if linked:roots.append(dict(owner=row['reference'],kind='artifact',reference=dict(authority=linked['authority'],artifact=linked['reference']),need='content'))
            for record in records:
                owner=dict(authority=authority,**{k:record['owner'][k] for k in ('scope_id','client','session_id','task_id')})
                if _raw(owner) not in owners:roots.extend(dict(owner=dict(authority=authority,id=record['id']),**edge,need='content') for edge in _artifact_dependencies(record))
            roots.extend(dict(owner=dict(authority=authority,source='native-guidance'),kind='artifact',reference=ref,need='content') for ref in guidance['references'])
            requirements.extend(_lifecycle_requirements(other,roots,db=db))
            if not local_members:continue
            observed=observations[_raw(local_members[0]['reference'])];allowed={row['task']['accepted_identity']['project_id'] for row in observed['tasks']}
            physical=_historical_inventory(other,db,observed['metadata'])
            for item in physical:
                metadata=item['metadata'];owner=metadata['owner']
                _require(owner['kind']=='project' and owner['project_id'] in allowed and
                    (owner['task'] is None or owner['task']['authority']==authority),'Unknown linked closure content owner remains protected')
                if owner['task'] is None:
                    body=_read(None,item['reference'],context=other,db=db)
                    _require(metadata['class']=='compact' and body.get('kind') in {'authority-source-baseline','d4-recovery-source'} or
                        metadata['class']=='detail' and item['reference'] in guidance['references'],'Unknown linked scope content remains protected')
            physicals[_raw(authority)]=physical
            _require(sorted(path.name for path in (other.directory/'evidence').iterdir())==sorted(
                [item['reference']['name'] for item in physical if item['stat'] is not None]+[ref['name'] for ref in excluded]),'Unaccounted linked closure content remains protected')
    issued={(_raw(a['reference']['authority']),a['reference']['id']) for m in component['members'] for a in m['certificate'].get('assignments',[])}
    _require(not any(edge['need']=='raw' and (edge['kind']=='task' and _raw(edge['reference']) in owners or
        edge['kind']=='assignment' and (_raw(edge['reference']['authority']),edge['reference']['id']) in issued) for edge in requirements),
        'An independent consumer still needs original linked raw support')
    ready_files={}
    for row in component['basis']['members']:
        for path,value in row['inputs'].items():
            _require(path not in ready_files or ready_files[path]==value,'Linked physical source observations disagree');ready_files[path]=value
    _check_preparation_inputs(component,writer=writer);_check_ready_inputs(ready_files)
    _require(all(_closure_file_stat(Path(path))==value for path,value in files.items()),'Linked recovery source changed before closure commit')
    facts={}
    for member in component['members']:
        ref=member['reference'];task=member['task'];original=task['accepted_identity'];bindings={original['project_root']:original['project_binding']}
        bindings.update({original[k]:original['bindings'][label] for k,label in (('repository_root','root'),('primary_root','primary_root'),('git_dir','git_dir'),('git_common_dir','git_common_dir'))})
        facts[_raw(ref)]=dict(version=1,task_ref=ref,task=task,certificate=member['certificate'],bindings=bindings,recovery_files=files,
            observed=observations[_raw(ref)],physical=physicals[_raw(ref['authority'])],ready_files=ready_files,requirements=sorted(requirements,key=_raw),recovery=recovery,
            artifacts=[receipts[_raw(ref)]['artifact']],projection=member['projection'],guidance=member['guidance'],
            linked=dict(aggregate=pointer,authorities=authorities,component_digest=_digest(component)))
    for key,candidate in candidates.items():
        if key not in published:_require(candidate['content']==_closure_content(facts[key]),'Retained linked closure candidate is stale or substituted')
    if new_compact is not None:_require(_raw(task_ref) in candidates and candidates[_raw(task_ref)]['reference']==new_compact,
        'New linked closure compact lacks its actual registered owner')
    return facts[_raw(task_ref)]


def _retirement_content(facts):
    return facts['linked_retirement']['closure']['content'] if 'linked_retirement' in facts else _closure_content(facts)


def _linked_retained_requirements(component,contexts,*,writer=None):
    """Only authenticated preparation-origin routes may replace their own terminal owners."""
    from runtime import delegation
    owners={_raw(m['reference']) for m in component['members']}
    assignments={_raw(a['certificate']['reference']) for m in component['members'] for a in m['assignments']}
    selected={_raw(_canonical_plain(c.authority_set[0])):c for c in contexts}
    sources={_raw(s['reference']):s for s in component['sources']}
    roots={_raw(edge):edge for m in component['members'] for edge in m['preparation']['metadata']['dependencies']}
    pending=[dict(owner=edge['reference'],**edge,need='content') for edge in roots.values()];seen=set();requirements=[]
    while pending:
        edge=pending.pop();key=_raw(edge)
        if key in seen:continue
        seen.add(key);_require(len(seen)<=4096,'Retained preparation dependency traversal exceeds bound')
        requirements.append(edge);kind=edge['kind'];ref=edge['reference']
        authority=ref.get('authority',edge['owner']['authority']);context=selected.get(_raw(authority))
        _require(context is not None,'Retained raw dependency authority is outside complete guards')
        with _preparation_database(context,writer) as db:
            if kind=='artifact':
                qualified=dict(authority=authority,artifact=ref.get('artifact',ref));source=sources.get(_raw(qualified))
                _require(source is not None,'Retained preparation source route is incomplete')
                metadata,raw=_managed_artifact(None,qualified['artifact'],context=context,db=db);body=json.loads(raw)
                _require(metadata==source['metadata'] and _closure_file_stat(Path(metadata['managed']['path']))==source['stat'],
                    'Retained preparation dependency source changed')
                terminal=_raw(metadata['owner'].get('task')) in owners
                for dependency in metadata['dependencies']:
                    child=dependency['reference'];child_kind=dependency['kind'];need='content' if child_kind=='artifact' else 'raw'
                    if child_kind=='task' and (terminal and _raw(child) in owners or
                        child==metadata['owner'].get('task') and body.get('kind')!='linked-verification'):need='identity'
                    if child_kind=='assignment' and terminal and _raw(child) in assignments:need='identity'
                    pending.append(dict(owner=qualified,**dependency,need=need))
            elif kind=='task':
                state._task_reference(ref)
                if edge['need']=='raw':
                    _require(_linked_raw_task(db,ref) is not None,'Independent retained source requires its original raw task')
                elif _raw(ref) not in owners:
                    _lifecycle_requirements(context,[edge],db=db)
            elif kind=='assignment':
                if edge['need']=='identity':_require(_raw(ref) in assignments,'Unknown retained assignment attribution')
                else:
                    row=db.execute('select id,scope_id,client,session_id,task_id,dispatch_id,data from assignments where id=?',(ref['id'],)).fetchone()
                    _require(row is not None,'Independent retained source requires its original raw assignment')
                    record=delegation._record(None,row,context=context,db=db)
                    _require(record['owner']==ref['owner'] and record['data']['assignment']==ref['assignment'],
                        'Independent retained assignment pointer changed')
            else:raise state.StateError('Independent recovery or unknown retained raw dependency remains protected')
    return requirements


def _linked_retirement_requirements(component,contexts,*,writer=None):
    from runtime import delegation
    owners={_raw(m['reference']) for m in component['members']};requirements=_linked_retained_requirements(component,contexts,writer=writer)
    for context in contexts:
        authority=_canonical_plain(context.authority_set[0])
        with _preparation_database(context,writer) as db:
            rows=db.execute('select scope_id,client,session_id,task_id from tasks limit 4097').fetchall()
            _require(len(rows)<=4096,'Retirement current task inspection exceeds bound');roots=[]
            for row in rows:
                ref=dict(authority=authority,scope_id=row[0],client=row[1],session_id=row[2],task_id=row[3])
                if _raw(ref) in owners:continue
                task=state._task(db,*row)
                roots.extend(dict(owner=ref,**edge,need='content') for edge in _artifact_dependencies(task))
                linked=task.get('evidence',{}).get('linked_verification')
                if linked:roots.append(dict(owner=ref,kind='artifact',reference=dict(authority=linked['authority'],artifact=linked['reference']),need='content'))
            records=delegation._ledger(None,db,context=context)
            for record in records:
                owner=dict(authority=authority,**{key:record['owner'][key] for key in ('scope_id','client','session_id','task_id')})
                if _raw(owner) not in owners:roots.extend(dict(owner=dict(authority=authority,id=record['id']),**edge,need='content') for edge in _artifact_dependencies(record))
            guidance=delegation._closure_guidance(context,db,records)
            roots.extend(dict(owner=dict(authority=authority,source='native-guidance'),kind='artifact',reference=ref,need='content') for ref in guidance['references'])
            requirements.extend(_lifecycle_requirements(context,roots,db=db))
    return requirements


def _linked_retirement_facts(context,task_ref,pointer,authorities,*,writer=None,recovery=None,files=None):
    from runtime import changes
    component=_linked_retained_component(pointer,authorities,writer=writer)
    if component.get('discovered_authorities'):return component
    contexts=tuple(_reference_context(a) for a in authorities)
    if recovery is None:
        # Component ownership is authenticated separately; D4 owns every actual current root.
        recovery=_canonical_plain(changes._inspect_lifecycle_recovery_guarded(authorities,[]));files=_closure_recovery_files(recovery)
    _require(recovery['complete'] and not recovery['blockers'] and not recovery['discovered_authorities'] and
        sorted(recovery['authorities'],key=_raw)==sorted(authorities,key=_raw),'Linked retirement recovery/source coverage is incomplete')
    _require(_linked_closure_recovery_heads(authorities,writer=writer)==sorted(recovery['roots'],key=_raw),'Retirement recovery source head changed')
    requirements=[*recovery['requirements'],*_linked_retirement_requirements(component,contexts,writer=writer)]
    owners={_raw(m['reference']) for m in component['members']}
    issued={(_raw(a['certificate']['reference']['authority']),a['certificate']['reference']['id']) for m in component['members'] for a in m['assignments']}
    _require(not any(edge['need']=='raw' and (edge['kind']=='task' and _raw(edge['reference']) in owners or
        edge['kind']=='assignment' and (_raw(edge['reference']['authority']),edge['reference']['id']) in issued) for edge in requirements),
        'An independent consumer still requires linked raw history')
    _require(all(_closure_file_stat(Path(path))==value for path,value in files.items()),'Linked retirement recovery files changed')
    member=next(m for m in component['members'] if m['reference']==task_ref)
    if member['task'] is None:return dict(component=component,recovery=recovery,recovery_files=files,requirements=requirements,member=member)
    with _preparation_database(context,writer) as db:observed=state.inspect_dependencies(db,task_ref)
    _require(not [value for value in observed['blockers'] if value!='Assignment body requires original task; exact assignment certificate integration is required'],
        'Linked original event/assignment ownership remains uncertain')
    with _preparation_database(context,writer) as db:
        physical=_historical_inventory(context,db,observed['metadata'])
    _require(sorted(path.name for path in (context.directory/'evidence').iterdir())==sorted(item['reference']['name'] for item in physical if item['stat'] is not None),
        'Unaccounted content protects linked retirement')
    task=member['task'];closure=member['closure'];observed.pop('digest')
    projection={key:closure['content'][key] for key in ('outcomes','reviews','workers','numerical','verifications','native_guidance','scope_guidance','sources')}
    return dict(version=1,task_ref=task_ref,task=task,certificate=closure['content']['stopped'],observed=observed,physical=physical,
        bindings={},ready_files={},guidance=dict(retained=[],files={},folder=None),recovery=recovery,recovery_files=files,
        requirements=sorted(requirements,key=_raw),artifacts=closure['content']['artifacts'],projection=projection,
        linked_retirement=dict(aggregate=pointer,authorities=authorities,component=component,closure=closure,closed_at=member['closed_at']))


def _stamp_linked_retirement(context,db,task_ref,observation):
    facts=_check_closure_observation(context,db,task_ref,observation)
    if 'linked_retirement' in facts:
        retained=facts['linked_retirement'];ref=retained['closure']['reference'];closed_at=retained['closed_at']
        metadata=state._metadata(db,ref['name'])
        _require(metadata==retained['closure']['metadata'] and metadata['closed_at'] in (None,closed_at), 'Original closure metadata date changed')
    else:
        current=_linked_raw_task(db,task_ref)
        _require(current is not None,'Original task closure owner is unavailable')
        ref=current['lifecycle']['compact'];closed_at=current['lifecycle']['safe_closed_at']
        _require(closed_at is not None,'Task has no authenticated safe closure date')
        metadata,raw=_managed_artifact(None,ref,context=context,db=db)
        body=json.loads(raw);closure=current['lifecycle']['closure']
        _require(metadata['owner']==dict(kind='project',project_id=current['accepted_identity']['project_id'],task=task_ref)
            and metadata['class']=='compact' and metadata['created_at']==current['lifecycle']['created_at']
            and metadata['closed_at'] in (None,closed_at) and body==_closure_content(facts)
            and closure['task_revision']==current['revision']==body['revision']
            and closure['dependency_digest']==body['dependency_digest'] and closure['observed_at']==closed_at
            and closure['evidence']==body['artifacts'],
            'Original task closure metadata, content or age changed')
    metadata=dict(metadata,closed_at=closed_at)
    db.execute('update evidence_metadata set closed_at=?,data=? where name=?',(closed_at,_raw(metadata).decode(),ref['name']))
    _require(state._metadata(db,ref['name'])==metadata,'Closure date was not retained atomically')


def _check_linked_retirement(context,db,task_ref,facts,*,assignments_retired=False,retired=False):
    """Only the selected local certified removal is an allowed transition."""
    from runtime import changes
    expected=facts['linked_retirement'];current=_linked_retained_component(expected['aggregate'],expected['authorities'],writer=(context,db))
    _require(not current.get('discovered_authorities'),'Retirement source guard set changed')
    for original,observed in zip(expected['component']['members'],current['members']):
        if original['reference']!=task_ref:_require(observed==original,'Foreign linked lifecycle/marker support changed')
        else:
            before=original['closure']['metadata'];now=observed['closure']['metadata']
            _require(dict(now,closed_at=before['closed_at'])==before and now['closed_at'] in (before['closed_at'],expected['closed_at']) and
                observed['preparation']==original['preparation'] and observed['closure']['reference']==original['closure']['reference'] and
                observed['closure']['content']==original['closure']['content'],'Local linked compact/date correspondence changed')
            if not retired:_require(observed['task']==original['task'] and observed['task_marker'] is None,'Original linked raw task changed')
            else:_require(observed['task'] is None and observed['task_marker'] is not None,'Certified linked task did not retire')
            _require(all((a['marker'] is not None and a['record'] is None) if assignments_retired or retired else a==b
                for a,b in zip(observed['assignments'],original['assignments'])),'Linked assignment transition is incomplete')
    _require(current['basis']==expected['component']['basis'] and current['sources']==expected['component']['sources'], 'Linked retained source graph changed')
    _require(_linked_closure_recovery_heads(expected['authorities'],writer=(context,db))==sorted(facts['recovery']['roots'],key=_raw),'Retirement recovery source head changed')
    contexts=tuple(_reference_context(a) for a in expected['authorities'])
    _require(sorted([*facts['recovery']['requirements'],*_linked_retirement_requirements(current,contexts,writer=(context,db))],key=_raw)==facts['requirements'],
        'Linked independent raw/content requirements changed')
    for dependency in facts['recovery']['dependencies']:
        if 'source_artifact' not in dependency or dependency['source_artifact'] is None:continue
        selected=_reference_context(dependency['authority'])
        with _preparation_database(selected,(context,db)) as reader:content=_read(None,dependency['source_artifact'],context=selected,db=reader)
        _require(_digest(changes._validate_recovery_references(content,contexts))==dependency['generation_digest'], 'Retirement recovery raw owner generation changed')
    _require(all(_closure_file_stat(Path(path))==value for path,value in facts['recovery_files'].items()), 'Retirement journal/source file changed')


def _linked_historical_closure(context,db,task_ref):
    task=_linked_raw_task(db,task_ref)
    _require(task is None or task.get('writer_stop',{}).get('linked'),'Linked historical owner is unavailable')
    prepared=_linked_owned_preparation(context,db,task_ref)
    closed=_linked_closed_member(context,db,task_ref,task,prepared)
    return dict(version=1,task_ref=task_ref,task=task,retained_linked_closure=dict(preparation=prepared,closure=closed))


def _linked_closure_observation(contexts,task_ref,pointer):
    from runtime import changes
    authorities=[_canonical_plain(c.authority_set[0]) for c in contexts]
    with _linked_stop_guards(pointer,authorities) as complete:
        refs=[row['task'] for row in _linked_source(pointer)['members']]
        recovery=_canonical_plain(changes._inspect_lifecycle_recovery_guarded(complete,refs));files=_closure_recovery_files(recovery)
        context=_reference_context(task_ref['authority'])
        facts=_linked_closure_facts(context,task_ref,pointer,complete,recovery,files)
        return _ClosureObservation(_canonical_freeze(facts),context,_CLOSURE_ISSUER)


@contextmanager
def _closure_support_guards(contexts):
    """Discover retained guidance support structurally; only normal readers authorize it."""
    from runtime import changes
    contexts=tuple(contexts);pending={_raw(_canonical_plain(c.authority_set[0])):_canonical_plain(c.authority_set[0]) for c in contexts}
    for _ in range(4096):
        expanded=dict(pending)
        with changes._authority_guards([Path(a['directory']) for a in pending.values()]):
            for context in contexts:
                with _context_database(context) as db:
                    rows=db.execute("select name,digest from evidence_metadata where class='compact' limit 4097").fetchall()
                    _require(len(rows)<=4096,'Retained closure source discovery exceeds bound')
                    for name,digest in rows:
                        owner=state._metadata(db,name)['owner'].get('task')
                        if owner is None or state._retired(db,'task',{key:owner[key] for key in ('scope_id','client','session_id','task_id')}) is None:continue
                        value=_read(None,dict(name=name,digest=digest),context=context,db=db)
                        if value.get('kind') not in {'task-closure','linked-closure-preparation'} or not value.get('stopped',{}).get('linked'):continue
                        _,authorities,_=_linked_stop_sources(_linked_basis_root(value['stopped']['linked']),list(pending.values()))
                        expanded.update({_raw(a):a for a in authorities})
            _require(len(expanded)<=4096,'Retained closure source authority bound exceeded')
            if set(expanded)==set(pending):yield;return
        pending=expanded
    raise state.StateError('Retained closure support authority closure did not converge')


def _observe_closure(contexts, task_ref):
    """Internal owner observation. Types/flags authenticate nothing; writers rederive facts."""
    from runtime import changes
    contexts=tuple(contexts)
    context=next((c for c in contexts if _canonical_plain(c.authority_set[0])==task_ref['authority']),None)
    _require(context is not None,'Closure task authority differs')
    with _context_database(context) as db:
        task=state._task(db,task_ref['scope_id'],task_ref['client'],task_ref['session_id'],task_ref['task_id'])
        linked=task.get('writer_stop',{}).get('linked') if task else None
        historical=bool(linked and task['lifecycle']['safe_closed_at'] is not None)
        if linked and not historical:pointer=_linked_basis_root(_read(None,linked,context=context,db=db))
    if historical:
        with changes._authority_guards([context.directory],observe=True),_context_database(context) as db:
            return _ClosureObservation(_canonical_freeze(_linked_historical_closure(context,db,task_ref)),context,_CLOSURE_ISSUER)
    if linked:return _linked_closure_observation(contexts,task_ref,pointer)
    _require(len(contexts)==1,'Foreign owner closure needs complete terminal component integration')
    context=contexts[0];authority=_canonical_plain(context.authority_set[0])
    _require(task_ref['authority']==authority,'Closure task authority differs')
    with _closure_support_guards((context,)):
        recovery,files=_closure_recovery(context,task_ref)
        with _context_database(context) as db:
            return _ClosureObservation(_canonical_freeze(_closure_facts(context,task_ref,db,recovery,recovery_files=files)),context,_CLOSURE_ISSUER)


def _closure_content(facts):
    task=facts['task']
    return dict(version=1,kind='task-closure',identity=facts['task_ref'],pins=task['pins'],accepted_identity=task['accepted_identity'],
        created_at=task['lifecycle']['created_at'],revision=task['revision'],outcome=task['state'],coverage='historical-ready' if task['state']=='ready' else 'stopped-owner-only',
        stopped=facts['certificate'],artifacts=facts['artifacts'],**facts['projection'],usage='unknown',
        dependency_digest=_digest(facts),limitations=['Closure preserves historical outcome; it creates no current readiness or delivery authority',
            'Command values describe original local executions; native usage remains unknown'])


def _check_closure_observation(context, db, task_ref, observations, *, new_compact=None, retired=False, assignments_retired=False):
    """Final local recheck only; complete source interpretation precedes the writer."""
    facts=_issued_closure(context,observations)
    _require(isinstance(facts,dict) and facts.get('task_ref')==task_ref,'Closure snapshot identity is unavailable')
    _check_context(context,db)
    if 'linked_retirement' in facts:
        _check_linked_retirement(context,db,task_ref,facts,assignments_retired=assignments_retired,retired=retired)
    if 'retained_linked_closure' in facts:
        _require(new_compact is None and not retired and not assignments_retired,'Historical linked observation cannot publish new lifecycle evidence')
        _require(_linked_historical_closure(context,db,task_ref)==facts,'Retained linked closure envelope changed')
        return facts
    if 'linked' in facts:
        _require(not retired and not assignments_retired,'Linked raw retirement awaits the dependent lifecycle slice')
        linked=facts['linked']
        current=_linked_closure_facts(context,task_ref,linked['aggregate'],linked['authorities'],facts['recovery'],facts['recovery_files'],writer=(context,db),new_compact=new_compact)
        _require(current==facts,'Linked closure component, local rows or source facts changed')
        if new_compact is not None:_require(_read(None,new_compact,context=context,db=db)==_closure_content(facts),'Linked closure compact differs from original prepared facts')
        return facts
    current=state.inspect_dependencies(db,task_ref)
    compact=(current['task']['lifecycle']['compact'] if current['task'] else None) or new_compact
    if current['task'] is not None and 'linked_retirement' not in facts:
        current['task']=dict(current['task'],lifecycle=dict(created_at=current['task']['lifecycle']['created_at'],safe_closed_at=None,closure=None,compact=None))
    current['tasks']=[dict(row,task=current['task']) if row['reference']==task_ref else row for row in current['tasks']]
    if 'linked_retirement' not in facts:current['metadata']=[item for item in current['metadata'] if item['reference']!=compact]
    current.pop('digest')
    expected=deepcopy(facts['observed'])
    if 'linked_retirement' in facts:
        closure=facts['linked_retirement']['closure'];original=closure['metadata']
        for item in current['metadata']:
            if item['reference']==closure['reference']:
                _require(item['metadata']['closed_at'] in (original['closed_at'],facts['linked_retirement']['closed_at']),'Closure date changed')
                item['metadata']=dict(item['metadata'],closed_at=original['closed_at'])
    if assignments_retired or retired:
        certificates=facts['certificate'].get('assignments',[])
        ids={item['reference']['id'] for item in certificates}
        _require(not any(row[0] in ids for row in current['assignments']),'Certified retired assignment remains live')
        expected['assignments']=[row for row in expected['assignments'] if row[0] not in ids]
        expected['requirements']=[edge for edge in expected['requirements'] if not (
            edge['kind']=='assignment' and edge['reference']['id'] in ids)]
        expected['blockers']=[blocker for blocker in expected['blockers'] if blocker!=
            'Assignment body requires original task; exact assignment certificate integration is required']
        for item in certificates:
            ref=item['reference'];marker=state._retired_assignment(db,ref['id'])
            _require(marker is not None and state._retired(db,'assignment',ref['owner'])==marker
                and marker['identity']==ref['owner'] and marker['created_at']==item['created_at']
                and marker['pins_digest']==state._digest(facts['task']['pins'])
                and marker['request_digest']==item['request_digest'] and marker['outcome']==item['reconciliation']['outcome']
                and not marker['evidence_expired'],'Assignment retirement marker differs from exact original certificate')
    if retired:
        _require(current['task'] is None,'Retired owner unexpectedly remains live')
        identity=tuple(task_ref[k] for k in ('scope_id','client','session_id','task_id'))
        removed_turns={tuple(row[:4]) for row in expected['turns'] if tuple(row[:3])==identity[:3] and row[4]==identity[3]}
        expected['task']=None
        expected['tasks']=[row for row in expected['tasks'] if row['reference']!=task_ref]
        expected['bindings']=[row for row in expected['bindings'] if tuple(row)!=identity]
        expected['turns']=[row for row in expected['turns'] if tuple(row[:4]) not in removed_turns]
        expected['receipts']=[row for row in expected['receipts'] if tuple(row[:4]) not in removed_turns]
    _require(current==expected,'Closure rows, source heads, generation or metadata changed')
    _require(all(_binding(Path(path))==binding for path,binding in facts['bindings'].items()),'Closure checkout binding changed')
    for item in facts['physical']:
        if item['stat'] is None:
            _require(_historical_inventory(context,db,[item])==[item],'Historical diagnostic absence changed')
        else:
            _require(_closure_file_stat(Path(item['metadata']['managed']['path']))==item['stat'],'Closure source bytes or physical identity changed')
        for path,binding in item['metadata']['managed']['parents'].items():
            _require(_binding(Path(path))==binding,'Closure content parent changed')
    _require(all(_closure_file_stat(Path(path))==value for path,value in facts['recovery_files'].items()),'Recovery source changed before closure commit')
    _check_ready_inputs(facts['ready_files'])
    guidance=facts['guidance']
    for support in guidance['retained']:
        if 'linked_component' in support:
            component=support['linked_component']
            _require(_linked_retained_component(component['aggregate'],component['authorities'],writer=(context,db))==component,
                'Retained linked guidance provenance changed before closure commit')
        _require(state._retired(db,'task',{key:support['identity'][key] for key in ('scope_id','client','session_id','task_id')})==support['marker']
            and all(state._retired_assignment(db,identity)==marker for identity,marker in support['assignments']),
            'Retained guidance owner markers changed before closure commit')
    if guidance['folder'] is not None:
        _require(_binding(Path(guidance['folder']['path']))==guidance['folder']['binding'],'Guidance cache folder changed')
    from runtime import delegation
    for path,original in guidance['files'].items():
        _require(_closure_file_stat(Path(path))==original['stat']
            and hashlib.sha256(delegation._read_bytes(Path(path))).hexdigest()==original['digest'],
            'Guidance cache source changed before closure commit')
    names=sorted(path.name for path in (context.directory/'evidence').iterdir())
    expected=sorted(item['reference']['name'] for item in _historical_inventory(context,db,_evidence_inventory_rows(db))
        if item['stat'] is not None)
    _require(names==expected,'Unaccounted content appeared before closure commit')
    if compact is not None:
        _require(_read(None,compact,context=context,db=db)==_retirement_content(facts),'Compact support differs from original owner facts')
    return facts


def close_task(scope, request, observations):
    """Internal coordinator wrapper only; public JSON/CLI cannot supply closure authority."""
    _require(isinstance(scope,AcceptedScope),'Closure requires current accepted scope wrapper')
    state._fields(request,('client','session_id','task_id','scope_ref','expected_revision','expected_pins'))
    state._identity(request);state._integer(request['expected_revision'],'expected_revision',1)
    state._validate_pins(request['expected_pins'])
    context=_evidence_context(scope)
    task_ref=dict(authority=_canonical_plain(context.authority_set[0]),scope_id=state._scope_id(scope),
        **{k:request[k] for k in ('client','session_id','task_id')})
    from runtime import changes
    original=_issued_closure(context,observations);linked=original.get('linked')
    historical=False
    if linked or 'retained_linked_closure' in original:
        with _context_database(context) as db:
            current=state._task(db,task_ref['scope_id'],request['client'],request['session_id'],request['task_id'])
            historical=current is not None and current.get('writer_stop',{}).get('linked') and current['lifecycle']['safe_closed_at'] is not None
    if historical:
        with changes._authority_guards([context.directory],observe=True),_context_database(context) as db:
            retained=_linked_historical_closure(context,db,task_ref);task=retained['task']
            _require(original.get('task_ref')==task_ref and (original==retained if 'retained_linked_closure' in original else
                linked and _closure_content(original)==retained['retained_linked_closure']['closure']['content']),
                'Historical closure replay differs from exact published owner')
            _require(task['revision']==request['expected_revision'] and task['pins']==request['expected_pins'] and task['scope_ref']==request['scope_ref'],
                'Closure replay request differs from exact original owner')
            return dict(ok=True,task=task)
    guards=_linked_stop_guards(linked['aggregate'],linked['authorities']) if linked else _closure_support_guards((context,))
    with guards:
        if linked:
            refs=[row['task'] for row in _linked_source(linked['aggregate'])['members']]
            recovery=_canonical_plain(changes._inspect_lifecycle_recovery_guarded(linked['authorities'],refs));files=_closure_recovery_files(recovery)
            actual=_linked_closure_facts(context,task_ref,linked['aggregate'],linked['authorities'],recovery,files)
        else:
            recovery,files=_closure_recovery(context,task_ref)
            with _context_database(context) as reader:actual=_closure_facts(context,task_ref,reader,recovery,recovery_files=files)
        _require(actual==_issued_closure(context,observations),'Closure owner observation is stale or caller supplied')
        _require(actual['task']['revision']==request['expected_revision'] and actual['task']['pins']==request['expected_pins'] and
            actual['task']['scope_ref']==request['scope_ref'],'Closure request differs from exact original owner')
        issued=_ClosureObservation(_canonical_freeze(actual),context,_CLOSURE_ISSUER)
        if linked:
            with _context_database(context,write=True) as db:
                facts=_check_closure_observation(context,db,task_ref,issued)
                task=state._task(db,task_ref['scope_id'],request['client'],request['session_id'],request['task_id'])
                prepared=_linked_owned_preparation(context,db,task_ref)
                candidate=_linked_closure_candidate(context,db,task_ref,task,prepared)
                if candidate is None:
                    content=_closure_content(facts);dependencies=tuple(_canonical_freeze(dict(kind='artifact',reference=ref)) for ref in facts['artifacts'])
                    owner=_ClosureOwner(_canonical_freeze(task_ref),issued,_canonical_freeze(content),dependencies,task['lifecycle']['created_at'])
                    compact=_artifact(None,content,context=context,owner=owner,db=db)
                    _check_closure_observation(context,db,task_ref,issued,new_compact=compact)
                else:compact=candidate['reference']
            # Registration confers no closure. Reobserve before the lifecycle transaction.
            recovery=_canonical_plain(changes._inspect_lifecycle_recovery_guarded(linked['authorities'],refs));files=_closure_recovery_files(recovery)
            _require(_linked_closure_facts(context,task_ref,linked['aggregate'],linked['authorities'],recovery,files)==actual,
                'Linked closure changed after candidate registration')
            with _context_database(context,write=True) as db:
                facts=_check_closure_observation(context,db,task_ref,issued,new_compact=compact)
                task=state._task(db,task_ref['scope_id'],request['client'],request['session_id'],request['task_id'])
                _require(task['revision']==request['expected_revision'] and task['pins']==request['expected_pins'] and task['scope_ref']==request['scope_ref'],
                    'Closure request differs from exact original owner')
                if task['lifecycle']['safe_closed_at'] is not None:return dict(ok=True,task=task)
                return dict(ok=True,task=state._close_lifecycle(db,task_ref,issued,compact))
        with _context_database(context,write=True) as db:
            facts=_check_closure_observation(context,db,task_ref,issued);task=facts['task']
            _require(task['revision']==request['expected_revision'] and task['pins']==request['expected_pins']
                and task['scope_ref']==request['scope_ref'],'Closure request differs from exact original owner')
            actual=state._task(db,task_ref['scope_id'],request['client'],request['session_id'],request['task_id'])
            if actual['lifecycle']['safe_closed_at'] is not None:
                _require(_read(None,actual['lifecycle']['compact'],context=context,db=db)==_closure_content(facts),
                    'Retained closure compact support changed')
                return dict(ok=True,task=actual)
            content=_closure_content(facts)
            dependencies=tuple(_canonical_freeze(dict(kind='artifact',reference=ref)) for ref in facts['artifacts'])
            owner=_ClosureOwner(_canonical_freeze(task_ref),issued,_canonical_freeze(content),dependencies,task['lifecycle']['created_at'])
            compact=_artifact(None,content,context=context,owner=owner,db=db)
            _check_closure_observation(context,db,task_ref,issued,new_compact=compact)
            task=state._close_lifecycle(db,task_ref,issued,compact)
            return dict(ok=True,task=task)


def _evidence_inventory_rows(db):
    rows=db.execute('select name,digest,owner_key,class,created_at,closed_at,status,bytes,data from evidence_metadata order by name limit 4097').fetchall()
    _require(len(rows)<=4096,'Evidence inventory exceeds its observation bound')
    return [dict(reference=dict(name=row[0],digest=row[1]),metadata=state._metadata_record(row)) for row in rows]


def _diagnostic_proof(context, db, reference):
    """Authenticate one ordinary diagnostic and its surviving original proof, never its release."""
    from runtime import changes
    _check_context(context,db);state._artifact_reference(reference)
    metadata=state._metadata(db,reference['name'])
    _require(metadata is not None and metadata['version']==2 and metadata['class']=='detail'
        and metadata['export'] is None and not metadata['targets'],'Diagnostic metadata is unavailable or unsupported')
    subject=_source_subject(context,db,metadata);owner=metadata['owner']['task']
    _require(not subject['live'] and subject['closed_at'] is not None,'Diagnostic owner is not safely retired')
    closures=[]
    for row in _evidence_inventory_rows(db):
        other=row['metadata']
        if other['owner']!=metadata['owner'] or other['class']!='compact' or other['status']!='live':continue
        body=_read(None,row['reference'],context=context,db=db)
        if body.get('kind')=='task-closure':closures.append((row['reference'],other,body))
    _require(len(closures)==1,'Diagnostic needs unique retained ordinary closure')
    closure,closure_meta,compact=closures[0]
    _require(not compact.get('stopped',{}).get('linked') and compact['identity']==compact['stopped']['reference']==owner
        and compact['pins']==subject['pins']==compact['stopped']['pins']
        and compact['accepted_identity']==subject['identity'] and compact['created_at']==closure_meta['created_at']
        and closure_meta['closed_at']==subject['closed_at'],'Diagnostic original ordinary closure differs')
    changes._check_stopped_certificate(context,db,compact['stopped'])
    outcomes=[row for row in compact['outcomes'] if row['attempt'].get('kind')=='check'
        and row.get('execution',{}).get('output')==reference]
    _require(len(outcomes)==1,'Diagnostic output has ambiguous execution correspondence')
    outcome=outcomes[0];attempt=outcome['attempt'];execution_ref=attempt['execution']
    execution_meta,raw=_managed_artifact(None,execution_ref,context=context,db=db);execution=json.loads(raw)
    state._fields(execution,('command','tool','output','result'))
    _require(outcome['execution']==dict(command=execution['command'],tool=execution['tool'],output=execution['output'],
        result={key:value for key,value in execution['result'].items() if key!='private_output'})
        and execution['output']==reference,'Diagnostic execution projection differs')
    expected_owner=dict(kind='project',project_id=subject['identity']['project_id'],task=owner)
    for ref,other in ((reference,metadata),(execution_ref,execution_meta)):
        _require(other['owner']==expected_owner and other['class']=='detail'
            and compact['created_at']<=other['created_at']<=subject['closed_at'] and ref in compact['artifacts']
            and dict(reference=ref,created_at=other['created_at'],owner=other['owner'],bytes=other['bytes'],unit='bytes') in compact['sources'],
            'Diagnostic original source provenance differs')
    _require(metadata['dependencies']==[dict(kind='task',reference=owner)]
        and execution_meta['dependencies']==[dict(kind='task',reference=owner),*_artifact_dependencies(execution)]
        and closure_meta['owner']==expected_owner and closure_meta['dependencies']==[
            dict(kind='task',reference=owner),*[dict(kind='artifact',reference=ref) for ref in compact['artifacts']]],
        'Diagnostic original dependency correspondence differs')
    certificates=[row for row in compact['stopped'].get('assignments',[]) if row['reference']['id']==outcome['assignment_id']]
    _require(len(certificates)==1 and outcome['assignment_id']==attempt['id']==execution['result']['id'],
        'Diagnostic original assignment differs')
    certificate=certificates[0];assignment=state._retired_assignment(db,attempt['id'])
    _require(assignment is not None and state._retired(db,'assignment',certificate['reference']['owner'])==assignment
        and not assignment['evidence_expired'] and assignment['created_at']==certificate['created_at']
        and assignment['request_digest']==certificate['request_digest'] and assignment['pins_digest']==_digest(compact['pins'])
        and assignment['outcome']==outcome['outcome']==certificate['reconciliation']['outcome'],
        'Diagnostic retired assignment certificate differs')
    numbers=[row for row in compact['numerical'] if row['source']==execution_ref]
    _require(len(numbers)==2 and {row['field'] for row in numbers}=={'exit_code','output_bytes'},
        'Diagnostic original numerical coverage differs')
    for number in numbers:
        field=number['field']
        _require(number['value']==execution['result'][field]==attempt[field]
            and number['unit']==('bytes' if field=='output_bytes' else 'exit-code')
            and number['created_at']==execution_meta['created_at'] and number['assignment_id']==attempt['id']
            and number['owner']==certificate['reference']['owner'] and number['status']==execution['result']['status'],
            'Diagnostic authoritative numerical receipt differs')
    mandate=_source_mandate(context,reference,db=db);execution_mandate=_source_mandate(context,execution_ref,db=db)
    _require(_bookkeeping_record(context,db,mandate['reference'],mandate['content'])
        and _bookkeeping_record(context,db,execution_mandate['reference'],execution_mandate['content']),
        'Diagnostic publication mandates differ')
    path=context.directory/'evidence'/reference['name'];managed=metadata['managed']
    _require(managed['path']==str(path) and managed['sha256']==reference['digest']
        and all(_binding(Path(parent))==binding for parent,binding in managed['parents'].items()),
        'Diagnostic physical parents or reference changed')
    present=os.path.lexists(path)
    if metadata['status']=='live':
        _,raw=_managed_artifact(None,reference,context=context,db=db);availability='live'
    else:
        _require(metadata['closed_at']==subject['closed_at'],'Diagnostic intent lacks original closure date')
        _require(metadata['status']!='expired' or not present,'Expired diagnostic content reappeared')
        if present:raw=_managed_content(context,reference,metadata);availability='pending-present'
        else:raw=None;availability='expired' if metadata['status']=='expired' else 'pending-absent'
    if raw is not None:
        diagnostic=json.loads(raw);state._fields(diagnostic,('text','truncated','redacted_lines','redaction'))
        _require(isinstance(diagnostic['text'],str) and type(diagnostic['truncated']) is bool
            and type(diagnostic['redacted_lines']) is int and diagnostic['redacted_lines']>=0
            and isinstance(diagnostic['redaction'],str),'Diagnostic original shape differs')
    marker=state._retired(db,'task',{key:owner[key] for key in ('scope_id','client','session_id','task_id')})
    return dict(reference=reference,metadata=metadata,owner=owner,closed_at=subject['closed_at'],availability=availability,
        execution=execution_ref,execution_metadata=execution_meta,execution_body=execution,closure=closure,compact=compact,
        mandate=mandate,execution_mandate=execution_mandate,task_marker=marker,assignment_marker=assignment)


def _historical_inventory(context, db, rows):
    """Observe physical files or exact intent-backed diagnostic absence, never substitute bodies."""
    _require(len(rows)<=4096,'Historical evidence inventory exceeds bound')
    physical=[]
    for row in rows:
        reference=row['reference'];metadata=row['metadata'];path=Path(metadata['managed']['path'])
        _require(state._metadata(db,reference['name'])==metadata,'Historical metadata changed')
        if metadata['status']=='live':
            before=_closure_file_stat(path);_,raw=_managed_artifact(None,reference,context=context,db=db)
            _require(isinstance(json.loads(raw),dict) and _closure_file_stat(path)==before,'Historical content changed')
        else:
            proof=_diagnostic_proof(context,db,reference)
            before=None if proof['availability'] in {'expired','pending-absent'} else _closure_file_stat(path)
        physical.append(dict(reference=reference,metadata=metadata,stat=before))
    return physical


def _diagnostic_consumers(context, db, proof, recovery):
    """Report incomplete acquisition as protection, never as an empty consumer set."""
    try:
        return _observe_diagnostic_consumers(context,db,proof,recovery)
    except StartupError as error:
        return dict(complete=False,required=[],blockers=[str(error)])
    except (OSError,ValueError,TypeError,KeyError,IndexError,AttributeError,RecursionError,sqlite3.Error):
        return dict(complete=False,required=[],blockers=['Diagnostic current consumer coverage is incomplete'])


def _observe_diagnostic_consumers(context, db, proof, recovery):
    """Classify actual consumer roots; only exact retired bookkeeping routes retain provenance."""
    from runtime import delegation
    authority=_canonical_plain(context.authority_set[0]);owner=proof['owner'];output=proof['reference']
    _require(recovery['complete'] and not recovery['blockers'] and not recovery['discovered_authorities']
        and recovery['authorities']==[authority],'Diagnostic recovery coverage is incomplete or foreign')
    baseline=state._source_baseline(None,db,context=context)
    _require(baseline is not None and baseline['content']['source_contract']==2
        and baseline['content']['project_id']==proof['metadata']['owner']['project_id'],
        'Diagnostic prospective recovery provenance is unavailable')
    _require(_reverse_source_authorities(context,db,proof['metadata'])==[authority],
        'Diagnostic reverse consumers include another authority')
    _require(not _source_intents(context,output,db=db),'Diagnostic has an issued foreign destination intent')
    _require(not _source_intents(context,proof['execution'],db=db),'Diagnostic execution has a foreign destination intent')
    rows=_evidence_inventory_rows(db);physical=_historical_inventory(context,db,rows)
    _require(sorted(path.name for path in (context.directory/'evidence').iterdir())==
        sorted(row['reference']['name'] for row in physical if row['stat'] is not None),'Diagnostic inventory is incomplete')
    records={};blockers=[];required=[]
    for row in rows:
        metadata=row['metadata'];ref=row['reference']
        _require(metadata['owner']['kind']=='project' and metadata['owner']['project_id']==proof['metadata']['owner']['project_id'],
            'Diagnostic inventory contains foreign or unknown owners')
        _require(metadata['export'] is None and not metadata['targets'],'Managed copies remain protected')
        body=_read(None,ref,context=context,db=db) if metadata['status']=='live' else None
        records[_raw(ref)]=(metadata,body)
        if body is not None and body.get('kind')=='linked-closure-preparation':
            selected=metadata['owner'].get('task')
            if selected is None or state._retired(db,'task',{key:selected[key] for key in ('scope_id','client','session_id','task_id')}) is None:
                blockers.append('Issued unretired linked preparation retains its inventory')
    historical={_raw(ref) for ref in (proof['execution'],proof['closure'],proof['mandate']['reference'],proof['execution_mandate']['reference'])}
    allowed={_raw(ref) for ref in (proof['execution'],proof['closure'],proof['mandate']['reference'])}
    def needs(edges,root,historic=False):
        pending=[(edge,root) for edge in edges];seen=set()
        while pending:
            edge,parent=pending.pop();kind=edge['kind']
            if kind=='task':continue
            _require(kind in {'artifact','assignment','recovery'},'Unknown diagnostic consumer dependency')
            ref=edge['reference']
            _require(ref.get('authority',authority)==authority,'Foreign diagnostic consumer remains protected')
            ref=ref.get('artifact',ref.get('assignment',ref.get('reference',ref)))
            if ref==output:
                if historic and _raw(parent) in allowed:continue
                return True
            key=_raw(ref)
            if key in seen:continue
            seen.add(key);_require(len(seen)<=4096,'Diagnostic consumer traversal exceeds bound')
            _require(key in records,'Diagnostic consumer content is unavailable')
            metadata,body=records[key]
            if body is None:
                _diagnostic_proof(context,db,ref)
                continue
            pending.extend((child,ref) for child in [*metadata['dependencies'],*_artifact_dependencies(body)])
        return False
    for key,(metadata,body) in records.items():
        if key==_raw(output) or body is None:continue
        ref=dict(name=Path(metadata['managed']['path']).name,digest=metadata['managed']['sha256'])
        if needs([*metadata['dependencies'],*_artifact_dependencies(body)],ref,key in historical):required.append(ref)
    observed=state.inspect_dependencies(db,owner)
    _require(not observed['blockers'],'Diagnostic live row ownership is uncertain')
    for row in observed['tasks']:
        if row['task'].get('lifecycle',{}).get('safe_closed_at') is not None:
            blockers.append('Issued unretired closure retains its authority inventory')
        if needs(_artifact_dependencies(row['task']),row['reference']):required.append(row['reference'])
    ledger=delegation._ledger(None,db,context=context)
    guidance=delegation._closure_guidance(context,db,ledger)
    for reference in guidance['references']:
        if needs([dict(kind='artifact',reference=reference)],dict(authority=authority,source='native-guidance')):
            required.append(reference)
    for record in ledger:
        ref=dict(authority=authority,id=record['id'])
        if needs(_artifact_dependencies(record),ref):required.append(ref)
    for edge in recovery['requirements']:
        if edge['kind']=='task' and edge['reference']==owner and edge['need']=='raw':required.append(edge['owner'])
        elif edge['kind']!='task' and needs([edge],edge['owner']):required.append(edge['owner'])
    if required:blockers.append('Independent or unclassified consumers require diagnostic content')
    return dict(complete=True,required=required,blockers=sorted(set(blockers)))


def _cleanup_diagnostics(context):
    """Bounded ordinary age cleanup; shared cap and other content classes remain incomplete."""
    from runtime import changes
    report=dict(expired=[],pending=[],protected=[],limitations=[
        'Ordinary diagnostic age cleanup only; Project cap, temporary/export and compact expiry remain incomplete'])
    if _DIAGNOSTIC_CLEANUP.get() or getattr(changes._authority_context,'held',()):
        report['limitations'].append('Cleanup deferred within existing publication or authority guards')
        return report
    errors=(StartupError,OSError,ValueError,TypeError,KeyError,IndexError,AttributeError,RecursionError,sqlite3.Error)
    token=_DIAGNOSTIC_CLEANUP.set(True)
    try:
        with changes._authority_guards([context.directory]):
            with _context_database(context) as db:
                rows=_evidence_inventory_rows(db);candidates={}
                for row in rows:
                    metadata=row['metadata'];ref=row['reference']
                    if metadata['status']=='delete_pending':report['pending'].append(ref);candidates[_raw(ref)]=ref
                    if metadata['class']!='compact' or metadata['status']!='live':continue
                    try:
                        body=_read(None,ref,context=context,db=db)
                        if body.get('kind')=='task-closure' and not body.get('stopped',{}).get('linked'):
                            for outcome in body['outcomes']:
                                if outcome['attempt'].get('kind')=='check' and 'execution' in outcome:
                                    output=outcome['execution']['output'];candidates[_raw(output)]=output
                    except errors:
                        report['limitations'].append('Some retained owners are unavailable; cleanup coverage is incomplete')
                ordered=sorted(candidates.values(),key=lambda ref:(state._metadata(db,ref['name'])['created_at'],ref['name']))
            for reference in ordered:
                try:
                    def acquire(db):
                        proof=_diagnostic_proof(context,db,reference)
                        _require(state._owner_time()>=proof['closed_at']+604800,'Diagnostic has not reached seven days after safe closure')
                        permission=_source_current_permission(context,proof['execution_mandate']['content']['source'],db=db)
                        recovery,files=_closure_recovery(context)
                        consumers=_diagnostic_consumers(context,db,proof,recovery)
                        _require(consumers['complete'] and not consumers['blockers'],'; '.join(consumers['blockers']))
                        _require(_closure_recovery_files(recovery)==files,'Diagnostic recovery sources changed')
                        return proof,permission
                    with _context_database(context,write=True,durable=True) as db:
                        proof,permission=acquire(db)
                        if proof['availability']=='expired':
                            report['expired'].append(reference)
                            continue
                        metadata=proof['metadata']
                        if metadata['status']=='live':
                            pending=dict(metadata,status='delete_pending',closed_at=proof['closed_at'])
                            db.execute('update evidence_metadata set status=?,closed_at=?,data=? where name=?',
                                ('delete_pending',proof['closed_at'],_raw(pending).decode(),reference['name']))
                            _require(state._metadata(db,reference['name'])==pending,'Diagnostic pending intent differs')
                    if reference not in report['pending']:report['pending'].append(reference)
                    with _context_database(context,write=True,durable=True) as db:
                        current,current_permission=acquire(db)
                        _require(current['availability'] in {'pending-present','pending-absent'} and current_permission==permission,
                            'Diagnostic permission or pending ownership changed')
                        folder=context.directory/'evidence'
                        descriptor=os.open(folder,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
                        try:
                            info=os.fstat(descriptor)
                            _require(dict(device=info.st_dev,inode=info.st_ino)==current['metadata']['managed']['parents'][str(folder)],
                                'Diagnostic evidence directory changed')
                            if current['availability']=='pending-present':
                                _require(_source_current_permission(context,current['execution_mandate']['content']['source'],db=db)==permission,
                                    'Diagnostic enrollment permission changed before unlink')
                                _managed_content(context,reference,current['metadata'])
                                info=os.fstat(descriptor)
                                _require(all(_binding(Path(parent))==binding
                                    for parent,binding in current['metadata']['managed']['parents'].items())
                                    and _binding(folder)==dict(device=info.st_dev,inode=info.st_ino),
                                    'Diagnostic evidence parent changed before unlink')
                                info=os.stat(reference['name'],dir_fd=descriptor,follow_symlinks=False)
                                _require(dict(device=info.st_dev,inode=info.st_ino)==current['metadata']['managed']['binding']
                                    and stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1
                                    and stat.S_IMODE(info.st_mode)==current['metadata']['managed']['mode']
                                    and info.st_size==current['metadata']['managed']['bytes'],
                                    'Diagnostic pathname was replaced')
                                os.unlink(reference['name'],dir_fd=descriptor)
                            else:_require(not os.path.lexists(folder/reference['name']),'Absent pending diagnostic reappeared')
                            os.fsync(descriptor)
                        finally:os.close(descriptor)
                        _require(not os.path.lexists(folder/reference['name']) and all(_binding(Path(parent))==binding
                            for parent,binding in current['metadata']['managed']['parents'].items()),
                            'Diagnostic content or parent changed after unlink')
                        expired=dict(current['metadata'],status='expired')
                        db.execute('update evidence_metadata set status=?,data=? where name=?',('expired',_raw(expired).decode(),reference['name']))
                        _require(state._metadata(db,reference['name'])==expired,'Diagnostic expiry metadata differs')
                    report['pending'].remove(reference);report['expired'].append(reference)
                except errors as error:
                    report['protected'].append(dict(reference=reference,reason=str(error) if isinstance(error,StartupError)
                        else 'Diagnostic owner, consumers, age or physical release remains unproven'))
    finally:_DIAGNOSTIC_CLEANUP.reset(token)
    return report


def _diagnostic_output_routes(context, db, task_ref):
    """Observe typed diagnostic provenance; content requirements and permissions stay intact."""
    from runtime import changes,delegation
    report=dict(owner=task_ref,closed_at=None,coverage='classification-only',deletion_authorized=False,outputs=[])
    unavailable='Diagnostic provenance is incomplete or changed; original content remains protected'
    errors=(StartupError,OSError,ValueError,TypeError,KeyError,IndexError,AttributeError,RecursionError,sqlite3.Error)
    try:
        _check_context(context,db);state._task_reference(task_ref)
        authority=_canonical_plain(context.authority_set[0])
        _require(task_ref['authority']==authority,'Diagnostic owner authority differs')
        rows=db.execute('select name,digest from evidence_metadata order by name limit 4097').fetchall()
        _require(len(rows)<=4096,'Diagnostic source observation exceeds bound')
        records={};unknown=[]
        for name,digest in rows:
            ref=dict(name=name,digest=digest)
            try:
                metadata,raw=_managed_artifact(None,ref,context=context,db=db)
                body=json.loads(raw)
                _require(isinstance(body,dict),'Diagnostic consumer content is not an artifact object')
                records[_raw(ref)]=(ref,metadata,body)
            except errors:
                unknown.append(ref)
        closures=[row for row in records.values() if row[1]['class']=='compact'
            and row[1]['owner'].get('task')==task_ref and row[2].get('kind')=='task-closure']
        _require(len(closures)==1,'Diagnostic owner needs unique retained closure')
        closure,closure_meta,compact=closures[0]
        if compact.get('stopped',{}).get('linked'):
            report['blockers']=['Linked diagnostic content requires its complete owner classification']
            return report

        def reaches(edges,output):
            pending=list(edges);seen=set()
            while pending:
                edge=pending.pop()
                if edge['kind']!='artifact':continue
                ref=edge['reference']
                if ref.get('authority',authority)!=authority:continue
                ref=ref.get('artifact',ref.get('reference',ref))
                if ref==output:return True
                key=_raw(ref)
                if key in seen:continue
                seen.add(key);_require(len(seen)<=4096,'Diagnostic route traversal exceeds bound')
                if key in records:
                    _,metadata,body=records[key]
                    pending.extend(metadata['dependencies']);pending.extend(_artifact_dependencies(body))
            return False

        for outcome in compact['outcomes']:
            attempt=outcome['attempt'];projected=outcome.get('execution')
            if attempt.get('kind')!='check' or projected is None:continue
            output=projected['output'];execution_ref=attempt['execution']
            item=dict(reference=output,execution=execution_ref,closure=closure,routes=[],blockers=[])
            report['outputs'].append(item)
            try:
                proof=_diagnostic_proof(context,db,output)
                _require(proof['owner']==task_ref and proof['execution']==execution_ref and proof['closure']==closure,
                    'Diagnostic classification differs from its actual owner proof')
                mandate=proof['mandate']
                report['closed_at']=proof['closed_at']
                item['routes']=[dict(owner=execution_ref,kind='execution',disposition='diagnostic-provenance',
                    reason='Exact diagnostic child; execution and numerical evidence remain content-required'),
                    dict(owner=closure,kind='compact',disposition='diagnostic-provenance',
                    reason='Original compact records diagnostic provenance without reproducing its text'),
                    dict(owner=mandate['reference'],kind='mandate',disposition='bookkeeping',
                    reason='Authenticated birth mandate names the source and attributes its original task')]
                _source_intents(context,output,db=db)
                known={_raw(ref) for ref in (execution_ref,closure,mandate['reference'])}
                for key,(ref,metadata,body) in records.items():
                    if key not in known and reaches([*metadata['dependencies'],*_artifact_dependencies(body)],output):
                        item['routes'].append(dict(owner=ref,kind='other',disposition='protected',
                            reason='Independent or unclassified content route remains required'))
                observed=state.inspect_dependencies(db,task_ref)
                consumers=[(row['reference'],row['task']) for row in observed['tasks']]
                consumers.extend((dict(authority=authority,id=row[0]),delegation._record(None,row,context=context,db=db))
                    for row in observed['assignments'])
                for ref,body in consumers:
                    if reaches(_artifact_dependencies(body),output):
                        item['routes'].append(dict(owner=ref,kind='other',disposition='protected',
                            reason='Live task or assignment retains a content route'))
                if unknown:item['blockers'].append('Some managed consumers are unavailable; coverage remains incomplete')
                item['blockers'].extend(sorted({r['reason'] for r in item['routes'] if r['disposition']=='protected'}))
            except errors:
                item['routes']=[dict(owner=closure,kind='other',disposition='protected',reason=unavailable)]
                item['blockers']=[unavailable]
    except errors:
        report['blockers']=[unavailable]
    return report


def _retire_closed_task(context, task_ref):
    from runtime import changes,delegation
    protected=dict(owner=task_ref,closed_at=None,coverage='classification-only',deletion_authorized=False,outputs=[],
        blockers=['Linked diagnostic content requires its complete owner classification'])
    with _context_database(context) as reader:
        task=_linked_raw_task(reader,task_ref)
        if task is not None:linked=task.get('writer_stop',{}).get('linked')
        else:
            rows=reader.execute("select name,digest from evidence_metadata where class='compact' limit 4097").fetchall()
            _require(len(rows)<=4096,'Retired linked owner lookup exceeds bound')
            linked=None
            for name,digest in rows:
                metadata=state._metadata(reader,name)
                if metadata['owner'].get('task')==task_ref:
                    body=_read(None,dict(name=name,digest=digest),context=context,db=reader)
                    if body.get('kind')=='linked-closure-preparation':linked=body['stopped']['writer_stop']['linked'];break
        if linked:pointer=_linked_basis_root(_read(None,linked,context=context,db=reader))
    if linked:
        pending=[task_ref['authority']]
        for _ in range(4096):
            with _linked_stop_guards(pointer,pending) as complete:
                facts=_linked_retirement_facts(context,task_ref,pointer,complete)
                if facts.get('discovered_authorities'):
                    pending=sorted({_raw(a):a for a in [*complete,*facts['discovered_authorities']]}.values(),key=_raw);continue
                if 'member' in facts:
                    marker=facts['member']['task_marker']
                    return dict(retired=True,identity=marker['identity'],outcome=marker['outcome'],diagnostic_retention=protected)
                issued=_ClosureObservation(_canonical_freeze(facts),context,_CLOSURE_ISSUER)
                with _context_database(context,write=True) as db:
                    _check_closure_observation(context,db,task_ref,issued)
                    _stamp_linked_retirement(context,db,task_ref,issued)
                    delegation.retire_settled(db,task_ref,issued)
                    return state.retire_closed(db,task_ref,issued) | dict(diagnostic_retention=protected)
        raise state.StateError('Linked retirement source authority closure did not converge')
    with _closure_support_guards((context,)):
        recovery,files=_closure_recovery(context,task_ref)
        with _context_database(context) as reader:
            facts=_closure_facts(context,task_ref,reader,recovery,recovery_files=files)
        issued=_ClosureObservation(_canonical_freeze(facts),context,_CLOSURE_ISSUER)
        with _context_database(context,write=True) as db:
            _check_closure_observation(context,db,task_ref,issued)
            task=_linked_raw_task(db,task_ref)
            _require(task['lifecycle']['safe_closed_at'] is not None,'Task has no retained safe closure')
            compact=_read(None,task['lifecycle']['compact'],context=context,db=db)
            _require(compact==_closure_content(facts),'Closure support or current dependencies changed')
            _stamp_linked_retirement(context,db,task_ref,issued)
            delegation.retire_settled(db,task_ref,issued)
            result=state.retire_closed(db,task_ref,issued)
            return result | dict(diagnostic_retention=_diagnostic_output_routes(context,db,task_ref))


def _registered_owner(scope, context, owner, db):
    if isinstance(owner,_SourceMandateOwner):
        birth=owner.birth
        _require(_SOURCE_BIRTH.get() is birth and birth['issuer'] is _SOURCE_BIRTH_ISSUER and
            birth['scope'] is scope and birth['db'] is db and birth['context']==context,
            'Mandate requires its actual source-publication birth transaction')
        _registered_owner(scope,context,birth['owner'],db)
        metadata,_=_managed_artifact(None,birth['reference'],context=context,db=db)
        _require(metadata==birth['metadata'] and metadata['version']==2,'Mandate source birth changed')
        return metadata['owner'],metadata['owner']['task']
    if isinstance(owner,_ForeignIntentOwner):
        _validate_publication_plan(owner.plan)
        source=_canonical_plain(owner.source)
        mandate=_source_mandate(context,source['reference'],db=db)
        _source_current_permission(context,mandate['content']['source'],db=db)
        _require(_canonical_plain(owner.content)==_intent_content(owner.plan,source,mandate) and
            owner.created_at==mandate['metadata']['created_at'],'Foreign intent owner/content/original age changed')
        return mandate['metadata']['owner'],mandate['metadata']['owner']['task']
    if isinstance(owner,_PreparationOwner):
        ref=_canonical_plain(owner.reference);facts=_check_preparation_observation(owner.observation,writer=(context,db))
        member=_preparation_member(facts,ref)
        _require(ref['authority']==_canonical_plain(context.authority_set[0]) and _canonical_plain(owner.content)==_preparation_content(facts,ref) and
            owner.created_at==member['task']['lifecycle']['created_at'] and
            [_canonical_plain(edge) for edge in owner.dependencies]==_preparation_dependencies(facts),'Preparation owner content/age/dependencies changed')
        return dict(kind='project',project_id=member['task']['accepted_identity']['project_id'],task=ref),ref
    if isinstance(owner,_ClosureOwner):
        ref=_canonical_plain(owner.reference)
        facts=_check_closure_observation(context,db,ref,owner.facts)
        _require('retained_linked_closure' not in facts and 'linked_retirement' not in facts,'Historical replay/retirement cannot register new closure artifacts')
        _require(_canonical_plain(owner.content)==_closure_content(facts)
            and owner.created_at==facts['task']['lifecycle']['created_at']
            and [_canonical_plain(d) for d in owner.dependencies]==[dict(kind='artifact',reference=r) for r in facts['artifacts']],
            'Closure registration differs from existing owner-derived facts')
        return dict(kind='project',project_id=facts['task']['accepted_identity']['project_id'],task=ref),ref
    if isinstance(owner, _LinkedOwner):
        if owner.publication is not None:
            _check_foreign_intents(owner.publication,writer=(context,db))
            _require([_canonical_plain(edge) for edge in owner.dependencies]==_publication_dependencies(owner.publication),
                'Foreign publication dependencies differ from actual acquired sources/intents')
        return _registered_owner(scope, context, owner.task_owner, db)
    if isinstance(owner, _RecoveryOwner):
        from runtime import changes
        _check_recovery_registration(context,db,owner.source,owner)
        baseline = state._source_baseline(None, db, context=context)
        _require(baseline is not None and baseline['content']['project_id'] == owner.project_id, 'Recovery Project owner changed')
        return dict(kind='project', project_id=owner.project_id, task=None), None
    if isinstance(owner, _BaselineOwner):
        _require(scope is not None and owner.project_id == scope.project_id, 'Baseline Project owner changed')
        state._check_creation(context.database, owner.creation, db)
        return dict(kind='project', project_id=owner.project_id, task=None), None
    _require(isinstance(owner, _ArtifactOwner) and scope is not None and owner.project_id == scope.project_id,
             'Artifact requires an explicitly derived existing owner')
    if owner.task is None:
        _require(owner.purpose == 'guidance' and _canonical_plain(owner.pins) == state._pins(scope),
                 'Only existing scope guidance may omit a task owner')
        return dict(kind='project', project_id=owner.project_id, task=None), None
    reference = _canonical_plain(owner.task)
    state._task_reference(reference)
    _require(reference['authority'] == _canonical_plain(context.authority_set[0])
        and reference['scope_id'] == state._scope_id(scope), 'Artifact owner authority changed')
    task = state._task(db, reference['scope_id'], reference['client'], reference['session_id'], reference['task_id'])
    _require(task is not None and task['pins'] == _canonical_plain(owner.pins), 'Artifact original task owner is unavailable')
    state._compatible(scope, task)
    state._assert_open(task)
    _require(state._physical_identity(task['accepted_identity']) == state._physical_identity(_canonical_plain(scope.accepted_identity)),
        'Artifact original task physical owner changed')
    return dict(kind='project', project_id=owner.project_id, task=reference), reference


def _artifact_dependencies(value):
    references = {}
    def visit(item):
        if isinstance(item, dict):
            if set(item) in ({'authority','artifact'},{'authority','reference'}):
                ref=item.get('artifact',item.get('reference'))
                _authority_artifact(dict(authority=item['authority'],reference=ref))
                qualified=dict(authority=item['authority'],artifact=ref)
                references[_raw(qualified)]=dict(kind='artifact',reference=qualified)
            elif set(item) == {'name', 'digest'}:
                state._artifact_reference(item)
                references[_raw(item)] = dict(kind='artifact', reference=item)
            else:
                for child in item.values(): visit(child)
        elif isinstance(item, list):
            for child in item: visit(child)
    visit(value)
    _require(len(references) < 4096, 'Artifact dependency bound exceeded')
    return list(references.values())


def _mandate_name(reference):
    return _digest(['source-import-mandate',reference])[:32]+'.json'


def _source_subject(context,db,metadata):
    owner=metadata['owner'].get('task')
    _require(owner is not None and owner['authority']==_canonical_plain(context.authority_set[0]),
        'Source bookkeeping needs its actual task owner')
    task=_linked_raw_task(db,owner)
    if task is not None:
        _require(task['pins']['schema_version']==3 and task['lifecycle']['created_at']<=metadata['created_at'],
            'Source original task age/pins differ')
        return dict(identity=task['accepted_identity'],pins=task['pins'],scope_ref=task['scope_ref'],
            closed_at=task['lifecycle']['safe_closed_at'],live=True)
    marker=state._retired(db,'task',{key:owner[key] for key in ('scope_id','client','session_id','task_id')})
    rows=db.execute("select name,digest from evidence_metadata where class='compact' and status='live' limit 4097").fetchall()
    _require(len(rows)<=4096,'Source owner compact lookup exceeds bound');found=[]
    for name,digest in rows:
        other=state._metadata(db,name)
        if other['owner']!=metadata['owner']:continue
        body=_read(None,dict(name=name,digest=digest),context=context,db=db)
        if not isinstance(body,dict) or body.get('kind')!='task-closure':continue
        _require(marker is not None and not marker['evidence_expired'] and body['identity']==owner and
            marker['pins_digest']==_digest(body['pins']) and marker['outcome']==body['outcome'] and
            marker['created_at']==body['created_at']==other['created_at'] and other['closed_at'] is not None and
            marker['retired_at']>=other['closed_at']>=metadata['created_at'],'Source retired owner lacks its exact dated closure')
        found.append(dict(identity=body['accepted_identity'],pins=body['pins'],scope_ref=body['stopped']['scope_ref'],
            closed_at=other['closed_at'],live=False))
    _require(len(found)==1,'Source bookkeeping owner is unavailable or ambiguous')
    return found[0]


def _source_current_permission(context,source,*,db=None):
    """Reobserve current private-bookkeeping enrollment; never assert native readiness."""
    from runtime import onboarding
    from runtime.startup import decode_project_record,canonical_scope_projection
    with _preparation_database(context,None if db is None else (context,db)) as reader:
        metadata=state._metadata(reader,source['artifact']['name'])
        _require(metadata is not None and metadata['status']=='live' and metadata['owner']==source['owner'] and
            metadata['created_at']==source['created_at'],'Source current owner/age/status changed')
        subject=_source_subject(context,reader,metadata)
    identity=subject['identity'];project=Path(identity['project_root'])
    observed=onboarding._authority_observation(project,{'paths':0,'bytes':0},canonical_only=True)
    _require(not observed['error'] and observed['record'] is not None,'Current source enrollment authority is unavailable')
    record=decode_project_record(observed['record']);data=_canonical_plain(record.data)
    current=canonical_scope_projection(record,repository_id=identity['repository_id'],checkout_id=identity['checkout_id'],client=identity['client'])
    _require(current is not None,'Current source enrollment is unavailable');current=_canonical_plain(current)
    _require(state._physical_identity(current)==state._physical_identity(identity) and current['membership']['included'] and
        current['configuration']['runtime']==dict(schema_version=3,state_dir=str(context.directory)) and
        current['configuration']['runtime_digest']==state.runtime_fingerprint() and
        current['configuration']['policy_digest']==policy_digest(state.PACKAGE),'Current source bookkeeping permission/configuration changed')
    selected=next(c for r in data['repositories'] if r['repository_id']==identity['repository_id']
        for c in r['checkouts'] if c['checkout_id']==identity['checkout_id'])
    client=next(c for c in selected['clients'] if c['client']==identity['client'])
    _require(client['activation']['status']!='suspended','Current source bookkeeping permission is suspended')
    if subject['live']:
        _require(_digest(current)==source['pins']['accepted_scope_digest'],'Active source enrollment changed since its accepted publisher')
    bindings={identity['project_root']:identity['project_binding']}
    bindings.update({identity[k]:identity['bindings'][label] for k,label in
        (('repository_root','root'),('primary_root','primary_root'),('git_dir','git_dir'),('git_common_dir','git_common_dir'))})
    _require(all(_binding(Path(path))==binding for path,binding in bindings.items()),'Current source physical enrollment changed')
    path=project/state.PROJECT_FILE
    raw=onboarding._read_file(path,onboarding.MAX_REQUEST,expected_binding=observed['target']['binding'])
    _require(json_object(raw)==observed['record'],'Source authority changed during permission observation')
    return dict(path=str(path),stat=_closure_file_stat(path),sha256=hashlib.sha256(raw).hexdigest(),projection=current)


def _mandate_content(birth):
    metadata=birth['metadata'];subject=_source_subject(birth['context'],birth['db'],metadata)
    return dict(version=1,kind='source-import-mandate',source=dict(authority=_canonical_plain(birth['context'].authority_set[0]),
        artifact=birth['reference'],owner=metadata['owner'],scope_ref=subject['scope_ref'],pins=subject['pins'],
        created_at=metadata['created_at'],managed_binding=metadata['managed']),operation='protective-import-bookkeeping')


def _source_mandate(context,source_ref,*,db=None):
    with _preparation_database(context,None if db is None else (context,db)) as reader:
        source=state._metadata(reader,source_ref['name'])
        _require(source is not None and source['version']==2 and source['managed']['sha256']==source_ref['digest'],
            'Source lacks prospective publication provenance')
        name=_mandate_name(source_ref);metadata=state._metadata(reader,name)
        _require(metadata is not None,'Source has no source-publication bookkeeping mandate')
        ref=dict(name=name,digest=metadata['managed']['sha256']);actual,raw=_managed_artifact(None,ref,context=context,db=reader)
        value=json.loads(raw);state._fields(value,('version','kind','source','operation'))
        binding=value['source'];state._fields(binding,('authority','artifact','owner','scope_ref','pins','created_at','managed_binding'))
        subject=_source_subject(context,reader,source)
        _require(type(value['version']) is int and value['version']==1 and value['kind']=='source-import-mandate' and
            value['operation']=='protective-import-bookkeeping' and binding==dict(authority=_canonical_plain(context.authority_set[0]),
                artifact=source_ref,owner=source['owner'],scope_ref=subject['scope_ref'],pins=subject['pins'],created_at=source['created_at'],managed_binding=source['managed']) and
            actual['version']==2 and actual['class']=='compact' and actual['owner']==source['owner'] and
            actual['created_at']==source['created_at'] and actual['closed_at'] in (None,subject['closed_at']) and
            actual['dependencies']==[dict(kind='task',reference=source['owner']['task'])] and not actual['targets'] and actual['export'] is None,
            'Source bookkeeping mandate differs from actual publication/owner/age')
        return dict(reference=ref,metadata=actual,content=value)


def _issue_source_mandate(scope,context,db,owner,reference,metadata):
    publisher=owner.task_owner if isinstance(owner,_LinkedOwner) else owner
    if not isinstance(publisher,_ArtifactOwner) or publisher.task is None:return
    _require(scope is not None,'Source publication mandate needs its actual accepted publisher')
    birth=dict(scope=scope,context=context,db=db,owner=publisher,reference=reference,metadata=metadata,issuer=_SOURCE_BIRTH_ISSUER)
    token=_SOURCE_BIRTH.set(birth)
    try:_artifact_registered(scope,_mandate_content(birth),context,_SourceMandateOwner(birth),db)
    finally:_SOURCE_BIRTH.reset(token)


def _bookkeeping_record(context,db,reference,body):
    if not isinstance(body,dict):return False
    if body.get('kind')=='source-import-mandate':
        _require(_source_mandate(context,body['source']['artifact'],db=db)['reference']==reference,
            'Bookkeeping mandate is not its actual publication-owned receipt')
        return True
    if body.get('kind')=='foreign-content-intent':
        _require(any(record['reference']==reference for record in _source_intents(context,body['source']['artifact'],db=db)),
            'Bookkeeping intent is not its actual source-owned receipt')
        return True
    return False


def _linked_producer(scope,request,snapshot,db):
    """Authenticate the actual synchronous producer, not a supplied operation label."""
    from runtime import delegation
    task=snapshot['task'];reference=snapshot['reference']
    verification=_read(scope,snapshot['verification_ref'],db=db)
    record=next((r for r in delegation._ledger(scope,db) if r['id']==verification['barrier_id']),None)
    dispatch='verify:'+str(request['expected_revision'])+':'+request['purpose']
    _require(record is not None and record['owner']==dict(scope_id=reference['scope_id'],
        **{key:task[key] for key in ('client','session_id','task_id')},dispatch_id=dispatch) and
        record['data']['role']=='coordinator' and record['data']['status']=='settled' and
        _read(scope,record['body']['operation'],db=db)==dict(id=dispatch,kind='completion-verification',
            decision_ref=task['decision_ref'],claims_digest=_digest(record['data']['claims'])),
        'Foreign publication lacks its actual original synchronous producer')
    reconciliation=_read(scope,record['data']['reconciliation'],db=db)
    _require(reconciliation==dict(version=1,kind='synchronous-verification',barrier_id=record['id'],
        verification=snapshot['verification_ref'],revision=task['revision']),
        'Foreign publication producer differs from the exact settled verifier')
    return dict(id=record['id'],dispatch_id=dispatch,assignment=record['data']['assignment'],
        reconciliation=record['data']['reconciliation'])


def _validate_publication_plan(plan,*,writer=None):
    _require(isinstance(plan,_LinkedPublicationPlan) and plan.issuer is _FOREIGN_PLAN_ISSUER and plan.state['active'],
        'Foreign admission requires its live actual producer observation')
    from runtime import changes
    _require(changes._held_authority_guards(plan.state['directories']), 'Foreign publication authority guards expired')
    scope=plan.scope;context=_evidence_context(scope)
    with _preparation_database(context,writer) as db:
        _recheck_linked_rows(scope,db,_canonical_plain(plan.snapshots))
        selected=next(row for row in _canonical_plain(plan.snapshots) if row['reference']==_canonical_plain(plan.content)['selected'])
        _require(_linked_producer(scope,_canonical_plain(plan.request),selected,db)==_canonical_plain(plan.producer),
            'Foreign publication producer identity changed')
        _registered_owner(scope,context,_artifact_owner(scope,selected['task']),db)
    _require(_digest(_canonical_plain(plan.content))==plan.state['reference']['digest'], 'Foreign publication payload changed')
    return context


def _intent_key(plan,source):
    selected=next(s for s in _canonical_plain(plan.snapshots) if s['reference']==_canonical_plain(plan.content)['selected'])
    return _digest(dict(source=_canonical_plain(source),destination=selected['reference'],pins=selected['task']['pins'],
        producer=_canonical_plain(plan.producer),entry_revision=plan.request['expected_revision']))


def _intent_name(plan,source):return _intent_key(plan,source)[:32]+'.json'


def _intent_content(plan,source,mandate):
    content=_canonical_plain(plan.content);selected=next(s for s in _canonical_plain(plan.snapshots) if s['reference']==content['selected'])
    original=mandate['content']['source']
    return dict(version=1,kind='foreign-content-intent',mandate=dict(authority=source['authority'],artifact=mandate['reference']),
        logical_key=_intent_key(plan,source),source={key:original[key] for key in ('authority','artifact','owner','created_at')},
        destination=dict(authority=selected['reference']['authority'],task=selected['reference'],scope_ref=selected['task']['scope_ref'],
            pins=selected['task']['pins'],entry_revision=plan.request['expected_revision'],expected_revision=selected['task']['revision'],
            producer_id=_canonical_plain(plan.producer),request_digest=_digest(_canonical_plain(plan.request)),artifact=plan.state['reference']),
        observed_at=plan.state['observed_at'])


def _source_intents(context,source_ref,*,db=None):
    """Direct source-owned discovery, including protective incomplete destinations."""
    with _preparation_database(context,None if db is None else (context,db)) as reader:
        mandate=_source_mandate(context,source_ref,db=reader);source=mandate['content']['source'];found=[]
        rows=reader.execute("select name,digest from evidence_metadata where class='compact' and status='live' limit 4097").fetchall()
        _require(len(rows)<=4096,'Source intent discovery exceeds bound')
        for name,digest in rows:
            metadata=state._metadata(reader,name)
            if metadata['owner']!=source['owner']:continue
            ref=dict(name=name,digest=digest);body=_read(None,ref,context=context,db=reader)
            if not isinstance(body,dict) or body.get('kind')!='foreign-content-intent' or body.get('source',{}).get('artifact')!=source_ref:continue
            state._fields(body,('version','kind','mandate','logical_key','source','destination','observed_at'))
            target=body['destination'];state._fields(target,('authority','task','scope_ref','pins','entry_revision','expected_revision','producer_id','request_digest','artifact'))
            expected=dict(source=dict(authority=source['authority'],reference=source_ref),destination=target['task'],pins=target['pins'],
                producer=target['producer_id'],entry_revision=target['entry_revision'])
            _require(body['version']==1 and body['source']=={key:source[key] for key in ('authority','artifact','owner','created_at')} and
                body['mandate']==dict(authority=source['authority'],artifact=mandate['reference']) and body['logical_key']==_digest(expected) and
                name==body['logical_key'][:32]+'.json' and target['authority']==target['task']['authority'] and
                metadata['version']==2 and metadata['class']=='compact' and metadata['created_at']==source['created_at'] and
                metadata['closed_at'] in (None,mandate['metadata']['closed_at']) and not metadata['targets'] and metadata['export'] is None and
                metadata['dependencies']==[dict(kind='task',reference=source['owner']['task']),
                    dict(kind='artifact',reference=dict(authority=source['authority'],artifact=source_ref)),
                    dict(kind='artifact',reference=body['mandate'])], 'Source-owned foreign intent binding changed')
            _authority_artifact(dict(authority=target['authority'],reference=target['artifact']));state._task_reference(target['task'])
            state._validate_pins(target['pins']);state._integer(body['observed_at'],'intent observation age')
            found.append(dict(reference=ref,metadata=metadata,content=body))
        return found


def _linked_publication_plan(scope,request,content,snapshots,acquired,observed_sources,dependencies):
    from runtime import changes
    context=_evidence_context(scope);selected=next(s for s in snapshots if s['reference']==content['selected'])
    with _context_database(context) as db:producer=_linked_producer(scope,request,selected,db)
    inputs=_linked_inputs(snapshots);projection=_linked_projection(selected['reference'],selected['plan'])
    fresh={}
    shared,delivered,sources,deliveries=_linked_outcomes(projection,_digest(inputs),acquired,snapshots,selected['reference'],observed=fresh)
    for snapshot in snapshots:
        _linked_source(dict(authority=snapshot['reference']['authority'],reference=snapshot['verification_ref']),observed=fresh)
    blockers=sorted(set(shared+[message for row in snapshots for message in row['blockers']]))
    expected=dict(version=1,kind='linked-verification',purpose=request['purpose'],projection=projection,inputs=inputs,
        inputs_digest=_digest(inputs),observations=acquired,members=[dict(task=row['reference'],revision=row['task']['revision'],
            generation=row['generation'],verification=row['verification_ref']) for row in snapshots],selected=selected['reference'],
        publication_revision=selected['task']['revision']+1,implementation_verified=not blockers,delivery_complete=delivered,
        deliveries=deliveries,blockers=blockers)
    expected_dependencies=[dict(kind='task',reference=row['reference']) for row in snapshots if row['reference']!=selected['reference']]
    expected_dependencies += [dict(kind='artifact',reference=dict(authority=row['reference']['authority'],artifact=row['verification_ref'])) for row in snapshots]
    expected_dependencies += [dict(kind='artifact',reference=dict(authority=source['authority'],artifact=source['reference']))
        for source in sources if _raw(source) in fresh]
    _require(content==expected and dependencies==expected_dependencies and observed_sources==fresh,
        'Foreign publication plan differs from actual approved producer/source facts')
    directories={context.directory,*[s['context'].directory for s in snapshots],
        *[Path(source['authority']['directory']) for source,_ in observed_sources.values()]}
    _require(changes._held_authority_guards(directories),'Foreign publication plan lacks its complete actual guards')
    # Conflicting replay is rejected before allocation. Recover a durable planned identity first.
    plan=_LinkedPublicationPlan(scope,_canonical_freeze(request),_canonical_freeze(content),tuple(_canonical_freeze(row) for row in snapshots),
        _canonical_freeze(acquired),_canonical_freeze(observed_sources),_canonical_freeze(dependencies),_canonical_freeze(producer),
        _FOREIGN_PLAN_ISSUER,dict(active=True,directories=directories,reference=None,observed_at=state._owner_time(),intents={}))
    prior=[]
    for source,_ in observed_sources.values():
        if source['authority']==_canonical_plain(context.authority_set[0]):continue
        source_context=_reference_context(source['authority'])
        with _context_database(source_context) as db:
            metadata=state._metadata(db,source['reference']['name']);reverse=_reverse_source_authorities(source_context,db,metadata)
            try:records=_source_intents(source_context,source['reference'],db=db)
            except state.StateError:
                _require(_canonical_plain(context.authority_set[0]) in reverse,'Independent source lacks prospective bookkeeping mandate')
                records=[]
            for intent in records:
                if intent['content']['logical_key']==_intent_key(plan,source):prior.append(intent)
    if prior:
        original=prior[0]['content'];planned=original['destination']['artifact']
        _require(all(item['content']['destination']['artifact']==planned and item['content']['observed_at']==original['observed_at'] for item in prior) and
            planned['digest']==_digest(content) and original['destination']['request_digest']==_digest(request),
            'Foreign publication replay conflicts with its original payload/request')
        plan.state.update(reference=planned,observed_at=original['observed_at'])
    else:plan.state['reference']=dict(name=uuid.uuid4().hex+'.json',digest=_digest(content))
    _validate_publication_plan(plan)
    return plan


def _commit_foreign_intent(plan,source):
    """Durably publish protective source intent before any destination transaction."""
    destination=_validate_publication_plan(plan);context=_reference_context(source['authority'])
    _require(context.directory!=destination.directory and _raw(source) in plan.observed,'Intent source was not actually acquired by this producer')
    with _context_database(context,write=True,durable=True) as db:
        mandate=_source_mandate(context,source['reference'],db=db)
        _source_current_permission(context,mandate['content']['source'],db=db)
        content=_intent_content(plan,source,mandate)
        found=next((record for record in _source_intents(context,source['reference'],db=db) if record['reference']['name']==_intent_name(plan,source)),None)
        if found is None:
            owner=_ForeignIntentOwner(plan,_canonical_freeze(source),_canonical_freeze(content),mandate['metadata']['created_at'])
            reference=_artifact(None,content,context=context,owner=owner,db=db)
            found=dict(reference=reference,metadata=state._metadata(db,reference['name']),content=content)
        else:_require(found['content']==content,'Foreign source intent replay changed original bindings')
        _source_current_permission(context,mandate['content']['source'],db=db)
    # This is reached only after actual source COMMIT succeeds.
    plan.state['intents'][_raw(source)]=found
    return found


def _check_foreign_intents(plan,*,writer=None):
    destination=_validate_publication_plan(plan,writer=writer)
    _check_foreign_intent_sources(plan)
    return destination


def _check_foreign_intent_sources(plan):
    from runtime import changes
    _require(plan.state['active'] and changes._held_authority_guards(plan.state['directories']),
        'Foreign source final check outlived its complete guards')
    for key,original in plan.state['intents'].items():
        source=_canonical_plain(plan.observed[key][0]);context=_reference_context(source['authority'])
        with _context_database(context) as db:
            mandate=_source_mandate(context,source['reference'],db=db)
            _source_current_permission(context,mandate['content']['source'],db=db)
            actual=next((r for r in _source_intents(context,source['reference'],db=db) if r['reference']==original['reference']),None)
            _require(actual==original and actual['content']==_intent_content(plan,source,mandate), 'Foreign source intent changed before destination commit')
            metadata,_=_managed_artifact(None,source['reference'],context=context,db=db)
            _require(metadata==_canonical_plain(plan.observed[key][1]), 'Foreign source changed before destination commit')


def _publication_dependencies(plan):
    dependencies=_canonical_plain(plan.dependencies)
    for key,record in sorted(plan.state['intents'].items(),key=lambda pair:pair[0]):
        dependencies.append(dict(kind='artifact',reference=dict(authority=_canonical_plain(plan.observed[key][0]['authority']),artifact=record['reference'])))
    return dependencies


def _linked_publication_entry(scope,request):
    """Unpublished settled attempts cannot be restarted using a newly observed revision."""
    with state._database(scope) as db:
        task=_task(db,scope,request);verification=task.get('evidence',{}).get('verification')
        if verification is None:return
        previous=task['evidence'].get('linked_verification')
        _require(previous is not None,'Prior verifier has no exact linked publication; explicit operation recovery is required before rerun')
        content=_linked_source(previous,db=db)
        row=next((row for row in content['members'] if row['task']==content['selected']),None)
        _require(row is not None and row['verification']==verification and content['publication_revision']==task['revision'],
            'Prior linked producer is unpublished or changed; no automatic restart is admitted')


def _content_dependencies(dependencies,authority):
    sources={}
    for edge in dependencies:
        kind=edge['kind'];ref=edge['reference']
        if kind=='task':continue
        _require(kind in {'artifact','assignment','recovery'},'Unsupported content demand remains unadmitted')
        selected=ref.get('authority',authority)
        target=ref['assignment'] if kind=='assignment' else ref.get('artifact',ref)
        source=dict(authority=selected,reference=target);_authority_artifact(source)
        sources[_raw(source)]=source
    return list(sources.values())


def _owner_dependencies(value,owner,task_ref=None):
    if isinstance(owner,_SourceMandateOwner):dependencies=[]
    elif isinstance(owner,_ForeignIntentOwner):
        dependencies=[dict(kind='artifact',reference=dict(authority=_canonical_plain(owner.source['authority']),artifact=_canonical_plain(owner.source['reference']))),
            dict(kind='artifact',reference=_canonical_plain(owner.content)['mandate'])]
    else:
        special=isinstance(owner,(_RecoveryOwner,_LinkedOwner,_ClosureOwner,_PreparationOwner))
        dependencies=[_canonical_plain(edge) for edge in owner.dependencies] if special else _artifact_dependencies(value)
    if task_ref is not None and not isinstance(owner,_PreparationOwner):
        dependencies.insert(0,dict(kind='task',reference=task_ref))
    return dependencies


@contextmanager
def _current_content_acquisition(scope,request):
    """A real current accepted producer; cached facts or a mapping cannot issue it."""
    _require(isinstance(scope,AcceptedScope),'Content acquisition needs its actual current accepted producer')
    context=_evidence_context(scope)
    with _context_database(context) as db:
        task=_task(db,scope,request,revision=False,allow_cancelled=True)
        owner=_artifact_owner(scope,task);_registered_owner(scope,context,owner,db)
    token=_CONTENT_ACQUISITION.set((scope,context,owner))
    try:yield
    finally:_CONTENT_ACQUISITION.reset(token)


def _admitted_body_route(source,metadata,consumer):
    """Follow actual admitted edges; parser compatibility cannot promote old blind refs."""
    pending=[consumer];seen=set()
    while pending:
        current=pending.pop();key=_raw(current)
        if key in seen:continue
        seen.add(key);_require(len(seen)<=4096,'Content admission route exceeds bound')
        context=_reference_context(current['authority'])
        with _context_database(context) as db:
            parent,raw=_managed_artifact(None,current['reference'],context=context,db=db)
        if parent['version']!=2:continue
        if current==source:return True
        children=_content_dependencies(parent['dependencies'],current['authority'])
        if source in children:
            if source['authority']==current['authority']:return True
            selected=_reference_context(source['authority'])
            with _context_database(selected) as db:
                reverse=_reverse_source_authorities(selected,db,metadata,include_intents=False)
                if current['authority'] in reverse:return True
                for record in _source_intents(selected,source['reference'],db=db):
                    target=record['content']['destination']
                    receipt=dict(authority=source['authority'],reference=record['reference'])
                    if target['authority']==current['authority'] and target['artifact']==current['reference'] and receipt in children and parent['owner']['task']==target['task']:
                        return True
            raise state.StateError('Prospective foreign source lacks its exact source-owned destination admission')
        body=json.loads(raw)
        if parent['class']=='compact' and body.get('kind') in {'task-closure','linked-closure-preparation'}:
            linked=body.get('stopped',{}).get('linked')
            if linked:
                _linked_stop_shape(linked)
                _require(parent['owner'].get('task')==body['identity'] and parent['created_at']==body['created_at'],
                    'Projected source owner/age differs from its issued compact')
                members={_raw(row['task']) for row in linked['members']}
                if _raw(metadata['owner'].get('task')) in members and any(
                        original['reference']==source and original['metadata']==metadata for original in linked['sources']):return True
        pending.extend(children)
    return False


def _check_content_consumption(source,metadata,consumer):
    if metadata['version']==1:return
    if consumer is not None:
        _authority_artifact(consumer)
        _require(_admitted_body_route(source,metadata,consumer),'Legacy or unadmitted consumer cannot acquire prospective source content')
        return
    from runtime import changes
    acquisition=_CONTENT_ACQUISITION.get()
    _require(acquisition is not None,'Prospective content requires an admitted consumer or actual current acquisition')
    scope,destination,owner=acquisition
    with _context_database(destination) as db:_registered_owner(scope,destination,owner,db)
    authority=_canonical_plain(destination.authority_set[0])
    if authority!=source['authority']:
        selected=_reference_context(source['authority'])
        _require(changes._held_authority_guards([destination.directory,selected.directory]),'Current foreign acquisition lacks actual source/destination guards')
        with _context_database(selected) as db:
            reverse=_reverse_source_authorities(selected,db,metadata)
            original=_reverse_source_authorities(selected,db,metadata,include_intents=False)
        if authority not in original:
            mandate=_source_mandate(selected,source['reference'])
            _source_current_permission(selected,mandate['content']['source'])
        _require(changes._held_authority_guards([Path(a['directory']) for a in reverse]),
            'Current foreign acquisition lacks complete source authority guards')


def _reverse_source_authorities(context,db,metadata,*,include_intents=True):
    """Structural discoverability only; it never asserts an independent stop."""
    from runtime import changes
    authority=_canonical_plain(context.authority_set[0]);found={_raw(authority):authority}
    baseline,sources=changes._recovery_sources(context,validate_stops=False)
    if baseline is not None and baseline['content']['source_contract']==2:
        for ref,value in sources:
            for _,prior in _recovery_source_history(context,db,ref,value['identity'],validate_stops=False):
                found.update({_raw(other):other for other in prior['authorities']})
    if include_intents and metadata['version']==2 and metadata['class']=='compact':
        local=dict(name=Path(metadata['managed']['path']).name,digest=metadata['managed']['sha256'])
        value=_read(None,local,context=context,db=db)
        if value.get('kind')=='foreign-content-intent':
            records=_source_intents(context,value['source']['artifact'],db=db)
            _require(any(record['reference']==local for record in records),'Foreign receipt lacks exact source ownership')
            other=value['destination']['authority'];found[_raw(other)]=other
    mandate=None
    if include_intents:
        try:mandate=_source_mandate(context,dict(name=Path(metadata['managed']['path']).name,digest=metadata['managed']['sha256']),db=db)
        except state.StateError:pass
    if mandate is not None:
        for record in _source_intents(context,mandate['content']['source']['artifact'],db=db):
            other=record['content']['destination']['authority'];found[_raw(other)]=other
    owner=metadata['owner'].get('task')
    if owner is not None:
        task=_linked_raw_task(db,owner)
        plan_refs=[]
        if task is not None and 'evidence' in task:
            evidence=task['evidence']
            plan_refs=[entry['plan'] for entry in [evidence,*evidence.get('history',[])] if 'plan' in entry]
        elif task is None:
            rows=db.execute("select name,digest from evidence_metadata where class='compact' and status='live' limit 4097").fetchall()
            _require(len(rows)<=4096,'Source reverse discovery exceeds its live bound')
            marker=state._retired(db,'task',{key:owner[key] for key in ('scope_id','client','session_id','task_id')})
            closed=[]
            for name,digest in rows:
                compact_meta=state._metadata(db,name)
                if compact_meta['owner']!=metadata['owner']:continue
                value=_read(None,dict(name=name,digest=digest),context=context,db=db)
                if value.get('kind')!='task-closure':continue
                _require(marker is not None and not marker['evidence_expired'] and value['identity']==owner and
                    compact_meta['closed_at'] is not None and marker['created_at']==value['created_at']==compact_meta['created_at'] and
                    marker['outcome']==value['outcome'] and marker['pins_digest']==_digest(value['pins']) and
                    marker['retired_at']>=compact_meta['closed_at'],'Retired reverse-discovery owner lacks its exact dated closure')
                closed.append(value)
            _require(len(closed)==1,'Retired reverse-discovery closure is unavailable or ambiguous')
            for source in closed[0]['sources']:
                ref=source['reference'];selected=ref.get('authority',authority)
                target=ref.get('artifact',ref)
                target_metadata=state._metadata(db,target['name'])
                if selected==authority and target_metadata is not None and target_metadata['status']=='live' and target_metadata['owner']==metadata['owner']:
                    value=_read(None,target,context=context,db=db)
                    if isinstance(value,dict) and value.get('version')==2 and 'linked' in value:plan_refs.append(target)
        for plan_ref in {_raw(ref):ref for ref in plan_refs}.values():
            plan_meta,raw=_managed_artifact(None,plan_ref,context=context,db=db)
            _require(plan_meta['owner']==metadata['owner'],'Source discovery plan owner differs')
            plan=json.loads(raw)
            if plan.get('version')==2:
                _plan(plan);projection=_linked_projection(owner,plan)
                found.update({_raw(row['task']['authority']):row['task']['authority'] for row in projection['participants']})
    return sorted(found.values(),key=_raw)


def _admit_content_dependencies(context,db,dependencies,*,owner=None):
    """Serialize admission with local retirement intent; cached bytes confer no right."""
    from runtime import changes
    _check_context(context,db)
    # A supplied deferred transaction must obtain the write reservation before reading sources.
    db.execute('update evidence_metadata set status=status where 0')
    authority=_canonical_plain(context.authority_set[0]);observed=[]
    for source in _content_dependencies(dependencies,authority):
        foreign=source['authority']!=authority
        selected=_reference_context(source['authority']) if foreign else context
        if foreign:
            _require(changes._held_authority_guards([context.directory,selected.directory]),
                'Foreign content admission requires actual source/destination guards before the write transaction')
        with _preparation_database(selected,(context,db)) as reader:
            metadata,raw=_managed_artifact(None,source['reference'],context=selected,db=reader)
            if foreign:
                if isinstance(owner,_RecoveryOwner):
                    lifetime=changes._check_d4_publication(owner.source,context,db)
                    _require(lifetime['kind']=='release' or any(item['reference']==dict(authority=source['authority'],artifact=source['reference'])
                        and item['metadata']==metadata for item in lifetime['permissions']['sources']),
                        'D4 body is outside its exact authorized source acquisition')
                    _require(metadata['version']==2,'Legacy foreign source remains unadmitted')
                    observed.append((source,metadata,hashlib.sha256(raw).hexdigest()))
                    continue
                reverse=_reverse_source_authorities(selected,reader,metadata)
                _require(authority in reverse and changes._held_authority_guards([Path(a['directory']) for a in reverse]),
                    'Foreign content destination is not in its complete reverse-discoverable inventory')
            observed.append((source,metadata,hashlib.sha256(raw).hexdigest()))
    return observed


@contextmanager
def _artifact_content_guards(context,value,owner):
    from runtime import changes
    authority=_canonical_plain(context.authority_set[0])
    sources=_content_dependencies(_owner_dependencies(value,owner),authority)
    foreign=[source for source in sources if source['authority']!=authority]
    if not foreign:yield;return
    pending={context.directory,*[Path(source['authority']['directory']) for source in foreign]}
    if changes._held_authority_guards(pending):yield;return
    _require(not getattr(changes._authority_context,'held',()),'Foreign content registration cannot expand a partial guard set')
    for _ in range(4096):
        with changes._authority_guards(pending):
            expanded=set(pending)
            for source in foreign:
                selected=_reference_context(source['authority'])
                with _context_database(selected) as reader:
                    metadata,_=_managed_artifact(None,source['reference'],context=selected,db=reader)
                    expanded.update(Path(a['directory']) for a in _reverse_source_authorities(selected,reader,metadata))
            if expanded!=pending:pending=expanded;continue
            yield;return
    raise state.StateError('Foreign content guard discovery did not converge')


def _artifact(scope, value, *, context=None, owner=None, db=None):
    """Register observed bytes before use; rollback leaves a protected unaccounted orphan.

    Existing schema-1/2 behavior is unchanged. An internal context represents trusted
    coordinator selection, never authentication of a caller-provided mapping.
    """
    if scope is not None and state._scope_version(scope) != 3:
        raw = _raw(value)
        _require(len(raw) <= MAX_ARTIFACT, 'Evidence artifact size limit exceeded')
        path = _folder(scope, create=True) / (uuid.uuid4().hex + '.json')
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        return dict(name=path.name, digest=hashlib.sha256(raw).hexdigest())
    _require((scope is None) != (context is None), 'Select exactly one existing evidence authority')
    context = context or _evidence_context(scope)
    if db is None:
        _cleanup_diagnostics(context)
        with _artifact_content_guards(context,value,owner),_context_database(context, write=True) as connection:
            return _artifact_registered(scope, value, context, owner, connection)
    _check_context(context, db)
    return _artifact_registered(scope, value, context, owner, db)


def _artifact_registered(scope, value, context, owner, db):
    metadata_owner, task_ref = _registered_owner(scope, context, owner, db)
    raw = _raw(value)
    _require(len(raw) <= MAX_ARTIFACT, 'Evidence artifact size limit exceeded')
    recovery = isinstance(owner, _RecoveryOwner)
    if recovery or isinstance(owner,(_ClosureOwner,_PreparationOwner)):
        _require(value == _canonical_plain(owner.content), 'Artifact differs from owner-derived content')
    if isinstance(owner,_SourceMandateOwner):_require(value==_mandate_content(owner.birth),'Mandate differs from actual publication birth')
    if isinstance(owner,_ForeignIntentOwner):_require(value==_canonical_plain(owner.content),'Intent differs from actual owner-derived content')
    dependencies = _owner_dependencies(value,owner,task_ref)
    _admit_content_dependencies(context,db,dependencies,owner=owner)
    folder = context.directory / 'evidence'
    try:
        folder.mkdir(mode=0o700)
    except FileExistsError:
        pass
    state._private(folder, True)
    parents = {str(folder): _binding(folder), str(context.directory): _binding(context.directory)}
    if isinstance(owner,_SourceMandateOwner):name=_mandate_name(owner.birth['reference'])
    elif isinstance(owner,_ForeignIntentOwner):name=_intent_name(owner.plan,owner.source)
    elif isinstance(owner,_LinkedOwner) and owner.publication is not None:
        _require(value==_canonical_plain(owner.publication.content),'Foreign publication payload differs from actual plan')
        name=owner.publication.state['reference']['name']
    else:name = state._source_baseline_name(_canonical_plain(owner.creation.authority)) if isinstance(owner, _BaselineOwner) else uuid.uuid4().hex + '.json'
    path = folder / name
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
        info = os.fstat(stream.fileno())
    directory_fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    digest = hashlib.sha256(raw).hexdigest()
    baseline = isinstance(owner, _BaselineOwner)
    created = owner.birth['metadata']['created_at'] if isinstance(owner,_SourceMandateOwner) else owner.creation.created_at if baseline else owner.created_at if recovery or isinstance(owner,(_ClosureOwner,_PreparationOwner,_ForeignIntentOwner)) else state._owner_time()
    content_class = 'compact' if baseline or recovery or isinstance(owner,(_ClosureOwner,_PreparationOwner,_SourceMandateOwner,_ForeignIntentOwner)) else 'detail'
    if baseline:
        expected = dict(version=1, kind='authority-source-baseline', source_contract=2,
            authority=_canonical_plain(owner.creation.authority), project_id=owner.project_id,
            created_at=created, runtime_digest=state.runtime_fingerprint())
        _require(value == expected and not dependencies, 'Baseline content differs from fresh owner provenance')
        state._check_creation(context.database, owner.creation, db)
    data = dict(version=2, owner=metadata_owner, created_at=created, **{'class': content_class}, bytes=len(raw),
        status='live', closed_at=None, dependencies=dependencies, targets=[], export=None,
        managed=dict(path=str(path), binding=dict(device=info.st_dev, inode=info.st_ino), parents=parents,
            sha256=digest, mode=stat.S_IMODE(info.st_mode), bytes=info.st_size))
    row = (path.name, digest, 'project:' + metadata_owner['project_id'], content_class, created, None, 'live', len(raw), _raw(data).decode())
    state._metadata_record(row)
    _check_context(context, db)
    _require(all(_binding(Path(parent)) == binding for parent, binding in parents.items())
        and _binding(path) == data['managed']['binding'], 'Artifact identity changed before registration')
    db.execute('insert into evidence_metadata values(?,?,?,?,?,?,?,?,?)', row)
    reference=dict(name=path.name,digest=digest)
    _issue_source_mandate(scope,context,db,owner,reference,data)
    return reference


def _managed_artifact(scope, reference, *, context=None, db=None):
    """Reobserve stored physical ownership; matching bytes alone cannot adopt a replacement."""
    _require((scope is None) != (context is None), 'Select exactly one existing evidence authority')
    context = context or _evidence_context(scope)
    if db is None:
        with _context_database(context) as connection:
            metadata = state._metadata(connection, reference['name'])
    else:
        _check_context(context, db)
        metadata = state._metadata(db, reference['name'])
    _require(metadata is not None and metadata['status'] == 'live', 'Artifact accounting unavailable or expired')
    return metadata, _managed_content(context,reference,metadata)


def _managed_content(context, reference, metadata):
    """Validate exact managed bytes; the caller owns its separate lifecycle-status permission."""
    managed = metadata['managed']
    path = context.directory / 'evidence' / reference['name']
    _require(managed['path'] == str(path) and managed['sha256'] == reference['digest'], 'Artifact metadata reference mismatch')
    _require(all(_binding(Path(parent)) == binding for parent, binding in managed['parents'].items()),
             'Artifact parent identity changed')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        raw = stream.read(MAX_ARTIFACT + 1)
    _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1
        and info.st_mode & 0o377 == 0 and len(raw) <= MAX_ARTIFACT
        and dict(device=info.st_dev, inode=info.st_ino) == managed['binding'] and stat.S_IMODE(info.st_mode) == managed['mode']
        and info.st_size == managed['bytes'] == len(raw) and hashlib.sha256(raw).hexdigest() == managed['sha256'],
        'Artifact physical ownership changed')
    return raw


def _read(scope, reference, *, context=None, db=None):
    state._fields(reference, ('name', 'digest'))
    _require(isinstance(reference['name'], str) and re.fullmatch(r'[0-9a-f]{32}\.json', reference['name']),
             'Invalid evidence artifact reference')
    _require((scope is None) != (context is None), 'Select exactly one existing evidence authority')
    try:
        if context is not None or state._scope_version(scope) == 3:
            _, raw = _managed_artifact(scope, reference, context=context, db=db)
        else:
            path = _folder(scope) / reference['name']
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, 'rb') as stream:
                info = os.fstat(stream.fileno())
                _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1
                         and info.st_mode & 0o377 == 0, 'Evidence artifact is unsafe or mutable')
                raw = stream.read(MAX_ARTIFACT + 1)
            _require(len(raw) <= MAX_ARTIFACT and hashlib.sha256(raw).hexdigest() == reference['digest'],
                     'Evidence artifact integrity failed')
        # Artifact JSON was generated here, and can exceed the external request bound.
        result = json.loads(raw)
        _require(isinstance(result, dict), 'Invalid evidence artifact')
        return result
    except (OSError, ValueError, TypeError):
        raise state.StateError('Evidence artifact unavailable, unsafe or corrupt') from None


def validate_evidence(value, *, canonical=False):
    _bounded(value)
    state._fields(value, ('version', 'plan', 'candidate', 'attempts'),
        ('verification', 'history') + (('linked_verification',) if canonical else ()))
    _require(type(value['version']) is int and value['version'] == VERSION and isinstance(value['attempts'], list)
             and len(value['attempts']) <= MAX_ATTEMPTS, 'Unsupported or oversized task evidence')
    if 'linked_verification' in value:
        _authority_artifact(value['linked_verification'])
    seen = set()
    for attempt in value['attempts']:
        _require(isinstance(attempt, dict) and isinstance(attempt.get('id'), str) and
                 re.fullmatch(r'[0-9a-f]{32}', attempt['id']) and attempt['id'] not in seen and
                 attempt.get('kind') in {'check', 'review'} and attempt.get('status') in
                 {'reserved', 'running', 'passed', 'failed', 'timed-out', 'uncertain', 'changed-inputs',
                  'collected', 'assessed', 'not-run', 'cancelled'}, 'Invalid or ambiguous evidence attempt')
        seen.add(attempt['id'])
        for key in ('candidate_digest', 'plan_digest'):
            _require(isinstance(attempt.get(key), str) and re.fullmatch(r'[0-9a-f]{64}', attempt[key]),
                     'Invalid evidence candidate or definition binding')
    for reference in [value['plan'], value['candidate'], *[a['candidate'] for a in value['attempts']]]:
        state._fields(reference, ('name', 'digest'))
        _require(isinstance(reference['name'], str) and re.fullmatch(r'[0-9a-f]{32}\.json', reference['name']) and
                 isinstance(reference['digest'], str) and re.fullmatch(r'[0-9a-f]{64}', reference['digest']),
                 'Invalid evidence artifact reference')


def _load_plan(scope, identity):
    with state._database(scope) as db:
        task = state._task(db, state._scope_id(scope), identity['client'], identity['session_id']) if db else None
        _require(task is not None and all(task[k] == identity[k] for k in IDENTITY[:4]) and 'evidence' in task,
                 'Evidence plan is missing')
        state._compatible(scope, task)
        return _read(scope, task['evidence']['plan'])


def _relative(value):
    _require(isinstance(value, str) and value and '\x00' not in value and '\n' not in value,
             'Invalid evidence relative path')
    path = Path(value)
    _require(not path.is_absolute() and '..' not in path.parts and str(path) == value, 'Unsafe evidence relative path')
    return value


def _delivery(value):
    if value is None:
        return
    state._fields(value, ('provider', 'repository', 'target', 'pull_request'))
    for field in value:
        state._text(value[field], 'linked delivery ' + field)


def _linked(value):
    state._fields(value, ('acceptance', 'delivery', 'companions'))
    _delivery(value['delivery'])
    _require(isinstance(value['acceptance'], list) and 0 < len(value['acceptance']) <= 32,
             'Missing bounded shared acceptance')
    ids = set()
    for criterion in value['acceptance']:
        state._fields(criterion, ('id', 'text'))
        state._text(criterion['id'], 'shared criterion id', 128)
        state._text(criterion['text'], 'shared criterion text')
        _require(criterion['id'] not in ids, 'Duplicate shared criterion')
        ids.add(criterion['id'])
    _require(isinstance(value['companions'], list) and len(value['companions']) <= 64,
             'Invalid bounded companion set')
    seen = set()
    for companion in value['companions']:
        state._fields(companion, ('task', 'delivery'))
        state._task_reference(companion['task'])
        _delivery(companion['delivery'])
        identity = _raw(companion['task'])
        _require(identity not in seen, 'Duplicate linked task')
        seen.add(identity)


def _linked_projection(task_ref, plan):
    """Compare approved participants; equality cannot prove scope completeness."""
    state._task_reference(task_ref)
    _require(plan.get('version') == 2, 'Linked acceptance requires plan version 2')
    linked = plan['linked']
    _linked(linked)
    _require(all(row['task'] != task_ref for row in linked['companions']), 'Self companion is forbidden')
    participants = [dict(task=task_ref, delivery=linked['delivery']), *linked['companions']]
    return deepcopy(dict(acceptance=sorted(linked['acceptance'], key=lambda row: row['id']),
                         participants=sorted(participants, key=lambda row: _raw(row['task']))))


def _plan(value):
    _bounded(value)
    state._fields(value, ('version', 'decision_ref', 'criteria', 'checks', 'reviews', 'security_impact', 'base',
                         'comparison', 'nontrivial', 'instructions', 'exclusions', 'review_limit'), ('relevant_untracked', 'linked'))
    _require(type(value['version']) is int and value['version'] in (1, 2), 'Unsupported evidence plan version')
    if value['version'] == 2:
        _require('linked' in value, 'Linked plan contract is missing')
        _linked(value['linked'])
    else:
        _require('linked' not in value, 'Legacy plans cannot carry linked acceptance')
    for name in ('decision_ref', 'base'):
        state._text(value[name], name)
    _require(value['comparison'] in {'endpoint', 'merge-base'} and type(value['nontrivial']) is bool,
             'Invalid candidate comparison or task impact')
    _require(type(value['review_limit']) is int and 1 <= value['review_limit'] <= 8, 'Invalid review round limit')
    _strings(value['instructions'], 'instructions')
    for item in value['instructions']:
        path = Path(item)
        _require(path.is_absolute() and path.resolve() == path and path.name in
                 {'AGENTS.md', 'AGENTS.override.md', 'CLAUDE.md', 'project.json', 'package.json', 'pyproject.toml',
                  'Cargo.toml', 'go.mod', 'Makefile', 'copilot-instructions.md'}, 'Unsafe instruction/configuration path')
    _require(isinstance(value['exclusions'], list) and len(value['exclusions']) <= 64, 'Invalid exclusions')
    for exclusion in value['exclusions']:
        state._fields(exclusion, ('path', 'impact'))
        _relative(exclusion['path'])
        state._text(exclusion['impact'], 'exclusion impact')
    _strings(value.get('relevant_untracked', []), 'relevant untracked paths')
    for path in value.get('relevant_untracked', []):
        _relative(path)
    state._fields(value['reviews'], ('general', 'security'))
    for kind, review in value['reviews'].items():
        state._fields(review, ('applicability', 'reason', 'independent'))
        _require(review['applicability'] in {'required', 'inapplicable', 'unresolved'} and type(review['independent']) is bool,
                 'Invalid review applicability')
        state._text(review['reason'], 'applicability reason')
        if review['applicability'] == 'inapplicable':
            _require(not re.search(r'no (tools?|capacity|reviewer)|unavailable|missing proof', review['reason'], re.I),
                     'Unavailable review remains unresolved')
    _require(not value['nontrivial'] or value['reviews']['general']['applicability'] != 'inapplicable',
             'General review is required for nontrivial completion')
    state._fields(value['security_impact'], ('status', 'reason', 'reference'))
    _require(value['security_impact']['status'] in {'assessed', 'unresolved'}, 'Invalid security impact assessment')
    for name in ('reason', 'reference'):
        state._text(value['security_impact'][name], 'security impact ' + name)
    _require(isinstance(value['checks'], list) and len(value['checks']) <= MAX_CHECKS, 'Invalid accepted checks')
    ids = set()
    for check in value['checks']:
        state._fields(check, ('id', 'argv', 'cwd', 'timeout', 'env', 'effects', 'baseline', 'dependencies'), ('thresholds', 'resources'))
        state._text(check['id'], 'check id', 128)
        _require(check['id'] not in ids, 'Duplicate check id')
        ids.add(check['id'])
        _require(isinstance(check['argv'], list) and 0 < len(check['argv']) <= 64 and
                 all(isinstance(a, str) and '\x00' not in a and len(a) <= 4096 for a in check['argv']) and
                 bool(check['argv'][0]), 'Invalid command arguments')
        _relative(check['cwd'])
        _require(type(check['timeout']) is int and 1 <= check['timeout'] <= 300, 'Invalid check timeout')
        _require(isinstance(check['env'], dict) and 'PATH' in check['env'] and set(check['env']) <= {'PATH', 'LANG', 'LC_ALL', 'TZ'},
                 'Checks require an explicit credential-free environment')
        for item in check['env'].values():
            state._text(item, 'check environment', 4096)
        if 'thresholds' in check:
            _require(check['thresholds'] == {'exit_codes': [0]}, 'Accepted zero-failure threshold cannot be weakened')
        state._fields(check['effects'], ('kind', 'inspection_ref', 'network', 'production', 'publish', 'migrations'))
        _require(check['effects']['kind'] in {'read-only', 'disposable'} and all(check['effects'][key] is False for key in
                 ('network', 'production', 'publish', 'migrations')), 'Check effects exceed safe local execution')
        state._text(check['effects']['inspection_ref'], 'command inspection reference')
        if 'resources' in check:
            from runtime import delegation
            claims = delegation._claims(check['resources'])
            _require(check['effects']['kind'] != 'read-only' or all(c['mode'] == 'read' for c in claims),
                     'Read-only checks cannot declare mutable resources')
        else:
            _require(check['effects']['kind'] == 'read-only', 'Mutable checks require declared resources')
        state._fields(check['baseline'], ('status', 'reference'), ('exit_code', 'output_digest'))
        _require(check['baseline']['status'] in {'passed', 'failed', 'not-run'}, 'Invalid baseline status')
        state._text(check['baseline']['reference'], 'baseline reference')
        if 'exit_code' in check['baseline']:
            _require(type(check['baseline']['exit_code']) is int, 'Invalid baseline exit code')
        if 'output_digest' in check['baseline']:
            _require(isinstance(check['baseline']['output_digest'], str) and re.fullmatch(r'[0-9a-f]{64}', check['baseline']['output_digest']), 'Invalid baseline output digest')
        _strings(check['dependencies'], 'check dependencies')
        for path in check['dependencies']:
            _relative(path)
    _require(isinstance(value['criteria'], list) and 0 < len(value['criteria']) <= 32, 'Missing acceptance criteria')
    criteria = set()
    for criterion in value['criteria']:
        state._fields(criterion, ('id', 'checks', 'behavior'))
        state._text(criterion['id'], 'criterion id', 128)
        _require(criterion['id'] not in criteria and type(criterion['behavior']) is bool, 'Invalid acceptance criterion')
        criteria.add(criterion['id'])
        _strings(criterion['checks'], 'criterion checks', ids)
        _require(criterion['checks'] or criterion['behavior'], 'Criterion has no accepted proof')
    return value


def _git(root, *args):
    from runtime.onboarding import _git as git
    code, raw = git(root, *args)
    _require(code == 0, 'Cannot capture Git candidate')
    return raw


def _tool(check, root):
    executable = check['argv'][0]
    path = Path(executable) if '/' in executable else Path(shutil.which(executable, path=check['env']['PATH']) or '/nonexistent')
    if not path.is_absolute():
        path = root / check['cwd'] / path
    try:
        path = path.resolve(strict=True)
        info = path.stat()
        _require(stat.S_ISREG(info.st_mode) and info.st_size <= 128 * 1024 * 1024 and os.access(path, os.X_OK),
                 'Accepted check executable is unavailable or over limit')
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(65536), b''):
                digest.update(chunk)
        return dict(path=str(path), sha256=digest.hexdigest(), mode=stat.S_IMODE(info.st_mode))
    except OSError:
        raise state.StateError('Accepted check executable is unavailable') from None



def _canonical_inputs(scope):
    """Reobserve accepted selected locations/dependencies; never adopt a new scope."""
    if not isinstance(scope, AcceptedScope):
        return None
    state._scope_version(scope)
    identity = state._accepted_identity(scope.accepted_identity)
    return _observe_pinned_identity(identity)


def _observe_pinned_identity(identity):
    from runtime.onboarding import _checkout_observation, _filesystem_binding, _fingerprint
    observed, error = _checkout_observation(identity['repository_root'], {'paths': 0})
    _require(error is None and _filesystem_binding(Path(identity['project_root'])) == identity['project_binding'] and
        observed['binding'] == identity['bindings'] and
        all(observed[key] == identity['repository_root' if key == 'root' else key]
            for key in ('root', 'primary_root', 'git_dir', 'git_common_dir')), 'Accepted checkout physical identity changed')
    for shared in identity['shared_policy']:
        path = Path(shared['path'])
        actual = _fingerprint(path.parent, path.name)
        _require(actual.get('status') == 'read' and actual.get('sha256') == shared['sha256'],
                 'Accepted shared dependency changed or is unavailable')
    return identity


def _candidate_projection(candidate, task):
    state._validate_pins(candidate['pins'])
    _require(candidate['pins'] == task['pins'], 'Candidate task pins changed')
    if task['pins']['schema_version'] == 3:
        identity = state._accepted_identity(candidate.get('accepted_identity'))
        _require(identity == task['accepted_identity'], 'Candidate accepted scope changed')


def _capture(scope, plan, *, pinned=None):
    from runtime.onboarding import _snapshot, _fingerprint
    accepted = _observe_pinned_identity(pinned[0]) if pinned is not None else _canonical_inputs(scope)
    snapshot = _snapshot(scope.repository_root)
    if accepted is not None:
        snapshot['accepted_identity'] = accepted
    _require(snapshot['git_common_dir'] == str(scope.git_common_dir), 'Checkout identity changed')
    _require(snapshot['head'] is not None, 'Candidate HEAD is unresolved')
    for name, value in snapshot['fingerprints'].items():
        _require(value['status'] in {'read', 'absent'}, 'Candidate coverage is incomplete, excluded, unsafe or bounded out')
        path = Path(name[len('instruction:'):]) if name.startswith('instruction:') else scope.repository_root / name
        if value['status'] == 'read':
            value['mode'] = stat.S_IMODE(path.lstat().st_mode)
    for name in plan['instructions']:
        path = Path(name)
        value = _fingerprint(path.parent, path.name)
        _require(value['status'] in {'read', 'absent'}, 'Instruction/configuration coverage is incomplete')
        if value['status'] == 'read':
            value['mode'] = stat.S_IMODE(path.lstat().st_mode)
        snapshot['fingerprints']['instruction:' + name] = value
    for name in plan.get('relevant_untracked', []):
        value = _fingerprint(scope.repository_root, name)
        _require(value['status'] in {'read', 'absent'}, 'Relevant ignored/untracked coverage is incomplete')
        if value['status'] == 'read':
            value['mode'] = stat.S_IMODE((scope.repository_root / name).lstat().st_mode)
        snapshot['fingerprints'][name] = value
    _require(sum(v.get('bytes', 0) for v in snapshot['fingerprints'].values()) <= 8 * 1024 * 1024,
             'Candidate total byte limit exceeded')
    base = _git(scope.repository_root, 'rev-parse', '--verify', '--end-of-options', plan['base'] + '^{commit}').decode().strip()
    comparison_base = base
    if plan['comparison'] == 'merge-base':
        comparison_base = _git(scope.repository_root, 'merge-base', base, snapshot['head']).decode().strip()
    index = _git(scope.repository_root, 'ls-files', '--stage', '-z')
    snapshot['index_entries'] = dict((os.fsdecode(row.split(b'\t', 1)[1]), os.fsdecode(row.split(b'\t', 1)[0]))
                                    for row in index.split(b'\0') if row)
    snapshot.update(base=base, comparison_base=comparison_base, comparison=plan['comparison'],
                    pins=pinned[1] if pinned is not None else state._pins(scope), actual_policy_digest=policy_digest(state.PACKAGE),
                    definitions_digest=_digest(plan), tools={c['id']: _tool(c, scope.repository_root) for c in plan['checks']},
                    environment=dict(python=sys.version, platform=platform.platform(), git=_git(scope.repository_root, '--version').decode().strip()))
    return snapshot


def capture_candidate(scope, plan):
    """Two bounded inventories detect movement; excluded/oversized bytes never prove coverage."""
    try:
        first = _capture(scope, plan)
        second = _capture(scope, plan)
        _require(first == second, 'Candidate moved during capture; retry after writers stop')
        _bounded(first, MAX_ARTIFACT)
        return first
    except state.StateError:
        raise
    except (OSError, StartupError, ValueError, TypeError, subprocess.TimeoutExpired):
        raise state.StateError('Candidate capture is incomplete, unstable or unavailable') from None


def plan_evidence(scope, request):
    _request(request, ('plan',), ('change_decision_ref',))
    plan = _plan(deepcopy(request['plan']))
    _require(plan['version'] == 1 or state._scope_version(scope) == 3, 'Linked plans require canonical schema 3')
    with state._database(scope) as db:
        task = _task(db, scope, request)
        if plan['version'] == 2:
            _linked_projection(_canonical_plain(_artifact_owner(scope, task).task), plan)
        old = deepcopy(task.get('evidence'))
        if old and _read(scope, old['plan']) != plan:
            state._text(request.get('change_decision_ref'), 'scoped rule-change decision reference')
        _require(plan['decision_ref'] == task['decision_ref'] or 'change_decision_ref' in request,
                 'Evidence rules require the existing scoped decision')
        _require(not old or not any(a['status'] in {'reserved', 'running', 'uncertain'} for a in old['attempts']),
                 'Reconcile outstanding attempts before changing accepted evidence rules')
    history = deepcopy(old.get('history', [])) if old else []
    if old:
        _require(len(history) < 16, 'Evidence plan history bound reached; preserve history in a new task')
        history.append({key: old[key] for key in ('plan', 'candidate', 'verification') if key in old} |
                       dict(revision=request['expected_revision'], decision_ref=request.get('change_decision_ref', plan['decision_ref'])))
    candidate = capture_candidate(scope, plan)
    evidence = dict(version=VERSION, plan=_artifact(scope, plan, owner=_artifact_owner(scope, task)), candidate=_artifact(scope, candidate, owner=_artifact_owner(scope, task)),
                    attempts=old['attempts'] if old else [], history=history)
    with state._database(scope, write=True) as db:
        task = _task(db, scope, request)
        task['evidence'] = evidence
        if task['state'] == 'ready':
            task['state'] = 'verifying'
        task['revision'] += 1
        state._save(db, state._scope_id(scope), task)
    return dict(ok=True, task=task, candidate_digest=_digest(candidate))


def _reserve(scope, request, kind, detail):
    if kind == 'check':
        result = _reserve_check(scope, _check_request(dict(request, check_id=detail['check_id'])))
        with state._database(scope) as db:
            from runtime import delegation
            record = next(row for row in delegation._ledger(scope, db) if row['id'] == result['attempt_id'])
        return _read(scope, record['body']['d5_plan']), _read(scope, result['attempt']['candidate']), result['attempt'], result['task']['revision']
    raise state.StateError('Native reviews require explicit linked prepare_review admission')


def _finish(scope, request, attempt, expected_revision, *, execution_owner=None):
    from runtime import delegation
    context = delegation._reservation_write(scope) if attempt['kind'] == 'check' or 'ledger_assignment_digest' in attempt else state._database(scope, write=True)
    with context as db:
        if execution_owner is None:
            task = _task(db, scope, dict(request, expected_revision=expected_revision))
        else:
            _require(attempt['kind'] == 'check' and 'ledger_assignment_digest' in attempt and 'execution' in attempt,
                     'Only exact managed check execution may attach a late result')
            task = delegation._assignment_task(scope, db, request, revision=False)
        attempts = task['evidence']['attempts']
        index = next((n for n, a in enumerate(attempts) if a['id'] == attempt['id']), None)
        _require(index is not None, 'Evidence attempt binding changed')
        if execution_owner is not None:
            _require(execution_owner['status'] == 'running' and attempts[index] == execution_owner,
                     'Check execution ownership changed before result attachment')
        if attempt['kind'] == 'check' and 'ledger_assignment_digest' in attempt:
            record = delegation._linked_check(scope, state._scope_id(scope), task, attempts[index], delegation._ledger(scope, db))
            _require(record is not None, 'Current check has no supported ownership link')
            _require(all(attempt[key] == attempts[index][key] for key in ('id', 'check_id', 'candidate_digest',
                'plan_digest', 'ledger_assignment_digest', 'ledger_claims_digest', 'dispatch_id')), 'Check immutable binding changed')
            record['data'].update(status='uncertain', observation=attempt.get('execution'))
            db.execute('update assignments set data=? where id=?', (_raw(record['data']).decode(), record['id']))
        if attempt['kind'] == 'review' and 'ledger_assignment_digest' in attempt:
            delegation._linked_review(scope, state._scope_id(scope), task, attempts[index], delegation._ledger(scope, db))
            _require(all(attempt[key] == attempts[index][key] for key in ('id', 'assignment_digest', 'assignment',
                'candidate_digest', 'plan_digest', 'ledger_assignment_digest', 'ledger_claims_digest', 'dispatch_id',
                'job_id', 'coverage', 'criteria', 'task_name')), 'Review immutable binding changed')
        attempts[index] = attempt
        task['revision'] += 1
        state._save(db, state._scope_id(scope), task)
    return dict(ok=True, task=task, attempt=attempt, attempt_id=attempt['id'], scope_id=state._scope_id(scope))


def _redact_output(raw, truncated=False):
    """Retain bounded diagnostics; remove common credential lines before persistence."""
    text = raw.decode('utf-8', errors='replace')
    lines = []
    redacted = 0
    for line in text.splitlines():
        if (re.search(r'(?i)password|passwd|secret|credential|api[_-]?key|access[_-]?token|authorization|bearer |private[_ -]?key', line)
                or re.search(r'[A-Za-z0-9_+/=-]{40,}', line)):
            lines.append('[sensitive output line redacted]')
            redacted += 1
        else:
            line = re.sub(r'https?://[^\s]+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[address redacted]', line)
            lines.append(line)
    return dict(text='\n'.join(lines), truncated=truncated, redacted_lines=redacted,
                redaction='Credential-pattern redaction; inspect private diagnostics before sharing')


def _execute(scope, check, tool):
    """Drain bounded output for private redacted diagnostics; own only this process group."""
    output = hashlib.sha256()
    captured = bytearray()
    size = 0
    process = None
    started_at_ns = time.time_ns()
    outcome = 'not-run'
    code = None
    try:
        cwd = scope.repository_root / check['cwd']
        _require(cwd.resolve(strict=True) == cwd and cwd.is_dir(), 'Unsafe accepted check cwd')
        process = subprocess.Popen([tool['path'], *check['argv'][1:]], cwd=cwd, env=check['env'],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.monotonic() + check['timeout']
        outcome = 'running'
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    outcome = 'timed-out'
                    break
                raw = os.read(process.stdout.fileno(), 8192)
                if not raw:
                    code = process.wait(timeout=max(0.01, deadline - time.monotonic()))
                    outcome = 'passed' if code == 0 else 'failed'
                    break
                size += len(raw)
                output.update(raw)
                captured.extend(raw[:max(0, MAX_OUTPUT - len(captured))])
                if size > MAX_OUTPUT:
                    outcome = 'uncertain'
                    break
    except (StartupError, OSError, subprocess.TimeoutExpired):
        outcome = 'uncertain' if process else 'not-run'
    finally:
        surviving = False
        if process:
            # Even a successful parent can leave descendants writing after stdout closes.
            try:
                os.killpg(process.pid, 0)
                surviving = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=0.2)
            except ProcessLookupError:
                pass
            except (OSError, subprocess.TimeoutExpired):
                surviving = True
            process.stdout.close()
            try:
                os.killpg(process.pid, 0)
                outcome = 'uncertain'
            except ProcessLookupError:
                pass
            except OSError:
                outcome = 'uncertain'
            if surviving and outcome in {'passed', 'failed'}:
                outcome = 'uncertain'
    return dict(status=outcome, exit_code=code, output_digest=output.hexdigest(), output_bytes=min(size, MAX_OUTPUT + 1),
                output_limit=MAX_OUTPUT, executor='local-subprocess', observation='static-or-local-command',
                process_id=process.pid if process else None, started_at_ns=started_at_ns, process_started=process is not None,
                private_output=_redact_output(bytes(captured), size > MAX_OUTPUT))


def _check_response(scope, db, request, record, replayed=True):
    from runtime import delegation
    task = delegation._assignment_task(scope, db, request, revision=False)
    attempt = next((a for a in task.get('evidence', {}).get('attempts', []) if a['id'] == record['id']), None)
    _require(attempt is not None and delegation._linked_check(scope, state._scope_id(scope), task, attempt, [record]) is not None,
             'Check replay has no exact retained D5 attempt')
    return dict(ok=True, task=task, attempt=attempt, attempt_id=attempt['id'], scope_id=state._scope_id(scope), replayed=replayed)


def _check_admission(scope, db, task, check, claims, records):
    from runtime import delegation
    # Exclusive bookkeeping for an unknown read footprint does not grant mutable command effects.
    _require(task['state'] not in {'blocked', 'awaiting_user'} and
        (task['mode'] == 'editable' or check['effects']['kind'] == 'read-only'), 'Task cannot reserve this check')
    _require(len(task['evidence']['attempts']) < MAX_ATTEMPTS, 'Evidence attempt bound reached')
    owner = dict(scope_id=state._scope_id(scope), **{key: task[key] for key in ('client', 'session_id', 'task_id')})
    _require(not any(r['data']['role'] == 'check' and r['data']['job_id'] == check['id'] and
        r['data']['status'] != 'settled' and all(r['owner'][key] == value for key, value in owner.items()) for r in records),
        'Exact check remains unresolved; reconcile its original execution first')
    delegation._resources_available(scope, db, claims, records)


def _reserve_check(scope, request):
    from runtime import delegation
    with state._database(scope) as db:
        _require(db is not None, 'Task state has not been initialized')
        state._assert_open(state._task(db,state._scope_id(scope),request['client'],request['session_id'],request['task_id']))
        replay = delegation._replay(scope, delegation._ledger(scope, db), request)
        if replay:
            _require(replay['data']['role'] == 'check', 'Dispatch identity belongs to another role')
            return _check_response(scope, db, request, replay)
        task = _task(db, scope, request)
        plan = _read(scope, task['evidence']['plan'])
        check = next((c for c in plan['checks'] if c['id'] == request['check_id']), None)
        _require(check is not None, 'Check id is not an accepted canonical command')
        claims = delegation._check_claims(scope, check)
        _check_admission(scope, db, task, check, claims, delegation._ledger(scope, db))
        generation = db.execute('select generation from checkouts where scope_id=?', (state._scope_id(scope),)).fetchone()[0]
    candidate = capture_candidate(scope, plan)
    reference = _artifact(scope, candidate, owner=_artifact_owner(scope, task))
    git_directory = delegation._git_directory(scope)
    routing = dict(git_directory=git_directory, git_routing=delegation._git_routing(scope, git_directory))
    attempt = dict(id=uuid.uuid4().hex, kind='check', status='reserved', check_id=check['id'], dispatch_id=request['dispatch_id'], candidate=reference,
                   candidate_digest=reference['digest'], plan_digest=_digest(plan))
    record = delegation._operation_record(scope, task, request, 'check', claims, attempt['id'], reference,
        dict(id=check['id'], kind='check'), job_id=check['id'], routing=routing)
    attempt['ledger_assignment_digest'] = record['data']['assignment']['digest']
    attempt['ledger_claims_digest'] = _digest(record['data']['claims'])
    with delegation._reservation_write(scope) as db:
        records = delegation._ledger(scope, db)
        replay = delegation._replay(scope, records, request)
        if replay:
            return _check_response(scope, db, request, replay)
        task = _task(db, scope, request)
        _require(_read(scope, task['evidence']['plan']) == plan and delegation._check_claims(scope, check) == claims and
            delegation._git_routing(scope, git_directory) == routing['git_routing'] and
            db.execute('select generation from checkouts where scope_id=?', (state._scope_id(scope),)).fetchone()[0] == generation,
            'Prepared check definition/resources/routing/generation changed')
        _check_admission(scope, db, task, check, claims, records)
        delegation._insert_assignment(db, scope, task, record)
        task['evidence']['attempts'].append(attempt)
        state._save(db, state._scope_id(scope), task)
    return dict(ok=True, task=task, attempt=attempt, attempt_id=attempt['id'], scope_id=state._scope_id(scope),
                replayed=False, plan=plan, candidate=candidate)


def _check_request(request):
    _request(request, ('check_id',), ('dispatch_id',))
    request = deepcopy(request)
    if 'dispatch_id' not in request:
        request['dispatch_id'] = 'check:' + _digest(dict(check_id=request['check_id'], revision=request['expected_revision']))
    state._text(request['dispatch_id'], 'stable check dispatch id', 128)
    return request


def run_check(scope, request):
    request = _check_request(request)
    reserved = _reserve_check(scope, request)
    if reserved['replayed']:
        return reserved
    plan, candidate, attempt = reserved['plan'], reserved['candidate'], reserved['attempt']
    check = next(c for c in plan['checks'] if c['id'] == attempt['check_id'])
    attempt['status'] = 'running'
    result = _finish(scope, request, attempt, reserved['task']['revision'])
    revision = result['task']['revision']
    execution_owner = deepcopy(result['attempt'])
    with state._database(scope) as db:
        _task(db,scope,request,revision=False)
    attempt.update(_execute(scope, check, candidate['tools'][check['id']]))
    output_ref = _artifact(scope, attempt.pop('private_output'), owner=_artifact_owner(scope, result["task"]))
    try:
        after = capture_candidate(scope, plan)
        attempt['inputs_changed'] = candidate != after
        if candidate != after and attempt['status'] != 'uncertain':
            attempt['status'] = 'changed-inputs'
    except StartupError:
        attempt.update(inputs_changed=True, status='uncertain', diagnostic='Post-execution candidate unavailable; ownership retained')
    baseline = check['baseline']
    if attempt['status'] == 'failed':
        comparable = 'exit_code' in baseline and 'output_digest' in baseline
        attempt['baseline_comparison'] = ('pre-existing-failure' if comparable and baseline['status'] == 'failed'
            and baseline['exit_code'] == attempt['exit_code'] and baseline['output_digest'] == attempt['output_digest']
            else 'introduced-failure' if baseline['status'] == 'passed' else 'unresolved-failure-comparison')
    else:
        attempt['baseline_comparison'] = 'no-observed-regression' if attempt['status'] == 'passed' else 'unresolved-result'
    attempt['observed_status'] = attempt['status']
    if attempt.get('process_started'):
        attempt['status'] = 'uncertain'
    attempt['execution'] = _artifact(scope, dict(command=check, tool=candidate['tools'][check['id']], output=output_ref, result=attempt.copy()), owner=_artifact_owner(scope, result["task"]))
    return _finish(scope, request, attempt, revision, execution_owner=execution_owner)


def _read_host_proof(scope, reference):
    state._fields(reference, ('path', 'sha256'))
    state._text(reference['path'], 'host proof path', 4096)
    path = Path(reference['path'])
    from runtime.onboarding import _no_links, _read_file
    _require(path.is_absolute() and path.resolve() == path and not path.is_relative_to(state.PACKAGE) and
             all(not os.path.lexists(p / '.git') and not (p.name == 'cache' and p.parent.name == 'plugins')
                 for p in (path, *path.parents)), 'Host proof must be canonical, private and outside repositories/caches')
    try:
        from runtime.startup import runtime_settings
        # This legacy selector validates a proof location, not the task's database version.
        runtime_settings({'runtime': {'schema_version': state.SCHEMA_VERSION, 'state_dir': str(path.parent)}}, state.PACKAGE, scope.git_common_dir)
        _no_links(path)
        raw = _read_file(path, MAX_INPUT, private=True)
        _require(hashlib.sha256(raw).hexdigest() == reference['sha256'], 'Host proof integrity failed')
        return json_object(raw)
    except (OSError, ValueError, TypeError):
        raise state.StateError('Trusted host lifecycle proof is unavailable, unsafe or corrupt') from None


def _reconcile_unlinked_check(scope, request):
    """Bind independently inspected host writer/descendant evidence to one current check.

    This is D4's coordinator-trusted host-proof boundary, not process supervision
    or authentication of an operator's assertions by JSON.
    """
    _request(request, ('attempt_id', 'host_proof'))
    with state._database(scope) as db:
        task = deepcopy(_task(db, scope, request))
        attempt = next((a for a in task.get('evidence', {}).get('attempts', []) if a['id'] == request['attempt_id']), None)
        _require(attempt is not None and attempt['kind'] == 'check' and attempt['status'] in {'reserved', 'running', 'uncertain'},
                 'Check reconciliation requires one unresolved exact attempt')
        plan = _read(scope, task['evidence']['plan'])
    proof = _read_host_proof(scope, request['host_proof'])
    state._fields(proof, ('version', 'kind', 'identity', 'expected_pins', 'expected_revision', 'scope_id', 'attempt_id',
                         'candidate_digest', 'current_candidate_digest', 'plan_digest', 'execution_digest',
                         'stopped', 'descendants_stopped', 'observation_ref', 'coordinator_ref'))
    _require(type(proof['version']) is int and proof['version'] == VERSION and proof['kind'] == 'check-writer-reconciliation'
             and proof['stopped'] is True and proof['descendants_stopped'] is True,
             'Independent stopped-writer and descendant host evidence is required')
    for key in ('observation_ref', 'coordinator_ref'):
        state._text(proof[key], 'trusted host ' + key, 4096)
    candidate = capture_candidate(scope, plan)
    execution_digest = attempt.get('execution', {}).get('digest')
    bindings = dict(identity={key: task[key] for key in IDENTITY[:4]}, expected_pins=task['pins'],
                    expected_revision=task['revision'], scope_id=state._scope_id(scope), attempt_id=attempt['id'],
                    candidate_digest=attempt['candidate_digest'], current_candidate_digest=_digest(candidate),
                    plan_digest=attempt['plan_digest'], execution_digest=execution_digest)
    _require(all(proof[key] == value for key, value in bindings.items()) and attempt['plan_digest'] == _digest(plan),
             'Host lifecycle evidence does not match current exact task, attempt, candidate, pins and result')
    execution = _read(scope, attempt['execution']) if execution_digest else None
    observed = execution.get('result', {}) if execution else {}
    _require(not execution or observed.get('id') == attempt['id'] and
             observed.get('candidate_digest') == attempt['candidate_digest'], 'Observed check result binding failed')
    status = observed.get('observed_status', 'cancelled')
    if status == 'passed':
        _require(observed.get('exit_code') == 0, 'Passing check requires actual observed exit zero')
        status = 'passed' if not observed.get('inputs_changed') and _digest(candidate) == attempt['candidate_digest'] else 'changed-inputs'
    elif status == 'uncertain':
        status = 'cancelled'
    _require(status in {'passed', 'failed', 'timed-out', 'changed-inputs', 'not-run', 'cancelled'},
             'Unknown observed check result cannot become passing proof')
    attempt.update(status=status, reconciliation=_artifact(scope, dict(proof=proof, source_digest=request['host_proof']['sha256']), owner=_artifact_owner(scope, task)))
    return _finish(scope, request, attempt, request['expected_revision'])


def reconcile_check(scope, request):
    """Settle one exact linked D5 check and resource owner using independent host proof."""
    _request(request, ('attempt_id', 'host_proof'))
    request = deepcopy(request)
    from runtime import delegation
    with state._database(scope) as db:
        task = deepcopy(delegation._assignment_task(scope, db, request, revision=False))
        attempt = next((a for a in task.get('evidence', {}).get('attempts', []) if a['id'] == request['attempt_id']), None)
        _require(attempt is not None and attempt['kind'] == 'check', 'Exact check attempt is absent')
        if 'ledger_assignment_digest' not in attempt:
            legacy = True
        else:
            legacy = False
            records = delegation._ledger(scope, db)
            record = delegation._linked_check(scope, state._scope_id(scope), task, attempt, records)
            if record['data']['status'] == 'settled':
                retained = _read(scope, record['data']['reconciliation'])
                _require(retained.get('request_digest') == _digest(delegation._semantic(request)), 'Settled check replay payload changed')
                return _check_response(scope, db, request, record)
            _require(task['revision'] == request['expected_revision'], 'Task revision conflict')
            plan = _read(scope, record['body']['d5_plan'])
            generation = db.execute('select generation from checkouts where scope_id=?', (state._scope_id(scope),)).fetchone()[0]
            reservations = {r['id']: _digest(r['data']) for r in records}
    if legacy:
        return _reconcile_unlinked_check(scope, request)
    proof = _read_host_proof(scope, request['host_proof'])
    candidate = capture_candidate(scope, plan)
    delegation._validate_operation_proof(scope, record, task, proof, current_candidate_digest=_digest(candidate))
    execution = _read(scope, attempt['execution']) if attempt.get('execution') else None
    observed = execution.get('result', {}) if execution else {}
    definition = next(c for c in plan['checks'] if c['id'] == attempt['check_id'])
    _require(not execution or execution['command'] == definition and
        execution['tool'] == _read(scope, record['data']['candidate'])['tools'][attempt['check_id']] and
        observed.get('id') == attempt['id'] and observed.get('candidate_digest') == attempt['candidate_digest'],
        'Observed check execution differs from the exact prepared command/candidate')
    status = observed.get('observed_status', 'cancelled')
    if status == 'passed':
        _require(observed.get('exit_code') == 0, 'Passing check requires actual observed exit zero')
        status = 'passed' if not observed.get('inputs_changed') and _digest(candidate) == attempt['candidate_digest'] else 'changed-inputs'
    elif status == 'uncertain':
        status = 'cancelled'
    _require(status in {'passed', 'failed', 'timed-out', 'changed-inputs', 'not-run', 'cancelled'}, 'Unknown check result')
    retained = _artifact(scope, dict(version=2, proof=proof, source_digest=request['host_proof']['sha256'],
        request_digest=_digest(delegation._semantic(request)), current_candidate=_artifact(scope, candidate, owner=_artifact_owner(scope, task))), owner=_artifact_owner(scope, task))
    attempt.update(status=status, reconciliation=retained)
    with delegation._reservation_write(scope) as db:
        current = delegation._assignment_task(scope, db, request)
        records = delegation._ledger(scope, db)
        _require({r['id']: _digest(r['data']) for r in records} == reservations and
            db.execute('select generation from checkouts where scope_id=?', (state._scope_id(scope),)).fetchone()[0] == generation,
            'Check reservation ownership or candidate generation changed; recapture proof')
        index = next(n for n, a in enumerate(current['evidence']['attempts']) if a['id'] == attempt['id'])
        linked = delegation._linked_check(scope, state._scope_id(scope), current, current['evidence']['attempts'][index], records)
        _require(linked['data'] == record['data'], 'Check ownership changed during reconciliation')
        current['evidence']['attempts'][index] = attempt
        current['revision'] += 1
        linked['data'].update(status='settled', reconciliation=retained,
            result=dict(outcome='completed' if status == 'passed' else 'cancelled' if status == 'cancelled' else 'failed'))
        db.execute('update assignments set data=? where id=?', (_raw(linked['data']).decode(), linked['id']))
        state._save(db, state._scope_id(scope), current)
    return dict(ok=True, task=current, attempt=attempt, attempt_id=attempt['id'], scope_id=state._scope_id(scope), replayed=False)


def _review_admission(scope, task, plan, request):
    _strings(request['coverage'], 'review coverage', COVERAGE)
    _require(request['coverage'], 'Review coverage is empty')
    _strings(request['criteria'], 'covered criteria', {c['id'] for c in plan['criteria']})
    assignment = request['assignment']
    _require(isinstance(assignment, str) and 0 < len(assignment) <= 65536 and '\x00' not in assignment,
             'Invalid review assignment')
    evidence = task['evidence']
    _require(len(evidence['attempts']) < MAX_ATTEMPTS, 'Evidence attempt bound reached')
    limits = [plan['review_limit']] + [_read(scope, entry['plan'])['review_limit'] for entry in evidence.get('history', [])]
    _require(sum(a['kind'] == 'review' for a in evidence['attempts']) < min(limits),
             'Original review round limit reached; preserve limits and seek a scoped decision')


def _review_attempt(scope, record, *, task, db):
    data, review = record['data'], record['body']['review']
    return dict(id=record['id'], kind='review', status='reserved', candidate=data['candidate'],
        candidate_digest=data['candidate']['digest'], plan_digest=review['d5_plan']['digest'],
        task_name=data['binding']['task_name'], assignment=_artifact(scope, dict(prompt=record['body']['request']['assignment']), owner=_artifact_owner(scope, task), db=db),
        assignment_digest=review['assignment_digest'], coverage=review['coverage'], criteria=review['criteria'],
        job_id=data['job_id'], dispatch_id=record['owner']['dispatch_id'],
        ledger_assignment_digest=data['assignment']['digest'], ledger_claims_digest=_digest(data['claims']))


def _review_response(scope, db, request, record, admitted=False):
    from runtime import delegation
    task = delegation._assignment_task(scope, db, request, revision=False)
    attempt = next((a for a in task['evidence']['attempts'] if a['id'] == record['id']), None)
    _require(attempt is not None and delegation._linked_review(scope, state._scope_id(scope), task, attempt, [record]) is not None,
             'Review replay has no exact linked attempt')
    review = record['body']['review']
    prompt = _raw(dict(assignment=record['body']['request']['assignment'], ledger_assignment_digest=record['data']['assignment']['digest'],
        report_contract=record['body']['report_contract'] | dict(attempt_id=record['id'],
            candidate_digest=attempt['candidate_digest'], coverage=attempt['coverage']), ownership=record['body'])).decode()
    return delegation._reply(record, admitted=admitted) | dict(attempt=attempt, task=task, prompt=prompt,
        assignment_digest=attempt['assignment_digest'], ledger_assignment_digest=record['data']['assignment']['digest'])


def prepare_review(scope, request):
    """The sole native review admission path: one D5 round and one D6 launch permit."""
    from runtime import delegation
    return delegation._prepare_native(scope, request, role='review')


def prepared_native_review(scope, attempt_id):
    """Read-only immutable binding for the native collector, never caller identity assertions."""
    with state._database(scope) as db:
        _require(db is not None, 'Missing native review state')
        rows = db.execute('select client,session_id,task_id from tasks where scope_id=?', (state._scope_id(scope),)).fetchall()
        found = []
        for client, session, task_id in rows:
            task = state._task(db, state._scope_id(scope), client, session, task_id)
            for attempt in task.get('evidence', {}).get('attempts', []):
                if attempt['id'] == attempt_id:
                    found.append((task, attempt))
        _require(len(found) == 1, 'Native review attempt identity is missing or ambiguous')
        task, attempt = found[0]
        binding = state._task(db, state._scope_id(scope), task['client'], task['session_id'])
        _require(binding['task_id'] == task['task_id'] and task['state'] != 'cancelled' and attempt['kind'] == 'review'
                 and attempt['status'] == 'reserved', 'Native review binding is no longer collectable')
        state._compatible(scope, task)
        if 'ledger_assignment_digest' in attempt:
            from runtime import delegation
            delegation._linked_review(scope, state._scope_id(scope), task, attempt, delegation._ledger(scope, db))
        plan = _read(scope, task['evidence']['plan'])
        assignment = _read(scope, attempt['assignment'])['prompt']
    _require(_digest(capture_candidate(scope, plan)) == attempt['candidate_digest'], 'Native review candidate is stale')
    return dict(parent_session_id=task['session_id'], assignment=assignment, assignment_digest=attempt['assignment_digest'],
                candidate_digest=attempt['candidate_digest'], requested_coverage=attempt['coverage'], task_name=attempt['task_name'])


def _report(value, attempt):
    _bounded(value)
    state._fields(value, ('version', 'attempt_id', 'assignment_digest', 'candidate_digest', 'coverage', 'findings', 'limitations'))
    _require(type(value['version']) is int and value['version'] == VERSION and value['attempt_id'] == attempt['id'] and
             value['assignment_digest'] == attempt['assignment_digest'] and value['candidate_digest'] == attempt['candidate_digest'],
             'Native review report does not match the prepared assignment')
    _strings(value['coverage'], 'observed review coverage', attempt['coverage'])
    _strings(value['limitations'], 'review limitations')
    _require(isinstance(value['findings'], list) and len(value['findings']) <= 64, 'Invalid native findings')
    ids = set()
    for finding in value['findings']:
        state._fields(finding, ('id', 'severity', 'scope', 'status', 'location', 'scenario', 'evidence', 'counterevidence'),
                      ('root_cause', 'classification', 'confidence', 'correction', 'validation'))
        _require(finding['id'] not in ids and finding['severity'] in {'critical', 'high', 'medium', 'low', 'info'} and
                 finding['scope'] in COVERAGE and finding['status'] in {'confirmed', 'hypothesis', 'optional'}, 'Invalid review finding')
        ids.add(finding['id'])
        for name in ('id', 'location', 'scenario', 'evidence', 'counterevidence'):
            state._text(finding[name], 'finding ' + name, 4096)
    return value


def _review_quality_matches(scope, attempt, record, collected=None, *, context=None):
    """Positive quality belongs to the exact latest native result, not just its assignment."""
    from runtime import delegation
    if record is None or collected is None and 'collected' not in attempt:
        return False
    history = delegation._worker_history(scope, record['data']['observation'], context=context)
    latest = history[0][1] if history else None
    if latest is None or latest['status'] != 'observed' or latest['error'] is not None or latest['conflict'] is not None:
        return False
    collected = _read(None if context is not None else scope, attempt['collected'], context=context) if collected is None else collected
    try:
        actual, receipt = latest['receipt'], collected['receipt']
        if actual is None or actual['turn_status'] != 'completed' or not isinstance(latest['result'], str):
            return False
        correspondence = dict(reviewer_id='worker_id', review_turn_id='worker_turn_id', report_item_id='result_item_id',
            report_digest='result_digest', requested_model='spawn_observed_model', requested_effort='spawn_observed_effort')
        _report(collected['report'], attempt)
        return (receipt['assignment_digest'] == attempt['assignment_digest'] and
            receipt['candidate_digest'] == attempt['candidate_digest'] and
            all(receipt[key] == actual[key] for key in ('parent_session_id', 'parent_turn_id', 'spawn_item_id', 'native_version')) and
            all(receipt[key] == actual[field] for key, field in correspondence.items()) and
            receipt.get('task_name') == actual['task_name'] and receipt.get('agent_path') == actual['agent_path'] and
            receipt['report_digest'] == hashlib.sha256(latest['result'].encode()).hexdigest() and
            json_object(latest['result']) == collected['report'])
    except (StartupError, state.StateError, ValueError, TypeError, KeyError, RecursionError):
        return False


def collect_review(scope, request):
    _request(request, ('attempt_id', 'parent_turn_id', 'spawn_item_id'))
    for key in ('attempt_id', 'parent_turn_id', 'spawn_item_id'):
        state._text(request[key], key)
    with state._database(scope) as db:
        task = _task(db, scope, request)
        attempt = deepcopy(next((a for a in task.get('evidence', {}).get('attempts', []) if a['id'] == request['attempt_id']), None))
    _require(attempt is not None and attempt['kind'] == 'review' and attempt['status'] == 'reserved', 'Native review attempt is not pending')
    from runtime import delegation
    with state._database(scope) as db:
        record = delegation._linked_review(scope, state._scope_id(scope), task, attempt, delegation._ledger(scope, db))
        _require(record is not None, 'Native review collection requires an exact linked admission')
    history = delegation._worker_history(scope, record['data']['observation'])
    latest = history[0][1] if history else None
    _require(latest is not None and latest['status'] == 'observed' and latest['error'] is None and latest['conflict'] is None and
        latest['receipt'] is not None and latest['receipt']['turn_status'] == 'completed', 'Review lifecycle is not exactly observed and complete')
    from runtime.adapters.codex import collect_native_review
    observed = collect_native_review(scope, attempt['id'], request['parent_turn_id'], request['spawn_item_id'])
    state._fields(observed, ('receipt', 'report'))
    receipt = observed['receipt']
    state._fields(receipt, ('version', 'mechanism', 'native_version', 'parent_session_id', 'parent_turn_id', 'spawn_item_id',
                           'reviewer_id', 'review_turn_id', 'report_item_id', 'assignment_digest', 'candidate_digest',
                           'report_digest', 'requested_model', 'requested_effort'), ('task_name', 'agent_path'))
    _require(type(receipt['version']) is int and receipt['version'] == VERSION and receipt['mechanism'] in {'codex-persisted-history', 'codex-native-agent-path'} and
             receipt['parent_session_id'] == request['session_id'] and receipt['parent_turn_id'] == request['parent_turn_id'] and
             receipt['spawn_item_id'] == request['spawn_item_id'] and receipt['reviewer_id'] != request['session_id'] and
             receipt['assignment_digest'] == attempt['assignment_digest'] and receipt['candidate_digest'] == attempt['candidate_digest'],
             'Native review provenance is unqualified')
    if receipt['mechanism'] == 'codex-native-agent-path':
        _require(receipt.get('task_name') == attempt['task_name'] and isinstance(receipt.get('agent_path'), str)
                 and receipt['agent_path'].split('/')[-1] == attempt['task_name'], 'Native prepared task marker is unverified')
    for key in ('reviewer_id', 'review_turn_id', 'report_item_id', 'report_digest', 'native_version'):
        state._text(receipt[key], 'observed ' + key)
    _require(_review_quality_matches(scope, attempt, record, observed),
             'D5 review collection differs from the exact D6 lifecycle result')
    report = _report(observed['report'], attempt)
    _require(_digest(capture_candidate(scope, _load_plan(scope, request))) == attempt['candidate_digest'], 'Review candidate changed during collection')
    attempt.update(status='collected', collected=_artifact(scope, dict(receipt=receipt, report=report), owner=_artifact_owner(scope, task)))
    return _finish(scope, request, attempt, request['expected_revision'])


def assess_review(scope, request):
    _request(request, ('attempt_id', 'assessment'))
    with state._database(scope) as db:
        task = _task(db, scope, request)
        attempt = deepcopy(next((a for a in task.get('evidence', {}).get('attempts', []) if a['id'] == request['attempt_id']), None))
    _require(attempt is not None and attempt['status'] in {'collected', 'assessed'}, 'Assessment requires collected native evidence')
    if 'ledger_assignment_digest' in attempt:
        from runtime import delegation
        with state._database(scope) as db:
            record = delegation._linked_review(scope, state._scope_id(scope), task, attempt, delegation._ledger(scope, db))
        _require(_review_quality_matches(scope, attempt, record), 'Review quality no longer matches the latest native result')
    collected = _read(scope, attempt['collected'])
    assessment = request['assessment']
    state._fields(assessment, ('coverage', 'criteria', 'qualification', 'independence', 'semantic_coverage', 'dispositions', 'decision_refs'),
                  ('rechecked_findings',))
    _strings(assessment['coverage'], 'assessed coverage', collected['report']['coverage'])
    _strings(assessment['criteria'], 'assessed criteria', attempt['criteria'])
    _strings(assessment['decision_refs'], 'assessment decision references')
    for key in ('qualification', 'independence', 'semantic_coverage'):
        state._text(assessment[key], 'coordinator ' + key, 4096)
    _require(isinstance(assessment['dispositions'], list) and len(assessment['dispositions']) <= 64, 'Invalid finding dispositions')
    findings = {f['id']: f for f in collected['report']['findings']}
    seen = set()
    for disposition in assessment['dispositions']:
        state._fields(disposition, ('finding_id', 'status', 'reference'))
        identity = disposition['finding_id']
        _require(identity in findings and identity not in seen and disposition['status'] in {'resolved', 'accepted', 'open'}, 'Invalid finding disposition')
        seen.add(identity)
        state._text(disposition['reference'], 'finding disposition reference')
        finding = findings[identity]
        if disposition['status'] == 'accepted':
            _require(assessment['decision_refs'] and not (finding['scope'] == 'security' and finding['status'] == 'confirmed'
                     and finding['severity'] in {'high', 'critical'}), 'Blocking security finding cannot be accepted or relabeled')
    _require(_digest(capture_candidate(scope, _load_plan(scope, request))) == attempt['candidate_digest'],
             'Coordinator assessment requires the current reviewed candidate')
    rechecked = assessment.get('rechecked_findings', [])
    _require(isinstance(rechecked, list) and len(rechecked) <= 64, 'Invalid scoped finding re-review')
    seen = set()
    for item in rechecked:
        state._fields(item, ('attempt_id', 'finding_id', 'status', 'reference'))
        key = (item['attempt_id'], item['finding_id'])
        _require(key not in seen and item['status'] in {'resolved', 'open'} and item['attempt_id'] != attempt['id'],
                 'Finding resolution requires a different fresh review')
        seen.add(key)
        state._text(item['reference'], 'fresh scoped finding proof', 4096)
        prior = next((a for a in task['evidence']['attempts'] if a['id'] == item['attempt_id'] and 'collected' in a), None)
        _require(prior is not None, 'Scoped re-review references missing native evidence')
        previous_report = _read(scope, prior['collected'])['report']
        finding = next((f for f in previous_report['findings'] if f['id'] == item['finding_id']), None)
        _require(finding is not None and finding['scope'] in assessment['coverage'],
                 'Fresh review does not cover the original finding scope')
    if 'assessment' in attempt:
        history = attempt.setdefault('assessment_history', [])
        _require(len(history) < 8, 'Coordinator assessment history bound reached')
        history.append(attempt['assessment'])
    attempt.update(status='assessed', assessment=_artifact(scope, dict(collected_digest=attempt['collected']['digest'], assessment=assessment), owner=_artifact_owner(scope, task)))
    return _finish(scope, request, attempt, request['expected_revision'])


def _current_attempt(scope, attempt, candidate, plan, reuse, *, context=None):
    if attempt['plan_digest'] != _digest(plan):
        return False
    previous = _read(None if context is not None else scope, attempt['candidate'], context=context)
    if previous == candidate:
        return True
    entry = next((r for r in reuse if r['attempt_id'] == attempt['id']), None)
    if entry is None:
        return False
    # Scope judgments cannot hide changed fixed metadata, instructions, or dependency bytes/modes/index layers.
    variable = {'fingerprints', 'index_entries', 'index_digest', 'dirty_inventory', 'paths'}
    if {k: v for k, v in previous.items() if k not in variable} != {k: v for k, v in candidate.items() if k not in variable}:
        return False
    deps = entry['dependencies']
    if attempt['kind'] == 'check':
        required = next(c['dependencies'] for c in plan['checks'] if c['id'] == attempt['check_id'])
        if not set(required) <= set(deps):
            return False
    if not deps:
        return False
    names = set(previous['fingerprints']) | set(candidate['fingerprints']) | set(previous['index_entries']) | set(candidate['index_entries'])
    for name in names:
        relevant = name.startswith('instruction:') or any(name == d or name.startswith(d.rstrip('/') + '/') for d in deps)
        if relevant and (previous['fingerprints'].get(name) != candidate['fingerprints'].get(name) or
                         previous['index_entries'].get(name) != candidate['index_entries'].get(name)):
            return False
    return True


def _checkout_attempt_blockers(db, scope, task, *, context=None):
    """Use the caller's transaction so another session cannot reserve between scan and commit."""
    from runtime import delegation
    blockers = []
    records = delegation._ledger(scope, db, context=context)
    rows = db.execute('select t.scope_id,t.client,t.session_id,t.task_id from tasks t join checkouts c on t.scope_id=c.scope_id '
                      'where c.repository_root=? and c.git_common_dir=?',
                      (str(scope.repository_root), str(scope.git_common_dir))).fetchall()
    for scope_id, client, session, task_id in rows:
        record = state._task(db, scope_id, client, session, task_id)
        if record.get('retirement'):
            _read(None if context is not None else scope, record['retirement']['proof'], context=context)
        elif any(a['status'] in {'reserved', 'running', 'uncertain'} and
                 delegation._linked_attempt(scope, scope_id, record, a, records, context=context, db=db) is None
                 for a in record.get('evidence', {}).get('attempts', [])):
            own = (scope_id, client, session, task_id) == ((_task_scope_id(task) if context is not None else state._scope_id(scope)), task['client'], task['session_id'], task['task_id'])
            blockers.append('Evidence attempt or surviving writer remains unresolved' if own else
                            'Unreconciled evidence attempt remains in checkout history')
    return blockers


def _blockers(scope, task, plan, candidate, purpose, reuse, security_impact=None, *, resource_closure=None, barrier_id=None, context=None):
    from runtime import delegation
    blockers = []
    evidence = task['evidence']
    if task['state'] == 'cancelled':
        blockers.append('Task is cancelled')
    if any(c['status'] == 'pending' and c['kind'] in {'blocker', 'decision'} for c in task['conditions']):
        blockers.append('Task conditions remain unresolved')
    with (_context_database(context) if context is not None else state._database(scope)) as db:
        blockers.extend(_checkout_attempt_blockers(db, scope, task, context=context))
        blockers.extend(_ledger_blockers(scope, db, resource_closure, barrier_id, context=context))
        review_records = delegation._ledger(scope, db, context=context)
    if task['turn_uncertain'] and task['turn_id'] is not None:
        blockers.append('Native turn interruption/correlation remains unresolved')
    if ((security_impact or plan['security_impact'])['status'] != 'assessed' or
            security_impact is None and _read(None if context is not None else scope, evidence['candidate'], context=context) != candidate):
        blockers.append('Post-implementation security impact assessment is unresolved or stale')
    if any(a['status'] in {'reserved', 'running', 'uncertain'} for a in evidence['attempts']):
        blockers.append('Evidence attempt or surviving writer remains unresolved')
    current = [a for a in evidence['attempts'] if _current_attempt(scope, a, candidate, plan, reuse, context=context)]
    for attempt in current:
        if attempt['kind'] == 'check' and attempt['status'] == 'passed':
            _require('execution' in attempt, 'Passing check lacks observed execution artifact')
            execution = _read(None if context is not None else scope, attempt['execution'], context=context)
            _read(None if context is not None else scope, execution['output'], context=context)
            _require('reconciliation' in attempt, 'Passing check lacks independently inspected host lifecycle evidence')
            reconciliation = _read(None if context is not None else scope, attempt['reconciliation'], context=context)['proof']
            _require(reconciliation['execution_digest'] == attempt['execution']['digest'] and
                     reconciliation['attempt_id'] == attempt['id'] and reconciliation['candidate_digest'] == attempt['candidate_digest']
                     and reconciliation['stopped'] is True and reconciliation['descendants_stopped'] is True,
                     'Check host lifecycle proof does not match observed execution')
            definition = next((c for c in plan['checks'] if c['id'] == attempt['check_id']), None)
            _require(execution.get('command') == definition and execution.get('tool') == candidate['tools'].get(attempt['check_id'])
                     and execution.get('result', {}).get('observed_status') == 'passed'
                     and execution['result'].get('candidate_digest') == attempt['candidate_digest'],
                     'Passing check receipt does not match accepted command, environment or candidate')
    for criterion in plan['criteria']:
        for check_id in criterion['checks']:
            attempts = [a for a in current if a['kind'] == 'check' and a['check_id'] == check_id]
            if not attempts or attempts[-1]['status'] != 'passed':
                blockers.append('Required accepted check is missing, stale or failed: ' + check_id)
    coverage = set()
    behavior = set()
    resolutions = {}
    for attempt in current:
        if attempt['kind'] != 'review' or attempt['status'] != 'assessed':
            continue
        if 'ledger_assignment_digest' in attempt:
            record = delegation._linked_review(scope, _task_scope_id(task) if context is not None else state._scope_id(scope), task, attempt, review_records, context=context)
            if not _review_quality_matches(scope, attempt, record, context=context):
                continue
        collected = _read(None if context is not None else scope, attempt['collected'], context=context)
        assessed = _read(None if context is not None else scope, attempt['assessment'], context=context)
        _require(assessed['collected_digest'] == attempt['collected']['digest'], 'Assessment receipt/report binding failed')
        assessment = assessed['assessment']
        _report(collected['report'], attempt)
        coverage.update(assessment['coverage'])
        if 'behavior' in assessment['coverage']:
            behavior.update(assessment['criteria'])
        for item in assessment.get('rechecked_findings', []):
            resolutions[(item['attempt_id'], item['finding_id'])] = item['status']
    # Findings remain known across edits and stale reports. Only fresh scoped proof
    # can resolve them; a new clean report must explicitly revisit the old concern.
    for attempt in evidence['attempts']:
        if attempt['kind'] != 'review' or 'collected' not in attempt:
            continue
        report = _read(None if context is not None else scope, attempt['collected'], context=context)['report']
        dispositions = {}
        if 'assessment' in attempt:
            assessment = _read(None if context is not None else scope, attempt['assessment'], context=context)['assessment']
            dispositions = {d['finding_id']: d for d in assessment['dispositions']}
        for finding in report['findings']:
            if finding['status'] == 'optional':
                continue
            key = (attempt['id'], finding['id'])
            if resolutions.get(key) == 'resolved':
                continue
            high = finding['status'] == 'confirmed' and finding['scope'] == 'security' and finding['severity'] in {'critical', 'high'}
            disposition = dispositions.get(finding['id'], {'status': 'open'})
            if high or disposition['status'] != 'accepted':
                label = 'Confirmed high/critical security finding needs fresh scoped review: ' if high else 'Finding remains unresolved: '
                blockers.append(label + finding.get('root_cause', finding['id']))
    for criterion in plan['criteria']:
        if criterion['behavior'] and criterion['id'] not in behavior:
            blockers.append('Required observed behavior is missing: ' + criterion['id'])
    for kind, review in plan['reviews'].items():
        applicability = review['applicability']
        if applicability == 'unresolved':
            blockers.append(kind + ' review applicability is unresolved')
        if (applicability == 'required' or kind == 'general' and purpose == 'merge-evidence') and kind not in coverage:
            blockers.append('Required qualified review is missing or stale: ' + kind)
    return sorted(set(blockers))


def _reuse(value):
    _require(isinstance(value, list) and len(value) <= MAX_ATTEMPTS, 'Invalid scoped evidence reuse')
    seen = set()
    for item in value:
        state._fields(item, ('attempt_id', 'reason', 'dependencies'))
        _require(item['attempt_id'] not in seen, 'Duplicate evidence reuse')
        seen.add(item['attempt_id'])
        state._text(item['reason'], 'reuse dependency justification', 4096)
        _strings(item['dependencies'], 'reuse dependencies')
        for path in item['dependencies']:
            _relative(path)
    return value


def _verification_resources(scope, task, plan):
    from runtime import delegation
    git_directory = delegation._git_directory(scope)
    resources = [dict(kind='path', key=str(scope.repository_root), mode='read'),
                 dict(kind='path', key=str(scope.repository_root / '.git'), mode='read'),
                 dict(kind='git', key=str(scope.git_common_dir), mode='read'),
                 dict(kind='git', key=git_directory, mode='read')]
    resources.extend(dict(kind='path', key=name, mode='read') for name in plan['instructions'])
    resources.extend(dict(kind='path', key=_tool(check, scope.repository_root)['path'], mode='read') for check in plan['checks'])
    for check in plan['checks']:
        resources.extend(dict(item, mode='read') for item in check.get('resources', []))
    if task.get('delegation'):
        native_plan = _read(scope, task['delegation']['plan'])
        resources.extend(dict(item, mode='read') for job in native_plan['jobs'] for item in job['claims'])
    _require(len(resources) <= delegation.MAX_VERIFICATION_CLAIMS, 'Verifier resource aggregate exceeds accepted plan bounds')
    canonical = list({_digest(claim): claim for item in resources for claim in delegation._claims([item])}.values())
    resources = [dict(kind=claim['kind'], key=claim.get('path', claim['key']), mode='read',
                      **({'host': claim['host']} if 'host' in claim else {})) for claim in canonical]
    return resources, canonical, dict(git_directory=git_directory,
        git_routing=delegation._git_routing(scope, git_directory))


def _ledger_blockers(scope, db, claims, exclude=None, *, context=None):
    from runtime import delegation
    return ['Relevant assignment ownership remains unresolved: ' + record['id'] for record in delegation._ledger(scope, db, context=context)
        if record['id'] != exclude and record['data']['status'] != 'settled' and
        (claims is None or delegation._held_overlap(claims, record['data']['claims']))]


def _verification_response(task, blockers, candidate=None):
    return dict(ok=True, verified=not blockers, task=task, blockers=blockers,
        candidate_digest=_digest(candidate) if candidate is not None else None, merge_authority=False,
        limitations=['Local point-in-time evidence; no repository merge gate or filesystem security boundary'])


def verify_completion(scope, request):
    return _verify_member(scope, request)


def _verify_member(scope, request, *, linked=False):
    _request(request, ('purpose',), ('reuse', 'security_impact'))
    request = deepcopy(request)
    _require(request['purpose'] in {'completion', 'merge-evidence'}, 'Invalid evidence verification purpose')
    reuse = _reuse(request.get('reuse', []))
    security_impact = request.get('security_impact')
    if security_impact is not None:
        state._fields(security_impact, ('status', 'reason', 'reference'))
        _require(security_impact['status'] in {'assessed', 'unresolved'}, 'Invalid current security impact assessment')
        for key in ('reason', 'reference'):
            state._text(security_impact[key], 'current security impact ' + key)
    from runtime import delegation
    with state._database(scope) as db:
        task = deepcopy(_task(db, scope, request))
        _require('evidence' in task, 'Evidence plan is missing')
        plan = _read(scope, task['evidence']['plan'])
        _require(plan['version'] == 1 or linked and plan['version'] == 2, 'Linked acceptance requires linked verification owner integration')
        generation = db.execute('select generation from checkouts where scope_id=?', (state._scope_id(scope),)).fetchone()[0]
    resources, closure, routing = _verification_resources(scope, task, plan)
    def ownership_blockers():
        with state._database(scope) as db:
            current = _task(db, scope, request)
            blockers = _checkout_attempt_blockers(db, scope, current) + _ledger_blockers(scope, db, closure)
            records = delegation._ledger(scope, db)
            try:
                delegation._resources_available(scope, db, closure, records)
            except state.StateError as error:
                blockers.append(str(error))
        return sorted(set(blockers))
    blockers = ownership_blockers()
    if blockers:
        return _verification_response(task, blockers)
    dispatch = 'verify:' + str(request['expected_revision']) + ':' + request['purpose']
    barrier_request = {key: request[key] for key in IDENTITY} | dict(dispatch_id=dispatch, claims=resources,
        operation=dict(id=dispatch, kind='completion-verification'), reason='Synchronous accepted D5 verification',
        ownership_ref=task['decision_ref'], stop_conditions=['Return after this synchronous verification'],
        verification=dict(purpose=request['purpose'], **routing))
    try:
        reserved = delegation._reserve_operation(scope, barrier_request, role='coordinator', _verification=True)
    except state.StateError:
        blockers = ownership_blockers()
        if blockers:
            return _verification_response(task, blockers)
        raise
    _require(reserved['reservation_admitted'], 'Existing verifier barrier requires exact operation recovery')
    request['expected_revision'] = reserved['revision']
    with state._database(scope) as db:
        task = deepcopy(_task(db, scope, request))
        barrier = next(record for record in delegation._ledger(scope, db) if record['id'] == reserved['attempt_id'])
        _require(barrier['data']['claims'] == closure, 'Verifier resource closure changed before capture')
    candidate = capture_candidate(scope, plan)
    blockers = _blockers(scope, task, plan, candidate, request['purpose'], reuse, security_impact,
                         resource_closure=closure, barrier_id=barrier['id'])
    verification = dict(version=VERSION, candidate_digest=_digest(candidate), plan_digest=_digest(plan),
        purpose=request['purpose'], generation=generation, blockers=blockers, reuse=reuse, security_impact=security_impact,
        resource_closure=closure, barrier_id=barrier['id'])
    verification_ref = _artifact(scope, verification, owner=_artifact_owner(scope, task))
    with delegation._reservation_write(scope) as db:
        current = _task(db, scope, request)
        actual_generation = db.execute('select generation from checkouts where scope_id=?', (state._scope_id(scope),)).fetchone()[0]
        active = next(record for record in delegation._ledger(scope, db) if record['id'] == barrier['id'])
        _require(actual_generation == generation and active['data'] == barrier['data'] and
            delegation._claims(resources, maximum=delegation.MAX_VERIFICATION_CLAIMS) == closure and delegation._git_routing(scope, routing['git_directory']) == routing['git_routing'],
            'Verification generation, barrier or physical routing changed; reconcile the retained barrier')
        final_blockers = sorted(set(blockers + _checkout_attempt_blockers(db, scope, current) +
            _ledger_blockers(scope, db, closure, barrier['id'])))
        if final_blockers != blockers:
            blockers = final_blockers
            verification['blockers'] = blockers
            verification_ref = _artifact(scope, verification, owner=_artifact_owner(scope, task), db=db)
        current['evidence']['verification'] = verification_ref
        if not blockers and request['purpose'] == 'completion' and not linked:
            current['state'] = 'ready'
            for condition in current['conditions']:
                if 'continuation' in condition:
                    condition['continuation']['revoked'] = True
        elif current['state'] == 'ready' or linked:
            current['state'] = 'verifying'
        current['revision'] += 1
        reconciliation = _artifact(scope, dict(version=1, kind='synchronous-verification', barrier_id=barrier['id'],
            verification=verification_ref, revision=current['revision']), owner=_artifact_owner(scope, task), db=db)
        active['data'].update(status='settled', reconciliation=reconciliation, result=dict(outcome='failed' if blockers else 'completed'))
        db.execute('update assignments set data=? where id=?', (_raw(active['data']).decode(), barrier['id']))
        state._save(db, state._scope_id(scope), current)
    return _verification_response(current, blockers, candidate)



def _task_scope_id(task):
    identity = task['accepted_identity']
    return state._digest([3, identity['project_id'], identity['repository_id'], identity['checkout_id']])


def _authority_artifact(value):
    state._fields(value, ('authority', 'reference'))
    authority = value['authority']
    state._fields(authority, ('directory','database','directory_binding','database_binding'))
    directory=state._canonical_path(authority['directory'])
    _require(state._canonical_path(authority['database'])==directory/'runtime.sqlite3','Artifact authority database differs')
    state._canonical_binding(authority['directory_binding']);state._canonical_binding(authority['database_binding'])
    state._artifact_reference(value['reference'])
    return value


def _reference_context(authority):
    authority = _canonical_plain(_canonical_freeze(authority))
    _authority_artifact(dict(authority=authority, reference=dict(name='a'*32+'.json', digest='a'*64)))
    return EvidenceAuthorityContext(Path(authority['directory']), Path(authority['database']),
        _canonical_freeze(authority['directory_binding']), _canonical_freeze(authority['database_binding']),
        (_canonical_freeze(authority),), 'Existing approved linked task authority')


def _linked_source(reference, *, observed=None, db=None,consumer=None,require_admission=False):
    _authority_artifact(reference)
    context = _reference_context(reference['authority'])
    def consume(connection):
        _check_context(context,connection)
        metadata=state._metadata(connection,reference['reference']['name'])
        value=_read(None,reference['reference'],context=context,db=connection)
        if require_admission:_check_content_consumption(reference,metadata,consumer)
        _require(state._metadata(connection,reference['reference']['name'])==metadata,'Linked source metadata changed during consumption')
        if observed is not None:
            key=_raw(reference)
            _require(key not in observed or observed[key][1]==metadata,'Linked source metadata observations disagree')
            observed[key]=(deepcopy(reference),metadata)
        return value
    if db is not None:return consume(db)
    with _context_database(context) as connection:return consume(connection)


def _pinned_locator(task, context):
    identity = state._accepted_identity(task['accepted_identity'])
    return ProjectScope(identity['project_id'], Path(identity['repository_root']), Path(identity['git_common_dir']),
        task['pins']['policy_digest'], RuntimeSettings(2, context.directory))


def _capture_pinned(context, task, plan):
    """Compare current named inputs to history; this locator grants no active scope."""
    from runtime import onboarding as d3
    from runtime.startup import decode_project_record, canonical_scope_projection
    identity = state._accepted_identity(task['accepted_identity'])
    authority = d3._authority_observation(Path(identity['project_root']), {'paths': 0, 'bytes': 0}, canonical_only=True)
    _require(not authority['error'] and authority['record'] is not None, 'Linked current Project authority is unavailable')
    current = canonical_scope_projection(decode_project_record(authority['record']), repository_id=identity['repository_id'],
        checkout_id=identity['checkout_id'], client=identity['client'])
    _require(current is not None and _canonical_plain(current) == identity and identity['membership']['included'],
        'Linked selected configuration or membership changed')
    _require(identity['configuration']['runtime'] == dict(schema_version=3,state_dir=str(context.directory))
        and task['pins']['runtime_digest'] == state.runtime_fingerprint()
        and task['pins']['policy_digest'] == policy_digest(state.PACKAGE), 'Linked original installed pins changed')
    locator = _pinned_locator(task, context)
    first = _capture(locator, plan, pinned=(identity, task['pins']))
    second = _capture(locator, plan, pinned=(identity, task['pins']))
    _require(first == second, 'Linked candidate moved during capture')
    _bounded(first, MAX_ARTIFACT)
    return locator, first


@dataclass(frozen=True)
class _LinkedOwner:
    task_owner: object
    dependencies: tuple
    publication: object = None


def _linked_members(scope, request, observations, *, lifecycle=False):
    state._fields(observations, ('members', 'observe'))
    _require(callable(observations['observe']), 'Linked observation acquisition requires the existing trusted coordinator owner')
    rows = observations['members']
    _require(isinstance(rows, list) and 1 <= len(rows) <= 65, 'Invalid bounded linked members')
    with state._database(scope) as db:
        selected = _task(db, scope, request, allow_cancelled=lifecycle)
        plan = _read(scope, selected['evidence']['plan'], db=db)
        selected_ref = _canonical_plain(_artifact_owner(scope, selected).task)
        projection = _linked_projection(selected_ref, plan)
    found = {}
    for row in rows:
        state._fields(row, ('scope', 'request'))
        member_scope, member_request = row['scope'], deepcopy(row['request'])
        _require(isinstance(member_scope, AcceptedScope) and member_scope.client == 'codex', 'Linked member requires its current supported scope')
        _request(member_request, ('purpose',), ('reuse', 'security_impact'))
        _require(member_request['purpose'] == request['purpose'], 'Linked verification purpose differs')
        with state._database(member_scope) as db:
            task = _task(db, member_scope, member_request, allow_cancelled=lifecycle)
            _require('evidence' in task, 'Linked member approval is missing')
            member_plan = _plan(_read(member_scope, task['evidence']['plan'], db=db))
            reference = _canonical_plain(_artifact_owner(member_scope, task).task)
            _require(_linked_projection(reference, member_plan) == projection, 'Linked approved participant contracts diverge')
        key = _raw(reference)
        _require(key not in found, 'Duplicate linked observation member')
        found[key] = dict(scope=member_scope, request=member_request, reference=reference)
    _require(set(found) == {_raw(row['task']) for row in projection['participants']}, 'Linked observation members do not match the complete approved set')
    _require(found[_raw(selected_ref)]['request'] == request, 'Selected linked request differs from its observation')
    return selected_ref, projection, [found[_raw(row['task'])] for row in projection['participants']]


def _linked_snapshot(reference, *, stopped=False):
    state._task_reference(reference)
    context = _reference_context(reference['authority'])
    with _context_database(context) as db:
        task = state._task(db, reference['scope_id'], reference['client'], reference['session_id'], reference['task_id'])
        _require(task is not None and task['client'] == 'codex' and 'evidence' in task, 'Linked member is unavailable')
        plan = _read(None, task['evidence']['plan'], context=context, db=db)
        _linked_projection(reference, plan)
        verification_ref = task['evidence'].get('verification')
        _require(verification_ref is not None, 'Linked member local verification is missing')
        verification = _read(None, verification_ref, context=context, db=db)
        generation = db.execute('select generation from checkouts where scope_id=?',(reference['scope_id'],)).fetchone()[0]
    locator, candidate = _capture_pinned(context, task, plan)
    _require(verification['purpose'] in {'completion','merge-evidence'} and verification['plan_digest'] == _digest(plan)
        and verification['candidate_digest'] == _digest(candidate) and verification['generation'] == generation,
        'Linked member local verification is stale')
    blockers = list(verification['blockers']) + _blockers(locator, task, plan, candidate, verification['purpose'],
        verification.get('reuse',[]), verification.get('security_impact'), resource_closure=verification['resource_closure'], context=context)
    if stopped and task['state']=='cancelled':
        with _context_database(context) as db:_stop_verification(context,db,task)
        blockers=[message for message in blockers if message!='Task is cancelled']
    return dict(task=task,plan=plan,candidate=candidate,context=context,generation=generation,
        verification=verification,verification_ref=verification_ref,blockers=sorted(set(blockers)),reference=reference)


def _linked_stop_content(content):
    state._fields(content,('version','kind','purpose','projection','inputs','inputs_digest','observations','members',
        'selected','publication_revision','implementation_verified','delivery_complete','deliveries','blockers'))
    _require(type(content['version']) is int and content['version']==1 and content['kind']=='linked-verification' and
        content['purpose'] in {'completion','merge-evidence'} and type(content['implementation_verified']) is bool and
        isinstance(content['blockers'],list) and all(isinstance(value,str) for value in content['blockers']) and
        content['blockers']==sorted(set(content['blockers'])) and content['implementation_verified']==(not content['blockers']),
        'Linked stop requires exact actual implementation result')
    _require(isinstance(content['members'],list) and 1<=len(content['members'])<=65 and
        [row['task'] for row in content['members']]==[row['task'] for row in content['projection']['participants']] and
        content['selected'] in [row['task'] for row in content['members']], 'Linked stop participant set is incomplete')
    state._integer(content['publication_revision'],'linked publication revision',2)
    for row in content['members']:
        state._fields(row,('task','revision','generation','verification'));state._task_reference(row['task'])
        state._integer(row['revision'],'original linked member revision',1);state._integer(row['generation'],'linked member generation')
        state._artifact_reference(row['verification'])
    selected=next(row for row in content['members'] if row['task']==content['selected'])
    _require(content['publication_revision']==selected['revision']+1,'Linked selected publication transition changed')


def _linked_source_closure(roots,authorities):
    from runtime import changes
    known={_raw(a):a for a in authorities};found=dict(known);observed={};pending=list(roots);seen=set()
    for authority in authorities:
        context=_reference_context(authority)
        # Authority discovery checks typed immutable history without recursively consuming its stop readers.
        _,sources=changes._recovery_sources(context,validate_stops=False)
        for reference,value in sources:
            with _context_database(context) as db:history=_recovery_source_history(context,db,reference,value['identity'],validate_stops=False)
            for _,prior in history:
                for other in prior['authorities']:found[_raw(other)]=other
    while pending:
        ref=pending.pop();key=_raw(ref)
        if key in seen:continue
        seen.add(key);_require(len(seen)<=4096,'Linked stop source traversal exceeds bound')
        authority=ref['authority'];found[_raw(authority)]=authority
        if _raw(authority) not in known:continue
        _linked_source(ref,observed=observed)
        metadata=observed[key][1]
        for edge in metadata['dependencies']:
            target=edge['reference'];other=target.get('authority',authority)
            found[_raw(other)]=other
            if edge['kind']=='artifact':pending.append(dict(authority=other,reference=target.get('artifact',target)))
            elif edge['kind'] in {'assignment','recovery'}:pending.append(dict(authority=other,reference=target['assignment'] if edge['kind']=='assignment' else target['artifact']))
            else:_require(edge['kind']=='task','Linked stop source has unsupported dependencies')
    _require(len(found)<=4096,'Linked stop authority closure exceeds bound')
    return sorted(found.values(),key=_raw),observed


def _linked_contract(pointer):
    value=_linked_source(pointer)
    if value.get('kind')=='linked-complete-stop' and value.get('version')==2:
        _linked_capture_shape(value,common=True)
        return value['content']
    _linked_stop_content(value)
    return value


def _linked_stop_sources(pointer,authorities):
    """Structural discovery grants no stop or closure authority."""
    content=_linked_contract(pointer);roots=[pointer,*_linked_source_refs(content['observations'])]
    for member in content['members']:
        if member.get('plan') is not None:roots.append(dict(authority=member['task']['authority'],reference=member['plan']))
        if member['verification'] is not None:roots.append(dict(authority=member['task']['authority'],reference=member['verification']))
    expanded,observed=_linked_source_closure(roots,authorities)
    return content,expanded,observed


@contextmanager
def _linked_stop_guards(pointer,authorities):
    from runtime import changes
    _authority_artifact(pointer)
    pending={_raw(a):a for a in [*authorities,pointer['authority']]}
    for _ in range(4096):
        with changes._authority_guards([Path(a['directory']) for a in pending.values()]):
            _,expanded,_=_linked_stop_sources(pointer,list(pending.values()))
            if {_raw(a) for a in expanded}==set(pending):
                yield sorted(pending.values(),key=_raw)
                return
        pending.update({_raw(a):a for a in expanded})
    raise state.StateError('Linked stop authority closure did not converge')


def _linked_execution_member(snapshot):
    """Check actual current ownership separately from its known or unknown result."""
    task=snapshot['task'];context=snapshot['context'];verification=snapshot['verification'];claims=snapshot.get('resource_closure',verification['resource_closure'] if verification is not None else None)
    _require(not any(a['status'] in {'reserved','running','uncertain'} for a in task['evidence']['attempts']) and
        not (task['turn_uncertain'] and task['turn_id'] is not None),'Linked execution/descendant ownership remains unresolved')
    _require(not any(c['status']=='pending' and c['kind'] in {'blocker','decision'} for c in task['conditions']),
        'Linked task authority/dependency conditions remain unresolved')
    locator=_pinned_locator(task,context)
    with _context_database(context) as db:
        state._ready_stop_bindings(context,db,task)
        _require(not _checkout_attempt_blockers(db,locator,task,context=context) and
            not _ledger_blockers(locator,db,claims,context=context),
            'Linked execution still has a relevant unresolved owner')



def _linked_lifecycle_member(snapshot,content):
    if content.get('kind')=='linked-verification' and content['implementation_verified']:
        _require(not snapshot['blockers'],'Linked member verification remains blocked');return
    _linked_execution_member(snapshot)


def _linked_lifecycle_outcomes(content,snapshots,*,observed,consumer):
    """Reproduce actual result facts without promoting them to passing readiness."""
    result=_linked_outcomes(content['projection'],content['inputs_digest'],content['observations'],snapshots,
        content['selected'],observed=observed,require_shared_support=True,consumer=consumer)
    shared,delivered,_,deliveries=result;local=[]
    for member in content['members']:
        if member['verification'] is None:continue
        verification=_linked_source(dict(authority=member['task']['authority'],reference=member['verification']),observed=observed,
            consumer=consumer,require_admission=True)
        _require(isinstance(verification['blockers'],list),'Original linked local result is unavailable')
        local.extend(verification['blockers'])
    if content.get('kind')=='linked-verification':
        _require(sorted(set(shared+local))==content['blockers'] and delivered==content['delivery_complete'] and deliveries==content['deliveries'],
            'Linked original result or required delivery observation changed')
    return result


def _linked_basis_root(basis):
    _linked_stop_shape(basis)
    return basis['aggregate'] if basis['version']==1 else basis['basis']


def _linked_capture_shape(value,*,common=False):
    state._fields(value,('version','kind','basis','aggregate','content','authorities','members','sources','delivery_complete','deliveries'))
    _require(type(value['version']) is int and value['version']==2 and value['kind']=='linked-complete-stop' and value['aggregate'] is None,
        'Unknown factual linked lifecycle basis')
    _require((value['basis'] is None)==common,'A factual capture cannot substitute for an independently stopped member')
    if not common:_authority_artifact(value['basis'])
    content=value['content'];state._fields(content,('projection','inputs','inputs_digest','observations','members','selected'))
    _require(1<=len(value['members'])<=65 and [m['task'] for m in value['members']]==[m['task'] for m in content['projection']['participants']] and
        [m['task'] for m in content['members']]==[m['task'] for m in value['members']] and content['selected'] in [m['task'] for m in value['members']],
        'Factual lifecycle basis omits an approved participant')
    for member,row in zip(value['members'],content['members']):
        state._fields(member,('task','state','revision','pins','created_at','plan','verification','candidate_digest','bindings','inputs'))
        state._task_reference(member['task']);state._artifact_reference(member['plan'])
        if member['verification'] is not None:state._artifact_reference(member['verification'])
        _require(row==dict(task=member['task'],revision=member['revision'],generation=member['bindings']['generation'],plan=member['plan'],verification=member['verification']),
            'Factual member contract/source snapshot changed')
    _bounded(value,MAX_ARTIFACT)


def _linked_require_absent_aggregate(context,db,task,reference):
    """A plan change cannot turn an actual historical aggregate into missing evidence."""
    evidence=task['evidence'];history=evidence.get('history',[])
    _require(isinstance(history,list) and all(isinstance(item,dict) for item in history),'Unknown aggregate history remains protected')
    _require(not any(item.get('linked_verification') for item in [evidence,*history]),
        'Existing current or historical aggregate requires its actual v1 lifecycle source')
    # Earlier plan-history records omit the aggregate pointer; its managed owner remains authoritative.
    rows=db.execute("select name,digest from evidence_metadata where class='detail' limit 4097").fetchall()
    _require(len(rows)<=4096,'Historical aggregate ownership lookup exceeds bound')
    for name,digest in rows:
        if state._metadata(db,name)['owner'].get('task')!=reference:continue
        body=_read(None,dict(name=name,digest=digest),context=context,db=db)
        _require(not isinstance(body,dict) or body.get('kind')!='linked-verification',
            'Existing managed historical aggregate requires its actual v1 lifecycle source')


def _linked_terminal_snapshot(reference):
    context=_reference_context(reference['authority'])
    with _context_database(context) as db:
        task=state._task(db,reference['scope_id'],reference['client'],reference['session_id'],reference['task_id'])
        _require(task is not None and task['state'] in {'ready','verifying','cancelled'},'Lifecycle member lacks an actual terminal reconciliation')
        _linked_require_absent_aggregate(context,db,task,reference)
        plan_ref=task['evidence']['plan'];plan=_read(None,plan_ref,context=context,db=db);_linked_projection(reference,plan)
        verification_ref=_stop_verification(context,db,task,allow_absent=True)
        verification=_read(None,verification_ref,context=context,db=db) if verification_ref is not None else None
        bindings=state._ready_stop_bindings(context,db,task)
    locator,candidate=_capture_pinned(context,task,plan)
    _,claims,_=_verification_resources(locator,task,plan)
    snapshot=dict(reference=reference,context=context,task=task,plan=plan,plan_ref=plan_ref,candidate=candidate,
        generation=bindings['generation'],bindings=bindings,verification_ref=verification_ref,verification=verification,resource_closure=claims)
    _linked_execution_member(snapshot)
    return snapshot


def _linked_terminal_facts(references,selected,acquired,authorities,*,original_authorities=None,consumer=None):
    snapshots=[_linked_terminal_snapshot(ref) for ref in references];projection=_linked_projection(selected,next(s['plan'] for s in snapshots if s['reference']==selected))
    _require([s['reference'] for s in snapshots]==[p['task'] for p in projection['participants']] and
        all(_linked_projection(s['reference'],s['plan'])==projection for s in snapshots),'Lifecycle scope contracts are incomplete or divergent')
    inputs=_linked_inputs(snapshots);observed={}
    _,delivered,_,deliveries=_linked_outcomes(projection,_digest(inputs),acquired,snapshots,selected,observed=observed,require_shared_support=True,consumer=consumer)
    roots=_linked_source_refs(acquired)
    for snapshot in snapshots:
        roots.append(dict(authority=snapshot['reference']['authority'],reference=snapshot['plan_ref']))
        if snapshot['verification_ref'] is not None:roots.append(dict(authority=snapshot['reference']['authority'],reference=snapshot['verification_ref']))
    expanded,observed=_linked_source_closure(roots,authorities)
    _require({_raw(a) for a in expanded}<={_raw(a) for a in authorities},'Lifecycle source authority set is incomplete')
    retained=sorted(original_authorities if original_authorities is not None else authorities,key=_raw)
    required={_raw(s['reference']['authority']) for s in snapshots}
    for reference,metadata in observed.values():
        required.add(_raw(reference['authority']));required.update(_raw(edge['reference'].get('authority',reference['authority'])) for edge in metadata['dependencies'])
    _require(required<={_raw(a) for a in retained},'Factual lifecycle omitted an original required authority')
    members=[]
    for snapshot in snapshots:
        task=snapshot['task'];files=_stop_input_files(task,snapshot['candidate']);project=Path(task['accepted_identity']['project_root'])/state.PROJECT_FILE
        files[str(project)]=_closure_file_stat(project)
        members.append(dict(task=snapshot['reference'],state=task['state'],revision=task['revision'],pins=task['pins'],created_at=task['lifecycle']['created_at'],
            plan=snapshot['plan_ref'],verification=snapshot['verification_ref'],candidate_digest=_digest(snapshot['candidate']),bindings=snapshot['bindings'],inputs=files))
    content=dict(projection=projection,inputs=inputs,inputs_digest=_digest(inputs),observations=deepcopy(acquired),
        members=[dict(task=m['task'],revision=m['revision'],generation=m['bindings']['generation'],plan=m['plan'],verification=m['verification']) for m in members],selected=selected)
    sources=[dict(reference=reference,metadata=metadata,stat=_closure_file_stat(Path(metadata['managed']['path']))) for _,(reference,metadata) in sorted(observed.items())]
    value=dict(version=2,kind='linked-complete-stop',basis=None,aggregate=None,content=content,authorities=retained,members=members,sources=sources,
        delivery_complete=delivered,deliveries=deliveries)
    _linked_capture_shape(value,common=True)
    for member in members:_check_ready_inputs(member['inputs'])
    return value


def _linked_capture_dependencies(value):
    selected=value['content']['selected'];refs=[dict(kind='task',reference=selected)]
    refs.extend(dict(kind='task',reference=member['task']) for member in value['members'] if member['task']!=selected)
    refs.extend(dict(kind='artifact',reference=dict(authority=source['reference']['authority'],artifact=source['reference']['reference'])) for source in value['sources'])
    return refs


def _linked_capture_record(pointer,*,writer=None):
    context=_reference_context(pointer['authority'])
    with _preparation_database(context,writer) as db:
        metadata,raw=_managed_artifact(None,pointer['reference'],context=context,db=db);value=json.loads(raw)
        _linked_capture_shape(value,common=True);selected=value['content']['selected']
        task=_linked_raw_task(db,selected)
        _require(task is not None,'Factual capture owner is no longer an open raw acquisition owner')
        _require(pointer['authority']==selected['authority'] and metadata['class']=='detail' and metadata['status']=='live' and metadata['closed_at'] is None and
            metadata['owner']==dict(kind='project',project_id=task['accepted_identity']['project_id'],task=selected) and metadata['dependencies']==_linked_capture_dependencies(value),
            'Factual lifecycle basis lacks its exact registered owner/dependencies')
    return value,metadata


def _linked_bound_basis(pointer,authorities,*,writer=None):
    original,metadata=_linked_capture_record(pointer,writer=writer)
    actual=_linked_terminal_facts([m['task'] for m in original['members']],original['content']['selected'],original['content']['observations'],authorities,
        original_authorities=original['authorities'],consumer=pointer)
    _require(actual==original,'Factual lifecycle member/input/source snapshot changed')
    bound=deepcopy(original);bound['basis']=deepcopy(pointer)
    bound['sources'].append(dict(reference=deepcopy(pointer),metadata=metadata,stat=_closure_file_stat(Path(metadata['managed']['path']))))
    bound['sources'].sort(key=lambda source:_raw(source['reference']));_linked_stop_shape(bound)
    return bound


def _acquire_linked_basis(scope,request,observations):
    """Capture managed facts first; this never asserts that independent task stops exist."""
    _request(request,('purpose',),('reuse','security_impact'))
    _require(isinstance(scope,AcceptedScope) and scope.client=='codex' and request['purpose'] in {'completion','merge-evidence'},'Factual lifecycle capture needs its actual supported accepted scope')
    selected,projection,members=_linked_members(scope,request,observations,lifecycle=True);references=[m['reference'] for m in members]
    pending={_raw(ref['authority']):ref['authority'] for ref in references};acquired=None
    from runtime import changes
    for _ in range(4096):
        with changes._authority_guards([Path(a['directory']) for a in pending.values()]),_current_content_acquisition(scope,request):
            snapshots=[_linked_terminal_snapshot(ref) for ref in references];inputs=_linked_inputs(snapshots)
            if acquired is None:acquired=json_object(_raw(observations['observe'](_canonical_freeze(dict(projection=projection,projection_digest=_digest(projection),inputs=inputs,inputs_digest=_digest(inputs))))),limit=MAX_ARTIFACT)
            roots=_linked_source_refs(acquired)+[dict(authority=s['reference']['authority'],reference=s['plan_ref']) for s in snapshots]
            roots.extend(dict(authority=s['reference']['authority'],reference=s['verification_ref']) for s in snapshots if s['verification_ref'] is not None)
            expanded,_=_linked_source_closure(roots,list(pending.values()))
            if {_raw(a) for a in expanded}!=set(pending):
                pending.update({_raw(a):a for a in expanded});continue
            value=_linked_terminal_facts(references,selected,acquired,list(pending.values()));context=_reference_context(selected['authority']);found=[]
            with _context_database(context,write=True) as db:
                rows=db.execute("select name,digest from evidence_metadata where class='detail' limit 4097").fetchall();_require(len(rows)<=4096,'Factual basis lookup exceeds bound')
                for name,digest in rows:
                    if state._metadata(db,name)['owner'].get('task')!=selected:continue
                    body=_read(None,dict(name=name,digest=digest),context=context,db=db)
                    if body.get('kind')=='linked-complete-stop' and body.get('version')==2 and body.get('basis') is None:
                        _require(body==value,'Prior factual lifecycle basis differs; preserve its incomplete owner');found.append(dict(name=name,digest=digest))
                _require(len(found)<=1,'Duplicate logical factual lifecycle bases remain protected')
                _require(_linked_terminal_facts(references,selected,acquired,list(pending.values()))==value,'Factual capture changed before registration')
                if found:reference=found[0]
                else:
                    task=state._task(db,selected['scope_id'],selected['client'],selected['session_id'],selected['task_id'])
                    owner=_LinkedOwner(_artifact_owner(scope,task),tuple(_canonical_freeze(edge) for edge in _linked_capture_dependencies(value)[1:]))
                    reference=_artifact(scope,value,owner=owner,db=db)
                _require(_linked_terminal_facts(references,selected,acquired,list(pending.values()))==value,'Factual capture changed during registration')
            pointer=dict(authority=selected['authority'],reference=reference)
            return dict(reference=pointer,basis=_linked_bound_basis(pointer,list(pending.values())))
    raise state.StateError('Factual lifecycle authority discovery did not converge')


def _linked_stop_basis(pointer,authorities):
    """Read-only exact linked-member basis under the complete existing authority guards."""
    from runtime import changes,delegation
    value=_linked_source(pointer)
    if value.get('kind')=='linked-complete-stop' and value.get('version')==2:return _linked_bound_basis(pointer,authorities)
    content,expanded,observed=_linked_stop_sources(pointer,authorities)
    _require(expanded==sorted(authorities,key=_raw),'Linked stop needs its complete source authority set')
    snapshots=[_linked_snapshot(row['task'],stopped=True) for row in content['members']]
    members=[]
    for captured,current in zip(content['members'],snapshots):
        task=current['task'];selected=captured['task']==content['selected']
        if selected:_require(task['evidence'].get('linked_verification')==pointer,'Linked aggregate is not the selected original publication')
        expected=content['publication_revision'] if selected else captured['revision']
        expected_state='ready' if selected and content['purpose']=='completion' and content['implementation_verified'] else 'verifying'
        if task['state']=='cancelled':
            _require(task['retirement']['previous_revision']==expected and task['revision']==expected+1,
                'Linked cancelled member does not match its original predecessor')
        else:_require(task['revision']==expected and task['state']==expected_state,'Linked original member state/revision changed')
        state._assert_open(task)
        _require(current['generation']==captured['generation'] and current['verification_ref']==captured['verification'] and
            _linked_projection(current['reference'],current['plan'])==content['projection'],
            'Linked member contract/local verification/generation changed')
        _linked_lifecycle_member(current,content)
        with _context_database(current['context']) as db:
            bindings=state._ready_stop_bindings(current['context'],db,task);barriers=[]
            for record in delegation._ledger(None,db,context=current['context']):
                if record['data']['role']!='coordinator' or not all(record['owner'][k]==current['reference'][k] for k in ('scope_id','client','session_id','task_id')):continue
                rec=_read(None,record['data']['reconciliation'],context=current['context'],db=db)
                if rec.get('kind')=='synchronous-verification':
                    changes._barrier_facts(current['context'],db,task,record,rec);barriers.append(rec)
            _require(any(rec['verification']==captured['verification'] and rec['revision']==captured['revision'] for rec in barriers),
                'Linked member lacks its exact actual synchronous barrier')
        inputs=_stop_input_files(task,current['candidate'])
        project=Path(task['accepted_identity']['project_root'])/state.PROJECT_FILE
        inputs[str(project)]=_closure_file_stat(project)
        members.append(dict(task=current['reference'],state=task['state'],revision=task['revision'],pins=task['pins'],
            created_at=task['lifecycle']['created_at'],verification=current['verification_ref'],candidate_digest=_digest(current['candidate']),
            bindings=bindings,inputs=inputs))
    inputs=_linked_inputs(snapshots)
    _require(inputs==content['inputs'] and _digest(inputs)==content['inputs_digest'],'Linked stop member inputs changed')
    blockers,delivered,_,deliveries=_linked_lifecycle_outcomes(content,snapshots,observed=observed,consumer=pointer)
    sources=[]
    for key,(reference,metadata) in sorted(observed.items()):
        path=Path(metadata['managed']['path'])
        sources.append(dict(reference=reference,metadata=metadata,stat=_closure_file_stat(path)))
    basis=dict(version=1,kind='linked-complete-stop',aggregate=pointer,content=content,authorities=expanded,members=members,
        sources=sources,delivery_complete=delivered,deliveries=deliveries)
    _bounded(basis,MAX_ARTIFACT)
    for member in members:_check_ready_inputs(member['inputs'])
    # Reobserve physical/source metadata after every participant and semantic read.
    for source in sources:
        current={};_linked_source(source['reference'],observed=current)
        _require(current[_raw(source['reference'])][1]==source['metadata'] and
            _closure_file_stat(Path(source['metadata']['managed']['path']))==source['stat'],'Linked stop source changed during capture')
    for row,member in zip(snapshots,members):
        ref=row['reference'];context=row['context']
        with _context_database(context) as db:
            current=state._task(db,ref['scope_id'],ref['client'],ref['session_id'],ref['task_id'])
            _require(current is not None and state._ready_stop_bindings(context,db,current)==member['bindings'] and
                current['lifecycle']['created_at']==member['created_at'] and current['lifecycle']['safe_closed_at'] is None,
                'Linked complete member snapshot changed during capture')
        _check_ready_inputs(member['inputs'])
    return basis


def _linked_stop_shape(basis):
    if basis.get('version')==2:
        _linked_capture_shape(basis);return
    state._fields(basis,('version','kind','aggregate','content','authorities','members','sources','delivery_complete','deliveries'))
    _require(type(basis['version']) is int and basis['version']==1 and basis['kind']=='linked-complete-stop','Unknown linked stop basis')
    _authority_artifact(basis['aggregate']);_linked_stop_content(basis['content'])
    _require([row['task'] for row in basis['members']]==[row['task'] for row in basis['content']['members']],
        'Linked stop basis member set differs from actual aggregate')
    _bounded(basis,MAX_ARTIFACT)


def _linked_owned_preparation(context,db,reference):
    found=[]
    rows=db.execute("select name,digest,owner_key,class,created_at,closed_at,status,bytes,data from evidence_metadata where class='compact' limit 4097").fetchall()
    _require(len(rows)<=4096,'Linked retained preparation lookup exceeds bound')
    for row in rows:
        metadata=state._metadata_record(row)
        if metadata['owner'].get('task')!=reference:continue
        ref=dict(name=row[0],digest=row[1]);body=_read(None,ref,context=context,db=db)
        if body.get('kind')!='linked-closure-preparation':continue
        _require(body['identity']==reference and metadata['owner']==dict(kind='project',project_id=body['accepted_identity']['project_id'],task=reference) and
            body['created_at']==metadata['created_at'] and metadata['status']=='live'
            and metadata['closed_at'] is None and not metadata['targets'] and metadata['export'] is None,
            'Linked preparation original managed owner/age changed')
        found.append(dict(reference=ref,metadata=metadata,content=body))
    _require(len(found)==1,'Linked lifecycle needs every exact managed preparation')
    return found[0]


def _linked_closure_candidate(context,db,reference,task,preparation):
    """A registered candidate owns support; only its lifecycle pointer publishes closure."""
    rows=db.execute("select name,digest,owner_key,class,created_at,closed_at,status,bytes,data from evidence_metadata where class='compact' limit 4097").fetchall()
    _require(len(rows)<=4096,'Linked closure candidate lookup exceeds bound');found=[];prepared=preparation['content']
    for row in rows:
        metadata=state._metadata_record(row)
        if metadata['owner'].get('task')!=reference:continue
        ref=dict(name=row[0],digest=row[1]);body=_read(None,ref,context=context,db=db)
        if body.get('kind')!='task-closure':continue
        projection=('outcomes','reviews','workers','numerical','verifications','native_guidance','scope_guidance','sources')
        _require(metadata['owner']==preparation['metadata']['owner'] and metadata['created_at']==prepared['created_at'] and
            metadata['status']=='live' and (metadata['closed_at'] is None or task is None or metadata['closed_at']==task['lifecycle']['safe_closed_at']) and not metadata['targets'] and metadata['export'] is None and
            body.get('version')==1 and body['identity']==reference and
            all(body[key]==prepared[key] for key in ('identity','pins','accepted_identity','created_at','revision','outcome','stopped',*projection)) and
            (task is None or body['outcome']==task['state'] and body['revision']==task['revision'] and body['pins']==task['pins'] and
                body['accepted_identity']==task['accepted_identity'] and body['created_at']==task['lifecycle']['created_at']) and body['artifacts']==[preparation['reference']] and
            metadata['dependencies']==[dict(kind='task',reference=reference),dict(kind='artifact',reference=preparation['reference'])],
            'Linked closure candidate differs from exact original managed preparation')
        found.append(dict(reference=ref,metadata=metadata,content=body))
    _require(len(found)<=1,'Duplicate linked closure candidates remain protected')
    return found[0] if found else None


def _linked_closed_member(context,db,reference,task,preparation):
    """Authenticate a committed successor; it creates no current passing assertion."""
    if task is None:
        candidate=_linked_closure_candidate(context,db,reference,None,preparation)
        _require(candidate is not None,'Retired linked member lacks actual managed closure')
        marker=state._retired(db,'task',{key:reference[key] for key in ('scope_id','client','session_id','task_id')});body=candidate['content']
        _require(marker is not None and not marker['evidence_expired'] and marker['pins_digest']==_digest(body['pins']) and
            marker['outcome']==body['outcome'] and marker['created_at']==body['created_at'] and marker['request_digest'] is None and
            candidate['metadata']['closed_at'] is not None and marker['retired_at']>=candidate['metadata']['closed_at'],
            'Retired linked task marker differs from exact closure outcome/pins/age/time')
        return candidate
    _require(state._retired(db,'task',{key:reference[key] for key in ('scope_id','client','session_id','task_id')}) is None,
        'Live linked member conflicts with its retirement marker')
    lifetime=state._task_lifecycle(task)
    _require(lifetime is not None and lifetime['safe_closed_at'] is not None,'Linked member has no retained safe closure')
    candidate=_linked_closure_candidate(context,db,reference,task,preparation)
    _require(candidate is not None and candidate['reference']==lifetime['compact'],'Linked closure lacks its actual managed candidate')
    body=candidate['content'];stopped=preparation['content']['stopped']
    _require(_digest({key:value for key,value in task.items() if key not in {'lifecycle','writer_stop'}})==stopped['proof']['task_digest'] and
        task.get('writer_stop')==stopped['writer_stop'],'Linked historical raw owner differs from original stop')
    _require(lifetime['closure']['task_revision']==body['revision'] and lifetime['closure']['dependency_digest']==body['dependency_digest'] and
        lifetime['closure']['observed_at']==lifetime['safe_closed_at'] and lifetime['closure']['evidence']==body['artifacts'],
        'Linked closure differs from exact preparation/managed lifecycle successor')
    return candidate


def _linked_raw_task(db,reference):
    """Read only a present row; the normal task lookup deliberately rejects retired admission."""
    key=tuple(reference[field] for field in ('scope_id','client','session_id','task_id'))
    if db.execute('select 1 from tasks where scope_id=? and client=? and session_id=? and task_id=?',key).fetchone() is None:return None
    return state._task(db,*key)


def _linked_component_closed(pointer,*,writer=None):
    content=_linked_contract(pointer)
    for row in content['members']:
        ref=row['task'];context=_reference_context(ref['authority'])
        with _preparation_database(context,writer) as db:
            task=_linked_raw_task(db,ref)
            if task is not None and task['lifecycle']['safe_closed_at'] is None:return False
    return True


def _linked_retained_references(value,authority):
    """Find actual qualified references in issued compact content, without adopting paths."""
    found={}
    def visit(item,current):
        if isinstance(item,dict):
            if set(item)=={'name','digest'}:
                state._artifact_reference(item);ref=dict(authority=current,artifact=item);found[_raw(ref)]=ref;return
            other=item.get('authority')
            if other is None:
                owner=item.get('task',item.get('reference'))
                if isinstance(owner,dict):other=owner.get('authority')
            if isinstance(other,dict) and set(other)=={'directory','database','directory_binding','database_binding'}:current=other
            for child in item.values():visit(child,current)
        elif isinstance(item,(list,tuple)):
            for child in item:visit(child,current)
    visit(value,authority)
    return list(found.values())


def _linked_retained_assignments(context,db,reference,task,prepared,closed_at,task_marker):
    from runtime import changes,delegation
    certificate=prepared['content']['stopped'];changes._stopped_certificate_shape(certificate)
    actual=db.execute('select id from assignments where scope_id=? and client=? and session_id=? and task_id=? limit 4097',
        tuple(reference[key] for key in ('scope_id','client','session_id','task_id'))).fetchall()
    _require(len(actual)<=4096,'Linked retained assignment membership exceeds bound');issued=certificate.get('assignments',[]);states=[]
    _require({row[0] for row in actual}<={item['reference']['id'] for item in issued},'Uncertified linked assignment remains protected')
    for item in issued:
        ref=item['reference'];marker=state._retired_assignment(db,ref['id']);owner_marker=state._retired(db,'assignment',ref['owner'])
        row=db.execute('select id,scope_id,client,session_id,task_id,dispatch_id,data from assignments where id=?',(ref['id'],)).fetchone()
        metadata,raw=_managed_artifact(None,ref['assignment'],context=context,db=db);body=json.loads(raw)
        _require(metadata['owner'].get('task')==reference and body['owner']==ref['owner'] and body['pins']==prepared['content']['pins'] and
            body['accepted_identity']==prepared['content']['accepted_identity'] and body['lifecycle']['created_at']==item['created_at'] and
            _digest(body['request'])==item['request_digest'] and body['role']==item['role'] and body['claims']==item['claims'],
            'Retained assignment concrete pointer differs from original issued certificate')
        if row is not None:
            _require(task is not None and marker is None and owner_marker is None,'Live linked assignment conflicts with marker/task absence')
            record=delegation._record(None,row,context=context,db=db)
            reconciliation=_read(None,record['data']['reconciliation'],context=context,db=db)
            observed=changes._barrier_certificate_fields(context,db,task,record,reconciliation) if reconciliation.get('kind')=='synchronous-verification' else changes._assignment_certificate(context,db,task,record)
            _require(observed==item,'Live linked assignment differs from exact original stop certificate')
            states.append(dict(certificate=item,record=record,marker=None))
        else:
            _require(marker is not None and marker==owner_marker and not marker['evidence_expired'] and
                marker['identity']==ref['owner'] and marker['assignment_id']==ref['id'] and marker['pins_digest']==_digest(prepared['content']['pins']) and
                marker['request_digest']==item['request_digest'] and marker['created_at']==item['created_at'] and
                marker['outcome']==item['reconciliation']['outcome'] and marker['retired_at']>=closed_at and
                (task_marker is None or marker['retired_at']<=task_marker['retired_at']),
                'Linked assignment marker differs from certified ID/owner/request/outcome/age/time')
            states.append(dict(certificate=item,record=None,marker=marker))
    return states


def _linked_retained_component(pointer,authorities,*,writer=None):
    """Actual compact/marker successors only; never reconstruct removed task bodies."""
    from runtime import changes
    content=_linked_contract(pointer);known={_raw(a):a for a in authorities};members=[];basis=None;digest=None;pending=[];discovered={};checked=set()
    for row in content['members']:
        ref=row['task']
        if _raw(ref['authority']) not in known:discovered[_raw(ref['authority'])]=ref['authority'];continue
        context=_reference_context(ref['authority'])
        with _preparation_database(context,writer) as db:
            if _raw(ref['authority']) not in checked:
                checked.add(_raw(ref['authority']));physical=_historical_inventory(context,db,_evidence_inventory_rows(db))
                _require(sorted(path.name for path in (context.directory/'evidence').iterdir())==
                    sorted(row['reference']['name'] for row in physical if row['stat'] is not None),
                    'Unaccounted content protects retained linked support')
            prepared=_linked_owned_preparation(context,db,ref);body=prepared['content'];stopped=body['stopped'];changes._stopped_certificate_shape(stopped)
            retained=stopped['linked'];_linked_stop_shape(retained)
            if basis is None:basis=retained;digest=body['component_digest']
            _require(retained==basis and _linked_basis_root(basis)==pointer and basis['content']==content and body['component_digest']==digest and
                body['component']['basis_digest']==_digest(basis) and body['component']['aggregate']==basis['aggregate'] and body['component']['delivery_complete'] is True and
                body['component']['acceptance']==content['projection']['acceptance'] and body['component']['deliveries']==basis['deliveries'] and
                body['component']['members']==[dict(reference=m['task'],state=m['state'],revision=m['revision'],pins=m['pins'],created_at=m['created_at']) for m in basis['members']],
                'Retained linked preparation complete membership/basis/acceptance/delivery changed')
            original=next(m for m in basis['members'] if m['task']==ref)
            _require(body['identity']==ref and body['outcome']==original['state'] and body['revision']==original['revision'] and
                body['pins']==original['pins'] and body['created_at']==original['created_at'] and stopped['reference']==ref and
                stopped['state']==body['outcome'] and stopped['revision']==body['revision'] and stopped['pins']==body['pins'] and
                stopped['accepted_identity']==body['accepted_identity'],'Retained linked original scalar facts changed')
            stop=stopped['writer_stop'];proof=_read(None,stop['proof'],context=context,db=db);candidate=_read(None,stop['candidate'],context=context,db=db)
            _ready_stop_shape(proof)
            _require(proof==stopped['proof'] and proof['linked_digest']==_digest(basis) and stop['proof']['digest']==_digest(proof) and
                _digest(candidate)==proof['candidate_digest'] and stop['candidate']['digest']==proof['candidate_digest'] and
                (stop['verification']['digest'] if stop['verification'] is not None else None)==proof['verification_digest'] and stop['task_revision']==body['revision'] and
                stop['generation']==original['bindings']['generation'] and all(proof[key]==original['bindings'][key] for key in
                    ('task_digest','attempts_digest','assignments_digest','generation')),
                'Retained linked independent complete stop changed')
            task=_linked_raw_task(db,ref)
            closure=_linked_closed_member(context,db,ref,task,prepared)
            closed_at=closure['metadata']['closed_at'] if task is None else task['lifecycle']['safe_closed_at']
            task_marker=state._retired(db,'task',{key:ref[key] for key in ('scope_id','client','session_id','task_id')})
            _require(closed_at>=max([body['created_at']]+[a['created_at'] for a in stopped.get('assignments',[])]+
                [value['created_at'] for value in body['numerical']+body['verifications']]),'Linked original closure clock predates support')
            assignments=_linked_retained_assignments(context,db,ref,task,prepared,closed_at,task_marker)
            barriers=[a['certificate'] for a in assignments if a['certificate'].get('version')==2 and
                a['certificate']['reconciliation']['body']['verification']==original['verification']]
            if basis['version']==1:
                _require(barriers,'Retained linked local synchronous verification is unavailable')
                assignment=_read(None,barriers[0]['reference']['assignment'],context=context,db=db)
                plan=_read(None,assignment['d5_plan'],context=context,db=db)
            else:
                _require((original['verification'] is None and not any(a['certificate'].get('version')==2 for a in assignments)) or
                    original['verification'] is not None and barriers,'Factual member silently lost or invented original verifier support')
                _require(stop['verification']==original['verification'],'Factual member verifier reference changed')
                plan=_read(None,original['plan'],context=context,db=db)
            _require(_linked_projection(ref,plan)==content['projection'] and _digest(plan)==candidate['definitions_digest'],
                'Retained linked approved local contract differs')
            members.append(dict(reference=ref,task=task,task_marker=task_marker,preparation=prepared,closure=closure,closed_at=closed_at,
                assignments=assignments,plan=plan,candidate=candidate))
            pending.extend(_linked_retained_references(body,ref['authority']));pending.extend(_linked_retained_references(prepared['metadata']['dependencies'],ref['authority']))
    if discovered:return dict(discovered_authorities=sorted(discovered.values(),key=_raw))
    _,expanded,observed=_linked_stop_sources(pointer,authorities)
    if expanded!=sorted(authorities,key=_raw):return dict(discovered_authorities=[a for a in expanded if _raw(a) not in known])
    _require([dict(reference=reference,metadata=metadata,stat=_closure_file_stat(Path(metadata['managed']['path']))) for _,(reference,metadata) in sorted(observed.items())]==basis['sources'],
        'Retained linked original source facts changed')
    snapshots=[dict(reference=m['reference'],plan=m['plan'],candidate=m['candidate']) for m in members]
    blockers,delivered,_,deliveries=_linked_lifecycle_outcomes(content,snapshots,observed=observed,consumer=pointer)
    _require(delivered and deliveries==basis['deliveries'],'Retained linked shared/exact delivery source support changed')
    sources={}
    while pending:
        ref=pending.pop();key=_raw(ref)
        if key in sources:continue
        _require(len(sources)<4096,'Retained linked source graph exceeds bound')
        if _raw(ref['authority']) not in known:discovered[_raw(ref['authority'])]=ref['authority'];continue
        context=_reference_context(ref['authority'])
        with _preparation_database(context,writer) as db:metadata,raw=_managed_artifact(None,ref['artifact'],context=context,db=db)
        sources[key]=dict(reference=ref,metadata=metadata,stat=_closure_file_stat(Path(metadata['managed']['path'])))
        for edge in metadata['dependencies']:
            target=edge['reference'];other=target.get('authority',ref['authority'])
            if _raw(other) not in known:discovered[_raw(other)]=other
            if edge['kind']=='artifact':pending.append(dict(authority=other,artifact=target.get('artifact',target)))
            elif edge['kind'] in {'assignment','recovery'}:pending.append(dict(authority=other,artifact=target['assignment'] if edge['kind']=='assignment' else target['artifact']))
            else:_require(edge['kind']=='task','Unknown retained source dependency remains protected')
    if discovered:return dict(discovered_authorities=sorted(discovered.values(),key=_raw))
    sources=[sources[key] for key in sorted(sources)]
    expected=_preparation_dependencies(dict(members=[dict(reference=m['reference'],certificate=m['preparation']['content']['stopped']) for m in members],sources=sources))
    _require(all(m['preparation']['metadata']['dependencies']==expected for m in members),'Retained preparation typed source dependencies changed')
    return dict(aggregate=pointer,basis=basis,component_digest=digest,members=members,sources=sources,authorities=sorted(authorities,key=_raw))


def _linked_stopped_basis(pointer,authorities,*,writer=None,fresh=False):
    """Open basis remains unchanged; only exact issued closures admit a historical successor."""
    if _linked_component_closed(pointer,writer=writer):
        retained=_linked_retained_component(pointer,authorities,writer=writer)
        _require(not retained.get('discovered_authorities'),'Retained linked source authority coverage is incomplete')
        if fresh:
            _require(all(m['task'] is not None for m in retained['members']),'Retired linked owners cannot obtain fresh verification')
            for member,original in zip(retained['members'],retained['basis']['members']):
                snapshot=_linked_terminal_snapshot(member['reference']) if retained['basis']['version']==2 else _linked_snapshot(member['reference'],stopped=True)
                _require(_digest(snapshot['candidate'])==original['candidate_digest'],'Closed linked current candidate changed')
                _linked_lifecycle_member(snapshot,retained['basis']['content'])
                _check_ready_inputs(original['inputs'])
        return retained['basis']
    capture=_linked_source(pointer)
    if capture.get('kind')=='linked-complete-stop' and capture.get('version')==2:
        basis=_linked_bound_basis(pointer,authorities,writer=writer)
        for original in basis['members']:
            ref=original['task'];context=_reference_context(ref['authority'])
            with _preparation_database(context,writer) as db:
                task=_linked_raw_task(db,ref)
                _require(task is not None,'Partly closed factual component lost its original raw owner')
                if task['lifecycle']['safe_closed_at'] is not None:
                    prepared=_linked_owned_preparation(context,db,ref)
                    _require(prepared['content']['stopped']['linked']==basis,'Closed factual member changed its original basis')
                    _linked_closed_member(context,db,ref,task,prepared)
        return basis
    content=_linked_contract(pointer);rows=[]
    for member in content['members']:
        ref=member['task'];context=_reference_context(ref['authority'])
        with _preparation_database(context,writer) as db:
            task=state._task(db,ref['scope_id'],ref['client'],ref['session_id'],ref['task_id'])
            _require(task is not None,'Linked raw member is unavailable; retirement is not supported')
            rows.append((ref,context,task))
    if not any(task['lifecycle']['safe_closed_at'] is not None for _,_,task in rows):
        return _linked_stop_basis(pointer,authorities)
    basis=None;component_digest=None;snapshots=[]
    for ref,context,task in rows:
        with _preparation_database(context,writer) as db:
            stop=task.get('writer_stop');state._writer_stop_shape(stop)
            retained=_read(None,stop['linked'],context=context,db=db);_linked_stop_shape(retained)
            if basis is None:basis=retained
            _require(retained==basis and _linked_basis_root(basis)==pointer and basis['content']==content,'Linked retained member basis changed')
            prepared=_linked_owned_preparation(context,db,ref);body=prepared['content']
            if component_digest is None:component_digest=body['component_digest']
            expected=next(row for row in basis['members'] if row['task']==ref)
            bindings=state._ready_stop_bindings(context,db,task)
            _require(body['component_digest']==component_digest and body['component']['aggregate']==basis['aggregate'] and
                body['component']['basis_digest']==_digest(basis) and body['component']['delivery_complete'] is True and
                body['component']['members']==[dict(reference=m['task'],state=m['state'],revision=m['revision'],pins=m['pins'],created_at=m['created_at']) for m in basis['members']], 'Linked preparation complete component changed')
            _require(body['identity']==ref and body['pins']==task['pins']==expected['pins'] and body['revision']==task['revision']==expected['revision'] and
                body['outcome']==task['state']==expected['state'] and body['created_at']==task['lifecycle']['created_at']==expected['created_at'] and
                body['accepted_identity']==task['accepted_identity'] and body['stopped']['linked']==basis and
                body['stopped']['writer_stop']==stop and bindings==expected['bindings'], 'Linked original raw member changed')
            proof=_read(None,stop['proof'],context=context,db=db);candidate=_read(None,stop['candidate'],context=context,db=db)
            verification=_stop_verification(context,db,task)
            _ready_stop_proof(task,proof,bindings,candidate,verification,basis)
            _require(body['stopped']['proof']==proof and stop['task_revision']==task['revision'] and stop['generation']==bindings['generation'] and
                stop['verification']==verification and all(proof[key]==stop[key] for key in ('observation_ref','coordinator_ref')),
                'Linked original independent stop changed')
            if task['lifecycle']['safe_closed_at'] is not None:_linked_closed_member(context,db,ref,task,prepared)
        if fresh or task['lifecycle']['safe_closed_at'] is None:
            snapshot=_linked_snapshot(ref,stopped=True)
            _require(snapshot['generation']==expected['bindings']['generation'] and snapshot['verification_ref']==expected['verification'] and
                _digest(snapshot['candidate'])==expected['candidate_digest'] and
                _linked_projection(ref,snapshot['plan'])==content['projection'], 'Linked current participant/source changed')
            _linked_lifecycle_member(snapshot,content)
            _check_ready_inputs(expected['inputs']);snapshots.append(snapshot)
        else:
            with _preparation_database(context,writer) as db:plan=_read(None,task['evidence']['plan'],context=context,db=db)
            _require(_linked_projection(ref,plan)==content['projection'],'Linked retained approved contract changed')
            snapshots.append(dict(reference=ref,task=task,candidate=candidate,plan=plan))
    _,expanded,observed=_linked_stop_sources(pointer,authorities)
    _require(expanded==sorted(authorities,key=_raw) and basis['authorities']==sorted(authorities,key=_raw),
        'Linked retained source authority set changed')
    actual=[dict(reference=reference,metadata=metadata,stat=_closure_file_stat(Path(metadata['managed']['path'])))
        for _,(reference,metadata) in sorted(observed.items())]
    _require(actual==basis['sources'],'Linked retained source support changed')
    blockers,delivered,_,deliveries=_linked_lifecycle_outcomes(content,snapshots,observed=observed,consumer=pointer)
    _require(delivered and deliveries==basis['deliveries'],'Linked acceptance or exact required delivery changed')
    return basis


_PREPARATION_ISSUER=object()


@dataclass(frozen=True)
class _PreparationObservation:
    facts: object
    authorities: object
    recovery: object
    recovery_files: object
    issuer: object


@dataclass(frozen=True)
class _PreparationOwner:
    reference: object
    observation: object
    content: object
    dependencies: tuple
    created_at: int


@contextmanager
def _preparation_database(context,writer=None):
    if writer is not None and writer[0].database==context.database:
        _check_context(context,writer[1]);yield writer[1]
    else:
        with _context_database(context) as db:yield db


def _linked_preparation_facts(pointer,authorities,*,writer=None):
    """Complete semantic/source facts; recovery interpretation belongs to the outer acquisition."""
    from runtime import changes,delegation
    content=_linked_contract(pointer)
    selected=content['selected'];context=_reference_context(selected['authority'])
    with _preparation_database(context,writer) as db:
        task=state._task(db,selected['scope_id'],selected['client'],selected['session_id'],selected['task_id'])
        _require(task is not None and task.get('writer_stop',{}).get('linked'),'Linked preparation needs every independent stop')
        basis=_read(None,task['writer_stop']['linked'],context=context,db=db)
    _require(_linked_basis_root(basis)==pointer and _linked_stopped_basis(pointer,basis['authorities'],writer=writer)==basis,
        'Linked preparation original basis changed')
    _require(basis['delivery_complete'] is True,'Linked preparation requires required merged or approved-null delivery')
    known={_raw(a):a for a in authorities};discovered={};members=[];pending=[]
    for row in basis['members']:
        ref=row['task'];context=_reference_context(ref['authority'])
        _require(_raw(ref['authority']) in known,'Linked preparation member authority is unguarded')
        with _preparation_database(context,writer) as db:
            task=state._task(db,ref['scope_id'],ref['client'],ref['session_id'],ref['task_id'])
            _require(task is not None and task.get('writer_stop',{}).get('linked'),'Linked preparation needs every independent stop')
            own_basis=_read(None,task['writer_stop']['linked'],context=context,db=db)
            _require(own_basis==basis,'Linked independent member bases differ')
            certificate=changes._stopped_certificate(context,db,dict(reference=ref,pins=task['pins']))
            records=delegation._closure_assignments(context,db,ref,task,certificate)
            all_records=delegation._ledger(None,db,context=context);guidance=delegation._closure_guidance(context,db,all_records)
            projection=_closure_assignment_projection(context,db,task,records);ids={r['id'] for r in records}
            projection.update(native_guidance=[item for item in guidance['native'] if item['reference']['id'] in ids],scope_guidance=guidance['sources'])
            local=deepcopy(task);local.pop('lifecycle',None);local['evidence'].pop('linked_verification',None)
            refs=[edge['reference'] for edge in _artifact_dependencies(local)]+guidance['references']
            for record in records:refs.extend(edge['reference'] for edge in _artifact_dependencies(record))
            pending.extend(dict(authority=ref['authority'],artifact=source) for source in refs)
            members.append(dict(reference=ref,task=dict(task,lifecycle=dict(created_at=task['lifecycle']['created_at'],safe_closed_at=None,closure=None,compact=None)),certificate=certificate,projection=projection,guidance=guidance))
            physical=_historical_inventory(context,db,_evidence_inventory_rows(db))
            folder=context.directory/'evidence'
            _require(sorted(path.name for path in folder.iterdir())==
                sorted(row['reference']['name'] for row in physical if row['stat'] is not None),
                'Unaccounted evidence content protects preparation')
    pending.append(dict(authority=pointer['authority'],artifact=pointer['reference']));sources={}
    while pending:
        ref=pending.pop();key=_raw(ref)
        if key in sources:continue
        _require(len(sources)<4096,'Preparation source traversal exceeds bound')
        authority=ref['authority']
        if _raw(authority) not in known:
            discovered[_raw(authority)]=authority;continue
        context=_reference_context(authority)
        with _preparation_database(context,writer) as db:
            metadata,raw=_managed_artifact(None,ref['artifact'],context=context,db=db)
        sources[key]=dict(reference=ref,metadata=metadata,stat=_closure_file_stat(Path(metadata['managed']['path'])))
        for edge in metadata['dependencies']:
            target=edge['reference'];other=target.get('authority',authority)
            if _raw(other) not in known:discovered[_raw(other)]=other
            if edge['kind']=='artifact':pending.append(dict(authority=other,artifact=target.get('artifact',target)))
            elif edge['kind'] in {'assignment','recovery'}:pending.append(dict(authority=other,artifact=target['assignment'] if edge['kind']=='assignment' else target['artifact']))
            else:_require(edge['kind']=='task','Preparation source dependency is unsupported')
    if discovered:return dict(discovered_authorities=sorted(discovered.values(),key=_raw))
    sources=[sources[key] for key in sorted(sources)]
    for member in members:
        own=member['reference'];guidance_refs=member['guidance']['references']
        member['projection']['sources']=[dict(reference=source['reference'],created_at=source['metadata']['created_at'],
            owner=source['metadata']['owner'],bytes=source['metadata']['bytes'],unit='bytes') for source in sources
            if source['metadata']['owner'].get('task')==own or source['reference']['authority']==own['authority'] and source['reference']['artifact'] in guidance_refs]
    receipts=[]
    fields={'linked-scope-decision':('version','kind','projection_digest','decision_ref','reference','observed_at'),
        'linked-integration-observation':('version','kind','inputs_digest','criteria','observed_at','reference'),
        'linked-delivery-observation':('version','kind','delivery','status','revision','observed_at','reference')}
    for source in _linked_source_refs(content['observations']):
        body=_linked_source(source);kind=body.get('kind');ref=dict(authority=source['authority'],artifact=source['reference'])
        metadata=next(item['metadata'] for item in sources if item['reference']==ref)
        receipts.append(dict(reference=ref,created_at=metadata['created_at'],owner=metadata['owner'],
            facts={key:body[key] for key in fields.get(kind,()) if key in body}))
    facts=dict(version=1,aggregate=pointer,basis=basis,members=members,sources=sources,receipts=receipts)
    _bounded(facts,MAX_ARTIFACT)
    return facts


def _preparation_member(facts,reference):
    matches=[m for m in facts['members'] if m['reference']==reference]
    _require(len(matches)==1,'Preparation member is outside the exact approved set')
    return matches[0]


def _preparation_content(facts,reference):
    member=_preparation_member(facts,reference);task=member['task'];basis=facts['basis']
    return dict(version=1,kind='linked-closure-preparation',identity=reference,pins=task['pins'],accepted_identity=task['accepted_identity'],
        created_at=task['lifecycle']['created_at'],revision=task['revision'],outcome=task['state'],stopped=member['certificate'],
        component_digest=_digest(facts),component=dict(aggregate=basis['aggregate'],basis_digest=_digest(basis),
            members=[dict(reference=m['reference'],state=m['task']['state'],revision=m['task']['revision'],pins=m['task']['pins'],
                created_at=m['task']['lifecycle']['created_at']) for m in facts['members']],
            acceptance=basis['content']['projection']['acceptance'],deliveries=basis['deliveries'],delivery_complete=basis['delivery_complete'],receipts=facts['receipts']),
        **member['projection'],usage='unknown',limitations=['Preparation preserves historical facts; it grants no safe closure, current readiness or delivery permission'])


def _preparation_dependencies(facts):
    owners={_raw(m['reference']) for m in facts['members']}
    assignments={_raw(a['reference']) for m in facts['members'] for a in m['certificate'].get('assignments',[])}
    sources={_raw(source['reference']):source for source in facts['sources']};raw=set();children={}
    for key,source in sources.items():
        authority=source['reference']['authority'];children[key]=[]
        for edge in source['metadata']['dependencies']:
            kind=edge['kind'];ref=edge['reference']
            if kind=='artifact':
                child=_raw(dict(authority=ref.get('authority',authority),artifact=ref.get('artifact',ref)))
                children[key].append(child)
                if child not in sources:raw.add(key)
            elif kind=='task':
                if _raw(ref) not in owners:raw.add(key)
            elif kind=='assignment':
                if _raw(ref) not in assignments:raw.add(key)
            else:raw.add(key)  # Recovery and unknown raw routes need their original owner support.
    pending=True
    while pending:
        expanded={key for key,refs in children.items() if any(child in raw for child in refs)}-raw
        pending=bool(expanded);raw.update(expanded)
    return [dict(kind='artifact',reference=source['reference']) for key,source in sources.items()
        if key in raw or _raw(source['metadata']['owner'].get('task')) not in owners]


def _preparation_receipt(facts,reference,*,writer=None):
    context=_reference_context(reference['authority']);expected=_preparation_content(facts,reference);found=[]
    with _preparation_database(context,writer) as db:
        rows=db.execute("select name,digest,owner_key,class,created_at,closed_at,status,bytes,data from evidence_metadata where class='compact' limit 4097").fetchall()
        _require(len(rows)<=4096,'Preparation receipt lookup exceeds bound')
        for row in rows:
            metadata=state._metadata_record(row)
            if metadata['owner'].get('task')!=reference:continue
            ref=dict(name=row[0],digest=row[1]);body=_read(None,ref,context=context,db=db)
            if body.get('kind')!='linked-closure-preparation':continue
            _require(body==expected and metadata['created_at']==expected['created_at'] and metadata['closed_at'] is None and
                metadata['status']=='live' and metadata['dependencies']==_preparation_dependencies(facts) and not metadata['targets'] and metadata['export'] is None,
                'Retained preparation differs from original component facts/age/dependencies')
            found.append(dict(authority=reference['authority'],artifact=ref))
    _require(len(found)<=1,'Duplicate logical preparation receipts remain protected')
    return found[0] if found else None


def _observe_linked_preparation(pointer,authorities):
    from runtime import changes
    pending=list(authorities)
    for _ in range(4096):
        with _linked_stop_guards(pointer,pending) as complete:
            facts=_linked_preparation_facts(pointer,complete)
            if facts.get('discovered_authorities'):
                pending=sorted({_raw(a):a for a in [*complete,*facts['discovered_authorities']]}.values(),key=_raw);continue
            refs=[m['reference'] for m in facts['members']]
            recovery=_canonical_plain(changes._inspect_lifecycle_recovery_guarded(complete,refs))
            if recovery['discovered_authorities']:
                pending=sorted({_raw(a):a for a in [*complete,*recovery['discovered_authorities']]}.values(),key=_raw);continue
            _require(recovery['complete'] and not recovery['blockers'],'Preparation recovery/source coverage is incomplete')
            files=_closure_recovery_files(recovery)
            return _PreparationObservation(_canonical_freeze(facts),_canonical_freeze(complete),_canonical_freeze(recovery),_canonical_freeze(files),_PREPARATION_ISSUER)
    raise state.StateError('Preparation authority closure did not converge')


def _check_preparation_inputs(facts,*,writer=None):
    """Last bounded writer check, after complete semantic/recovery interpretation."""
    from runtime import delegation
    checked=set()
    for member in facts['members']:
        ref=member['reference'];context=_reference_context(ref['authority'])
        original=next(row for row in facts['basis']['members'] if row['task']==ref)
        with _preparation_database(context,writer) as db:
            task=state._task(db,ref['scope_id'],ref['client'],ref['session_id'],ref['task_id'])
            closed=task is not None and task['lifecycle']['safe_closed_at'] is not None
            if closed:_linked_closed_member(context,db,ref,task,_linked_owned_preparation(context,db,ref))
            normalized=dict(task,lifecycle=dict(created_at=task['lifecycle']['created_at'],safe_closed_at=None,closure=None,compact=None)) if closed else task
            _require(normalized==member['task'] and state._ready_stop_bindings(context,db,task)==original['bindings'],
                'Preparation rows, assignments or generation changed before commit')
            for support in member['guidance']['retained']:
                _require(state._retired(db,'task',{key:support['identity'][key] for key in ('scope_id','client','session_id','task_id')})==support['marker'] and
                    all(state._retired_assignment(db,identity)==marker for identity,marker in support['assignments']),
                    'Preparation retained guidance ownership changed')
            authority=_raw(ref['authority'])
            if authority not in checked:
                checked.add(authority)
                physical=_historical_inventory(context,db,_evidence_inventory_rows(db))
                _require(sorted(path.name for path in (context.directory/'evidence').iterdir())==
                    sorted(row['reference']['name'] for row in physical if row['stat'] is not None),
                    'Unaccounted preparation content appeared before commit')
        if not closed:_check_ready_inputs(original['inputs'])
        guidance=member['guidance']
        if guidance['folder'] is not None:_require(_binding(Path(guidance['folder']['path']))==guidance['folder']['binding'],'Preparation guidance folder changed')
        for path,source in guidance['files'].items():
            _require(_closure_file_stat(Path(path))==source['stat'] and hashlib.sha256(delegation._read_bytes(Path(path))).hexdigest()==source['digest'],
                'Preparation guidance source changed before commit')
    for source in facts['sources']:
        ref=source['reference'];context=_reference_context(ref['authority']);metadata=source['metadata']
        with _preparation_database(context,writer) as db:_require(state._metadata(db,ref['artifact']['name'])==metadata,'Preparation source metadata changed')
        _require(_closure_file_stat(Path(metadata['managed']['path']))==source['stat'] and
            all(_binding(Path(path))==binding for path,binding in metadata['managed']['parents'].items()),
            'Preparation source bytes or physical identity changed before commit')


def _check_preparation_observation(observation,*,writer=None):
    from runtime import changes
    _require(isinstance(observation,_PreparationObservation) and observation.issuer is _PREPARATION_ISSUER and
        state._frozen_snapshot(observation.facts),'Preparation requires immutable actual owner acquisition')
    facts=_canonical_plain(observation.facts);authorities=_canonical_plain(observation.authorities)
    _require(_linked_preparation_facts(facts['aggregate'],authorities,writer=writer)==facts,'Preparation component/source facts changed')
    recovery=_canonical_plain(changes._inspect_lifecycle_recovery_guarded(authorities,[m['reference'] for m in facts['members']]))
    _require(recovery==_canonical_plain(observation.recovery) and _closure_recovery_files(recovery)==_canonical_plain(observation.recovery_files),
        'Preparation recovery observation changed before owner commit')
    _check_preparation_inputs(facts,writer=writer)
    return facts


def _prepare_linked_closure(observation):
    _require(isinstance(observation,_PreparationObservation) and observation.issuer is _PREPARATION_ISSUER,'Preparation requires owner observation')
    original=_canonical_plain(observation.facts);receipts=[]
    with _linked_stop_guards(original['aggregate'],_canonical_plain(observation.authorities)):
        facts=_check_preparation_observation(observation)
        for member in facts['members']:
            ref=member['reference'];context=_reference_context(ref['authority'])
            with _context_database(context,write=True) as db:
                _check_preparation_observation(observation,writer=(context,db))
                receipt=_preparation_receipt(facts,ref,writer=(context,db))
                if receipt is None:
                    content=_preparation_content(facts,ref);deps=tuple(_canonical_freeze(edge) for edge in _preparation_dependencies(facts))
                    owner=_PreparationOwner(_canonical_freeze(ref),observation,_canonical_freeze(content),deps,member['task']['lifecycle']['created_at'])
                    artifact=_artifact(None,content,context=context,owner=owner,db=db)
                    receipt=dict(authority=ref['authority'],artifact=artifact)
                    _check_preparation_observation(observation,writer=(context,db))
                    _require(_preparation_receipt(facts,ref,writer=(context,db))==receipt,'Prepared replacement was not registered exactly')
                _check_preparation_inputs(facts,writer=(context,db))
                receipts.append(dict(task=ref,reference=receipt,created_at=member['task']['lifecycle']['created_at']))
        return dict(complete=True,preparations=receipts)


def _linked_prepared_replacements(certificates,contexts,*,writer=None):
    """Prove all owned replacements before any linked raw route can be released."""
    authorities=[_canonical_plain(c.authority_set[0]) for c in contexts];groups={};extra=[];routes={};result=[]
    for certificate in certificates:
        if 'linked' not in certificate:result.append(certificate);continue
        pointer=_linked_basis_root(certificate['linked']);key=_raw(pointer)
        if key not in groups:
            present=False
            for row in certificate['linked']['members']:
                ref=row['task'];ctx=_reference_context(ref['authority'])
                with _preparation_database(ctx,writer) as db:
                    rows=db.execute("select name,digest,owner_key,class,created_at,closed_at,status,bytes,data from evidence_metadata where class='compact' limit 4097").fetchall()
                    _require(len(rows)<=4096,'Preparation discovery exceeds bound')
                    for item in rows:
                        metadata=state._metadata_record(item)
                        if metadata['owner'].get('task')==ref and _read(None,dict(name=item[0],digest=item[1]),context=ctx,db=db).get('kind')=='linked-closure-preparation':present=True
            if not present:
                groups[key]=(None,None);result.append(certificate);continue
            historical=_linked_component_closed(pointer,writer=writer)
            facts=_linked_retained_component(pointer,authorities,writer=writer) if historical else _linked_preparation_facts(pointer,authorities,writer=writer)
            _require(not facts.get('discovered_authorities'),'Prepared replacement authority coverage is incomplete')
            required={_raw(m['reference']) for m in facts['members']}
            actual={_raw(c['reference']) for c in certificates if c.get('linked') and _linked_basis_root(c['linked'])==pointer}
            _require(actual==required,'D4 prepared component omits an approved member')
            receipts={_raw(m['reference']):(dict(authority=m['reference']['authority'],artifact=m['preparation']['reference']) if historical else
                _preparation_receipt(facts,m['reference'],writer=writer)) for m in facts['members']}
            groups[key]=(facts,receipts if all(receipts.values()) else None)
            if all(receipts.values()):
                extra.extend(receipts.values());extra.extend(s['reference'] for s in facts['sources'])
                for source in facts['sources']:
                    if _raw(source['metadata']['owner'].get('task')) in required:
                        routes[_raw(source['reference'])]=required
        facts,receipts=groups[key]
        if receipts is not None:
            certificate=dict(certificate,preparation=dict(reference=receipts[_raw(certificate['reference'])]['artifact'],component_digest=facts['component_digest'] if 'component_digest' in facts else _digest(facts),authorities=authorities))
        result.append(certificate)
    return result,extra,routes


def _check_retained_linked_certificate(component,certificate):
    _require(not component.get('discovered_authorities'),'Retained linked source guards are incomplete')
    member=next((m for m in component['members'] if m['reference']==certificate['reference']),None)
    _require(member is not None and {key:value for key,value in certificate.items() if key!='preparation'}==member['preparation']['content']['stopped'],
        'Retained linked certificate differs from actual prepared/closed original owner')
    if 'preparation' in certificate:
        prepared=certificate['preparation'];required={_raw(a) for a in component['basis']['authorities']}
        required.update(_raw(m['reference']['authority']) for m in component['members'])
        for source in component['sources']:
            required.add(_raw(source['reference']['authority']))
            required.update(_raw(edge['reference'].get('authority',source['reference']['authority'])) for edge in source['metadata']['dependencies'])
        _require(prepared['reference']==member['preparation']['reference'] and prepared['component_digest']==component['component_digest'] and
            required<={_raw(a) for a in prepared['authorities']}<={_raw(a) for a in component['authorities']},
            'Retained preparation owner pointer/component/source set changed')
    return member


_PREPARATION_READER = ContextVar('linked_preparation_inspection_reader', default=None)


class _PreparationReader:
    """Ephemeral semantic observations owned by one read-only guarded inspection."""
    def __init__(self,authorities):
        self.authorities={_raw(_canonical_plain(a)):_canonical_plain(a) for a in authorities}
        self.entries={}
        self.active=True

    def _check_owner(self):
        _require(self.active and _PREPARATION_READER.get() is self,
            'Preparation reader is foreign or expired')

    def check(self,context,db,certificate):
        self._check_owner()
        authorities=certificate['preparation']['authorities'];pointer=_linked_basis_root(certificate['linked'])
        _require({_raw(a) for a in authorities}<=self.authorities.keys() and
            _raw(_canonical_plain(context.authority_set[0])) in self.authorities,
            'Preparation reader physical authority set differs')
        key=_raw(dict(aggregate=pointer,authorities=[self.authorities[a] for a in sorted(self.authorities)]))
        if key not in self.entries and _linked_component_closed(pointer,writer=(context,db)):
            support=_linked_retained_component(pointer,list(self.authorities.values()),writer=(context,db))
            _require(not support.get('discovered_authorities'),'Retained preparation authority coverage is incomplete')
            self.entries[key]=('retained',_canonical_freeze(support))
        if key in self.entries and self.entries[key][0]=='retained':
            _check_retained_linked_certificate(_canonical_plain(self.entries[key][1]),certificate)
            return
        if key not in self.entries:
            facts=_linked_preparation_facts(pointer,list(self.authorities.values()),writer=(context,db))
            _require(not facts.get('discovered_authorities'),'D4 prepared component authority set is incomplete')
            receipts={_raw(m['reference']).decode():_preparation_receipt(facts,m['reference'],writer=(context,db)) for m in facts['members']}
            _require(all(receipts.values()),'D4 requires every actual prepared replacement')
            self.entries[key]=(_canonical_freeze(facts),_canonical_freeze(receipts))
        captured,retained=self.entries[key];facts=_canonical_plain(captured);receipts=_canonical_plain(retained)
        required={_raw(a) for a in facts['basis']['authorities']}
        required.update(_raw(m['reference']['authority']) for m in facts['members'])
        for source in facts['sources']:
            authority=source['reference']['authority'];required.add(_raw(authority))
            required.update(_raw(edge['reference'].get('authority',authority)) for edge in source['metadata']['dependencies'])
        _require(required<={_raw(a) for a in authorities},'D4 prepared component authority set is incomplete')
        _require(_digest(facts)==certificate['preparation']['component_digest'],'D4 prepared component facts changed')
        own=receipts.get(_raw(certificate['reference']).decode())
        _require(own is not None and own['artifact']==certificate['preparation']['reference'],
            'D4 preparation pointer differs from actual owner receipt')

    def finish(self):
        self._check_owner()
        for captured,retained in self.entries.values():
            if captured=='retained':
                support=_canonical_plain(retained)
                _require(_linked_retained_component(support['aggregate'],list(self.authorities.values()))==support,
                    'Retained linked marker/source support changed during inspection')
                continue
            facts=_canonical_plain(captured);receipts=_canonical_plain(retained)
            _check_preparation_inputs(facts)
            _require(all(_preparation_receipt(facts,m['reference'])==receipts[_raw(m['reference']).decode()] for m in facts['members']),
                'D4 prepared replacement changed during inspection')
            _check_preparation_inputs(facts)


@contextmanager
def _linked_preparation_reader(authorities):
    reader=_PreparationReader(authorities);token=_PREPARATION_READER.set(reader)
    try:
        yield reader
    finally:
        reader.active=False;reader.entries.clear()
        _PREPARATION_READER.reset(token)


def _check_linked_preparation_certificate(context,db,certificate,*,preparation_reader=None,writer=None):
    if preparation_reader is not None:
        _require(type(preparation_reader) is _PreparationReader,'Preparation reader is foreign or expired')
        _require(writer is None,'Preparation inspection reader cannot replace an active writer')
        preparation_reader.check(context,db,certificate)
        return
    writer=writer if writer is not None else (context,db)
    basis=certificate['linked'];authorities=certificate['preparation']['authorities']
    if _linked_component_closed(_linked_basis_root(basis),writer=writer):
        _check_retained_linked_certificate(_linked_retained_component(_linked_basis_root(basis),authorities,writer=writer),certificate)
        return
    facts=_linked_preparation_facts(_linked_basis_root(basis),authorities,writer=writer)
    _require(not facts.get('discovered_authorities') and _digest(facts)==certificate['preparation']['component_digest'],
        'D4 prepared component facts changed')
    receipts=[_preparation_receipt(facts,m['reference'],writer=writer) for m in facts['members']]
    _require(all(receipts),'D4 requires every actual prepared replacement')
    own=_preparation_receipt(facts,certificate['reference'],writer=writer)
    _require(own['artifact']==certificate['preparation']['reference'],'D4 preparation pointer differs from actual owner receipt')
    _check_preparation_inputs(facts,writer=writer)


def _linked_inputs(snapshots):
    return [dict(task=row['reference'], pins=row['task']['pins'], plan_digest=_digest(row['plan']),
        candidate_digest=_digest(row['candidate'])) for row in snapshots]


def _linked_outcomes(projection, inputs_digest, acquired, snapshots, selected_ref, *, observed=None,require_shared_support=False,consumer=None):
    """Validate retained source correspondence; trusted acquisition owns its provenance/semantics."""
    state._fields(acquired, ('scope_decision','shared','deliveries'))
    _bounded(acquired, MAX_ARTIFACT)
    blockers=[]; sources=[]
    decision=_linked_source(acquired['scope_decision'],observed=observed,consumer=consumer,require_admission=True);sources.append(acquired['scope_decision'])
    _require(decision.get('kind') == 'linked-scope-decision' and type(decision.get('version')) is int and decision['version'] == 1
        and decision.get('projection_digest') == _digest(projection)
        and decision.get('decision_ref') == next(s['plan']['decision_ref'] for s in snapshots if s['reference']==selected_ref), 'Linked complete scope decision is unsupported')
    state._text(decision.get('reference'),'coordinator scope decision')
    state._integer(decision.get('observed_at'),'original scope observation time')
    _require(isinstance(acquired['shared'],list) and len(acquired['shared']) == len(projection['acceptance']), 'Shared criterion observations are incomplete')
    seen=set()
    for row in acquired['shared']:
        state._fields(row,('id','status','evidence','reference'))
        _require(row['id'] not in seen and row['id'] in {c['id'] for c in projection['acceptance']}, 'Shared criterion observation differs from approval')
        seen.add(row['id']);state._text(row['reference'],'shared semantic assessment')
        _require(row['status'] in {'passed','failed','unknown'} and isinstance(row['evidence'],list)
            and 0 < len(row['evidence']) <= 64, 'Shared source support is unavailable')
        supported=False
        for reference in row['evidence']:
            source=_linked_source(reference,observed=observed,consumer=consumer,require_admission=True);sources.append(reference)
            if (type(source.get('version')) is int and source['version'] == 1 and source.get('kind') == 'linked-integration-observation'
                    and source.get('inputs_digest') == inputs_digest and isinstance(source.get('criteria'),dict)
                    and source['criteria'].get(row['id']) == row['status']):
                state._integer(source.get('observed_at'),'original shared observation time')
                state._text(source.get('reference'),'observed integration source')
                supported=True
        _require(supported or not require_shared_support,'Linked lifecycle shared result lacks its actual input-bound source')
        if row['status'] != 'passed' or not supported:
            blockers.append('Shared criterion is unresolved or unsupported: '+row['id'])
    required={_raw(row['delivery']):row['delivery'] for row in projection['participants'] if row['delivery'] is not None}
    _require(isinstance(acquired['deliveries'],list) and len(acquired['deliveries']) <= len(required), 'Invalid linked delivery observation set')
    deliveries={};delivery_complete=True
    for row in acquired['deliveries']:
        state._fields(row,('delivery','status','source','observed_at','revision'))
        key=_raw(row['delivery']);_require(key in required and key not in deliveries, 'Unapproved or duplicate delivery observation')
        _require(row['status'] in {'merged','open','unknown'},'Invalid delivery observation status')
        state._integer(row['observed_at'],'original delivery observation time');state._text(row['revision'],'observed delivery revision')
        source={}
        if row['source'] is not None:
            try:source=_linked_source(row['source'],observed=observed,consumer=consumer,require_admission=True)
            except (StartupError,OSError):pass
            sources.append(row['source'])
        supported=(source.get('kind') == 'linked-delivery-observation' and type(source.get('version')) is int and source['version'] == 1
            and all(source.get(field) == row[field] for field in ('delivery','status','observed_at','revision')))
        owners=[s for s,p in zip(snapshots,projection['participants']) if p['delivery']==row['delivery']]
        current=all(s['candidate']['head']==row['revision'] and not any(
            entry[3:] != str(state.PROJECT_FILE) for entry in s['candidate']['dirty_inventory']) for s in owners)
        deliveries[key]=dict(row, status=row['status'] if supported and current else 'unknown')
    delivery_complete=all(key in deliveries and deliveries[key]['status']=='merged' for key in required)
    return sorted(set(blockers)),delivery_complete,sources,list(deliveries.values())


def _linked_source_refs(acquired):
    state._fields(acquired, ('scope_decision','shared','deliveries'))
    _require(isinstance(acquired['shared'],list) and len(acquired['shared']) <= 32
        and isinstance(acquired['deliveries'],list) and len(acquired['deliveries']) <= 65, 'Linked observation bound exceeded')
    sources=[acquired['scope_decision']]
    for row in acquired['shared']:
        state._fields(row,('id','status','evidence','reference'))
        _require(isinstance(row['evidence'],list) and len(row['evidence']) <= 64, 'Shared source bound exceeded')
        sources.extend(row['evidence'])
    sources.extend(row['source'] for row in acquired['deliveries'] if row.get('source') is not None)
    for source in sources:_authority_artifact(source)
    return sources


def _recheck_linked_sources(scope, db, acquired, snapshots, observed, *, aggregate=None):
    """Revalidate bounded original source bytes/metadata at the publication boundary."""
    strong={_raw(acquired['scope_decision'])}
    strong.update(_raw(reference) for row in acquired['shared'] for reference in row['evidence'])
    strong.update(_raw(dict(authority=row['reference']['authority'],reference=row['verification_ref'])) for row in snapshots)
    if aggregate is not None:strong.add(_raw(aggregate))
    delivery_changed=False
    for key,(reference,metadata) in observed.items():
        try:
            current={}
            connection=db if Path(reference['authority']['database'])==state._path(scope) else None
            _linked_source(reference,observed=current,db=connection,consumer=aggregate,require_admission=True)
            _require(current[key][1]==metadata,'Linked retained source metadata changed')
        except (StartupError,OSError):
            if key in strong:raise state.StateError('Linked implementation source changed before publication') from None
            delivery_changed=True
    return delivery_changed


def _recheck_linked_rows(scope, db, snapshots):
    for snapshot in snapshots:
        reference=snapshot['reference'];context=snapshot['context']
        def check(connection):
            _check_context(context,connection)
            current=state._task(connection,reference['scope_id'],reference['client'],reference['session_id'],reference['task_id'])
            generation=connection.execute('select generation from checkouts where scope_id=?',(reference['scope_id'],)).fetchone()
            _require(current==snapshot['task'] and generation is not None and generation[0]==snapshot['generation'],
                'Linked member row or generation changed before publication')
        if context.database==state._path(scope):check(db)
        else:
            with _context_database(context) as peer:check(peer)


def verify_linked(scope, request, observations):
    """Internal trusted-coordinator acquisition; a callable or JSON is not authentication.

    The integration caller verifies original scope/source semantics independently.
    The callback is bounded, local and read-only; no public JSON/CLI route exists.
    """
    _request(request, ('purpose',), ('reuse','security_impact'))
    request=deepcopy(request)
    _require(request['purpose'] in {'completion','merge-evidence'}, 'Invalid linked verification purpose')
    _linked_publication_entry(scope,request)
    selected_ref,projection,members=_linked_members(scope,deepcopy(request),observations)
    observe=observations['observe']
    for row in members:
        result=_verify_member(row['scope'],row['request'],linked=True)
        row['revision']=result['task']['revision']
    from runtime.changes import _authority_guards
    directories={Path(row['reference']['authority']['directory']) for row in members}
    acquired=None
    while True:
        with _authority_guards(directories),_current_content_acquisition(scope,request):
            snapshots=[_linked_snapshot(row['reference']) for row in members]
            _require(all(s['task']['revision']==m['revision'] for s,m in zip(snapshots,members)), 'Linked member changed during verification')
            inputs=_linked_inputs(snapshots)
            facts=dict(projection=projection,projection_digest=_digest(projection),inputs=inputs,inputs_digest=_digest(inputs))
            if acquired is None:
                # Snapshot the owner's result; caller mutation cannot revise an acquired observation.
                acquired=json_object(_raw(observe(_canonical_freeze(facts))),limit=MAX_ARTIFACT)
            sources=_linked_source_refs(acquired)
            expanded=directories | {Path(source['authority']['directory']) for source in sources}
            if expanded!=directories:
                directories=expanded
                continue  # Release every partial guard before acquiring the complete sorted set.
            for source in sources:
                context=_reference_context(source['authority'])
                try:
                    with _context_database(context) as reader:
                        metadata,_=_managed_artifact(None,source['reference'],context=context,db=reader)
                        expanded.update(Path(authority['directory']) for authority in _reverse_source_authorities(context,reader,metadata))
                except (StartupError,OSError):pass  # Semantic strong/optional source checks below preserve the actual outcome.
            if expanded!=directories:
                directories=expanded
                continue
            observed_sources={}
            shared_blockers,delivered,sources,deliveries=_linked_outcomes(projection,facts['inputs_digest'],acquired,snapshots,selected_ref,observed=observed_sources)
            for row in snapshots:
                _linked_source(dict(authority=row['reference']['authority'],reference=row['verification_ref']),observed=observed_sources)
            blockers=sorted(set(shared_blockers+[message for row in snapshots for message in row['blockers']]))
            final=[_linked_snapshot(row['reference']) for row in members]
            _require(_linked_inputs(final)==inputs and all(a['task']==b['task'] and a['generation']==b['generation']
                for a,b in zip(final,snapshots)), 'Linked inputs changed before publication')
            selected=next(row for row in final if row['reference']==selected_ref)
            content=dict(version=1,kind='linked-verification',purpose=request['purpose'],projection=projection,
                inputs=inputs,inputs_digest=facts['inputs_digest'],observations=acquired,
                members=[dict(task=s['reference'],revision=s['task']['revision'],generation=s['generation'],
                    verification=s['verification_ref']) for s in final],selected=selected_ref,
                publication_revision=selected['task']['revision']+1,implementation_verified=not blockers,
                delivery_complete=delivered,deliveries=deliveries,blockers=blockers)
            dependencies=[dict(kind='task',reference=s['reference']) for s in final if s['reference']!=selected_ref]
            dependencies += [dict(kind='artifact',reference=dict(authority=s['reference']['authority'],artifact=s['verification_ref'])) for s in final]
            dependencies += [dict(kind='artifact',reference=dict(authority=reference['authority'],artifact=reference['reference']))
                for reference in sources if _raw(reference) in observed_sources]
            publication=_linked_publication_plan(scope,request,content,final,acquired,observed_sources,dependencies)
            try:
                for source,metadata in observed_sources.values():
                    if source['authority']==selected_ref['authority']:continue
                    source_context=_reference_context(source['authority'])
                    with _context_database(source_context) as reader:
                        reverse=_reverse_source_authorities(source_context,reader,metadata,include_intents=False)
                    if selected_ref['authority'] not in reverse:_commit_foreign_intent(publication,source)
                with state._database(scope,write=True) as db:
                    current=_task(db,scope,dict(request,expected_revision=selected['task']['revision']))
                    _recheck_linked_rows(scope,db,final)
                    owner=_LinkedOwner(_artifact_owner(scope,current),
                        tuple(_canonical_freeze(d) for d in _publication_dependencies(publication)),publication)
                    reference=_artifact(scope,content,owner=owner,db=db)
                    _require(not _recheck_linked_sources(scope,db,acquired,final,observed_sources),
                        'Linked delivery changed after source intent; publication remains incomplete')
                    _recheck_linked_rows(scope,db,final)
                    pointer=dict(authority=selected_ref['authority'],reference=reference)
                    _require(_linked_source(pointer,db=db)==content,'Linked aggregate changed before publication')
                    _check_foreign_intents(publication,writer=(_evidence_context(scope),db))
                    current['evidence']['linked_verification']=pointer
                    if not blockers and request['purpose']=='completion':
                        current['state']='ready'
                        for condition in current['conditions']:
                            if 'continuation' in condition:condition['continuation']['revoked']=True
                    elif current['state']=='ready':current['state']='verifying'
                    current['revision']+=1
                    state._save(db,state._scope_id(scope),current)
                    # Independent final permission/source check follows all destination SQL writes.
                    _check_foreign_intent_sources(publication)
            finally:publication.state['active']=False
            break
    return dict(ok=True,verified=not blockers,implementation_verified=not blockers,delivery_complete=delivered,
        merge_authority=False,task=current,blockers=blockers,verification=pointer,deliveries=deliveries)


def _downgrade_linked(scope, task, db):
    current=state._task(db,state._scope_id(scope),task['client'],task['session_id'],task['task_id'])
    _require(current is not None and current['revision']==task['revision'], 'Linked claimant changed during freshness verification')
    if current['state']=='ready':
        current.update(state='verifying',reason='Linked implementation proof requires freshness verification',reference='evidence:linked-status')
        current['revision']+=1
        state._save(db,state._scope_id(scope),current)


def _revalidate_linked(scope, task, *, update_ready=False):
    """Recheck retained source/full inputs and optionally downgrade only this claimant."""
    pointer=task['evidence'].get('linked_verification')
    try:
        _require(pointer is not None,'Linked verification is missing')
        observed_sources={}
        content=_linked_source(pointer,observed=observed_sources)
        state._fields(content,('version','kind','purpose','projection','inputs','inputs_digest','observations','members',
            'selected','publication_revision','implementation_verified','delivery_complete','deliveries','blockers'))
        _require(type(content['version']) is int and content['version']==1 and content['kind']=='linked-verification'
            and content['selected']['scope_id']==state._scope_id(scope)
            and content['selected']['authority']==_canonical_plain(_evidence_context(scope).authority_set[0])
            and all(content['selected'][key]==task[key] for key in ('client','session_id','task_id')),
            'Linked verification selected identity changed')
        _require(isinstance(content['members'],list) and 1<=len(content['members'])<=65
            and [row['task'] for row in content['members']]==[row['task'] for row in content['projection']['participants']],
            'Linked retained participant set is incomplete')
        from runtime.changes import _authority_guards
        directories={Path(row['task']['authority']['directory']) for row in content['members']} | {
            Path(source['authority']['directory']) for source in _linked_source_refs(content['observations'])}
        with _authority_guards(directories):
            _require(_linked_source(pointer,observed=observed_sources)==content,'Linked aggregate source changed')
            snapshots=[_linked_snapshot(row['task']) for row in content['members']]
            for captured,current in zip(content['members'],snapshots):
                expected=content['publication_revision'] if captured['task']==content['selected'] else captured['revision']
                _require(current['task']['revision']==expected and current['generation']==captured['generation']
                    and current['verification_ref']==captured['verification'],'Linked member revision or generation changed')
                _require(_linked_projection(current['reference'],current['plan'])==content['projection'],'Linked approved contract changed')
            inputs=_linked_inputs(snapshots)
            _require(inputs==content['inputs'] and _digest(inputs)==content['inputs_digest'],'Linked member inputs are stale')
            blockers,delivered,_,deliveries=_linked_outcomes(content['projection'],content['inputs_digest'],content['observations'],snapshots,content['selected'],observed=observed_sources,consumer=pointer)
            for row in snapshots:
                _linked_source(dict(authority=row['reference']['authority'],reference=row['verification_ref']),observed=observed_sources)
            blockers=sorted(set(content['blockers']+blockers+[message for row in snapshots for message in row['blockers']]))
            result=dict(implementation_verified=not blockers,delivery_complete=delivered,deliveries=deliveries,blockers=blockers)
            mutate_ready=update_ready and task['state']=='ready'
            with state._database(scope,write=mutate_ready) as db:
                _recheck_linked_rows(scope,db,snapshots)
                if _recheck_linked_sources(scope,db,content['observations'],snapshots,observed_sources,aggregate=pointer):
                    result['delivery_complete']=False
                    result['deliveries']=[dict(row,status='unknown') for row in result['deliveries']]
                if mutate_ready and blockers:_downgrade_linked(scope,task,db)
            return result
    except (StartupError,OSError,ValueError,KeyError,TypeError,RecursionError):
        result=dict(implementation_verified=False,delivery_complete=False,deliveries=[],
            blockers=['Linked verification is stale, unavailable or incompatible'])
    if update_ready and task['state']=='ready':
        from runtime import delegation
        with delegation._reservation_write(scope) as db:_downgrade_linked(scope,task,db)
    return result


def _closed_status(scope,task):
    result=dict(historical=True,outcome=task['state'],current=False,implementation_verified=False,delivery_complete=False,
        merge_authority=False,status='unavailable',compact=task['lifecycle']['compact'])
    try:
        content=_read(scope,task['lifecycle']['compact'])
        if task.get('writer_stop',{}).get('linked'):
            context=_evidence_context(scope);ref=dict(authority=_canonical_plain(context.authority_set[0]),scope_id=_task_scope_id(task),
                **{key:task[key] for key in ('client','session_id','task_id')})
            with _context_database(context) as db:_linked_historical_closure(context,db,ref)
        _require(content['kind']=='task-closure' and content['revision']==task['revision'] and content['outcome']==task['state'] and
            content['pins']==task['pins'] and content['created_at']==task['lifecycle']['created_at'],'Historical closure support changed')
        result['status']='retained'
    except (StartupError,OSError,KeyError,TypeError):pass
    return result


def revalidate_ready(scope, client, session_id):
    """Status captures actual freshness and rechecks shared ownership before returning ready."""
    from runtime import delegation
    with state._database(scope) as db:
        task = state._task(db, state._scope_id(scope), client, session_id) if db else None
        if task is None or task['state'] != 'ready' or task.get('lifecycle',{}).get('safe_closed_at') is not None:
            return
        state._compatible(scope, task)
        request = {key: task[key] for key in IDENTITY[:4]} | dict(expected_revision=task['revision'])
        evidence = task.get('evidence')
        linked = bool(evidence and 'linked_verification' in evidence)
        verification = _read(scope, evidence['verification']) if not linked and evidence and 'verification' in evidence else None
        plan = _read(scope, evidence['plan']) if not linked and evidence else None
        closure = delegation._ready_closure(scope, task) if not linked else None
    valid = False
    if linked or plan and plan.get('version') == 2:
        _revalidate_linked(scope, task, update_ready=True)
        return
    try:
        candidate = capture_candidate(scope, plan) if plan and closure is not None else None
        valid = bool(verification and closure is not None and verification['purpose'] == 'completion' and not verification['blockers'] and
            verification['candidate_digest'] == _digest(candidate) and not _blockers(scope, task, plan, candidate, 'completion',
                verification.get('reuse', []), verification.get('security_impact'), resource_closure=closure))
    except (StartupError, OSError):
        valid = False
    with delegation._reservation_write(scope) as db:
        current = state._task(db, state._scope_id(scope), client, session_id)
        if current['state'] != 'ready':
            return
        _require(current['revision'] == request['expected_revision'], 'Ready task revision changed during freshness capture')
        valid = valid and not _ledger_blockers(scope, db, closure) and not _checkout_attempt_blockers(db, scope, current)
        if not valid:
            current.update(state='verifying', reason='Completion evidence requires freshness verification', reference='evidence:status')
            current['revision'] += 1
            state._save(db, state._scope_id(scope), current)


def evidence_status(scope, client, session_id):
    result = state.task_status(scope, client, session_id)
    result['scope_id'] = state._scope_id(scope)
    task = result['task']
    if task and task.get('lifecycle',{}).get('safe_closed_at') is not None:
        result['evidence']=result['historical'];return result
    if task and 'evidence' in task:
        plan = _read(scope, task['evidence']['plan'])
        if plan.get('version') == 2:
            result['evidence'] = _revalidate_linked(scope, task, update_ready=True)
            with state._database(scope) as db:
                result['task'] = state._task(db,state._scope_id(scope),client,session_id)
            return result
        try:
            candidate = capture_candidate(scope, plan)
            verification = _read(scope, task['evidence']['verification']) if 'verification' in task['evidence'] else {}
            current = verification.get('candidate_digest') == _digest(candidate)
            _, closure, _ = _verification_resources(scope, task, plan)
            result['evidence'] = dict(candidate_digest=_digest(candidate), blockers=_blockers(scope, task, plan, candidate, 'completion',
                verification.get('reuse', []) if current else [], verification.get('security_impact') if current else None,
                resource_closure=closure))
        except StartupError:
            result['evidence'] = dict(blockers=['Candidate capture is incomplete, unstable or unavailable'])
    else:
        result['evidence'] = dict(blockers=['Evidence plan is missing'])
    return result
