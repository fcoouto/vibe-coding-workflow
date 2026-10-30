"""Bounded v3 Council recovery. The existing Council lock owns every transition.

Research and inference remain native coordinator operations outside this module.
Source records are hypotheses; only normal host verification accepts a report.
"""
import copy
from contextlib import contextmanager
import math
from pathlib import Path
import time
from urllib.parse import urlsplit
import uuid

from runtime import council as c

HISTORY_LIMIT = 256
HISTORY_TTL = 86400
BLOCKING = {'authentication', 'budget', 'permission', 'integration'}


def initialize(value):
    value['recovery'] = {}
    value['archived_attempts'] = []
    value['supervisors'] = []
    value['critique_generation'] = 1
    value['generations'] = []
    value['retained_frozen'] = {}
    value['role_bindings'] = {'investigate': {}, 'critique': {}, 'synthesis': {}}
    for member, seat in value['roster'].items():
        value['recovery'][member] = dict(serial=1, candidates=[_candidate(seat)], catch_up=False)


def _candidate(seat):
    return dict(candidate_id=str(uuid.uuid4()), seat=copy.deepcopy(seat), investigation=None, tried=[])


def current(value, member):
    return value['recovery'][member]['candidates'][-1]


def catch_up(value, phase, member):
    return value.get('version') == 3 and phase == 'critique' and value['recovery'][member]['catch_up']


def effective_seat(value, phase, member):
    seat = dict(c._seat(value, member, phase))
    correction = value['recovery'][member].get('active_correction', {})
    if correction.get('kind') == 'output_steps':
        seat.update(output_tokens=correction['output_tokens'], steps=correction['steps'])
    return seat


def objective(value, phase, member, original):
    if catch_up(value, phase, member): original = c._objective(value, 'investigate')
    if value['recovery'][member].get('active_correction', {}).get('kind') == 'workspace_guidance':
        original += '\nUse the copied workspace as root; only supplied relative paths are evidence. Return the required phase findings with citations and uncertainty.'
    return original


def attempt_identity(value, phase, member):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, value['run'] + ':' + phase + ':' + member + ':' + str(value['recovery'][member]['serial'])))


def bind_attempt(value, phase, member):
    item = value['members'][c._key(phase, member)]
    item.update(attempt_id=attempt_identity(value, phase, member), candidate_id=current(value, member)['candidate_id'],
                phase=phase, member=member, seat=copy.deepcopy(c._seat(value, member, phase)),
                generation=value['critique_generation'], catch_up=catch_up(value, phase, member))
    correction = value['recovery'][member].get('active_correction')
    if correction: item['correction'] = copy.deepcopy(correction)
    binding = dict(candidate_id=item['candidate_id'], model=item['seat']['model'],
                   canonical_model=_canonical(item['seat']))
    if phase == 'synthesis': value['role_bindings']['synthesis'] = binding
    elif not item['catch_up']: value['role_bindings'][phase][member] = binding


def owners(value):
    found = {}
    for item in value['archived_attempts'] + list(value['members'].values()):
        if 'attempt_id' in item: found[item['attempt_id']] = item
    return list(found.values())


def observe(value, owner):
    if owner.get('preparation_failure'): return owner['preparation_failure']
    if owner['kind'] == 'native':
        return owner.get('receipt', dict(state='issued', local_execution_stopped=False))
    try:
        raw = c._read(Path(owner['worker_run']) / 'result.json', c.workers.LIMIT + c.REPORT_LIMIT)
        result = c.onboarding.read_request(raw, c.workers.LIMIT + c.REPORT_LIMIT)
    except FileNotFoundError:
        return dict(state='unresolved', local_execution_stopped=False)
    if result.get('state') == 'accepted':
        verified = owner.get('verification', {})
        if (verified.get('sha256') != c._digest(raw) or not c._text(result.get('session_id'))
                or result['session_id'] != verified.get('session_id')):
            return dict(result, state='awaiting_verification')
        if (Path(owner['worker_run']) / 'result.json').stat().st_mtime > value['started_wall'] + c._end(value, owner['phase']):
            return dict(result, state='late')
    return result


