"""Usage Routing accounting with transaction-bound coordinator admission."""
from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import uuid

MAX_INTEGER = 2**53 - 1
MAX_RECORD = 2_000_000
FRESH_SECONDS = 900
MAX_DIAGNOSTIC_MS = 300000


class BudgetError(ValueError):
    """A bounded local operation cannot proceed safely."""


def require(condition, reason):
    if not condition:
        raise BudgetError(reason)


def integer(value):
    require(type(value) is int and 0 <= value <= MAX_INTEGER, 'invalid_integer')
    return value


def name(value):
    require(type(value) is str and 0 < len(value) <= 256 and value.isprintable(), 'invalid_identity')
    return value


def fields(value, expected):
    require(type(value) is dict and set(value) == set(expected.split()), 'invalid_fields')


def transport_diagnostic(value):
    """Copy bounded transport facts, omitting invalid optional metadata."""
    try:
        fields(value, 'version phase stage exception_category deadline_fired elapsed_ms remaining_ms '
                      'request_id response_id http_status')
        require(type(value['version']) is int and value['version'] == 1, 'invalid_diagnostic')
        for key, allowed in (
                ('phase', ('count', 'generation')),
                ('stage', ('validation', 'credential', 'connect', 'admission', 'request',
                           'response_headers', 'response_body', 'response_validation')),
                ('exception_category', ('dns', 'tls', 'timeout', 'remote_disconnected',
                                        'connection_reset', 'broken_pipe', 'os_error', 'http_error',
                                        'validation', 'malformed', 'unknown'))):
            require(type(value[key]) is str and value[key] in allowed, 'invalid_diagnostic')
        require(type(value['deadline_fired']) is bool, 'invalid_diagnostic')
        require(type(value['elapsed_ms']) is int and 0 <= value['elapsed_ms'] <= MAX_DIAGNOSTIC_MS,
                'invalid_diagnostic')
        remaining = value['remaining_ms']
        require(remaining is None or (type(remaining) is int and -MAX_DIAGNOSTIC_MS <= remaining <= MAX_DIAGNOSTIC_MS),
                'invalid_diagnostic')
        for key, pattern in [('request_id', r'req_[A-Za-z0-9_-]{1,251}'),
                             ('response_id', r'resp_[A-Za-z0-9_-]{1,250}')]:
            require(value[key] is None or (type(value[key]) is str and re.fullmatch(pattern, value[key])),
                    'invalid_diagnostic')
        status = value['http_status']
        require(status is None or (type(status) is int and 100 <= status <= 599), 'invalid_diagnostic')
        return value.copy()
    except BudgetError:
        return None


def private(path, directory=False):
    info = path.lstat()
    require(not path.is_symlink() and path.resolve() == path and info.st_uid == os.getuid()
            and info.st_mode & 0o077 == 0
            and (stat.S_ISDIR(info.st_mode) if directory else
                 stat.S_ISREG(info.st_mode) and info.st_nlink == 1), 'unsafe_ledger_path')
    return info


