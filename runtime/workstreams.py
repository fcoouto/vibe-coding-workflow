"""Optional checkout mode and one-use native send gates over the existing D6 authority."""
import re
import uuid

from runtime import delegation as d6, evidence, state
from runtime.startup import json_object


LIMITATIONS = [
    'Workstreams is an optional Codex mode; saved enablement qualifies no native capability',
    'Send admission is cooperative and one-use; native delivery is neither atomic nor exactly-once',
    'Requested token, step and time allocations are not hard native execution enforcement',
    'Delivery records are coordinator assertions; native observation and D6 ownership proof remain authoritative',
]
TRANSIENT = {'serverOverloaded', 'internalServerError', 'httpConnectionFailed',
             'responseStreamConnectionFailed', 'responseStreamDisconnected', 'responseTooManyFailedAttempts'}
LIMIT_FAILURES = {'rateLimitExceeded', 'usageLimitExceeded'}


def _path(scope):
    return state._path(scope).parent / ('workstreams-' + state._scope_id(scope) + '.json')


def _binding(scope):
    def identity(path):
        info = path.lstat()
        return dict(device=info.st_dev, inode=info.st_ino)
    return dict(scope_id=state._scope_id(scope), repository=identity(scope.repository_root),
        git_common=identity(scope.git_common_dir), directory=identity(state._path(scope).parent),
        database=identity(state._path(scope)))


def _load(scope):
    return _load_bound(_path(scope), _binding(scope) if _path(scope).parent.exists() and state._path(scope).exists() else None)


def _load_bound(path, binding):
    """Read the supported setting using an already authenticated physical binding."""
    if not path.parent.exists():
        return dict(version=1, revision=0, enabled=False, binding=None)
    state._private(path.parent, True)
    raw = d6._read_bytes(path)
    if raw is None:
        return dict(version=1, revision=0, enabled=False, binding=None)
    value = json_object(raw, limit=d6.MAX_GUIDANCE)
    return _validate_setting_value(value,binding)


def _validate_setting_value(value,binding):
    """Validate recorded or current v1 data against its exact physical binding."""
    state._fields(value, ('version', 'revision', 'enabled', 'binding'), ('handoff',))
    d6._require(type(value['version']) is int and value['version'] == 1 and
        type(value['revision']) is int and 0 < value['revision'] < 2**53 and
        type(value['enabled']) is bool and binding is not None and value['binding'] == binding,
        'Workstreams setting is corrupt or its checkout authority changed')
    if 'handoff' in value:
        handoff = value['handoff']
        state._fields(handoff, ('version', 'descriptor', 'manifest_digest', 'source_revision', 'source_enabled'))
        d6._require(type(handoff['version']) is int and handoff['version'] == 1
            and type(handoff['source_enabled']) is bool, 'Invalid Workstreams handoff provenance')
        d6._require(d6._hex(handoff['descriptor']) and d6._hex(handoff['manifest_digest']), 'Invalid Workstreams handoff digest')
        state._integer(handoff['source_revision'], 'Workstreams original revision')
    return value


def initialize_default(scope, db):
    """Seed only a newly registered checkout inside its existing transaction."""
    d6._require(db is not None and db.in_transaction and db.execute(
        'select 1 from checkouts where scope_id=?', (state._scope_id(scope),)).fetchone() is not None,
        'Workstreams default requires existing checkout authority and its write transaction')
    current = _load(scope)
    if current['revision'] == 0:
        updated = dict(version=1, enabled=True, revision=1, binding=_binding(scope))
        d6._atomic(_path(scope), updated,
            guard=lambda: d6._require(_load(scope) == current, 'Workstreams setting changed during publication'))


def _permission(scope, revision):
    state._integer(revision, 'Workstreams revision', 1)
    setting = _load(scope)
    d6._require(setting['enabled'] and setting['revision'] == revision,
        'Workstreams is disabled or its revision changed; reassess pending work')
    return setting


def _report(scope, setting, db):
    records = d6._ledger(scope, db) if db is not None else []
    active = [r for r in records if r['owner']['scope_id'] == state._scope_id(scope)
        and 'workstream_revision' in r['body']['request'] and r['data']['status'] != 'settled']
    return dict(ok=True, control_scope='checkout', scope_id=state._scope_id(scope),
        checkout=str(scope.repository_root), enabled=setting['enabled'], revision=setting['revision'],
        unresolved_assignments=len(active), drained=not active, activity='unresolved' if active else 'drained',
        limitations=list(LIMITATIONS))


