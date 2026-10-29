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
            raise StartupError("Invalid task, evidence, delegation, doctor, onboard or storage command arguments")

    try:
        parser = Parser(add_help=False)
        commands = parser.add_subparsers(dest="command", required=True)
        storage = commands.add_parser("storage", add_help=False)
        storage_actions = storage.add_subparsers(dest="action", required=True)
        storage_actions.add_parser("status", add_help=False)
        storage_actions.add_parser("prepare", add_help=False)
        storage_actions.add_parser("owner", add_help=False).add_argument("--cwd", required=True)
        task = commands.add_parser("task", add_help=False)
        actions = task.add_subparsers(dest="action", required=True)
        for name in ("start", "update", "status", "retire"):
            action = actions.add_parser(name, add_help=False)
            action.add_argument("--cwd", required=True)
            if name == "status":
                action.add_argument("--client", required=True, choices=("codex", "claude-code"))
                action.add_argument("--session", required=True)
                action.add_argument("--prepare-observability", action="store_true")
        evidence = commands.add_parser("evidence", add_help=False)
        evidence_actions = evidence.add_subparsers(dest="action", required=True)
        for name in ("plan", "status", "check", "reconcile-check", "verify"):
            action = evidence_actions.add_parser(name, add_help=False)
            action.add_argument("--cwd", required=True)
            if name == "status":
                action.add_argument("--client", required=True, choices=("codex",))
                action.add_argument("--session", required=True)
        review = evidence_actions.add_parser("review", add_help=False)
        review_actions = review.add_subparsers(dest="review_action", required=True)
        for name in ("prepare", "collect", "assess"):
            action = review_actions.add_parser(name, add_help=False)
            action.add_argument("--cwd", required=True)
        delegation = commands.add_parser("delegation", add_help=False)
        delegation_actions = delegation.add_subparsers(dest="delegation_action", required=True)
        for name in ("plan", "prepare", "observe", "reconcile", "status"):
            action = delegation_actions.add_parser(name, add_help=False)
            action.add_argument("--cwd", required=True)
            if name == "status":
                action.add_argument("--client", required=True, choices=("codex",))
                action.add_argument("--session", required=True)
        guidance = delegation_actions.add_parser("guidance", add_help=False)
        guidance_actions = guidance.add_subparsers(dest="guidance_action", required=True)
        for name in ("status", "claim", "record"):
            guidance_actions.add_parser(name, add_help=False).add_argument("--cwd", required=True)
        coordinator = delegation_actions.add_parser("coordinator", add_help=False)
        coordinator_actions = coordinator.add_subparsers(dest="coordinator_action", required=True)
        coordinator_actions.add_parser("reserve", add_help=False).add_argument("--cwd", required=True)
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
        if args.command == "storage":
            from runtime import review_storage
            if args.action == "prepare":
                request = json_object(sys.stdin.buffer.read(MAX_INPUT + 1))
                if set(request) != {"private_data_dir"} or not isinstance(request["private_data_dir"], str):
                    raise StartupError("Expected an explicit private_data_dir")
                report = review_storage.prepare_storage(Path(request["private_data_dir"]))
            elif args.action == "owner":
                report = review_storage.resolve_owner(Path(args.cwd))
            else:
                report = review_storage.storage_status()
            print(json.dumps(report))
            return 0 if report["ok"] else 1
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
        if args.command == "delegation":
            if args.delegation_action == "status":
                client = args.client
            else:
                request = json_object(sys.stdin.buffer.read(MAX_INPUT + 1))
                if args.delegation_action == "guidance":
                    if request.get("client_surface") not in {"codex-cli", "codex-desktop"}:
                        raise StartupError("Expected a supported native guidance surface")
                    client = "codex"
                else:
                    client = request.get("client")
                    if client != "codex":
                        raise StartupError("Expected a supported native task client")
        elif (args.command == "task" and args.action in ("start", "update", "retire") or
                args.command == "evidence" and args.action != "status"):
            request = json_object(sys.stdin.buffer.read(MAX_INPUT + 1))
            client = request.get("client")
            allowed_clients = {"codex", "claude-code"} if args.command == "task" and args.action in ("start", "update") else {"codex"}
            if client not in allowed_clients:
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
        if args.command == "delegation":
            from runtime import delegation
            if args.delegation_action == "guidance":
                report = {"status": delegation.guidance_status, "claim": delegation.claim_guidance,
                          "record": delegation.record_guidance}[args.guidance_action](scope, request)
            elif args.delegation_action == "status":
                report = delegation.delegation_status(scope, client, args.session)
            else:
                operation = {"plan": delegation.plan_delegation, "prepare": delegation.prepare_assignment,
                             "observe": delegation.observe_assignment, "reconcile": delegation.reconcile_assignment,
                             "coordinator": delegation.reserve_coordinator}
                report = operation[args.delegation_action](scope, request)
            print(json.dumps(report))
            return 0
        if args.command == "evidence":
            from runtime import evidence
            operations = {"plan": evidence.plan_evidence, "check": evidence.run_check, "reconcile-check": evidence.reconcile_check, "verify": evidence.verify_completion,
                          "prepare": evidence.prepare_review, "collect": evidence.collect_review, "assess": evidence.assess_review}
            report = (evidence.evidence_status(scope, client, args.session) if args.action == "status" else
                      operations[args.review_action if args.action == "review" else args.action](scope, request))
            print(json.dumps(report))
            return 0
        from runtime.state import start_task, update_task, task_status, retire_task
        if args.action == "status":
            report = task_status(scope, client, args.session)
            if args.prepare_observability:
                try:
                    from runtime.observability import prepare_task_status
                    preparation = {"status": "prepared", "data": prepare_task_status(report, enabled=True)}
                except Exception:
                    # Optional preparation must preserve the owner's ordinary status result.
                    preparation = {"status": "unavailable"}
                report = dict(report, observability_preparation=preparation)
        else:
            report = {"start": start_task, "update": update_task, "retire": retire_task}[args.action](scope, request)
        print(json.dumps(report))
        return 0
    except StartupError as error:
        reason = str(error)
    except (ImportError, ValueError, TypeError, KeyError, OSError, RecursionError, subprocess.TimeoutExpired):
        reason = "Invalid task input, enrollment or local runtime"
    print(json.dumps({"ok": False, "error": reason}))
    return 1