def initialize(path):
    """Explicitly create a private simulation ledger; never replace an existing one."""
    path = Path(path).absolute()
    path = path.parent.resolve() / path.name
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    private(path.parent, True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    except FileExistsError as error:
        raise BudgetError('ledger_exists') from error
    os.close(fd)
    identity = uuid.uuid4().hex
    state = dict(version=1, identity=identity, organizations={}, runs={}, native={}, finished_native=[], slot=None)
    with closing(sqlite3.connect(path)) as db:
        db.execute('CREATE TABLE ledger (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)')
        db.execute('INSERT INTO ledger VALUES (1, ?)', (json.dumps(state),))
        db.commit()
    return identity


class Ledger:
    """Identity-bound accounting. Only the trusted coordinator can supply a live gate."""
    def __init__(self, path, identity):
        self.path = Path(path).absolute()
        self.path = self.path.parent.resolve() / self.path.name
        self.identity = name(identity)
        private(self.path.parent, True)
        try:
            info = private(self.path)
        except FileNotFoundError as error:
            raise BudgetError('manual_recovery_required') from error
        self.file_identity = (info.st_dev, info.st_ino)
        self.db = sqlite3.connect(f'{self.path.as_uri()}?mode=rw', uri=True, timeout=5,
                                  isolation_level=None)
        try:
            self.db.execute('PRAGMA synchronous=FULL')
            self.snapshot()
        except BaseException:
            self.close()
            raise

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _check(self):
        try:
            info = private(self.path)
            private(self.path.parent, True)
        except FileNotFoundError as error:
            raise BudgetError('manual_recovery_required') from error
        require((info.st_dev, info.st_ino) == self.file_identity, 'ledger_replaced')

    @contextmanager
    def transaction(self, write=True):
        self._check()
        self.db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        try:
            row = self.db.execute('SELECT body FROM ledger WHERE id=1').fetchone()
            require(row is not None and len(row[0]) <= MAX_RECORD, 'invalid_ledger')
            data = json.loads(row[0])
            require(data['version'] == 1 and data['identity'] == self.identity, 'ledger_identity_changed')
            yield data
            self._check()
            if write:
                raw = json.dumps(data, allow_nan=False, separators=(',', ':'))
                require(len(raw) <= MAX_RECORD, 'ledger_capacity_reached')
                self.db.execute('UPDATE ledger SET body=? WHERE id=1', (raw,))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def snapshot(self):
        with self.transaction(False) as data:
            return data

    def configure(self, organization, policy, expected_revision):
        with self.transaction() as data:
            return self._configure(data, organization, policy, expected_revision)

    @staticmethod
    def _configure(data, organization, policy, expected_revision):
        name(organization); integer(expected_revision)
        fields(policy, 'cycle start end expiry stop_at ceiling amount grant_amount pilot_limit task_limit')
        name(policy['cycle'])
        for key in ('start', 'end', 'expiry', 'stop_at', 'grant_amount'):
            integer(policy[key])
        require(policy['start'] < policy['stop_at'] < min(policy['end'], policy['expiry']), 'invalid_expiry_window')
        require(policy['ceiling'] in ('none', 'custom', 'subscription_benefit'), 'invalid_ceiling')
        if policy['ceiling'] == 'custom':
            require(integer(policy['amount']) > 0, 'invalid_ceiling')
        else:
            require(policy['amount'] is None, 'unexpected_amount')
        for limit in (policy['pilot_limit'], policy['task_limit']):
            require(limit is None or integer(limit) > 0, 'invalid_limits')
        if policy['ceiling'] == 'subscription_benefit':
            require(policy['grant_amount'] > 0, 'missing_grant_coverage')
        org = data['organizations'].get(organization)
        require((org['revision'] if org else 0) == expected_revision, 'policy_revision_changed')
        if org:
            old = org['policy']
            if old == policy:
                return org['revision']
            if old['cycle'] == policy['cycle']:
                require((old['start'], old['end']) == (policy['start'], policy['end']), 'cycle_changed')
            else:
                require(policy['start'] >= old['end'], 'overlapping_cycle')
            # A new cycle does not create credits or clear retained exposure.
        else:
            org = dict(revision=0, balance=None, observed_at=None, floor=None, blocked=False)
            data['organizations'][organization] = org
        org['revision'] += 1
        org['policy'] = policy.copy()
        return org['revision']

    def observe(self, organization, balance, observed_at):
        integer(balance); integer(observed_at)
        with self.transaction() as data:
            org = data['organizations'][organization]
            require(org['observed_at'] is None or observed_at > org['observed_at'], 'observation_not_newer')
            org['balance'] = min(org['balance'], balance) if org['balance'] is not None else balance
            if org['floor'] is None:
                org['floor'] = (balance + 4) // 5
            org['observed_at'] = observed_at

    @staticmethod
    def _cost(call):
        return call['cost'] if call['cost'] is not None else call['maximum']

    @classmethod
    def _total(cls, data, organization, task=None, cycle=None):
        return sum(cls._cost(call) for run in data['runs'].values()
                   if run['organization'] == organization and (task is None or run['task'] == task)
                   for call in run['calls'].values() if cycle is None or call['cycle'] == cycle)

    @classmethod
    def _credit(cls, data, organization):
        org = data['organizations'][organization]
        require(org['balance'] is not None, 'balance_unverified')
        return max(0, org['balance'] - org['floor'] - cls._total(data, organization))

    @classmethod
    def _headroom(cls, data, organization, task=None):
        org = data['organizations'][organization]; policy = org['policy']
        limits = [cls._credit(data, organization)]
        if policy['pilot_limit'] is not None:
            limits.append(policy['pilot_limit'] - cls._total(data, organization))
        if task is not None and policy['task_limit'] is not None:
            limits.append(policy['task_limit'] - cls._total(data, organization, task))
        cap = policy['amount'] if policy['ceiling'] == 'custom' else policy['grant_amount']
        if policy['ceiling'] != 'none':
            limits.append(cap - cls._total(data, organization, cycle=policy['cycle']))
        return max(0, min(limits))

    def headroom(self, organization):
        with self.transaction(False) as data:
            return self._headroom(data, organization)

    def credit_headroom(self, organization):
        with self.transaction(False) as data:
            return self._credit(data, organization)

    @classmethod
    def _admit(cls, data, organization, task, maximum, revision, now):
        integer(maximum); integer(revision); integer(now)
        org = data['organizations'][organization]; policy = org['policy']
        require(not org['blocked'], 'manual_recovery_required')
        require(org['revision'] == revision, 'policy_revision_changed')
        require(org['observed_at'] is not None and 0 <= now - org['observed_at'] <= FRESH_SECONDS,
                'balance_stale_or_missing')
        require(policy['start'] <= now < policy['stop_at'], 'expiry_or_cycle_boundary')
        require(maximum <= cls._headroom(data, organization, task), 'insufficient_headroom')

    @classmethod
    def _live_admit(cls, data, organization, added, now, gate, run=None):
        if run is not None:
            require(('live_admission' in run) == (gate is not None), 'live_admission_mismatch')
        if gate is None:
            return None
        require(callable(gate), 'invalid_live_gate')
        integer(added); integer(now)
        # The gate may stage verified credit in this transaction before _admit reads it.
        admission = gate(data, now)
        fields(admission, 'pin maximum')
        name(admission['pin'])
        require(integer(admission['maximum']) > 0, 'invalid_live_cap')
        if run is not None:
            require(admission == run['live_admission'], 'live_admission_mismatch')
        require(cls._total(data, organization) + added <= admission['maximum'], 'live_cap_exceeded')
        return admission.copy()

    @staticmethod
    def _native(data, evidence, now, reserve=True):
        fields(evidence, 'account task windows')
        account, task = name(evidence['account']), name(evidence['task'])
        key = json.dumps([account, task])
        require(key not in data['finished_native'], 'native_task_closed')
        if reserve and key not in data['native']:
            data['native'][key] = dict(account=account, task=task, latest_at=now)
        return key

    def begin(self, organization, task, run_id, digest, maximum, revision, now, native, *, consent=None, live_gate=None):
        for value in (organization, task, run_id, digest): name(value)
        with self.transaction() as data:
            if run_id in data['runs']:
                run = data['runs'][run_id]
                require(live_gate is None and 'live_admission' not in run, 'live_run_id_already_used')
                require((run['organization'], run['task'], run['digest']) == (organization, task, digest), 'run_identity_changed')
                return run
            require(len(data['runs']) < 1000, 'ledger_capacity_reached')
            require(data['slot'] is None, 'request_in_flight')
            admission = self._live_admit(data, organization, maximum, now, live_gate)
            self._admit(data, organization, task, maximum, revision, now)
            require(native.get('task') == task, 'native_task_mismatch')
            key = self._native(data, native, now)
            data['native'][key]['latest_at'] = now
            if consent is not None:
                self._consent(data, consent)
            run = dict(consent=consent, organization=organization, task=task, digest=digest, revision=revision,
                       native=key, closed=False, calls={})
            if admission is not None:
                run['live_admission'] = admission
            data['runs'][run_id] = run
            run['calls']['count'] = self._call(data, run, maximum, digest)
            data['slot'] = run_id
            return run

    @staticmethod
    def _call(data, run, maximum, digest):
        return dict(maximum=maximum, cost=None, digest=digest, state='reserved',
                    cycle=data['organizations'][run['organization']]['policy']['cycle'])

    def reserve_generation(self, run_id, digest, maximum, revision, now, *, live_gate=None):
        name(digest)
        with self.transaction() as data:
            run = data['runs'][run_id]
            require(data['slot'] == run_id and not run['closed'] and
                    run['calls']['count']['state'] == 'completed', 'count_not_completed')
            require('generation' not in run['calls'], 'attempt_exists')
            require(run['revision'] == revision, 'policy_revision_changed')
            self._live_admit(data, run['organization'], maximum, now, live_gate, run)
            self._admit(data, run['organization'], run['task'], maximum, revision, now)
            run['calls']['generation'] = self._call(data, run, maximum, digest)

    def dispatch(self, run_id, phase, revision, now, *, live_gate=None):
        with self.transaction() as data:
            run = data['runs'][run_id]; call = run['calls'][phase]
            if run.get('consent') is not None:
                self._consent(data, run['consent'])
            require(data['slot'] == run_id and not run['closed'] and call['state'] == 'reserved', 'dispatch_forbidden')
            require(run['revision'] == revision, 'policy_revision_changed')
            # The call's own reservation has already reduced headroom.
            self._live_admit(data, run['organization'], 0, now, live_gate, run)
            self._admit(data, run['organization'], run['task'], 0, revision, now)
            require(self._headroom(data, run['organization'], run['task']) >= 0, 'insufficient_headroom')
            policy = data['organizations'][run['organization']]['policy']
            require((policy['pilot_limit'] is None or self._total(data, run['organization']) <= policy['pilot_limit'])
                    and (policy['task_limit'] is None
                         or self._total(data, run['organization'], run['task']) <= policy['task_limit']),
                    'limits_changed')
            cap = policy['amount'] if policy['ceiling'] == 'custom' else policy['grant_amount']
            require(policy['ceiling'] == 'none' or self._total(data, run['organization'], cycle=policy['cycle']) <= cap, 'limits_changed')
            require(data['organizations'][run['organization']]['balance'] >=
                    data['organizations'][run['organization']]['floor'] + self._total(data, run['organization']), 'credit_changed')
            call['state'] = 'dispatching'
            data['native'][run['native']]['latest_at'] = now

    def complete(self, run_id, phase, actual):
        integer(actual)
        overrun = False
        with self.transaction() as data:
            run = data['runs'][run_id]; call = run['calls'][phase]
            require(call['state'] in ('dispatching', 'unresolved'), 'completion_forbidden')
            if actual > call['maximum']:
                data['organizations'][run['organization']]['blocked'] = True
                call['state'] = 'unresolved'; overrun = True
            else:
                call.update(cost=actual, state='completed')
                if phase == 'generation':
                    data['slot'] = None; run['closed'] = True
        require(not overrun, 'cost_exceeds_bound')

    def uncertain(self, run_id, phase, *, incomplete=None, diagnostic=None):
        diagnostic = transport_diagnostic(diagnostic)
        with self.transaction() as data:
            call = data['runs'][run_id]['calls'][phase]
            require(call['state'] == 'dispatching', 'uncertainty_forbidden')
            call['state'] = 'unresolved'
            if incomplete is not None:
                call['incomplete'] = incomplete
            if diagnostic is not None and diagnostic['phase'] == phase:
                call['diagnostic'] = diagnostic
                # Optional diagnostics must not prevent conservative accounting.
                if len(json.dumps(data, allow_nan=False, separators=(',', ':'))) > MAX_RECORD:
                    del call['diagnostic']

    def close_run(self, run_id):
        with self.transaction() as data:
            run = data['runs'][run_id]
            require(not any(c['state'] in ('dispatching', 'unresolved') for c in run['calls'].values()), 'request_may_be_running')
            for call in run['calls'].values():
                if call['state'] == 'reserved': call.update(cost=0, state='rejected-before-send')
            run['closed'] = True
            if data['slot'] == run_id: data['slot'] = None

    def release_native(self, account, task, evidence, now):
        with self.transaction() as data:
            key = json.dumps([name(account), name(task)])
            runs = [run for run in data['runs'].values() if run['native'] == key]
            require(all(run['closed'] for run in runs), 'native_task_active')
            require(evidence['account'] == account and evidence['task'] == task, 'native_task_mismatch')
            require(key in data['native'], 'native_task_missing')
            if key not in data['finished_native']:
                data['finished_native'].append(key)

    def reject_unsent(self, run_id, phase):
        """Host transport established no send; not a user/worker receipt."""
        with self.transaction() as data:
            run = data['runs'][run_id]; call = run['calls'][phase]
            require(call['state'] == 'dispatching', 'rejection_forbidden')
            call.update(cost=0, state='rejected-before-send')
            run['closed'] = True
            if data['slot'] == run_id: data['slot'] = None

    @staticmethod
    def _consent(data, pin):
        fields(pin, 'scope revision qualification_revision')
        config = data.get('routing', {}).get(pin['scope'])
        require(config is not None and config['revision'] == pin['revision']
                and not config['disabled'] and (pin['qualification_revision'] is None
                or config['qualification_revision'] == pin['qualification_revision']), 'consent_changed')

    def reconcile(self, *, scope=None):
        """Report scoped recovery evidence without altering reservations."""
        result = {'state': 'manual_recovery_required'}
        if scope is None:
            return result
        data = self.snapshot()
        run_id = data['slot']
        run = data['runs'].get(run_id)
        if run and (run.get('consent') or {}).get('scope') == scope:
            for phase, call in run['calls'].items():
                if call['state'] == 'unresolved':
                    result['pending'] = dict(attempt_id=run_id + ':' + phase,
                                             reserved_usd_micros=call['maximum'],
                                             incomplete=call.get('incomplete'))
                    diagnostic = transport_diagnostic(call.get('diagnostic'))
                    if diagnostic is not None and diagnostic['phase'] == phase:
                        result['pending']['diagnostic'] = diagnostic
                    break
        return result
