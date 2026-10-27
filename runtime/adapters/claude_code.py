"""Claude Code SessionStart input and output; no client settings are changed."""

from pathlib import Path

from runtime.adapters import session_start
from runtime.adapters.session_start import diagnostic, render
from runtime.engine import HookResult, RuntimeEvent
from runtime.startup import StartupError


SOURCES = {"startup", "resume", "clear", "compact", "fork"}
RUNTIME_EVENTS = {"PreToolUse"}


def normalize(payload):
    return session_start.normalize(payload, "claude-code", SOURCES)


def normalize_runtime(payload):
    if not isinstance(payload, dict) or payload.get("hook_event_name") != "PreToolUse":
        raise StartupError("Unsupported Claude Code runtime event")
    values = {}
    for field in ("session_id", "cwd", "tool_name"):
        value = payload.get(field)
        if (not isinstance(value, str) or not value.strip() or len(value) > 4096 or
                any(not char.isprintable() for char in value)):
            raise StartupError(f"Invalid Claude Code {field}")
        values[field] = value
    call = payload.get("tool_use_id")
    if call is not None and (not isinstance(call, str) or not call.strip() or len(call) > 4096 or
                             any(not char.isprintable() for char in call)):
        raise StartupError("Invalid Claude Code tool_use_id")
    cwd = Path(values["cwd"])
    if not cwd.is_absolute():
        raise StartupError("Runtime cwd must be absolute")
    return RuntimeEvent("PreToolUse", "claude-code", values["session_id"], cwd,
                        tool_call_id=call, tool_name=values["tool_name"])


def render_runtime(result: HookResult):
    if result.action == "pass":
        return None
    if result.event_kind != "PreToolUse" or result.action not in {"deny", "context"}:
        raise StartupError("Unsupported Claude Code runtime result")
    if not isinstance(result.reason, str):
        raise StartupError("Invalid runtime result reason")
    reason = " ".join("".join(char for char in result.reason if char.isprintable() or char.isspace()).split())[:1024]
    if not reason:
        raise StartupError("Invalid runtime result reason")
    if result.action == "deny":
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": reason}}
    return {"systemMessage": reason}


def runtime_diagnostic(kind, reason):
    return {"systemMessage": f"Vibe Coding Workflow {kind} runtime unavailable: {reason}. "
            "Execution coverage and workflow readiness remain unverified."}
