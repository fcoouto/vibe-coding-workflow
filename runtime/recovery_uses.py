"""Pure, bounded annotations of recovery dependency uses; these functions grant no permission."""
from copy import deepcopy
import json
from pathlib import PurePosixPath
import re

MAX_ROWS = 4096
MAX_BYTES = 4 * 1024 * 1024


class UseContractError(ValueError):
    """A use annotation differs from its exact bounded contract."""


def key(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise UseContractError('Recovery use contains non-JSON data') from None


def _require(condition, message='Invalid recovery use contract'):
    if not condition: raise UseContractError(message)


def _fields(value, fields):
    _require(type(value) is dict and set(value) == set(fields))


def _text(value):
    _require(isinstance(value, str) and 0 < len(value) <= 4096 and not any(ord(c) < 32 for c in value))


def _hash(value):
    _require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None)


def _path(value, absolute=True):
    _text(value)
    path = PurePosixPath(value)
    _require(path.is_absolute() == absolute and str(path) == value and '..' not in path.parts and value not in ('.', '/'))


def _authority(value):
    _fields(value, ('directory', 'database', 'directory_binding', 'database_binding'))
    _path(value['directory']); _path(value['database'])
    _require(value['database'] == value['directory'] + '/runtime.sqlite3')
    for field in ('directory_binding', 'database_binding'):
        _fields(value[field], ('device', 'inode'))
        _require(all(type(n) is int and n >= 0 for n in value[field].values()))


def _artifact(value):
    _fields(value, ('name', 'digest'))
    _require(isinstance(value['name'], str) and re.fullmatch('[0-9a-f]{32}\\.json', value['name']) is not None)
    _hash(value['digest'])


def _pointer(value):
    _fields(value, ('authority', 'artifact')); _authority(value['authority']); _artifact(value['artifact'])


def _task(value):
    _fields(value, ('authority', 'scope_id', 'client', 'session_id', 'task_id'))
    _authority(value['authority']); _hash(value['scope_id'])
    for field in ('client', 'session_id', 'task_id'): _text(value[field])
    _require(len(value['task_id']) <= 128)


def _identity(value):
    _fields(value, ('plan_dir', 'transaction_id', 'manifest_digest'))
    _path(value['plan_dir']); _text(value['transaction_id']); _hash(value['manifest_digest'])


def _dependency(value):
    _fields(value, ('kind', 'reference')); ref = value['reference']
    if value['kind'] == 'task': _task(ref)
    elif value['kind'] in ('artifact', 'recovery'): _pointer(ref)
    elif value['kind'] == 'assignment':
        _fields(ref, ('authority', 'id', 'owner', 'assignment')); _authority(ref['authority']); _artifact(ref['assignment'])
        _require(isinstance(ref['id'], str) and re.fullmatch('[0-9a-f]{32}', ref['id']) is not None)
        _fields(ref['owner'], ('scope_id', 'client', 'session_id', 'task_id', 'dispatch_id'))
        _task(dict(authority=ref['authority'], **{k: ref['owner'][k] for k in ('scope_id', 'client', 'session_id', 'task_id')}))
        _text(ref['owner']['dispatch_id'])
    else: raise UseContractError('Unknown recovery use dependency')


def qualify_dependency(edge, authority):
    """Normalize an existing local typed edge without observing or authorizing its source."""
    _authority(authority); _fields(edge, ('kind', 'reference'))
    value = deepcopy(edge); ref = value['reference']
    if value['kind'] == 'artifact' and type(ref) is dict and set(ref) == {'name', 'digest'}:
        value['reference'] = dict(authority=deepcopy(authority), artifact=ref)
    elif value['kind'] == 'recovery' and type(ref) is dict and set(ref) == {'identity', 'artifact'}:
        _identity(ref['identity']); value['reference'] = dict(authority=deepcopy(authority), artifact=ref['artifact'])
    _dependency(value)
    return value


