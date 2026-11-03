#!/usr/bin/env python3
"""Prepare and publish optional native worker labels in the existing task context."""

import argparse
import json
import os
from pathlib import Path
import re
import sys
import uuid

PACKAGE = Path(__file__).resolve().parents[1]
if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))

from runtime import worker_visibility as visibility
from runtime.adapters import codex
from runtime.startup import StartupError, json_object


CONTEXT_FIELDS = {'parent_session_id', 'checkout', 'task_name', 'visibility'}


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


def prepare_native(path, request):
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
    visibility.save(context_path(path, checkout), context, exclusive=True)
    return dict(prepared=True, visibility=context['visibility'],
                **({'prompt_marker': context['prompt_marker']} if 'prompt_marker' in context else {}))


def publish_native(path, worker_id, phase, plugin_root, endpoint, account, *, parent_turn_id=None, spawn_item_id=None):
    """Bind only to a real child of the declared parent; continuation reuses it."""
    try:
        path = context_path(path, plugin_root=plugin_root)
        context = visibility.read(path)
        if (not isinstance(context, dict) or type(context.get('version')) is not int or context['version'] != 1
                or not CONTEXT_FIELDS <= set(context) or set(context) - (
                    CONTEXT_FIELDS | {'version', 'prompt_marker', 'ledger_assignment_digest', 'observed'})
                or len({'prompt_marker', 'ledger_assignment_digest'} & set(context)) != 1):
            raise ValueError('invalid_native_visibility_context')
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
            label = visibility.display_label(metadata, (prior or observed)['configured_model'])
            binding = dict(parent=observed['parent_session_id'], agent_id=observed['worker_id'],
                           label=label, cwd=observed['checkout'])
            publisher = visibility.publisher(visibility.transport(plugin_root), endpoint, account, binding, metadata,
                                             path.with_name(path.name + '.delivery.json'))
            return publisher(phase)
    except (ValueError, OSError, ImportError, KeyError, TypeError, AttributeError, RuntimeError):
        return dict(delivered=False, reason='native_visibility_unavailable')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'publish'))
    parser.add_argument('--context', required=True, type=Path)
    parser.add_argument('--visibility-plugin', type=Path)
    parser.add_argument('--habblaud-endpoint')
    parser.add_argument('--habblaud-account')
    args = parser.parse_args()
    try:
        request = json_object(sys.stdin.buffer.read(visibility.LIMIT + 1), limit=visibility.LIMIT)
        if args.action == 'prepare':
            result = prepare_native(args.context, request)
        else:
            fields = {'worker_id', 'phase'}
            if (set(request) not in (fields, fields | {'parent_turn_id', 'spawn_item_id'}) or not args.visibility_plugin
                    or not args.habblaud_endpoint or not args.habblaud_account):
                raise ValueError('invalid_visibility_publish_request')
            result = publish_native(args.context, request['worker_id'], request['phase'],
                args.visibility_plugin, args.habblaud_endpoint, args.habblaud_account,
                parent_turn_id=request.get('parent_turn_id'), spawn_item_id=request.get('spawn_item_id'))
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, OSError, TypeError, RuntimeError):
        print(json.dumps(dict(delivered=False, reason='invalid_visibility_request')))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
