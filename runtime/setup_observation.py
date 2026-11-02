"""Owned setup observations retained by D4; routine reads use local files only.

The coordinator independently verifies semantic evidence before passing it here.
Journal origin is a cooperative code-path contract, not same-user forgery defense.
"""

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import time
import tomllib
from types import SimpleNamespace

from runtime import onboarding as d3, startup


BEHAVIOR_CASES = ('startup-context', 'pre-tool-enforcement', 'post-tool-handling',
    'stop-ownership', 'interrupt-ownership', 'adoption', 'review-readiness', 'repository-gate', 'recovery')
_ISSUER = object()
_FEATURES = ('hooks', 'codex_hooks', 'plugins', 'remote_plugin')
_EVENTS = ('SessionStart', 'PreToolUse', 'PostToolUse', 'Stop', 'Interrupt')
OPERATION_CAPABILITIES = {
    'observe-cli-basic': ('startup-context',),
    'observe-setup-metadata': ('startup-context',),
    'task-start': ('pre-tool-enforcement',), 'task-patch': ('pre-tool-enforcement',),
    'task-continue': ('stop-ownership',),
    'check-run': ('review-readiness',), 'verify-completion': ('review-readiness',), 'verify-merge': ('review-readiness',),
    'native-worker': ('post-tool-handling','stop-ownership','interrupt-ownership'),
    'delegation-continue': ('post-tool-handling','stop-ownership','interrupt-ownership'),
    'native-review': ('post-tool-handling','stop-ownership','interrupt-ownership','review-readiness'),
    'operation-coordinator': ('pre-tool-enforcement',), 'task-ready': ('full-onboarding',),
    'gate-ready': ('review-readiness','repository-gate','full-onboarding'),
    'delivery-ready': ('review-readiness','repository-gate','full-onboarding'),
    'delivery-merge': ('review-readiness','repository-gate','full-onboarding'),
}


@dataclass(frozen=True)
class _SetupObservation:
    content: object
    issuer: object


@dataclass(frozen=True)
class _CapabilityAdmission:
    mode: str
    capability_keys: tuple
    qualification_ref: object
    attempt_ref: object
    issuer: object
    limits: object = None
    original_attempt: object = None
    operation: str | None = None
    _owner: object = None
    _process: object = None


def qualification_attempt_projection(decision, *, operation=None, case_id, process=None):
    d3._require(isinstance(decision,_CapabilityAdmission) and decision.issuer is _ISSUER
        and decision.mode == 'qualification' and decision.original_attempt is not None,
        'An actual owner-issued qualification admission is required')
    projection = startup._canonical_plain(decision.original_attempt)
    attempt = projection['attempt']
    operation = decision.operation if operation is None else operation
    d3._require(operation == decision.operation and operation in OPERATION_CAPABILITIES and operation in attempt['operations']
        and case_id in attempt['capability_keys'] and attempt['limits']['deadline'] > time.time(),
        'Original qualification operation is unavailable or expired')
    if process is not None:
        context = getattr(decision._owner,'_setup_context',None)
        d3._require(decision._process is process and context is not None and context['process'] is process
            and context['attempt_ref'] == startup._canonical_plain(decision.attempt_ref),
            'Frontend observation requires the exact active D4-owned process')
    return decision.original_attempt


def _projection_shape(value):
    d3._object(value, ('reference', 'verified', 'complete'))
    startup._canonical_ref(value['reference'])
    d3._require(type(value['complete']) is bool and isinstance(value['verified'], (list, tuple))
        and len(set(value['verified'])) == len(value['verified']) and set(value['verified']) <= set(BEHAVIOR_CASES),
        'Invalid retained capability projection')


def _budget(deadline=None):
    return dict(paths=0, bytes=0, deadline=deadline if deadline is not None else time.monotonic()+4)


def _read(path, budget, *, absent=False, private=False, limit=d3.MAX_FILE):
    startup._entry_budget_check(budget)
    budget['paths'] += 1
    d3._no_links(path)
    try:
        raw = d3._read_file(path, min(limit, d3.MAX_TOTAL-budget['bytes']-1), private=private)
    except FileNotFoundError:
        if absent:
            return None
        raise
    budget['bytes'] += len(raw)
    startup._entry_budget_check(budget)
    return raw


def _children(path, budget):
    entries = []
    for entry in path.iterdir():
        startup._entry_budget_check(budget)
        budget['paths'] += 1
        startup._entry_budget_check(budget)
        entries.append(entry)
    return entries


def plugin_content_hash(root, budget):
    """Codex's bounded codex-plugin-bundle-v1 fingerprint, including directory names."""
    root = Path(root)
    pending = [root]
    digest = hashlib.sha256(b'codex-plugin-bundle-v1')
    while pending:
        startup._entry_budget_check(budget)
        path = pending.pop()
        if path != root and (path.name in ('__pycache__', '.venv') or path.name.endswith(('.pyc', '.egg-info'))):
            continue
        budget['paths'] += 1
        relative = os.fsencode(str(path.relative_to(root))) if path != root else b''
        digest.update(len(relative).to_bytes(8, 'little')); digest.update(relative)
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            digest.update(b'directory')
            pending.extend(sorted(_children(path, budget), key=lambda item: os.fsencode(item.name), reverse=True))
        else:
            d3._require(stat.S_ISREG(info.st_mode), 'Unsupported plugin source entry')
            raw = _read(path, budget)
            d3._require(len(raw) == info.st_size, 'Plugin contents changed during setup observation')
            digest.update(b'file'); digest.update(info.st_size.to_bytes(8, 'little')); digest.update(raw)
    startup._entry_budget_check(budget)
    return 'sha256:' + digest.hexdigest()


def _runtime_digest(package, budget):
    from runtime import state
    digest = hashlib.sha256()
    for source in state._runtime_sources():
        relative = source.relative_to(state.PACKAGE)
        digest.update(str(relative).encode()+b'\0'+_read(package/relative, budget)+b'\0')
    return digest.hexdigest()