def prior_stopped(value, phase):
    return (all(observe(value, owner).get('local_execution_stopped') is True for owner in owners(value)
                if c.PHASES.index(owner['phase']) <= c.PHASES.index(phase))
            and all(owner['local_execution_stopped'] for owner in value['supervisors']
                    if c.PHASES.index(owner['phase']) <= c.PHASES.index(phase)))


def phase_guard(value, phase):
    pending = any(state['catch_up'] for state in value['recovery'].values())
    if phase == 'synthesis' and pending:
        c._require(c._elapsed(value) >= c._end(value, 'critique'), 'critique_generation_pending')
        c._require(prior_stopped(value, 'critique'), 'phase_not_ready')
        for member, state in value['recovery'].items():
            if not state['catch_up']: continue
            owner = value['members'].get(c._key('critique', member))
            if owner: owner['excluded_from_round'] = True
            state['catch_up'] = False
    if phase == 'critique' and value['phase'] == 'critique' and pending:
        # Other catch-ups can proceed, but their accepted reports cannot count yet.
        return


def launch_guard(value, phase, member):
    item = value['members'].get(c._key(phase, member), {})
    c._require(item.get('candidate_id') == current(value, member)['candidate_id'], 'candidate_changed')
    c._require(time.monotonic() >= value['recovery'][member].get('not_before_monotonic', 0), 'retry_delay_pending')
    c._require(not (phase == 'critique' and any(s['catch_up'] for s in value['recovery'].values())
                   and not catch_up(value, phase, member)), 'critique_generation_pending')


@contextmanager
def _admitted(run):
    with c._locked(run) as before:
        root, source, stamp = Path(before['root']), before['source_root'], before['management']
    with c.settings.admission(source, 'council', root=root, **stamp):
        with c._locked(run) as value:
            c._require(value['management'] == stamp, 'council_worker_identity_changed')
            yield value


def _guard(run, value, phase, member):
    c._require(value.get('version') == 3, 'recovery_manifest_required')
    c._identity(value, phase, member)
    c._remaining(value, phase)
    c._require(value['phase'] == phase, 'phase_already_closed')
    c._check_frozen(run, value)
    item = value['members'].get(c._key(phase, member))
    c._require(item is not None, 'failed_attempt_required')
    observed = observe(value, item)
    c._require(observed.get('local_execution_stopped') is True, 'prior_owner_not_stopped')
    c._require(observed.get('state') in ('failed', 'rejected', 'unresolved', 'late', 'not_launched'), 'failed_attempt_required')
    failure = c.workers.safe_failure(observed.get('failure')) or {'category': 'substantive_rejection'}
    c._require(failure['category'] not in BLOCKING, 'shared_harness_or_authorization_blocker')
    learn(value, phase, member, 'failed')
    return item, failure


def _canonical(seat):
    return seat.get('canonical_model', seat['model'])


def _signature(candidate, failure):
    seat = candidate['seat']
    return c._digest(c._json(dict(model=seat['model'], provider=seat.get('provider'), effort=seat['effort'],
        qualification=seat.get('permission_qualification'), input_tokens=seat['input_tokens'],
        output_tokens=seat['output_tokens'], steps=seat['steps'], failure=failure)))


def _history(value, new=None):
    directory = Path(value['root']).parent
    with c.onboarding._locked(directory):
        try: records = c.onboarding.read_request(c._read(directory / 'council-recovery-history.json'), c.MANIFEST_LIMIT)['records']
        except FileNotFoundError: records = []
        c._require(isinstance(records, list) and len(records) <= HISTORY_LIMIT, 'invalid_recovery_history')
        if new is not None:
            records = [row for row in records if row.get('attempt_id') != new['attempt_id']] + [new]
            c.changes._atomic(directory, 'council-recovery-history.json', c._json(dict(records=records[-HISTORY_LIMIT:])))
        return records


