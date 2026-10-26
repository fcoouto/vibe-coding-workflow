"""Codex hook boundaries; no client settings are changed."""

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

from runtime.adapters import session_start
from runtime.adapters.session_start import diagnostic, render
from runtime.engine import HookResult, RuntimeEvent
from runtime.doctor import NativeProcess, ObservationError, version
from runtime.startup import StartupError, json_object


SOURCES = {"startup", "resume", "clear", "compact", "fork"}
RUNTIME_EVENTS = {"PreToolUse", "PostToolUse", "Stop", "Interrupt"}


def normalize(payload):
    return session_start.normalize(payload, "codex", SOURCES)


def native_string(payload, field, optional=False):
    if optional and field not in payload:
        return None
    value = payload.get(field)
    if (not isinstance(value, str) or not value.strip() or len(value) > 4096
            or any(not char.isprintable() for char in value)):
        raise StartupError(f"Invalid codex {field}")
    return value


def normalize_runtime(payload) -> RuntimeEvent:
    if not isinstance(payload, dict):
        raise StartupError("Expected a runtime JSON object")
    kind = payload.get("hook_event_name")
    if not isinstance(kind, str) or kind not in RUNTIME_EVENTS:
        raise StartupError("Unsupported codex runtime event")
    session = native_string(payload, "session_id")
    cwd = Path(native_string(payload, "cwd"))
    if not cwd.is_absolute():
        raise StartupError("Runtime cwd must be absolute")
    turn = native_string(payload, "turn_id", optional=True)
    tool = call = fingerprint = None
    active = None
    if kind in {"PreToolUse", "PostToolUse"}:
        tool = native_string(payload, "tool_name")
        call = native_string(payload, "tool_use_id", optional=True)
        if turn is not None and call is not None:
            relevant = {"tool_name": tool}
            for field in ("tool_input", "tool_response"):
                if field in payload and (field != "tool_response" or kind == "PostToolUse"):
                    relevant[field] = payload[field]
            try:
                canonical = json.dumps(relevant, sort_keys=True, separators=(",", ":"), allow_nan=False)
                fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            except (ValueError, TypeError, UnicodeError):
                raise StartupError("Invalid runtime tool observation") from None
    if kind == "Stop" and "stop_hook_active" in payload:
        if type(payload["stop_hook_active"]) is not bool:
            raise StartupError("Invalid codex stop_hook_active")
        active = payload["stop_hook_active"]
    return RuntimeEvent(kind, "codex", session, cwd, turn, call, tool, active, fingerprint)


def render_runtime(result: HookResult) -> dict | None:
    kind, action = result.event_kind, result.action
    allowed = {"PreToolUse": {"pass", "deny", "context"},
               "PostToolUse": {"pass", "context"}, "Stop": {"pass", "context", "continue"},
               "Interrupt": {"pass", "context"}}
    if not isinstance(kind, str) or not isinstance(action, str) or kind not in allowed or action not in allowed[kind]:
        raise StartupError("Unsupported runtime result")
    if action == "pass":
        return {} if kind == "Stop" else None
    if not isinstance(result.reason, str):
        raise StartupError("Invalid runtime result reason")
    reason = " ".join("".join(char for char in result.reason if char.isprintable() or char.isspace()).split())[:1024]
    if not reason:
        raise StartupError("Invalid runtime result reason")
    if action == "deny":
        return {"hookSpecificOutput": {"hookEventName": kind, "permissionDecision": "deny",
                                       "permissionDecisionReason": reason}}
    if action == "continue":
        return {"decision": "block", "reason": reason}
    if kind in {"Stop", "Interrupt"}:
        return {"systemMessage": reason}
    return {"hookSpecificOutput": {"hookEventName": kind, "additionalContext": reason}}


def runtime_diagnostic(kind, reason):
    """Errors never block an unvalidated scope or replace a completed tool result."""
    return {"systemMessage": f"Vibe Coding Workflow {kind} runtime unavailable: {reason}. "
            "Execution coverage and workflow readiness remain unverified."}


REVIEW_TIMEOUT = 15
REVIEW_VERSIONS = {"0.163.0"}
REVIEW_METHODS = {"initialize", "thread/read", "thread/items/read", "thread/turns/list", "thread/items/list"}


def _review_id(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > 256
            or any(not char.isprintable() for char in value)):
        raise StartupError("Invalid native review identifier")
    return value


