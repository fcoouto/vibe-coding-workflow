#!/usr/bin/env python3
"""Prepare native role declarations and publish optional worker labels."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid

PACKAGE = Path(__file__).resolve().parents[1]
if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))

from runtime import worker_visibility as visibility
from runtime.adapters import codex
from runtime.startup import StartupError, json_object


CONTEXT_FIELDS = {'parent_session_id', 'checkout', 'task_name', 'visibility'}
CONTEXT_OPTIONAL = {'version', 'prompt_marker', 'ledger_assignment_digest', 'observed'}


def context_path(path, checkout=None, plugin_root=None):
    path = visibility.private_path(path)
    protected = [PACKAGE]
    if checkout is not None:
        protected.append(Path(checkout).resolve(strict=True))
    if plugin_root is not None:
        protected.append(Path(plugin_root).resolve(strict=True))
    if any(path.is_relative_to(root) for root in protected) or any(
            os.path.lexists(parent / '.git') for parent in path.parents):
        raise ValueError('native_visibility_context_must_be_private')
    return path


def prepare_native(path, request, *, reuse=False):
    if not isinstance(request, dict) or not CONTEXT_FIELDS <= set(request) <= CONTEXT_FIELDS | {'ledger_assignment_digest'}:
        raise ValueError('invalid_native_visibility_request')
    parent = request['parent_session_id']
    if not isinstance(parent, str) or str(uuid.UUID(parent)) != parent:
        raise ValueError('invalid_native_parent')
    checkout = Path(request['checkout'])
    if not checkout.is_absolute() or checkout.resolve(strict=True) != checkout or not checkout.is_dir():
        raise ValueError('invalid_native_checkout')
    visibility.text(request['task_name'], 128)
    context = dict(request, version=1, visibility=visibility.declaration(request['visibility']))
    if 'ledger_assignment_digest' in request:
        digest = request['ledger_assignment_digest']
        if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('invalid_visibility_assignment_digest')
    else:
        context['prompt_marker'] = 'VCW worker visibility ' + uuid.uuid4().hex
    path = context_path(path, checkout)
    if reuse and path.exists():
        existing = read_context(path)
        if ({key: value for key, value in context.items() if key != 'prompt_marker'} !=
                {key: value for key, value in existing.items() if key not in {'prompt_marker', 'observed'}}):
            raise ValueError('native_visibility_context_changed')
        context = existing
    else:
        visibility.save(path, context, exclusive=True)
    return dict(prepared=True, visibility=context['visibility'],
                **({'prompt_marker': context['prompt_marker']} if 'prompt_marker' in context else {}))


def prepare_context(request, *, context=None, context_directory=None, reuse=False):
    path = context
    if path is None:
        directory = context_directory or default_context_directory(create=True)
        path = hook_context_path(directory, request['parent_session_id'], request['task_name'])
        context_path(path.parent, request['checkout']).mkdir(mode=0o700, exist_ok=True)
    return path, prepare_native(path, request, reuse=reuse)


def prepare_assignment(request, *, context=None, context_directory=None):
    """Assemble one native brief; display failure preserves its original spawn inputs."""
    result = dict(prepared=False, task_name=request.get('task_name'), message=request.get('message'))
    try:
        message = request['message']
        if not isinstance(message, str) or len(message.encode('utf-8')) > visibility.LIMIT:
            raise ValueError('invalid_native_assignment_message')
        declaration = {key: value for key, value in request.items() if key != 'message'}
        declaration['visibility'] = visibility.declaration(request.get('visibility'))
        path, prepared = prepare_context(declaration, context=context,
                                         context_directory=context_directory, reuse=True)
        message = prepared['prompt_marker'] + '\n' + message if 'prompt_marker' in prepared else message
        return result | prepared | dict(context=str(path), message=message)
    except (ValueError, OSError, TypeError, RuntimeError, KeyError):
        return result | dict(reason='native_visibility_unavailable')


def prepare_managed(checkout, parent, report, *, context_directory=None):
    """Consume an already-prepared worker/reviewer result outside its transaction."""
    prepared = prepare_assignment(dict(parent_session_id=parent, checkout=str(checkout),
        task_name=report.get('task_name'), message=report.get('prompt'), visibility=report.get('visibility'),
        ledger_assignment_digest=report.get('ledger_assignment_digest', report.get('assignment_digest'))),
        context_directory=context_directory)
    return report | dict(visibility_preparation={key: prepared[key] for key in ('prepared', 'context', 'reason')
                                                if key in prepared})


def read_context(path):
    context = visibility.read(path)
    if (not isinstance(context, dict) or type(context.get('version')) is not int or context['version'] != 1
            or not CONTEXT_FIELDS <= set(context) or set(context) - (CONTEXT_FIELDS | CONTEXT_OPTIONAL)
            or len({'prompt_marker', 'ledger_assignment_digest'} & set(context)) != 1):
        raise ValueError('invalid_native_visibility_context')
    return context


def hook_context_path(directory, parent, task_name):
    if not isinstance(parent, str) or str(uuid.UUID(parent)) != parent:
        raise ValueError('invalid_native_parent')
    key = hashlib.sha256(visibility.text(task_name, 128).encode()).hexdigest()
    return Path(directory) / parent / (key + '.json')


def default_context_directory(*, create=False):
    home = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex').resolve(strict=True)
    directory = home / 'vibe-worker-visibility' / 'contexts'
    if create:
        directory.parent.mkdir(mode=0o700, exist_ok=True)
        visibility.private_path(directory).mkdir(mode=0o700, exist_ok=True)
    return directory


def specific_native_role(value):
    return isinstance(value, str) and value.strip().casefold() not in {'', 'default'}


def native_label(metadata, observation):
    # Prior observations froze the raw name before the catalog lookup was available.
    model = observation.get('model_display_name')
    if not model:
        model = observation['configured_model']
        if 'model_display_name' in observation and isinstance(model, str) and '-' in model and ' ' not in model:
            model = model.replace('-', ' ').title()
            if model.startswith('Gpt '):
                model = 'GPT-' + model[4:]
    composite = visibility.display_label(metadata, model)
    label = visibility.text(observation.get('forwarded_label', composite), visibility.LABEL_LIMIT)
    return label, label == composite


def enrich_start(event, directory, checkout, executable):
    if event.get('hook_event_name') != 'SubagentStart':
        return event
    try:
        cwd = Path(event['cwd'])
        if str(cwd) != event['cwd'] or (checkout is not None and cwd != checkout):
            return event
        checkout = cwd
        parent, child = event['session_id'], event['agent_id']
        parent_dir = hook_context_path(directory, parent, 'probe').parent
        if not parent_dir.is_dir() or parent_dir.is_symlink():
            return event
        executable = Path(executable)
        if (not executable.is_absolute() or executable.resolve(strict=True) != executable
                or not executable.is_file() or executable.stat().st_mode & 0o022):
            return event
        observed = codex.observe_worker_visibility(checkout, parent, child, deadline=time.monotonic() + 1,
                                                   executable=str(executable))
        task = observed['task_name']
        if (not task or observed['parent_session_id'] != parent
                or observed['worker_id'] != child or observed['checkout'] != str(checkout)):
            return event
        path = context_path(hook_context_path(directory, parent, task), checkout)
        if not path.is_file():
            return event
        with visibility.locked(path.with_name(path.name + '.lock')):
            context = read_context(path)
            if (context['parent_session_id'], context['checkout'], context['task_name']) != (parent, str(checkout), task):
                return event
            prior = context.get('observed')
            if prior is not None and prior['worker_id'] != child:
                return event
            incoming_role = event.get('agent_role')
            label, managed = native_label(context['visibility'], prior or observed)
            # The downstream hook can reduce every string to 200 UTF-16 units.
            if (len(label.encode('utf-16-le')) > 400 or label.strip() != label
                    or label[0].upper() != label[0] or 'guardian' in label.casefold()):
                return event
            if prior is None:
                visibility.save(path, context | dict(observed=observed | dict(forwarded_label=label)))
            role = incoming_role if specific_native_role(incoming_role) else label
            return event | dict(agent_role=role, agent_type=label) | (
                {visibility.MANAGED_DISPLAY_FIELD: label} if managed else {})
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError):
        return event


def forward_start(directory, checkout, executable, command):
    raw = sys.stdin.buffer.read(visibility.LIMIT + 1)
    if len(raw) <= visibility.LIMIT:
        try:
            event = json_object(raw, limit=visibility.LIMIT)
            enriched = enrich_start(event, directory, checkout, executable)
            if enriched != event:
                raw = json.dumps(enriched, ensure_ascii=False).encode()
        except (ValueError, RecursionError):
            pass
        return subprocess.run(command, input=raw).returncode
    with subprocess.Popen(command, stdin=subprocess.PIPE) as child:
        try:
            child.stdin.write(raw)
            shutil.copyfileobj(sys.stdin.buffer, child.stdin)
            child.stdin.close()
        except BrokenPipeError:
            pass
        return child.wait()


def publish_native(path, worker_id, phase, plugin_root, endpoint, account, *, parent_turn_id=None, spawn_item_id=None):
    """Bind only to a real child of the declared parent; continuation reuses it."""
    try:
        path = context_path(path, plugin_root=plugin_root)
        context = read_context(path)
        context_path(path, context['checkout'], plugin_root)
        metadata = visibility.declaration(context['visibility'])
        spawn_binding = None
        if parent_turn_id is not None or spawn_item_id is not None:
            spawn_binding = {key: context[key] for key in (
                'task_name', 'visibility', 'ledger_assignment_digest', 'prompt_marker') if key in context}
            spawn_binding.update(parent_turn_id=parent_turn_id, spawn_item_id=spawn_item_id)
        with visibility.locked(path.with_name(path.name + '.lock')):
            if visibility.read(path) != context:
                return dict(delivered=False, reason='native_visibility_context_changed')
            prior = context.get('observed')
            if prior is not None and prior['worker_id'] != worker_id:
                return dict(delivered=False, reason='native_visibility_identity_changed')
            try:
                observed = codex.observe_worker_visibility(context['checkout'], context['parent_session_id'], worker_id,
                                                           spawn_binding=spawn_binding)
            except StartupError:
                return dict(delivered=False, reason='native_visibility_identity_unobserved')
            if observed['task_name'] != context['task_name']:
                return dict(delivered=False, reason='native_visibility_identity_unobserved')
            if prior is None:
                visibility.save(path, context | dict(observed=observed))
            label, managed = native_label(metadata, prior or observed)
            binding = dict(parent=observed['parent_session_id'], agent_id=observed['worker_id'],
                           label=label, cwd=observed['checkout'])
            publisher = visibility.publisher(visibility.transport(plugin_root), endpoint, account, binding, metadata,
                                             path.with_name(path.name + '.delivery.json'), managed_native_label=managed)
            return publisher(phase)
    except (ValueError, OSError, ImportError, KeyError, TypeError, AttributeError, RuntimeError):
        return dict(delivered=False, reason='native_visibility_unavailable')


def main():
    if sys.argv[1:2] == ['forward-start']:
        parser = argparse.ArgumentParser(description='Forward the existing Habblaud start hook')
        parser.add_argument('--context-directory', required=True, type=Path)
        parser.add_argument('--checkout', type=Path)
        parser.add_argument('--codex-executable', required=True, type=Path)
        parser.add_argument('command', nargs=argparse.REMAINDER)
        args = parser.parse_args(sys.argv[2:])
        command = args.command[1:] if args.command[:1] == ['--'] else args.command
        if not command:
            parser.error('supply the original hook command after --')
        return forward_start(args.context_directory, args.checkout, args.codex_executable, command)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'publish'))
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument('--context', type=Path)
    destination.add_argument('--context-directory', type=Path)
    parser.add_argument('--visibility-plugin', type=Path)
    parser.add_argument('--habblaud-endpoint')
    parser.add_argument('--habblaud-account')
    args = parser.parse_args()
    try:
        request = json_object(sys.stdin.buffer.read(visibility.LIMIT + 1), limit=visibility.LIMIT)
        if args.action == 'prepare':
            if 'message' in request:
                result = prepare_assignment(request, context=args.context, context_directory=args.context_directory)
            else:
                path, result = prepare_context(request, context=args.context, context_directory=args.context_directory)
                if args.context is None:
                    result['context'] = str(path)
        else:
            fields = {'worker_id', 'phase'}
            if (set(request) not in (fields, fields | {'parent_turn_id', 'spawn_item_id'}) or not args.context or not args.visibility_plugin
                    or not args.habblaud_endpoint or not args.habblaud_account):
                raise ValueError('invalid_visibility_publish_request')
            result = publish_native(args.context, request['worker_id'], request['phase'],
                args.visibility_plugin, args.habblaud_endpoint, args.habblaud_account,
                parent_turn_id=request.get('parent_turn_id'), spawn_item_id=request.get('spawn_item_id'))
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, OSError, TypeError, RuntimeError, KeyError):
        print(json.dumps(dict(delivered=False, reason='invalid_visibility_request')))
        return 1


if __name__ == '__main__':
    status = main()
    if status < 0:
        number = -status
        if number not in (signal.SIGKILL, signal.SIGSTOP):
            signal.signal(number, signal.SIG_DFL)
        os.kill(os.getpid(), number)
    raise SystemExit(status)