def investigate_failure(run, phase, member):
    with _admitted(run) as value:
        item, failure = _guard(run, value, phase, member)
        candidate = current(value, member)
        c._require(candidate['investigation'] is None, 'investigation_already_used')
        now = time.monotonic()
        episode = dict(candidate_id=candidate['candidate_id'], failure_id=item['attempt_id'],
            failure=failure, signature=_signature(candidate, failure), started_monotonic=now,
            deadline_monotonic=min(now + 120, value['started_monotonic'] + c._end(value, phase),
                                   value['started_monotonic'] + value['timeout_seconds']), state='investigating')
        candidate['investigation'] = episode
        matches = [row for row in _history(value) if row.get('signature') == episode['signature']
                   and 0 <= time.time() - row.get('checked_at', 0) <= HISTORY_TTL]
        c._save(run, value)
        return dict(episode, searches_remaining=3, reads_remaining=5, history=matches)


def _source(source):
    c._require(isinstance(source, dict) and set(source) == {'url', 'checked_at', 'authority', 'applicability'}, 'invalid_recovery_source')
    parsed = urlsplit(source['url']) if c._text(source.get('url'), 2048) else None
    c._require(parsed is not None and parsed.scheme == 'https' and parsed.hostname and not parsed.username
               and not parsed.password and not parsed.query and not parsed.fragment, 'invalid_recovery_source')
    checked = source['checked_at']
    c._require(type(checked) in (float, int) and math.isfinite(checked) and 0 <= time.time() - checked <= HISTORY_TTL
               and source['authority'] in ('official', 'community') and c._text(source['applicability'], 1000), 'stale_recovery_source')


def _correction(correction, seat, sources):
    c._require(isinstance(correction, dict), 'unsupported_correction')
    kind = correction.get('kind')
    fields = {'kind', 'source'}
    if kind == 'output_steps': fields |= {'output_tokens', 'steps'}
    elif kind == 'fresh_connection': fields.add('retry_delay_seconds')
    elif kind == 'request_representation': fields.add('representation')
    else: c._require(kind == 'workspace_guidance', 'unsupported_correction')
    c._require(set(correction) == fields and type(correction.get('source')) is int
               and 0 <= correction['source'] < len(sources), 'unsupported_correction')
    if kind == 'request_representation':
        c._require(seat['kind'] == 'external' and correction['representation'] == 'output_limit_only', 'unsupported_correction')
    if kind == 'output_steps':
        c._require(all(type(correction[k]) is int and 1 <= correction[k] <= seat[k] for k in ('output_tokens', 'steps')), 'correction_exceeds_envelope')
        c._require(any(correction[k] != seat[k] for k in ('output_tokens', 'steps')), 'unchanged_correction')
    if kind == 'fresh_connection':
        delay = correction['retry_delay_seconds']
        c._require(type(delay) in (int, float) and math.isfinite(delay) and 0 <= delay <= 120, 'invalid_retry_delay')
    return {key: val for key, val in correction.items() if key != 'source'}