def _projection(value, config, *, user=False):
    d3._require(isinstance(value, dict), 'Observable configuration is not an object')
    result = {}
    features = value.get('features') or {}
    d3._require(isinstance(features, dict), 'Unsupported hook feature configuration')
    selected = {key: features[key] for key in _FEATURES if key in features and features[key] is not None}
    if selected:
        result['features'] = selected
    plugins = value.get('plugins') or {}
    d3._require(isinstance(plugins, dict), 'Unsupported plugin configuration')
    selected = {key: {field: plugins[key][field] for field in ('enabled', 'remote_plugin_id', 'release_id')
        if field in plugins[key]} for key in ('_default', config['plugin_id']) if key in plugins}
    if selected:
        result['plugins'] = selected
    marketplaces = value.get('marketplaces') or {}
    d3._require(isinstance(marketplaces, dict), 'Unsupported marketplace configuration')
    if config['plugin_id'].split('@')[1] in marketplaces:
        result['marketplace'] = d3._digest(marketplaces[config['plugin_id'].split('@')[1]])
    hooks = value.get('hooks') or {}
    d3._require(isinstance(hooks, dict), 'Unsupported hook configuration')
    declarations = {key: hooks[key] for key in _EVENTS if key in hooks}
    if declarations:
        result['hook_declarations'] = d3._digest(declarations)
    if user:
        states = hooks.get('state') or {}
        d3._require(isinstance(states, dict), 'Unsupported hook approval configuration')
        selected = {key: {field: states[key][field] for field in ('enabled', 'trusted_hash', 'trusted_content_hash')
            if field in states[key]} for key in config['keys'] if key in states}
        if selected:
            result['hook_state'] = selected
    projects = value.get('projects') or {}
    d3._require(isinstance(projects, dict) and all(isinstance(entry, dict) for entry in projects.values()), 'Unsupported project trust configuration')
    selected = {key: entry.get('trust_level') for key, entry in projects.items() if Path(key).is_absolute()
        and any(Path(root).is_relative_to(Path(key)) or Path(key).is_relative_to(Path(root)) for root in config['roots'])}
    if selected:
        result['project_trust'] = selected
    for key in ('project_root_markers', 'allow_managed_hooks_only'):
        if value.get(key) is not None:
            result[key] = value[key]
    # Requirements use their own marketplace schema; keep its relevant policy as a digest.
    if value.get('marketplaces') and 'restrict_to_allowed_sources' in marketplaces:
        result['marketplace_requirements'] = d3._digest(marketplaces)
    requirements = value.get('feature_requirements') or {}
    d3._require(isinstance(requirements, dict), 'Unsupported hook feature requirement')
    selected = {key: requirements[key] for key in _FEATURES if key in requirements}
    if selected:
        result['feature_requirements'] = selected
    return result


def _configuration_files(config, cwd):
    files = {item['path']: item for item in config['files']}
    cwd = startup._canonical_path(str(cwd))
    selected = Path(config['roots'][0])
    d3._require(cwd.is_relative_to(selected), 'Configuration observation left its selected checkout')
    for root in {selected, Path(config['roots'][-1]), cwd, *[p for p in cwd.parents if p.is_relative_to(selected)]}:
        for name, kind in (('config.toml', 'toml'), ('hooks.json', 'json')):
            path = str(root/'.codex'/name)
            files[path] = dict(path=path, kind=kind, user=False)
    return [files[key] for key in sorted(files)]


def current_configuration(config, cwd, budget=None, *, bundle_budget=None):
    """Compare captured local inputs; never query native processes or reconstruct precedence."""
    budget = budget if budget is not None else _budget()
    observed = []
    for item in _configuration_files(config, cwd):
        raw = _read(Path(item['path']), budget, absent=True)
        value = {} if raw is None else tomllib.loads(raw.decode()) if item['kind'] == 'toml' else startup.json_object(raw)
        observed.append(dict(path=item['path'], values=_projection(value, config, user=item['user'])))
    root = Path(config['package_root']); source = root/'hooks/codex.json'
    hook_owner = dict(root=str(root), binding=d3._filesystem_binding(root), source=str(source),
        sha256=hashlib.sha256(_read(source, budget)).hexdigest())
    scan = bundle_budget if bundle_budget is not None else budget
    scan['paths'] = budget['paths']
    bundle = plugin_content_hash(root, scan)
    versions = sorted(p.name for p in _children(root.parent, scan) if p.is_dir())
    budget['paths'] = scan['paths']
    material = dict(files=observed, bundle=bundle, installation_versions=versions)
    return dict(digest=d3._digest(material), hook_owner=hook_owner, material=material)


def _assessment(value, *, staged=False):
    from runtime.changes import _evidence
    value = startup._canonical_copy(value)
    d3._object(value, ('cases', 'requirements', 'general_review', 'security_review', 'semantic_assessment'))
    d3._require(isinstance(value['cases'], list) and len(value['cases']) == len(BEHAVIOR_CASES), 'Complete setup behavior matrix is required')
    seen = set()
    for row in value['cases']:
        d3._object(row, ('id', 'status', 'evidence') if staged else ('id', 'evidence'), ('reason',) if staged else ())
        d3._require(row['id'] in BEHAVIOR_CASES and row['id'] not in seen, 'Unknown or duplicate setup behavior')
        if staged:
            _outcome(row)
        else:
            d3._require(_evidence(row['evidence'], many=True), 'Missing independent semantic behavior evidence')
        seen.add(row['id'])
    seen = set()
    d3._require(isinstance(value['requirements'], list) and len(value['requirements']) <= 4096, 'Bounded mandatory adoption evidence is required')
    for row in value['requirements']:
        d3._object(row, ('id', 'status', 'evidence') if staged else ('id', 'evidence'), ('reason',) if staged else ())
        d3._require(isinstance(row['id'], str) and row['id'] and row['id'] not in seen, 'Unknown or duplicate mandatory adoption requirement')
        if staged:
            _outcome(row)
        else:
            d3._require(_evidence(row['evidence'], many=True), 'Missing mandatory adoption evidence')
        seen.add(row['id'])
    d3._require(_evidence(value['general_review'], many=True) and isinstance(value['security_review'], list), 'Independent review evidence is required')
    _evidence(value['security_review'], many=True)
    d3._require(isinstance(value['semantic_assessment'], dict) and all(value['semantic_assessment'].get(key) is True for key in
        ('complete', 'catalog_complete', 'conflicts_checked', 'instructions_checked', 'source_provenance_checked')), 'Complete semantic adoption assessment is required')
    return value


def _outcome(row):
    from runtime.changes import _evidence
    d3._require(row['status'] in ('pending', 'verified', 'inapplicable'), 'Unknown qualification outcome')
    evidence = _evidence(row['evidence'], many=True)
    d3._require(row['status'] == 'pending' or evidence, 'Qualification outcome needs independent evidence')
    if row['status'] == 'inapplicable':
        startup._canonical_text(row.get('reason'), 4096)