def collect_native_review(scope, attempt_id, parent_turn_id, spawn_item_id):
    """Fetch provenance and report; never dispatch, resume, message or execute review."""
    from runtime.evidence import prepared_native_review

    for value in (attempt_id, parent_turn_id, spawn_item_id):
        _review_id(value)
    binding = prepared_native_review(scope, attempt_id)
    parent = _review_id(binding["parent_session_id"])
    child = None
    process = None
    deadline = time.monotonic() + REVIEW_TIMEOUT
    try:
        executable = shutil.which("codex")
        if executable is None:
            raise ObservationError("unavailable")
        observed_version = version(executable, deadline)
        if observed_version not in REVIEW_VERSIONS:
            raise ObservationError("unsupported_version")
        process = NativeProcess([executable, "app-server", "--listen", "stdio://"], deadline)
        sequence = 0

        def request(method, params):
            nonlocal sequence
            if method not in REVIEW_METHODS:
                raise ObservationError("unsupported_method")
            sequence += 1
            return process.request(sequence, method, params)

        request("initialize", {"clientInfo": {"name": "vibe-workflow-review-observer", "version": "1"},
                               "capabilities": {"experimentalApi": True}})
        process.send({"method": "initialized"})

        def metadata(identity):
            thread = request("thread/read", {"threadId": identity, "includeTurns": False}).get("thread")
            if (not isinstance(thread, dict) or thread.get("id") != identity
                    or thread.get("cwd") != str(scope.repository_root)
                    or thread.get("cliVersion") != observed_version):
                raise ObservationError("thread_mismatch")
            return thread

        metadata(parent)
        selected = request("thread/items/read", {"threadId": parent, "turnId": parent_turn_id,
                                                 "itemIds": [spawn_item_id]}).get("data")
        if (not isinstance(selected, list) or len(selected) != 1 or not isinstance(selected[0], dict)
                or selected[0].get("turnId") != parent_turn_id):
            raise ObservationError("spawn_unverified")
        spawn = selected[0].get("item")
        task_name = _review_id(binding["task_name"])
        if task_name != "review_" + attempt_id or "/" in task_name:
            raise ObservationError("assignment_marker_invalid")
        if (not isinstance(spawn, dict) or spawn.get("id") != spawn_item_id
                or spawn.get("type") != "subAgentActivity" or spawn.get("kind") != "started"):
            raise ObservationError("spawn_unverified")
        child = _review_id(spawn.get("agentThreadId"))
        agent_path = spawn.get("agentPath")
        if (child == parent or not isinstance(agent_path, str) or len(agent_path) > 4096
                or not agent_path.startswith("/") or agent_path.rsplit("/", 1)[-1] != task_name):
            raise ObservationError("child_mismatch")
        thread = metadata(child)
        source = thread.get("source")
        subagent = source.get("subAgent") if isinstance(source, dict) else None
        origin = subagent.get("thread_spawn") if isinstance(subagent, dict) else None
        if (thread.get("parentThreadId") != parent or not isinstance(origin, dict)
                or origin.get("parent_thread_id") != parent or origin.get("agent_path") != agent_path):
            raise ObservationError("child_mismatch")
        requested_model, requested_effort = spawn.get("model"), spawn.get("reasoningEffort")
        for value in (requested_model, requested_effort):
            if value is not None:
                _review_id(value)

        def latest():
            turns = request("thread/turns/list", {"threadId": child, "limit": 1,
                                                 "sortDirection": "desc", "itemsView": "notLoaded"}).get("data")
            if (not isinstance(turns, list) or len(turns) != 1 or not isinstance(turns[0], dict)
                    or turns[0].get("status") != "completed" or turns[0].get("error") is not None):
                raise ObservationError("turn_incomplete")
            return _review_id(turns[0].get("id"))

        review_turn = latest()
        final = []
        cursor = None
        seen = set()
        for _ in range(4):
            params = {"threadId": child, "turnId": review_turn, "limit": 100, "sortDirection": "asc"}
            if cursor is not None:
                params["cursor"] = cursor
            page = request("thread/items/list", params)
            entries = page.get("data")
            if not isinstance(entries, list) or len(entries) > 100:
                raise ObservationError("malformed_history")
            for entry in entries:
                if (not isinstance(entry, dict) or entry.get("turnId") != review_turn
                        or not isinstance(entry.get("item"), dict)):
                    raise ObservationError("malformed_history")
                item = entry["item"]
                if item.get("type") == "agentMessage" and item.get("phase") == "final_answer":
                    final.append(item)
            cursor = page.get("nextCursor")
            if cursor is None:
                break
            if not isinstance(cursor, str) or not cursor or len(cursor) > 4096 or cursor in seen:
                raise ObservationError("pagination_limit")
            seen.add(cursor)
        else:
            raise ObservationError("pagination_limit")
        if len(final) != 1:
            raise ObservationError("final_unverified")
        report_item = _review_id(final[0].get("id"))
        text = final[0].get("text")
        if not isinstance(text, str) or len(text.encode("utf-8")) > 64 * 1024:
            raise ObservationError("report_limit")
        report = json_object(text.encode("utf-8"))
        if (set(report) != {"version", "attempt_id", "assignment_digest", "candidate_digest", "coverage", "findings", "limitations"}
                or type(report.get("version")) is not int or report["version"] != 1
                or report.get("attempt_id") != attempt_id
                or report.get("assignment_digest") != binding["assignment_digest"]
                or report.get("candidate_digest") != binding["candidate_digest"]
                or report.get("coverage") != binding["requested_coverage"]
                or not isinstance(report.get("findings"), list) or len(report["findings"]) > 256
                or not isinstance(report.get("limitations"), list) or len(report["limitations"]) > 64
                or any(not isinstance(item, str) or len(item) > 4096 for item in report["limitations"])):
            raise ObservationError("report_mismatch")
        if latest() != review_turn or prepared_native_review(scope, attempt_id) != binding:
            raise ObservationError("review_changed")
        return {"receipt": {"version": 1, "mechanism": "codex-native-agent-path",
                "task_name": task_name, "agent_path": agent_path,
                "native_version": observed_version, "parent_session_id": parent,
                "parent_turn_id": parent_turn_id, "spawn_item_id": spawn_item_id,
                "reviewer_id": child, "review_turn_id": review_turn, "report_item_id": report_item,
                "assignment_digest": binding["assignment_digest"], "candidate_digest": binding["candidate_digest"],
                "report_digest": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "requested_model": requested_model, "requested_effort": requested_effort}, "report": report}
    except (ObservationError, OSError, ValueError, TypeError, KeyError, RecursionError, subprocess.TimeoutExpired):
        raise StartupError("Native review observation unavailable; independent review remains unverified") from None
    finally:
        if process is not None:
            process.close()