def record_investigation(run, phase, member, evidence):
    with _admitted(run) as value:
        _guard(run, value, phase, member)
        candidate = current(value, member)
        episode = candidate['investigation']
        c._require(episode is not None and episode['state'] == 'investigating', 'investigation_already_used')
        c._require(time.monotonic() <= episode['deadline_monotonic'], 'investigation_deadline_exhausted')
        fields = {'candidate_id', 'failure_id', 'searches', 'reads', 'sources', 'corrections'}
        c._require(isinstance(evidence, dict) and set(evidence) == fields
                   and evidence['candidate_id'] == candidate['candidate_id']
                   and evidence['failure_id'] == episode['failure_id'], 'investigation_identity_changed')
        c._require(type(evidence['searches']) is int and 0 <= evidence['searches'] <= 3
                   and type(evidence['reads']) is int and 0 <= evidence['reads'] <= 5, 'investigation_research_limit')
        sources, corrections = evidence['sources'], evidence['corrections']
        c._require(isinstance(sources, list) and len(sources) <= 5 and len(sources) <= evidence['reads']
                   and isinstance(corrections, list) and len(corrections) <= 2, 'investigation_research_limit')
        for source in sources: _source(source)
        normalized = [_correction(fix, candidate['seat'], sources) for fix in corrections]
        c._require(len({c._json(fix) for fix in normalized}) == len(normalized), 'distinct_corrections_required')
        failed = [row.get('correction') for row in _history(value) if row.get('signature') == episode['signature']
                  and row.get('outcome') != 'accepted']
        c._require(not any(fix in failed for fix in normalized), 'previously_failed_correction')
        episode.update(state='diagnosed', evidence=copy.deepcopy(evidence), completed_monotonic=time.monotonic())
        c._save(run, value)
        return dict(candidate_id=candidate['candidate_id'], corrections=len(corrections), state='diagnosed')


def _archive(value, phase, member):
    key = c._key(phase, member)
    if key in value['members']:
        item = value['members'].pop(key)
        if not any(old['attempt_id'] == item['attempt_id'] for old in value['archived_attempts']):
            value['archived_attempts'].append(item)
    state = value['recovery'][member]
    state['serial'] += 1
    state.pop('active_correction', None)
    state.pop('not_before_monotonic', None)


def correct_candidate(run, phase, member, correction):
    with _admitted(run) as value:
        item, failure = _guard(run, value, phase, member)
        candidate = current(value, member)
        episode = candidate['investigation']
        c._require(episode is not None and episode['state'] == 'diagnosed', 'diagnosis_required')
        c._require(type(correction) is int and 0 <= correction < len(episode['evidence']['corrections']), 'unsupported_correction')
        c._require(correction not in candidate['tried'], 'correction_already_tried')
        c._require(len(candidate['tried']) < 2, 'correction_limit')
        fix = episode['evidence']['corrections'][correction]
        if fix['kind'] == 'fresh_connection':
            c._require(failure['category'] in ('service', 'rate_limit', 'transport', 'unknown', 'interrupted'), 'transport_correction_required')
            c._require(fix['retry_delay_seconds'] < c._remaining(value, phase), 'deadline_exhausted')
        candidate['tried'].append(correction)
        _archive(value, phase, member)
        value['recovery'][member]['active_correction'] = copy.deepcopy(fix)
        value['recovery'][member]['failure_id'] = item['attempt_id']
        value['recovery'][member]['not_before_monotonic'] = time.monotonic() + fix.get('retry_delay_seconds', 0)
        c._save(run, value)
        return dict(candidate_id=candidate['candidate_id'], state='correction_ready', correction_number=len(candidate['tried']),
                    not_before_monotonic=value['recovery'][member]['not_before_monotonic'])