def _coverage(content):
    assessment = content['assessment']
    if content['version'] == 1:
        return list(BEHAVIOR_CASES), True
    verified = [row['id'] for row in assessment['cases'] if row['status'] == 'verified']
    complete = all(row['status'] in ('verified', 'inapplicable')
        for row in [*assessment['cases'], *assessment['requirements']])
    return verified, complete


def collect_setup(witness, accepted_identity, transaction_id, verified_assessment, *, predecessor=None):
    """Consume Native's genuine frontend witness, never labels or fabricated hook pairs.

    Witness capture is a setup operation: native hooks/list may initialize trust
    baselines for enumerated plugins. Routine qualification reads local files only.
    """
    from runtime.doctor import _native_witness_content, ObservationError, inspect_hooks
    from runtime.state import _accepted_identity
    try:
        observed = _native_witness_content(witness)
    except ObservationError:
        raise startup.StartupError('Actual owned frontend setup witness is required') from None
    return _collect_content(observed,accepted_identity,transaction_id,verified_assessment,predecessor=predecessor)


def _collect_content(observed, accepted_identity, transaction_id, verified_assessment, *, predecessor=None, capture_reference=None):
    from runtime.doctor import inspect_hooks
    from runtime.state import _accepted_identity
    identity = _accepted_identity(accepted_identity)
    d3._require(identity['client'] == 'codex', 'Only the Codex local setup source is supported')
    binding = observed['binding']
    d3._object(binding, ('accepted_scope_digest','attempt_ref','transaction_id'))
    d3._require(binding['accepted_scope_digest'] == d3._digest(identity)
        and (capture_reference is not None or binding['transaction_id'] == transaction_id),
        'Native witness belongs to another setup operation or scope')
    startup._canonical_ref(binding['attempt_ref'])
    native = observed['native']
    d3._require(native['surface'] == 'codex-cli', 'This setup source does not qualify the selected frontend')
    startup._canonical_text(native['version'],128)
    root = startup._canonical_path(identity['repository_root'])
    package = startup._canonical_path(observed['package_root']);budget = _budget()
    assessment = _assessment(verified_assessment,staged=True)
    from runtime.changes import _evidence
    d3._require(_evidence(observed['bootstrap'],many=True) and isinstance(observed['observations'],dict),
        'Genuine frontend bootstrap observations are missing')
    d3._require(set(observed['observations']) <= set(BEHAVIOR_CASES), 'Unknown frontend behavior claim')
    observations = dict(observed['observations'])
    if predecessor is not None:
        previous, _ = _retained_reference(predecessor,budget)
        d3._require(previous['identity'] == identity, 'Successor frontend observation changed original accepted scope')
        _monotonic_coverage(previous,dict(version=2,assessment=assessment))
        for row in previous.get('assessment',{}).get('cases',[]):
            if row.get('status','verified') == 'verified':
                observations.setdefault(row['id'],previous.get('source',{}).get('observations',{}).get(row['id'],row['evidence']))
    for case in assessment['cases']:
        actual = observations.get(case['id'],[])
        _evidence(actual,many=True)
        if case['status'] == 'verified':
            d3._require(actual and all(proof in case['evidence'] for proof in actual),
                'A verified behavior lacks its actual frontend observations')
    d3._require(identity['configuration']['policy_digest'] == startup.policy_digest(package, budget=budget)
        and identity['configuration']['runtime_digest'] == _runtime_digest(package, budget), 'Setup candidate policy/runtime identity differs')
    d3._require(d3._filesystem_binding(Path(identity['project_root'])) == identity['project_binding']
        and all(d3._filesystem_binding(Path(identity['repository_root' if key == 'root' else key])) == binding
            for key, binding in identity['bindings'].items()), 'Setup physical project/checkout identity differs')
    for dependency in identity['shared_policy']:
        d3._require(hashlib.sha256(_read(Path(dependency['path']), budget)).hexdigest() == dependency['sha256'], 'Setup shared instruction source differs')
    definitions = startup.json_object(_read(package/'hooks/codex.json', budget))['hooks']
    listed = observed['hooks']
    d3._require(inspect_hooks(listed, SimpleNamespace(repository_root=root), definitions, package=package)['status'] == 'passed', 'Actual native hook registration is unqualified')
    entries = [row for row in listed['data'][0]['hooks'] if row['sourcePath'] == str(package/'hooks/codex.json')]
    d3._require(not any(row.get('isManaged') for row in listed['data'][0]['hooks']), 'Managed hook sources are outside this personal setup source')
    plugin_ids = {row.get('pluginId') for row in entries}
    d3._require(len(plugin_ids) == 1 and isinstance(next(iter(plugin_ids)), str), 'Actual plugin identity is missing')
    plugin_id = next(iter(plugin_ids))
    d3._require(plugin_id.count('@') == 1 and not plugin_id.split('@')[1].startswith('openai-'), 'Only an explicit personal local plugin is supported')
    config = dict(package_root=str(package), codex_home=observed['codex_home'], plugin_id=plugin_id,
        roots=[str(root), identity['primary_root']], keys=sorted(row['key'] for row in entries), files=[])
    layers = observed['layers']
    d3._require(isinstance(layers, list) and 0 < len(layers) <= 64, 'Native configuration origins are unavailable')
    expected = {}; user_layers = []; system_files = []
    for layer in layers:
        name = layer['name']; kind = name['type']; value = layer['config']; user = kind == 'user'
        projection = _projection(value, config, user=kind in ('user', 'sessionFlags'))
        if kind in ('system', 'user', 'packagedDefaults', 'legacyManagedConfigTomlFromFile'):
            path = startup._canonical_path(name['file'])
        elif kind == 'project':
            path = startup._canonical_path(name['dotCodexFolder'])/'config.toml'
        else:
            d3._require(not projection, 'A required configuration origin is not file-backed')
            continue
        d3._require(projection.get('project_root_markers', ['.git']) == ['.git'], 'Custom project discovery is not qualified by this local source')
        config['files'].append(dict(path=str(path), kind='toml', user=user))
        expected[str(path)] = projection
        if user:user_layers.append(projection)
        if kind == 'system':system_files.append(path)
    d3._require(user_layers and len(system_files) == 1, 'User and system configuration origins must be observed')
    for path in (Path(config['codex_home'])/'hooks.json', system_files[0].parent/'hooks.json'):
        config['files'].append(dict(path=str(path), kind='json', user=False))
    for name in ('requirements.toml', 'managed_config.toml'):
        config['files'].append(dict(path=str(system_files[0].parent/name), kind='toml', user=False))
    requirements = observed['requirements'] or {}
    relevant = dict(feature_requirements=requirements.get('featureRequirements'),
        allow_managed_hooks_only=requirements.get('allowManagedHooksOnly'), hooks=requirements.get('hooks'),
        marketplaces=requirements.get('marketplaces'))
    d3._require(not _projection(relevant, config), 'Managed hook/plugin requirements are outside this personal setup source')
    current = current_configuration(config, root, budget)
    observed_files = {item['path']: item['values'] for item in current['material']['files']}
    d3._require(all(observed_files.get(path) == projection for path, projection in expected.items()), 'Native origins differ from their actual local files')
    d3._require(all(not observed_files[str(system_files[0].parent/name)] for name in ('requirements.toml', 'managed_config.toml')), 'Unmapped local requirements prevent personal activation')
    approvals = {}
    for layer in reversed(user_layers):
        for key, value in layer.get('hook_state', {}).items():approvals.setdefault(key, {}).update(value)
    for entry in entries:
        approval = approvals.get(entry['key'], {})
        d3._require(entry['currentHash'] == approval.get('trusted_hash', '')+'/'+approval.get('trusted_content_hash', '')
            and approval.get('trusted_content_hash') == current['material']['bundle'], 'Modern persisted plugin content approval is required')
    config.update(digest=current['digest'], hook_owner=current['hook_owner'])
    content = dict(version=2, kind='owner-observed-setup', transaction_id=transaction_id, identity=identity,
        native=native, configuration=config, runs=[], assessment=assessment, predecessor=predecessor,
        source=dict(binding=binding,bootstrap=observed['bootstrap'],observations=observations,
            pending_reason=observed['pending_reason']))
    if capture_reference is not None:content['source']['capture_reference'] = capture_reference
    d3._bounded(content)
    return _SetupObservation(startup._canonical_freeze(content), _ISSUER)


