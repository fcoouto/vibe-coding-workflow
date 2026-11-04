"""Explicit worker presentation, independent of execution authority and admission."""

from contextlib import contextmanager
import fcntl
import importlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from uuid import NAMESPACE_URL, UUID, uuid5


ROLES = frozenset({'Coordinator', 'Scout', 'Builder', 'Tester', 'Reviewer', 'Scribe', 'Investigator'})
LIMIT = 128 * 1024
LABEL_LIMIT = 2 * 4096 + len(' · ')
TERMINAL = frozenset({'accepted', 'rejected', 'failed', 'unresolved', 'completed', 'cancelled'})


def text(value, limit=4096):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or not value.isprintable():
        raise ValueError('invalid_visibility_text')
    return value


def declaration(value):
    if (not isinstance(value, dict) or not {'version', 'role', 'specialty'} <= set(value)
            or set(value) - {'version', 'role', 'specialty', 'custom_role_name'}
            or type(value['version']) is not int or value['version'] != 1
            or not isinstance(value['role'], str) or value['role'] not in ROLES):
        raise ValueError('invalid_visibility_declaration')
    text(value['specialty'])
    if 'custom_role_name' in value:
        text(value['custom_role_name'])
    return dict(value)


def display_label(value, model_display_name):
    value = declaration(value)
    # Retain the existing model-display normalization; custom names remain exact.
    model = (' '.join(''.join(c for c in model_display_name if c.isprintable()).split())
             if isinstance(model_display_name, str) else 'Model unknown')
    return text(value.get('custom_role_name', value['role']) + ' · ' + text(model), LABEL_LIMIT)


def private_path(path):
    path = Path(path)
    if not path.is_absolute() or path.parent.resolve(strict=True) != path.parent or path.is_symlink():
        raise ValueError('unsafe_visibility_path')
    parent = path.parent.stat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid() or parent.st_mode & 0o077:
        raise ValueError('unsafe_visibility_path')
    return path


def read(path):
    path = private_path(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_nlink != 1):
            raise ValueError('unsafe_visibility_file')
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('visibility_size_limit')
    from runtime.startup import json_object
    return json_object(raw, limit=LIMIT)


def save(path, value, *, exclusive=False):
    path = private_path(path)
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True).encode()
    if len(raw) > LIMIT:
        raise ValueError('visibility_size_limit')
    fd, temporary = tempfile.mkstemp(prefix='.visibility-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def locked(path):
    path = private_path(path)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_nlink != 1):
            raise ValueError('unsafe_visibility_lock')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def transport(plugin_root):
    """Load only the already-installed optional transport, without its job store."""
    root = str(Path(plugin_root).resolve(strict=True))
    sys.path.insert(0, root)
    try:
        module = importlib.import_module('local_model_delegation.habblaud')
        if not Path(module.__file__).resolve().is_relative_to(root):
            raise ValueError('visibility_adapter_mismatch')
        return module
    finally:
        sys.path.remove(root)