def control(scope, action, request):
    """Inspect without creating state; controls do not launch, probe, or change any route."""
    state._fields(request, ('client',) if action == 'status' else ('client', 'expected_revision'))
    d6._require(request['client'] == 'codex' and action in {'enable', 'disable', 'status'},
        'Unsupported Workstreams control')
    if action == 'status':
        with state._database(scope) as db:
            return _report(scope, _load(scope), db)
    state._integer(request['expected_revision'], 'Workstreams expected revision')
    with d6._reservation_write(scope) as db:
        d6._require(db is not None and db.execute('select 1 from checkouts where scope_id=?', (state._scope_id(scope),)).fetchone() is not None,
            'Workstreams requires the existing checkout runtime authority')
        current = _load(scope)
        d6._require(current['revision'] == request['expected_revision'], 'Workstreams revision conflict')
        wanted = action == 'enable'
        if current['enabled'] != wanted or current['revision'] == 0:
            updated = dict(current, version=1, enabled=wanted, revision=current['revision'] + 1, binding=_binding(scope))
            d6._require(updated['revision'] < 2**53, 'Workstreams revision exhausted')
            d6._atomic(_path(scope), updated, guard=lambda: d6._require(_load(scope) == current,
                'Workstreams setting changed during publication'))
            current = _load(scope)
        return _report(scope, current, db)


def validate_admission(scope, request):
    """Omission preserves ordinary D6. Mode-specific fields travel in the original assignment."""
    present = {'workstream_revision', 'workstream_limits'} & request.keys()
    if not present:
        return
    d6._require(present == {'workstream_revision', 'workstream_limits'}, 'Workstreams requires revision and task-derived limits')
    _permission(scope, request['workstream_revision'])
    d6._native_name('0' * 32, 'worker', request)
    limits = request['workstream_limits']
    state._fields(limits, ('context_id', 'rationale', 'output_tokens', 'context_tokens', 'max_steps',
        'max_seconds', 'max_continuations', 'backoff_seconds'))
    for key in ('context_id', 'rationale'):
        state._text(limits[key], 'Workstreams ' + key, 4096 if key == 'rationale' else 128)
    for key in ('output_tokens', 'context_tokens', 'max_steps', 'max_seconds', 'max_continuations', 'backoff_seconds'):
        state._integer(limits[key], 'Workstreams ' + key, 0 if key in {'max_continuations', 'backoff_seconds'} else 1)
        d6._require(limits[key] < 2**53, 'Workstreams allocation exceeds finite input bounds')


def validate_record(value, read):
    """Validate additive immutable references without changing original assignment authority."""
    for key in ('workstream_dispatch', 'workstream_continuation'):
        if key in value:
            d6._reference(value[key])
            read(value[key])


def _request(request, fields, optional=()):
    evidence._request(request, ('attempt_id', *fields), optional)
    state._text(request['attempt_id'], 'Workstreams attempt', 128)
    return json_object(evidence._raw(request))


def _owned(scope, db, request, records, *, allow_settled=False):
    record = d6._assignment(scope, db, request, records=records)
    task = d6._assignment_task(scope, db, request)
    d6._require('workstream_revision' in record['body']['request'] and record['body']['pins'] == task['pins'],
        'Continuation requires the original Workstreams owner and pins')
    d6._require(allow_settled or record['data']['status'] != 'settled', 'Reconciled ownership cannot resume without reacquisition')
    d6._require(task['state'] not in {'BLOCKED', 'WAITING', 'PAUSED', 'CANCELLED'} and not any(
        c['kind'] in {'blocker', 'decision'} and c['status'] == 'pending' for c in task['conditions']),
        'Task blockers, pauses or pending decisions prevent Workstreams dispatch')
    records = [r for r in records if r['id'] != record['id']]
    d6._resources_available(scope, db, record['data']['claims'], records)
    plan = d6._task_plan(scope, task)
    d6._require(plan['limits']['deadline'] > d6._now(), 'Original delegation deadline has elapsed')
    job = next(job for job in plan['jobs'] if job['id'] == record['data']['job_id'])
    d6._worker_scope(scope, job['claims'], record['body']['request']['brief']['files'])
    current_claims = d6._claims(job['claims'])
    d6._resources_available(scope, db, current_claims, records)
    own = [r for r in records if all(r['owner'][key] == record['owner'][key]
        for key in ('scope_id', 'client', 'session_id', 'task_id'))]
    d6._require(not any(r['data']['job_id'] == job['id'] and
        r['data']['revision'] > record['data']['revision'] for r in own),
        'Superseded same-job child cannot resume; reconcile the current attempt')
    validate_dependencies(scope, task, plan, job, [record, *records])
    descendants = {job['id']}
    while True:
        expanded = descendants | {j['id'] for j in plan['jobs'] if set(j['dependencies']) & descendants}
        if expanded == descendants:
            break
        descendants = expanded
    d6._require(not any(r['data']['job_id'] in descendants and r['data']['status'] != 'settled' for r in own),
        'An admitted dependent still relies on the original accepted output')
    return record, task