def _issued(observation):
    d3._require(isinstance(observation, _SetupObservation) and observation.issuer is _ISSUER, 'Owner-issued native setup source is required')
    return startup._canonical_plain(observation.content)


def _reference(content, directory):
    return dict(reference=str(Path(directory)/'transaction.json')+'#setup:'+d3._digest(content['identity']), sha256=d3._digest(content))


def _binding(content, directory):
    config = content['configuration']
    return dict(client=content['identity']['client'], surface=content['native']['surface'], version=content['native']['version'],
        configuration_digest=config['digest'], hook_owner=config['hook_owner'],
        accepted_scope_digest=d3._digest(content['identity']), receipt=_reference(content, directory))


def receipt_binding(observation, directory):
    return _binding(_issued(observation), directory)


def receipt_shape(content):
    d3._bounded(content)
    d3._object(content, ('version', 'kind', 'transaction_id', 'identity', 'native', 'configuration', 'runs', 'assessment'), ('predecessor', 'source'))
    d3._require(type(content['version']) is int and content['version'] in (1, 2) and content['kind'] == 'owner-observed-setup', 'Invalid original setup receipt')
    _assessment(content['assessment'], staged=content['version'] == 2)
    if content['version'] == 2:
        d3._require('predecessor' in content, 'Successor source must retain its original predecessor')
        if content['predecessor'] is not None:
            startup._canonical_ref(content['predecessor'])
            d3._require('#setup:' in content['predecessor']['reference'],'Setup predecessor must name a full retained setup receipt')
        source = content['source']
        d3._object(source, ('binding','observations','bootstrap','pending_reason'), ('capture_reference','command_origins','command_origin','source_capture'))
        d3._object(source['binding'], ('accepted_scope_digest','attempt_ref','transaction_id'))
        d3._require(source['binding']['accepted_scope_digest'] == d3._digest(content['identity'])
            and (source['binding']['transaction_id'] == content['transaction_id'] or 'capture_reference' in source),
            'Original frontend witness binding differs')
        if 'capture_reference' in source:
            startup._canonical_ref(source['capture_reference'])
            d3._require(content['predecessor'] == source['capture_reference'],'Original native capture provenance differs')
        if 'source_capture' in source:
            startup._canonical_ref(source['source_capture'])
            d3._require('#command-capture:' in source['source_capture']['reference'],'Original CLI source is not its command capture')
        startup._canonical_ref(source['binding']['attempt_ref'])
        from runtime.changes import _evidence
        d3._require(_evidence(source['bootstrap'],many=True) and isinstance(source['observations'],dict)
            and set(source['observations']) <= set(BEHAVIOR_CASES), 'Original frontend observation source is missing')
        for row in content['assessment']['cases']:
            proofs = source['observations'].get(row['id'],[])
            _evidence(proofs,many=True)
            d3._require(row['status'] != 'verified' or proofs and all(proof in row['evidence'] for proof in proofs),
                'Verified behavior lost its genuine frontend observation')
    else:
        d3._require('predecessor' not in content and 'source' not in content, 'Original setup history cannot be rewritten')
    d3._require(content['identity']['client'] == 'codex' and content['native']['surface'] == 'codex-cli', 'Unsupported original setup scope')
    startup._canonical_text(content['transaction_id'], 128)
    startup._canonical_hash(content['configuration']['digest']); startup._canonical_hook(content['configuration']['hook_owner'])


def _retained_reference(reference, budget):
    from runtime import changes
    startup._canonical_ref(reference)
    path, separator, name = reference['reference'].partition('#setup:')
    pointer = startup._canonical_path(path)
    d3._require(separator and pointer.name == 'transaction.json', 'Setup source is not its retained D4 journal')
    d3._private(pointer.parent.stat(), directory=True)
    journal = d3.read_request(_read(pointer, budget, private=True, limit=changes.MAX_JOURNAL), changes.MAX_JOURNAL)
    changes._scoped_journal_shape(journal)
    d3._require(journal['state'] == 'applied' and not journal['blocked'] and journal['enrollment'] is not None
        and any(row['phase'] == 'final' for row in journal['enrollment']['postimages']), 'Original setup operation did not complete')
    content = journal.get('setup_receipts', {}).get(name)
    d3._require(content is not None and reference == _reference(content, pointer.parent)
        and name == d3._digest(content['identity']) and content['transaction_id'] == journal['transaction_id'],
        'Setup source no longer matches its original journal')
    if content.get('source',{}).get('command_origin') is not None and 'capture_reference' not in content['source']:
        _stopped_source(journal,content['source']['command_origin'])
    if content.get('source',{}).get('source_capture') is not None:
        original,prior=_retained_capture(content['source']['source_capture'],budget)
        d3._require(_capture_identity(original,prior)==content['identity'],'Original CLI capture changed accepted scope')
    return content, journal


