"""Owned setup observations retained by D4; routine reads use local files only.

The coordinator independently verifies semantic evidence before passing it here.
Journal origin is a cooperative code-path contract, not same-user forgery defense.
"""

from dataclasses import dataclass
import hashlib
import json
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


@dataclass(frozen=True)
class _SetupObservation:
    content: object
    issuer: object


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


def _assessment(value):
    from runtime.changes import _evidence
    value = startup._canonical_copy(value)
    d3._object(value, ('cases', 'requirements', 'general_review', 'security_review', 'semantic_assessment'))
    d3._require(isinstance(value['cases'], list) and len(value['cases']) == len(BEHAVIOR_CASES), 'Complete setup behavior matrix is required')
    seen = set()
    for row in value['cases']:
        d3._object(row, ('id', 'evidence'))
        d3._require(row['id'] in BEHAVIOR_CASES and row['id'] not in seen and _evidence(row['evidence'], many=True), 'Missing independent semantic behavior evidence')
        seen.add(row['id'])
    seen = set()
    d3._require(isinstance(value['requirements'], list) and len(value['requirements']) <= 4096, 'Bounded mandatory adoption evidence is required')
    for row in value['requirements']:
        d3._object(row, ('id', 'evidence'))
        d3._require(isinstance(row['id'], str) and row['id'] and row['id'] not in seen and _evidence(row['evidence'], many=True), 'Missing mandatory adoption evidence')
        seen.add(row['id'])
    d3._require(_evidence(value['general_review'], many=True) and isinstance(value['security_review'], list), 'Independent review evidence is required')
    _evidence(value['security_review'], many=True)
    d3._require(isinstance(value['semantic_assessment'], dict) and all(value['semantic_assessment'].get(key) is True for key in
        ('complete', 'catalog_complete', 'conflicts_checked', 'instructions_checked', 'source_provenance_checked')), 'Complete semantic adoption assessment is required')
    return value


