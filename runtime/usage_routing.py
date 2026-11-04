"""Select routes and enforce local controls for Usage Routing."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from runtime import startup, usage_admission, usage_credentials
from runtime.usage_budget import BudgetError, fields, integer, name, require

PACKAGE = Path(__file__).resolve().parents[1]
MAX_INPUT = 65536
FUNDING_WARNING = ('Grant-only funding is best effort. Account auto-reload may buy credits and '
                   'the provider may consume other funding; local limits cannot guarantee otherwise.')
HANDOFF_REASONS = frozenset(('insufficient_headroom', 'balance_stale_or_missing',
    'expiry_or_cycle_boundary', 'evidence_deadline_expired', 'observation_stale',
    'request_in_flight', 'native_capacity_expired'))


def status(cwd=None):
    """Read enrollment only, without creating runtime state or observing billing."""
    enrollment = 'unknown'
    if cwd is not None:
        try:
            entry = startup.acquire_project_entry(SimpleNamespace(client='codex', cwd=Path(cwd)), PACKAGE)
            enrollment = entry.resolution.status
        except (OSError, ValueError, startup.StartupError):
            enrollment = 'unavailable'
    enrolled = True if enrollment in ('active', 'configured') else False if enrollment == 'outside' else None
    result = dict(version=1, mode='off', live_dispatch=False, simulation_only=True,
                  review_authority=False, enrolled=enrolled, enrollment=enrollment,
                  reason='live_adapter_unavailable', enabled=False, funding_policy='best_effort_grant',
                  warnings=[FUNDING_WARNING])
    from runtime.usage_settings import controller, directory
    if (directory() / 'organizations.sqlite3').exists() and cwd is not None:
        try:
            with controller(cwd) as control:
                result.update(control.status())
        except (BudgetError, OSError, ValueError, KeyError, TypeError):
            result['reason'] = 'configuration_or_scope_unavailable'
    return result



def enable(cwd, request):
    if cwd is None:
        raise BudgetError('live_execution_unavailable')
    from runtime.usage_settings import controller
    fields(request, 'expected_revision mode' if isinstance(request, dict) and 'mode' in request else 'expected_revision')
    with controller(cwd) as control:
        return control.enable(request['expected_revision'], mode=request.get('mode'))


def run(cwd, request):
    raise BudgetError('live_execution_unavailable')


def _run_live(cwd, task, evidence):
    """Internal Codex host path. The host owns evidence provenance."""
    from runtime import usage_admission, usage_settings

    require(type(evidence) is usage_admission.Admission, 'trusted_live_evidence_required')
    with usage_settings.controller(cwd) as control:
        def check_scope():
            require(usage_settings.scope(cwd) == (control.scope, control.root), 'scope_changed')

        return control._run_live(task, evidence, scope_check=check_scope)


def quote(packet, profile, now):
    """Conservative offline quote from synthetic, untrusted count/pricing observations.

    A digest binds these inputs, but does not authenticate them or authorize a call.
    Rates use integer USD micro-units per million tokens.
    """
    fields(packet, 'version model reasoning text input_tokens max_output_tokens')
    fields(profile, 'model reasoning tier input_rate cached_input_rate cache_write_rate output_rate max_input_tokens max_output_tokens verified_at valid_until count_maximum')
    require(type(packet['version']) is int and packet['version'] == 1, 'invalid_version')
    for item in (packet['model'], packet['reasoning'], profile['model'], profile['reasoning']): name(item)
    require(packet['model'] == profile['model'] and packet['reasoning'] == profile['reasoning'], 'profile_mismatch')
    require(profile['tier'] == 'default', 'unsupported_processing_tier')
    require(type(packet['text']) is str and 0 < len(packet['text'].encode()) <= MAX_INPUT, 'invalid_text')
    for key in ('input_tokens', 'max_output_tokens'): integer(packet[key])
    for key in ('input_rate', 'cached_input_rate', 'cache_write_rate', 'output_rate',
                'max_input_tokens', 'max_output_tokens', 'verified_at', 'valid_until', 'count_maximum'):
        integer(profile[key])
    require(profile['input_rate'] > 0 and profile['output_rate'] > 0, 'unknown_price')
    require(profile['verified_at'] <= integer(now) < profile['valid_until'], 'pricing_stale')
    require(packet['input_tokens'] <= profile['max_input_tokens'] and
            0 < packet['max_output_tokens'] <= profile['max_output_tokens'], 'token_limit_exceeded')
    rate = max(profile['input_rate'], profile['cached_input_rate'], profile['cache_write_rate'])
    maximum = (packet['input_tokens'] * rate + packet['max_output_tokens'] * profile['output_rate'] + 999999) // 1000000
    integer(maximum)
    raw = json.dumps(dict(packet=packet, profile=profile), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    require(len(raw) <= MAX_INPUT, 'request_too_large')
    return dict(version=1, digest=hashlib.sha256(raw).hexdigest(), maximum_usd_micros=maximum,
                count_maximum_usd_micros=profile['count_maximum'], simulation_only=True)


def calibrate(samples, resolution_pp, rounding_qualified):
    """Fixed native allowance; never infer zero consumption from rounded usage."""
    require(rounding_qualified is True and type(samples) is list and 0 < len(samples) <= 100,
            'native_calibration_unqualified')
    resolution = integer(resolution_pp)
    require(0 < resolution <= 100, 'native_calibration_unqualified')
    for value in samples: integer(value)
    allowance = 2 * (max(samples) + resolution)
    allowance = ((allowance + resolution - 1) // resolution) * resolution
    require(allowance <= 100, 'native_allowance_unaffordable')
    return allowance


def profile_digest(profile):
    return hashlib.sha256(json.dumps(profile, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class Controller:
    """Durable consent, shadow selection and internal live admission.

    Shadow observations and qualifications grant no live authority.
    """
    def __init__(self, ledger, scope, *, clock=None, root=None):
        import time
        self.ledger, self.scope = ledger, name(scope)
        self.clock = clock or (lambda: int(time.time()))
        self.root = Path(root).resolve() if root is not None else None

    def _config(self, data):
        config = data.get('routing', {}).get(self.scope)
        require(config is not None, 'not_configured')
        return config

    def configure(self, request):
        fields(request, 'version expected_revision expected_org_revision binding policy profile class_name mode')
        version = request['version']
        require(type(version) is int and version in (1, 2), 'invalid_version')
        integer(request['expected_revision']); integer(request['expected_org_revision'])
        binding = request['binding']
        if version == 1:
            fields(binding, 'organization project credential_ref')
            for value in binding.values(): name(value)
            require(binding['credential_ref'].isidentifier(), 'invalid_credential_reference')
        else:
            try:
                usage_credentials.validate_binding(binding)
            except usage_credentials.CredentialError as error:
                raise BudgetError(str(error)) from None
        name(request['class_name'])
        require(request['mode'] in ('manual', 'smart'), 'invalid_mode')
        profile = request['profile']
        # Validate the complete profile without transmitting a counting request.
        packet = dict(version=1, model=profile['model'], reasoning=profile['reasoning'],
                      text='qualification', input_tokens=0, max_output_tokens=1)
        quote(packet, profile, self.clock())
        with self.ledger.transaction() as data:
            records = data.setdefault('routing', {})
            old = records.get(self.scope)
            require((old['revision'] if old else 0) == request['expected_revision'], 'consent_revision_changed')
            revision = self.ledger._configure(data, binding['organization'], request['policy'], request['expected_org_revision'])
            records[self.scope] = dict(revision=request['expected_revision']+1, binding=binding.copy(),
                org_revision=revision, profile=profile.copy(), class_name=request['class_name'],
                requested_mode=request['mode'], enabled=False, disabled=False, qualification=None, qualification_revision=0)
        return self.status()

    def status(self):
        data = self.ledger.snapshot()
        config = data.get('routing', {}).get(self.scope)
        enabled = bool(config and config.get('enabled',False) and not config['disabled'])
        return dict(version=1, mode=config['requested_mode'] if enabled else 'off', enabled=enabled,
                    live_dispatch=False, review_authority=False, funding_policy='best_effort_grant',
                    warnings=[FUNDING_WARNING],
                    simulation_only=True, requested_mode=config['requested_mode'] if config else None,
                    revision=config['revision'] if config else 0,
                    reason='disabled' if config and config['disabled'] else 'live_adapter_unavailable')

    def enable(self, expected_revision, *, mode=None):
        integer(expected_revision)
        require(mode in (None, 'manual', 'smart'), 'invalid_mode')
        with self.ledger.transaction() as data:
            config = self._config(data)
            require(config['revision'] == expected_revision, 'consent_revision_changed')
            require('manual_test_owner' not in config, 'manual_test_in_use')
            if mode is not None:
                config['requested_mode'] = mode
            config['revision'] += 1
            config['enabled'] = True
            config['disabled'] = False
        return self.status()

    def disable(self, expected_revision):
        integer(expected_revision)
        with self.ledger.transaction() as data:
            config = self._config(data)
            require(config['revision'] == expected_revision, 'consent_revision_changed')
            config['revision'] += 1
            config['disabled'] = True
            config['enabled'] = False
        return self.status()

    def record_qualification(self, record):
        expected = 'class_name profile_digest samples quality_passed net_native_saved uncertainty unit native_calibrated observed_at valid_until'
        if isinstance(record, dict) and 'native_allowance_pp' in record:
            expected += ' native_allowance_pp'
            usage_admission.smart_native_allowance(record)
        fields(record, expected)
        for field in ('samples','net_native_saved','uncertainty','observed_at','valid_until'):
            integer(record[field])
        for field in ('quality_passed','native_calibrated'):
            require(type(record[field]) is bool, 'invalid_qualification')
        require(record['observed_at'] <= self.clock() < record['valid_until'], 'qualification_stale')
        name(record['unit'])
        with self.ledger.transaction() as data:
            config = self._config(data)
            require('manual_test_owner' not in config, 'manual_test_in_use')
            require(record['class_name'] == config['class_name'] and
                    record['profile_digest'] == profile_digest(config['profile']), 'qualification_profile_changed')
            config['qualification'] = dict(record)
            config['qualification_revision'] += 1

    def observe(self, observation):
        fields(observation, 'version organization project currency balance expiry observed_at source pool')
        require(type(observation['version']) is int and observation['version'] == 1, 'invalid_version')
        require(observation['currency'] == 'USD' and observation['source'] in
                ('codex-dashboard', 'platform-credit-grants'), 'observation_unqualified')
        integer(observation['balance']); integer(observation['observed_at']); integer(observation['expiry'])
        with self.ledger.transaction() as data:
            config = self._config(data); org_id = config['binding']['organization']
            require((observation['organization'], observation['project']) ==
                    (org_id, config['binding']['project']), 'observation_identity_changed')
            org = data['organizations'][org_id]
            require(observation['expiry'] == org['policy']['expiry'], 'expiry_changed')
            require(observation['pool'] in ('benefit','prepaid','mixed') and
                    (org['policy']['ceiling'] != 'subscription_benefit' or observation['pool'] == 'benefit'), 'pool_unqualified')
            require(0 <= self.clock() - observation['observed_at'] <= 900, 'observation_stale')
            require(org['observed_at'] is None or observation['observed_at'] > org['observed_at'], 'observation_not_newer')
            org['balance'] = min(org['balance'], observation['balance']) if org['balance'] is not None else observation['balance']
            if org['floor'] is None: org['floor'] = (observation['balance'] + 4)//5
            org['observed_at'] = observation['observed_at']
            org['observation_source'] = observation['source']
            org['funding_state'] = 'unverified'

    def _snapshots(self, snapshots):
        require(type(snapshots) is list and len(snapshots) <= 32, 'invalid_snapshots')
        for snapshot in snapshots:
            fields(snapshot, 'path sha256')
            require(self.root is not None, 'snapshot_changed')
            path = Path(snapshot['path'])
            require(path.is_absolute() and not path.is_symlink() and path.resolve().is_relative_to(self.root)
                    and path.is_file() and path.stat().st_size <= MAX_INPUT, 'snapshot_changed')
            require(hashlib.sha256(path.read_bytes()).hexdigest() == snapshot['sha256'], 'snapshot_changed')

    def _evaluate(self, data, task):
        fields(task, 'task_id run_id class_name packet provider local_preferred api_only reviewer_available native snapshots')
        for field in ('local_preferred','api_only','reviewer_available'):
            require(type(task[field]) is bool, 'invalid_task')
        for field in ('task_id','run_id','class_name','provider'): name(task[field])
        config = self._config(data)
        require(not config['disabled'], 'disabled')
        if task['provider'] not in ('auto','openai-api') or task['local_preferred']:
            return dict(decision='paused' if task['api_only'] else 'native', reason='explicit_provider_or_local_preference')
        require(task['reviewer_available'], 'independent_review_unavailable')
        require(task['class_name'] == config['class_name'], 'task_class_unqualified')
        org_id = config['binding']['organization']
        require(data['organizations'][org_id]['revision'] == config['org_revision'], 'policy_revision_changed')
        if config['requested_mode'] == 'smart':
            usage_admission.smart_qualification(config, self.clock())
        self._snapshots(task['snapshots'])
        bound = quote(task['packet'], config['profile'], self.clock())
        require(task['native'].get('task') == task['task_id'], 'native_task_mismatch')
        # Operate on a deserialized snapshot: selection must not reserve or write.
        self.ledger._native(data, task['native'], self.clock())
        require(data['slot'] is None, 'request_in_flight')
        self.ledger._admit(data, org_id, task['task_id'],
                           bound['maximum_usd_micros'] + bound['count_maximum_usd_micros'],
                           config['org_revision'], self.clock())
        return dict(decision='eligible', reason='qualified_profile_and_budget', maximum_usd_micros=bound['maximum_usd_micros'],
                    consent=dict(scope=self.scope, revision=config['revision'], qualification_revision=config['qualification_revision']))

    def evaluate(self, task):
        try:
            result = self._evaluate(self.ledger.snapshot(), task)
        except (BudgetError, KeyError, TypeError, OSError, ValueError) as error:
            result = dict(decision='paused', reason=str(error) if isinstance(error,BudgetError) else 'invalid_task_or_state')
        return result | dict(simulation_only=True, live_blocker='live_adapter_unavailable',
                             warning_codes=['best_effort_grant_funding'],
                             handoff_recommended=result['decision'] == 'paused' and result['reason'] in HANDOFF_REASONS)

    def request_handoff(self, task, reason):
        """Queue remaining work for existing native dispatch; never clears API exposure."""
        import copy
        require(reason in HANDOFF_REASONS, 'unsupported_handoff_reason')
        fields(task, 'task_id run_id class_name packet provider local_preferred api_only reviewer_available native snapshots')
        name(task['task_id']); name(task['run_id']); name(task['provider'])
        require(type(task['api_only']) is bool and type(task['reviewer_available']) is bool, 'invalid_task')
        require(type(task['packet']) is dict and type(task['packet'].get('text')) is str and
                len(json.dumps(task['packet']).encode()) <= MAX_INPUT, 'invalid_handoff_packet')
        self._snapshots(task['snapshots'])
        packet_id = profile_digest(task['packet'])
        key = profile_digest(dict(scope=self.scope,task=task['task_id']))
        with self.ledger.transaction() as data:
            config = self._config(data)
            require(not config['disabled'], 'disabled')
            records = data.setdefault('handoffs',{})
            record = records.get(key)
            if record is not None:
                require(record['packet_digest'] == packet_id, 'handoff_task_changed')
            if record is None or record['claim_attempt'] is None:
                state = 'ready'
                if task['api_only'] or task['provider'] not in ('auto','openai-api','native'):
                    state = 'user_choice_required'
                elif not task['reviewer_available']:
                    state = 'waiting_for_native_capacity'
                else:
                    try:
                        require(task['native'].get('task') == task['task_id'], 'native_task_mismatch')
                        self.ledger._native(copy.deepcopy(data),task['native'],self.clock())
                    except BudgetError:
                        state = 'waiting_for_native_capacity'
                require(record is not None or len(records) < 1000, 'handoff_capacity_reached')
                record = dict(handoff_id=key, state=state, reason=reason, task_id=task['task_id'],
                    packet_digest=packet_id, scope=self.scope, revision=config['revision'],
                    native=copy.deepcopy(task['native']), claim_attempt=None)
                records[key] = record
            pending = any(run['task'] == task['task_id'] and
                          (run.get('consent') or {}).get('scope',self.scope) == self.scope and
                          any(call['state'] in ('dispatching','unresolved') for call in run['calls'].values())
                          for run in data['runs'].values())
            result = dict(record)
        return result | dict(pending_api_accounting=pending, requires_native_review=True, accepted=False,
            brief=dict(task_id=task['task_id'], packet=task['packet'], snapshots=task['snapshots'],
                       instruction='Continue remaining work natively. Recheck source; do not apply late API output without fresh checks and independent review.'))

    def claim_handoff(self, task_id, attempt_id):
        """Claim once BEFORE host native dispatch; a replay must observe, never respawn."""
        name(task_id); name(attempt_id)
        key = profile_digest(dict(scope=self.scope,task=task_id))
        with self.ledger.transaction() as data:
            record = data.get('handoffs',{}).get(key)
            require(record is not None, 'handoff_missing')
            if record['claim_attempt'] is not None:
                require(record['claim_attempt'] == attempt_id, 'handoff_already_claimed')
                return dict(record,new_claim=False)
            config = self._config(data)
            require(config['revision'] == record['revision'] and not config['disabled'], 'consent_changed')
            require(record['state'] == 'ready', 'handoff_not_ready')
            key_native = self.ledger._native(data,record['native'],self.clock())
            data['native'][key_native]['latest_at'] = self.clock()
            record.update(state='claimed',claim_attempt=attempt_id)
            return dict(record,new_claim=True)

    def _transmit(self, operation, packet, binding, dispatch, factory, run_id, revision, resolver,
                  live_gate=None, final_check=None):
        from runtime import openai_api

        def dispatch_gate(state, _):
            # Recheck local scope after acquiring the dispatch transaction.
            # Credential lookup and connection preparation stay outside it.
            final_check()
            now = self.clock()
            require(now < dispatch['deadline'], 'evidence_deadline_expired')
            return live_gate(state, now)

        def admit():
            # The final grant is atomic. Disable after it sees accounted work.
            require(self.clock() < dispatch['deadline'], 'evidence_deadline_expired')
            self.ledger.dispatch(run_id, dispatch['phase'], revision, self.clock(),
                                 live_gate=dispatch_gate if live_gate is not None else None)

        require(self.clock() < dispatch['deadline'], 'evidence_deadline_expired')
        if live_gate is not None or resolver is not None:
            return openai_api._authenticated_call(
                packet, binding, dispatch, dispatch['phase'], admit=admit,
                connection_factory=factory, resolver=resolver)
        try:
            connection = factory('api.openai.com', min(300,dispatch['deadline']-self.clock()))
        except Exception:
            raise openai_api.TransportError('transport_failure',uncertain=False) from None
        try:
            admit()
            return operation(packet,binding,dispatch,connection_factory=lambda host,timeout: connection)
        finally:
            try: connection.close()
            except Exception: pass

    def run_shadow(self, task, *, connection_factory=None, credential_resolver=None):
        """Exercise the admitted protocol with explicit connection and credential fixtures."""
        require(callable(connection_factory), 'live_execution_unavailable')
        require(credential_resolver is None or callable(credential_resolver), 'invalid_credential_fixture')
        return self._run(task, connection_factory, credential_resolver)

    def _stage_live(self, data, task, evidence, now):
        from dataclasses import asdict
        from runtime import usage_admission

        config = self._config(data)
        org = data['organizations'][config['binding']['organization']]
        require(config['org_revision'] == org['revision'], 'policy_revision_changed')
        deadline = usage_admission.validate(evidence, scope=self.scope, config=config,
                                            policy=org['policy'], task=task, now=now)
        grant = evidence.grant
        current = dict(observed_at=grant.observed_at, digest=usage_admission.digest(asdict(grant)))
        previous = org.get('live_funding')
        require(previous is None or current == previous or
                current['observed_at'] > previous['observed_at'], 'live_grant_observation_changed')
        # Prior shadow observations can only lower the usable balance. The first
        # trusted observation establishes a floor even if shadow data set one.
        balance = org['balance']
        org['balance'] = grant.balance if balance is None else min(balance, grant.balance)
        if previous is None or previous['digest'] is None:
            org['floor'] = max(org['floor'] or 0, (grant.balance + 4) // 5)
        org['observed_at'] = max(org['observed_at'] or 0, grant.observed_at)
        org['live_funding'] = current
        return deadline, dict(pin=usage_admission.digest(asdict(evidence)),
                              maximum=evidence.maximum_usd_micros)

    def _run_live(self, task, evidence, *, scope_check=None,
                  connection_factory=None, credential_resolver=None):
        """Trusted host entry. This is intentionally absent from the JSON CLI."""
        from runtime import usage_admission

        require(type(evidence) is usage_admission.Admission, 'trusted_live_evidence_required')
        require(type(task) is dict, 'invalid_task')
        require((connection_factory is None) == (credential_resolver is None),
                'invalid_transport_dependencies')
        require(connection_factory is not None or callable(scope_check), 'live_scope_check_required')
        if scope_check is not None:
            scope_check()
        return self._run(task, connection_factory, credential_resolver, evidence, scope_check)

    def _run(self, task, connection_factory, credential_resolver, evidence=None, scope_check=None):
        import copy
        from runtime import openai_api

        task = copy.deepcopy(task)
        data = self.ledger.snapshot()
        existing = data['runs'].get(task.get('run_id'))
        if existing is not None:
            require(evidence is None, 'live_run_id_already_used')
            require(existing.get('consent', {}).get('scope') == self.scope and
                    existing['digest'] == openai_api.packet_digest(task['packet']) and
                    existing['task'] == task['task_id'], 'run_identity_changed')
            return dict(replayed=True, simulation_only=True, accepted=False,
                        requires_native_review=True, state=existing['calls'])
        live_gate = final_check = None
        if evidence is None:
            decision = self.evaluate(task)
            data = self.ledger.snapshot()
        else:
            # Keep a newer lower balance even when it rules out the request.
            # Otherwise an older proof could still allocate the depleted pool.
            denial = None
            with self.ledger.transaction() as data:
                try:
                    deadline, _ = self._stage_live(data, task, evidence, self.clock())
                except BudgetError as error:
                    if str(error) not in ('expiry_changed', 'live_grant_observation_changed'):
                        raise
                    # A fresh, identity-checked conflicting row retires prior
                    # evidence. Resume only from a newer usable observation.
                    org = data['organizations'][evidence.grant.organization]
                    previous = org.get('live_funding')
                    observed_at = evidence.grant.observed_at
                    if previous is None or observed_at >= previous['observed_at']:
                        org['live_funding'] = dict(observed_at=observed_at, digest=None)
                    denial = error
            if denial is not None:
                raise denial
            decision = self._evaluate(data, task)

            def live_gate(state, now):
                return self._stage_live(state, task, evidence, now)[1]

            def final_check():
                if scope_check is not None:
                    scope_check()
                self._snapshots(task['snapshots'])

        require(decision['decision'] == 'eligible', decision['reason'])
        config = self._config(data)
        require(decision['consent'] == dict(scope=self.scope, revision=config['revision'],
                qualification_revision=config['qualification_revision']), 'consent_changed')
        binding, profile, packet = config['binding'], config['profile'], task['packet'].copy()
        now = self.clock(); org_id = binding['organization']; run_id = task['run_id']
        if evidence is None:
            deadline = min(now+300, profile['valid_until'],
                           data['organizations'][org_id]['policy']['stop_at'],
                           min(min(w['reset_at'],w['observed_at']+900) for w in task['native']['windows']),
                           config['qualification']['valid_until'] if config['requested_mode'] == 'smart' else profile['valid_until'])
        else:
            deadline = min(deadline, now + 300)
        packet_id = openai_api.packet_digest(packet)
        self.ledger.begin(org_id, task['task_id'], run_id, packet_id, profile['count_maximum'],
                          config['org_revision'], now, task['native'],
                          consent=decision['consent'], live_gate=live_gate)
        phase = 'count'
        try:
            dispatch = dict(phase=phase, attempt_id=run_id+':'+phase, packet_digest=packet_id,
                            committed=True, deadline=deadline)
            counted = self._transmit(openai_api.count, packet, binding, dispatch, connection_factory,
                                     run_id, config['org_revision'], credential_resolver, live_gate, final_check)
            self.ledger.complete(run_id, phase, profile['count_maximum'])
            packet['input_tokens'] = counted['input_tokens']
            bound = quote(packet, profile, self.clock())
            self._snapshots(task['snapshots'])
            packet_id = openai_api.packet_digest(packet)
            self.ledger.reserve_generation(run_id, packet_id, bound['maximum_usd_micros'],
                                           config['org_revision'], self.clock(), live_gate=live_gate)
            phase = 'generation'
            dispatch.update(phase=phase, attempt_id=run_id+':'+phase, packet_digest=packet_id)
            result = self._transmit(openai_api.generate, packet, binding, dispatch, connection_factory,
                                    run_id, config['org_revision'], credential_resolver, live_gate, final_check)
            require(result['input_tokens'] == counted['input_tokens'], 'counted_input_changed')
            used = dict(packet, input_tokens=result['input_tokens'], max_output_tokens=result['output_tokens'])
            # Use conservative rates; retain local charge even if provider balance includes it.
            if result['output_tokens'] == 0:
                raise BudgetError('incomplete_output')
            actual = quote(used, profile, self.clock())['maximum_usd_micros']
            self.ledger.complete(run_id, phase, actual)
            return dict(simulation_only=connection_factory is not None, accepted=False, requires_native_review=True,
                        text=result['text'], request_id=result['request_id'], run_id=run_id,
                        execution_route='openai-api',
                        reported_cost_usd_micros=actual, profile_digest=profile_digest(profile))
        except BaseException as error:
            record = self.ledger.snapshot()['runs'][run_id]['calls'].get(phase)
            if record and record['state'] == 'dispatching':
                if isinstance(error, openai_api.TransportError) and not error.uncertain:
                    self.ledger.reject_unsent(run_id, phase)
                else:
                    incomplete = error.incomplete if isinstance(error, openai_api.TransportError) else None
                    self.ledger.uncertain(run_id, phase, incomplete=incomplete)
            elif not any(c['state'] in ('dispatching','unresolved')
                         for c in self.ledger.snapshot()['runs'][run_id]['calls'].values()):
                self.ledger.close_run(run_id)
            raise


def configure(cwd, request):
    from runtime.usage_settings import controller
    with controller(cwd, create=True) as control:
        return control.configure(request)


def disable(cwd, request):
    from runtime.usage_settings import controller
    fields(request, 'expected_revision')
    with controller(cwd) as control:
        return control.disable(request['expected_revision'])


def evaluate(cwd, task):
    from runtime.usage_settings import controller
    try:
        with controller(cwd) as control:
            return control.evaluate(task)
    except (BudgetError, OSError, KeyError, TypeError, ValueError):
        return dict(decision='paused', reason='configuration_or_scope_unavailable',
                    simulation_only=True, live_blocker='live_adapter_unavailable')


def reconcile(cwd, request):
    from runtime.usage_settings import controller
    fields(request, '')
    with controller(cwd) as control:
        return control.ledger.reconcile(scope=control.scope)


def handoff(cwd, request):
    from runtime.usage_settings import controller
    fields(request, 'task reason')
    with controller(cwd) as control:
        return control.request_handoff(request['task'], request['reason'])


def claim_handoff(cwd, request):
    from runtime.usage_settings import controller
    fields(request, 'task_id attempt_id')
    with controller(cwd) as control:
        return control.claim_handoff(request['task_id'], request['attempt_id'])