def _capture_shape(capture):
    d3._object(capture, ('version','origin','witness','launch'), ('source_capture',))
    d3._require(type(capture['version']) is int and capture['version'] == 1,'Unknown original native capture')
    d3._object(capture['origin'], ('transaction_id','action_id','attempt_id'))
    for value in capture['origin'].values():startup._canonical_text(value,128)
    d3._object(capture['launch'],('command_digest','cwd','codex_home','configuration_overrides_present'))
    startup._canonical_hash(capture['launch']['command_digest'])
    d3._require(type(capture['launch']['configuration_overrides_present']) is bool,'Unknown CLI launch configuration scope')
    startup._canonical_path(capture['launch']['cwd']);startup._canonical_path(capture['launch']['codex_home'])
    witness = capture['witness']
    d3._object(witness, ('binding','package_root','native','codex_home','hooks','layers','requirements','observations','bootstrap','pending_reason'))
    d3._object(witness['binding'], ('accepted_scope_digest','attempt_ref','transaction_id'))
    startup._canonical_hash(witness['binding']['accepted_scope_digest']);startup._canonical_ref(witness['binding']['attempt_ref'])
    d3._require(witness['binding']['transaction_id'] == capture['origin']['transaction_id'],'Native capture transaction differs')
    d3._require(all(witness[key] is None for key in ('hooks','layers','requirements')) and witness['observations'] == {},
        'Only the minimal native CLI fragment may be retained before filtering')
    if 'source_capture' in capture:startup._canonical_ref(capture['source_capture'])


def _capture_reference(directory,capture):
    origin=capture['origin']
    return dict(reference=str(Path(directory)/'transaction.json')+'#command-capture:'+origin['action_id']+':'+origin['attempt_id'],
        sha256=d3._digest(capture))


def _capture_identity(capture,journal):
    from runtime import changes
    record=journal['manifest']['enrollment']['record'];matches=[]
    for key in changes._scoped_entries(record):
        identity=startup._canonical_plain(startup.canonical_scope_projection(startup.decode_project_record(record),
            repository_id=key[0],checkout_id=key[1],client=key[2]))
        if d3._digest(identity) == capture['witness']['binding']['accepted_scope_digest']:matches.append(identity)
    d3._require(len(matches)==1,'Original native capture has no exact approved member')
    return matches[0]


def persist_capture(directory,journal,witness,action_id,attempt_id, *, process):
    """Only the actual D4 callback retains its privately issued Native witness."""
    from runtime import changes,doctor
    command=journal['receipts'][action_id]
    d3._require(command['command']==dict(attempt_id=attempt_id,stopped=False),'Native capture lost its original command claim')
    origin=dict(transaction_id=journal['transaction_id'],action_id=action_id,attempt_id=attempt_id)
    if isinstance(witness,_SetupObservation):
        content=_issued(witness);receipt_shape(content)
        authority=_authorization_shape(journal.get('qualification_scope'))
        allocation=next((row for row in authority['attempts'] if row['reference']==content['source']['binding']['attempt_ref']),None)
        d3._require(allocation is not None and allocation['operations']==['observe-setup-metadata']
            and allocation['command_action']==action_id and content['transaction_id']==journal['transaction_id']
            and content['predecessor'] is None, 'Filtered metadata source lost its original command/CLI binding')
        original,prior=_retained_capture(allocation['source_capture'],_budget())
        d3._require(_capture_identity(original,prior)==content['identity']
            and content['configuration']['codex_home']==original['launch']['codex_home']
            and str(process.launch_cwd)==original['launch']['cwd']
            and process.launch_codex_home==original['launch']['codex_home']
            and content['native']['executable']==original['witness']['native']['executable']
            and content['configuration']['package_root']==original['witness']['package_root'],
            'Metadata source differs from its original CLI launch')
        content['source'].update(command_origin=origin,command_origins=[origin,original['origin']],source_capture=allocation['source_capture'])
        name=d3._digest(content['identity']);receipts=journal.setdefault('setup_receipts',{})
        d3._require(name not in receipts or receipts[name]==content,'Original metadata source cannot be overwritten')
        receipts[name]=content;changes._save(Path(directory),journal)
        return _reference(content,directory)
    try:payload=doctor._native_witness_content(witness)
    except doctor.ObservationError:raise startup.StartupError('An actual frontend capture is required') from None
    action=next(row for row in journal['manifest']['actions'] if row['id']==action_id)
    threads=payload['native']['threads']
    d3._require(len(threads)==1,'Original CLI capture needs its exact native session')
    capture=dict(version=1,origin=dict(transaction_id=journal['transaction_id'],action_id=action_id,attempt_id=attempt_id),witness=payload,
        launch=dict(command_digest=d3._digest(action['execution']),cwd=process.launch_cwd,codex_home=process.launch_codex_home,
            configuration_overrides_present=threads[0]['launch']['configuration_overrides_present']))
    d3._require(list(process.argv)==action['execution']['argv'] and capture['launch']['cwd']==action['execution']['cwd']
        and payload['codex_home']==capture['launch']['codex_home'],'Frontend capture differs from its actual D4 launch inputs')
    authority=_authorization_shape(journal.get('qualification_scope'))
    attempt=next((row for row in authority['attempts'] if row['reference']==payload['binding']['attempt_ref']),None)
    d3._require(attempt is not None and attempt['command_action']==action_id,'Native capture selected another original allocation')
    if 'source_capture' in attempt:capture['source_capture']=attempt['source_capture']
    _capture_shape(capture);_capture_identity(capture,journal)
    d3._require('setup_capture' not in command or command['setup_capture']==capture,'Original native capture cannot be replaced')
    command['setup_capture']=capture;changes._save(Path(directory),journal)
    return _capture_reference(directory,capture)