def publisher(module, endpoint, account, binding, visibility, receipt):
    """Freeze before delivery; reuse actual native or explicitly external identity."""
    visibility = declaration(visibility)
    binding = dict(binding)
    if set(binding) != {'parent', 'agent_id', 'label', 'cwd'}:
        raise ValueError('invalid_visibility_binding')
    for key, value in binding.items():
        text(value, LABEL_LIMIT if key == 'label' else 4096)
    text(account, 200)
    client = module.Client(endpoint)
    receipt = private_path(receipt)

    def observed_binding():
        snapshot = client.snapshot(account)
        matches = [item for item in snapshot['agents'] if item.get('id') == account + ':' + binding['agent_id']]
        if len(matches) > 1 or any(item.get('parentId') != account + ':' + binding['parent']
                or item.get('role') != binding['label'] for item in matches):
            raise ValueError('habblaud_binding_mismatch')
        return bool(matches)

    def publish(phase):
        status = dict(version=1, binding=binding, visibility=visibility, account=account,
                      delivered=False, phase=text(phase, 256), started=False, stopped=False)
        try:
            with locked(receipt.with_name(receipt.name + '.lock')):
                old = read(receipt)
                if old is not None and 'binding' in old:
                    if (not set(status) <= set(old) <= set(status) | {'reason'}
                            or type(old['version']) is not int or old['version'] != 1
                            or any(type(old[key]) is not bool for key in ('delivered', 'started', 'stopped'))):
                        return status | dict(reason='invalid_visibility_receipt')
                    text(old['phase'], 256)
                    if 'reason' in old:
                        text(old['reason'], 256)
                    if any(old.get(key) != status[key] for key in ('binding', 'visibility', 'account')):
                        return status | dict(reason='visibility_binding_changed')
                    status.update(started=old.get('started') is True, stopped=old.get('stopped') is True)
                elif old is not None:
                    if (type(old.get('delivered')) is not bool or set(old) - {
                            'delivered', 'phase', 'reason', 'agent_id', 'parent', 'account', 'observed_at'}):
                        return status | dict(reason='invalid_visibility_receipt')
                    if old['delivered']:
                        if (old.get('agent_id'), old.get('parent'), old.get('account')) != (
                                binding['agent_id'], binding['parent'], account):
                            return status | dict(reason='visibility_binding_changed')
                        status['started'] = True
                # Freeze even when the first delivery fails.
                save(receipt, status)
                if 'guardian' in binding['label'].casefold():
                    status['reason'] = 'unsupported_display_label'
                    save(receipt, status)
                    return status
                try:
                    present = observed_binding()
                    if not present and not status['stopped'] and (not status['started'] or phase not in TERMINAL):
                        client.event(account, module._event(binding, 'SubagentStart'))
                        status['started'] = True
                        save(receipt, status)
                        present = observed_binding()
                    if not present:
                        status['reason'] = 'visibility_unconfirmed'
                    else:
                        status['started'] = True
                        if not status['stopped']:
                            client.event(account, module._event(binding, 'PreToolUse', phase))
                            if phase in TERMINAL:
                                client.event(account, module._event(binding, 'SubagentStop'))
                                status['stopped'] = True
                        status['delivered'] = True
                except (ValueError, OSError, KeyError, TypeError, AttributeError, RecursionError) as error:
                    reason = str(error)
                    status['reason'] = {
                        'habblaud_binding_mismatch': 'habblaud_binding_mismatch',
                        'habblaud_event_too_large': 'unsupported_display_label',
                    }.get(reason, 'visibility_unavailable')
                save(receipt, status)
                return status
        except (ValueError, OSError, KeyError, TypeError, AttributeError, RecursionError):
            return status | dict(delivered=False, reason='visibility_unavailable')

    return publish


def register_external(*, module, endpoint: str, account: str, parent: str, checkout: str,
                      run_id: str, execution_route: str, model_display_name: str,
                      visibility: dict, state_directory: Path) -> dict:
    """Publish display metadata using the transport and identity verified by the host."""
    try:
        if (str(UUID(text(parent, 36))) != parent
                or re.fullmatch(r'[A-Za-z0-9_-]+', text(execution_route, 256)) is None):
            raise ValueError('invalid_external_visibility_identity')
        text(run_id, 256)
        external_id = str(uuid5(NAMESPACE_URL, f'vcw:{execution_route}:{parent}:{run_id}'))
        metadata = declaration(visibility)
        badge_role = {key: metadata[key] for key in ('version', 'role', 'specialty')}
        binding = dict(parent=parent, agent_id=external_id, cwd=checkout,
                       label=display_label(badge_role, text(model_display_name, 160)))
        receipt = state_directory / f'habblaud-{external_id}.json'
        status = publisher(module, endpoint, account, binding, metadata, receipt)('completed')
        return {key: status[key] for key in ('delivered', 'reason') if key in status}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError, ImportError):
        return dict(delivered=False, reason='visibility_unavailable')
