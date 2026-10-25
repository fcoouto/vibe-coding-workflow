#!/usr/bin/env python3
"""Plugin hook entry point. No enrollment, settings changes or network calls."""

import json
from pathlib import Path
import subprocess
import sys


PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))


def main():
    if sys.version_info < (3, 11):
        print(json.dumps({"systemMessage": "Vibe Coding Workflow requires Python 3.11+ on the hook PATH."}))
        return 0
    from runtime.adapters import claude_code, codex, session_start
    from runtime.startup import MAX_INPUT, StartupError, json_object, orient

    try:
        adapters = {"codex": codex, "claude-code": claude_code}
        if len(sys.argv) != 3 or sys.argv[1] not in adapters or sys.argv[2] != "SessionStart":
            raise StartupError("Expected a supported client and SessionStart")
        adapter = adapters[sys.argv[1]]
        payload = json_object(sys.stdin.buffer.read(MAX_INPUT + 1))
        output = adapter.render(orient(adapter.normalize(payload), PACKAGE))
    except StartupError as error:
        output = session_start.diagnostic(str(error))
    except (ValueError, OSError, RecursionError, subprocess.TimeoutExpired):
        # Input and OS exception text may contain private paths or record contents.
        output = session_start.diagnostic("invalid input, enrollment or local runtime; inspect the installed client instructions")
    if output is not None:
        print(json.dumps(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