def replace_candidate(run, phase, member, seat):
    with _admitted(run) as value:
        _guard(run, value, phase, member)
        state = value['recovery'][member]
        c._require(len(state['candidates']) < 4, 'replacement_limit')
        episode = current(value, member)['investigation']
        c._require(episode is not None and (episode['state'] == 'diagnosed' or time.monotonic() >= episode['deadline_monotonic']), 'diagnosis_required')
        c._require(isinstance(seat, dict) and seat.get('kind') == c._seat(value, member, phase)['kind'], 'replacement_kind_changed')
        original = state['candidates'][0]['seat']
        c._require(all(type(seat.get(k)) is int and 1 <= seat[k] <= original[k] for k in ('input_tokens', 'output_tokens', 'steps')), 'replacement_exceeds_envelope')
        c._require(_canonical(seat) not in {_canonical(x['seat']) for x in state['candidates']}, 'candidate_already_used')
        permitted = value.get('fallbacks', {}).get(member, [])
        route = lambda row: (_canonical(row), row['model'], row.get('provider'), row['kind'])
        transfer = phase == 'synthesis' and any(route(seat) == route(s) and
            c._observations(value, 'investigate')[m].get('state') == 'accepted'
            for m, s in value['roster'].items() if m != member)
        c._require(transfer or any(route(seat) == route(row) for row in permitted), 'replacement_outside_approved_shortlist')
        roster = copy.deepcopy(value['roster'])
        roster[member] = seat
        if phase != 'synthesis':
            c._require(_canonical(seat) not in {_canonical(s) for m, s in roster.items() if m != member}, 'canonical_model_claimed')
        # Validate the complete original topology and selected route, including Free/max reasoning.
        # A synthesis role transfer may reuse a successful participant's canonical identity.
        validation_roster = copy.deepcopy(roster)
        if phase == 'synthesis':
            for m, other in validation_roster.items():
                if m != member and _canonical(other) == _canonical(seat):
                    c._require(any(binding.get('canonical_model') == _canonical(seat)
                                   for binding in value['role_bindings']['investigate'].values()), 'chair_transfer_not_successful')
                    validation_roster[m] = copy.deepcopy(value['recovery'][member]['candidates'][0]['seat'])
        request = {key: value[key] for key in ('run_id', 'question', 'constraints', 'coordinator_chat_id', 'approval_ref',
                    'phase_seconds', 'timeout_seconds', 'group', 'chair')}
        request.update(roster=validation_roster, research='', approved_files=value['snapshot_manifest']['files'])
        c._validate(request)
        _archive(value, phase, member)
        state['candidates'].append(_candidate(seat))
        if phase == 'synthesis': value.setdefault('synthesis_roster', {})[member] = copy.deepcopy(seat)
        else:
            value['roster'][member] = copy.deepcopy(seat)
            if phase == 'critique': state['catch_up'] = True
        c._save(run, value)
        return dict(candidate_id=current(value, member)['candidate_id'], replacements=len(state['candidates']) - 1,
                    state='catch_up_required' if state['catch_up'] else 'replacement_ready')


def _generation_directory(run, generation):
    directory = run / ('generation-' + str(generation))
    if not directory.exists(): directory.mkdir(mode=0o700)
    return directory


def freeze(run, value, phase, observed):
    directory = _generation_directory(run, value['critique_generation'])
    names = {}
    for number, member in enumerate(c._members(value), 1):
        item = observed.get(member, {})
        if item.get('state') == 'accepted':
            name = ('initial' if phase == 'investigate' else 'critique') + '-' + str(number) + '.md'
            raw = c._report(item.get('report', item.get('final_response', item.get('response'))))
            path = str(directory.relative_to(run) / name)
            if path in value['frozen']: c._require(value['frozen'][path] == c._digest(raw), 'frozen_evidence_changed')
            else: c.changes._atomic(directory, name, raw)
            names[path] = c._digest(raw)
    if phase == 'investigate': names['research.md'] = c._digest(c._read(run / 'research.md', c.REPORT_LIMIT))
    value['frozen'].update(names)
    value.setdefault('phase_execution', {})[phase] = c._execution_summary(phase, observed, c._members(value))


def publish_generation(run):
    with _admitted(run) as value:
        c._require(value.get('version') == 3 and value['phase'] == 'critique', 'critique_phase_required')
        c._remaining(value, 'critique')
        pending = [member for member, state in value['recovery'].items() if state['catch_up']]
        c._require(pending, 'no_pending_generation')
        c._require(prior_stopped(value, 'critique'), 'prior_owner_not_stopped')
        for member in pending:
            owner = value['members'].get(c._key('critique', member))
            c._require(owner is not None and observe(value, owner).get('state') == 'accepted', 'catch_up_not_accepted')
        value['generations'].append(dict(generation=value['critique_generation'], frozen=copy.deepcopy(value['frozen']), superseded=True))
        value['retained_frozen'].update(value['frozen'])
        value['frozen'] = {}
        value['critique_generation'] += 1
        for member in c._members(value):
            if member in pending:
                owner = value['members'][c._key('critique', member)]
                _archive(value, 'investigate', member)
                value['members'][c._key('investigate', member)] = owner
                binding = dict(candidate_id=owner['candidate_id'], model=owner['seat']['model'], canonical_model=_canonical(owner['seat']))
                value['role_bindings']['investigate'][member] = binding
                value['recovery'][member]['catch_up'] = False
            _archive(value, 'critique', member)
        freeze(run, value, 'investigate', c._observations(value, 'investigate'))
        c._save(run, value)
        return dict(critique_generation=value['critique_generation'], state='critique_ready')