def _retained_capture(reference,budget):
    from runtime import changes
    startup._canonical_ref(reference)
    path,separator,suffix=reference['reference'].partition('#command-capture:')
    d3._require(separator and suffix.count(':')==1,'Original native capture route differs')
    action_id,attempt_id=suffix.split(':');pointer=startup._canonical_path(path)
    d3._require(pointer.name=='transaction.json','Native capture is not its original D4 journal')
    d3._private(pointer.parent.stat(),directory=True)
    journal=d3.read_request(_read(pointer,budget,private=True,limit=changes.MAX_JOURNAL),changes.MAX_JOURNAL)
    changes._scoped_journal_shape(journal)
    command=journal['receipts'].get(action_id);capture=command.get('setup_capture') if command else None
    d3._require(capture is not None and reference==_capture_reference(pointer.parent,capture)
        and command['command']==dict(attempt_id=attempt_id,stopped=True)
        and journal['state']=='applied' and not journal['blocked'],
        'Original native command and descendants are not reconciled')
    _stopped_source(journal,capture['origin'])
    return capture,journal


def _stopped_source(journal,origin):
    command=journal['receipts'].get(origin['action_id'])
    d3._require(origin['transaction_id']==journal['transaction_id'] and command is not None
        and command['command']==dict(attempt_id=origin['attempt_id'],stopped=True)
        and any(row['id']==origin['action_id'] and row['attempt_id']==origin['attempt_id'] and row['stopped'] is True
            for observation in journal['observations'] for row in observation['command_reconciliation']),
        'Original native command and descendants lack exact stopped reconciliation')


def setup_capture_projection(decision, *, process):
    projection=qualification_attempt_projection(decision,operation='observe-setup-metadata',case_id='startup-context',process=process)
    reference=startup._canonical_plain(projection['attempt'].get('source_capture'))
    capture,journal=_retained_capture(reference,_budget())
    identity=_capture_identity(capture,journal);payload=capture['witness']
    sessions=sorted(thread['id'] for thread in payload['native']['threads'])
    d3._require(identity==startup._canonical_plain(projection['identity'])
        and sorted(projection['attempt']['native_sessions'])==sessions,'Metadata selected another frontend source/session')
    return startup._canonical_freeze(payload)


def collect_retained_setup(reference, identity, new_transaction, assessment):
    """Publish an exact successor, preserving the actual native capture transaction."""
    budget=_budget();original,journal=_retained_reference(reference,budget)
    d3._require(original['identity']==startup._canonical_plain(identity) and 'assessment' in original
        and original['transaction_id']!=new_transaction,'Retained setup needs a complete filtered source and a new exact transaction')
    assessment=_assessment(assessment,staged=True)
    _monotonic_coverage(original,dict(assessment=assessment))
    observations=original.get('source',{}).get('observations',{})
    for row in assessment['cases']:
        actual=observations.get(row['id'],[])
        d3._require(row['status']!='verified' or actual and all(proof in row['evidence'] for proof in actual),
            'A successor cannot qualify behavior absent from its retained genuine observations')
    current=current_configuration(original['configuration'],Path(identity['repository_root']),budget)
    d3._require(current['digest']==original['configuration']['digest'] and current['hook_owner']==original['configuration']['hook_owner'],
        'Original observable setup configuration changed')
    content=startup._canonical_copy(original)
    content.update(version=2,transaction_id=new_transaction,assessment=assessment,predecessor=reference)
    content['source']['capture_reference']=reference
    return _SetupObservation(startup._canonical_freeze(content),_ISSUER)


def _monotonic_coverage(previous, successor):
    old = previous.get('assessment',dict(cases=[],requirements=[])); new = successor['assessment']
    for name in ('cases', 'requirements'):
        retained = {row['id']: row for row in new[name]}
        for row in old[name]:
            status = row.get('status', 'verified')
            d3._require(row['id'] in retained and (status == 'pending' or
                retained[row['id']]['status'] == status and all(proof in retained[row['id']]['evidence'] for proof in row['evidence'])),
                'Successor lost original qualified evidence or catalog coverage')


def _authorization_shape(value):
    from runtime.changes import _evidence
    d3._object(value, ('decision_reference', 'target', 'attempts'))
    d3._require(_evidence(value['decision_reference']), 'Verified disposable qualification authority is missing')
    target = value['target']
    d3._object(target, ('accepted_scope_digest', 'repository_root', 'git_common_dir', 'disposable'))
    startup._canonical_hash(target['accepted_scope_digest'])
    for key in ('repository_root', 'git_common_dir'):startup._canonical_path(target[key])
    d3._require(target['disposable'] is True and isinstance(value['attempts'], list) and 0 < len(value['attempts']) <= 64,
        'An exact approved disposable target and bounded attempts are required')
    seen = set()
    for attempt in value['attempts']:
        d3._object(attempt, ('reference', 'task', 'native_sessions', 'operations', 'capability_keys', 'limits', 'stop_conditions'), ('plan_reference','command_action','source_capture'))
        startup._canonical_ref(attempt['reference'])
        token = d3._digest(attempt['reference'])
        d3._require(token not in seen, 'Duplicate original qualification attempt');seen.add(token)
        bootstrap = attempt['task'] is None
        metadata = bootstrap and attempt['operations'] == ['observe-setup-metadata']
        if not bootstrap:
            d3._object(attempt['task'], ('client', 'session_id', 'task_id'))
            for entry in attempt['task'].values():startup._canonical_text(entry, 128)
        for key in ('native_sessions', 'operations', 'capability_keys', 'stop_conditions'):
            if key == 'native_sessions' and bootstrap and not metadata:
                d3._require(attempt[key] == [], 'Bootstrap cannot invent native sessions')
                continue
            d3._require(isinstance(attempt[key], list) and 0 < len(attempt[key]) <= 64
                and len(set(attempt[key])) == len(attempt[key]), 'Invalid bounded qualification attempt scope')
            for entry in attempt[key]:startup._canonical_text(entry, 4096)
        d3._require(set(attempt['capability_keys']) <= set(BEHAVIOR_CASES)
            and set(attempt['operations']) <= set(OPERATION_CAPABILITIES), 'Unknown qualification case or operation')
        d3._require((attempt['operations'] in (['observe-cli-basic'],['observe-setup-metadata']) and attempt['capability_keys'] == ['startup-context']) if bootstrap
            else attempt['task']['session_id'] in attempt['native_sessions'] and 'observe-cli-basic' not in attempt['operations'],
            'Attempt lost its native/task scope')
        if bootstrap:
            startup._canonical_text(attempt.get('command_action'),128)
        if metadata:startup._canonical_ref(attempt.get('source_capture'))
        else:d3._require('source_capture' not in attempt,'Only the claimed metadata operation consumes a frontend fragment')
        if 'plan_reference' in attempt:
            from runtime.state import _artifact_reference
            _artifact_reference(attempt['plan_reference'])
        limits = attempt['limits']
        d3._object(limits, ('deadline', 'max_attempts', 'max_resource_units'))
        d3._require(type(limits['deadline']) in (int,float) and math.isfinite(limits['deadline'])
            and all(type(limits[key]) is int and 0 < limits[key] <= 4096 for key in ('max_attempts','max_resource_units')),
            'Qualification needs original finite allocations')
    return value


