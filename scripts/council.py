#!/usr/bin/env python3
"""Bounded local Council controls. Native dispatch remains in the coordinator."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import signal
import sys
import time

PACKAGE = Path(__file__).resolve().parents[1]
if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))

from runtime import council, onboarding, openrouter_settings as settings
from runtime.startup import StartupError
from scripts import openrouter_workers as workers


@contextmanager
def _launch_guard(run, phase):
    # Worker settings admission is held first, and this lock ends immediately after Popen.
    with council._locked(run) as value:
        council._remaining(value, phase)
        council._require(value['phase'] == phase, 'phase_already_closed')
        council._check_frozen(run, value)
        yield


def _execute(run, phase, packet, report):
    remaining = packet['deadline_monotonic'] - time.monotonic()
    council._require(remaining > 0, 'deadline_exhausted')
    previous_handler = signal.getsignal(signal.SIGALRM)
    council._require(signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0), 'existing_deadline_timer')
    # Exact phase/total elapsed ceiling includes preparation and waits, not only inference.
    def exhausted(*_):
        raise TimeoutError('Council deadline exhausted')
    signal.signal(signal.SIGALRM, exhausted)
    try:
        signal.setitimer(signal.ITIMER_REAL, remaining)
        return workers.execute(Path(packet['worker_run']), Path(report['opencode']), Path(report['auth_data']),
                               launch_guard=lambda: _launch_guard(run, phase), deadline_monotonic=packet['deadline_monotonic'])
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def main():
    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise ValueError('invalid_council_arguments')
    try:
        parser = Parser(description=__doc__)
        parser.add_argument('action', choices=('prepare', 'member', 'resume-member', 'record-native', 'verify-external', 'status', 'cancel'))
        parser.add_argument('--cwd', type=Path, required=True)
        args = parser.parse_args()
        request = onboarding.read_request(sys.stdin.buffer.read(council.REQUEST_LIMIT + 1), council.REQUEST_LIMIT)
        if args.action == 'prepare':
            result = council.prepare(args.cwd, request)
        else:
            expected = {'run'} if args.action in ('status', 'cancel') else {'run', 'phase', 'member'}
            if args.action == 'record-native': expected.add('receipt')
            if args.action == 'verify-external': expected |= {'disposition', 'checks'}
            council._require(expected <= set(request) and not set(request) - expected - ({'native_receipt'} if args.action == 'member' else set()), 'invalid_council_request')
            report = settings.status(args.cwd)
            run = Path(request['run'])
            council._require(run.is_absolute() and run.resolve() == run and run.parent == Path(report['council_root']), 'council_checkout_mismatch')
            with council._locked(run) as value:
                council._require(value['source_root'] == report['checkout'] and value['management']['scope_id'] == report['scope_id'], 'council_checkout_mismatch')
            if args.action in ('member', 'resume-member'):
                result = (council.resume_member(run, request['phase'], request['member']) if args.action == 'resume-member' else
                          council.packet(run, request['phase'], request['member'], native_receipt=request.get('native_receipt')))
                if result['kind'] == 'external':
                    result = _execute(run, request['phase'], result, report)
            elif args.action == 'verify-external':
                result = council.verify_external(run, request['phase'], request['member'], request['disposition'], request['checks'])
            elif args.action == 'record-native':
                council.record_native(run, request['phase'], request['member'], request['receipt'])
                result = council.status(run)
            else:
                result = getattr(council, args.action)(run)
        print(json.dumps(result, allow_nan=False, separators=(',', ':')))
        return 0
    except (settings.SettingsError, StartupError, OSError, ValueError, TypeError, KeyError, RecursionError) as error:
        # These errors contain local contract names/paths, never provider credentials or source bytes.
        print(json.dumps(dict(ok=False, error=str(error)), separators=(',', ':')))
        return 1


if __name__ == '__main__':
    sys.exit(main())
