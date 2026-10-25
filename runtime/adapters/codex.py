"""Codex hook boundaries; no client settings are changed."""

import hashlib
import json
from pathlib import Path

from runtime.adapters import session_start
from runtime.adapters.session_start import diagnostic, render
from runtime.engine import HookResult, RuntimeEvent
from runtime.startup import StartupError


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
