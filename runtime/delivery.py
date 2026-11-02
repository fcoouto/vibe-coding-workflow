"""Task-owned delivery decisions; recorded references never grant external authority."""
from copy import deepcopy
import re

from runtime import state


def _require(condition, message):
    if not condition:
        raise state.StateError(message)


def _ref(value):
    state._text(value, 'delivery decision reference', 1024)


def _branch(value):
    state._text(value, 'delivery ref', 256)
    _require(not value.startswith(('-', '/', '.')) and not value.endswith(('/', '.', '.lock'))
             and not any(c.isspace() or c in '~^:?*[\\' for c in value)
             and not any(p in value for p in ('..', '//', '@{'))
             and all(p and not p.startswith('.') and not p.endswith('.lock') for p in value.split('/')),
             'Invalid delivery branch')


def validate_policy(value: dict) -> dict:
    state._fields(value, ('version', 'merge', 'separate_worktrees', 'targets', 'decision_ref'))
    _require(type(value['version']) is int and value['version'] == 1, 'Unsupported delivery policy')
    _require(value['merge'] in ('manual', 'agent') and type(value['separate_worktrees']) is bool,
             'Invalid delivery defaults')
    _ref(value['decision_ref'])
    _require(isinstance(value['targets'], list) and len(value['targets']) <= 64, 'Invalid delivery targets')
    seen = set()
    for target in value['targets']:
        state._fields(target, ('provider', 'host', 'repository', 'target', 'merge_method',
                              'publication_ref', 'merge_ref', 'remote_cleanup_ref'))
        _require(target['provider'] == 'github', 'Unsupported delivery provider')
        _require(isinstance(target['host'], str) and re.fullmatch(r'[a-z0-9]+(?:[.-][a-z0-9]+)*', target['host']),
                 'Invalid delivery host')
        _require(isinstance(target['repository'], str)
                 and re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+', target['repository'])
                 and target['repository'].split('/')[1] not in ('.', '..'), 'Invalid delivery repository')
        _branch(target['target'])
        _require(target['merge_method'] in ('merge', 'squash', 'rebase', 'queue'), 'Invalid delivery merge method')
        for key in ('publication_ref', 'merge_ref', 'remote_cleanup_ref'):
            if target[key] is not None:
                _ref(target[key])
        identity = tuple(target[k] for k in ('provider', 'host', 'repository', 'target'))
        _require(identity not in seen, 'Duplicate delivery target')
        seen.add(identity)
    return deepcopy(value)


def effective_policy(saved: dict, override: dict | None) -> dict:
    result = validate_policy(saved)
    if override is not None:
        state._fields(override, ('merge', 'decision_ref'))
        _require(override['merge'] in ('manual', 'agent'), 'Invalid task merge override')
        _ref(override['decision_ref'])
        result.update(override)
    return result


def validate_record(value):
    state._fields(value, ('plan', 'operations'))
    state._artifact_reference(value['plan'])
    _require(isinstance(value['operations'], list) and len(value['operations']) <= 64,
             'Invalid delivery operation history')
    for reference in value['operations']:
        state._artifact_reference(reference)


def _plan(value, saved, override=None):
    from runtime import evidence
    evidence._bounded(value)
    state._fields(value, ('version', 'decision_ref', 'policy', 'workspace', 'publications', 'companions'))
    _require(type(value['version']) is int and value['version'] == 1, 'Unsupported delivery plan')
    _ref(value['decision_ref'])
    _require(validate_policy(value['policy']) == effective_policy(saved, override),
             'Plan differs from adopted delivery policy')
    _require(value['workspace'] is None, 'Workspace binding needs independently observed native ownership')
    publications, companions = value['publications'], value['companions']
    _require(isinstance(publications, list) and len(publications) <= 64
             and isinstance(companions, list) and len(companions) <= 64, 'Invalid delivery scope')
    ids = set()
    for publication in publications:
        state._fields(publication, ('id', 'provider', 'host', 'repository', 'target', 'branch',
                                   'candidate', 'pull_request', 'dependencies', 'required'))
        state._text(publication['id'], 'publication id', 128)
        _require(publication['id'] not in ids, 'Duplicate publication')
        ids.add(publication['id'])
        _branch(publication['branch'])
        _require(type(publication['required']) is bool, 'Invalid delivery requirement')
        _require(publication['pull_request'] is None and publication['candidate'] is None,
                 'Publication binding requires observed candidate and PR ownership')
        _require(any(all(publication[k] == t[k] for k in ('provider', 'host', 'repository', 'target'))
                     for t in value['policy']['targets']), 'Unadopted publication target')
        _require(isinstance(publication['dependencies'], list) and len(publication['dependencies']) <= 64
                 and all(isinstance(i, str) for i in publication['dependencies'])
                 and len(set(publication['dependencies'])) == len(publication['dependencies']),
                 'Invalid publication dependencies')
    remaining = {p['id']: set(p['dependencies']) for p in publications}
    _require(all(deps <= ids for deps in remaining.values()), 'Unknown publication dependency')
    while remaining:
        ready = {key for key, deps in remaining.items() if not deps & remaining.keys()}
        _require(ready, 'Cyclic publication dependency')
        remaining = {key: deps for key, deps in remaining.items() if key not in ready}
    for companion in companions:
        state._task_reference(companion)
    _require(len({evidence._raw(c) for c in companions}) == len(companions), 'Duplicate delivery companion')
    return deepcopy(value)


def _read_plan(scope, task, *, db=None):
    from runtime import evidence
    return evidence._read(scope, task['delivery']['plan'], db=db)


def completion_requirements(scope, db, task: dict) -> dict:
    """Local retained facts only; a title or caller's remote claim is never proof."""
    adopted = 'delivery_policy' in task.get('accepted_identity', {})
    if 'delivery' not in task:
        required = adopted and task['mode'] == 'editable'
        return dict(delivery_required=required, delivery_complete=not required,
                    pending=[], blockers=['Delivery scope decision is missing'] if required else [])
    plan = _read_plan(scope, task, db=db)
    required = [p['id'] for p in plan['publications'] if p['required']]
    pending = required + ['companion:' + c['task_id'] for c in plan['companions']]
    return dict(delivery_required=bool(pending), delivery_complete=not pending,
                pending=pending, blockers=[])


def operate(scope, action: str, request: dict, *, owner=None) -> dict:
    from runtime import evidence
    evidence._bounded(request)
    if action == 'status':
        state._fields(request, ('client', 'session_id'))
        with state._database(scope) as db:
            task = state._task(db, state._scope_id(scope), request['client'], request['session_id'])
            _require(task is not None, 'Delivery task is not bound')
            state._compatible(scope, task)
            return dict(task=task, plan=_read_plan(scope, task, db=db) if 'delivery' in task else None,
                        **completion_requirements(scope, db, task))
    _require(action == 'plan', 'Unsupported delivery operation')
    evidence._request(request, ('plan',), ('override',))
    with state._database(scope, write=True) as db:
        task = evidence._task(db, scope, request)
        saved = task.get('accepted_identity', {}).get('delivery_policy')
        _require(saved is not None, 'Delivery policy has not been adopted')
        _require('delivery' not in task, 'Delivery plan already exists; reconcile the existing scope')
        plan = _plan(request['plan'], saved, request.get('override'))
        reference = evidence._artifact(scope, plan, owner=evidence._artifact_owner(scope, task), db=db)
        task['delivery'] = dict(plan=reference, operations=[])
        task['revision'] += 1
        state._save(db, state._scope_id(scope), task)
        return dict(task=task, plan=plan, **completion_requirements(scope, db, task))
