"""Bounded D5 evidence: private immutable artifacts, actual inputs and native receipts.

Coordinator decisions describe semantic coverage and existing authorization. They do
not authenticate review execution or grant permission for a command's effects.
"""
from contextlib import contextmanager
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


def _task(db, scope, request, revision=True):
    _require(db is not None, 'Task state has not been initialized')
    task = state._task(db, state._scope_id(scope), request['client'], request['session_id'])
    _require(task is not None and all(task[k] == request[k] for k in IDENTITY[:4]), 'Evidence task binding changed')
    state._compatible(scope, task)
    state._assert_open(task)
    _require(not revision or task['revision'] == request['expected_revision'], 'Task revision conflict')
    _require(task['state'] != 'cancelled', 'Cancelled tasks cannot collect or verify evidence')
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


def _recovery_source_history(context,db,reference,identity):
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
        if value['version']==2:
            from runtime import changes
            for certificate in value['stopped']:
                if certificate['reference']['authority']==_canonical_plain(context.authority_set[0]):
                    changes._check_stopped_certificate(context,db,certificate)
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
    changes._check_recovery_source(source, selected, db)
    baseline = state._source_baseline(None, db, context=selected)
    _require(baseline is not None, 'Recovery source baseline is unavailable; preserve operation markers')
    baseline = _canonical_plain(baseline)
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
            return _canonical_freeze(previous)
    content['previous'] = previous if content['version']==1 else None
    dependencies = _recovery_source_dependencies(content,_canonical_plain(selected.authority_set[0]))
    owner = _RecoveryOwner(baseline['content']['project_id'], source, created, tuple(_canonical_freeze(d) for d in dependencies), _canonical_freeze(content))
    reference = _artifact(None, content, context=selected, owner=owner, db=db)
    edges = [e for e in edges if e['reference']['identity'] != identity]
    edges.append(dict(kind='recovery',reference=dict(identity=identity,artifact=reference)))
    edges.sort(key=lambda e: _raw(e))
    _require(len(edges) <= 4096, 'Recovery baseline source bound exceeded')
    metadata = state._metadata(db, baseline['reference']['name'])
    metadata['dependencies'] = edges
    db.execute('update evidence_metadata set data=? where name=?', (_raw(metadata).decode(),baseline['reference']['name']))
    changes._check_recovery_source(source, selected, db)
    return _canonical_freeze(reference)


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
def _context_database(context, *, write=False):
    _check_context(context)
    db = None
    try:
        db = sqlite3.connect(context.database.as_uri() + ('?mode=rw' if write else '?mode=ro'), uri=True, timeout=0.1)
        db.execute('pragma trusted_schema=off')
        db.execute('begin immediate' if write else 'begin')
        _check_context(context, db)
        yield db
        _check_context(context, db)
        if write:
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
    _require('linked_verification' not in task.get('evidence',{}),
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
    authority=_canonical_plain(context.authority_set[0]);pending=list(roots);seen=set();requirements=[]
    while pending:
        edge=pending.pop(0);key=_raw(edge)
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
            metadata,raw=_managed_artifact(None,ref,context=context,db=db)
            value=json.loads(raw)
            for dependency in metadata['dependencies']:
                child=dict(dependency);child_need='content' if child['kind']=='artifact' else 'raw'
                if child['kind']=='task' and child['reference']==metadata['owner'].get('task') and value.get('kind')!='linked-verification':
                    child_need='identity'
                _require(child['kind'] in {'task','artifact'},'Unknown owner dependency requires its original raw support')
                pending.append(dict(owner=dict(authority=authority,artifact=ref),**child,need=child_need))
        else:
            raise state.StateError('Assignment, delivery or recovery body needs owner-specific closure support')
    return sorted(requirements,key=_raw)


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


def _closure_recovery(context,task_ref):
    from runtime import changes
    authorities=[_canonical_plain(context.authority_set[0])]
    result=_canonical_plain(changes._inspect_lifecycle_recovery_guarded(authorities,[task_ref]))
    before=_closure_recovery_files(result)
    latest=_canonical_plain(changes._inspect_lifecycle_recovery_guarded(authorities,[task_ref]))
    _require(latest==result and _closure_recovery_files(latest)==before,'Recovery source moved during closure observation')
    return result,before


def _ready_stop_shape(proof):
    _bounded(proof)
    state._fields(proof,('version','kind','identity','expected_revision','expected_pins','observed_turn_id','stopped','descendants_stopped',
        'attempt_ids','observation_ref','coordinator_ref','candidate_digest','verification_digest','task_digest','attempts_digest','assignments_digest','generation'))
    state._integer(proof['expected_revision'],'ready proof revision',1);state._validate_pins(proof['expected_pins'])
    state._fields(proof['identity'],IDENTITY[:4]);state._identity(proof['identity'])
    _require(isinstance(proof['attempt_ids'],list) and len(proof['attempt_ids'])<=MAX_ATTEMPTS and
        all(isinstance(item,str) for item in proof['attempt_ids']) and len(set(proof['attempt_ids']))==len(proof['attempt_ids']),
        'Ready stop attempt identity set is malformed')
    if proof['observed_turn_id'] is not None:state._text(proof['observed_turn_id'],'ready stop turn',4096)
    for key in ('observation_ref','coordinator_ref'):state._text(proof[key],key)
    for key in ('candidate_digest','verification_digest','task_digest','attempts_digest','assignments_digest'):state._canonical_hash(proof[key])
    state._integer(proof['generation'],'ready proof generation')
    _require(type(proof['version']) is int and proof['version']==2 and proof['kind']=='stopped-writer-reconciliation' and
        proof['stopped'] is True and proof['descendants_stopped'] is True,'Independent complete ready stop remains missing')


def _ready_stop_proof(task,proof,bindings,candidate):
    _ready_stop_shape(proof)
    attempts=task.get('evidence',{}).get('attempts',[])
    _require(task['state']=='ready' and task['pins']['schema_version']==3 and type(proof['version']) is int and proof['version']==2 and
        proof['kind']=='stopped-writer-reconciliation' and proof['stopped'] is True and proof['descendants_stopped'] is True and
        proof['identity']=={k:task[k] for k in ('client','session_id','task_id','scope_ref')} and
        proof['expected_revision']==task['revision'] and proof['expected_pins']==task['pins'] and proof['observed_turn_id']==task['turn_id'] and
        proof['attempt_ids']==[a['id'] for a in attempts] and not any(a['status'] in {'reserved','running','uncertain'} for a in attempts) and
        all(proof[k]==v for k,v in bindings.items()) and proof['candidate_digest']==_digest(candidate) and
        proof['verification_digest']==task['evidence']['verification']['digest'],
        'Independent ready stop does not bind the complete current original owner snapshot')


def _check_ready_inputs(files,*,directory_identity=False):
    for path,value in files.items():
        current=_closure_file_stat(Path(path)) if os.path.lexists(path) else None
        if value is not None and stat.S_ISDIR(value[2]) and (directory_identity or len(value)==4):
            _require(current is not None and current[:4]==value[:4],'Ready input directory identity changed')
        else:_require(current==value,'Ready candidate inputs changed before owner commit')


def _ready_stop_candidate(context,task,candidate):
    """Read-only freshness from original pinned context; never reserve another verifier."""
    with _context_database(context) as db:
        plan=_read(None,task['evidence']['plan'],context=context,db=db)
        verification=_read(None,task['evidence']['verification'],context=context,db=db)
    _require(task['state']=='ready' and plan['version']==1 and 'linked_verification' not in task['evidence'] and
        verification['purpose']=='completion' and not verification['blockers'] and verification['plan_digest']==_digest(plan) and
        verification['candidate_digest']==_digest(candidate),'Ready verification is missing, linked or stale')
    _candidate_projection(candidate,task)
    _require(state.runtime_fingerprint()==task['pins']['runtime_digest'] and policy_digest(state.PACKAGE)==task['pins']['policy_digest'],
        'Installed ready source pins changed')
    locator=_pinned_locator(task,context)
    first=_capture(locator,plan,pinned=(task['accepted_identity'],task['pins']))
    second=_capture(locator,plan,pinned=(task['accepted_identity'],task['pins']))
    _require(first==second==candidate,'Ready candidate changed after independent stop')
    _require(not _blockers(locator,task,plan,candidate,'completion',verification.get('reuse',[]),verification.get('security_impact'),
        resource_closure=verification['resource_closure'],context=context),'Ready findings/resources remain blocked')
    # Stat snapshots supplement the complete capture at the last short writer.
    root=Path(task['accepted_identity']['repository_root']);git=Path(task['accepted_identity']['git_dir'])
    common=Path(task['accepted_identity']['git_common_dir'])
    paths={root,root/'.git',git,common,git/'HEAD',git/'index',git/'commondir',common/'HEAD',common/'packed-refs'}
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
    ready_files=_ready_stop_candidate(context,task,_read(None,task['writer_stop']['candidate'],context=context,db=db)) if ready else {}
    certificate=changes._stopped_certificate(context,db,dict(reference=task_ref,pins=task['pins']))
    _require(ready or not certificate['proof']['attempt_ids'],'Stopped unresolved attempts require assignment certificate integration')
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
    physical=[];compact=task['lifecycle']['compact']
    for item in observed['metadata']:
        ref=item['reference'];path=Path(item['metadata']['managed']['path']);before=_closure_file_stat(path)
        metadata,raw=_managed_artifact(None,ref,context=context,db=db)
        _require(_closure_file_stat(path)==before,'Managed source moved during closure read')
        owner=metadata['owner'];body=json.loads(raw)
        _require(owner.get('kind')=='project' and owner.get('project_id')==task['accepted_identity']['project_id'],
            'Unknown or foreign evidence owner remains protected')
        _require(owner['task'] is None or owner['task']['authority']==authority,'Foreign evidence task owner remains protected')
        if owner['task'] is None:
            _require(metadata['class']=='compact' and body.get('kind') in {'authority-source-baseline','d4-recovery-source'}
                or metadata['class']=='detail' and ref in guidance['references'],
                'Scope-owned consumer dependencies require existing guidance/review owner integration')
        physical.append(dict(reference=ref,metadata=metadata,stat=before))
    folder=context.directory/'evidence'
    names=sorted(p.name for p in folder.iterdir()) if folder.exists() else []
    _require(len(names)<=4096 and names==sorted(item['reference']['name'] for item in observed['metadata']),
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


def _observe_closure(contexts, task_ref):
    """Internal owner observation. Types/flags authenticate nothing; writers rederive facts."""
    from runtime import changes
    contexts=tuple(contexts);_require(len(contexts)==1,'Foreign owner closure needs complete terminal component integration')
    context=contexts[0];authority=_canonical_plain(context.authority_set[0])
    _require(task_ref['authority']==authority,'Closure task authority differs')
    with changes._authority_guards([context.directory]):
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
    current=state.inspect_dependencies(db,task_ref)
    compact=(current['task']['lifecycle']['compact'] if current['task'] else None) or new_compact
    if current['task'] is not None:
        current['task']=dict(current['task'],lifecycle=dict(created_at=current['task']['lifecycle']['created_at'],safe_closed_at=None,closure=None,compact=None))
    current['tasks']=[dict(row,task=current['task']) if row['reference']==task_ref else row for row in current['tasks']]
    current['metadata']=[item for item in current['metadata'] if item['reference']!=compact]
    current.pop('digest')
    expected=deepcopy(facts['observed'])
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
        _require(_closure_file_stat(Path(item['metadata']['managed']['path']))==item['stat'],'Closure source bytes or physical identity changed')
        for path,binding in item['metadata']['managed']['parents'].items():
            _require(_binding(Path(path))==binding,'Closure content parent changed')
    _require(all(_closure_file_stat(Path(path))==value for path,value in facts['recovery_files'].items()),'Recovery source changed before closure commit')
    _check_ready_inputs(facts['ready_files'])
    guidance=facts['guidance']
    for support in guidance['retained']:
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
    expected=sorted([item['reference']['name'] for item in current['metadata']]+([] if compact is None else [compact['name']]))
    _require(names==expected,'Unaccounted content appeared before closure commit')
    if compact is not None:
        _require(_read(None,compact,context=context,db=db)==_closure_content(facts),'Compact support differs from original owner facts')
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
    with changes._authority_guards([context.directory]):
        recovery,files=_closure_recovery(context,task_ref)
        with _context_database(context) as reader:
            actual=_closure_facts(context,task_ref,reader,recovery,recovery_files=files)
        _require(actual==_issued_closure(context,observations),'Closure owner observation is stale or caller supplied')
        issued=_ClosureObservation(_canonical_freeze(actual),context,_CLOSURE_ISSUER)
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


def _retire_closed_task(context, task_ref):
    from runtime import changes,delegation
    with changes._authority_guards([context.directory]):
        recovery,files=_closure_recovery(context,task_ref)
        with _context_database(context) as reader:
            facts=_closure_facts(context,task_ref,reader,recovery,recovery_files=files)
        issued=_ClosureObservation(_canonical_freeze(facts),context,_CLOSURE_ISSUER)
        with _context_database(context,write=True) as db:
            _check_closure_observation(context,db,task_ref,issued)
            task=state._task(db,task_ref['scope_id'],task_ref['client'],task_ref['session_id'],task_ref['task_id'])
            _require(task['lifecycle']['safe_closed_at'] is not None,'Task has no retained safe closure')
            compact=_read(None,task['lifecycle']['compact'],context=context,db=db)
            _require(compact==_closure_content(facts),'Closure support or current dependencies changed')
            delegation.retire_settled(db,task_ref,issued)
            return state.retire_closed(db,task_ref,issued)


def _registered_owner(scope, context, owner, db):
    if isinstance(owner,_ClosureOwner):
        ref=_canonical_plain(owner.reference)
        facts=_check_closure_observation(context,db,ref,owner.facts)
        _require(_canonical_plain(owner.content)==_closure_content(facts)
            and owner.created_at==facts['task']['lifecycle']['created_at']
            and [_canonical_plain(d) for d in owner.dependencies]==[dict(kind='artifact',reference=r) for r in facts['artifacts']],
            'Closure registration differs from existing owner-derived facts')
        return dict(kind='project',project_id=facts['task']['accepted_identity']['project_id'],task=ref),ref
    if isinstance(owner, _LinkedOwner):
        return _registered_owner(scope, context, owner.task_owner, db)
    if isinstance(owner, _RecoveryOwner):
        from runtime import changes
        changes._check_recovery_source(owner.source, context, db)
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
    state._assert_open(task)
    _require(state._physical_identity(task['accepted_identity']) == state._physical_identity(_canonical_plain(scope.accepted_identity)),
        'Artifact original task physical owner changed')
    return dict(kind='project', project_id=owner.project_id, task=reference), reference


def _artifact_dependencies(value):
    references = {}
    def visit(item):
        if isinstance(item, dict):
            if set(item) == {'name', 'digest'}:
                state._artifact_reference(item)
                references[_raw(item)] = dict(kind='artifact', reference=item)
            else:
                for child in item.values(): visit(child)
        elif isinstance(item, list):
            for child in item: visit(child)
    visit(value)
    _require(len(references) < 4096, 'Artifact dependency bound exceeded')
    return list(references.values())


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
        with _context_database(context, write=True) as connection:
            return _artifact_registered(scope, value, context, owner, connection)
    _check_context(context, db)
    return _artifact_registered(scope, value, context, owner, db)


def _artifact_registered(scope, value, context, owner, db):
    metadata_owner, task_ref = _registered_owner(scope, context, owner, db)
    raw = _raw(value)
    _require(len(raw) <= MAX_ARTIFACT, 'Evidence artifact size limit exceeded')
    folder = context.directory / 'evidence'
    try:
        folder.mkdir(mode=0o700)
    except FileExistsError:
        pass
    state._private(folder, True)
    parents = {str(folder): _binding(folder), str(context.directory): _binding(context.directory)}
    name = state._source_baseline_name(_canonical_plain(owner.creation.authority)) if isinstance(owner, _BaselineOwner) else uuid.uuid4().hex + '.json'
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
    recovery = isinstance(owner, _RecoveryOwner)
    if recovery or isinstance(owner,_ClosureOwner): _require(value == _canonical_plain(owner.content), 'Artifact differs from owner-derived content')
    dependencies = [_canonical_plain(d) for d in owner.dependencies] if recovery or isinstance(owner, (_LinkedOwner,_ClosureOwner)) else _artifact_dependencies(value)
    if task_ref is not None:
        dependencies.insert(0, dict(kind='task', reference=task_ref))
    baseline = isinstance(owner, _BaselineOwner)
    created = owner.creation.created_at if baseline else owner.created_at if recovery or isinstance(owner,_ClosureOwner) else state._owner_time()
    content_class = 'compact' if baseline or recovery or isinstance(owner,_ClosureOwner) else 'detail'
    if baseline:
        expected = dict(version=1, kind='authority-source-baseline', source_contract=2,
            authority=_canonical_plain(owner.creation.authority), project_id=owner.project_id,
            created_at=created, runtime_digest=state.runtime_fingerprint())
        _require(value == expected and not dependencies, 'Baseline content differs from fresh owner provenance')
        state._check_creation(context.database, owner.creation, db)
    data = dict(version=1, owner=metadata_owner, created_at=created, **{'class': content_class}, bytes=len(raw),
        status='live', closed_at=None, dependencies=dependencies, targets=[], export=None,
        managed=dict(path=str(path), binding=dict(device=info.st_dev, inode=info.st_ino), parents=parents,
            sha256=digest, mode=stat.S_IMODE(info.st_mode), bytes=info.st_size))
    row = (path.name, digest, 'project:' + metadata_owner['project_id'], content_class, created, None, 'live', len(raw), _raw(data).decode())
    state._metadata_record(row)
    _check_context(context, db)
    _require(all(_binding(Path(parent)) == binding for parent, binding in parents.items())
        and _binding(path) == data['managed']['binding'], 'Artifact identity changed before registration')
    db.execute('insert into evidence_metadata values(?,?,?,?,?,?,?,?,?)', row)
    return dict(name=path.name, digest=digest)


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
    return metadata, raw


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


def _linked_source(reference, *, observed=None, db=None):
    _authority_artifact(reference)
    context = _reference_context(reference['authority'])
    def consume(connection):
        _check_context(context,connection)
        metadata=state._metadata(connection,reference['reference']['name'])
        value=_read(None,reference['reference'],context=context,db=connection)
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


def _linked_members(scope, request, observations):
    state._fields(observations, ('members', 'observe'))
    _require(callable(observations['observe']), 'Linked observation acquisition requires the existing trusted coordinator owner')
    rows = observations['members']
    _require(isinstance(rows, list) and 1 <= len(rows) <= 65, 'Invalid bounded linked members')
    with state._database(scope) as db:
        selected = _task(db, scope, request)
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
            task = _task(db, member_scope, member_request)
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


def _linked_snapshot(reference):
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
    return dict(task=task,plan=plan,candidate=candidate,context=context,generation=generation,
        verification=verification,verification_ref=verification_ref,blockers=sorted(set(blockers)),reference=reference)


def _linked_inputs(snapshots):
    return [dict(task=row['reference'], pins=row['task']['pins'], plan_digest=_digest(row['plan']),
        candidate_digest=_digest(row['candidate'])) for row in snapshots]


def _linked_outcomes(projection, inputs_digest, acquired, snapshots, selected_ref, *, observed=None):
    """Validate retained source correspondence; trusted acquisition owns its provenance/semantics."""
    state._fields(acquired, ('scope_decision','shared','deliveries'))
    _bounded(acquired, MAX_ARTIFACT)
    blockers=[]; sources=[]
    decision=_linked_source(acquired['scope_decision'],observed=observed);sources.append(acquired['scope_decision'])
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
            source=_linked_source(reference,observed=observed);sources.append(reference)
            if (type(source.get('version')) is int and source['version'] == 1 and source.get('kind') == 'linked-integration-observation'
                    and source.get('inputs_digest') == inputs_digest and isinstance(source.get('criteria'),dict)
                    and source['criteria'].get(row['id']) == row['status']):
                state._integer(source.get('observed_at'),'original shared observation time')
                state._text(source.get('reference'),'observed integration source')
                supported=True
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
            try:source=_linked_source(row['source'],observed=observed)
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
            _linked_source(reference,observed=current,db=connection)
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
    _require(request['purpose'] in {'completion','merge-evidence'}, 'Invalid linked verification purpose')
    selected_ref,projection,members=_linked_members(scope,deepcopy(request),observations)
    observe=observations['observe']
    for row in members:
        result=_verify_member(row['scope'],row['request'],linked=True)
        row['revision']=result['task']['revision']
    from runtime.changes import _authority_guards
    directories={Path(row['reference']['authority']['directory']) for row in members}
    acquired=None
    while True:
        with _authority_guards(directories):
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
            dependencies += [dict(kind='artifact',reference=dict(authority=reference['authority'],artifact=reference['reference'])) for reference in sources]
            with state._database(scope,write=True) as db:
                current=_task(db,scope,dict(request,expected_revision=selected['task']['revision']))
                _recheck_linked_rows(scope,db,final)
                owner=_LinkedOwner(_artifact_owner(scope,current),tuple(_canonical_freeze(d) for d in dependencies))
                db.execute('savepoint linked_publication')
                reference=_artifact(scope,content,owner=owner,db=db)
                if _recheck_linked_sources(scope,db,acquired,final,observed_sources):
                    # One conservative correction; the first file remains a protected orphan.
                    db.execute('rollback to linked_publication')
                    delivered=False
                    deliveries=[dict(row,status='unknown') for row in deliveries]
                    content.update(delivery_complete=False,deliveries=deliveries)
                    reference=_artifact(scope,content,owner=owner,db=db)
                    _recheck_linked_sources(scope,db,acquired,final,observed_sources)
                db.execute('release linked_publication')
                _recheck_linked_rows(scope,db,final)
                pointer=dict(authority=selected_ref['authority'],reference=reference)
                _require(_linked_source(pointer,db=db)==content,'Linked aggregate changed before publication')
                current['evidence']['linked_verification']=pointer
                if not blockers and request['purpose']=='completion':
                    current['state']='ready'
                    for condition in current['conditions']:
                        if 'continuation' in condition:condition['continuation']['revoked']=True
                elif current['state']=='ready':current['state']='verifying'
                current['revision']+=1
                state._save(db,state._scope_id(scope),current)
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
            blockers,delivered,_,deliveries=_linked_outcomes(content['projection'],content['inputs_digest'],content['observations'],snapshots,content['selected'],observed=observed_sources)
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
