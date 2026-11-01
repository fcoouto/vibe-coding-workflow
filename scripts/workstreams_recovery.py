#!/usr/bin/env python3
"""Private shared-monitor controls; native App operations run through supported tools."""
import argparse
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))


def main():
    from runtime import parent_recovery
    from runtime.startup import MAX_INPUT, StartupError, json_object, resolve_project
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('status', 'register', 'withdraw', 'reactivate', 'suspend',
        'schedule', 'record-schedule', 'observe', 'record-send'))
    parser.add_argument('--cwd', type=Path)
    parser.add_argument('--full', action='store_true', help='Include complete private registry details for diagnosis')
    args = parser.parse_args()
    try:
        request = json_object(sys.stdin.buffer.read(MAX_INPUT + 1))
        directory = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'workstreams-recovery'
        if args.action == 'register':
            if args.cwd is None:
                raise ValueError('Registration requires the enrolled checkout')
            scope = resolve_project(SimpleNamespace(client='codex', cwd=args.cwd), PACKAGE)
            if scope is None or scope.runtime is None:
                raise ValueError('Registration requires an enrolled workflow task')
            report = parent_recovery.register(scope, directory, request)
        elif args.action == 'reactivate':
            report = parent_recovery.reactivate(directory, request, PACKAGE)
        elif args.action == 'observe':
            report = parent_recovery.observe(directory, request, PACKAGE)
        else:
            report = parent_recovery.control(directory, args.action, request)
        if not args.full:
            report = parent_recovery.compact_result(report, args.action, request.get('thread_id', request.get('session_id')))
        print(json.dumps(report))
        return 0
    except (StartupError, ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps(dict(ok=False, error=str(error))))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