def _staged_scope(content, journal):
    if content['version'] == 1:return
    required = next(row['requirements'] for row in journal['manifest']['enrollment']['qualification']
        if all(row[key] == content['identity'][key] for key in ('repository_id','checkout_id','client')))
    d3._require(set(required) == {row['id'] for row in content['assessment']['requirements']},
        'Staged source lost its complete mandatory catalog')
    if _coverage(content)[1]:return
    authority = _authorization_shape(journal.get('qualification_scope'))
    identity = content['identity'];target = authority['target']
    d3._require(target['accepted_scope_digest'] == d3._digest(identity)
        and all(target[key] == identity[key] for key in ('repository_root','git_common_dir')),
        'Partial acceptance is limited to its originally approved disposable target')


def _attempt_admission(identity, authorization, attempt, transaction_id, qualification_ref, operation, *, owner=None, process=None):
    projection = startup._canonical_freeze(dict(identity=identity,target=authorization['target'],
        transaction_id=transaction_id,attempt=attempt))
    return _CapabilityAdmission('qualification',tuple(attempt['capability_keys']),qualification_ref,
        projection['attempt']['reference'],_ISSUER,projection['attempt']['limits'],projection,operation,owner,process)


def _original_attempt(content, journal, reference, *, budget=None):
    """Resolve one immutable allocation across bounded retained successor history."""
    selected = None;seen = set();budget = budget if budget is not None else _budget();identity = content['identity']
    while True:
        authority = journal.get('qualification_scope')
        if authority is not None:
            _authorization_shape(authority)
            attempt = next((row for row in authority['attempts'] if row['reference'] == startup._canonical_plain(reference)),None)
            if attempt is not None:
                original = dict(target=authority['target'],decision_reference=authority['decision_reference'],attempt=attempt)
                d3._require(selected is None or selected[2] == original,
                    'Successor cannot rebind an original qualification allocation')
                selected = authority,attempt,original
        predecessor = content.get('predecessor')
        if predecessor is None:break
        token = d3._digest(predecessor)
        d3._require(token not in seen and len(seen) < 64, 'Invalid retained qualification history');seen.add(token)
        content,journal = _retained_reference(predecessor,budget)
        d3._require(content['identity'] == identity, 'Qualification predecessor changed original scope')
    d3._require(selected is not None, 'Original qualification authority is unavailable')
    return selected[:2]


def persist_setup(directory, journal, observations, *, qualification_scope=None):
    """Called by the already admitted coordinator under D4's existing operation guards."""
    from runtime import changes
    record = journal['manifest']['enrollment']['record']
    receipts = journal.get('setup_receipts', {})
    if qualification_scope is not None:
        authorization = _authorization_shape(startup._canonical_copy(qualification_scope))
        d3._require('qualification_scope' not in journal or journal['qualification_scope'] == authorization,
            'Original qualification authorization cannot change during recovery')
        journal['qualification_scope'] = authorization
    d3._require(isinstance(observations, (list, tuple)) and len(observations) <= 64, 'Bounded owner setup collection is required')
    for observation in observations:
        content = _issued(observation); receipt_shape(content); identity = content['identity']
        key = (identity['repository_id'], identity['checkout_id'], identity['client'])
        entry = changes._scoped_entries(record)[key][2]
        projection = startup._canonical_plain(startup.canonical_scope_projection(startup.decode_project_record(record),
            repository_id=key[0], checkout_id=key[1], client=key[2]))
        d3._require(content['transaction_id'] == journal['transaction_id'] and identity == projection
            and entry['activation']['qualification_binding'] == receipt_binding(observation, directory), 'Setup source does not bind this approved transaction/member')
        rule = next(row for row in journal['manifest']['enrollment']['qualification'] if all(row[k] == v for k, v in zip(('repository_id', 'checkout_id', 'client'), key)))
        assessment = content['assessment']
        covered = {row['id'] for row in assessment['requirements']}
        d3._require((covered == set(rule['requirements']) if content['version'] == 2 else set(rule['requirements']) <= covered)
            and (not rule['security_required'] or bool(assessment['security_review'])), 'Complete scoped adoption/security qualification is missing')
        if content['version'] == 2:
            _staged_scope(content, journal)
            if content['predecessor'] is not None:
                previous, _ = _retained_reference(content['predecessor'], _budget())
                d3._require(previous['identity'] == identity and previous['transaction_id'] != content['transaction_id'],
                    'Successor must retain its exact original scope in a new D4 transaction')
                _monotonic_coverage(previous, content)
        name = d3._digest(identity)
        d3._require(name not in receipts or receipts[name] == content, 'Original setup observation cannot be replaced during recovery')
        receipts[name] = content
    if observations:
        journal['setup_receipts'] = receipts
        changes._save(Path(directory), journal)