def main():
    control = len(sys.argv) > 1 and sys.argv[1] in {"task", "doctor", "onboard", "evidence", "delegation", "storage"}
    if sys.version_info < (3, 11):
        print(json.dumps({"ok": False, "error": "Vibe Coding Workflow requires Python 3.11+"} if control else
                         {"systemMessage": "Vibe Coding Workflow requires Python 3.11+ on the hook PATH."}))
        return 1 if control else 0
    if control:
        return control_main()
    requested_event = sys.argv[2] if len(sys.argv) == 3 else None
    from runtime.adapters import claude_code, codex, session_start
    from runtime.engine import HookResult, guarded_mutation
    from runtime.startup import MAX_INPUT, RuntimeScopeError, StartupError, json_object, orient, resolve_project
    client = sys.argv[1] if len(sys.argv) > 1 else None
    adapters = {"codex": codex, "claude-code": claude_code}
    adapter = adapters.get(client)
    runtime_events = {"codex": codex.RUNTIME_EVENTS, "claude-code": claude_code.RUNTIME_EVENTS}
    runtime_kind = requested_event if requested_event in runtime_events.get(client, set()) else None
    event = None

    def failure(reason):
        if runtime_kind is not None:
            return adapter.runtime_diagnostic(runtime_kind, reason)
        return session_start.diagnostic(reason)

    try:
        if len(sys.argv) != 3 or adapter is None:
            raise StartupError("Expected a supported client and event")
        if requested_event != "SessionStart" and runtime_kind is None:
            raise StartupError("Unsupported client runtime event")
        payload = json_object(sys.stdin.buffer.read(MAX_INPUT + 1))
        if payload.get("hook_event_name") != requested_event:
            raise StartupError("CLI event does not match the payload event")
        if requested_event == "SessionStart":
            output = adapter.render(orient(adapter.normalize(payload), PACKAGE))
        else:
            event = adapter.normalize_runtime(payload)
            scope = resolve_project(event, PACKAGE)
            result = HookResult(event.kind)
            if scope is not None and scope.runtime is not None:
                from runtime.state import process_event
                result = process_event(scope, event)
            output = adapter.render_runtime(result)
    except RuntimeScopeError as error:
        if event is not None and guarded_mutation(event):
            output = adapter.render_runtime(HookResult(event.kind, "deny", str(error)))
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