def _candidate(scope, record, task):
    return evidence.capture_candidate(scope, d6._assignment_plan(scope, record, task))


def _save(scope, db, record, task, field, value):
    reference = evidence._artifact(scope, value)
    record['data'][field] = reference
    db.execute('update assignments set data=? where id=?', (evidence._raw(record['data']).decode(), record['id']))
    task['revision'] += 1
    state._save(db, state._scope_id(scope), task)
    return reference


def consume_dispatch(scope, request):
    """Commit one send decision before the external native call; never report actual delivery."""
    request = _request(request, ('workstream_revision',))
    with d6._reservation_write(scope) as db:
        _permission(scope, request['workstream_revision'])
        d6._require(db is not None, 'Missing native assignment state')
        records = d6._ledger(scope, db)
        record, task = _owned(scope, db, request, records)
        d6._require(record['body']['request']['workstream_revision'] == request['workstream_revision'] and
            record['data']['status'] == 'prepared' and record['data']['observation'] is None and
            'workstream_dispatch' not in record['data'], 'Prepared Workstreams dispatch is stale or already consumed')
        d6._require(evidence._digest(_candidate(scope, record, task)) == record['data']['candidate']['digest'],
            'Prepared Workstreams candidate changed')
        _save(scope, db, record, task, 'workstream_dispatch', dict(version=1, workstream_revision=request['workstream_revision'],
            assignment=record['data']['assignment'], owner=record['owner'], state='consumed', native_delivery='unobserved'))
        return d6._reply(record) | dict(send_admitted=True, native_delivery='unobserved', revision=task['revision'],
            limitations=list(LIMITATIONS))


def _ownership(records):
    return evidence._digest([dict(id=r['id'], owner=r['owner'], data={k: v for k, v in r['data'].items()
        if k != 'workstream_continuation'}) for r in sorted(records, key=lambda r: r['id'])])


def _intent(scope, record):
    reference = record['data'].get('workstream_continuation')
    if reference is None:
        return None
    value = evidence._read(scope, reference)
    state._fields(value, ('version', 'token', 'state', 'used', 'remaining_continuations', 'workstream_revision',
        'owner', 'assignment', 'pins', 'native_identity', 'observation', 'candidate', 'ownership_digest',
        'task_revision', 'reason', 'prompt', 'human_continue', 'retry_at', 'proof', 'previous',
        'delivery', 'delivery_ref', 'prior_reconciliation', 'prior_result', 'current_claims'))
    d6._require(value['version'] == 1 and value['owner'] == record['owner'] and
        value['assignment'] == record['data']['assignment'] and value['pins'] == record['body']['pins'] and
        value['state'] in {'prepared', 'consumed', 'recorded'} and re.fullmatch('[0-9a-f]{32}', value['token']),
        'Continuation intent binding is invalid')
    state._integer(value['used'], 'continuation allocation consumed', 1)
    maximum = record['body']['request']['workstream_limits']['max_continuations']
    d6._require(value['used'] <= maximum and value['remaining_continuations'] == maximum - value['used'],
        'Continuation allocation binding changed')
    return value


def _receipt(scope, record):
    history = d6._worker_history(scope, record['data']['observation'])
    current = history[0][1] if history else None
    d6._require(current is not None and current['status'] == 'observed' and not current['error'] and
        current['conflict'] is None and isinstance(current['receipt'], dict),
        'Continuation requires current unambiguous native history')
    receipt = current['receipt']
    d6._require(receipt['turn_status'] in {'completed', 'interrupted', 'failed'} and
        receipt.get('will_retry') is not True and receipt['worker_id'] and receipt['worker_turn_id'],
        'Native work or host retry remains active or uncertain')
    return receipt


def _recovery(receipt, reason, human):
    code = receipt.get('failure_code')
    if receipt['turn_status'] == 'failed':
        d6._require(code in TRANSIENT | LIMIT_FAILURES, 'Unknown failure requires reconciliation, not resend')
        d6._require(human or code not in LIMIT_FAILURES, 'Capacity limits require human continue; no automatic retry')
        d6._require(human or receipt.get('will_retry') is False,
            'Automatic continuation requires observed host retry completion')
        d6._require(reason == 'transient', 'Failed child requires a recognized recovery reason')
    elif receipt['turn_status'] == 'interrupted':
        d6._require(human, 'Interrupted child requires human continue')
    else:
        d6._require(reason != 'transient', 'Transient continuation requires an observed failure')


