"""Bounded D5 evidence: private immutable artifacts, actual inputs and native receipts.

Coordinator decisions describe semantic coverage and existing authorization. They do
not authenticate review execution or grant permission for a command's effects.
"""
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
import subprocess
import sys
import time
import uuid

from runtime import state
from runtime.startup import MAX_INPUT, StartupError, json_object, policy_digest

VERSION = 1
MAX_ATTEMPTS = 32
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
    _require(isinstance(value, list) and len(value) <= 64 and all(isinstance(v, str) for v in value)
             and len(value) == len(set(value)), 'Invalid ' + field)
    for v in value:
        state._text(v, field, 4096)
    _require(choices is None or set(value) <= set(choices), 'Unsupported ' + field)
    return value


def _request(request, required=(), optional=()):
    _bounded(request)
    state._fields(request, (*IDENTITY, *required), optional)
    state._identity(request)
    state._integer(request['expected_revision'], 'expected_revision', 1)


def _task(db, scope, request, revision=True):
    _require(db is not None, 'Task state has not been initialized')
    task = state._task(db, state._scope_id(scope), request['client'], request['session_id'])
    _require(task is not None and all(task[k] == request[k] for k in IDENTITY[:4]), 'Evidence task binding changed')
    state._compatible(scope, task)
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


def _artifact(scope, value):
    raw = _raw(value)
    _require(len(raw) <= MAX_ARTIFACT, 'Evidence artifact size limit exceeded')
    path = _folder(scope, create=True) / (uuid.uuid4().hex + '.json')
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return dict(name=path.name, digest=hashlib.sha256(raw).hexdigest())


def _read(scope, reference):
    state._fields(reference, ('name', 'digest'))
    _require(isinstance(reference['name'], str) and re.fullmatch(r'[0-9a-f]{32}\.json', reference['name']),
             'Invalid evidence artifact reference')
    path = _folder(scope) / reference['name']
    try:
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


def validate_evidence(value):
    _bounded(value)
    state._fields(value, ('version', 'plan', 'candidate', 'attempts'), ('verification', 'history'))
    _require(type(value['version']) is int and value['version'] == VERSION and isinstance(value['attempts'], list)
             and len(value['attempts']) <= MAX_ATTEMPTS, 'Unsupported or oversized task evidence')
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


def _plan(value):
    _bounded(value)
    state._fields(value, ('version', 'decision_ref', 'criteria', 'checks', 'reviews', 'security_impact', 'base',
                         'comparison', 'nontrivial', 'instructions', 'exclusions', 'review_limit'), ('relevant_untracked',))
    _require(type(value['version']) is int and value['version'] == VERSION, 'Unsupported evidence plan version')
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
    _require(isinstance(value['checks'], list) and len(value['checks']) <= 32, 'Invalid accepted checks')
    ids = set()
    for check in value['checks']:
        state._fields(check, ('id', 'argv', 'cwd', 'timeout', 'env', 'effects', 'baseline', 'dependencies'), ('thresholds',))
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


