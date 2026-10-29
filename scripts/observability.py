#!/usr/bin/env python3
"""Explicit optional connection controls; no hooks, collector or secret persistence."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace


PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))


def main():
    if sys.version_info < (3, 11):
        print(json.dumps(dict(ok=False, error="python_3_11_required")))
        return 1
    from runtime import langfuse, observability_settings as settings
    from runtime.startup import StartupError, json_object, resolve_project

    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise StartupError("invalid_observability_arguments")

    try:
        parser = Parser(description=__doc__)
        parser.add_argument("action", choices=("configure", "status", "enable", "disable", "probe"))
        parser.add_argument("--cwd", required=True)
        args = parser.parse_args()
        raw = b"{}" if args.action == "status" and sys.stdin.isatty() else sys.stdin.buffer.read(settings.MAX_CONFIG + 1)
        request = json_object(raw or b"{}", limit=settings.MAX_CONFIG)
        if args.action == "status" and request:
            raise StartupError("invalid_observability_status_request")
        scope = resolve_project(SimpleNamespace(client="codex", cwd=Path(args.cwd)), PACKAGE)
        if scope is None or scope.runtime is None:
            raise StartupError("existing_enrolled_runtime_required")
        if args.action == "status":
            result = settings.status(scope)
        else:
            operation = {"configure": settings.configure, "enable": settings.enable,
                         "disable": settings.disable, "probe": settings.probe}[args.action]
            result = operation(scope, request)
        print(json.dumps(result, separators=(",", ":")))
        return 0
    except (settings.SettingsError, langfuse.LangfuseError) as error:
        reason = str(error)
    except (StartupError, OSError, ValueError, TypeError, KeyError, ImportError,
            RecursionError, subprocess.SubprocessError):
        reason = "invalid_observability_input_or_runtime"
    print(json.dumps(dict(ok=False, error=reason), separators=(",", ":")))
    return 1


if __name__ == "__main__":
    sys.exit(main())