def collect_setup(process, collectors, accepted_identity, transaction_id, verified_assessment, *, request_id=100):
    """Trusted setup operation; semantic results are independently verified, never proposal JSON.

    Native hooks/list may initialize .hook-trust baselines for any enumerated
    plugin. Campaign authorization must cover those native effects before use.
    """
    from runtime.doctor import NativeProcess, HookCollector, ObservationError, inspect_hooks
    from runtime.adapters.codex import _native_surface
    from runtime.state import _accepted_identity
    d3._require(isinstance(process, NativeProcess) and process.identity is not None and isinstance(collectors, list)
        and 0 < len(collectors) <= 64 and all(isinstance(c, HookCollector) for c in collectors), 'Actual owned native collection is required')
    identity = _accepted_identity(accepted_identity)
    d3._require(identity['client'] == 'codex', 'Only the Codex local setup source is supported')
    root = startup._canonical_path(identity['repository_root']); startup._canonical_text(transaction_id, 128)
    budget = _budget(process.deadline)
    def request(method, params):
        nonlocal request_id
        request_id += 1
        try:
            return process.request(request_id, method, params)
        except ObservationError:
            raise startup.StartupError('Owned native setup observation is unavailable') from None
    threads = []
    for thread_id in sorted({c.scope[0] for c in collectors}):
        thread = request('thread/read', dict(threadId=thread_id, includeTurns=False)).get('thread')
        d3._require(isinstance(thread, dict) and thread.get('id') == thread_id and thread.get('cwd') == str(root), 'Setup native checkout differs')
        try:
            _native_surface(thread, 'codex-cli')
        except ObservationError:
            raise startup.StartupError('This native setup source did not observe Codex CLI') from None
        startup._canonical_text(thread.get('cliVersion'), 128)
        threads.append(dict(id=thread_id, surface='codex-cli', version=thread['cliVersion'], originator=thread['originator']))
    runs = []
    for collector in collectors:
        snapshot = startup._canonical_plain(collector.snapshot())
        d3._require(collector.native_process is process and collector.native_only and snapshot
            and len(snapshot) == len(collector.runs), 'Direct, foreign or incomplete hook collection cannot qualify setup')
        runs.extend(snapshot)
    d3._require(len(runs) <= 64 and len({run['id'] for run in runs}) == len(runs), 'Setup native collection exceeds its scope')
    package = Path(collectors[0].scope[2]).parent.parent
    d3._require(all(c.scope[2] == str(package/'hooks/codex.json') for c in collectors), 'Setup hook sources differ')
    d3._require(identity['configuration']['policy_digest'] == startup.policy_digest(package, budget=budget)
        and identity['configuration']['runtime_digest'] == _runtime_digest(package, budget), 'Setup candidate policy/runtime identity differs')
    d3._require(d3._filesystem_binding(Path(identity['project_root'])) == identity['project_binding']
        and all(d3._filesystem_binding(Path(identity['repository_root' if key == 'root' else key])) == binding
            for key, binding in identity['bindings'].items()), 'Setup physical project/checkout identity differs')
    for dependency in identity['shared_policy']:
        d3._require(hashlib.sha256(_read(Path(dependency['path']), budget)).hexdigest() == dependency['sha256'], 'Setup shared instruction source differs')
    definitions = startup.json_object(_read(package/'hooks/codex.json', budget))['hooks']
    listed = request('hooks/list', dict(cwds=[str(root)]))
    d3._require(inspect_hooks(listed, SimpleNamespace(repository_root=root), definitions, package=package)['status'] == 'passed', 'Actual native hook registration is unqualified')
    entries = [row for row in listed['data'][0]['hooks'] if row['sourcePath'] == str(package/'hooks/codex.json')]
    d3._require(not any(row.get('isManaged') for row in listed['data'][0]['hooks']), 'Managed hook sources are outside this personal setup source')
    plugin_ids = {row.get('pluginId') for row in entries}
    d3._require(len(plugin_ids) == 1 and isinstance(next(iter(plugin_ids)), str), 'Actual plugin identity is missing')
    plugin_id = next(iter(plugin_ids))
    d3._require(plugin_id.count('@') == 1 and not plugin_id.split('@')[1].startswith('openai-'), 'Only an explicit personal local plugin is supported')
    d3._require({run['eventName'] for run in runs} >= {name[0].lower()+name[1:] for name in definitions}, 'Required native hook behavior was not observed')
    config = dict(package_root=str(package), codex_home=process.identity['codexHome'], plugin_id=plugin_id,
        roots=[str(root), identity['primary_root']], keys=sorted(row['key'] for row in entries), files=[])
    layers = request('config/read', dict(cwd=str(root), includeLayers=True)).get('layers')
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
    requirements = request('configRequirements/read', {}).get('requirements') or {}
    relevant = dict(feature_requirements=requirements.get('featureRequirements'),
        allow_managed_hooks_only=requirements.get('allowManagedHooksOnly'), hooks=requirements.get('hooks'),
        marketplaces=requirements.get('marketplaces'))
    d3._require(not _projection(relevant, config), 'Managed hook/plugin requirements are outside this personal setup source')
    current = current_configuration(config, root, budget)
    observed = {item['path']: item['values'] for item in current['material']['files']}
    d3._require(all(observed.get(path) == projection for path, projection in expected.items()), 'Native origins differ from their actual local files')
    d3._require(all(not observed[str(system_files[0].parent/name)] for name in ('requirements.toml', 'managed_config.toml')), 'Unmapped local requirements prevent personal activation')
    approvals = {}
    for layer in reversed(user_layers):
        for key, value in layer.get('hook_state', {}).items():approvals.setdefault(key, {}).update(value)
    for entry in entries:
        approval = approvals.get(entry['key'], {})
        d3._require(entry['currentHash'] == approval.get('trusted_hash', '')+'/'+approval.get('trusted_content_hash', '')
            and approval.get('trusted_content_hash') == current['material']['bundle'], 'Modern persisted plugin content approval is required')
    config.update(digest=current['digest'], hook_owner=current['hook_owner'])
    executable = Path(process.argv[0]).resolve(strict=True)
    executable_digest = hashlib.sha256(); size = 0
    with executable.open('rb') as stream:
        while chunk := stream.read(64*1024):
            startup._check_observation_deadline(budget); size += len(chunk)
            d3._require(size <= 256*1024*1024, 'Native executable identity exceeds setup budget')
            executable_digest.update(chunk)
    content = dict(version=1, kind='owner-observed-setup', transaction_id=transaction_id, identity=identity,
        native=dict(surface='codex-cli', version=threads[0]['version'], threads=threads,
            executable=dict(path=str(executable), sha256=executable_digest.hexdigest())),
        configuration=config, runs=runs, assessment=_assessment(verified_assessment))
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
    d3._object(content, ('version', 'kind', 'transaction_id', 'identity', 'native', 'configuration', 'runs', 'assessment'))
    d3._require(type(content['version']) is int and content['version'] == 1 and content['kind'] == 'owner-observed-setup', 'Invalid original setup receipt')
    _assessment(content['assessment'])
    d3._require(content['identity']['client'] == 'codex' and content['native']['surface'] == 'codex-cli', 'Unsupported original setup scope')
    startup._canonical_text(content['transaction_id'], 128)
    startup._canonical_hash(content['configuration']['digest']); startup._canonical_hook(content['configuration']['hook_owner'])


def persist_setup(directory, journal, observations):
    """Called by the already admitted coordinator under D4's existing operation guards."""
    from runtime import changes
    record = journal['manifest']['enrollment']['record']
    receipts = journal.get('setup_receipts', {})
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
        d3._require(set(rule['requirements']) <= {row['id'] for row in assessment['requirements']}
            and (not rule['security_required'] or bool(assessment['security_review'])), 'Complete scoped adoption/security qualification is missing')
        name = d3._digest(identity)
        d3._require(name not in receipts or receipts[name] == content, 'Original setup observation cannot be replaced during recovery')
        receipts[name] = content
    if observations:
        journal['setup_receipts'] = receipts
        changes._save(Path(directory), journal)


def read_qualification(record, facts, *, cwd=None, pending_journal=None, budget=None):
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
        return dict(current=dict(client=client, configuration_digest=current['digest'], hook_owner=current['hook_owner']),
            receipt=binding['receipt'], binding=binding, provenance=dict(kind='trusted-coordinator', **binding['receipt']))
    except (startup.StartupError, OSError, ValueError, TypeError, KeyError, StopIteration):
        return None