def validate(value):
    """Validate canonical shape only; the owner must independently check live provenance and coverage."""
    _fields(value, ('version', 'roots', 'edges', 'legacy_routes'))
    _require(type(value['version']) is int and value['version'] == 1)
    for field in ('roots', 'edges', 'legacy_routes'):
        rows = value[field]
        _require(type(rows) is list and len(rows) <= MAX_ROWS)
        _require([key(r) for r in rows] == sorted(set(key(r) for r in rows)), 'Recovery use rows are not canonical')
    _require(len(key(value).encode()) <= MAX_BYTES, 'Recovery use contract exceeds byte bound')
    for root in value['roots']:
        _require(type(root) is dict)
        historical = root.get('purpose') == 'historical-stop'
        _fields(root, ('purpose', 'reference', *(('task', 'proof', 'effect') if historical else ())))
        _require(root['purpose'] in ('historical-stop', 'content')); _dependency(root['reference'])
        if historical:
            _task(root['task']); _pointer(root['proof']); _fields(root['effect'], ('action_id', 'path'))
            _text(root['effect']['action_id']); _path(root['effect']['path'], absolute=False)
            _require(root['reference'] == dict(kind='task', reference=root['task']))
            _require(root['proof']['authority'] == root['task']['authority'])
    for edge in value['edges']:
        _fields(edge, ('root', 'parent', 'dependency', 'purpose'))
        _require(type(edge['root']) is int and 0 <= edge['root'] < len(value['roots']))
        if edge['parent'] is not None: _pointer(edge['parent'])
        _dependency(edge['dependency']); _require(edge['purpose'] in ('retention-only', 'content'))
        if value['roots'][edge['root']]['purpose'] == 'content':
            _require(edge['purpose'] == 'content', 'Content reason lost its permission requirement')
    origins = set()
    for row in value['legacy_routes']:
        _fields(row, ('origin', 'destinations')); origin = row['origin']
        _fields(origin, ('authority', 'artifact', 'identity', 'journal_sha256'))
        _authority(origin['authority']); _artifact(origin['artifact']); _identity(origin['identity']); _hash(origin['journal_sha256'])
        _require(key(origin) not in origins, 'Conflicting legacy route origin'); origins.add(key(origin))
        _require(type(row['destinations']) is list and len(row['destinations']) <= MAX_ROWS)
        for authority in row['destinations']: _authority(authority)
        _require([key(a) for a in row['destinations']] == sorted(set(key(a) for a in row['destinations'])))
    return value


def build(roots, edges, legacy_routes=()):
    """Canonicalize root indices, preserving different reasons for the same dependency."""
    roots = list(roots); edges = list(edges)
    _require(len(roots) <= MAX_ROWS and len(edges) <= MAX_ROWS, 'Recovery use row bound exceeded')
    unique = {key(root): deepcopy(root) for root in roots}; ordered = sorted(unique)
    indices = {raw: index for index, raw in enumerate(ordered)}
    remapped = []
    for edge in edges:
        _fields(edge, ('root', 'parent', 'dependency', 'purpose'))
        _require(type(edge.get('root')) is int and 0 <= edge['root'] < len(roots))
        remapped.append(dict(deepcopy(edge), root=indices[key(roots[edge['root']])]))
    canonical = lambda rows: [deepcopy(row) for _, row in sorted({key(row): row for row in rows}.items())]
    return validate(dict(version=1, roots=[unique[raw] for raw in ordered], edges=canonical(remapped), legacy_routes=canonical(legacy_routes)))


def merge(contracts):
    roots = []; indices = {}; edges = {}; routes = {}
    for contract in contracts:
        validate(contract); remap = {}
        for index, root in enumerate(contract['roots']):
            raw = key(root)
            if raw not in indices:
                _require(len(roots) < MAX_ROWS, 'Recovery use inherited roots exceed bound')
                indices[raw] = len(roots); roots.append(root)
            remap[index] = indices[raw]
        for edge in contract['edges']:
            row = dict(edge, root=remap[edge['root']]); edges[key(row)] = row
            _require(len(edges) <= MAX_ROWS, 'Recovery use inherited edges exceed bound')
        for row in contract['legacy_routes']:
            origin = key(row['origin'])
            _require(origin not in routes or routes[origin] == row, 'Legacy route projection changed')
            routes[origin] = row
            _require(len(routes) <= MAX_ROWS, 'Recovery use inherited routes exceed bound')
    return build(roots, list(edges.values()), list(routes.values()))