def fresh_session(value, session, path):
    for owner in owners(value):
        if owner['kind'] != 'external' or owner['worker_run'] == str(path): continue
        observed = observe(value, owner)
        c._require(session != observed.get('session_id') and session not in owner.get('session_ids', []), 'fresh_external_session_required')


def fresh_child(value, child):
    c._require(all(owner.get('receipt', {}).get('child_id') != child for owner in owners(value)), 'fresh_native_child_required')


def learn(value, phase, member, outcome):
    owner = value['members'].get(c._key(phase, member), {})
    if not owner.get('correction') or owner.get('learning_recorded'): return
    candidate = next(row for row in value['recovery'][member]['candidates'] if row['candidate_id'] == owner['candidate_id'])
    episode = candidate['investigation']
    correction = owner['correction']
    observed = observe(value, owner)
    if observed.get('local_execution_stopped') is not True: return
    _history(value, dict(attempt_id=owner['attempt_id'], signature=episode['signature'],
        model=owner['seat']['model'], provider=owner['seat'].get('provider'),
        qualification=owner['seat'].get('permission_qualification'), correction={k: v for k, v in correction.items() if k != 'source'},
        sources=episode['evidence']['sources'], checked_at=time.time(), outcome=outcome,
        verification=owner.get('verification', {}), provisional=outcome == 'accepted'))
    owner['learning_recorded'] = True