def _capture(scope, plan):
    from runtime.onboarding import _snapshot, _fingerprint
    snapshot = _snapshot(scope.repository_root)
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
                    pins=state._pins(scope), actual_policy_digest=policy_digest(state.PACKAGE),
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
    with state._database(scope) as db:
        task = _task(db, scope, request)
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
    evidence = dict(version=VERSION, plan=_artifact(scope, plan), candidate=_artifact(scope, candidate),
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
    plan = _load_plan(scope, request)
    candidate = capture_candidate(scope, plan)
    attempt = dict(id=uuid.uuid4().hex, kind=kind, status='reserved', candidate=_artifact(scope, candidate),
                   candidate_digest=_digest(candidate), plan_digest=_digest(plan), **detail)
    if kind == 'review':
        attempt['task_name'] = 'review_' + attempt['id']
    with state._database(scope, write=True) as db:
        task = _task(db, scope, request)
        _require('evidence' in task and len(task['evidence']['attempts']) < MAX_ATTEMPTS, 'Evidence attempt bound reached')
        if kind == 'review':
            _require(sum(a['kind'] == 'review' for a in task['evidence']['attempts']) < plan['review_limit'],
                     'Review round limit reached; preserve limits and seek a scoped decision')
        task['evidence']['attempts'].append(attempt)
        task['revision'] += 1
        if task['state'] == 'ready':
            task['state'] = 'verifying'
        state._save(db, state._scope_id(scope), task)
    return plan, candidate, attempt, task['revision']


def _finish(scope, request, attempt, expected_revision):
    with state._database(scope, write=True) as db:
        task = _task(db, scope, dict(request, expected_revision=expected_revision))
        attempts = task['evidence']['attempts']
        index = next((n for n, a in enumerate(attempts) if a['id'] == attempt['id']), None)
        _require(index is not None, 'Evidence attempt binding changed')
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


def run_check(scope, request):
    _request(request, ('check_id',))
    plan = _load_plan(scope, request)
    check = next((c for c in plan['checks'] if c['id'] == request['check_id']), None)
    _require(check is not None, 'Check id is not an accepted canonical command')
    plan, candidate, attempt, revision = _reserve(scope, request, 'check', dict(check_id=check['id']))
    attempt['status'] = 'running'
    result = _finish(scope, request, attempt, revision)
    revision = result['task']['revision']
    # A crash or revision conflict leaves the durable running reservation blocking readiness.
    attempt.update(_execute(scope, check, candidate['tools'][check['id']]))
    after = capture_candidate(scope, plan)
    attempt['inputs_changed'] = candidate != after
    if candidate != after and attempt['status'] != 'uncertain':
        attempt['status'] = 'changed-inputs'
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
    output_ref = _artifact(scope, attempt.pop('private_output'))
    attempt['execution'] = _artifact(scope, dict(command=check, tool=candidate['tools'][check['id']],
                                               output=output_ref, result=attempt.copy()))
    return _finish(scope, request, attempt, revision)


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
        runtime_settings({'runtime': {'schema_version': 1, 'state_dir': str(path.parent)}}, state.PACKAGE, scope.git_common_dir)
        _no_links(path)
        raw = _read_file(path, MAX_INPUT, private=True)
        _require(hashlib.sha256(raw).hexdigest() == reference['sha256'], 'Host proof integrity failed')
        return json_object(raw)
    except (OSError, ValueError, TypeError):
        raise state.StateError('Trusted host lifecycle proof is unavailable, unsafe or corrupt') from None


def reconcile_check(scope, request):
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
    attempt.update(status=status, reconciliation=_artifact(scope, dict(proof=proof, source_digest=request['host_proof']['sha256'])))
    return _finish(scope, request, attempt, request['expected_revision'])


def prepare_review(scope, request):
    _request(request, ('coverage', 'criteria', 'assignment'))
    _strings(request['coverage'], 'review coverage', COVERAGE)
    _require(request['coverage'], 'Review coverage is empty')
    plan = _load_plan(scope, request)
    _strings(request['criteria'], 'covered criteria', {c['id'] for c in plan['criteria']})
    assignment = request['assignment']
    _require(isinstance(assignment, str) and 0 < len(assignment) <= 65536 and '\x00' not in assignment,
             'Invalid review assignment')
    _, _, attempt, revision = _reserve(scope, request, 'review', dict(coverage=request['coverage'], criteria=request['criteria'],
        assignment=_artifact(scope, dict(prompt=assignment)), assignment_digest=hashlib.sha256(assignment.encode()).hexdigest()))
    return dict(ok=True, attempt_id=attempt['id'], assignment_digest=attempt['assignment_digest'],
                candidate_digest=attempt['candidate_digest'], task_name=attempt['task_name'], revision=revision)


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


def collect_review(scope, request):
    _request(request, ('attempt_id', 'parent_turn_id', 'spawn_item_id'))
    for key in ('attempt_id', 'parent_turn_id', 'spawn_item_id'):
        state._text(request[key], key)
    with state._database(scope) as db:
        task = _task(db, scope, request)
        attempt = deepcopy(next((a for a in task.get('evidence', {}).get('attempts', []) if a['id'] == request['attempt_id']), None))
    _require(attempt is not None and attempt['kind'] == 'review' and attempt['status'] == 'reserved', 'Native review attempt is not pending')
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
    report = _report(observed['report'], attempt)
    _require(_digest(capture_candidate(scope, _load_plan(scope, request))) == attempt['candidate_digest'], 'Review candidate changed during collection')
    attempt.update(status='collected', collected=_artifact(scope, dict(receipt=receipt, report=report)))
    return _finish(scope, request, attempt, request['expected_revision'])


def assess_review(scope, request):
    _request(request, ('attempt_id', 'assessment'))
    with state._database(scope) as db:
        task = _task(db, scope, request)
        attempt = deepcopy(next((a for a in task.get('evidence', {}).get('attempts', []) if a['id'] == request['attempt_id']), None))
    _require(attempt is not None and attempt['status'] in {'collected', 'assessed'}, 'Assessment requires collected native evidence')
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
    attempt.update(status='assessed', assessment=_artifact(scope, dict(collected_digest=attempt['collected']['digest'], assessment=assessment)))
    return _finish(scope, request, attempt, request['expected_revision'])


def _current_attempt(scope, attempt, candidate, plan, reuse):
    if attempt['plan_digest'] != _digest(plan):
        return False
    previous = _read(scope, attempt['candidate'])
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


def _checkout_attempt_blockers(db, scope, task):
    """Use the caller's transaction so another session cannot reserve between scan and commit."""
    blockers = []
    rows = db.execute('select t.scope_id,t.client,t.session_id,t.task_id from tasks t join checkouts c on t.scope_id=c.scope_id '
                      'where c.repository_root=? and c.git_common_dir=?',
                      (str(scope.repository_root), str(scope.git_common_dir))).fetchall()
    for scope_id, client, session, task_id in rows:
        record = state._task(db, scope_id, client, session, task_id)
        if record.get('retirement'):
            _read(scope, record['retirement']['proof'])
        elif any(a['status'] in {'reserved', 'running', 'uncertain'} for a in record.get('evidence', {}).get('attempts', [])):
            own = (scope_id, client, session, task_id) == (state._scope_id(scope), task['client'], task['session_id'], task['task_id'])
            blockers.append('Evidence attempt or surviving writer remains unresolved' if own else
                            'Unreconciled evidence attempt remains in checkout history')
    return blockers


def _blockers(scope, task, plan, candidate, purpose, reuse, security_impact=None):
    blockers = []
    evidence = task['evidence']
    if task['state'] == 'cancelled':
        blockers.append('Task is cancelled')
    if any(c['status'] == 'pending' and c['kind'] in {'blocker', 'decision'} for c in task['conditions']):
        blockers.append('Task conditions remain unresolved')
    with state._database(scope) as db:
        blockers.extend(_checkout_attempt_blockers(db, scope, task))
    if task['turn_uncertain'] and task['turn_id'] is not None:
        blockers.append('Native turn interruption/correlation remains unresolved')
    if ((security_impact or plan['security_impact'])['status'] != 'assessed' or
            security_impact is None and _read(scope, evidence['candidate']) != candidate):
        blockers.append('Post-implementation security impact assessment is unresolved or stale')
    if any(a['status'] in {'reserved', 'running', 'uncertain'} for a in evidence['attempts']):
        blockers.append('Evidence attempt or surviving writer remains unresolved')
    current = [a for a in evidence['attempts'] if _current_attempt(scope, a, candidate, plan, reuse)]
    for attempt in current:
        if attempt['kind'] == 'check' and attempt['status'] == 'passed':
            _require('execution' in attempt, 'Passing check lacks observed execution artifact')
            execution = _read(scope, attempt['execution'])
            _read(scope, execution['output'])
            _require('reconciliation' in attempt, 'Passing check lacks independently inspected host lifecycle evidence')
            reconciliation = _read(scope, attempt['reconciliation'])['proof']
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
        collected = _read(scope, attempt['collected'])
        assessed = _read(scope, attempt['assessment'])
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
        report = _read(scope, attempt['collected'])['report']
        dispositions = {}
        if 'assessment' in attempt:
            assessment = _read(scope, attempt['assessment'])['assessment']
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


def verify_completion(scope, request):
    _request(request, ('purpose',), ('reuse', 'security_impact'))
    _require(request['purpose'] in {'completion', 'merge-evidence'}, 'Invalid evidence verification purpose')
    reuse = _reuse(request.get('reuse', []))
    security_impact = request.get('security_impact')
    if security_impact is not None:
        state._fields(security_impact, ('status', 'reason', 'reference'))
        _require(security_impact['status'] in {'assessed', 'unresolved'}, 'Invalid current security impact assessment')
        for key in ('reason', 'reference'):
            state._text(security_impact[key], 'current security impact ' + key)
    with state._database(scope) as db:
        task = deepcopy(_task(db, scope, request))
        _require('evidence' in task, 'Evidence plan is missing')
        plan = _read(scope, task['evidence']['plan'])
        generation = db.execute('select generation from checkouts where scope_id=?', (state._scope_id(scope),)).fetchone()[0]
    candidate = capture_candidate(scope, plan)
    blockers = _blockers(scope, task, plan, candidate, request['purpose'], reuse, security_impact)
    verification = dict(version=VERSION, candidate_digest=_digest(candidate), plan_digest=_digest(plan),
                        purpose=request['purpose'], generation=generation, blockers=blockers, reuse=reuse, security_impact=security_impact)
    verification_ref = _artifact(scope, verification)
    with state._database(scope, write=True) as db:
        current = _task(db, scope, request)
        actual_generation = db.execute('select generation from checkouts where scope_id=?', (state._scope_id(scope),)).fetchone()[0]
        _require(actual_generation == generation, 'Verification generation changed; recapture before completion')
        final_blockers = sorted(set(blockers + _checkout_attempt_blockers(db, scope, current)))
        if final_blockers != blockers:
            blockers = final_blockers
            verification['blockers'] = blockers
            verification_ref = _artifact(scope, verification)
        current['evidence']['verification'] = verification_ref
        if not blockers and request['purpose'] == 'completion':
            current['state'] = 'ready'
            for condition in current['conditions']:
                if 'continuation' in condition:
                    condition['continuation']['revoked'] = True
        elif current['state'] == 'ready':
            current['state'] = 'verifying'
        current['revision'] += 1
        state._save(db, state._scope_id(scope), current)
    return dict(ok=True, verified=not blockers, task=current, blockers=blockers, candidate_digest=_digest(candidate),
                merge_authority=False, limitations=['Local point-in-time evidence; no repository merge gate or filesystem security boundary'])


def revalidate_ready(scope, client, session_id):
    """Status is an actual freshness check; hook generation alone cannot prove change."""
    with state._database(scope) as db:
        task = state._task(db, state._scope_id(scope), client, session_id) if db else None
        if task is None or task['state'] != 'ready':
            return
        state._compatible(scope, task)
        request = {key: task[key] for key in IDENTITY[:4]} | dict(expected_revision=task['revision'])
        evidence = task.get('evidence')
        valid = False
        verification = _read(scope, evidence['verification']) if evidence and 'verification' in evidence else None
        plan = _read(scope, evidence['plan']) if evidence else None
    try:
        candidate = capture_candidate(scope, plan) if plan else None
        valid = bool(verification and verification['purpose'] == 'completion' and not verification['blockers'] and
                     verification['candidate_digest'] == _digest(candidate) and not
                     _blockers(scope, task, plan, candidate, 'completion', verification.get('reuse', []), verification.get('security_impact')))
    except (StartupError, OSError):
        valid = False
    if not valid:
        with state._database(scope, write=True) as db:
            current = _task(db, scope, request)
            current.update(state='verifying', reason='Completion evidence requires freshness verification', reference='evidence:status')
            current['revision'] += 1
            state._save(db, state._scope_id(scope), current)


def evidence_status(scope, client, session_id):
    result = state.task_status(scope, client, session_id)
    result['scope_id'] = state._scope_id(scope)
    task = result['task']
    if task and 'evidence' in task:
        plan = _read(scope, task['evidence']['plan'])
        try:
            candidate = capture_candidate(scope, plan)
            verification = _read(scope, task['evidence']['verification']) if 'verification' in task['evidence'] else {}
            current = verification.get('candidate_digest') == _digest(candidate)
            result['evidence'] = dict(candidate_digest=_digest(candidate), blockers=_blockers(scope, task, plan, candidate, 'completion',
                verification.get('reuse', []) if current else [], verification.get('security_impact') if current else None))
        except StartupError:
            result['evidence'] = dict(blockers=['Candidate capture is incomplete, unstable or unavailable'])
    else:
        result['evidence'] = dict(blockers=['Evidence plan is missing'])
    return result