def check_coverage(contract, direct, metadata):
    """Compare exact qualified direct edges and each observed managed parent's dependencies.

    metadata maps key({authority, artifact}) to its qualified dependency list.
    Every producer-supplied parent is required, including parents with no dependencies.
    """
    validate(contract)
    _require(type(metadata) is dict and len(metadata) <= MAX_ROWS)
    _require(type(direct) in (list, tuple) and len(direct) <= MAX_ROWS)
    _require(all(type(rows) in (list, tuple) for rows in metadata.values()))
    _require(sum(len(rows) for rows in metadata.values()) <= MAX_ROWS)
    direct_keys = {key(edge) for edge in direct}
    for edge in direct: _dependency(edge)
    actual = {key(row['dependency']) for row in contract['edges'] if row['parent'] is None}
    _require(actual == direct_keys, 'Recovery use direct coverage differs')
    by_parent = {}
    for row in contract['edges']:
        if row['parent'] is not None:
            by_parent.setdefault(key(row['parent']), set()).add(key(row['dependency']))
    _require(set(by_parent) <= set(metadata), 'Recovery use has unobserved parent')
    for parent, dependencies in metadata.items():
        try: pointer = json.loads(parent)
        except (TypeError, ValueError): raise UseContractError('Invalid recovery metadata parent') from None
        _pointer(pointer)
        _require(key(pointer) == parent, 'Noncanonical recovery metadata parent')
        expected = {key(edge) for edge in dependencies}
        for edge in dependencies: _dependency(edge)
        incoming = [row for row in contract['edges'] if row['dependency'] in
            (dict(kind='artifact', reference=pointer), dict(kind='recovery', reference=pointer))]
        _require(incoming, 'Recovery use has an unrooted observed parent')
        for root in {row['root'] for row in incoming}:
            observed = {key(row['dependency']) for row in contract['edges']
                if row['root'] == root and row['parent'] == pointer}
            _require(observed == expected, 'Recovery use rooted metadata coverage differs')
            if any(row['root'] == root and row['purpose'] == 'content' for row in incoming):
                content = {key(row['dependency']) for row in contract['edges']
                    if row['root'] == root and row['parent'] == pointer and row['purpose'] == 'content'}
                _require(content == expected, 'Recovery content use lost its outgoing content coverage')
        _require(by_parent.get(parent, set()) == expected, 'Recovery use metadata coverage differs')
    for row in contract['edges']:
        if row['parent'] is None: continue
        incoming = dict(kind='artifact', reference=row['parent'])
        recovery = dict(kind='recovery', reference=row['parent'])
        _require(any(other['root'] == row['root'] and other['dependency'] in (incoming, recovery)
            and (row['purpose'] == 'content' or other['purpose'] == 'retention-only')
            for other in contract['edges']), 'Recovery use parent has no compatible incoming purpose')
        _require(any(other['root'] == row['root'] and other['parent'] is None
            and other['dependency'] == row['dependency'] and other['purpose'] == row['purpose']
            for other in contract['edges']), 'Recovery use lost its flattened purpose')
    return contract


def project(contract, direct, metadata):
    """Drop only cut uses. Unknown replacement routes fail; no purpose can be upgraded."""
    validate(contract); direct_keys = {key(edge) for edge in direct}
    edges = [row for row in contract['edges'] if
        (row['parent'] is None and key(row['dependency']) in direct_keys) or
        (row['parent'] is not None and key(row['parent']) in metadata and
         key(row['dependency']) in {key(edge) for edge in metadata[key(row['parent'])]})]
    result = build(contract['roots'], edges, contract['legacy_routes'])
    check_coverage(result, direct, metadata)
    return result


def legacy_projection(origin, content):
    """Carry an actual unextended source's original inventory; never a merged inventory."""
    _require('use_contract' not in content, 'Restricted inventory cannot create legacy permission')
    _require(origin['identity'] == content['identity'] and origin['journal_sha256'] == content['journal']['sha256'],
        'Legacy origin differs from observed source')
    destinations = sorted({key(authority): authority for authority in content['authorities']}.values(), key=key)
    return build([], [], [dict(origin=origin, destinations=destinations)])['legacy_routes'][0]