def _read_qualification(record, facts, *, cwd=None, pending_journal=None, budget=None):
    """Bounded local receipt/config reader; enrollment and proposal labels cannot mint receipts."""
    from runtime import changes
    try:
        data = startup._canonical_plain(record.data if isinstance(record, startup.CanonicalRecord) else record)
        root = facts['observation']['root']; client = facts['client']
        matches = [(key, entry) for key, (_, checkout, entry) in changes._scoped_entries(data).items()
            if checkout['root'] == root and key[2] == client]
        if len(matches) != 1:return None
        key, entry = matches[0]; activation = entry['activation']; binding = activation['qualification_binding']
        if client != 'codex' or binding is None:return None
        path, separator, name = binding['receipt']['reference'].partition('#setup:')
        if not separator:return None
        pointer = startup._canonical_path(path)
        d3._require(pointer.name == 'transaction.json', 'Setup receipt route is not an original D4 journal')
        budget = budget if budget is not None else _budget(facts.get('deadline'))
        d3._private(pointer.parent.stat(), directory=True)
        raw = _read(pointer, budget, private=True, limit=changes.MAX_JOURNAL)
        journal = d3.read_request(raw, changes.MAX_JOURNAL)
        changes._scoped_journal_shape(journal)
        d3._require(journal['transaction_id'] == activation['transaction_id'] and journal['manifest_digest'] == d3._digest(journal['manifest']), 'Original setup transaction changed')
        content = journal.get('setup_receipts', {}).get(name)
        if content is None:return None
        receipt_shape(content)
        if content['version'] == 2:
            _staged_scope(content, journal)
            predecessor = content['predecessor'];seen = set();original_identity = content['identity']
            while predecessor is not None:
                token = d3._digest(predecessor)
                d3._require(token not in seen and len(seen) < 64,'Invalid original setup source history');seen.add(token)
                parent,_ = _retained_reference(predecessor,budget)
                d3._require(parent['identity'] == original_identity,'Original setup source changed accepted scope')
                predecessor = parent.get('predecessor')
        d3._require(binding['receipt'] == _reference(content, pointer.parent)
            and content['transaction_id'] == journal['transaction_id'] and name == d3._digest(content['identity']), 'Setup receipt does not bind its retained journal')
        projection = startup._canonical_plain(startup.canonical_scope_projection(startup.decode_project_record(data),
            repository_id=key[0], checkout_id=key[1], client=key[2]))
        d3._require(content['identity'] == projection and projection['configuration']['policy_digest'] == facts['installed']['policy_digest']
            and projection['configuration']['runtime_digest'] == facts['installed']['runtime_digest'], 'Setup scope/source identity changed')
        expected = _binding(content, pointer.parent)
        d3._require(binding == expected, 'Historical setup qualification binding changed')
        if pending_journal is not None and pending_journal['transaction_id'] == journal['transaction_id']:
            d3._require(journal == pending_journal and journal['state'] in ('prepared', 'applying', 'blocked', 'interrupted'), 'Setup publication lost its actual pending journal')
        else:
            d3._require(journal['state'] == 'applied' and not journal['blocked'] and journal['enrollment'] is not None
                and any(row['phase'] == 'final' for row in journal['enrollment']['postimages']), 'Original setup enrollment did not complete')
        final = changes._scoped_entries(journal['manifest']['enrollment']['record']).get(key)
        d3._require(final is not None and final[2]['activation'] == activation, 'Setup receipt was replayed into another activation')
        config = content['configuration']
        home = Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex'))).resolve()
        d3._require(str(home) == config['codex_home'] and config['package_root'] == facts['installed']['package_root'], 'Required local configuration origin is unavailable')
        # Native bundle bytes have their own 8 MiB cap; time and path limits stay shared.
        scan = _budget(budget.get('deadline'))
        current = current_configuration(config, Path(cwd or root), budget, bundle_budget=scan)
        result = dict(current=dict(client=client, configuration_digest=current['digest'], hook_owner=current['hook_owner']),
            receipt=binding['receipt'], binding=binding, provenance=dict(kind='trusted-coordinator', **binding['receipt']))
        if content['version'] == 2:
            verified, complete = _coverage(content)
            result['capabilities'] = dict(reference=binding['receipt'], verified=verified, complete=complete)
        return result, content
    except (startup.StartupError, OSError, ValueError, TypeError, KeyError, StopIteration):
        return None


def read_qualification(record, facts, **options):
    retained = _read_qualification(record, facts, **options)
    return retained[0] if retained is not None else None


def require_capability(scope, keys, *, task, operation, attempt_ref=None):
    """Derive purpose from retained owner authority; selection JSON grants nothing."""
    d3._require(isinstance(scope, startup.AcceptedScope) and isinstance(keys, (list,tuple,set)) and keys
        and set(keys) <= {*BEHAVIOR_CASES, 'full-onboarding'}, 'Unknown capability admission')
    d3._require(operation in OPERATION_CAPABILITIES and set(OPERATION_CAPABILITIES[operation]) <= set(keys),
        'Unknown operation or missing dependent capability')
    d3._require(isinstance(task, dict), 'Actual owned task identity is required')
    sticky = task.get('qualification_attempt')
    if sticky is not None:
        d3._require(attempt_ref is None or attempt_ref == sticky, 'Qualification task cannot change its original purpose')
        attempt_ref = sticky
    if scope.qualification is None:
        d3._require(attempt_ref is None, 'Legacy scope has no staged qualification authority')
        return _CapabilityAdmission('ordinary',tuple(sorted(keys)),None,None,_ISSUER,operation=operation)
    from runtime import state
    budget = _budget()
    current = startup.acquire_project_entry(SimpleNamespace(client=scope.client,cwd=scope.repository_root),state.PACKAGE,budget=budget)
    fresh = current.resolution.scope
    d3._require(fresh is not None and fresh.accepted_scope_digest == scope.accepted_scope_digest
        and fresh.qualification == scope.qualification and fresh.authority_target == scope.authority_target,
        'Qualification scope or observable configuration changed')
    content, journal = _retained_reference(startup._canonical_plain(scope.qualification['reference']), budget)
    verified, complete = _coverage(content)
    ordinary = ('startup-context' in verified and 'pre-tool-enforcement' in verified
        and all(key in verified or key == 'full-onboarding' and complete for key in keys)
        and (operation != 'task-patch' or 'post-tool-handling' in verified))
    if ordinary and attempt_ref is None:
        return _CapabilityAdmission('ordinary',tuple(sorted(keys)),scope.qualification['reference'],None,_ISSUER,operation=operation)
    d3._require(attempt_ref is not None and 'full-onboarding' not in keys, 'Pending capability needs its exact authorized qualification attempt')
    authorization, attempt = _original_attempt(content,journal,attempt_ref,budget=budget)
    target = authorization['target']
    d3._require(target['accepted_scope_digest'] == scope.accepted_scope_digest
        and target['repository_root'] == str(scope.repository_root) and target['git_common_dir'] == str(scope.git_common_dir),
        'Qualification attempt selected an unapproved repository')
    d3._require(attempt is not None and all(task.get(key) == value for key,value in attempt['task'].items())
        and operation in attempt['operations'] and set(keys) <= set(attempt['capability_keys'])
        and attempt['limits']['deadline'] > time.time()
        and task.get('state') not in ('BLOCKED','WAITING','PAUSED','CANCELLED'),
        'Original qualification attempt is unavailable, expired or outside its scope')
    return _attempt_admission(content['identity'],authorization,attempt,content['transaction_id'],scope.qualification['reference'],operation)
