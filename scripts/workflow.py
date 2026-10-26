#!/usr/bin/env python3
"""Plugin hooks and local controls, including approved onboarding and recovery."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace


PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))


def control_main():
    from runtime.startup import MAX_INPUT, StartupError, json_object, resolve_project

    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise StartupError("Invalid task, doctor or onboard command arguments")

    try:
        parser = Parser(add_help=False)
        commands = parser.add_subparsers(dest="command", required=True)
        task = commands.add_parser("task", add_help=False)
        actions = task.add_subparsers(dest="action", required=True)
        for name in ("start", "update", "status"):
            action = actions.add_parser(name, add_help=False)
            action.add_argument("--cwd", required=True)
            if name == "status":
                action.add_argument("--client", required=True, choices=("codex",))
                action.add_argument("--session", required=True)
        doctor = commands.add_parser("doctor", add_help=False)
        doctor.add_argument("--cwd", required=True)
        doctor.add_argument("--client", required=True, choices=("codex",))
        doctor.add_argument("--executable", required=True)
        onboard = commands.add_parser("onboard", add_help=False)
        onboarding = onboard.add_subparsers(dest="action", required=True)
        for name in ("inspect", "plan", "apply", "resume", "rollback"):
            action = onboarding.add_parser(name, add_help=False)
            action.add_argument("--plan-dir", required=True)
            if name == "inspect":
                action.add_argument("--cwd", required=True)
        args = parser.parse_args()
        if args.command == "onboard":
            from runtime.onboarding import MAX_REQUEST, inspect_project, read_request, record_plan
            request = read_request(sys.stdin.buffer.read(MAX_REQUEST + 1))
            if args.action == "inspect":
                report = inspect_project(Path(args.cwd), Path(args.plan_dir), request)
            elif args.action == "plan":
                report = record_plan(Path(args.plan_dir), request)
            else:
                from runtime.changes import apply_plan, resume_plan, rollback_plan
                operation = {"apply": apply_plan, "resume": resume_plan, "rollback": rollback_plan}
                report = operation[args.action](Path(args.plan_dir), request)
            print(json.dumps(report))
            return report["exit_code"]
        if args.command == "task" and args.action in ("start", "update"):
            request = json_object(sys.stdin.buffer.read(MAX_INPUT + 1))
            client = request.get("client")
            if client != "codex":
                raise StartupError("Expected a supported native task client")
        else:
            client = args.client
        scope = resolve_project(SimpleNamespace(client=client, cwd=Path(args.cwd)), PACKAGE)
        if args.command == "doctor":
            from runtime.doctor import inspect_runtime
            report = inspect_runtime(scope, args.executable)
            print(json.dumps(report))
            return report["exit_code"]
        if scope is None:
            raise StartupError("The requested checkout is not enrolled for this client")
        if scope.runtime is None:
            raise StartupError("Runtime state is not configured for this checkout")
        from runtime.state import start_task, update_task, task_status
        if args.action == "status":
            report = task_status(scope, client, args.session)
        else:
            report = (start_task if args.action == "start" else update_task)(scope, request)
        print(json.dumps(report))
        return 0
    except StartupError as error:
        reason = str(error)
    except (ImportError, ValueError, TypeError, KeyError, OSError, RecursionError, subprocess.TimeoutExpired):
        reason = "Invalid task input, enrollment or local runtime"
    print(json.dumps({"ok": False, "error": reason}))
    return 1


def main():
    control = len(sys.argv) > 1 and sys.argv[1] in {"task", "doctor", "onboard"}
    if sys.version_info < (3, 11):
        print(json.dumps({"ok": False, "error": "Vibe Coding Workflow requires Python 3.11+"} if control else
                         {"systemMessage": "Vibe Coding Workflow requires Python 3.11+ on the hook PATH."}))
        return 1 if control else 0
    if control:
        return control_main()
    requested_event = sys.argv[2] if len(sys.argv) == 3 else None
    from runtime.adapters import claude_code, codex, session_start
    from runtime.engine import HookResult
    from runtime.startup import MAX_INPUT, RuntimeScopeError, StartupError, json_object, orient, resolve_project
    runtime_kind = requested_event if requested_event in codex.RUNTIME_EVENTS else None

    def failure(reason):
        if runtime_kind is not None:
            return codex.runtime_diagnostic(runtime_kind, reason)
        return session_start.diagnostic(reason)

    try:
        adapters = {"codex": codex, "claude-code": claude_code}
        if len(sys.argv) != 3 or sys.argv[1] not in adapters:
            raise StartupError("Expected a supported client and event")
        if requested_event != "SessionStart" and (sys.argv[1] != "codex" or runtime_kind is None):
            raise StartupError("Unsupported client runtime event")
        adapter = adapters[sys.argv[1]]
        payload = json_object(sys.stdin.buffer.read(MAX_INPUT + 1))
        if payload.get("hook_event_name") != requested_event:
            raise StartupError("CLI event does not match the payload event")
        if requested_event == "SessionStart":
            output = adapter.render(orient(adapter.normalize(payload), PACKAGE))
        else:
            event = codex.normalize_runtime(payload)
            scope = resolve_project(event, PACKAGE)
            result = HookResult(event.kind)
            if scope is not None and scope.runtime is not None:
                from runtime.state import process_event
                result = process_event(scope, event)
            output = codex.render_runtime(result)
    except RuntimeScopeError as error:
        if runtime_kind == "PreToolUse" and event.tool_name == "apply_patch":
            output = codex.render_runtime(HookResult(runtime_kind, "deny", str(error)))
        else:
            output = failure(str(error))
    except StartupError as error:
        output = failure(str(error))
    except (ValueError, OSError, RecursionError, subprocess.TimeoutExpired):
        # Input and OS exception text may contain private paths or record contents.
        output = failure("invalid input, enrollment or local runtime; inspect the installed client instructions")
    if output is not None:
        print(json.dumps(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