def status(run, value):
    phases = {phase: c._observations(value, phase) for phase in c.PHASES}
    accepted = {phase: {m for m, row in rows.items() if row.get('state') == 'accepted'} for phase, rows in phases.items()}
    # Earlier independent reports remain valid across a synthesis-only role transfer.
    for phase in c.PHASES[:c.PHASES.index(value['phase'])]:
        prefix = 'initial' if phase == 'investigate' else 'critique'
        accepted[phase] = {m for number, m in enumerate(c._members(value), 1)
                           if any(Path(name).name == prefix + '-' + str(number) + '.md' for name in value['frozen'])}
    chair = value['chair']
    full = all(len(accepted[p]) == 3 for p in c.PHASES[:2]) and chair in accepted['synthesis']
    common = accepted['investigate'] & accepted['critique']
    sufficient = len(common) >= 2 and chair in accepted['synthesis']
    stop, attempts, costs, known = [], [], [], []
    external = []
    for owner in owners(value):
        result = observe(value, owner)
        stopped = result.get('local_execution_stopped') is True
        projected = dict(attempt_id=owner['attempt_id'], candidate_id=owner['candidate_id'], phase=owner['phase'],
                         member=owner['member'], generation=owner['generation'], state=result.get('state'),
                         local_execution_stopped=stopped, model=owner['seat']['model'])
        if result.get('failure') is not None: projected['failure'] = c.workers.safe_failure(result['failure'])
        attempts.append(projected)
        if not stopped:
            stop.append(dict(projected, **{k: owner[k] for k in ('worker_run', 'issued_id', 'supervisor_id') if k in owner},
                             **({'child_id': result['child_id']} if result.get('child_id') else {})))
        if owner['kind'] == 'external': external.append(result)
    for owner in value['supervisors']:
        if not owner['local_execution_stopped']:
            stop.append(dict(kind='supervisor', **{k: owner[k] for k in ('phase', 'member', 'supervisor_id')}))
    valid = lambda x: type(x) in (int, float) and math.isfinite(x) and x >= 0
    for item in external:
        costs.append(item.get('reported_cost_usd'))
        known.append(item.get('known_cost_subtotal_usd', 0))
    try: remaining, timing = max(0, value['timeout_seconds'] - c._elapsed(value)), True
    except ValueError: remaining, timing = 0, False
    recovery = {}
    for member, state in value['recovery'].items():
        candidate = current(value, member)
        episode = candidate['investigation']
        item = phases[value['phase']].get(member, {})
        progress = ('accepted' if item.get('state') == 'accepted' else
                    'investigating' if episode and episode['state'] == 'investigating' and time.monotonic() < episode['deadline_monotonic'] else
                    'trying_correction' if state.get('active_correction') else 'replacing' if len(state['candidates']) > 1 else 'working')
        recovery[member] = dict(candidate_id=candidate['candidate_id'], candidates=copy.deepcopy(state['candidates']),
            investigations_remaining=0 if episode else 1, corrections_remaining=2-len(candidate['tried']),
            replacements_remaining=4-len(state['candidates']), progress=progress,
            investigation_seconds_remaining=max(0, episode['deadline_monotonic']-time.monotonic()) if episode and episode['state'] == 'investigating' else 0,
            catch_up=state['catch_up'])
    return dict(run=str(run), phase=value['phase'], cancelled=value['cancelled'],
        outcome='complete' if full else 'incomplete' if sufficient else 'partial',
        accepted_participation={phase: dict(accepted=len(accepted[phase]), expected=1 if phase == 'synthesis' else 3) for phase in c.PHASES},
        fresh_synthesis_available=chair in accepted['synthesis'], remaining_seconds=remaining, timing_certain=timing,
        recovery=recovery, attempts=attempts, role_bindings=value['role_bindings'], critique_generation=value['critique_generation'],
        generations=value['generations'], members={phase: {m: {k: row[k] for k in ('state', 'local_execution_stopped') if k in row}
                                               for m, row in rows.items()} for phase, rows in phases.items()},
        external_total_usd=sum(costs) if external and all(valid(x) for x in costs) and all(x.get('accounting_complete') is True for x in external) else None,
        known_external_subtotal_usd=sum(x for x in known if valid(x)), upstream_cancellation_confirmed=False,
        all_local_execution_stopped=not stop, stop_requests=stop)


def record_supervisor(run, phase, member, supervisor):
    # Stop observations remain recordable after cancellation or scope revocation.
    with c._locked(run) as value:
        c._require(value.get('version') == 3, 'recovery_manifest_required')
        c._identity(value, phase, member)
        fields = {'supervisor_id', 'local_execution_stopped', 'checks'}
        c._require(isinstance(supervisor, dict) and set(supervisor) == fields
                   and c._text(supervisor['supervisor_id']) and type(supervisor['local_execution_stopped']) is bool
                   and isinstance(supervisor['checks'], list) and supervisor['checks']
                   and all(c._text(check) for check in supervisor['checks']), 'invalid_supervisor_observation')
        existing = next((item for item in value['supervisors'] if item['supervisor_id'] == supervisor['supervisor_id']), None)
        if existing:
            c._require(existing['phase'] == phase and existing['member'] == member
                       and not existing['local_execution_stopped'] and supervisor['local_execution_stopped'], 'supervisor_identity_changed')
            existing.update(supervisor)
        else:
            c._remaining(value, phase)
            c._require(value['phase'] == phase and not supervisor['local_execution_stopped'], 'invalid_supervisor_admission')
            c._require(not any(item['member'] == member and not item['local_execution_stopped'] for item in value['supervisors']), 'supervisor_already_owned')
            c._require(len(value['supervisors']) < 48, 'supervisor_history_limit')
            value['supervisors'].append(dict(supervisor, phase=phase, member=member))
        c._save(run, value)
        return dict(supervisor_id=supervisor['supervisor_id'], local_execution_stopped=supervisor['local_execution_stopped'])
