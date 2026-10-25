"""Read-only startup orientation shared by client adapters."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess


MAX_INPUT = 128 * 1024
PROJECT_FILE = Path(".vibe-coding-workflow/project.json")


class StartupError(ValueError):
    """A safe, actionable startup diagnostic with no input contents."""


@dataclass(frozen=True)
class StartupEvent:
    client: str
    session_id: str
    cwd: Path
    source: str
    model: str | None = None
    permission_mode: str | None = None


def json_object(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise StartupError("Duplicate JSON field")
            result[key] = value
        return result

    def invalid_number(_):
        raise StartupError("Non-JSON number")

    if len(raw) > MAX_INPUT:
        raise StartupError("JSON exceeds 128 KiB")
    result = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_number)
    if not isinstance(result, dict):
        raise StartupError("Expected a JSON object")
    return result


def repository_root(cwd):
    """Locate the nearest repository boundary without requiring working Git metadata."""
    cwd = cwd.resolve(strict=True)
    if not cwd.is_dir():
        raise StartupError("Startup cwd must be a directory")
    return next((p for p in (cwd, *cwd.parents) if os.path.lexists(p / ".git")), None)


def checkout(cwd):
    """Resolve checkout identity; never inherit a Git selector from the caller."""
    boundary = repository_root(cwd)
    if boundary is None:
        return None
    result = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--path-format=absolute",
         "--show-toplevel", "--git-common-dir"],
        env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
        capture_output=True, text=True, timeout=2, check=False,
    )
    lines = result.stdout.splitlines()
    if result.returncode or len(lines) != 2:
        raise StartupError("Cannot resolve checkout identity")
    root, common = (Path(line).resolve(strict=True) for line in lines)
    if root != boundary or not common.is_dir():
        raise StartupError("Checkout identity does not match the nearest repository")
    return root, common


def read_record(root):
    """Reject links and special files before reading the bounded enrollment record."""
    directory = root / PROJECT_FILE.parent
    if not os.path.lexists(directory):
        return None
    if directory.is_symlink() or not directory.is_dir():
        raise StartupError("Enrollment directory must be a local directory")
    if os.name != "posix":
        raise StartupError("Enrollment reads require a qualified POSIX client")
    path = root / PROJECT_FILE
    if not os.path.lexists(path):
        raise StartupError("Enrollment record is missing")
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory_fd)
    finally:
        os.close(directory_fd)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise StartupError("Enrollment record must be a regular file")
        return json_object(stream.read(MAX_INPUT + 1))


def policy_digest(package):
    """Bind enrollment to the installed policy filenames and exact contents."""
    paths = sorted((package / "policies").glob("*.md"))
    if not paths or not (package / "policies/00-index.md").is_file():
        raise StartupError("Installed policy index is missing")
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def orient(event, package):
    root = repository_root(event.cwd)
    if root is None:
        return None
    record = read_record(root)
    if record is None:
        return None
    if type(record.get("schema_version")) is not int or record["schema_version"] != 1:
        raise StartupError("Unsupported enrollment schema")
    if not isinstance(record.get("project_id"), str) or not re.fullmatch(
            r"[a-zA-Z0-9_-]{1,128}", record["project_id"]):
        raise StartupError("Invalid project identity")
    clients = record.get("clients")
    if not isinstance(clients, list) or not clients or any(
            not isinstance(client, str) or not client for client in clients):
        raise StartupError("Invalid enrolled clients")
    if event.client not in clients:
        return None
    root, common = checkout(root)
    if record.get("repository_root") != str(root) or record.get("git_common_dir") != str(common):
        raise StartupError("Enrollment does not cover this checkout")
    if record.get("policy_digest") != policy_digest(package):
        raise StartupError("Installed policies differ from the accepted enrollment")
    client_file = package / "clients" / f"{event.client}.md"
    if not client_file.is_file():
        raise StartupError("Installed client instructions are missing")
    return (
        "Vibe Coding Workflow applies to this enrolled checkout. Read the client instructions at "
        f"{json.dumps(str(client_file))}, the policy index at "
        f"{json.dumps(str(package / 'policies/00-index.md'))}, and accepted project configuration at "
        f"{json.dumps(str(root / PROJECT_FILE))}. Load only triggered policies and applicable "
        "project/directory instructions. Activate silently; explain useful task steps, blockers or "
        "decisions. Startup supplies orientation only; it does not establish enforcement or readiness."
    )