def prepare_continuation(scope, request):
    """Persist bounded same-child intent only after current independent stopped-writer proof."""
    request = _request(request, ('workstream_revision', 'reason', 'prompt', 'human_continue', 'host_proof'), ('retry_at',))
    d6._require(request['reason'] in {'follow-up', 'review-fixes', 'transient'} and type(request['human_continue']) is bool,
        'Invalid Workstreams continuation reason')
    state._text(request['prompt'], 'bounded continuation prompt', 32768)
    retry_at = request.get('retry_at', 0)
    state._integer(retry_at, 'continuation retry time')
    proof = evidence._read_host_proof(scope, request['host_proof'])
    with d6._reservation_write(scope) as db:
        _permission(scope, request['workstream_revision'])
        d6._require(db is not None, 'Missing native assignment state')
        records = d6._ledger(scope, db)
        record, task = _owned(scope, db, request, records, allow_settled=True)
        receipt = _receipt(scope, record)
        _recovery(receipt, request['reason'], request['human_continue'])
        previous = _intent(scope, record)
        candidate = _candidate(scope, record, task)
        ownership = _ownership(records)
        unsent = previous is not None and previous['state'] == 'prepared'
        if previous:
            changed = (previous['workstream_revision'] != request['workstream_revision'] or
                previous['task_revision'] != task['revision'] or previous['observation'] != record['data']['observation'] or
                previous['ownership_digest'] != ownership or previous['candidate']['digest'] != evidence._digest(candidate))
            progressed = previous['native_identity']['worker_turn_id'] != receipt['worker_turn_id']
            d6._require((unsent and changed) or
                (previous['state'] == 'recorded' and progressed) or
                (previous['state'] == 'consumed' and progressed and request['human_continue']),
                'Prior continuation delivery is unresolved; observe the original child before reassessing')
        limits = record['body']['request']['workstream_limits']
        used = (previous['used'] if previous else 0) + (0 if unsent else 1)
        d6._require(used <= limits['max_continuations'], 'Original continuation allocation is exhausted; human input required')
        d6._validate_operation_proof(scope, record, task, proof, current_candidate_digest=evidence._digest(candidate))
        native = proof['native_identity']
        if previous:
            d6._require(all(native[key] == previous['native_identity'][key] for key in
                ('client_surface', 'native_version', 'parent_session_id', 'parent_turn_id', 'spawn_item_id', 'task_name', 'worker_id')),
                'Same-child continuation identity changed')
        earliest = int(d6._now()) + (limits['backoff_seconds'] if request['reason'] == 'transient' else 0)
        value = dict(version=1, token=uuid.uuid4().hex, state='prepared', used=used,
            remaining_continuations=limits['max_continuations'] - used, workstream_revision=request['workstream_revision'],
            owner=record['owner'], assignment=record['data']['assignment'], pins=task['pins'], native_identity=native,
            observation=record['data']['observation'], candidate=evidence._artifact(scope, candidate), ownership_digest=ownership,
            task_revision=task['revision'] + 1, reason=request['reason'], prompt=request['prompt'],
            human_continue=request['human_continue'], retry_at=max(retry_at, earliest),
            proof=evidence._artifact(scope, proof),
            previous=record['data'].get('workstream_continuation'), delivery=None, delivery_ref=None,
            prior_reconciliation=record['data']['reconciliation'], prior_result=record['data']['result'],
            current_claims=d6._claims(next(j for j in d6._task_plan(scope, task)['jobs']
                if j['id'] == record['data']['job_id'])['claims']))
        _save(scope, db, record, task, 'workstream_continuation', value)
        return _continuation_reply(record, task, value)


def _continuation_reply(record, task, value, admitted=False):
    reply = dict(ok=True, attempt_id=record['id'], revision=task['revision'], token=value['token'],
        worker_id=value['native_identity']['worker_id'], task_name=record['data']['binding']['task_name'],
        state=value['state'], send_admitted=admitted, native_delivery='unobserved',
        remaining_continuations=value['remaining_continuations'], retry_at=value['retry_at'],
        delivery=value['delivery'], limitations=list(LIMITATIONS))
    if admitted:
        reply['prompt'] = value['prompt']
    return reply


