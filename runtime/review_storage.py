"""Explicit machine-private bootstrap and compact, non-enrolling review owners."""

from contextlib import contextmanager
from contextvars import ContextVar
import fcntl
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import time
import uuid

from runtime import evidence, state
from runtime.startup import PROJECT_FILE, checkout, json_object, read_git, _canonical_freeze, _canonical_plain


MAX_CONFIG = 64 * 1024
MAX_RECORDS = 4096
_ACTIVE_PRODUCER = ContextVar('temporary_storage_producer', default=None)
_ERRORS = (OSError, state.StartupError, sqlite3.Error, ValueError, TypeError, KeyError,
           RecursionError, subprocess.SubprocessError)


def _machine_config_path():
    return Path.home() / '.config' / 'vibe-coding-workflow' / 'machine.json'


def _require(value, reason='Temporary review storage remains protected'):
    if not value:
        raise state.StateError(reason)


def _path(value):
    _require(isinstance(value, (str, Path)))
    path = Path(value)
    state._canonical_path(str(path))
    try:
        _require(len(str(path)) <= 4096 and path.resolve() == path)
    except RuntimeError:
        raise state.StateError('Storage path cannot be resolved safely') from None
    return path


def _parents(path, *, existing=False):
    parents = path.parents
    _require(len(parents) <= 128)
    result = {}
    for parent in parents:
        if existing and not os.path.lexists(parent):
            continue
        info = parent.lstat()
        _require(stat.S_ISDIR(info.st_mode) and not parent.is_symlink())
        result[str(parent)] = evidence._binding(parent)
    _require(len(evidence._raw(result)) <= MAX_CONFIG // 2)
    return result


def _check_parents(parents):
    _require(isinstance(parents, dict) and 0 < len(parents) <= 128)
    for value, binding in parents.items():
        path = _path(value)
        state._canonical_binding(binding)
        _require(path.is_dir() and not path.is_symlink() and evidence._binding(path) == binding)


def _location(value):
    path = _path(value)
    _parents(path, existing=True)
    _require(not path.is_relative_to(state.PACKAGE.resolve()))
    for ancestor in (path, *path.parents):
        _require(not os.path.lexists(ancestor / '.git') and
                 not (ancestor.name == 'plugins' and ancestor.parent.name in {'.codex', '.claude'}) and
                 not (ancestor.name == 'cache' and ancestor.parent.name == 'plugins') and
                 not (ancestor.parent.name in {'.agents', '.codex', '.claude', '.cursor'} and
                      ancestor.name in {'skills', 'commands', 'instructions', 'agents'}) and
                 not (ancestor.parent.name == '.cursor' and ancestor.name == 'rules'))
    existing = next(p for p in (path, *path.parents) if p.exists())
    _require(existing.is_dir())
    code, _ = read_git(existing, '-c', 'safe.bareRepository=all', 'rev-parse', '--absolute-git-dir',
                       limit=4096, discovery=True, timeout=2)
    _require(code != 0)
    return path


@contextmanager
def _machine_guard(*, create=False):
    path = _path(_machine_config_path())
    original_parents = _parents(path, existing=True)
    if not path.parent.exists():
        if not create:
            yield path, None, None
            return
        _location(path.parent)
        state._prepare_directory(path.parent)
    _location(path.parent)
    state._private(path.parent, True)
    parents = _parents(path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        _require(dict(device=info.st_dev, inode=info.st_ino) == parents[str(path.parent)])
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                _require(time.monotonic() < deadline)
                time.sleep(0.01)
        _check_parents(parents)
        _check_parents(original_parents)
        yield path, descriptor, parents
        _check_parents(parents)
    finally:
        os.close(descriptor)


def _configuration(path, descriptor):
    if descriptor is None:
        return None
    try:
        file_descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
    except FileNotFoundError:
        return None
    with os.fdopen(file_descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1
                 and info.st_mode & 0o077 == 0 and info.st_size <= MAX_CONFIG)
        raw = stream.read(MAX_CONFIG + 1)
        current = os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
        _require((current.st_dev, current.st_ino, current.st_size) == (info.st_dev, info.st_ino, len(raw)))
        _require(stat.S_ISREG(current.st_mode) and current.st_uid == os.getuid()
                 and current.st_nlink == 1 and current.st_mode & 0o077 == 0)
    return json_object(raw, limit=MAX_CONFIG)


def _publish(path, descriptor, parents, value, *, expected):
    raw = evidence._raw(value)
    _require(len(raw) <= MAX_CONFIG and _configuration(path, descriptor) == expected)
    _check_parents(parents)
    name = '.machine-' + uuid.uuid4().hex
    file_descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                              0o600, dir_fd=descriptor)
    try:
        with os.fdopen(file_descriptor, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        _check_parents(parents)
        _require(_configuration(path, descriptor) == expected)
        os.replace(name, path.name, src_dir_fd=descriptor, dst_dir_fd=descriptor)
        os.fsync(descriptor)
    finally:
        try:
            os.unlink(name, dir_fd=descriptor)
        except FileNotFoundError:
            pass


def _ready_context(config, machine_parents):
    state._fields(config, ('version', 'state', 'private_data_dir', 'parents', 'machine_parents',
                          'authority', 'provenance', 'owner', 'created_at'))
    _require(type(config['version']) is int and config['version'] == 1 and config['state'] == 'ready'
             and config['machine_parents'] == machine_parents)
    _check_parents(config['parents'])
    _check_parents(config['machine_parents'])
    root = _location(config['private_data_dir'])
    state._private(root, True)
    authority = config['authority']
    _require(authority['database'] == str(root / 'review-evidence' / 'runtime.sqlite3')
             and authority['directory'] == str(root / 'review-evidence'))
    _require(config['parents'] == _parents(Path(authority['database'])))
    context = evidence.EvidenceAuthorityContext(Path(authority['directory']), Path(authority['database']),
        _canonical_freeze(authority['directory_binding']), _canonical_freeze(authority['database_binding']),
        (_canonical_freeze(authority),), 'explicit machine-private temporary evidence authority')
    evidence._check_context(context)
    return context


def _provenance_content(authority, parents, owner, created_at, runtime_digest):
    return dict(version=1, kind='temporary-authority-provenance', authority=authority,
                parents=parents, owner=owner, created_at=created_at, runtime_digest=runtime_digest)


def _provenance(config, context, db):
    reference = config['provenance']
    metadata = state._metadata(db, reference['name'])
    _require(metadata is not None and metadata['bytes'] <= MAX_CONFIG)
    content = evidence._read(None, reference, context=context, db=db)
    state._canonical_hash(content['runtime_digest'])
    _require(content == _provenance_content(config['authority'], config['parents'], config['owner'],
                 config['created_at'], content['runtime_digest'])
             and metadata['owner'] == config['owner'] and metadata['created_at'] == config['created_at']
             and config['owner']['created_at'] == config['created_at'] and metadata['class'] == 'compact'
             and metadata['closed_at'] is None and not metadata['targets'] and not metadata['dependencies']
             and metadata['export'] is None)
    for table in state.CANONICAL_TABLE_SQL:
        if table != 'evidence_metadata':
            _require(db.execute('select 1 from ' + table + ' limit 1').fetchone() is None)
    return reference


def _check_producer(context, db, owner):
    """Only the active real producer can register its exact observed compact facts."""
    _require(_ACTIVE_PRODUCER.get() is owner and owner.db is db and owner.context == context
             and db.in_transaction and state._frozen_snapshot(owner.content) and state._frozen_snapshot(owner.targets))
    content, targets = _canonical_plain(owner.content), _canonical_plain(owner.targets)
    metadata_owner = content['owner']
    state._fields(metadata_owner, ('kind', 'id', 'created_at'))
    _require(metadata_owner['kind'] == 'temporary' and metadata_owner['created_at'] == owner.created_at)
    state._integer(owner.created_at, 'original temporary creation time')
    if owner.creation is not None:
        state._check_creation(context.database, owner.creation, db)
        _require(not os.path.lexists(context.directory / 'evidence'))
        _require(not targets and owner.created_at == owner.creation.created_at
                 and content == _provenance_content(_canonical_plain(owner.creation.authority),
                     _parents(context.database), metadata_owner, owner.created_at, state.runtime_fingerprint()))
        for table in state.CANONICAL_TABLE_SQL:
            _require(db.execute('select 1 from ' + table + ' limit 1').fetchone() is None)
    else:
        _require(len(targets) == 1 and _observe_target(Path(targets[0]['path'])) == targets[0]
                 and content == dict(version=1, kind='temporary-target-owner', owner=metadata_owner,
                    created_at=owner.created_at, target=targets[0], provenance=content['provenance']))
    return metadata_owner


def _register(context, db, content, targets, *, creation=None):
    _require(len(evidence._raw(content)) <= MAX_CONFIG)
    owner = evidence._TemporaryOwner(context, db, _canonical_freeze(content), _canonical_freeze(targets),
                                     content['created_at'], creation)
    token = _ACTIVE_PRODUCER.set(owner)
    try:
        return evidence._artifact(None, content, context=context, owner=owner, db=db)
    finally:
        _ACTIVE_PRODUCER.reset(token)


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ready_report(config):
    return dict(ok=True, status='ready', private_data_dir=config['private_data_dir'])


def _protected():
    return dict(ok=False, status='protected',
                reason='Review storage or target is interrupted, unsafe, incompatible or outside this supported slice')


def _pending():
    return dict(ok=False, status='storage_pending')


def storage_status():
    """Inspect existing selection and original provenance without creating anything."""
    try:
        with _machine_guard() as (path, descriptor, parents):
            config = _configuration(path, descriptor)
            if config is None:
                return _pending()
            context = _ready_context(config, parents)
            with evidence._context_database(context) as db:
                _provenance(config, context, db)
            return _ready_report(config)
    except _ERRORS:
        return _protected()


def prepare_storage(private_data_dir):
    """Select once; durable initializing intent prevents automatic bootstrap retries."""
    creation = None
    try:
        root = _location(private_data_dir)
        machine = _path(_machine_config_path())
        _require(not root.is_relative_to(machine.parent) and not machine.parent.is_relative_to(root))
        with _machine_guard(create=True) as (path, descriptor, parents):
            config = _configuration(path, descriptor)
            if config is not None:
                _require(config.get('private_data_dir') == str(root))
                context = _ready_context(config, parents)
                with evidence._context_database(context) as db:
                    _provenance(config, context, db)
                return _ready_report(config)
            directory = root / 'review-evidence'
            _require(not os.path.lexists(directory))
            if root.exists():
                state._private(root, True)
            intent = dict(version=1, state='initializing', private_data_dir=str(root),
                          parents=_parents(directory, existing=True), machine_parents=parents)
            for parent in parents:
                _check_parents(parents)
                _sync_directory(Path(parent))
                _check_parents(parents)
            _publish(path, descriptor, parents, intent, expected=None)
            _check_parents(intent['parents'])
            state._prepare_directory(directory)
            creation = state._initialize(directory / 'runtime.sqlite3', version=3,
                                         expected_directory=evidence._binding(directory))
            state._check_creation(directory / 'runtime.sqlite3', creation)
            authority = _canonical_plain(creation.authority)
            context = evidence.EvidenceAuthorityContext(directory, directory / 'runtime.sqlite3',
                _canonical_freeze(authority['directory_binding']), _canonical_freeze(authority['database_binding']),
                (_canonical_freeze(authority),), 'fresh machine-private temporary evidence authority')
            original = dict(kind='temporary', id=uuid.uuid4().hex, created_at=creation.created_at)
            physical_parents = _parents(context.database)
            content = _provenance_content(authority, physical_parents, original, creation.created_at,
                                          state.runtime_fingerprint())
            with evidence._context_database(context, write=True, durable=True) as db:
                reference = _register(context, db, content, [], creation=creation)
                state._check_creation(context.database, creation, db)
            os.fsync(creation.descriptor)
            _check_parents(intent['parents'])
            _check_parents(physical_parents)
            for parent in physical_parents:
                _sync_directory(Path(parent))
            ready = dict(intent, state='ready', parents=physical_parents, authority=authority,
                         provenance=reference, owner=original, created_at=creation.created_at)
            _publish(path, descriptor, parents, ready, expected=intent)
            return _ready_report(ready)
    except _ERRORS:
        return _protected()
    finally:
        if creation is not None:
            os.close(creation.descriptor)


def _observe_target(target):
    from runtime.onboarding import _checkout_observation
    _require(isinstance(target, (str, Path)) and len(str(target)) <= 4096)
    try:
        selected = Path(target).resolve(strict=True)
    except RuntimeError:
        raise state.StateError('Review target cannot be resolved safely') from None
    if selected.is_file():
        selected = selected.parent
    _require(selected.is_dir())
    identity = checkout(selected, limit=64 * 1024, deadline=time.monotonic() + 5)
    _require(identity is not None)
    root, common = identity
    _require(root / '.git' == common and (root / '.git').is_dir() and not (root / '.git').is_symlink())
    for ancestor in (selected, *selected.parents):
        _require(not os.path.lexists(ancestor / PROJECT_FILE.parent))
        if ancestor != root and not ancestor.is_relative_to(root):
            _require(not os.path.lexists(ancestor / '.git'))
    worktrees = common / 'worktrees'
    _require(not os.path.lexists(worktrees) or worktrees.is_dir() and next(worktrees.iterdir(), None) is None)
    observed, error = _checkout_observation(str(root), dict(paths=0, bytes=0, deadline=time.monotonic() + 5))
    _require(error is None and observed['primary_root'] == str(root) and observed['git_dir'] == str(common))
    git = {key: observed[key] for key in ('root', 'primary_root', 'git_dir', 'git_common_dir', 'binding')}
    return dict(path=str(root), binding=evidence._binding(root), parents=_parents(root), git=git)


def _owners(config, context, db):
    _provenance(config, context, db)
    rows = db.execute('select name,digest from evidence_metadata order by name limit 4097').fetchall()
    _require(len(rows) <= MAX_RECORDS)
    names = {row[0] for row in rows}
    folder = context.directory / 'evidence'
    state._private(folder, True)
    with os.scandir(folder) as entries:
        actual = set()
        for entry in entries:
            actual.add(entry.name)
            _require(len(actual) <= MAX_RECORDS)
    _require(actual == names)
    total = 0
    owners = []
    for name, digest in rows:
        if name == config['provenance']['name']:
            continue
        reference = dict(name=name, digest=digest)
        metadata = state._metadata(db, name)
        total += metadata['bytes']
        _require(metadata['bytes'] <= MAX_CONFIG and total <= evidence.MAX_ARTIFACT)
        content = evidence._read(None, reference, context=context, db=db)
        state._fields(content, ('version', 'kind', 'owner', 'created_at', 'target', 'provenance'))
        _require(type(content['version']) is int and content['version'] == 1
                 and content['kind'] == 'temporary-target-owner' and content['provenance'] == config['provenance']
                 and metadata['owner']['kind'] == 'temporary' and metadata['owner'] == content['owner']
                 and metadata['created_at'] == content['created_at'] == content['owner']['created_at']
                 and metadata['class'] == 'compact' and metadata['targets'] == [content['target']]
                 and not metadata['dependencies'] and metadata['closed_at'] is None and metadata['export'] is None)
        owners.append(dict(owner=content['owner'], reference=reference, created_at=content['created_at'],
                           target=content['target'], bytes=metadata['bytes']))
    return owners


def _existing_owner(owners, target):
    result = None
    root = Path(target['path'])
    for owner in owners:
        original = owner['target']
        old_root = Path(original['path'])
        related = (root.is_relative_to(old_root) or old_root.is_relative_to(root)
                   or original['binding'] == target['binding']
                   or original['git']['binding']['git_common_dir'] == target['git']['binding']['git_common_dir'])
        if related:
            _require(original == target and result is None)
            result = owner
    return result


def _resolved(owner):
    return dict(ok=True, status='resolved', **{key: owner[key] for key in ('owner', 'reference', 'created_at')})


def resolve_owner(target):
    """Resolve one ordinary never-enrolled Repository; unsupported cases allocate nothing."""
    try:
        with _machine_guard() as (path, descriptor, parents):
            config = _configuration(path, descriptor)
            if config is None:
                return _pending()
            context = _ready_context(config, parents)
            observed = _observe_target(target)
            root = Path(observed['path'])
            _require(not context.directory.is_relative_to(root) and not root.is_relative_to(context.directory)
                     and not path.is_relative_to(root))
            with evidence._context_database(context) as db:
                existing = _existing_owner(_owners(config, context, db), observed)
                if existing is not None:
                    _require(_observe_target(target) == observed and _configuration(path, descriptor) == config)
                    return _resolved(existing)

            def before_commit(db):
                _require(_configuration(path, descriptor) == config and _observe_target(target) == observed)
                _ready_context(config, parents)
                _provenance(config, context, db)

            with evidence._context_database(context, write=True, durable=True, before_commit=before_commit) as db:
                owners = _owners(config, context, db)
                existing = _existing_owner(owners, observed)
                if existing is not None:
                    return _resolved(existing)
                _require(len(owners) < MAX_RECORDS - 1)
                created_at = state._owner_time()
                owner = dict(kind='temporary', id=uuid.uuid4().hex, created_at=created_at)
                content = dict(version=1, kind='temporary-target-owner', owner=owner, created_at=created_at,
                               target=observed, provenance=config['provenance'])
                _require(sum(row['bytes'] for row in owners) + len(evidence._raw(content)) <= evidence.MAX_ARTIFACT)
                reference = _register(context, db, content, [observed])
                result = dict(owner=owner, reference=reference, created_at=created_at)
            return _resolved(result)
    except _ERRORS:
        return _protected()