def consume_continuation(scope, request):
    """Consume immediately before the native same-child send; loss requires reconciliation."""
    request = _request(request, ('workstream_revision', 'token'))
    with d6._reservation_write(scope) as db:
        _permission(scope, request['workstream_revision'])
        d6._require(db is not None, 'Missing native assignment state')
        records = d6._ledger(scope, db)
        record, task = _owned(scope, db, request, records, allow_settled=True)
        value = _intent(scope, record)
        d6._require(value is not None and value['token'] == request['token'] and value['state'] == 'prepared' and
            value['workstream_revision'] == request['workstream_revision'] and value['task_revision'] == task['revision'],
            'Continuation permission is stale or already consumed')
        d6._require(value['retry_at'] <= d6._now(), 'Continuation backoff has not elapsed')
        d6._require(value['observation'] == record['data']['observation'] and
            value['ownership_digest'] == _ownership(records) and
            value['candidate']['digest'] == evidence._digest(_candidate(scope, record, task)),
            'Continuation candidate, native observation or shared ownership changed')
        _receipt(scope, record)
        plan = d6._task_plan(scope, task)
        current_claims = d6._claims(next(j for j in plan['jobs'] if j['id'] == record['data']['job_id'])['claims'])
        d6._require(current_claims == value['current_claims'], 'Continuation physical resource aliases changed')
        if record['data']['status'] == 'settled':
            active = [r for r in records if r['data']['role'] in d6.NATIVE_ROLES and r['data']['status'] != 'settled']
            own = [r for r in active if all(r['owner'][k] == record['owner'][k]
                for k in ('scope_id', 'client', 'session_id', 'task_id'))]
            d6._require(len(own) < plan['limits']['max_parallel_workers'] and
                len(active) < min([plan['limits']['host_capacity']] + [r['data']['host_capacity'] for r in active]),
                'Managed worker capacity is exhausted during reacquisition')
            d6._invalidate_ready(db, scope, task, current_claims)
            if task['state'] == 'DONE':
                task['state'] = 'REVIEW'
            record['data'].update(status='observed', reconciliation=None, result=None)
        value = dict(value, state='consumed')
        _save(scope, db, record, task, 'workstream_continuation', value)
        return _continuation_reply(record, task, value, admitted=True)


def record_continuation(scope, request):
    """Retain delivery assertions even while disabled; never release or reassign ownership."""
    request = _request(request, ('token', 'delivery', 'delivery_ref'))
    d6._require(request['delivery'] in {'sent', 'uncertain'}, 'Invalid continuation delivery outcome')
    state._text(request['delivery_ref'], 'continuation delivery reference', 4096)
    with d6._reservation_write(scope) as db:
        record = d6._assignment(scope, db, request)
        task = d6._assignment_task(scope, db, request)
        value = _intent(scope, record)
        d6._require(value is not None and value['token'] == request['token'] and value['state'] == 'consumed',
            'Continuation delivery has no exact consumed permission')
        value = dict(value, state='recorded', delivery=request['delivery'], delivery_ref=request['delivery_ref'])
        _save(scope, db, record, task, 'workstream_continuation', value)
        return _continuation_reply(record, task, value)


def validate_dependencies(scope, task, plan, job, records):
    """A reopened prerequisite invalidates old direct and transitive acceptance."""
    own = [r for r in records if r['owner']['scope_id'] == state._scope_id(scope) and
        all(r['owner'][key] == task[key] for key in ('client', 'session_id', 'task_id'))]
    jobs = {j['id']: j for j in plan['jobs']}
    latest = {}
    for row in own:
        key=row['data']['job_id']
        if key not in latest or row['data']['revision']>latest[key]['data']['revision']:
            latest[key]=row
    checked={}
    pending=[(identity,False) for identity in job['dependencies']]
    while pending:
        identity,expanded=pending.pop()
        if identity in checked:
            continue
        if not expanded:
            pending.append((identity,True))
            pending.extend((parent,False) for parent in jobs[identity]['dependencies'] if parent not in checked)
            continue
        row=latest.get(identity)
        d6._require(row is not None and row['data']['status']=='settled' and
            row['data']['result']['outcome']=='completed','Workstream prerequisite acceptance is unresolved')
        revision=evidence._read(scope,row['data']['reconciliation']).get('revision')
        state._integer(revision,'prerequisite reconciliation revision',1)
        d6._require(all(revision>checked[parent] for parent in jobs[identity]['dependencies']),
            'Prior dependent acceptance predates reopened prerequisite work')
        checked[identity]=revision


def validate_settlement(scope, record, outcome):
    if outcome == 'completed' and 'workstream_continuation' in record['data']:
        intent = _intent(scope, record)
        if intent['state'] in {'consumed', 'recorded'}:
            receipt = _receipt(scope, record)
            d6._require(receipt['worker_turn_id'] != intent['native_identity']['worker_turn_id'],
                'Completed continuation requires a newly observed native result')
