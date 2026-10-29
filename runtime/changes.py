"""Bounded D4 transactions; trusted coordinators verify approval and effect claims.

A manifest declares an approved effect contract. It is not a command sandbox or
an authentication mechanism. Receipts prove local file observations only.
"""

from contextlib import ExitStack, closing, contextmanager
from copy import deepcopy
from dataclasses import dataclass, replace
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sqlite3
import subprocess
import threading
import unicodedata
import uuid

from runtime import onboarding as d3
from runtime import state as task_state
from runtime import recovery_uses
from runtime.startup import (PROJECT_FILE, ProjectScope, StartupError, checkout,
                             policy_digest, runtime_settings, _canonical_freeze, _canonical_plain)

LOCK_ROOT = Path.home() / ".local/share/vcw-transactions"
MAX_JOURNAL = 8 * 1024 * 1024
LIMITATIONS = ["Approval, qualification and command effect claims require trusted coordinator verification; JSON does not authenticate intent.",
              "Declared command effects are not a sandbox; shared/global effects require manual resource serialization.",
              "Local file receipts and enrollment do not qualify client execution or future task readiness."]


class Pending(StartupError):
    """Safe intervention needed before the affected operation can continue."""


def _checkpoint(stage):
    """Crash-boundary injection point for disposable transaction tests."""


def _checkout(root):
    found = checkout(Path(root))
    d3._require(found is not None and found[0] == Path(root), "Selected checkout identity changed")
    code, raw = d3._git(found[0], "rev-parse", "--path-format=absolute", "--git-dir")
    d3._require(code == 0, "Cannot resolve worktree Git directory")
    git_dir = Path(os.fsdecode(raw).strip()).resolve(strict=True)
    d3._require(git_dir.is_dir(), "Worktree Git directory is unavailable")
    return found[0], git_dir, found[1]


def _evidence(value, many=False):
    if many:
        d3._require(isinstance(value, list) and len(value) <= d3.MAX_PATHS, "Invalid scoped evidence list")
        for item in value:
            d3._require(_evidence(item), "Evidence lists require non-null reference/hash objects")
        return bool(value)
    if value is None:
        return False
    d3._object(value, ("reference", "sha256"))
    d3._text(value["reference"])
    d3._hash(value["sha256"])
    return True


def _fp_schema(value):
    if value is not None:
        d3._object(value, ("sha256", "mode"))
        d3._hash(value["sha256"])
        d3._require(type(value["mode"]) is int and 0 <= value["mode"] <= 0o777,
                    "Invalid file permission mode")


def _target(value):
    d3._relative(value)
    d3._require(".git" not in Path(value).parts and value != str(PROJECT_FILE)
                and not Path(value).is_relative_to(PROJECT_FILE) and not PROJECT_FILE.is_relative_to(Path(value))
                and not any(part.startswith(".d4-") for part in Path(value).parts), "Reserved mutation target")
    return value


def _record(record, plan, current=True):
    d3._object(record, ("schema_version", "project_id", "clients", "repository_root", "git_common_dir", "policy_digest"), ("runtime",))
    d3._require(type(record["schema_version"]) is int and record["schema_version"] == 1,
                "Unsupported enrollment schema")
    d3._require(isinstance(record["project_id"], str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", record["project_id"]),
                "Invalid project identity")
    d3._require(record["repository_root"] == plan["identity"]["repository_root"]
                and record["git_common_dir"] == plan["identity"]["git_common_dir"], "Enrollment checkout changed")
    d3._require((not current or record["clients"] == plan["identity"]["clients"]) and bool(record["clients"])
                and all((d3.PACKAGE / "clients" / (client + ".md")).is_file() for client in record["clients"]),
                "Enrollment client selection changed")
    d3._hash(record["policy_digest"])
    d3._require(not current or record["policy_digest"] == policy_digest(d3.PACKAGE), "Enrollment policies are stale")
    legacy = (not current and isinstance(record.get("runtime"), dict) and
              type(record["runtime"].get("schema_version")) is int and record["runtime"]["schema_version"] == 1)
    inspected = dict(record, runtime=dict(record["runtime"], schema_version=2)) if legacy else record
    runtime = runtime_settings(inspected, d3.PACKAGE, Path(record["git_common_dir"]))
    if legacy:
        runtime = replace(runtime, schema_version=1)
    return ProjectScope(record["project_id"], Path(record["repository_root"]), Path(record["git_common_dir"]),
                        record["policy_digest"], runtime)


def _validate(request, plan):
    d3._bounded(request)
    d3._validate_proposal(plan)
    d3._object(request, ("schema_version", "manifest", "approval"), ("observations",))
    d3._require(type(request["schema_version"]) is int and request["schema_version"] == 1, "Unsupported D4 request schema")
    m, approval = request["manifest"], request["approval"]
    d3._object(m, ("schema_version", "transaction_id", "plan", "checkout", "pins", "authorization_reference", "approved_scope", "actions", "enrollment"))
    d3._require(type(m["schema_version"]) is int and m["schema_version"] == 1, "Unsupported D4 manifest schema")
    d3._require(isinstance(m["transaction_id"], str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", m["transaction_id"]),
                "Invalid transaction identity")
    d3._object(m["plan"], ("plan_id", "revision", "review_digest", "current_input_digest"))
    d3._require(m["plan"] == {k: plan[k] for k in m["plan"]} and type(m["plan"]["revision"]) is int,
                "Frozen plan identity, revision or digest changed")
    d3._require(plan["review_digest"] == d3._review_digest(plan), "Frozen D3 plan digest is invalid")
    root, git_dir, common = _checkout(Path(plan["identity"]["repository_root"]))
    d3._object(m["checkout"], ("repository_root", "git_dir", "git_common_dir"))
    d3._require(m["checkout"] == dict(repository_root=str(root), git_dir=str(git_dir), git_common_dir=str(common)),
                "Approved checkout identity changed")
    d3._object(m["pins"], ("package_pins", "toolkit_commit", "sources_digest"))
    d3._require(m["pins"] == dict(package_pins=plan["package_pins"], toolkit_commit=plan["sources"]["declared"]["toolkit"]["commit"],
                    sources_digest=d3._digest(plan["sources"])) and plan["package_pins"] == d3._package_pins(),
                "Source or installed package pins changed")
    d3._text(m["authorization_reference"])
    d3._strings(m["approved_scope"])
    ids = [a["id"] for a in plan["actions"]]
    d3._require("enrollment" not in ids and set(m["approved_scope"]) <= set(ids) | {"enrollment"}, "Unknown approved scope")
    d3._object(approval, ("reference", "evidence", "manifest_digest"))
    d3._require(approval["reference"] == m["authorization_reference"] and approval["manifest_digest"] == d3._digest(m),
                "Approval does not bind this exact manifest")
    _evidence(approval["evidence"], many=True)
    d3._require(isinstance(m["actions"], list) and [a.get("id") for a in m["actions"] if isinstance(a, dict)] == ids,
                "Manifest must retain exact D3 action order and IDs")
    paths, groups, last = set(), set(), None
    for original, action in zip(plan["actions"], m["actions"]):
        d3._object(action, ("id", "group", "resources", "preconditions", "effects", "recovery", "execution"))
        d3._text(action["group"])
        if action["group"] != last:
            d3._require(action["group"] not in groups, "Dependency groups must be contiguous")
            groups.add(action["group"])
            last = action["group"]
        d3._strings(action["resources"])
        d3._require(action["recovery"] in ("file-preimages", "manual"), "Unknown recovery method")
        for key in ("preconditions", "effects"):
            d3._require(isinstance(action[key], list) and len(action[key]) <= d3.MAX_PATHS, "Invalid effect/precondition set")
        seen = set()
        for condition in action["preconditions"]:
            d3._object(condition, ("path", "fingerprint"))
            _target(condition["path"])
            _fp_schema(condition["fingerprint"])
            d3._require(condition["path"] not in seen, "Duplicate precondition")
            seen.add(condition["path"])
        for effect in action["effects"]:
            d3._object(effect, ("path", "before", "after"))
            if original["target"] == str(PROJECT_FILE) and original["kind"] == "write":
                d3._require(effect["path"] == str(PROJECT_FILE), "Enrollment proposal target changed")
            else:
                _target(effect["path"])
            _fp_schema(effect["before"])
            _fp_schema(effect["after"])
            d3._require(effect["path"] not in paths, "Overlapping approved effects")
            paths.add(effect["path"])
        if original["kind"] in ("write", "delete"):
            d3._require(len(action["effects"]) == 1 and action["execution"] is None, "File action needs exactly one effect")
            effect = action["effects"][0]
            d3._require(effect["path"] == original["target"]
                        and (effect["before"]["sha256"] if effect["before"] else "absent") == original["before"]
                        and (effect["after"]["sha256"] if effect["after"] else "absent") == original["after"],
                        "File effects differ from the frozen D3 proposal")
        elif original["kind"] == "command":
            execution = action["execution"]
            d3._object(execution, ("argv", "timeout_seconds", "qualification", "idempotency"))
            d3._require(execution["argv"] == original["text"] and type(execution["timeout_seconds"]) is int
                        and 1 <= execution["timeout_seconds"] <= 300, "Command differs from the approved bounded proposal")
            _evidence(execution["qualification"])
            _evidence(execution["idempotency"])
        else:
            d3._require(action["execution"] is None, "External action requires manual operation")
    e = m["enrollment"]
    d3._object(e, ("record", "before", "requires", "qualification"))
    _fp_schema(e["before"])
    _record(e["record"], plan)
    d3._strings(e["requires"])
    mandatory = {a for row in plan["coverage"] if row["mandatory"] and row["applicability"] == "applicable" for a in row["actions"]}
    by_id = {a["id"]: a for a in plan["actions"]}
    while True:
        expanded = mandatory | {dep for key in mandatory for dep in by_id[key]["dependencies"]}
        if expanded == mandatory:
            break
        mandatory = expanded
    d3._require(mandatory <= set(e["requires"]) <= set(ids), "Enrollment must follow mandatory adoption dependencies")
    enrollment_action = next((a for a in plan["actions"] if a["target"] == str(PROJECT_FILE)), None)
    if enrollment_action is not None:
        d3._require(enrollment_action["kind"] == "write" and enrollment_action["scope"] == "checkout"
                    and d3.read_request(enrollment_action["text"].encode()) == e["record"],
                    "Final enrollment differs from its exact D3 proposal")
    q = e["qualification"]
    d3._object(q, ("requirements", "security_required"))
    d3._require(type(q["security_required"]) is bool, "Invalid security review applicability")
    d3._strings(q["requirements"])
    required = {r["id"] for r in plan["coverage"] if r["mandatory"] and r["applicability"] == "applicable"}
    d3._require(required <= set(q["requirements"]) <= {r["id"] for r in plan["requirements"]}, "Qualification must cover applicable mandatory requirements")
    if "observations" in request:
        o = request["observations"]
        d3._object(o, ("manifest_digest", "input_digest", "qualification", "task_reconciliation", "prior_compatibility"), ("command_reconciliation",))
        d3._require(o["manifest_digest"] == d3._digest(m), "Observations bind a different manifest")
        d3._hash(o["input_digest"])
        _evidence(o["task_reconciliation"])
        _evidence(o["prior_compatibility"])
        command_ids = {a["id"] for a in plan["actions"] if a["kind"] == "command"}
        commands = o.get("command_reconciliation", [])
        d3._require(isinstance(commands, list) and len(commands) <= len(command_ids), "Invalid command lifecycle proof list")
        seen_commands = set()
        for command in commands:
            d3._object(command, ("id", "attempt_id", "stopped", "evidence"))
            d3._require(command["id"] in command_ids and command["id"] not in seen_commands and command["stopped"] is True,
                        "Command reconciliation needs exact stopped command scope")
            seen_commands.add(command["id"])
            d3._require(isinstance(command["attempt_id"], str) and re.fullmatch(r"[0-9a-f]{32}", command["attempt_id"]), "Invalid command attempt identity")
            d3._require(_evidence(command["evidence"], many=True), "Command lifecycle proof requires evidence")
        proof = o["qualification"]
        d3._object(proof, ("requirements", "general_review", "security_review"))
        _evidence(proof["general_review"], many=True)
        _evidence(proof["security_review"], many=True)
        d3._require(isinstance(proof["requirements"], list), "Invalid qualification evidence")
        seen = set()
        for row in proof["requirements"]:
            d3._object(row, ("id", "evidence"))
            d3._require(row["id"] in q["requirements"] and row["id"] not in seen, "Unknown/duplicate qualification requirement")
            seen.add(row["id"])
            _evidence(row["evidence"], many=True)
    return root, git_dir


@contextmanager
def _lock(path):
    """No waits: an owned descriptor serializes this resource until the operation ends."""
    descriptor = d3._open_path(path, os.O_RDWR | os.O_CREAT)
    try:
        d3._private(os.fstat(descriptor))
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise StartupError("D4 transaction busy; retry the same bound request") from None
        yield descriptor
    finally:
        os.close(descriptor)


def _worktree_lock(git_dir):
    root = d3._plan_path(LOCK_ROOT)
    location = root / (hashlib.sha256(str(git_dir).encode()).hexdigest() + ".lock")
    if not location.exists():
        try:
            fd = os.open(location, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        except FileExistsError:
            pass
    return _lock(location)


_authority_context = threading.local()


def _held_authority_guards(directories):
    """Observe this thread's still-held locks, never a caller's asserted lock set."""
    held={}
    for observation in getattr(_authority_context,'held',()):
        if observation['active']:
            held.update(observation['bindings'])
    for directory in directories:
        directory=Path(directory)
        if directory not in held or not directory.exists():return False
        info=directory.lstat()
        if held[directory]!=(info.st_dev,info.st_ino):return False
    return True


def _authority_locations(directories):
    keys = set()
    for directory in directories:
        directory = Path(directory)
        d3._require(directory.is_absolute() and directory.resolve() == directory, "Unsafe state authority identity")
        keys.add("path:" + unicodedata.normalize("NFC", str(directory)).casefold())
        if directory.exists():
            task_state._private(directory, True)
            info = directory.stat()
            keys.add("inode:" + str(info.st_dev) + ":" + str(info.st_ino))
    if not keys:
        return []
    try:
        root = d3._plan_path(LOCK_ROOT)
    except FileExistsError:
        # A concurrent first user may create the root; re-run every ownership/path check.
        root = d3._plan_path(LOCK_ROOT)
    return [root / ("authority-" + hashlib.sha256(key.encode()).hexdigest()) for key in sorted(keys)]


def _authority_owner(location):
    try:
        owner = d3.read_request(d3._read_file(Path(str(location) + ".json"), d3.MAX_REQUEST, private=True))
    except FileNotFoundError:
        return None
    d3._object(owner, ("schema_version", "plan_dir", "transaction_id", "manifest_digest"))
    d3._require(type(owner["schema_version"]) is int and owner["schema_version"] == 1 and
                Path(owner["plan_dir"]).is_absolute() and str(Path(owner["plan_dir"]).resolve()) == owner["plan_dir"],
                "Unsafe authority operation owner")
    d3._text(owner["transaction_id"])
    d3._hash(owner["manifest_digest"])
    return owner


@contextmanager
def _authority_guards(directories, owner=None, *, observe=False):
    """Shared approved-authority exclusion; never locks or writes the old database."""
    directories=tuple(sorted(set(map(Path,directories))))
    locations = _authority_locations(directories)
    with ExitStack() as locks:
        for location in locations:
            lock = Path(str(location) + ".lock")
            try:
                descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                os.close(descriptor)
            except FileExistsError:
                pass
            locks.enter_context(_lock(lock))
            held = _authority_owner(location)
            if held is not None and held != owner and not observe:
                raise Pending("Shared state authority has an active or uncertain D4 operation; resume its bound journal")
        observation=dict(active=True,bindings={directory:(directory.lstat().st_dev,directory.lstat().st_ino)
            for directory in directories if directory.exists()})
        previous=getattr(_authority_context,'held',())
        _authority_context.held=(*previous,observation)
        try:yield locations
        finally:
            observation['active']=False
            _authority_context.held=previous


@contextmanager
def _authority_operation(path, root, journal, observation):
    records = _writer_records(path, root, journal)
    scopes = [_record(record, journal["plan"], current=False) for record in records]
    directories = {scope.runtime.state_dir for scope in scopes if scope.runtime is not None}
    owner = dict(schema_version=1, plan_dir=str(path), transaction_id=journal["transaction_id"],
                 manifest_digest=journal["manifest_digest"])
    with _authority_guards(directories, owner) as locations:
        d3._require(_writer_records(path, root, journal) == records, "Enrollment authorities changed while acquiring shared guards")
        if journal["state"] != "rolled_back":
            for record, scope in zip(records, scopes):
                _writers(journal["plan"], record, observation, scope=scope)
        for location in locations:
            _atomic(location.parent, location.name + ".json", json.dumps(owner, sort_keys=True).encode())
    previous = getattr(_authority_context, "directories", None)
    _authority_context.directories = directories
    complete = False
    try:
        yield
        complete = True
    finally:
        _authority_context.directories = previous
        unsettled = any(receipt.get("command") and not receipt["command"]["stopped"]
                        for receipt in journal["receipts"].values())
        if complete and not unsettled:
            with _authority_guards(directories, owner):
                for location in locations:
                    d3._require(_authority_owner(location) == owner, "D4 authority owner changed; preserve recovery evidence")
                    os.unlink(Path(str(location) + ".json"))
                if locations:
                    descriptor = d3._open_path(locations[0].parent, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)


def _owner_path(git_dir):
    return d3._plan_path(LOCK_ROOT) / (hashlib.sha256(str(git_dir).encode()).hexdigest() + ".command.json")


def _command_owner(git_dir):
    try:
        owner = d3.read_request(d3._read_file(_owner_path(git_dir), d3.MAX_REQUEST, private=True))
    except FileNotFoundError:
        return None
    d3._object(owner, ("schema_version", "plan_dir", "transaction_id", "id", "attempt_id"))
    d3._require(owner["schema_version"] == 1 and isinstance(owner["plan_dir"], str)
                and Path(owner["plan_dir"]).is_absolute() and str(Path(owner["plan_dir"]).resolve()) == owner["plan_dir"], "Unsafe command ownership marker")
    for field in ("transaction_id", "id", "attempt_id"):
        d3._text(owner[field])
    return owner


def _publish_command_owner(path, journal, action, attempt_id):
    location = _owner_path(journal["manifest"]["checkout"]["git_dir"])
    d3._require(_command_owner(journal["manifest"]["checkout"]["git_dir"]) is None, "Another unresolved command owns this checkout")
    owner = dict(schema_version=1, plan_dir=str(path), transaction_id=journal["transaction_id"], id=action["id"], attempt_id=attempt_id)
    _atomic(location.parent, location.name, json.dumps(owner, sort_keys=True).encode())


def _reconcile_command_lifecycles(path, journal):
    git_dir = journal["manifest"]["checkout"]["git_dir"]
    owner = _command_owner(git_dir)
    observation = _current_observation(journal)
    proofs = observation.get("command_reconciliation", []) if observation else []
    known_owner = owner is None
    for action_id, receipt in journal["receipts"].items():
        command = receipt.get("command")
        if not command:
            continue
        matching_owner = owner and owner["id"] == action_id and owner["attempt_id"] == command["attempt_id"]
        known_owner |= bool(matching_owner)
        if not command["stopped"]:
            proof = next((p for p in proofs if p["id"] == action_id and p["attempt_id"] == command["attempt_id"]), None)
            if not proof:
                raise Pending("Command lifecycle remains uncertain; verify this exact attempt and all writable descendants stopped before recovery")
            d3._require(proof["stopped"] is True and _evidence(proof["evidence"], many=True), "Invalid stopped command evidence")
            command["stopped"] = True
            _save(path, journal)
        if matching_owner:
            location = _owner_path(git_dir)
            os.unlink(location)
            descriptor = d3._open_path(location.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    if not known_owner:
        raise Pending("Unresolved checkout command marker has no matching receipt; preserve it for original-plan/manual recovery")


def _atomic(directory, name, raw, mode=0o600, target=False, guard=None, temporary=None, prepared=None):
    """Replace one bounded regular file and durably publish its directory entry."""
    d3._require(len(raw) <= MAX_JOURNAL, "D4 artifact size limit exceeded")
    fd = d3._open_path(directory, os.O_RDONLY | os.O_DIRECTORY)
    temporary = temporary or ".d4-" + uuid.uuid4().hex
    created = False
    created_identity = None
    try:
        output = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=fd)
        created = True
        created_info = os.fstat(output)
        created_identity = (created_info.st_dev,created_info.st_ino)
        with os.fdopen(output, "wb") as stream:
            stream.write(raw)
            if target:
                _checkpoint("temp_write")
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
            if prepared is not None:
                os.fsync(fd)
                prepared(os.fstat(stream.fileno()))
            if target:
                _checkpoint("temp_fsync")
        if guard is not None:
            guard()
        current_parent = d3._open_path(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            d3._require(os.fstat(current_parent).st_ino == os.fstat(fd).st_ino and os.fstat(current_parent).st_dev == os.fstat(fd).st_dev,
                        "Target directory changed during replacement")
        finally:
            os.close(current_parent)
        if prepared is not None:
            observed = os.stat(temporary,dir_fd=fd,follow_symlinks=False)
            if (observed.st_dev,observed.st_ino) != created_identity or not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
                raise Pending("Prepared temporary physical identity changed; preserve it")
            descriptor=os.open(temporary,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
            with os.fdopen(descriptor,"rb") as stream:
                current=os.fstat(stream.fileno())
                if ((current.st_dev,current.st_ino) != created_identity or stream.read(len(raw)+1) != raw or stat.S_IMODE(current.st_mode) != mode):
                    raise Pending("Prepared temporary bytes or mode changed; preserve it")
        os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
        if target:
            _checkpoint("rename")
        os.fsync(fd)
        if target:
            _checkpoint("parent_fsync")
    finally:
        if created:
            try:
                safe = True
                if prepared is not None:
                    info=os.stat(temporary,dir_fd=fd,follow_symlinks=False)
                    safe = stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and (info.st_dev,info.st_ino) == created_identity
                    if safe:
                        descriptor=os.open(temporary,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
                        with os.fdopen(descriptor,"rb") as stream:
                            safe=raw.startswith(stream.read(len(raw)+1))
                if safe: os.unlink(temporary, dir_fd=fd)
            except FileNotFoundError:
                pass
        os.close(fd)


def _journal(path):
    try:
        raw = d3._read_file(path / "transaction.json", MAX_JOURNAL, private=True)
    except FileNotFoundError:
        return None
    result = d3.read_request(raw, limit=MAX_JOURNAL)
    d3._object(result, ("schema_version", "transaction_id", "manifest_digest", "manifest", "approval", "plan", "state", "receipts", "enrollment", "blocked", "directories", "observations"))
    if result.get("schema_version") == 2:
        return _scoped_journal_shape(result)
    d3._require(result["schema_version"] == 1 and result["state"] in
                ("prepared", "applying", "interrupted", "applied", "blocked", "rollback_partial", "rolled_back"), "Invalid D4 journal")
    return result


def _save(path, journal):
    with _lock(path / ".d4-journal.lock"):
        if (path / "transaction.json").exists():
            d3._private((path / "transaction.json").lstat())
        _atomic(path, "transaction.json", json.dumps(journal, sort_keys=True, ensure_ascii=True).encode() + b"\n")


def _load_journal(path):
    lock = path / ".d4-journal.lock"
    if not lock.exists():
        try:
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        except FileExistsError:
            pass
    with _lock(lock):
        return _journal(path)


def _fingerprint(root, relative):
    path = root / relative
    try:
        fd = d3._open_path(path, os.O_RDONLY)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > d3.MAX_FILE or info.st_mode & 0o7000:
            raise Pending("Target must be a bounded regular file without links or special permissions")
        raw = stream.read(d3.MAX_FILE + 1)
        d3._require(len(raw) <= d3.MAX_FILE, "Target file size limit exceeded")
        return {"sha256": hashlib.sha256(raw).hexdigest(), "mode": stat.S_IMODE(info.st_mode)}


def _backup(path, root, relative, expected, name):
    actual = _fingerprint(root, relative)
    if actual != expected:
        raise Pending("Current file differs from the approved preimage")
    if expected is None:
        return None
    raw = d3._read_file(root / relative, d3.MAX_FILE)
    d3._require(hashlib.sha256(raw).hexdigest() == expected["sha256"], "File changed while backing up")
    backup = path / name
    if os.path.lexists(backup):
        d3._require(hashlib.sha256(d3._read_file(backup, d3.MAX_FILE, private=True)).hexdigest() == expected["sha256"],
                    "Existing recovery backup differs from the approved original")
    else:
        _atomic(path, name, raw)
    _checkpoint("backup")
    return name


def _replace(root, relative, raw, fingerprint, expected, temporary=None):
    if _fingerprint(root, relative) != expected:
        raise Pending("Target changed outside this transaction; preserve it for manual reconciliation")
    path = root / relative
    if fingerprint is None:
        if expected is not None:
            directory = d3._open_path(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.unlink(path.name, dir_fd=directory)
                _checkpoint("rename")
                os.fsync(directory)
                _checkpoint("parent_fsync")
            finally:
                os.close(directory)
    else:
        def unchanged():
            if _fingerprint(root, relative) != expected:
                raise Pending("Target changed while preparing replacement; preserve the external edit")
        _atomic(path.parent, path.name, raw, fingerprint["mode"], target=True, guard=unchanged, temporary=temporary)
    if _fingerprint(root, relative) != fingerprint:
        raise Pending("Observed operation result differs from the intended postimage")


def _scoped_replace(path, root, relative, raw, before, after, receipt, journal):
    """Keep physical ownership durable across schema-2 replacement crash boundaries."""
    location = root / relative
    def binding():
        if not os.path.lexists(location):
            return None
        d3._no_links(location)
        info = location.stat()
        return dict(device=info.st_dev, inode=info.st_ino)
    actual = _fingerprint(root, relative)
    if actual is None and after is None and (before is None or receipt.get("delete_intent") is True):
        receipt["result_binding"] = None
        _save(path,journal)
        return
    if actual == after and after is not None:
        owned = receipt.get("result_binding") or receipt["prepared_binding"]
        if owned is None and before == after and receipt.get("before_binding") == binding():
            owned = receipt["before_binding"]
        if owned is None or binding() != owned:
            raise Pending("Scoped output physical ownership is ambiguous; preserve the current file")
        receipt["result_binding"] = owned
        _save(path, journal)
        return
    if actual != before:
        raise Pending("Scoped target changed outside this transaction")
    if "before_binding" in receipt and binding() != receipt["before_binding"]:
        raise Pending("Scoped preimage physical identity changed")
    expected_binding = binding()
    temporary = location.parent / receipt["temporary"]
    if os.path.lexists(temporary):
        info = temporary.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                dict(device=info.st_dev, inode=info.st_ino) != receipt["prepared_binding"]):
            raise Pending("Scoped temporary ownership is unverified; preserve it")
        directory = d3._open_path(temporary.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.unlink(temporary.name, dir_fd=directory)
            os.fsync(directory)
        finally:
            os.close(directory)
    def unchanged():
        if _fingerprint(root, relative) != before or binding() != expected_binding:
            raise Pending("Scoped target physical identity changed before replacement")
    def prepared(info):
        receipt["prepared_binding"] = dict(device=info.st_dev, inode=info.st_ino)
        _save(path, journal)
        _checkpoint("scoped_temp_recorded")
    if after is None:
        unchanged()
        receipt["delete_intent"] = True
        _save(path,journal)
        _replace(root, relative, raw, after, before, receipt["temporary"])
        receipt["result_binding"] = None
    else:
        _atomic(location.parent, location.name, raw, after["mode"], target=True,
                guard=unchanged, temporary=receipt["temporary"], prepared=prepared)
        if _fingerprint(root, relative) != after or binding() != receipt["prepared_binding"]:
            raise Pending("Scoped output differs from its prepared physical identity")
        receipt["result_binding"] = receipt["prepared_binding"]
    _save(path, journal)


def _restore(path, root, relative, receipt, before, after):
    actual = _fingerprint(root, relative)
    if actual == before:
        return
    if actual != after:
        raise Pending("Unrecognized current file; preserve user changes and reconcile manually")
    raw = b"" if before is None else d3._read_file(path / receipt["backup"], d3.MAX_FILE, private=True)
    if before is not None:
        d3._require(hashlib.sha256(raw).hexdigest() == before["sha256"], "Recovery backup is corrupt")
    _replace(root, relative, raw, before, after, receipt["temporary"])


def _owned(journal):
    return {effect["path"]: (effect, receipt) for action in journal["manifest"]["actions"]
            for effect, receipt in zip(action["effects"], journal["receipts"].get(action["id"], {}).get("files", []))}


def _recovery_files(path, root, journal, cleanup=True):
    manifest = journal["manifest"]
    d3._require(journal["transaction_id"] == manifest["transaction_id"] and isinstance(journal["receipts"], dict)
                and set(journal["receipts"]) <= {a["id"] for a in manifest["actions"]}, "Invalid transaction receipt identities")
    d3._require(isinstance(journal["directories"], dict) and len(journal["directories"]) <= d3.MAX_PATHS, "Invalid parent directory receipts")
    allowed_parents = {str(parent) for action in manifest["actions"] for effect in action["effects"]
                       for parent in Path(effect["path"]).parents if str(parent) != "."} | {str(PROJECT_FILE.parent)}
    for name, stored in journal["directories"].items():
        d3._require(name in allowed_parents, "Unknown parent directory recovery scope")
        d3._object(stored, ("status", "device", "inode"))
        d3._require(stored["status"] in ("prepared", "owned", "retained", "removed")
                    and all(value is None or type(value) is int for value in (stored["device"], stored["inode"])), "Invalid parent directory ownership")
    temporary_files = []
    for index, action in enumerate(manifest["actions"]):
        receipt = journal["receipts"].get(action["id"])
        if receipt is None:
            continue
        d3._object(receipt, ("status", "files", "returncode"), ("command",))
        d3._require(receipt["status"] in ("prepared", "started", "completed", "rolled_back")
                    and (receipt["returncode"] is None or type(receipt["returncode"]) is int), "Invalid action receipt")
        original = journal["plan"]["actions"][index]
        if "command" in receipt:
            command = receipt["command"]
            d3._object(command, ("attempt_id", "stopped"))
            d3._require(original["kind"] == "command" and isinstance(command["attempt_id"], str)
                        and re.fullmatch(r"[0-9a-f]{32}", command["attempt_id"]) and type(command["stopped"]) is bool,
                        "Invalid durable command lifecycle")
        d3._require(original["kind"] != "command" or receipt["status"] == "prepared" or "command" in receipt,
                    "Command receipt lacks recoverable attempt identity")
        enrollment_action = original["target"] == str(PROJECT_FILE)
        d3._require(isinstance(receipt["files"], list) and len(receipt["files"]) == (0 if enrollment_action else len(action["effects"])),
                    "Incomplete durable backup receipt")
        for number, (effect, stored) in enumerate(zip(action["effects"], receipt["files"])):
            d3._object(stored, ("backup", "temporary"))
            expected_backup = "backup-" + str(index) + "-" + str(number) if effect["before"] else None
            d3._require(stored["backup"] == expected_backup and stored["temporary"] ==
                        ".d4-" + journal["transaction_id"] + "-" + str(index) + "-" + str(number), "Invalid recovery material reference")
            candidates = []
            if expected_backup:
                candidates.append(d3._read_file(path / expected_backup, d3.MAX_FILE, private=True))
                d3._require(hashlib.sha256(candidates[-1]).hexdigest() == effect["before"]["sha256"], "Recovery backup is corrupt")
            if original["kind"] == "write":
                candidates.append(original["text"].encode())
            temporary_files.append((effect["path"], stored["temporary"], candidates))
    receipt = journal["enrollment"]
    if receipt:
        d3._object(receipt, ("before", "after", "backup", "status", "temporary"))
        d3._require(receipt["before"] == manifest["enrollment"]["before"] and receipt["status"] in
                    ("prepared", "inactive", "activating", "active", "restoring", "restored")
                    and receipt["backup"] == ("enrollment.backup" if receipt["before"] else None)
                    and receipt["temporary"] == ".d4-" + journal["transaction_id"] + "-enrollment", "Invalid enrollment receipt")
        raw, mode = _enrollment_postimage(journal)
        d3._require(receipt["after"] == {"sha256": hashlib.sha256(raw).hexdigest(), "mode": mode}, "Invalid enrollment postimage receipt")
        candidates = [raw]
        if receipt["backup"]:
            candidates.append(d3._read_file(path / receipt["backup"], d3.MAX_FILE, private=True))
            d3._require(hashlib.sha256(candidates[-1]).hexdigest() == receipt["before"]["sha256"], "Prior enrollment backup is corrupt")
        temporary_files.append((str(PROJECT_FILE), receipt["temporary"], candidates))
    if not cleanup:
        return
    for relative, name, candidates in temporary_files:
        temporary = root / Path(relative).parent / name
        if not os.path.lexists(temporary):
            continue
        _fingerprint(root, str(temporary.relative_to(root)))
        raw = d3._read_file(temporary, d3.MAX_FILE)
        if not any(candidate.startswith(raw) for candidate in candidates):
            raise Pending("Transaction temporary contains unrecognized edits; preserve it for manual reconciliation")
        directory = d3._open_path(temporary.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.unlink(name, dir_fd=directory)
            os.fsync(directory)
        finally:
            os.close(directory)


def _fresh(plan, journal=None, *, external_owned=()):
    """Normalize only receipt-owned paths; unrelated inputs retain D3 freshness checks."""
    root = Path(plan["identity"]["repository_root"])
    current = d3._snapshot(root, d3._snapshot_targets(plan))
    previous = plan["identity"]
    owned = _owned(journal) if journal else {}
    owned.update({key:(None,None) for key in external_owned})
    if journal and journal["enrollment"]:
        owned[str(PROJECT_FILE)] = (None, None)
    for key in ("repository_root", "git_common_dir", "head", "index_digest"):
        d3._require(current[key] == previous[key], "Unrelated checkout identity/index changed")
    def external_inventory(rows):
        return [row for row in rows if row[3:] not in owned]
    d3._require(external_inventory(current["dirty_inventory"]) == external_inventory(previous["dirty_inventory"])
                and set(current["paths"]) - owned.keys() == set(previous["paths"]) - owned.keys(),
                "Unrelated current checkout inputs changed")
    old, new = previous["fingerprints"], current["fingerprints"]
    for key in old.keys() | new.keys():
        relative = key
        if key.startswith("instruction:"):
            location = Path(key[len("instruction:"):])
            relative = str(location.relative_to(root)) if location.is_relative_to(root) else key
        if relative not in owned:
            d3._require(old.get(key, {"status": "absent"}) == new.get(key, {"status": "absent"}), "Unrelated current input fingerprint changed")
    if journal is None:
        changes, _, _ = d3._current(plan)
        # Sources are checked per dependent action; all unrelated checkout inputs must match.
        d3._require(not [c for c in changes if not c.startswith("source:")], "Current D3 inputs are stale")


def _action_blockers(plan, action, manifest, completed, observed):
    original = next(a for a in plan["actions"] if a["id"] == action["id"])
    if action["id"] not in manifest["approved_scope"]:
        return "Action has no scoped approval"
    if not set(original["dependencies"]) <= completed:
        return "Required dependency has not completed"
    if original["scope"] != "checkout" or action["resources"] != ["checkout"]:
        return "Shared/global or unknown resources require manual serialization"
    if action["recovery"] != "file-preimages" or not action["effects"]:
        return "Complete bounded effects and recoverable file preimages are required"
    for decision in plan["decisions"]:
        if (decision["id"] in original["decision_ids"] or action["id"] in decision["affected_actions"]) and decision["disposition"] in ("pending", "proposed"):
            return "An applicable scoped decision remains unresolved"
    if original["kind"] == "external":
        return "External effects need the approved manual procedure"
    if original["kind"] == "command" and not action["execution"]["qualification"]:
        return "Coordinator qualification of complete command effects/recovery is missing"
    source_blockers = {row["scope"] for row in d3._source_blockers(plan, observed)}
    for row in plan["coverage"]:
        if action["id"] in row["actions"]:
            if row["blocker"] or row["outcome"] == "blocked":
                return "The applicable adoption requirement remains blocked"
            if "sources" in source_blockers or "catalog" in source_blockers or "source:" + row["source"] in source_blockers:
                return "The applicable pinned Toolkit source/provenance is unavailable"
    return None


def _legacy_writers(scope):
    """Inspect schema-1 retirement only; never initialize, adopt pins or open writable state."""
    from runtime.evidence import _read
    from runtime.startup import json_object
    # Current path/artifact safety checks apply without making the old DB runnable.
    inspected = replace(scope, runtime=replace(scope.runtime, schema_version=task_state.SCHEMA_VERSION))
    try:
        path = task_state._path(inspected)
        task_state._sidecars(path)
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0.1)) as db:
            db.execute("pragma trusted_schema=off")
            db.execute("pragma query_only=on")
            db.execute("begin")
            task_state._schema(db, version=1)
            checkouts = {}
            for scope_id, project_id, root, common, generation in db.execute("select * from checkouts"):
                d3._require(len(checkouts) < 1024, "Legacy checkout inspection exceeds its bound")
                for value in (project_id, root, common):
                    task_state._text(value, "legacy checkout identity", 4096)
                d3._require(Path(root).is_absolute() and str(Path(root).resolve()) == root and
                            Path(common).is_absolute() and str(Path(common).resolve()) == common,
                            "Legacy checkout identity is not canonical")
                task_state._integer(generation, "legacy checkout generation")
                identity = ProjectScope(project_id, Path(root), Path(common), scope.policy_digest)
                d3._require(scope_id == task_state._scope_id(identity), "Legacy checkout identity is corrupt")
                checkouts[scope_id] = (root, common)
            rows = db.execute("select scope_id,client,session_id,task_id,data from tasks limit 1025").fetchall()
            d3._require(len(rows) <= 1024 and sum(len(row[4]) for row in rows) <= 4 * 1024 * 1024,
                        "Legacy task inspection exceeds its bound")
            active = False
            identities = set()
            for scope_id, client, session, task_id, raw in rows:
                d3._require(scope_id in checkouts, "Legacy task has no checkout identity")
                json_object(raw)
                task = task_state._task(db, scope_id, client, session, task_id)
                d3._require("delegation" not in task, "Legacy task contains unsupported delegation ownership state")
                d3._require(task["pins"]["schema_version"] == 1, "Legacy task pins have an incompatible schema")
                for field in ("policy_digest", "runtime_digest"):
                    d3._hash(task["pins"][field])
                identities.add((scope_id, client, session, task_id))
                unresolved = [a["id"] for a in task.get("evidence", {}).get("attempts", [])
                              if a["status"] in {"reserved", "running", "uncertain"}]
                shared_git = checkouts[scope_id][1] == str(scope.git_common_dir)
                if not unresolved and (task["mode"] != "editable" or not shared_git):
                    continue
                retirement = task.get("retirement")
                if task["state"] != "cancelled" or not retirement:
                    active = True
                    continue
                d3._hash(retirement["proof_digest"])
                proof = _read(inspected, retirement["proof"])
                task_state._fields(proof, ("version", "kind", "identity", "expected_revision", "expected_pins",
                    "observed_turn_id", "stopped", "descendants_stopped", "attempt_ids", "observation_ref", "coordinator_ref"))
                task_state._integer(proof["expected_revision"], "legacy stopped revision", 1)
                task_state._fields(proof["expected_pins"], ("schema_version", "policy_digest", "runtime_digest"))
                d3._require(type(proof["expected_pins"]["schema_version"]) is int,
                            "Legacy stopped-writer proof pins are corrupt")
                d3._require(type(proof["version"]) is int and proof["version"] == 1 and
                    proof["kind"] == "stopped-writer-reconciliation" and proof["stopped"] is True and
                    proof["descendants_stopped"] is True and proof["identity"] ==
                    {key: task[key] for key in ("client", "session_id", "task_id", "scope_ref")} and
                    proof["expected_pins"] == task["pins"] and proof["expected_revision"] == retirement["previous_revision"] and
                    retirement["previous_revision"] == task["revision"] - 1 and proof["observed_turn_id"] == task["turn_id"] and
                    proof["attempt_ids"] == unresolved and all(proof[key] == retirement[key]
                    for key in ("observation_ref", "coordinator_ref")), "Legacy stopped-writer proof binding failed")
            for identity in db.execute("select scope_id,client,session_id,task_id from bindings"):
                d3._require(identity in identities, "Legacy task binding is corrupt")
            for table in ("turns", "receipts"):
                d3._require(not db.execute("select 1 from " + table +
                    " where scope_id is null or scope_id not in (select scope_id from checkouts) limit 1").fetchone(),
                    "Legacy event checkout binding is corrupt")
            return active
    except (StartupError, OSError, sqlite3.Error, ValueError, TypeError, KeyError, RecursionError):
        raise Pending("Legacy runtime state or retained stopped-writer proof is unavailable, unsafe or incompatible") from None


def _writers(plan, prior, observation, scope=None):
    scope = scope or _record(prior, plan, current=False)
    if scope.runtime is None:
        return
    if not observation or not observation["task_reconciliation"]:
        raise Pending("Confirm stopped writers and reconcile their task/evidence records")
    if scope.runtime.schema_version == 1:
        if _legacy_writers(scope):
            raise Pending("Affected legacy task writers remain active or unreconciled; use their old pinned runtime first")
        return
    active = False
    with task_state._database(scope) as db:
        if db is None:
            return
        rows = db.execute("select t.scope_id,t.client,t.session_id,t.task_id from tasks t join checkouts c on t.scope_id=c.scope_id where c.repository_root=? and c.git_common_dir=?",
                          (str(scope.repository_root), str(scope.git_common_dir))).fetchall()
        for scope_id, client, session, task_id in rows:
            task = task_state._task(db, scope_id, client, session, task_id)
            active |= task["mode"] == "editable" and task["state"] != "cancelled"
        from runtime.delegation import _ledger, _held_conflict, _linked_attempt
        affected = [dict(kind="path", key=str(scope.repository_root), mode="write"),
                    dict(kind="git", key=str(scope.git_common_dir), mode="write")]
        from runtime.delegation import _claims
        records = _ledger(scope, db)
        for record in records:
            if record["data"]["status"] != "settled" and _held_conflict(_claims(affected), record["data"]["claims"]):
                active = True
        for scope_id, client, session, task_id in db.execute("select scope_id,client,session_id,task_id from tasks"):
            task = task_state._task(db, scope_id, client, session, task_id)
            active |= not task.get("retirement") and any(a["status"] in {"reserved", "running", "uncertain"} and
                        _linked_attempt(scope, scope_id, task, a, records) is None
                        for a in task.get("evidence", {}).get("attempts", []))
    if active:
        raise Pending("Affected task writers remain active or unreconciled; stop and reconcile them first")


def _writer_records(path, root, journal):
    records = [journal["manifest"]["enrollment"]["record"]]
    actual = _fingerprint(root, str(PROJECT_FILE))
    if actual is not None:
        stored = journal["enrollment"]
        allowed = [journal["manifest"]["enrollment"]["before"]] if stored is None else [stored["after"]]
        if stored and stored["status"] in ("prepared", "restoring", "restored"):
            allowed.append(stored["before"])
        if actual not in allowed:
            raise Pending("Enrollment changed externally; preserve it and supporting configuration")
        records.append(d3.read_request(d3._read_file(root / PROJECT_FILE, d3.MAX_FILE)))
    if journal["enrollment"] and journal["enrollment"]["backup"]:
        records.append(d3.read_request(d3._read_file(path / journal["enrollment"]["backup"], d3.MAX_FILE, private=True)))
    return records


def _guard_writers(path, root, journal, observation):
    records = _writer_records(path, root, journal)
    covered = getattr(_authority_context, "directories", None)
    if covered is not None:
        d3._require({Path(record["runtime"]["state_dir"]) for record in records if record.get("runtime")} <= covered,
                    "Enrollment authority changed outside the protected operation")
    seen = set()
    for record in records:
        key = d3._digest(record.get("runtime"))
        if key not in seen:
            _writers(journal["plan"], record, observation)
            seen.add(key)


def _ensure_parents(path, root, relative, journal):
    parts = Path(relative).parent.parts
    for number in range(1, len(parts) + 1):
        name = str(Path(*parts[:number]))
        location = root / name
        if journal["schema_version"] == 2:
            name = str(location)
        stored = journal["directories"].get(name)
        try:
            descriptor = d3._open_path(location, os.O_RDONLY | os.O_DIRECTORY)
        except FileNotFoundError:
            if stored and stored["status"] == "owned":
                raise Pending("A transaction-owned parent directory disappeared; reconcile it before writing")
            journal["directories"][name] = {"status": "prepared", "device": None, "inode": None}
            _save(path, journal)
            parent = d3._open_path(location.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                try:
                    os.mkdir(location.name, mode=0o700, dir_fd=parent)
                except FileExistsError:
                    raise Pending("A parent directory appeared during preparation; preserve it and retry reconciliation") from None
                os.fsync(parent)
                _checkpoint("directory_created")
                descriptor = os.open(location.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                info = os.fstat(descriptor)
                journal["directories"][name] = {"status": "owned", "device": info.st_dev, "inode": info.st_ino}
                os.close(descriptor)
                _save(path, journal)
                _checkpoint("directory_recorded")
            finally:
                os.close(parent)
        else:
            try:
                info = os.fstat(descriptor)
                if stored and stored["status"] == "owned" and (info.st_dev, info.st_ino) != (stored["device"], stored["inode"]):
                    raise Pending("Parent directory ownership changed; preserve it before further mutation")
                if stored and stored["status"] == "prepared":
                    journal["directories"][name] = {"status": "retained", "device": info.st_dev, "inode": info.st_ino}
                    _save(path, journal)
            finally:
                os.close(descriptor)


def _restore_directories(path, root, journal):
    for name in sorted(journal["directories"], key=lambda value: len(Path(value).parts), reverse=True):
        stored = journal["directories"][name]
        if stored["status"] not in ("owned", "prepared"):
            continue
        location = root / name
        try:
            descriptor = d3._open_path(location, os.O_RDONLY | os.O_DIRECTORY)
        except FileNotFoundError:
            stored["status"] = "removed"
            continue
        try:
            if stored["status"] == "prepared":
                stored["status"] = "retained"
                continue
            info = os.fstat(descriptor)
            if (info.st_dev, info.st_ino) != (stored["device"], stored["inode"]):
                stored["status"] = "retained"
                continue
        finally:
            os.close(descriptor)
        parent = d3._open_path(location.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            try:
                os.rmdir(location.name, dir_fd=parent)
            except OSError:
                stored["status"] = "retained"
            else:
                os.fsync(parent)
                stored["status"] = "removed"
        finally:
            os.close(parent)
    _save(path, journal)


def _deactivate(path, root, journal, observation):
    _guard_writers(path, root, journal, observation)
    e = journal["manifest"]["enrollment"]
    stored = journal["enrollment"]
    if stored is not None:
        actual = _fingerprint(root, str(PROJECT_FILE))
        accepted = [None, stored["before"], stored["after"]] if stored["status"] == "prepared" else [None, stored["after"]]
        if actual not in accepted:
            raise Pending("Enrollment changed externally; preserve it and reconcile ownership")
        if stored["status"] == "prepared" and actual == stored["before"]:
            _guard_writers(path, root, journal, observation)
            _replace(root, str(PROJECT_FILE), b"", None, stored["before"])
            stored["status"] = "inactive"
            _save(path, journal)
        return
    actual = _fingerprint(root, str(PROJECT_FILE))
    if actual != e["before"]:
        raise Pending("Existing enrollment does not match the approved record")
    if actual is not None:
        prior = d3.read_request(d3._read_file(root / PROJECT_FILE, d3.MAX_FILE))
        _writers(journal["plan"], prior, observation)
    backup = _backup(path, root, str(PROJECT_FILE), actual, "enrollment.backup")
    raw, mode = _enrollment_postimage(journal)
    after = {"sha256": hashlib.sha256(raw).hexdigest(), "mode": mode}
    journal["enrollment"] = {"before": actual, "after": after, "backup": backup, "status": "prepared",
                             "temporary": ".d4-" + journal["transaction_id"] + "-enrollment"}
    _save(path, journal)
    if actual is not None:
        _guard_writers(path, root, journal, observation)
        _replace(root, str(PROJECT_FILE), b"", None, actual)
    journal["enrollment"]["status"] = "inactive"
    _save(path, journal)


def observation_digest(manifest):
    """Bind coordinator observations to current checkout, effect files and enrollment."""
    root = Path(manifest["checkout"]["repository_root"])
    paths = sorted({str(PROJECT_FILE)} | {e["path"] for a in manifest["actions"] for e in a["effects"]})
    return d3._digest({"identity": d3._snapshot(root, paths),
        "effects": {name: _fingerprint(root, name) for name in paths},
        "enrollment": _fingerprint(root, str(PROJECT_FILE)), "package_pins": d3._package_pins()})


def _current_observation(journal):
    current = observation_digest(journal["manifest"])
    return next((o for o in reversed(journal["observations"]) if o["input_digest"] == current), None)


def _enrollment_postimage(journal):
    original = next((a for a in journal["plan"]["actions"] if a["target"] == str(PROJECT_FILE)), None)
    if original:
        action = next(a for a in journal["manifest"]["actions"] if a["id"] == original["id"])
        return original["text"].encode(), action["effects"][0]["after"]["mode"]
    return json.dumps(journal["manifest"]["enrollment"]["record"], sort_keys=True, ensure_ascii=True).encode() + b"\n", 0o600


def _qualification(journal):
    plan, manifest = journal["plan"], journal["manifest"]
    e = manifest["enrollment"]
    if "enrollment" not in manifest["approved_scope"]:
        return "Enrollment activation/recovery lacks scoped approval"
    observation = _current_observation(journal)
    if observation is None:
        return "Collect adoption qualification/reviews and bind observations to current inputs before final enrollment"
    rows = {row["id"]: row["evidence"] for row in observation["qualification"]["requirements"]}
    required_actions = set(e["requires"])
    required_decisions = {d for a in plan["actions"] if a["id"] in required_actions for d in a["decision_ids"]}
    for requirement in plan["requirements"]:
        coverage = next((r for r in plan["coverage"] if r["id"] == requirement["id"]), None)
        if coverage is None:
            return "Complete pinned Toolkit/policy coverage is missing"
        if requirement["mandatory"] and coverage["applicability"] == "applicable" and not rows.get(requirement["id"]):
            return "A mandatory adoption requirement lacks scoped qualification evidence"
        relevant = coverage["applicability"] == "applicable" and (requirement["mandatory"] or bool(set(coverage["actions"]) & required_actions))
        if relevant:
            required_decisions.update(coverage["decision_ids"])
            if coverage["blocker"] or coverage["outcome"] == "blocked":
                return "Required adoption coverage contains unresolved blockers"
    q = observation["qualification"]
    if not q["general_review"] or (e["qualification"]["security_required"] and not q["security_review"]):
        return "Required general/security review evidence is missing"
    if not plan["semantic_assessment"] or not all(plan["semantic_assessment"].get(k) for k in
            ("complete", "catalog_complete", "conflicts_checked", "instructions_checked", "source_provenance_checked")):
        return "Complete semantic assessment and catalog coverage are required before enrollment"
    if any(d["disposition"] in ("pending", "proposed") and (d["id"] in required_decisions or bool(set(d["affected_actions"]) & required_actions)) for d in plan["decisions"]):
        return "Unresolved adoption decisions prevent enrollment"
    if d3._source_blockers(plan, d3._sources(plan["sources"]["declared"])):
        return "Pinned Toolkit source coverage is incomplete"
    return None


def _apply_action(path, root, journal, original, action, observation, checkout_lock):
    receipt = journal["receipts"].get(action["id"])
    outputs = {e["path"]: e["after"] for e in action["effects"]} if receipt else {}
    for condition in action["preconditions"]:
        if condition["path"] in outputs and _fingerprint(root, condition["path"]) == outputs[condition["path"]]:
            continue
        if _fingerprint(root, condition["path"]) != condition["fingerprint"]:
            raise Pending("An approved action precondition changed")
    receipt = journal["receipts"].get(action["id"])
    if receipt is None or receipt["status"] != "completed":
        _guard_writers(path, root, journal, observation)
        enrollment = journal["enrollment"]
        if enrollment and _fingerprint(root, str(PROJECT_FILE)) == enrollment["after"]:
            _replace(root, str(PROJECT_FILE), b"", None, enrollment["after"])
            enrollment["status"] = "inactive"
            _save(path, journal)
    if receipt is None:
        files = []
        for index, effect in enumerate(action["effects"]):
            backup = _backup(path, root, effect["path"], effect["before"],
                             "backup-" + str(journal["manifest"]["actions"].index(action)) + "-" + str(index))
            files.append({"backup": backup, "temporary": ".d4-" + journal["transaction_id"] + "-"
                          + str(journal["manifest"]["actions"].index(action)) + "-" + str(index)})
        receipt = {"status": "prepared", "files": files, "returncode": None}
        journal["receipts"][action["id"]] = receipt
        _save(path, journal)
        _checkpoint("prepared")
    actual = [_fingerprint(root, effect["path"]) for effect in action["effects"]]
    before = [e["before"] for e in action["effects"]]
    after = [e["after"] for e in action["effects"]]
    if any(value not in (old, new) for value, old, new in zip(actual, before, after)):
        raise Pending("Action output changed externally; preserve the unrecognized state")
    command = original["kind"] == "command"
    if receipt["status"] == "completed":
        if actual != after:
            raise Pending("Completed action output no longer matches its receipt")
        return
    if command:
        execution = action["execution"]
        if receipt["status"] == "started":
            d3._require(receipt["command"]["stopped"], "Command lifecycle must be reconciled before effects")
            if actual == after and (before != after or receipt["returncode"] == 0):
                if receipt["returncode"] not in (None, 0):
                    raise Pending("Command reported failure; reconcile its effects manually before completion")
                receipt["status"] = "completed"
                _save(path, journal)
                return
            if not execution["idempotency"] or actual != before:
                raise Pending("Command outcome is uncertain; inspect approved effects before any replay")
        elif actual != before:
            raise Pending("Command preimages changed before execution")
        receipt["status"] = "started"
        receipt["returncode"] = None
        receipt["command"] = {"attempt_id": uuid.uuid4().hex, "stopped": False}
        _save(path, journal)
        _publish_command_owner(path, journal, action, receipt["command"]["attempt_id"])
        _checkpoint("command_started")
        _guard_writers(path, root, journal, observation)
        try:
            process = subprocess.Popen(execution["argv"], cwd=root,
                env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True, pass_fds=(checkout_lock,))
            try:
                receipt["returncode"] = process.wait(timeout=execution["timeout_seconds"])
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                receipt["returncode"] = process.returncode
                raise
        except (OSError, subprocess.TimeoutExpired):
            _save(path, journal)
            raise Pending("Command failed or timed out; verify all writable descendants stopped before reconciling effects") from None
        _save(path, journal)
        _checkpoint("command_finished")
        raise Pending("Command direct process exited; current lifecycle proof for this attempt and all writable descendants is required")
    else:
        effect = action["effects"][0]
        if actual[0] != effect["after"]:
            raw = original["text"].encode() if original["kind"] == "write" else b""
            _ensure_parents(path, root, effect["path"], journal)
            _guard_writers(path, root, journal, observation)
            _replace(root, effect["path"], raw, effect["after"], effect["before"], receipt["files"][0]["temporary"])
    receipt["status"] = "completed"
    _save(path, journal)
    _checkpoint("outcome")


def _activate(path, root, journal, observation):
    e, receipt = journal["manifest"]["enrollment"], journal["enrollment"]
    actual = _fingerprint(root, str(PROJECT_FILE))
    if actual == receipt["after"] and receipt["status"] in ("activating", "active"):
        receipt["status"] = "active"
        _save(path, journal)
        return
    reason = _qualification(journal)
    if reason:
        raise Pending(reason)
    compatibility = task_state.inspect_state(_record(e["record"], journal["plan"]))
    if not compatibility["compatible"]:
        raise Pending("Enrollment runtime state/pins are incompatible; reconcile them before activation")
    if actual is not None:
        raise Pending("Enrollment changed externally; activation preserves it")
    _guard_writers(path, root, journal, observation)
    _ensure_parents(path, root, str(PROJECT_FILE), journal)
    receipt["status"] = "activating"
    _save(path, journal)
    raw, _ = _enrollment_postimage(journal)
    _replace(root, str(PROJECT_FILE), raw, receipt["after"], None, receipt["temporary"])
    receipt["status"] = "active"
    _save(path, journal)


def _rollback(path, root, journal, observation):
    _guard_writers(path, root, journal, observation)
    receipt = journal["enrollment"]
    if receipt is not None:
        actual = _fingerprint(root, str(PROJECT_FILE))
        if receipt["status"] in ("restoring", "restored") and actual == receipt["before"]:
            receipt["status"] = "restored"
            return
        if actual == receipt["after"] and receipt["status"] in ("activating", "active"):
            _guard_writers(path, root, journal, observation)
            _replace(root, str(PROJECT_FILE), b"", None, receipt["after"])
        elif actual is not None and not (receipt["status"] == "prepared" and actual == receipt["before"]):
            raise Pending("Enrollment changed externally; dependent configuration rollback is blocked")
        receipt["status"] = "inactive"
        _save(path, journal)
    failed = set()
    originals = {a["id"]: a for a in journal["plan"]["actions"]}
    for action in reversed(journal["manifest"]["actions"]):
        stored = journal["receipts"].get(action["id"])
        if stored is None:
            continue
        if stored["status"] == "rolled_back":
            if any(_fingerprint(root, effect["path"]) != effect["before"] for effect in action["effects"]):
                failed.add(action["id"])
                journal["blocked"].append({"id": action["id"], "reason": "A restored file changed externally; preserve it and keep prior enrollment inactive"})
            continue
        if any(action["id"] in originals[key]["dependencies"] for key in failed):
            journal["blocked"].append({"id": action["id"], "reason": "A dependent action has not been safely rolled back"})
            failed.add(action["id"])
            continue
        try:
            for effect, backup in reversed(list(zip(action["effects"], stored["files"]))):
                _guard_writers(path, root, journal, observation)
                _restore(path, root, effect["path"], backup, effect["before"], effect["after"])
            stored["status"] = "rolled_back"
            _save(path, journal)
        except Pending as error:
            failed.add(action["id"])
            journal["blocked"].append({"id": action["id"], "reason": str(error)})
    if failed:
        return
    _restore_directories(path, root, journal)
    if receipt is not None and receipt["before"] is not None:
        for action in journal["manifest"]["actions"]:
            for effect in action["effects"]:
                if effect["path"] != str(PROJECT_FILE) and _fingerprint(root, effect["path"]) != effect["before"]:
                    raise Pending("Prior enrollment stays inactive because supporting configuration changed")
        _fresh(journal["plan"], journal)
        observation = _current_observation(journal)
        if not observation or not observation["prior_compatibility"]:
            raise Pending("Prior enrollment stays inactive until client/runtime compatibility is qualified")
        prior_raw = d3._read_file(path / receipt["backup"], d3.MAX_FILE, private=True)
        try:
            prior_scope = _record(d3.read_request(prior_raw), journal["plan"])
            if not task_state.inspect_state(prior_scope)["compatible"]:
                raise StartupError("Prior runtime state is incompatible")
        except StartupError:
            raise Pending("Prior enrollment is stale or incompatible and remains inactive") from None
        receipt["status"] = "restoring"
        _save(path, journal)
        _restore(path, root, str(PROJECT_FILE), receipt, receipt["before"], None)
    if receipt is not None:
        receipt["status"] = "restored"


def _report(journal, exit_code, reason=None):
    blocked = deepcopy(journal.get("blocked", [])) if journal else []
    if reason:
        blocked.append({"id": "transaction", "reason": reason})
    try:
        inputs = observation_digest(journal["manifest"]) if journal else None
    except (StartupError, OSError, ValueError, KeyError, TypeError):
        inputs = None
    return {"transaction_id": journal["transaction_id"] if journal else None,
            "state": journal["state"] if journal else "blocked",
            "completed": [key for key, value in journal["receipts"].items() if value["status"] == "completed"] if journal else [],
            "blocked": blocked,
            "next_step": "No further action for this operation" if exit_code == 0 else
                "Resolve the reported scope safely, then retry the same bound request; obtain renewed approval for changed scope",
            "command_attempts": [dict(id=key, **value["command"]) for key, value in journal.get("receipts", {}).items() if "command" in value] if journal else [],
            "retained_directories": [name for name, value in journal.get("directories", {}).items() if value["status"] == "retained"] if journal else [],
            "observation_input_digest": inputs,
            "exit_code": exit_code, "limitations": LIMITATIONS}


def _run(plan_dir, request, operation):
    journal = None
    try:
        path = d3._plan_path(plan_dir)
        with d3._locked(path):
            plan = d3._load(path)
        d3._require(plan is not None, "Inspect and record a D3 plan before applying")
        d3._require(plan["schema_version"] == 1,
                    "D4 cannot apply, resume or roll back onboarding schema 2 Project inspections")
        root, git_dir = _validate(request, plan)
        with _worktree_lock(git_dir) as checkout_lock:
            owner = _command_owner(git_dir)
            if owner and (owner["plan_dir"] != str(path) or owner["transaction_id"] != request["manifest"]["transaction_id"]):
                missing = not (Path(owner["plan_dir"]) / "transaction.json").is_file()
                raise Pending("Unresolved command owner blocks this checkout; " +
                              ("the original plan is missing and needs trusted manual recovery" if missing else "resume the original plan with current command lifecycle proof"))
            journal = _load_journal(path)
            if journal is not None:
                d3._require(journal["manifest_digest"] == d3._digest(request["manifest"])
                            and journal["manifest"] == request["manifest"] and journal["approval"] == request["approval"]
                            and journal["plan"] == plan, "Transaction binding or frozen proposal changed")
                _recovery_files(path, root, journal, cleanup=False)
            elif operation != "apply":
                raise StartupError("No prepared transaction to resume or roll back")
            if not request["approval"]["evidence"]:
                return _report(journal, 2, "Trusted host/session approval evidence is missing; D3 free text grants no authority")
            if journal is None:
                _fresh(plan)
                for action in request["manifest"]["actions"]:
                    for effect in action["effects"]:
                        d3._require(_fingerprint(root, effect["path"]) == effect["before"], "Approved effect preimage changed")
                journal = {"schema_version": 1, "transaction_id": request["manifest"]["transaction_id"],
                    "manifest_digest": d3._digest(request["manifest"]), "manifest": deepcopy(request["manifest"]),
                    "approval": deepcopy(request["approval"]), "plan": deepcopy(plan), "state": "prepared",
                    "receipts": {}, "enrollment": None, "blocked": [], "directories": {}, "observations": []}
                _save(path, journal)
                _checkpoint("state")
            effective_observation = None
            if journal["state"] != "rolled_back":
                if "observations" in request:
                    effective_observation = request["observations"]
                    d3._require(effective_observation["input_digest"] == observation_digest(request["manifest"]),
                                "Observation input bindings are stale")
                else:
                    effective_observation = _current_observation(journal)
            with _authority_operation(path, root, journal, effective_observation):
                if journal["state"] == "rolled_back":
                    if owner is not None:
                        _reconcile_command_lifecycles(path, journal)
                    if operation == "rollback":
                        for action in journal["manifest"]["actions"]:
                            for effect in action["effects"]:
                                if effect["path"] != str(PROJECT_FILE) and _fingerprint(root, effect["path"]) != effect["before"]:
                                    return _report(journal, 2, "Previously restored content changed externally; preserve the current user edit")
                        if journal["enrollment"] and _fingerprint(root, str(PROJECT_FILE)) != journal["enrollment"]["before"]:
                            return _report(journal, 2, "Enrollment changed after rollback; preserve its external ownership")
                    return _report(journal, 0 if operation == "rollback" else 1,
                                   None if operation == "rollback" else "Rolled-back transactions cannot apply again; prepare a fresh approved transaction")
                journal["blocked"] = []
                if "observations" in request:
                    observation = request["observations"]
                    d3._require(observation["input_digest"] == observation_digest(request["manifest"]), "Observation input bindings are stale")
                    if observation not in journal["observations"]:
                        journal["observations"].append(deepcopy(observation))
                        _save(path, journal)
                _reconcile_command_lifecycles(path, journal)
                _recovery_files(path, root, journal)
                writer_observation = _current_observation(journal)
                try:
                    if operation == "rollback":
                        _rollback(path, root, journal, writer_observation)
                        journal["state"] = "rollback_partial" if journal["blocked"] else "rolled_back"
                    else:
                        if journal["state"] == "rollback_partial":
                            raise Pending("Partial rollback must finish before any application can continue")
                        _fresh(plan, journal)
                        if "enrollment" not in journal["manifest"]["approved_scope"]:
                            raise Pending("Enrollment activation and recovery need scoped approval before changing adoption configuration")
                        _deactivate(path, root, journal, writer_observation)
                        journal["state"] = "applying"
                        _save(path, journal)
                        completed = set()
                        observed = d3._sources(plan["sources"]["declared"])
                        originals = {a["id"]: a for a in plan["actions"]}
                        for action in journal["manifest"]["actions"]:
                            if any(r.get("command") and not r["command"]["stopped"] for r in journal["receipts"].values()):
                                journal["blocked"].append({"id": action["id"], "reason": "An earlier command attempt needs stopped-descendant lifecycle proof before further mutation"})
                                continue
                            if originals[action["id"]]["target"] == str(PROJECT_FILE):
                                continue
                            reason = _action_blockers(plan, action, journal["manifest"], completed, observed)
                            if not reason:
                                try:
                                    _apply_action(path, root, journal, originals[action["id"]], action, writer_observation, checkout_lock)
                                    completed.add(action["id"])
                                except Pending as error:
                                    reason = str(error)
                            if reason:
                                journal["blocked"].append({"id": action["id"], "reason": reason})
                        required = set(journal["manifest"]["enrollment"]["requires"])
                        enrollment_ids = {a["id"] for a in plan["actions"] if a["target"] == str(PROJECT_FILE)}
                        unsettled = any(r.get("command") and not r["command"]["stopped"] for r in journal["receipts"].values())
                        if unsettled or not required - enrollment_ids <= completed:
                            journal["state"] = "blocked"
                        else:
                            for action_id in enrollment_ids:
                                original = originals[action_id]
                                if action_id not in journal["manifest"]["approved_scope"] or not set(original["dependencies"]) <= completed:
                                    raise Pending("Final enrollment action/dependencies lack scoped approval or completion")
                            _activate(path, root, journal, writer_observation)
                            for action_id in enrollment_ids:
                                journal["receipts"][action_id] = {"status": "completed", "files": [], "returncode": None}
                            journal["state"] = "blocked" if journal["blocked"] else "applied"
                except Pending as error:
                    journal["blocked"].append({"id": "enrollment" if operation == "rollback" else "transaction", "reason": str(error)})
                    journal["state"] = "rollback_partial" if operation == "rollback" else "blocked"
                except StartupError:
                    journal["state"] = "interrupted"
                    _save(path, journal)
                    raise
                _save(path, journal)
                _checkpoint("state")
                return _report(journal, 0 if journal["state"] in ("applied", "rolled_back") else 2)
    except Pending as error:
        return _report(journal, 2, str(error))
    except StartupError as error:
        return _report(journal, 1, str(error))
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        return _report(journal, 1, "D4 input, filesystem or runtime state is unavailable or unsafe; preserve recovery files")


def apply_plan(plan_dir, request):
    """Prepare/apply currently approved effects; enrollment activation is mandatory and last."""
    return _run(plan_dir, request, "apply")


def resume_plan(plan_dir, request):
    """Reconcile durable receipts against the frozen manifest before continuing."""
    return _run(plan_dir, request, "resume")


def rollback_plan(plan_dir, request):
    """Deactivate owned enrollment, restore effects backwards, then restore compatible prior enrollment."""
    return _run(plan_dir, request, "rollback")


# Internal schema-2 path; public startup/transaction activation remains gated.
def _scoped_entries(record):
    if record is None or record.get("schema_version") != 2:
        return {}
    return {(r["repository_id"], c["checkout_id"], e["client"]): (r, c, e)
            for r in record["repositories"] for c in r["checkouts"] for e in c["clients"]}


def _scoped_projection(record, key):
    from runtime.startup import canonical_scope_projection, decode_project_record, _canonical_plain
    return _canonical_plain(canonical_scope_projection(decode_project_record(record),
        repository_id=key[0], checkout_id=key[1], client=key[2]))


def _canonical_record(record, plan, *, current):
    from runtime.startup import decode_project_record
    decode_project_record(record)
    d3._require(all(record[k] == plan["identity"][k] for k in ("project_id", "project_root", "kind"))
                and record["project_binding"] == plan["identity"]["binding"], "Canonical Project binding changed")
    entries = _scoped_entries(record)
    for assessment in plan["assessments"]["repositories"]:
        owner, identity = assessment["owner"], assessment["identity"]
        repo = next((r for r in record["repositories"] if r["repository_id"] == owner["repository_id"]), None)
        selected = next((c for c in repo["checkouts"] if c["checkout_id"] == owner["checkout_id"]), None) if repo else None
        d3._require(repo is not None and selected is not None and all(repo[k] == owner[k] for k in ("primary_root", "git_common_dir"))
                    and selected["root"] == owner["root"] and selected["git_dir"] == owner["git_dir"]
                    and repo["binding"] | selected["binding"] == identity["binding"], "Canonical selected owner changed")
        if current:
            for key, (_, _, entry) in entries.items():
                if key[:2] == (owner["repository_id"], owner["checkout_id"]) and entry["configuration"] is not None:
                    d3._require(all(entry["configuration"][k] == plan["package_pins"][k] for k in ("policy_digest", "runtime_digest")),
                                "Canonical selected configuration pins are stale")
    return record


def _scoped_originals(plan):
    originals, dependencies, order = {}, {}, []
    for assessment in d3._assessments(plan["assessments"]):
        previous = None
        for original in assessment["actions"]:
            identity = d3._qualified(assessment["owner"], original["id"])
            originals[identity] = original
            dependencies[identity] = set(original["dependencies"]) | ({previous} if previous else set())
            order.append(identity)
            previous = identity
    result, done = [], set()
    while len(done) != len(order):
        identity = next((i for i in order if i not in done and dependencies[i] <= done), None)
        d3._require(identity is not None, "Scoped action dependencies are incomplete or cyclic")
        result.append(identity)
        done.add(identity)
    return originals, result, dependencies


def _scoped_prior(plan):
    authority = next(a for a in plan["identity"]["authority"] if a["path"] == plan["project_scope"]["authority"]["path"])
    d3._require(authority.get("target") is not None and not authority["error"], "Complete authority parent observations are required")
    return authority, authority["record"]


def _validate_scoped(request, plan):
    d3._bounded(request)
    d3._project_plan_shape(plan)
    d3._require(plan["schema_version"] == 2 and plan["review_digest"] == d3._review_digest(plan), "Frozen scoped proposal changed")
    d3._object(request, ("schema_version", "manifest", "approval"), ("observations",))
    m = request["manifest"]
    d3._object(m, ("schema_version", "transaction_id", "plan", "pins", "authorization_reference", "approved_scope", "owners", "actions", "enrollment"))
    d3._require(type(request["schema_version"]) is int and request["schema_version"] == 2 and type(m["schema_version"]) is int and m["schema_version"] == 2,
                "Unsupported scoped transaction schema")
    d3._require(isinstance(m["transaction_id"], str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", m["transaction_id"]), "Invalid transaction ID")
    d3._require(m["plan"] == {k: plan[k] for k in ("plan_id", "revision", "review_digest", "current_input_digest")}
        and m["pins"] == dict(package_pins=plan["package_pins"], toolkit_commit=plan["sources"]["declared"]["toolkit"]["commit"], sources_digest=d3._digest(plan["sources"]))
        and plan["package_pins"] == d3._package_pins(), "Scoped plan/package/source pins changed")
    d3._require(isinstance(m["actions"],list) and all(isinstance(a,dict) and isinstance(a.get("effects"),list) and isinstance(a.get("preconditions"),list) for a in m["actions"])
                and sum(len(a["effects"])+len(a["preconditions"]) for a in m["actions"]) <= d3.MAX_PATHS, "Scoped effect/precondition limit exceeded")
    expected_owners = [{k: a[k] for k in ("owner", "identity")} for a in d3._assessments(plan["assessments"])]
    d3._require(m["owners"] == expected_owners, "Frozen scoped owners changed")
    originals, order, dependencies = _scoped_originals(plan)
    d3._strings(m["approved_scope"])
    d3._require(set(m["approved_scope"]) <= set(order) | {"enrollment"} and "enrollment" in m["approved_scope"], "Unknown or missing scoped approval")
    approval = request["approval"]
    d3._object(approval, ("reference", "evidence", "manifest_digest"))
    d3._text(m["authorization_reference"])
    d3._require(approval["reference"] == m["authorization_reference"] and approval["manifest_digest"] == d3._digest(m), "Approval differs from exact scoped manifest")
    d3._require(_evidence(approval["evidence"], many=True), "Trusted session approval evidence is required")
    d3._require(isinstance(m["actions"], list) and [a.get("id") for a in m["actions"]] == order, "Scoped action order differs from stable dependency order")
    physical, groups, last = [], set(), None
    for action in m["actions"]:
        d3._object(action, ("id", "owner", "group", "resources", "preconditions", "effects", "recovery", "execution"))
        original, owner = originals[action["id"]], action["owner"]
        d3._require(owner == original["owner"] and action["recovery"] in ("file-preimages", "manual"), "Scoped action owner/recovery changed")
        d3._text(action["group"]); d3._strings(action["resources"])
        if last != action["group"]:
            d3._require(action["group"] not in groups, "Scoped action groups must be contiguous")
            groups.add(action["group"]); last = action["group"]
        for condition in action["preconditions"]:
            d3._object(condition, ("path", "fingerprint")); _target(condition["path"]); _fp_schema(condition["fingerprint"])
        for effect in action["effects"]:
            d3._object(effect, ("path", "before", "after", "target") if original["kind"] == "command" else ("path", "before", "after"))
            _fp_schema(effect["before"]); _fp_schema(effect["after"])
            if not (original["kind"] == "write" and original["target"] == str(PROJECT_FILE) and effect["path"] == str(PROJECT_FILE)):
                _target(effect["path"])
            if original["kind"] == "command":
                from runtime.startup import _canonical_target
                _canonical_target(effect["target"])
                d3._require(effect["target"]["path"] == str(Path(owner["root"])/effect["path"])
                    and effect["target"]["parents"].get(owner["root"]) == next(a["identity"]["binding"]["root"] for a in m["owners"] if a["owner"] == owner)
                    and all(Path(p).is_relative_to(Path(owner["root"])) for p in effect["target"]["parents"]), "Command effect target is outside its selected owner")
            location = Path(owner["root"]) / effect["path"]
            d3._require(all(not location.is_relative_to(p) and not p.is_relative_to(location) for p in physical), "Scoped effects overlap")
            physical.append(location)
        if original["kind"] in ("write", "delete"):
            d3._require(len(action["effects"]) == 1 and action["execution"] is None, "Scoped file action needs one effect")
            effect = action["effects"][0]
            d3._require(effect["path"] == original["target"] and (effect["before"]["sha256"] if effect["before"] else "absent") == original["before"]
                and (effect["after"]["sha256"] if effect["after"] else "absent") == original["after"], "Scoped file postimage differs from proposal")
        elif original["kind"] == "command":
            e = action["execution"]
            d3._object(e, ("argv", "cwd", "cwd_target", "timeout_seconds", "qualification", "idempotency"))
            assessment = next(a for a in d3._assessments(plan["assessments"]) if a["owner"] == owner)
            d3._require(e["argv"] == original["text"] and e["cwd"] == original["cwd"]
                and e["cwd_target"] == assessment["identity"]["targets"].get("cwd:" + original["cwd"])
                and e["cwd_target"] is not None and type(e["timeout_seconds"]) is int and 1 <= e["timeout_seconds"] <= 300, "Scoped command cwd or execution changed")
            _evidence(e["qualification"]); _evidence(e["idempotency"])
        else:
            d3._require(action["execution"] is None, "External actions require manual operation")
    enrollment = m["enrollment"]
    d3._object(enrollment, ("record", "before", "affected", "requires", "qualification"))
    record = _canonical_record(enrollment["record"], plan, current=True)
    d3._require(all(record["membership"][k] == plan["project_scope"]["membership"][k] for k in ("include","exclude","future_join")), "Canonical membership differs from frozen Project scope")
    d3._require(all(isinstance(enrollment[k],list) and len(enrollment[k]) <= d3.MAX_PATHS for k in ("affected","requires","qualification")), "Scoped enrollment row limit exceeded")
    for member in enrollment["affected"]: d3._object(member,("repository_id","checkout_id","client"))
    authority, prior = _scoped_prior(plan)
    expected_before = dict(revision=prior.get("revision") if prior else None,
        raw_sha256=authority["fingerprint"].get("sha256"), target=authority["target"])
    d3._require(enrollment["before"] == expected_before, "Scoped authority preimage changed")
    old, new = _scoped_entries(prior), _scoped_entries(record)
    d3._require(set(old) <= set(new), "Removed members must retain tombstone/history entries")
    affected = {key for key in new if key not in old or _scoped_projection(prior, key) != _scoped_projection(record, key)
                or old[key][2]["activation"] != new[key][2]["activation"]}
    declared = [tuple(a[k] for k in ("repository_id", "checkout_id", "client")) for a in enrollment["affected"]]
    d3._require(declared == sorted(affected), "Scoped affected set is incomplete or excessive")
    selected = {(a["owner"]["repository_id"], a["owner"]["checkout_id"]) for a in plan["assessments"]["repositories"]}
    d3._require(all(k[:2] in selected and k[2] in plan["sources"]["declared"]["clients"] for k in affected), "Shared dependency update lacks an affected member/client assessment")
    if prior and prior.get("schema_version") == 2:
        for previous in prior["repositories"]:
            retained = next((r for r in record["repositories"] if r["repository_id"] == previous["repository_id"]),None)
            d3._require(retained is not None and all(previous[k] == retained[k] for k in ("primary_root","git_common_dir","binding")), "Historical Repository identity/tombstone was discarded")
            d3._require(previous["membership"] == retained["membership"] or previous["repository_id"] in {o[0] for o in selected}, "Unselected membership tombstone changed")
            for checkout in previous["checkouts"]:
                kept = next((c for c in retained["checkouts"] if c["checkout_id"] == checkout["checkout_id"]),None)
                d3._require(kept is not None and all(checkout[k] == kept[k] for k in ("root","git_dir","binding")), "Historical checkout identity was discarded")
    for key in set(old) - affected:
        before_repo,before_checkout,before_entry = old[key]
        after_repo,after_checkout,after_entry = new[key]
        d3._require(before_entry == after_entry and {k:v for k,v in before_repo.items() if k != "checkouts"} == {k:v for k,v in after_repo.items() if k != "checkouts"}
            and {k:v for k,v in before_checkout.items() if k != "clients"} == {k:v for k,v in after_checkout.items() if k != "clients"}, "Unrelated member identity/configuration/receipts changed")
    suspend = bool(prior and (prior.get("schema_version") == 1 or any(old[k][2]["activation"]["status"] == "active" for k in affected if k in old)))
    d3._require(record["revision"] == (prior.get("revision", 0) if prior else 0) + (2 if suspend else 1), "Scoped final revision must match frozen write sequence")
    d3._strings(enrollment["requires"])
    mandatory = set()
    for assessment in plan["assessments"]["repositories"]:
        for row in assessment["coverage"]:
            if row["mandatory"] and row["applicability"] == "applicable": mandatory.update(row["actions"])
    while True:
        expanded = mandatory | {d for i in mandatory for d in dependencies[i]}
        if expanded == mandatory: break
        mandatory = expanded
    d3._require(mandatory <= set(enrollment["requires"]) <= set(order), "Scoped enrollment omits mandatory dependencies")
    for action in m["actions"]:
        if originals[action["id"]]["target"] == str(PROJECT_FILE):
            d3._require(Path(action["owner"]["root"]) == Path(record["project_root"]) and originals[action["id"]]["kind"] == "write"
                and d3.read_request(originals[action["id"]]["text"].encode()) == record, "Canonical enrollment differs from exact proposal")
    shared_before = {s["path"]:s["sha256"] for s in prior.get("shared_policy",[])} if prior else {}
    shared_after = {s["path"]:s["sha256"] for s in record["shared_policy"]}
    for action in m["actions"]:
        for effect in action["effects"]:
            location=str(Path(action["owner"]["root"])/effect["path"])
            if location in shared_before or location in shared_after:
                d3._require(shared_after.get(location) == (effect["after"]["sha256"] if effect["after"] else None), "Shared resource postimage is missing from selected dependency projections")
    qkeys = []
    for row in enrollment["qualification"]:
        d3._object(row, ("repository_id", "checkout_id", "client", "requirements", "security_required"))
        key = tuple(row[k] for k in ("repository_id", "checkout_id", "client")); qkeys.append(key)
        assessment = next(a for a in plan["assessments"]["repositories"] if (a["owner"]["repository_id"],a["owner"]["checkout_id"]) == key[:2])
        required = {r["id"] for r in assessment["coverage"] if r["mandatory"] and r["applicability"] == "applicable"}
        d3._strings(row["requirements"])
        d3._require(type(row["security_required"]) is bool and required <= set(row["requirements"]) <= {r["id"] for r in plan["requirements"]}, "Scoped qualification requirements incomplete")
    d3._require(sorted(qkeys) == sorted(affected), "Scoped member/client qualification scope changed")
    return originals, dependencies, affected, suspend


def _scoped_target(root, relative):
    return d3._physical_target(root, root / relative, d3._fingerprint(root, relative), {"paths": 0, "bytes": 0})


def _scoped_runtime_locations(records, affected=None):
    locations = {}
    for record in records:
        if not record: continue
        if record.get("schema_version") == 1:
            rows = [(record["project_id"], record["repository_root"], record["git_common_dir"], record["policy_digest"], record.get("runtime"))]
        else:
            rows = [(record["project_id"], c["root"], r["git_common_dir"], e["configuration"]["policy_digest"], e["configuration"]["runtime"])
                    for key, (r, c, e) in _scoped_entries(record).items() if e["configuration"] and (affected is None or key in affected)]
        for project, root, common, policy, runtime in rows:
            if runtime is None: continue
            # This is a historical storage locator, not a fabricated active canonical scope.
            settings = runtime_settings({"runtime": dict(schema_version=2, state_dir=runtime["state_dir"])}, d3.PACKAGE, Path(common))
            locations[settings.state_dir] = (ProjectScope(project, Path(root), Path(common), policy, settings), runtime["schema_version"])
    return locations


def _scoped_writer_roots(manifest):
    git_roots={Path(a['owner']['git_common_dir']) for a in manifest['owners'] if a['owner']['kind']=='repository'}
    return {Path(a['owner']['root']) for a in manifest['owners']} | git_roots,git_roots


def _scoped_changed_paths(manifest):
    # Fingerprints include mode and existence, not just the content digest.
    paths={Path(action['owner']['root'])/effect['path'] for action in manifest['actions']
        for effect in action['effects'] if effect['before']!=effect['after']}
    # The approved canonical revision always changes; publication/recovery can also create/delete it.
    paths.add(Path(manifest['enrollment']['record']['project_root'])/PROJECT_FILE)
    return paths


def _scoped_task_relevant(checkout_row,roots,task=None,changed_paths=()):
    physical=Path(checkout_row[0]) in roots or any(Path(checkout_row[1])==root or root.is_relative_to(Path(checkout_row[1])) for root in roots)
    historical=task.get('accepted_identity',{}).get('shared_policy',[]) if task is not None else []
    return physical or any(Path(dependency['path']) in changed_paths for dependency in historical)


def _scoped_writers(locations, affected_roots, git_roots=(), *, changed_paths=()):
    from runtime import delegation, evidence
    claims = [dict(kind="path", key=str(root), mode="write") for root in affected_roots] + [dict(kind="git", key=str(root), mode="write") for root in git_roots]
    # D4's validated finite Project scope has its own bound, separate from assignment claim budgets.
    claims = delegation._claims(claims, maximum=len(claims)) if claims else []
    for directory, (locator, version) in locations.items():
        if version == 1:
            if _legacy_writers(replace(locator, runtime=replace(locator.runtime, schema_version=1))):
                raise Pending("Affected legacy writers remain unreconciled")
            continue
        selected = locator if isinstance(locator,evidence.EvidenceAuthorityContext) else None
        path = selected.database if selected else task_state._path(locator)
        if not os.path.lexists(path):
            d3._require(selected is None,'Discovered writer physical authority unavailable')
            continue
        task_state._sidecars(path)
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0.1)) as db:
            db.execute("pragma trusted_schema=off"); db.execute("begin")
            task_state._schema(db, version=version)
            context = selected or (evidence._existing_authority_context(task_state._authority_identity(path), db=db) if version == 3 else None)
            if context: evidence._check_context(context,db)
            records = delegation._ledger(locator, db, context=context)
            if any(r["data"]["status"] != "settled" and delegation._held_conflict(claims, r["data"]["claims"]) for r in records):
                raise Pending("Affected foreign or uncertain assignment remains unreconciled")
            rows = db.execute("select scope_id,client,session_id,task_id from tasks limit 4097").fetchall()
            d3._require(len(rows) <= 4096, "Writer history exceeds safe inspection bound")
            for scope_id, client, session, task_id in rows:
                task = task_state._task(db, scope_id, client, session, task_id)
                row = db.execute("select repository_root,git_common_dir from checkouts where scope_id=?", (scope_id,)).fetchone()
                d3._require(row is not None, "Historical writer has no checkout")
                unresolved = [a for a in task.get("evidence", {}).get("attempts", []) if a["status"] in {"reserved", "running", "uncertain"}]
                retirement = task.get("retirement")
                relevant = _scoped_task_relevant(row,affected_roots,task,changed_paths)
                if retirement and (relevant or unresolved):
                    proof = evidence._read(None if context else locator, retirement["proof"], context=context, db=db)
                    d3._require(task["state"] == "cancelled" and proof.get("kind") == "stopped-writer-reconciliation"
                        and proof.get("stopped") is True and proof.get("descendants_stopped") is True
                        and proof.get("identity") == {k: task[k] for k in ("client", "session_id", "task_id", "scope_ref")}
                        and proof.get("expected_pins") == task["pins"] and proof.get("expected_revision") == retirement["previous_revision"] == task["revision"] - 1
                        and proof.get("observed_turn_id") == task["turn_id"] and proof.get("attempt_ids") == [a["id"] for a in unresolved],
                        "Historical stopped-writer proof does not match original pins/identity")
                elif task.get('writer_stop') and (relevant or unresolved):
                    task_state._ready_stop(context,db,task,observe=True)
                elif relevant and task["mode"] == "editable":
                    raise Pending("Affected editable task lacks exact stopped-writer retirement proof")
                elif any(delegation._linked_attempt(locator, scope_id, task, a, records, context=context, db=db) is None for a in unresolved):
                    raise Pending("Unlinked or foreign task attempt retains unknown writer ownership")


_RECOVERY_ISSUER = object()
_RECOVERY_RELEASE_ISSUER = object()
_D4_HOST_BOOTSTRAP_ISSUER = object()
_D4_HOST_ISSUER = object()


@dataclass(frozen=True)
class _D4HostCapability:
    owner: object
    issuer: object
    state: object


@dataclass(frozen=True)
class _D4HostGrant:
    capability: object
    acquisition: object
    facts: object
    issuer: object


@contextmanager
def _bootstrap_d4_host(owner, *, issuer):
    """Trusted integration only: the caller independently verifies user/session authority."""
    d3._require(issuer is _D4_HOST_BOOTSTRAP_ISSUER and callable(getattr(owner,'acquire_d4_bookkeeping',None)),
        'D4 host bootstrap requires its independently trusted integration owner')
    state=dict(active=True,capability=None)
    capability=_D4HostCapability(owner,_D4_HOST_ISSUER,state);state['capability']=capability
    try:yield capability
    finally:state['active']=False


def _check_d4_grant(grant):
    d3._require(isinstance(grant,_D4HostGrant),'Actual D4 host grant is required')
    capability=grant.capability;acquisition=grant.acquisition
    d3._require(isinstance(capability,_D4HostCapability) and capability.issuer is _D4_HOST_ISSUER
        and capability.state['active'] and capability.state['capability'] is capability
        and grant.issuer is _D4_HOST_ISSUER and acquisition['active'] and acquisition['grant'] is grant
        and acquisition['capability'] is capability and acquisition['facts'] is grant.facts,
        'D4 host grant is foreign, reconstructed or expired')


@contextmanager
def _acquire_d4_grant(host,facts):
    if not isinstance(host,_D4HostCapability) or host.issuer is not _D4_HOST_ISSUER or not host.state['active'] or host.state['capability'] is not host:
        raise Pending('Actual trusted D4 host authority is unavailable; bookkeeping remains pending')
    frozen=_canonical_freeze(facts)
    acquisition=dict(active=True,capability=host,facts=frozen,grant=None)
    def issue(approved):
        d3._require(acquisition['active'] and acquisition['grant'] is None and _canonical_plain(approved)==facts,
            'D4 host approval differs from exact acquired subjects/sources/transitions')
        grant=_D4HostGrant(host,acquisition,frozen,_D4_HOST_ISSUER);acquisition['grant']=grant
        return grant
    try:
        grant=host.owner.acquire_d4_bookkeeping(frozen,issue)
        _check_d4_grant(grant)
        d3._require(grant.acquisition is acquisition,'D4 host returned a copied or stale acquisition')
        yield grant
    finally:acquisition['active']=False


@dataclass(frozen=True)
class _RecoverySourceObservation:
    content: object
    contexts: tuple
    generations: object
    created_at: int
    issuer: object
    release: object = None
    ready_inputs: object = None
    provenance: object = None


def _stop_revision(task):
    return task['retirement']['previous_revision'] if task.get('state')=='cancelled' else task.get('writer_stop',{}).get('task_revision',task['revision'])


def _stop_envelope(task):
    return task['writer_stop'] if task.get('writer_stop') else task['retirement']


def _barrier_facts(context,db,task,record,rec):
    from runtime import evidence
    task_state._fields(rec,('version','kind','barrier_id','verification','revision'))
    task_state._integer(rec['revision'],'original synchronous revision',2)
    verification=evidence._read(None,rec['verification'],context=context,db=db)
    operation=evidence._read(None,record['body']['operation'],context=context,db=db)
    task_state._fields(verification,('version','candidate_digest','plan_digest','purpose','generation','blockers','reuse','security_impact','resource_closure','barrier_id'))
    task_state._integer(verification['generation'],'original verification generation')
    d3._hash(verification['candidate_digest']);d3._hash(verification['plan_digest'])
    d3._require(type(verification['version']) is int and verification['version']==1 and
        verification['purpose'] in {'completion','merge-evidence'} and isinstance(verification['blockers'],list) and
        verification['plan_digest']==record['data']['plan_digest'] and rec['revision']==record['data']['revision']+1,
        'Synchronous barrier does not retain its actual original verification transition')
    outcome='failed' if verification['blockers'] else 'completed'
    d3._require(type(rec['version']) is int and rec['version']==1 and rec['kind']=='synchronous-verification' and
        rec['barrier_id']==record['id']==verification['barrier_id'] and rec['revision']<=_stop_revision(task) and
        operation['kind']=='completion-verification' and verification['resource_closure']==record['data']['claims'] and
        record['data']['result']==dict(outcome=outcome),'Original synchronous barrier differs from independent stopped owner')
    return outcome


def _barrier_certificate(context,db,task,record,rec):
    task_state._ready_stop(context,db,task)
    return _barrier_certificate_fields(context,db,task,record,rec)


def _barrier_certificate_fields(context,db,task,record,rec):
    outcome=_barrier_facts(context,db,task,record,rec)
    data=record['data']
    return dict(version=2,reference=dict(authority=_canonical_plain(context.authority_set[0]),id=record['id'],owner=record['owner'],assignment=data['assignment']),
        created_at=data['lifecycle']['created_at'],request_digest=data['request_digest'],role=data['role'],claims=data['claims'],
        reconciliation=dict(version=2,kind='synchronous-verification-stop',reference=data['reconciliation'],body=rec,outcome=outcome,
            stop_digest=task['writer_stop']['proof']['digest'],bindings=dict(operation=record['body']['operation'],verification=rec['verification'],candidate=data['candidate'])))


def _assignment_certificate_shape(value, task):
    from runtime import delegation, evidence
    task_state._fields(value,('reference','created_at','request_digest','role','claims','reconciliation'),('version',))
    ref=value['reference']; task_state._fields(ref,('authority','id','owner','assignment'))
    owner=ref['owner']; task_state._retired_identity('assignment',owner); task_state._artifact_reference(ref['assignment'])
    d3._require(isinstance(ref['id'],str) and re.fullmatch(r'[0-9a-f]{32}',ref['id']) and
        ref['authority']==task['reference']['authority'] and all(owner[k]==task['reference'][k] for k in
        ('scope_id','client','session_id','task_id')),'Stopped assignment original owner differs')
    task_state._integer(value['created_at'],'original stopped assignment age'); d3._hash(value['request_digest'])
    delegation._stored_claims(value['claims'],maximum=delegation.MAX_VERIFICATION_CLAIMS)
    role=value['role']; d3._require(role in {'coordinator','check','worker','review'},'Unknown stopped assignment role')
    rec=value['reconciliation']
    if 'version' in value:
        d3._require(type(value['version']) is int and value['version']==2 and task.get('writer_stop') and task.get('state') in {'ready','verifying','cancelled'} and role=='coordinator',
            'Barrier certificate needs its independently stopped complete owner')
        task_state._fields(rec,('version','kind','reference','body','outcome','stop_digest','bindings'))
        task_state._artifact_reference(rec['reference']);body=rec['body']
        task_state._fields(body,('version','kind','barrier_id','verification','revision'))
        task_state._integer(body['revision'],'synchronous barrier revision',2)
        task_state._fields(rec['bindings'],('operation','verification','candidate'))
        for ref in rec['bindings'].values():
            if ref is not None:task_state._artifact_reference(ref)
        d3._require(type(rec['version']) is int and rec['version']==2 and rec['kind']=='synchronous-verification-stop' and
            type(body['version']) is int and body['version']==1 and body['kind']=='synchronous-verification' and
            body['barrier_id']==value['reference']['id'] and body['revision']<=_stop_revision(task) and
            body['verification']==rec['bindings']['verification'] and rec['stop_digest']==task['writer_stop']['proof']['digest'] and
            rec['outcome'] in {'completed','failed'},'Barrier stop certificate changed original facts')
        return value
    task_state._fields(rec,('reference','source_digest','request_digest','revision','outcome','assessment','proof','bindings'))
    task_state._artifact_reference(rec['reference']); d3._hash(rec['source_digest']); d3._hash(rec['request_digest'])
    task_state._integer(rec['revision'],'assignment reconciliation revision',2)
    d3._require(rec['revision']<=_stop_revision(task) and rec['outcome'] in {'completed','failed','cancelled'},
        'Assignment reconciliation does not precede exact stopped transition')
    proof=rec['proof']; evidence._bounded(proof)
    d3._require(proof.get('version')==2 and type(proof['version']) is int and
        proof.get('identity')==dict(client=owner['client'],session_id=owner['session_id'],task_id=owner['task_id'],scope_ref=task['scope_ref']) and
        proof.get('scope_id')==owner['scope_id'] and proof.get('attempt_id')==ref['id'] and
        proof.get('dispatch_id')==owner['dispatch_id'] and proof.get('assignment_digest')==ref['assignment']['digest'] and
        proof.get('claims_digest')==evidence._digest(value['claims']) and proof.get('expected_pins')==task['pins'] and
        type(proof.get('expected_revision')) is int and proof['expected_revision']==rec['revision']-1,
        'Stopped assignment proof original identity differs')
    bindings=rec['bindings']
    fields={'coordinator':('operation','operation_evidence','resource_observations','d5_plan','d6_plan','candidate','current_candidate'),
        'check':('d5_plan','candidate','current_candidate','execution'),
        'worker':('plan','candidate','current_candidate','observation','native_receipt'),
        'review':('plan','candidate','current_candidate','observation','native_receipt')}[role]
    task_state._fields(bindings,fields)
    for key in fields:
        if key!='native_receipt' and bindings[key] is not None: task_state._artifact_reference(bindings[key])
    if role=='check':
        d3._require(rec['assessment'] is None,'Check certificate invented an assessment')
    else:
        assessment=rec['assessment']; task_state._fields(assessment,('outcome','changed_paths','evidence','coordinator_ref'))
        d3._require(assessment['outcome']==rec['outcome'],'Stopped assessment outcome differs')
        for key in ('changed_paths','evidence'): delegation._strings(assessment[key],key,maximum=64,limit=4096,nonempty=key=='evidence')
        for name in assessment['changed_paths']: evidence._relative(name)
        task_state._text(assessment['coordinator_ref'],'assessment coordinator',4096)
    if role=='coordinator':
        d3._require(proof.get('kind')=='coordinator-operation-reconciliation' and proof.get('operation_stopped') is True and
            proof.get('operation_descendants_stopped') is True and proof.get('operation_digest')==bindings['operation']['digest'] and
            all(proof.get(k)==bindings[k] for k in ('operation_evidence','resource_observations')),
            'Stopped coordinator operation bindings differ')
        for key in ('d5_plan','d6_plan'):
            if bindings[key] is not None: d3._require(proof.get(key+'_digest')==bindings[key]['digest'],'Stopped coordinator plan differs')
    else:
        d3._require(proof.get('kind')==('check-writer-reconciliation' if role=='check' else 'assignment-writer-reconciliation') and
            proof.get('stopped') is True and proof.get('descendants_stopped') is True,'Stopped assignment descendants differ')
        if role=='check':
            d3._require(proof.get('plan_digest')==bindings['d5_plan']['digest'] and
                proof.get('execution_digest')==(bindings['execution']['digest'] if bindings['execution'] else None),'Stopped check bindings differ')
        else:
            receipt=bindings['native_receipt']; task_state._fields(receipt,('native_identity','result_digest','launch_state'))
            d3._require(proof.get('d6_plan_digest')==bindings['plan']['digest'] and
                proof.get('observation_digest')==(bindings['observation']['digest'] if bindings['observation'] else None) and
                all(proof.get(k)==receipt[k] for k in receipt),'Stopped native receipt differs')
    if bindings['candidate'] is not None:
        d3._require(proof.get('candidate_digest')==bindings['candidate']['digest'] and bindings['current_candidate'] is not None and
            proof.get('current_candidate_digest')==bindings['current_candidate']['digest'],'Stopped candidate bindings differ')
    return value


def _assignment_certificate(context,db,task,record):
    from runtime import evidence,delegation
    data,body,owner=record['data'],record['body'],record['owner']
    d3._require(data['status']=='settled' and data.get('lifecycle'),'Recovery assignment lacks dated reconciled stop proof')
    read=lambda ref:evidence._read(None,ref,context=context,db=db)
    rec=read(data['reconciliation'])
    if rec.get('kind')=='synchronous-verification':return _barrier_certificate(context,db,task,record,rec)
    d3._require(type(rec.get('version')) is int and rec['version']==2,'Recovery assignment requires version2 role proof')
    role=data['role']
    task_state._fields(rec,('version','proof','source_digest','request_digest','current_candidate',*(() if role=='check' else ('assessment','revision','reservation_snapshot_digest'))))
    d3._hash(rec['source_digest']);d3._hash(rec['request_digest'])
    if role!='check': d3._hash(rec['reservation_snapshot_digest'])
    proof=rec['proof']; attempt=next((a for a in task.get('evidence',{}).get('attempts',[]) if a['id']==record['id']),None)
    current=rec['current_candidate']; revision=rec.get('revision')
    if role=='check':
        d3._require(attempt is not None and delegation._linked_check(None,owner['scope_id'],task,attempt,[record],context=context,db=db) is not None,
            'Recovery check lacks actual linked attempt')
        d3._require(attempt.get('reconciliation')==data['reconciliation'] and attempt['status'] not in {'reserved','running','uncertain'},
            'Recovery check remains unresolved')
        outcome='completed' if attempt['status']=='passed' else 'cancelled' if attempt['status']=='cancelled' else 'failed'
        # The check writer persists no revision/assessment; its exact transition increments once.
        revision=proof['expected_revision']+1; assessment=None
    else:
        if role=='review':
            d3._require(attempt is not None and attempt['status'] not in {'reserved','running','uncertain'} and
                attempt.get('ownership_reconciliation')==data['reconciliation'],'Recovery review remains unresolved')
        assessment=rec['assessment']; task_state._fields(assessment,('outcome','changed_paths','result_assessment','partial_change_assessment','evidence','coordinator_ref'))
        outcome=assessment['outcome']; assessment={k:assessment[k] for k in ('outcome','changed_paths','evidence','coordinator_ref')}
    task_state._integer(revision,'historical reconciliation revision',2)
    d3._require(revision<=_stop_revision(task) and data['result']==dict(outcome=outcome),
        'Recovery role outcome/revision differs from stopped owner')
    delegation._validate_role_proof(record,task,proof,scope_id=owner['scope_id'],revision=revision-1,read=read,
        linked_review=lambda a:delegation._linked_review(None,owner['scope_id'],task,a,[record],context=context,db=db),
        current_candidate_digest=current['digest'] if current else None)
    if current is not None: evidence._candidate_projection(read(current),task)
    if role=='coordinator':
        bindings={k:body[k] for k in ('operation','d5_plan','d6_plan')}
        bindings.update({k:proof[k] for k in ('operation_evidence','resource_observations')})
    elif role=='check':
        bindings=dict(d5_plan=body['d5_plan'],execution=data['observation'])
    else:
        history=delegation._worker_history(None,data['observation'],context=context)
        observation=history[0][1] if history else None;receipt=observation['receipt'] if observation else {}
        if observation is not None:
            d3._require(isinstance(receipt,dict) and all(receipt.get(k)==v for k,v in data['binding'].items()) and
                receipt.get('assignment_digest')==data['assignment']['digest'] and receipt.get('candidate_digest')==data['candidate']['digest'] and
                receipt.get('checkout')==task['accepted_identity']['repository_root'] and
                any(read(item['incoming']).get('receipt')==receipt for _,item in history),
                'Recovery native receipt lacks actual original observation/binding')
            result=observation['result']
            d3._require((result is None and receipt.get('result_digest') is None) or
                isinstance(result,str) and hashlib.sha256(result.encode()).hexdigest()==receipt.get('result_digest'),
                'Recovery native result identity differs')
        else:
            d3._require(data['observation'] is None and proof['launch_state']=='not-started' and
                proof['observation_digest'] is None and proof['result_digest'] is None,'Recovery no-launch proof is incomplete')
        native={k:data['binding'][k] for k in ('client_surface','native_version','parent_session_id','task_name')}
        native.update({k:receipt.get(k) for k in ('parent_turn_id','spawn_item_id','worker_id','worker_turn_id','result_item_id')})
        bindings=dict(plan=body['plan'],observation=data['observation'],native_receipt=dict(native_identity=native,
            result_digest=receipt.get('result_digest'),launch_state='observed' if observation else 'not-started'))
    bindings.update(candidate=data['candidate'],current_candidate=current)
    return dict(reference=dict(authority=_canonical_plain(context.authority_set[0]),id=record['id'],owner=owner,assignment=data['assignment']),
        created_at=data['lifecycle']['created_at'],request_digest=data['request_digest'],role=role,claims=data['claims'],
        reconciliation=dict(reference=data['reconciliation'],source_digest=rec['source_digest'],request_digest=rec['request_digest'],
            revision=revision,outcome=outcome,assessment=assessment,proof=proof,bindings=bindings))


def _stopped_certificate_shape(value):
    complete='writer_stop' in value
    cancelled=complete and value.get('state')=='cancelled'
    task_state._fields(value,('reference','created_at','revision','pins','accepted_identity','scope_ref','turn_id','proof',
        *(('version','state','writer_stop',*(['retirement','retirement_proof'] if cancelled else []),
            *(['linked'] if value.get('writer_stop',{}).get('linked') else [])) if complete else ('retirement',))),('assignments','preparation'))
    task_state._task_reference(value['reference']); task_state._integer(value['created_at'],'original stopped task age')
    task_state._integer(value['revision'],'stopped task revision',2); task_state._text(value['scope_ref'],'stopped scope')
    d3._require(task_state._validate_pins(value['pins'])==3,'Stopped certificate requires canonical pins')
    accepted=task_state._accepted_identity(value['accepted_identity'])
    ref=value['reference']
    d3._require(task_state._digest(accepted)==value['pins']['accepted_scope_digest'] and accepted['client']==ref['client']
        and task_state._digest([3,accepted['project_id'],accepted['repository_id'],accepted['checkout_id']])==ref['scope_id'],
        'Stopped certificate original accepted identity differs')
    if complete:
        from runtime import evidence
        d3._require(value['state'] in {'ready','cancelled','verifying'} and (value['state']!='verifying' or 'linked' in value) and type(value['version']) is int and value['version']==2,'Unknown complete stop certificate')
        stop=value['writer_stop'];task_state._writer_stop_shape(stop);proof=value['proof']
        evidence._ready_stop_shape(proof)
        d3._require(proof['identity']=={k:(ref[k] if k!='scope_ref' else value[k]) for k in ('client','session_id','task_id','scope_ref')} and
            proof['expected_pins']==value['pins'] and proof['expected_revision']==stop['task_revision']==value['revision'] and
            proof['observed_turn_id']==value['turn_id'] and proof['candidate_digest']==stop['candidate']['digest'] and
            proof['verification_digest']==(stop['verification']['digest'] if stop['verification'] is not None else None) and proof['generation']==stop['generation'] and
            evidence._digest(proof)==stop['proof']['digest'] and all(proof[k]==stop[k] for k in ('observation_ref','coordinator_ref')),
            'Complete certificate changed original independent task stop')
        d3._require(('linked' in value)==('linked_digest' in proof),'Complete certificate lost its linked basis')
        if 'linked' in value:
            linked=value['linked'];evidence._linked_stop_shape(linked)
            if stop['verification'] is None:
                d3._require(linked['version']==2 and linked['aggregate'] is None and proof['verification_digest'] is None and
                    any(row['task']==ref and row['verification'] is None for row in linked['members']),
                    'Absent verifier needs its exact factual lifecycle member basis')
            d3._require(evidence._digest(linked)==proof['linked_digest']==stop['linked']['digest'] and
                any(row['task']==ref and row['state']==value['state'] and row['revision']==value['revision'] and
                    row['pins']==value['pins'] and row['created_at']==value['created_at'] for row in linked['members']),
                'Complete certificate changed its actual linked-member basis')
    if not complete or cancelled:
        retirement=value['retirement']; proof=value['retirement_proof'] if complete else value['proof']
        task_state._fields(retirement,('proof_digest','proof','observation_ref','coordinator_ref','previous_revision'))
        task_state._artifact_reference(retirement['proof']); d3._hash(retirement['proof_digest'])
        task_state._fields(proof,('version','kind','identity','expected_revision','expected_pins','observed_turn_id','stopped','descendants_stopped','attempt_ids','observation_ref','coordinator_ref'))
        d3._require(type(proof['version']) is int and proof['version']==1 and proof['kind']=='stopped-writer-reconciliation'
            and proof['stopped'] is True and proof['descendants_stopped'] is True
            and proof['identity']=={k:(ref[k] if k!='scope_ref' else value[k]) for k in ('client','session_id','task_id','scope_ref')}
            and proof['expected_pins']==value['pins'] and proof['expected_revision']==retirement['previous_revision']==value['revision']-1
            and proof['observed_turn_id']==value['turn_id'] and all(proof[k]==retirement[k] for k in ('observation_ref','coordinator_ref')),
            'Stopped certificate exact reconciliation differs')
        d3._require(isinstance(proof['attempt_ids'],list) and len(proof['attempt_ids'])<=4096 and len(set(proof['attempt_ids']))==len(proof['attempt_ids']),
            'Stopped certificate attempt set differs')
        for attempt in proof['attempt_ids']: task_state._text(attempt,'stopped attempt ID')
        for key in ('observation_ref','coordinator_ref'): task_state._text(proof[key],key)
        if complete:d3._require(evidence._digest(proof)==retirement['proof']['digest'],
            'Complete certificate changed original cancellation proof')
    if 'preparation' in value:
        d3._require('linked' in value,'Preparation needs an actual stopped linked member')
        prepared=value['preparation'];task_state._fields(prepared,('reference','component_digest','authorities'))
        task_state._artifact_reference(prepared['reference']);d3._hash(prepared['component_digest'])
        d3._require(isinstance(prepared['authorities'],list) and 0<len(prepared['authorities'])<=4096,'Prepared authority set is incomplete')
        for authority in prepared['authorities']:task_state._task_reference(dict(value['reference'],authority=authority))
    if 'assignments' in value:
        d3._require(isinstance(value['assignments'],list) and len(value['assignments'])<=4096,'Stopped assignment certificate bound exceeded')
        for assignment in value['assignments']: _assignment_certificate_shape(assignment,value)
        d3._require(len({a['reference']['id'] for a in value['assignments']})==len(value['assignments']),'Duplicate stopped assignments')
    return value


def _stopped_certificate(context,db,item):
    from runtime import evidence
    ref=item['reference']; task=task_state._task(db,ref['scope_id'],ref['client'],ref['session_id'],ref['task_id'])
    d3._require(task is not None and task.get('lifecycle') and task['pins']==item['pins'],'Recovery original stopped owner/age/pins changed')
    if task.get('writer_stop'):
        proof=task_state._ready_stop(context,db,task,observe=True)
        result=dict(reference=ref,created_at=task['lifecycle']['created_at'],version=2,state=task['state'],writer_stop=task['writer_stop'],
            **{k:task[k] for k in ('revision','pins','accepted_identity','scope_ref','turn_id')},proof=proof)
        if 'linked' in task['writer_stop']:result['linked']=evidence._read(None,task['writer_stop']['linked'],context=context,db=db)
        if task['state']=='cancelled':result.update(retirement=task['retirement'],
            retirement_proof=evidence._read(None,task['retirement']['proof'],context=context,db=db))
    else:
        d3._require(task['state']=='cancelled' and task.get('retirement'),'Recovery release requires exact cancelled or independently stopped ready owner')
        proof=evidence._read(None,task['retirement']['proof'],context=context,db=db)
        unresolved=[a['id'] for a in task.get('evidence',{}).get('attempts',[]) if a['status'] in {'reserved','running','uncertain'}]
        d3._require(proof.get('attempt_ids')==unresolved,'Recovery stopped attempt ownership differs')
        result=dict(reference=ref,created_at=task['lifecycle']['created_at'],**{k:task[k] for k in
            ('revision','pins','accepted_identity','scope_ref','turn_id','retirement')},proof=proof)
    from runtime import delegation
    records=delegation._ledger(None,db,context=context)
    result['assignments']=[_assignment_certificate(context,db,task,r) for r in records if all(r['owner'][k]==ref[k] for k in ('scope_id','client','session_id','task_id'))]
    result['assignments'].sort(key=d3._digest)
    return _stopped_certificate_shape(result)


def _stopped_assignment_certificate(value,reference):
    """Resolve an exact issued pointer; retirement markers cannot authenticate that pointer."""
    _stopped_certificate_shape(value)
    matches=[a for a in value.get('assignments',[]) if a['reference']==reference]
    d3._require(len(matches)==1,'Recovery requested assignment differs from retained issued pointer')
    return matches[0]


def _check_stopped_certificate(context,db,value,*,preparation_reader=None,writer=None):
    from runtime import evidence
    _stopped_certificate_shape(value)
    ref=value['reference']
    linked_writer=writer if writer is not None else (context,db)
    if value.get('linked') and evidence._linked_component_closed(evidence._linked_basis_root(value['linked']),writer=linked_writer):
        if preparation_reader is not None and 'preparation' in value:
            evidence._check_linked_preparation_certificate(context,db,value,preparation_reader=preparation_reader,writer=writer)
        else:
            authorities=value.get('preparation',{}).get('authorities',value['linked']['authorities'])
            support=evidence._linked_retained_component(evidence._linked_basis_root(value['linked']),authorities,writer=linked_writer)
            evidence._check_retained_linked_certificate(support,value)
        identity=task_state._lifecycle_identity(db,'task',ref)
        d3._require(identity['status']!='expired','Expired linked identity cannot validate historical support')
        return identity
    identity=task_state._lifecycle_identity(db,'task',ref)
    d3._require(identity['pins_digest']==task_state._digest(value['pins']) and identity['created_at']==value['created_at']
        and identity['identity']=={k:ref[k] for k in ('scope_id','client','session_id','task_id')},'Recovery stopped identity support differs')
    if identity['status']=='live':
        task=task_state._task(db,ref['scope_id'],ref['client'],ref['session_id'],ref['task_id'])
        complete='writer_stop' in value
        d3._require(task['state']==value.get('state','cancelled') and all(task[k]==value[k] for k in
            ('revision','pins','accepted_identity','scope_ref','turn_id',*(['writer_stop',*(['retirement'] if task['state']=='cancelled' else [])] if complete else ['retirement']))),'Recovery live stopped owner changed')
        if complete:task_state._ready_stop(context,db,task)
        attempts=[a['id'] for a in task.get('evidence',{}).get('attempts',[]) if complete or a['status'] in {'reserved','running','uncertain'}]
        d3._require(attempts==value['proof']['attempt_ids'],'Recovery live stopped attempts changed')
    for assignment in value.get('assignments',[]):
        observed=task_state._lifecycle_identity(db,'assignment',assignment['reference'])
        d3._require(observed['pins_digest']==task_state._digest(value['pins']) and observed['request_digest']==assignment['request_digest'] and
            observed['created_at']==assignment['created_at'] and observed['identity']==dict(id=assignment['reference']['id'],owner=assignment['reference']['owner']),
            'Recovery stopped assignment identity support differs')
        if observed['status']=='live':
            from runtime import delegation
            row=db.execute('select id,scope_id,client,session_id,task_id,dispatch_id,data from assignments where id=?',(assignment['reference']['id'],)).fetchone()
            record=delegation._record(None,row,context=context,db=db)
            d3._require(_assignment_certificate(context,db,task,record)==assignment,'Recovery live stopped assignment changed')
    if 'preparation' in value:evidence._check_linked_preparation_certificate(context,db,value,preparation_reader=preparation_reader,writer=writer)
    return identity


def _cut_recovery_content(content,certificates,contexts):
    # Preserve independent artifact/assignment raw routes; only the issued proof route is cut.
    from runtime import evidence
    content=deepcopy(content);certificates,extra,component_routes=evidence._linked_prepared_replacements(certificates,contexts)
    content['artifacts']=list({evidence._raw(row):row for row in [*content['artifacts'],*extra]}.values())
    certificates=sorted(certificates,key=d3._digest)
    component_routes={(d3._digest(ref['authority']),d3._digest(ref['artifact'])):owners
        for raw,owners in component_routes.items() for ref in [json.loads(raw)]}
    certified={d3._digest(a['reference']):a for c in certificates if 'linked' not in c or 'preparation' in c for a in c.get('assignments',[])}
    # Linked raw routes need every exact prepared replacement; no safe closure is implied.
    seeds=[((d3._digest(c['reference']['authority']),d3._digest(_stop_envelope(c)['proof'])),c['reference']) for c in certificates if 'linked' not in c or 'preparation' in c]
    for c in certificates:
        if 'linked' in c and 'preparation' not in c:continue
        if c.get('writer_stop'):
            if c.get('state')=='cancelled':seeds.append(((d3._digest(c['reference']['authority']),d3._digest(c['retirement']['proof'])),c['reference']))
            seeds.extend(((d3._digest(c['reference']['authority']),d3._digest(ref)),c['reference']) for ref in (c['writer_stop']['candidate'],c['writer_stop']['verification']) if ref is not None)
    seeds.extend((key,json.loads(next(iter(owners)))) for key,owners in component_routes.items())
    for assignment in certified.values():
        authority=assignment['reference']['authority']; rec=assignment['reconciliation']
        refs=[assignment['reference']['assignment'],rec['reference']]
        refs += [ref for key,ref in rec['bindings'].items() if key!='native_receipt' and ref is not None]
        owner=dict(authority=authority,**{k:assignment['reference']['owner'][k] for k in ('scope_id','client','session_id','task_id')})
        seeds.extend(((d3._digest(authority),d3._digest(ref)),owner) for ref in refs)
    raw_tasks=set();metadata_by_key={}
    by_authority={d3._digest(_canonical_plain(c.authority_set[0])):c for c in contexts}
    for artifact in content['artifacts']:
        key=(d3._digest(artifact['authority']),d3._digest(artifact['artifact']))
        with evidence._context_database(by_authority[key[0]]) as db:
            metadata,_=evidence._managed_artifact(None,artifact['artifact'],context=by_authority[key[0]],db=db)
        metadata_by_key[key]=(artifact['authority'],metadata)
    # A route retains its original owner; another certified task is still foreign.
    support=set();foreign=set();seen=set();pending=list(seeds)
    while pending:
        key,owner=pending.pop();route=(key,d3._digest(owner))
        if route in seen or key not in metadata_by_key: continue
        seen.add(route);authority,metadata=metadata_by_key[key]
        component=component_routes.get(key)
        owned=component is not None and evidence._raw(owner) in component and evidence._raw(metadata['owner'].get('task')) in component
        if not owned and (authority!=owner['authority'] or metadata['owner'].get('task')!=owner):
            foreign.add(key);continue
        support.add(key)
        for edge in metadata['dependencies']:
            if edge['kind']!='artifact': continue
            ref=edge['reference'];other=ref.get('authority',authority)
            pending.append(((d3._digest(other),d3._digest(ref.get('artifact',ref))),owner))
    # Discover independent routes before removing any certified raw ownership edge.
    raw_assignments=set();retained=set();pending=(set(metadata_by_key)-support)|foreign
    while pending:
        key=pending.pop()
        if key in retained: continue
        d3._require(key in metadata_by_key,'Recovery retained artifact route is incomplete')
        retained.add(key);authority,metadata=metadata_by_key[key]
        for edge in metadata['dependencies']:
            if edge['kind']=='task': raw_tasks.add(d3._digest(edge['reference']))
            elif edge['kind']=='assignment':
                assignment_key=d3._digest(edge['reference']);raw_assignments.add(assignment_key)
                if assignment_key in certified:
                    assignment=certified[assignment_key];rec=assignment['reconciliation']
                    refs=[assignment['reference']['assignment'],rec['reference']]
                    refs += [ref for key,ref in rec['bindings'].items() if key!='native_receipt' and ref is not None]
                    pending.update((d3._digest(assignment['reference']['authority']),d3._digest(ref)) for ref in refs
                        if (d3._digest(assignment['reference']['authority']),d3._digest(ref)) in metadata_by_key)
            elif edge['kind'] in ('artifact','recovery'):
                ref=edge['reference'];other=ref.get('authority',authority)
                required=(d3._digest(other),d3._digest(ref.get('artifact',ref)))
                if required not in retained: pending.add(required)
    content['assignments']=[a for a in content['assignments'] if d3._digest(a) not in certified or d3._digest(a) in raw_assignments]
    for assignment in content['assignments']:
        owner=assignment['owner'];raw_tasks.add(d3._digest(dict(authority=assignment['authority'],**{k:owner[k] for k in ('scope_id','client','session_id','task_id')})))
    cut={d3._digest(c['reference']) for c in certificates}-raw_tasks
    content['tasks']=[t for t in content['tasks'] if d3._digest(t['reference']) not in cut]
    content['artifacts']=[a for a in content['artifacts'] if (d3._digest(a['authority']),d3._digest(a['artifact'])) in retained]
    content.update(version=2,stopped=certificates,previous=None)
    if 'use_contract' in content:
        content['use_contract']=_project_recovery_uses(content,contexts,[content['use_contract']])
    return content


def _recovery_ready_inputs(content,contexts):
    from runtime import evidence
    files={}
    for context in contexts:
        authority=_canonical_plain(context.authority_set[0])
        with evidence._context_database(context) as db:
            for certificate in content.get('stopped',[]):
                ref=certificate['reference']
                if not certificate.get('writer_stop') or ref['authority']!=authority:continue
                identity=task_state._lifecycle_identity(db,'task',ref)
                if identity['status']!='live':continue
                task=task_state._task(db,ref['scope_id'],ref['client'],ref['session_id'],ref['task_id'])
                if certificate.get('linked') and task['lifecycle']['safe_closed_at'] is not None and evidence._linked_component_closed(evidence._linked_basis_root(certificate['linked']),writer=(context,db)):continue
                candidate=evidence._read(None,task['writer_stop']['candidate'],context=context,db=db)
                files[d3._digest(ref)]=evidence._ready_stop_candidate(context,task,candidate)
    return _canonical_freeze(files)


def _recovery_generation(db,tasks,assignments):
    rows=[]
    for item in tasks:
        ref=item['reference']
        row=db.execute('select data from tasks where scope_id=? and client=? and session_id=? and task_id=?',
            tuple(ref[k] for k in ('scope_id','client','session_id','task_id'))).fetchone()
        d3._require(row is not None,'Recovery original task unavailable')
        rows.append(['task',ref,row[0]])
    for item in assignments:
        row=db.execute('select data from assignments where id=?',(item['id'],)).fetchone()
        d3._require(row is not None,'Recovery original assignment unavailable')
        rows.append(['assignment',item['id'],row[0]])
    return d3._digest(rows)


def _historical_recovery_roots(manifest,context,db,task,reference):
    """Recognize only the same physical member's removed, actually changed shared dependency."""
    from runtime import evidence
    from runtime.startup import decode_project_record,canonical_scope_projection
    identity=task_state._accepted_identity(task['accepted_identity'])
    record=manifest['enrollment']['record']
    changed={str(Path(action['owner']['root'])/effect['path']) for action in manifest['actions'] for effect in action['effects']
        if effect['before']!=effect['after']}
    if not any(row['path'] in changed for row in identity['shared_policy']):return []
    if identity['project_id']!=record['project_id'] or identity['project_root']!=record['project_root']:
        return []
    observed=d3._authority_observation(Path(identity['project_root']),{'paths':0,'bytes':0},canonical_only=True)
    if observed['error'] or observed['record'] is None:return []
    current=observed['record'];key=tuple(identity[k] for k in ('repository_id','checkout_id','client'))
    if current.get('schema_version')!=2 or key not in _scoped_entries(current):return []
    projection=canonical_scope_projection(decode_project_record(current),repository_id=key[0],checkout_id=key[1],client=key[2])
    if projection is None:return []
    projection=_canonical_plain(projection)
    # Only removed dependency declarations and client suspension may differ.
    expected=deepcopy(identity);expected['shared_policy']=projection['shared_policy']
    if projection!=expected or _scoped_entries(current)[key][2]['activation']['status']!='suspended':return []
    configuration=projection['configuration']
    if configuration['runtime']!=dict(schema_version=3,state_dir=str(context.directory)):return []
    # The responsible stop validator decides whether original historical pins remain supported.
    baseline=task_state._source_baseline(None,db,context=context)
    if baseline is None or baseline['content']['project_id']!=record['project_id'] or baseline['content']['source_contract']!=2:return []
    proposed=canonical_scope_projection(decode_project_record(record),repository_id=key[0],checkout_id=key[1],client=key[2])
    if proposed is None or _canonical_plain(proposed)!=projection:return []
    if _scoped_entries(record)[key][2]['activation']['status']!='suspended':return []
    if evidence._binding(Path(identity['project_root']))!=identity['project_binding']:return []
    if any(evidence._binding(Path(identity[path]))!=identity['bindings'][binding] for path,binding in
            (('repository_root','root'),('primary_root','primary_root'),('git_dir','git_dir'),('git_common_dir','git_common_dir'))):return []
    old={row['path']:row for row in identity['shared_policy']}
    if any(old.get(row['path'])!=row for row in projection['shared_policy']):return []
    removed=set(old)-{row['path'] for row in projection['shared_policy']}
    effects=[dict(action_id=action['id'],path=effect['path']) for action in manifest['actions'] for effect in action['effects']
        if effect['before']!=effect['after'] and str(Path(action['owner']['root'])/effect['path']) in removed]
    if not effects or not (task.get('retirement') or task.get('writer_stop')):return []
    certificate=_stopped_certificate(context,db,dict(reference=reference,pins=task['pins']))
    _check_stopped_certificate(context,db,certificate)
    proof=dict(authority=reference['authority'],artifact=_stop_envelope(task)['proof'])
    return [dict(purpose='historical-stop',reference=dict(kind='task',reference=reference),task=reference,proof=proof,effect=effect)
        for effect in effects]


def _recovery_owner_refs(manifest,context,task_refs,*,use_roots=None):
    """Select actual affected-writer proofs; never inspect user payloads for lookalike refs."""
    from runtime import evidence,delegation
    roots,_=_scoped_writer_roots(manifest)
    changed_paths=_scoped_changed_paths(manifest)
    tasks=[]; assignments={}; references=[];reasons={}
    authority=_canonical_plain(context.authority_set[0])
    with evidence._context_database(context) as db:
        records=delegation._ledger(None,db,context=context)
        rows=db.execute('select scope_id,client,session_id,task_id from tasks limit 4097').fetchall()
        d3._require(len(rows)<=4096,'Recovery task discovery exceeds bound')
        for scope_id,client,session,task_id in rows:
            task=task_state._task(db,scope_id,client,session,task_id)
            row=db.execute('select repository_root,git_common_dir from checkouts where scope_id=?',(scope_id,)).fetchone()
            d3._require(row is not None,'Recovery task checkout unavailable')
            relevant=_scoped_task_relevant(row,roots,task,changed_paths)
            unresolved=[a for a in task.get('evidence',{}).get('attempts',[]) if a['status'] in {'reserved','running','uncertain'}]
            ref=dict(authority=authority,scope_id=scope_id,client=client,session_id=session,task_id=task_id)
            named=any(_canonical_plain(r)==ref for r in task_refs)
            if not (named or unresolved or relevant and (task.get('retirement') or task.get('writer_stop'))): continue
            tasks.append(dict(reference=ref,revision=task['revision'],pins=task['pins'],turn_id=task['turn_id']))
            if use_roots is not None:
                selected=_historical_recovery_roots(manifest,context,db,task,ref)
                if not selected or named:selected.append(dict(purpose='content',reference=dict(kind='task',reference=ref)))
                reasons[d3._digest(ref)]=[dict(root=root,dependencies=[dict(kind='task',reference=ref)]) for root in selected]
                use_roots.extend(reasons[d3._digest(ref)])
            start=len(references)
            for record in records:
                if all(record['owner'][k]==ref[k] for k in ('scope_id','client','session_id','task_id')): assignments[record['id']]=record
            if task.get('retirement') or task.get('writer_stop'):
                envelope=_stop_envelope(task)
                references.extend(edge['reference'] for edge in evidence._artifact_dependencies(envelope))
            else:
                for attempt in unresolved:
                    record=delegation._linked_attempt(None,scope_id,task,attempt,records,context=context,db=db,artifact_refs=references)
                    d3._require(record is not None,'Recovery task attempt has unknown ownership')
                    assignments[record['id']]=record
            if use_roots is not None:
                for reason in reasons[d3._digest(ref)]:
                    reason['dependencies'].extend(dict(kind='artifact',reference=dict(authority=authority,artifact=artifact))
                        for artifact in references[start:])
        for record in assignments.values():
            row=db.execute('select id,scope_id,client,session_id,task_id,dispatch_id,data from assignments where id=?',(record['id'],)).fetchone()
            start=len(references)
            delegation._record(None,row,db=db,context=context,artifact_refs=references)
            if use_roots is not None:
                owner=dict(authority=authority,**{k:record['owner'][k] for k in ('scope_id','client','session_id','task_id')})
                assignment=dict(authority=authority,id=record['id'],owner=record['owner'],assignment=record['data']['assignment'])
                for reason in reasons[d3._digest(owner)]:
                    reason['dependencies'].append(dict(kind='assignment',reference=assignment))
                    reason['dependencies'].extend(dict(kind='artifact',reference=dict(authority=authority,artifact=artifact))
                        for artifact in references[start:])
    return tasks,[dict(authority=authority,id=r['id'],owner=r['owner'],assignment=r['data']['assignment']) for r in assignments.values()],references


def _collect_recovery_references(manifest,contexts,task_refs=(),*,use_roots=None):
    from runtime import evidence,delegation
    by_authority={d3._digest(_canonical_plain(c.authority_set[0])):c for c in contexts}
    tasks={}; assignments={}; artifacts={}; foreign={}; pending=[]; seen=set()
    def enqueue(kind,authority,reference):
        key=(kind,d3._digest(authority),d3._digest(reference))
        if key not in seen:
            d3._require(len(seen)<4096,'Recovery typed reference closure exceeds bound')
            seen.add(key); pending.append((kind,authority,reference))
    for context in contexts:
        authority=_canonical_plain(context.authority_set[0])
        selected,selected_assignments,roots=_recovery_owner_refs(manifest,context,task_refs,use_roots=use_roots)
        for task in selected: tasks[d3._digest(task['reference'])]=task
        for assignment in selected_assignments:
            assignments[d3._digest(assignment)]=assignment
        for reference in roots: enqueue('artifact',authority,reference)
    def dependency(value,authority):
        task_state._fields(value,('kind','reference')); kind=value['kind']; ref=value['reference']
        if kind=='task':
            task_state._task_reference(ref); enqueue('task',ref['authority'],ref)
        elif kind=='artifact':
            if set(ref)=={'name','digest'}:
                task_state._artifact_reference(ref); enqueue('artifact',authority,ref)
            else:
                task_state._fields(ref,('authority','artifact')); task_state._artifact_reference(ref['artifact'])
                enqueue('artifact',ref['authority'],ref['artifact'])
        elif kind=='assignment':
            task_state._fields(ref,('authority','id','owner','assignment'))
            task_state._retired_identity('assignment',ref['owner']); task_state._artifact_reference(ref['assignment'])
            d3._require(isinstance(ref['id'],str) and re.fullmatch(r'[0-9a-f]{32}',ref['id']),'Invalid recovery assignment ID')
            enqueue('assignment',ref['authority'],ref)
        elif kind=='recovery':
            if set(ref)=={'identity','artifact'}:
                task_state._fields(ref['identity'],('plan_dir','transaction_id','manifest_digest'))
                task_state._canonical_path(ref['identity']['plan_dir']); d3._text(ref['identity']['transaction_id']); d3._hash(ref['identity']['manifest_digest'])
                task_state._artifact_reference(ref['artifact']); enqueue('artifact',authority,ref['artifact'])
            else:
                task_state._fields(ref,('authority','artifact')); task_state._artifact_reference(ref['artifact'])
                enqueue('artifact',ref['authority'],ref['artifact'])
        else:
            raise Pending('Unsupported typed recovery dependency; owner observation required')
    while pending:
        kind,authority,reference=pending.pop()
        task_state._fields(authority,('directory','database','directory_binding','database_binding'))
        task_state._canonical_path(authority['directory']); task_state._canonical_path(authority['database'])
        task_state._canonical_binding(authority['directory_binding']); task_state._canonical_binding(authority['database_binding'])
        context=by_authority.get(d3._digest(authority))
        if context is None:
            foreign[d3._digest(authority)]=authority
            continue
        with evidence._context_database(context) as db:
            if kind=='artifact':
                metadata,raw=evidence._managed_artifact(None,reference,context=context,db=db)
                if use_roots is not None:
                    body=json.loads(raw)
                    d3._require(not (isinstance(body,dict) and body.get('kind')=='d4-recovery-source' and 'use_contract' in body),
                        'Restricted recovery wrapper requires exact owner admission projection')
                artifacts[d3._digest([authority,reference])]=dict(authority=authority,artifact=reference)
                for edge in metadata['dependencies']: dependency(edge,authority)
            elif kind=='task':
                task=task_state._task(db,reference['scope_id'],reference['client'],reference['session_id'],reference['task_id'])
                d3._require(task is not None,'Typed recovery task unavailable')
                tasks[d3._digest(reference)]=dict(reference=reference,revision=task['revision'],pins=task['pins'],turn_id=task['turn_id'])
            else:
                row=db.execute('select id,scope_id,client,session_id,task_id,dispatch_id,data from assignments where id=?',(reference['id'],)).fetchone()
                d3._require(row is not None,'Typed recovery assignment unavailable')
                roots=[]; record=delegation._record(None,row,db=db,context=context,artifact_refs=roots)
                d3._require(record['owner']==reference['owner'] and record['data']['assignment']==reference['assignment'],'Typed recovery assignment differs')
                assignments[d3._digest(reference)]=reference
                for root in roots: enqueue('artifact',authority,root)
    return list(tasks.values()),list(assignments.values()),list(artifacts.values()),list(foreign.values())


def _recovery_use_graph(content,contexts):
    """Read the full acquired graph; annotations never replace its typed dependencies."""
    from runtime import evidence
    by_authority={d3._digest(_canonical_plain(c.authority_set[0])):c for c in contexts}
    direct=[dict(kind='task',reference=t['reference']) for t in content['tasks']]
    direct.extend(dict(kind='assignment',reference=a) for a in content['assignments'])
    direct.extend(dict(kind='artifact',reference=a) for a in content['artifacts'])
    metadata={};owners={}
    for pointer in content['artifacts']:
        context=by_authority[d3._digest(pointer['authority'])]
        with evidence._context_database(context) as db:
            observed,raw=evidence._managed_artifact(None,pointer['artifact'],context=context,db=db)
        # An outer inventory cannot turn an inherited restricted body into fresh content.
        body=json.loads(raw)
        d3._require(not (isinstance(body,dict) and body.get('kind')=='d4-recovery-source' and 'use_contract' in body),
            'Restricted recovery wrapper requires exact owner admission projection')
        name=recovery_uses.key(pointer)
        metadata[name]=[recovery_uses.qualify_dependency(edge,pointer['authority']) for edge in observed['dependencies']]
        owners[name]=observed['owner']['task']
    return direct,metadata,owners


def _build_recovery_uses(content,contexts,reasons):
    """Freeze each actual selected reason before graph deduplication can hide a mixed role."""
    direct,metadata,owners=_recovery_use_graph(content,contexts)
    roots=[reason['root'] for reason in reasons];edges=[]
    for index,reason in enumerate(reasons):
        root=reason['root'];historical=root['purpose']=='historical-stop'
        pending=[(None,edge,'retention-only' if historical else 'content') for edge in reason['dependencies']]
        seen=set()
        while pending:
            parent,dependency,purpose=pending.pop()
            if historical and purpose=='retention-only':
                ref=dependency['reference'];kind=dependency['kind']
                if kind in ('artifact','recovery'):
                    owned=owners.get(recovery_uses.key(ref))==root['task']
                elif kind=='task':owned=ref==root['task']
                else:owned=dict(authority=ref['authority'],**{k:ref['owner'][k] for k in ('scope_id','client','session_id','task_id')})==root['task']
                if not owned:purpose='content'
            route=recovery_uses.key([parent,dependency,purpose])
            if route in seen:continue
            d3._require(len(edges)<recovery_uses.MAX_ROWS,'Recovery rooted use closure exceeds bound')
            seen.add(route);edges.append(dict(root=index,parent=parent,dependency=dependency,purpose=purpose))
            # Every flattened direct dependency keeps each actual rooted reason as well.
            if parent is not None:pending.append((None,dependency,purpose))
            if dependency['kind'] in ('artifact','recovery'):
                pointer=dependency['reference'];name=recovery_uses.key(pointer)
                d3._require(name in metadata,'Recovery use has an unacquired managed parent')
                pending.extend((pointer,child,purpose) for child in metadata[name])
    try:
        contract=recovery_uses.build(roots,edges)
        recovery_uses.check_coverage(contract,direct,metadata)
        return contract
    except recovery_uses.UseContractError as exc:raise Pending(str(exc)) from None


def _project_recovery_uses(content,contexts,contracts,legacy_routes=()):
    """Release may remove proved routes; unknown replacements cannot invent admission."""
    direct,metadata,_=_recovery_use_graph(content,contexts)
    try:
        contract=recovery_uses.merge([*contracts,recovery_uses.build([],[],legacy_routes)])
        return recovery_uses.project(contract,direct,metadata)
    except recovery_uses.UseContractError as exc:raise Pending(str(exc)) from None


def _existing_recovery_age(contexts,identity):
    """Observe one original source age across stores, with no cross-store transaction held."""
    from runtime import evidence
    ages=set()
    for context in contexts:
        with evidence._context_database(context) as db:
            baseline=task_state._source_baseline(None,db,context=context)
            if baseline is None: continue
            matches=[edge for edge in baseline['dependencies'] if _canonical_plain(edge['reference']['identity'])==identity]
            d3._require(len(matches)<=1,'Conflicting original recovery source age edges')
            if matches:
                reference=_canonical_plain(matches[0]['reference']['artifact'])
                evidence._recovery_source_history(context,db,reference,identity)
                ages.add(task_state._metadata(db,reference['name'])['created_at'])
    d3._require(len(ages)<=1,'Conflicting original recovery source ages')
    return next(iter(ages)) if ages else None


def _observe_recovery_source(path, journal, contexts, task_refs):
    """Observe exact existing source owners under caller-held complete authority guards."""
    raw=d3._read_file(path/'transaction.json',MAX_JOURNAL,private=True)
    d3._require(d3.read_request(raw)==journal,'Recovery journal changed during source observation')
    _scoped_journal_shape(journal); contexts=tuple(contexts)
    use_roots=[]
    tasks,assignments,artifacts,foreign=_collect_recovery_references(journal['manifest'],contexts,task_refs,use_roots=use_roots)
    d3._require(not foreign,'Recovery requires another physical authority')
    for ref in task_refs:
        task_state._task_reference(_canonical_plain(ref))
        d3._require(any(t['reference']==_canonical_plain(ref) for t in tasks),'Named recovery task unavailable')
    canonical=lambda values: sorted(values,key=d3._digest)
    content=dict(version=1,kind='d4-recovery-source',identity=dict(plan_dir=str(path),transaction_id=journal['transaction_id'],manifest_digest=journal['manifest_digest']),
        journal=dict(sha256=hashlib.sha256(raw).hexdigest(),observed_at=task_state._owner_time(),state=journal['state']),
        authorities=canonical([_canonical_plain(c.authority_set[0]) for c in contexts]),tasks=canonical(tasks),assignments=canonical(assignments),artifacts=canonical(artifacts),previous=None)
    from runtime import evidence
    if any(reason['root']['purpose']=='historical-stop' for reason in use_roots):
        content['use_contract']=_build_recovery_uses(content,contexts,use_roots)
    prior_cuts=[];supersedes=[];contracts=[];legacy_sources=[]
    if 'use_contract' in content:contracts.append(content['use_contract'])
    for context in contexts:
        authority=_canonical_plain(context.authority_set[0])
        _,sources=_recovery_sources(context)
        for reference,prior in sources:
            if prior['identity']!=content['identity']:continue
            with evidence._context_database(context) as db:
                history=evidence._recovery_source_history(context,db,reference,content['identity'])
            for prior_reference,prior_body in history:
                if 'use_contract' in prior_body:contracts.append(prior_body['use_contract'])
                else:
                    origin=dict(authority=authority,artifact=prior_reference,identity=prior_body['identity'],journal_sha256=prior_body['journal']['sha256'])
                    legacy_sources.append((origin,prior_body))
            if prior['version']==2:
                prior_cuts.extend(prior['stopped']);supersedes.extend(prior['supersedes'])
    if contracts:
        legacy_routes=[recovery_uses.legacy_projection(origin,body) for origin,body in legacy_sources]
        try:content['use_contract']=recovery_uses.merge([*contracts,recovery_uses.build([],[],legacy_routes)])
        except recovery_uses.UseContractError as exc:raise Pending(str(exc)) from None
    if prior_cuts or supersedes:
        content=_cut_recovery_content(content,list({d3._digest(c):c for c in prior_cuts}.values()),contexts)
        content['supersedes']=sorted({d3._digest(c):c for c in supersedes}.values(),key=d3._digest)
    elif contracts:
        content['use_contract']=_project_recovery_uses(content,contexts,[content['use_contract']])
    generations={}
    for context in contexts:
        authority=_canonical_plain(context.authority_set[0])
        with evidence._context_database(context) as db:
            selected=[t for t in content['tasks'] if t['reference']['authority']==authority]
            for item in selected:
                ref=item['reference']; current=task_state._task(db,ref['scope_id'],ref['client'],ref['session_id'],ref['task_id'])
                d3._require(current is not None and all(current[k]==item[k] for k in ('revision','pins','turn_id')),
                    'Selected recovery owner changed during observation')
            generations[d3._digest(authority)]=_recovery_generation(db,selected,[a for a in content['assignments'] if a['authority']==authority])
    created_at=_existing_recovery_age(contexts,content['identity'])
    if created_at is None: created_at=task_state._owner_time()
    return _RecoverySourceObservation(_canonical_freeze(content),contexts,_canonical_freeze(generations),created_at,_RECOVERY_ISSUER,
        ready_inputs=_recovery_ready_inputs(content,contexts))


def _check_recovery_source(source,context,db,*,writer=None):
    from runtime import evidence
    d3._require(isinstance(source,_RecoverySourceObservation) and source.issuer is _RECOVERY_ISSUER,'D4 owner-observed recovery source is required')
    authority=_canonical_plain(context.authority_set[0]); content=_canonical_plain(source.content)
    evidence._recovery_source_shape(content,content['identity'])
    d3._require(authority in content['authorities'],'Recovery registration physical authority differs')
    for observed in source.contexts: evidence._check_context(observed)
    originals=_canonical_plain(source.release) if source.release is not None else content
    tasks=[t for t in originals['tasks'] if t['reference']['authority']==authority]
    assignments=[a for a in originals['assignments'] if a['authority']==authority]
    d3._require(_recovery_generation(db,tasks,assignments)==source.generations[d3._digest(authority)],
        'Recovery source selected owner generation changed')
    for item in content['artifacts']:
        if item['authority']==authority:
            evidence._managed_artifact(None,item['artifact'],context=context,db=db)
    for certificate in content.get('stopped',[]):
        if certificate['reference']['authority']!=authority:continue
        identity=_check_stopped_certificate(context,db,certificate,writer=writer)
        historical=certificate.get('linked') and evidence._linked_component_closed(evidence._linked_basis_root(certificate['linked']),
            writer=writer if writer is not None else (context,db))
        if certificate.get('writer_stop') and identity['status']=='live' and not historical:
            key=d3._digest(certificate['reference'])
            d3._require(source.ready_inputs is not None and key in source.ready_inputs,'Ready source needs its actual bounded input observation')
            evidence._check_ready_inputs(_canonical_plain(source.ready_inputs[key]))
    if source.release is not None:
        baseline=task_state._source_baseline(None,db,context=context)
        matches=[edge for edge in baseline['dependencies'] if _canonical_plain(edge['reference']['identity'])==content['identity']]
        d3._require(len(matches)==1,'Recovery release source head unavailable')
        head=_canonical_plain(matches[0]['reference']['artifact'])
        expected=next(row['artifact'] for row in originals['heads'] if row['authority']==authority)
        if head!=expected:
            current=evidence._read(None,head,context=context,db=db)
            comparable=deepcopy(content); comparable['journal']['observed_at']=current['journal']['observed_at']
            d3._require(current==comparable,'Recovery release source head changed')
    evidence._check_context(context,db)
    raw=d3._read_file(Path(content['identity']['plan_dir'])/'transaction.json',MAX_JOURNAL,private=True)
    d3._require(hashlib.sha256(raw).hexdigest()==content['journal']['sha256'],'Recovery journal changed before registration')


def _check_recovery_source_global(source):
    """Recheck each existing store before opening the next local registration writer."""
    from runtime import evidence
    for context in source.contexts:
        with evidence._context_database(context) as db:
            _check_recovery_source(source,context,db)
    age=_existing_recovery_age(source.contexts,_canonical_plain(source.content['identity']))
    d3._require(age is None or age==source.created_at,'Original recovery source age changed')


def _recovery_context(authority):
    from runtime import evidence
    path=Path(authority['database'])
    task_state._sidecars(path)
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=0.1)) as db:
        db.execute('pragma trusted_schema=off'); db.execute('begin')
        return evidence._existing_authority_context(authority,db=db)


def _recovery_sources(context,*,validate_stops=True,preparation_reader=None):
    from runtime import evidence
    with evidence._context_database(context) as db:
        baseline=task_state._source_baseline(None,db,context=context)
        if baseline is None: return None,[]
        sources=[]
        for edge in baseline['dependencies']:
            reference=_canonical_plain(edge['reference']['artifact'])
            content=evidence._read(None,reference,context=context,db=db)
            metadata=task_state._metadata(db,reference['name'])
            d3._require(metadata['class']=='compact' and metadata['owner']==dict(kind='project',project_id=baseline['content']['project_id'],task=None)
                and metadata['closed_at'] is None and not metadata['targets'] and metadata['export'] is None,'Recovery source metadata owner differs')
            evidence._recovery_source_history(context,db,reference,_canonical_plain(edge['reference']['identity']),validate_stops=validate_stops,preparation_reader=preparation_reader)
            evidence._recovery_source_shape(content,_canonical_plain(edge['reference']['identity']))
            sources.append((reference,content))
        return baseline,sources


def _recovery_foreign_authorities(context,manifest):
    return _collect_recovery_references(manifest,(context,))[3]


def _validate_recovery_references(content,contexts,*,preparation_reader=None):
    from runtime import evidence,delegation
    by_authority={d3._digest(_canonical_plain(c.authority_set[0])):c for c in contexts}
    generations={}
    for context in contexts:
        authority=_canonical_plain(context.authority_set[0])
        with evidence._context_database(context) as db:
            generations[d3._digest(authority)]=_recovery_generation(db,[t for t in content['tasks'] if t['reference']['authority']==authority],
                [a for a in content['assignments'] if a['authority']==authority])
            for item in content['tasks']:
                ref=item['reference']; task_state._task_reference(ref)
                if ref['authority']!=authority: continue
                task=task_state._task(db,ref['scope_id'],ref['client'],ref['session_id'],ref['task_id'])
                d3._require(task is not None and task['pins']==item['pins'],'Recovery original task unavailable or changed')
            selected=[a for a in content['assignments'] if a['authority']==authority]
            for assignment in selected:
                row=db.execute('select id,scope_id,client,session_id,task_id,dispatch_id,data from assignments where id=?',(assignment['id'],)).fetchone()
                d3._require(row is not None,'Recovery original assignment unavailable')
                record=delegation._record(None,row,db=db,context=context)
                owner=record['owner']
                original=task_state._task(db,owner['scope_id'],owner['client'],owner['session_id'],owner['task_id'])
                d3._require(record['owner']==assignment['owner'] and record['data']['assignment']==assignment['assignment'] and original is not None
                    and original['pins']==record['body']['pins'] and original['accepted_identity']==record['body']['accepted_identity'],
                    'Recovery original assignment unavailable or changed')
            for item in content['artifacts']:
                if item['authority']==authority:
                    evidence._managed_artifact(None,item['artifact'],context=context,db=db)
            for certificate in content.get('stopped',[]):
                if certificate['reference']['authority']==authority: _check_stopped_certificate(context,db,certificate,preparation_reader=preparation_reader)
    for item in [*[t['reference'] for t in content['tasks']],*content['assignments'],*content['artifacts']]:
        d3._require(d3._digest(item['authority']) in by_authority,'Recovery reference physical authority unavailable')
    return generations


@contextmanager
def _scoped_source_guards(locations,owner,manifest):
    """Reacquire a complete finite source-authority set before registration/effects."""
    pending={Path(d):None for d in locations}
    for _ in range(4096):
        expanded={}; contexts=[]
        with _authority_guards(pending,owner) as guards:
            for directory,expected in pending.items():
                database=directory/'runtime.sqlite3'
                version=locations.get(directory,(None,3))[1]
                if expected is not None:
                    context=_recovery_context(expected)
                elif version==3 and os.path.lexists(database):
                    context=_recovery_context(task_state._authority_identity(database))
                else: continue
                contexts.append(context)
                _,sources=_recovery_sources(context)
                candidates=_recovery_foreign_authorities(context,manifest)
                candidates += [a for _,content in sources for a in content['authorities']]
                for authority in candidates:
                    other=Path(authority['directory'])
                    if other not in pending: expanded[other]=authority
                    elif pending[other] is not None:
                        d3._require(pending[other]==authority,'Conflicting prior physical authority bindings')
                    else:
                        d3._require(task_state._authority_identity(other/'runtime.sqlite3')==authority,'Prior physical authority changed')
            if not expanded:
                yield guards,tuple(contexts)
                return
            d3._require(len(pending)+len(expanded)<=4096,'Recovery authority closure exceeds bound')
        pending.update(expanded)
    raise Pending('Recovery authority closure did not converge')


def _scoped_writer_locations(locations,contexts):
    # Historical schema3 reads use the exact discovered binding, never a synthetic scope.
    return dict(locations) | {context.directory:(context,3) for context in contexts}


def _d4_owned_transition(journal,key):
    record=journal['manifest']['enrollment']['record'];_,prior=_scoped_prior(journal['plan'])
    affected={tuple(member[k] for k in ('repository_id','checkout_id','client')) for member in journal['manifest']['enrollment']['affected']}
    before=_scoped_entries(prior).get(key);after=_scoped_entries(record).get(key)
    return key in affected and (before is None or after is None or _scoped_projection(prior,key)!=_scoped_projection(record,key)
        or before[2]['activation']!=after[2]['activation'])


def _d4_taskless_permission(journal,context,db,project):
    """Stored physical identities locate an owner; only fresh authority/grant facts permit bookkeeping."""
    from runtime import evidence
    from runtime.startup import decode_project_record,canonical_scope_projection
    rows=db.execute('select scope_id,physical_identity from checkouts where project_id=? limit 4097',(project,)).fetchall()
    d3._require(0<len(rows)<=4096,'Taskless D4 source Project identity is unavailable or excessive')
    identities={};roots={}
    for scope_id,raw in rows:
        identity=task_state.json_object(raw)
        task_state._fields(identity,('version','project_id','repository_id','checkout_id','project_root','project_binding',
            'primary_root','repository_root','git_dir','git_common_dir','bindings'))
        d3._require(type(identity['version']) is int and identity['version']==1 and identity['project_id']==project and
            scope_id==d3._digest([3,project,identity['repository_id'],identity['checkout_id']]),'Taskless D4 source physical identity differs')
        task_state._canonical_path(identity['project_root']);task_state._canonical_binding(identity['project_binding'])
        identities[scope_id]=identity;roots[d3._digest([identity['project_root'],identity['project_binding']])]=identity
    d3._require(len(roots)==1,'Taskless D4 source Project authority is ambiguous')
    identity=next(iter(roots.values()));root=Path(identity['project_root'])
    d3._require(evidence._binding(root)==identity['project_binding'],'Taskless D4 source Project physical ownership changed')
    observed=d3._authority_observation(root,{'paths':0,'bytes':0},canonical_only=True)
    record=journal['manifest']['enrollment']['record'];_,prior=_scoped_prior(journal['plan'])
    own=project==record['project_id'] and str(root)==record['project_root'] and identity['project_binding']==record['project_binding']
    d3._require(not observed['error'],'Taskless D4 source current Project authority is unavailable')
    candidates=[]
    if observed['record'] is not None:
        d3._require(observed['record']['project_id']==project,'Taskless D4 source current Project owner changed')
        candidates.append(('current',observed['record']))
    if own:
        candidates.extend((phase,value) for phase,value in (('before',prior),('after',record)) if value and value.get('schema_version')==2)
    else:d3._require(observed['record'] is not None,'Taskless D4 source current Project authority is unavailable')
    proofs={}
    for phase,value in candidates:
        decoded=decode_project_record(value)
        for key,(_,_,entry) in _scoped_entries(value).items():
            configuration=entry['configuration']
            if configuration is None or configuration['runtime']!=dict(schema_version=3,state_dir=str(context.directory)):continue
            if phase!='current' and not _d4_owned_transition(journal,key):continue
            if phase=='current' and entry['activation']['status']=='suspended':continue
            projection=canonical_scope_projection(decoded,repository_id=key[0],checkout_id=key[1],client=key[2])
            if projection is None:continue
            if phase=='current' and projection['membership']['included'] is not True:continue
            projection=_canonical_plain(projection);scope_id=d3._digest([3,project,key[0],key[1]])
            if identities.get(scope_id)!=task_state._physical_identity(projection):continue
            d3._require(configuration['runtime_digest']==task_state.runtime_fingerprint() and
                configuration['policy_digest']==policy_digest(task_state.PACKAGE),'Taskless D4 source current bookkeeping configuration changed')
            d3._require(all(evidence._binding(Path(projection[path]))==projection['bindings'][binding]
                for path,binding in (('repository_root','root'),('primary_root','primary_root'),('git_dir','git_dir'),('git_common_dir','git_common_dir'))),
                'Taskless D4 source physical member bindings changed')
            proof=dict(subject={k:projection[k] for k in ('project_id','repository_id','checkout_id','client')},phase=phase,identity=projection)
            proofs[d3._digest(proof)]=proof
    d3._require(proofs,'Taskless D4 source has no exact current or owned-transition bookkeeping permission')
    return dict(project_id=project,authority=_canonical_plain(context.authority_set[0]),current=observed,
        permitted=[proofs[key] for key in sorted(proofs)])


def _d4_permission_facts(journal,source):
    from runtime import evidence
    record=journal['manifest']['enrollment']['record'];root=Path(record['project_root'])
    d3._require(_scoped_owned_authority(journal),'Current D4 Project authority changed outside its owned transition')
    _scoped_owner_bindings(journal['plan'])
    target=_scoped_target(root,str(PROJECT_FILE))
    current=d3.read_request(d3._read_file(root/PROJECT_FILE,128*1024)) if target['binding'] is not None else None
    subjects={};sources=[];current_permissions=[];project_permissions={}
    _,prior=_scoped_prior(journal['plan'])
    for candidate in (prior,record):
        if not candidate or candidate.get('schema_version')!=2:continue
        for key,(repository,checkout,entry) in _scoped_entries(candidate).items():
            configuration=entry['configuration']
            if configuration and configuration['runtime'] and any(
                    configuration['runtime']==dict(schema_version=3,state_dir=str(c.directory)) for c in source.contexts):
                subject=dict(project_id=candidate['project_id'],repository_id=key[0],checkout_id=key[1],client=key[2])
                subjects[d3._digest(subject)]=subject
    by_authority={d3._digest(_canonical_plain(c.authority_set[0])):c for c in source.contexts}
    refs={d3._digest(t['reference']):t['reference'] for t in _canonical_plain(source.content)['tasks']}
    # Artifact ownership may be retained; explicit task requirements still need raw rows.
    owners={}
    for item in _canonical_plain(source.content)['artifacts']:
        context=by_authority[d3._digest(item['authority'])]
        with evidence._context_database(context) as db:
            metadata,_=evidence._managed_artifact(None,item['artifact'],context=context,db=db)
            d3._require(metadata['version']==2,'Legacy D4 body cannot gain prospective admission')
            if metadata['owner']['task'] is not None:
                ref=metadata['owner']['task']
                owners[d3._digest(ref)]=(ref,evidence._source_subject(context,db,metadata))
            else:
                key=(str(context.database),metadata['owner']['project_id'])
                if key not in project_permissions:
                    project_permissions[key]=_d4_taskless_permission(journal,context,db,metadata['owner']['project_id'])
                    for proof in project_permissions[key]['permitted']:
                        subjects[d3._digest(proof['subject'])]=proof['subject']
            sources.append(dict(reference=item,metadata=metadata))
    for ref in refs.values():
        context=by_authority[d3._digest(ref['authority'])]
        with evidence._context_database(context) as db:
            task=task_state._task(db,ref['scope_id'],ref['client'],ref['session_id'],ref['task_id'])
            d3._require(task is not None,'Current D4 subject owner is unavailable')
            owners[d3._digest(ref)]=(ref,dict(identity=task['accepted_identity'],pins=task['pins']))
    for ref,owner in owners.values():
        context=by_authority[d3._digest(ref['authority'])]
        with evidence._context_database(context) as db:
            identity=task_state._accepted_identity(owner['identity'])
            subject={k:identity[k] for k in ('project_id','repository_id','checkout_id','client')}
            subjects[d3._digest(subject)]=subject
            own=identity['project_id']==record['project_id'] and identity['project_root']==str(root)
            key=tuple(identity[k] for k in ('repository_id','checkout_id','client'))
            transition=own and _d4_owned_transition(journal,key)
            if transition:
                d3._require(evidence._binding(Path(identity['project_root']))==identity['project_binding'] and
                    all(evidence._binding(Path(identity[k]))==identity['bindings'][binding]
                    for k,binding in (('repository_root','root'),('primary_root','primary_root'),('git_dir','git_dir'),('git_common_dir','git_common_dir'))),
                    'D4 source subject physical bindings changed')
            else:
                from runtime.startup import decode_project_record,canonical_scope_projection
                observed=d3._authority_observation(Path(identity['project_root']),{'paths':0,'bytes':0},canonical_only=True)
                d3._require(not observed['error'] and observed['record'] is not None,'Current D4 source enrollment is unavailable')
                current_identity=canonical_scope_projection(decode_project_record(observed['record']),repository_id=identity['repository_id'],
                    checkout_id=identity['checkout_id'],client=identity['client'])
                d3._require(current_identity is not None and _canonical_plain(current_identity)==identity,
                    'Current D4 source subject enrollment changed')
                d3._require(_scoped_entries(observed['record'])[key][2]['activation']['status']!='suspended',
                    'Current D4 source bookkeeping permission is suspended')
                current_permissions.append(dict(subject=subject,authority=observed))
                for item in sources:
                    if item['metadata']['owner']['task']==ref:
                        permission=evidence._source_current_permission(context,dict(artifact=item['reference']['artifact'],
                            owner=item['metadata']['owner'],created_at=item['metadata']['created_at'],pins=owner['pins']),db=db)
                        current_permissions.append(dict(source=item['reference'],permission=permission))
    return dict(subjects=sorted(subjects.values(),key=d3._digest),record=dict(path=str(root/PROJECT_FILE),target=target,content=current),
        sources=sources,current_permissions=current_permissions,project_permissions=[project_permissions[key] for key in sorted(project_permissions)])


def _check_d4_publication(source,context,db):
    from runtime import evidence
    lifetime=getattr(_authority_context,'publication',None)
    d3._require(lifetime is not None and lifetime['active'] and lifetime['source'] is source,
        'Recovery publication requires its actual active owner lifetime')
    d3._require(all(observation['active'] and any(observation is held for held in getattr(_authority_context,'held',()))
        for observation in lifetime['guards']) and _held_authority_guards(c.directory for c in source.contexts),
        'Recovery publication guards expired or changed')
    # Peer preparation reads must see this transaction's uncommitted metadata.
    writer=(context,db)
    _check_recovery_source(source,context,db,writer=writer)
    for other in source.contexts:
        if other.database!=context.database:
            with evidence._context_database(other) as reader:_check_recovery_source(source,other,reader,writer=writer)
    if lifetime['kind']=='operation':
        _check_d4_grant(lifetime['grant'])
        approved=_canonical_plain(lifetime['grant'].facts)
        d3._require(approved['registration_projections']==lifetime['registration_projections'],
            'Recovery registration projection differs from actual approved acquisition')
        d3._require(approved['source']==_canonical_plain(source.content) and approved['generations']==_canonical_plain(source.generations)
            and approved['created_at']==source.created_at,'D4 source content differs from actual approved acquisition')
        d3._require(_d4_permission_facts(lifetime['journal'],source)==lifetime['permissions'],
            'Current D4 subject, source or owned enrollment transition changed')
        for location in lifetime['markers']:
            d3._require(_authority_owner(location)==lifetime['owner'],'D4 protective operation marker changed')
    else:
        d3._require(source.provenance is _RECOVERY_RELEASE_ISSUER and source.release is not None,
            'Recovery release requires its distinct actual factory')
        d3._require(_scoped_owned_authority(lifetime['journal']),'Recovery release owned effects changed')
        _scoped_recovery_files(Path(source.content['identity']['plan_dir']),lifetime['journal'])
        current=_load_journal(Path(source.content['identity']['plan_dir']))
        d3._require(current==lifetime['journal'],'Recovery release journal changed')
        for action in current['manifest']['actions']:
            receipt=current['receipts'][action['id']]
            for effect,file in zip(action['effects'],receipt['files']):
                root=Path(action['owner']['root']);target=_scoped_target(root,effect['path'])
                expected=effect['before'] if current['state']=='rolled_back' else effect['after']
                binding=file['before_binding'] if current['state']=='rolled_back' else file['result_binding']
                d3._require(_fingerprint(root,effect['path'])==expected and target['binding']==binding,
                    'Recovery release effect changed before commit')
    return lifetime


@contextmanager
def _d4_publication_batch(path,journal,contexts,request,host,owner,markers):
    from runtime import evidence
    if not contexts:
        for location in markers:_atomic(location.parent,location.name+'.json',json.dumps(owner,sort_keys=True).encode())
        yield None
        return
    if not isinstance(host,_D4HostCapability):raise Pending('Actual trusted D4 host authority is unavailable; bookkeeping remains pending')
    source=_observe_recovery_source(path,journal,contexts,())
    permissions=_d4_permission_facts(journal,source)
    baselines=[];projections={}
    for context in contexts:
        with evidence._context_database(context) as db:
            baseline=task_state._source_baseline(None,db,context=context)
            d3._require(baseline is not None and baseline['content']['source_contract']==2,'D4 requires original source_contract2 coverage')
            project=baseline['content']['project_id']
            d3._require(project==journal['manifest']['enrollment']['record']['project_id'] or any(
                subject['project_id']==project for subject in permissions['subjects']),'D4 Project owner lacks exact current subject coverage')
            baselines.append(dict(authority=_canonical_plain(context.authority_set[0]),baseline=_canonical_plain(baseline)))
            content=_canonical_plain(source.content)
            heads=[edge['reference']['artifact'] for edge in baseline['dependencies'] if _canonical_plain(edge['reference']['identity'])==content['identity']]
            d3._require(len(heads)<=1,'Recovery original baseline head is ambiguous')
            inputs=evidence._recovery_use_inputs(context,db,_canonical_plain(heads[0]) if heads else None,content['identity'],content=content)
            projections[str(context.database)]=evidence._recovery_registration_projection(content,source.created_at,inputs)
    facts=dict(operation='protective-recovery-bookkeeping',request=request,plan=journal['plan'],identity=_canonical_plain(source.content)['identity'],
        journal=_canonical_plain(source.content)['journal'],permissions=permissions,baselines=baselines,
        source=_canonical_plain(source.content),generations=_canonical_plain(source.generations),created_at=source.created_at,
        registration_projections=projections)
    with _acquire_d4_grant(host,facts) as grant:
        for location in markers:_atomic(location.parent,location.name+'.json',json.dumps(owner,sort_keys=True).encode())
        lifetime=dict(active=True,kind='operation',source=source,grant=grant,permissions=permissions,journal=deepcopy(journal),
            guards=tuple(getattr(_authority_context,'held',())),markers=tuple(markers),owner=owner,registrations={},
            baselines={str(context.database):item['baseline'] for context,item in zip(contexts,baselines)},
            registration_projections=_canonical_plain(grant.facts)['registration_projections'])
        previous=getattr(_authority_context,'publication',None);_authority_context.publication=lifetime
        try:yield lifetime
        finally:lifetime['active']=False;_authority_context.publication=previous


def _scoped_register_sources(path,journal,contexts):
    """Called only under the operation's complete ordered authority guards."""
    from runtime import evidence
    if not contexts: return
    lifetime=getattr(_authority_context,'publication',None)
    d3._require(lifetime is not None and lifetime['kind']=='operation','D4 source publication requires actual host acquisition')
    source=lifetime['source']
    d3._require(tuple(contexts)==source.contexts,'D4 registration omitted an acquired authority')
    for context in contexts:
        _check_recovery_source_global(source)
        with evidence._context_database(context,write=True,durable=True,before_commit=lambda db,context=context:evidence._check_recovery_registration(context,db,source)) as db:
            # Legacy/baselineless lifetimes remain unknown; never retrofit a baseline.
            d3._require(task_state._source_baseline(None,db,context=context) is not None,
                'Existing schema3 source baseline is unavailable; preserve recovery markers')
            evidence._register_recovery_source(None,db,source,context=context)
    d3._require(set(lifetime['registrations'])=={str(context.database) for context in contexts},'D4 all-peer registrations are incomplete')
    for context in contexts:
        with evidence._context_database(context) as db:evidence._check_recovery_registration(context,db,source)


def _recovery_release_journal(identity):
    path=d3._plan_path(identity['plan_dir']); journal=_load_journal(path)
    d3._require(journal is not None and journal['schema_version']==2 and
        all(journal[k]==identity[k] for k in ('transaction_id','manifest_digest')),'Recovery release journal identity differs')
    d3._require(journal['state'] in ('applied','rolled_back'),'Recovery release requires a settled physical journal')
    _validate_scoped(dict(schema_version=2,manifest=journal['manifest'],approval=journal['approval']),journal['plan'])
    return path,journal


@contextmanager
def _recovery_release_guards(authorities,identity):
    path,journal=_recovery_release_journal(identity)
    manifest=journal['manifest']; plan=journal['plan']; root=Path(manifest['enrollment']['record']['project_root'])
    before,prior=_scoped_prior(plan)
    lock_root=d3._plan_path(LOCK_ROOT)
    keys={'destination:'+str(root/PROJECT_FILE),'parent:'+str(root)+':'+d3._digest(plan['identity']['binding'])}
    if before['binding']: keys.add('inode:'+d3._digest(before['binding']))
    with ExitStack() as locks:
        for key in sorted(keys):
            location=lock_root/('canonical-'+hashlib.sha256(key.encode()).hexdigest()+'.lock')
            try:
                fd=os.open(location,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd)
            except FileExistsError: pass
            locks.enter_context(_lock(location))
            d3._require(_authority_owner(location) is None,'Recovery release has an active canonical operation')
        git_dirs={a['owner']['git_dir'] for a in manifest['owners'] if a['owner']['kind']=='repository'}
        if plan['identity']['kind']=='standalone':
            git_dirs.update(a['owner']['git_common_dir'] for a in manifest['owners'] if a['owner']['kind']=='repository')
        for git_dir in sorted(git_dirs):
            locks.enter_context(_worktree_lock(git_dir))
            d3._require(_command_owner(git_dir) is None,'Recovery release has an active command')
        locations=_scoped_runtime_locations([prior,manifest['enrollment']['record']])
        supplied={Path(a['directory']):a for a in _canonical_plain(authorities)}
        d3._require(0<len(supplied)<=4096,'Recovery release authority set is empty or excessive')
        for directory,authority in supplied.items():
            d3._require(task_state._authority_identity(Path(authority['database']))==authority,'Recovery release physical authority differs')
            locations[directory]=(_recovery_context(authority),3)
        with _scoped_source_guards(locations,None,manifest) as (_,contexts):
            d3._require(_load_journal(path)==journal,'Recovery release journal changed while acquiring guards')
            _scoped_owner_bindings(plan);_scoped_recovery_files(path,journal)
            d3._require(_scoped_owned_authority(journal),'Recovery release canonical physical ownership changed')
            for action in manifest['actions']:
                receipt=journal['receipts'].get(action['id'])
                d3._require(receipt is not None,'Recovery release action receipt is missing')
                if receipt.get('command'):
                    d3._require(receipt['command']['stopped'] is True,'Recovery release command descendants remain uncertain')
                for effect,file in zip(action['effects'],receipt['files']):
                    root=Path(action['owner']['root']); current=_scoped_target(root,effect['path'])
                    expected=effect['before'] if journal['state']=='rolled_back' else effect['after']
                    binding=file['before_binding'] if journal['state']=='rolled_back' else file['result_binding']
                    d3._require(_fingerprint(root,effect['path'])==expected and current['binding']==binding,
                        'Recovery release effect physical ownership changed')
            roots,git_roots=_scoped_writer_roots(manifest)
            _scoped_writers(_scoped_writer_locations(locations,contexts),roots,git_roots,changed_paths=_scoped_changed_paths(manifest))
            yield path,journal,contexts


def _observe_recovery_release(authorities,identity):
    """Private stopped-proof replacement; neither general closure nor public release."""
    from runtime import evidence
    identity=_canonical_plain(identity)
    with _recovery_release_guards(authorities,identity) as (path,journal,contexts):
        heads=[]; supersedes=[]; tasks={};assignments={};artifacts={};certificates={}; generations={};ages=set();contracts=[];legacy_sources=[]
        for context in contexts:
            authority=_canonical_plain(context.authority_set[0])
            baseline,sources=_recovery_sources(context)
            d3._require(baseline is not None and baseline['content']['source_contract']==2,'Recovery release requires creation-time D4 coverage')
            matches=[(ref,c) for ref,c in sources if c['identity']==identity]
            d3._require(len(matches)==1,'Recovery release source head unavailable')
            reference,current=matches[0];heads.append(dict(authority=authority,artifact=reference))
            raw=d3._read_file(path/'transaction.json',MAX_JOURNAL,private=True)
            d3._require(current['journal']['sha256']==hashlib.sha256(raw).hexdigest() and current['journal']['state']==journal['state'],
                'Recovery release journal snapshot requires reconciliation')
            with evidence._context_database(context) as db:
                ages.add(task_state._metadata(db,reference['name'])['created_at'])
                history=evidence._recovery_source_history(context,db,reference,identity)
            for prior_ref,content in history:
                _validate_recovery_references(content,contexts)
                if 'use_contract' in content:contracts.append(content['use_contract'])
                else:
                    origin=dict(authority=authority,artifact=prior_ref,identity=content['identity'],journal_sha256=content['journal']['sha256'])
                    legacy_sources.append((origin,content))
                if content['version']==2:
                    for row in content['supersedes']: supersedes.append(row)
                    for c in content['stopped']:certificates[d3._digest(c['reference'])]=c
                else:
                    supersedes.append(dict(authority=authority,artifact=prior_ref,identity=identity,journal_sha256=content['journal']['sha256']))
                for task in content['tasks']:tasks[d3._digest(task['reference'])]=task
                for assignment in content['assignments']:assignments[d3._digest(assignment)]=assignment
                for artifact in content['artifacts']:artifacts[d3._digest(artifact)]=artifact
        d3._require(len(ages)==1,'Recovery release original source ages differ')
        for context in contexts:
            authority=_canonical_plain(context.authority_set[0])
            with evidence._context_database(context) as db:
                selected=[t for t in tasks.values() if t['reference']['authority']==authority]
                associated=[a for a in assignments.values() if a['authority']==authority]
                generations[d3._digest(authority)]=_recovery_generation(db,selected,associated)
                for task in selected:
                    cert=_stopped_certificate(context,db,task);certificates[d3._digest(cert['reference'])]=cert
        canonical=lambda rows:sorted(rows,key=d3._digest)
        content=dict(version=2,kind='d4-recovery-source',identity=identity,
            journal=dict(sha256=hashlib.sha256(raw).hexdigest(),observed_at=task_state._owner_time(),state=journal['state']),
            authorities=canonical([_canonical_plain(c.authority_set[0]) for c in contexts]),tasks=canonical(list(tasks.values())),
            assignments=canonical(list(assignments.values())),artifacts=canonical(list(artifacts.values())),previous=None,
            supersedes=canonical(list({d3._digest(row):row for row in supersedes}.values())))
        if contracts:
            legacy_routes=[recovery_uses.legacy_projection(origin,body) for origin,body in legacy_sources]
            try:content['use_contract']=recovery_uses.merge([*contracts,recovery_uses.build([],[],legacy_routes)])
            except recovery_uses.UseContractError as exc:raise Pending(str(exc)) from None
        content=_cut_recovery_content(content,list(certificates.values()),contexts)
        original=dict(heads=heads,tasks=list(tasks.values()),assignments=list(assignments.values()))
        return _RecoverySourceObservation(_canonical_freeze(content),tuple(contexts),_canonical_freeze(generations),next(iter(ages)),_RECOVERY_ISSUER,_canonical_freeze(original),
            _recovery_ready_inputs(content,contexts),_RECOVERY_RELEASE_ISSUER)


def _register_recovery_release(observation):
    """Sequential existing-store replacement; mixed heads retain old raw requirements."""
    from runtime import evidence
    replacements=[]
    try:
        d3._require(isinstance(observation,_RecoverySourceObservation) and observation.issuer is _RECOVERY_ISSUER and observation.provenance is _RECOVERY_RELEASE_ISSUER
            and observation.release is not None,'Recovery release requires owner-issued observation')
        content=_canonical_plain(observation.content)
        with _recovery_release_guards(content['authorities'],content['identity']) as (_,journal,contexts):
            d3._require(sorted([_canonical_plain(c.authority_set[0]) for c in contexts],key=d3._digest)==sorted([_canonical_plain(c.authority_set[0]) for c in observation.contexts],key=d3._digest),
                'Recovery release complete authority set changed')
            lifetime=dict(active=True,kind='release',source=observation,journal=deepcopy(journal),
                guards=tuple(getattr(_authority_context,'held',())),registrations={},baselines={},registration_projections={})
            for context in contexts:
                with evidence._context_database(context) as db:
                    lifetime['baselines'][str(context.database)]=_canonical_plain(task_state._source_baseline(None,db,context=context))
                    baseline=lifetime['baselines'][str(context.database)]
                    heads=[edge['reference']['artifact'] for edge in baseline['dependencies'] if edge['reference']['identity']==content['identity']]
                    d3._require(len(heads)==1,'Recovery release source head unavailable')
                    inputs=evidence._recovery_use_inputs(context,db,heads[0],content['identity'],content=content)
                    lifetime['registration_projections'][str(context.database)]=evidence._recovery_registration_projection(content,observation.created_at,inputs)
            previous=getattr(_authority_context,'publication',None);_authority_context.publication=lifetime
            try:
                for context in contexts:
                    _check_recovery_source_global(observation)
                    with evidence._context_database(context,write=True,durable=True,
                            before_commit=lambda db,context=context:evidence._check_recovery_registration(context,db,observation)) as db:
                        reference=evidence._register_recovery_source(None,db,observation,context=context)
                    replacements.append(dict(authority=_canonical_plain(context.authority_set[0]),artifact=_canonical_plain(reference)))
                _check_recovery_source_global(observation)
                for context in contexts:
                    with evidence._context_database(context) as db:evidence._check_recovery_registration(context,db,observation)
            finally:lifetime['active']=False;_authority_context.publication=previous
        return _canonical_freeze(dict(complete=True,replacements=replacements,blockers=[]))
    except (StartupError,task_state.StateError,OSError,sqlite3.Error,ValueError,TypeError,KeyError) as error:
        return _canonical_freeze(dict(complete=False,replacements=replacements,blockers=[str(error)]))


def _recovery_current_requirements(root,history):
    """Origin-qualified edges; a cut never exempts another root's old source route."""
    from runtime import evidence
    requirements=[];authority=root['authority']
    for reference,content in history:
        owner=dict(authority=authority,artifact=reference)
        requirements.append(dict(root=root,owner=owner,kind='artifact',reference=owner,need='content'))
        for edge in evidence._recovery_source_dependencies(content,authority):
            kind=edge['kind'];ref=edge['reference']
            requirements.append(dict(root=root,owner=owner,kind=kind,reference=ref,need='raw' if kind in ('task','assignment') else 'content'))
        for certificate in content.get('stopped',[]):
            requirements.append(dict(root=root,owner=owner,kind='task',reference=certificate['reference'],need='identity'))
            for assignment in certificate.get('assignments',[]):
                requirements.append(dict(root=root,owner=owner,kind='assignment',reference=assignment['reference'],need='identity'))
    d3._require(len(requirements)<=4096,'Recovery current-root requirements exceed bound')
    return requirements


def _inspect_lifecycle_recovery_guarded(authorities,task_refs):
    """One reader lifetime stays inside this read-only, caller-guarded invocation."""
    from runtime import evidence
    with evidence._linked_preparation_reader(authorities) as preparation_reader:
        return _inspect_lifecycle_recovery_read(authorities,task_refs,preparation_reader)


def _inspect_lifecycle_recovery_read(authorities,task_refs,preparation_reader):
    """Inspect one fixed set under caller-held complete guards; never acquire/expand locks."""
    from runtime import evidence
    dependencies=[];blockers=[];roots=[];requirements=[];discovered={};contexts=[];observed=[];pending={};journals={}
    def result():
        return _canonical_freeze(dict(complete=not blockers and not discovered,dependencies=dependencies,blockers=blockers,
            roots=roots,requirements=requirements,authorities=sorted([_canonical_plain(c.authority_set[0]) for c in contexts],key=d3._digest),
            discovered_authorities=sorted(discovered.values(),key=d3._digest)))
    try:
        pending={d3._digest(_canonical_plain(a)):_canonical_plain(a) for a in authorities}
        d3._require(0<len(pending)<=4096,'Recovery authority selection is empty or exceeds bound')
        for authority in pending.values():
            seen_markers=set()
            for location in _authority_locations([Path(authority['directory'])]):
                marker=_authority_owner(location)
                if marker is not None and d3._digest(marker) not in seen_markers:
                    seen_markers.add(d3._digest(marker))
                    blockers.append(dict(reason='active_or_uncertain_operation',authority=authority,owner=marker))
                    dependencies.append(dict(authority=authority,**marker,source_artifact=None,journal=None,task_refs=[]))
            context=_recovery_context(authority); contexts.append(context)
            baseline,sources=_recovery_sources(context,validate_stops=False)
            if baseline is None or baseline['content']['source_contract']!=2:
                blockers.append(dict(reason='unknown_creation_time_d4_coverage',authority=authority))
            for reference,content in sources:
                with evidence._context_database(context) as db:
                    history=evidence._recovery_source_history(context,db,reference,content['identity'],validate_stops=False)
                for _,prior in history:
                    for other in prior['authorities']:
                        key=d3._digest(other)
                        if key not in pending: discovered[key]=other
                observed.append((context,reference,content))
        if discovered:
            d3._require(len(pending)+len(discovered)<=4096,'Recovery authority closure exceeds bound')
            blockers.append(dict(reason='recovery_authority_set_incomplete'))
            return result()
        for context,reference,content in observed:
            authority=_canonical_plain(context.authority_set[0])
            path=Path(content['identity']['plan_dir'])
            raw=d3._read_file(path/'transaction.json',MAX_JOURNAL,private=True)
            journal=_scoped_journal_shape(d3.read_request(raw,limit=MAX_JOURNAL))
            journals[path]=hashlib.sha256(raw).hexdigest()
            d3._require(journal is not None and journal['schema_version']==2 and
                all(journal[k]==content['identity'][k] for k in ('transaction_id','manifest_digest')),
                'Recovery journal stable identity differs')
            if hashlib.sha256(raw).hexdigest()!=content['journal']['sha256'] or journal['state']!=content['journal']['state']:
                blockers.append(dict(reason='journal_snapshot_requires_reconciliation',identity=content['identity']))
            generations=_validate_recovery_references(content,contexts,preparation_reader=preparation_reader)
            with evidence._context_database(context) as db:
                history=evidence._recovery_source_history(context,db,reference,content['identity'],preparation_reader=preparation_reader)
            for _,prior in history:
                _validate_recovery_references(prior,contexts,preparation_reader=preparation_reader)
            current_root=dict(authority=authority,identity=content['identity'],source_artifact=reference)
            roots.append(current_root);requirements.extend(_recovery_current_requirements(current_root,history))
            d3._require(len(requirements)<=4096,'Recovery current-root requirements exceed bound')
            dependencies.append(dict(authority=authority,**content['identity'],source_artifact=reference,journal=content['journal'],
                task_refs=[t['reference'] for t in content['tasks']],assignments=content['assignments'],artifacts=content['artifacts'],generation_digest=d3._digest(generations)))
        for original_ref in task_refs:
            ref=_canonical_plain(original_ref); task_state._task_reference(ref)
            context=next((c for c in contexts if _canonical_plain(c.authority_set[0])==ref['authority']),None)
            d3._require(context is not None,'Named task authority is outside observed closure')
            with evidence._context_database(context) as db:
                identity=task_state._lifecycle_identity(db,'task',ref)
                if identity['status']!='live':
                    certificates=[certificate for _,_,value in observed for certificate in value.get('stopped',[]) if certificate['reference']==ref]
                    d3._require(certificates,'Named retired recovery task lacks retained stopped support')
                    for certificate in certificates: _check_stopped_certificate(context,db,certificate,preparation_reader=preparation_reader)
        # Sources/physical bindings must still be the exact point observations before return.
        for context,reference,content in observed:
            _,latest=_recovery_sources(context,preparation_reader=preparation_reader)
            d3._require(any(ref==reference and value==content for ref,value in latest),'Recovery source edge changed during inspection')
        for path,digest in journals.items():
            d3._require(hashlib.sha256(d3._read_file(path/'transaction.json',MAX_JOURNAL,private=True)).hexdigest()==digest,
                'Recovery journal changed during inspection')
        preparation_reader.finish()
        return result()
    except (StartupError,task_state.StateError,OSError,sqlite3.Error,ValueError,TypeError,KeyError) as error:
        blockers.append(dict(reason=str(error) if isinstance(error,(StartupError,task_state.StateError)) else 'recovery_source_unavailable'))
        return result()


def inspect_lifecycle_recovery(authorities,task_refs):
    """Finite D4 coverage with release/reacquire on discovery; no closure authorization."""
    try:
        pending={d3._digest(_canonical_plain(a)):_canonical_plain(a) for a in authorities}
        d3._require(0<len(pending)<=4096,'Recovery authority selection is empty or exceeds bound')
        for _ in range(4096):
            with _authority_guards([Path(a['directory']) for a in pending.values()],observe=True):
                inspected=_inspect_lifecycle_recovery_guarded(tuple(pending.values()),task_refs)
                discovered=[_canonical_plain(a) for a in inspected['discovered_authorities']]
                if not discovered: return inspected
                d3._require(len(pending)+len(discovered)<=4096,'Recovery authority closure exceeds bound')
            # Never acquire a discovered lower-order guard while holding a partial set.
            pending.update({d3._digest(a):a for a in discovered})
        raise Pending('Recovery authority closure did not converge')
    except (StartupError,task_state.StateError,OSError,sqlite3.Error,ValueError,TypeError,KeyError) as error:
        return _canonical_freeze(dict(complete=False,dependencies=[],blockers=[dict(reason=str(error))],roots=[],requirements=[],
            authorities=[],discovered_authorities=[]))


def _scoped_journal_shape(journal):
    d3._object(journal, ("schema_version", "transaction_id", "manifest_digest", "manifest", "approval", "plan", "state", "receipts", "enrollment", "blocked", "directories", "observations"))
    d3._require(type(journal["schema_version"]) is int and journal["schema_version"] == 2 and journal["manifest_digest"] == d3._digest(journal["manifest"])
                and journal["state"] in ("prepared", "applying", "interrupted", "applied", "blocked", "rollback_partial", "rolled_back"), "Invalid scoped journal")
    d3._require(isinstance(journal["receipts"], dict) and isinstance(journal["directories"], dict) and isinstance(journal["observations"], list), "Invalid scoped recovery containers")
    actions = {a["id"]: a for a in journal["manifest"]["actions"]}
    d3._require(set(journal["receipts"]) <= set(actions), "Unknown scoped receipt")
    for observation in journal["observations"]: _scoped_observation_shape(observation,journal["manifest"])
    for identity, receipt in journal["receipts"].items():
        d3._object(receipt, ("owner", "status", "files", "returncode"), ("command",))
        d3._require(receipt["owner"] == actions[identity]["owner"] and receipt["status"] in ("prepared", "started", "completed", "rolled_back"), "Invalid scoped receipt owner/status")
        d3._require(len(receipt["files"]) == len(actions[identity]["effects"]), "Incomplete scoped backup coverage")
        if "command" in receipt:
            command=receipt["command"]
            d3._object(command,("attempt_id","stopped"))
            d3._require(actions[identity]["execution"] is not None and isinstance(command["attempt_id"],str) and re.fullmatch(r"[0-9a-f]{32}",command["attempt_id"])
                and type(command["stopped"]) is bool,"Invalid durable scoped command identity")
            if command["stopped"]:
                d3._require(any(p["id"] == identity and p["attempt_id"] == command["attempt_id"] for o in journal["observations"] for p in o["command_reconciliation"]),
                    "Stopped command lacks its retained exact lifecycle proof")
        action_index = journal["manifest"]["actions"].index(actions[identity])
        assessment = next(a for a in d3._assessments(journal["plan"]["assessments"]) if a["owner"] == actions[identity]["owner"])
        for index, (file, effect) in enumerate(zip(receipt["files"], actions[identity]["effects"])):
            d3._object(file, ("backup", "temporary", "target", "before_binding", "prepared_binding", "result_binding", "owned_target"), ("restore", "delete_intent"))
            expected_temp = ".d4-" + journal["transaction_id"] + "-" + str(action_index) + "-" + str(index)
            d3._require(file["backup"] == ("backup-" + str(action_index) + "-" + str(index) if effect["before"] else None)
                and file["temporary"] == expected_temp and file["target"] == (effect["target"] if "target" in effect else assessment["identity"]["targets"].get(effect["path"]))
                and file["before_binding"] == file["target"]["binding"], "Scoped recovery file reference changed")
            for key in ("before_binding", "prepared_binding", "result_binding"):
                if file[key] is not None:
                    from runtime.startup import _canonical_binding
                    _canonical_binding(file[key])
            if file["owned_target"] is not None:
                from runtime.startup import _canonical_target
                _canonical_target(file["owned_target"])
                d3._require(file["owned_target"]["path"] == file["target"]["path"] and file["owned_target"]["binding"] == file["result_binding"], "Scoped owned result changed")
            if "restore" in file:
                d3._object(file["restore"], ("temporary", "before_binding", "prepared_binding", "result_binding"), ("delete_intent",))
                d3._require(file["restore"]["temporary"] == expected_temp + "-restore" and file["restore"]["before_binding"] == file["result_binding"], "Scoped restore ownership changed")
    for location, receipt in journal["directories"].items():
        d3._require(Path(location).is_absolute(), "Invalid scoped directory path")
        d3._object(receipt, ("status", "device", "inode"))
        allowed = {str(p) for action in actions.values() for effect in action["effects"] for p in (Path(action["owner"]["root"]) / effect["path"]).parents if p.is_relative_to(Path(action["owner"]["root"])) and p != Path(action["owner"]["root"])}
        allowed.add(str(Path(journal["manifest"]["enrollment"]["record"]["project_root"]) / PROJECT_FILE.parent))
        d3._require(location in allowed and receipt["status"] in ("prepared", "owned", "retained", "removed")
                    and all(v is None or type(v) is int and v >= 0 for v in (receipt["device"],receipt["inode"])), "Scoped directory ownership invalid")
    e = journal["enrollment"]
    if e is not None:
        d3._object(e, ("before", "backup", "status", "temporary", "postimages", "members"))
        d3._require(e["before"] == journal["manifest"]["enrollment"]["before"] and e["backup"] == ("enrollment.backup" if e["before"]["raw_sha256"] is not None else None)
            and e["temporary"] == ".d4-"+journal["transaction_id"]+"-enrollment" and e["status"] in ("prepared","inactive","activating","active","restoring","restored"), "Invalid canonical recovery preimage")
        d3._require(isinstance(e["members"],list) and len(e["members"]) == len(journal["manifest"]["enrollment"]["affected"]), "Incomplete scoped member outcome coverage")
        for member,accepted in zip(e["members"],journal["manifest"]["enrollment"]["affected"]):
            d3._object(member,("repository_id","checkout_id","client","status","blocked"))
            d3._require(all(member[k] == accepted[k] for k in accepted) and member["status"] in ("pending","configured","active","suspended","restored","blocked")
                and (member["blocked"] is None or isinstance(member["blocked"],str)), "Invalid scoped member outcome")
        d3._require(isinstance(e["postimages"], list) and len(e["postimages"]) <= 4, "Invalid canonical postimage sequence")
        phases=[]
        _,prior=_scoped_prior(journal["plan"])
        for post in e["postimages"]:
            d3._object(post, ("phase", "revision", "raw_sha256", "target", "backup", "temporary", "status", "before", "after", "before_binding", "prepared_binding", "result_binding"), ("delete_intent",))
            d3._require(post["phase"] in ("suspended", "final", "rollback_suspended", "restore") and post["temporary"].startswith(".d4-" + journal["transaction_id"] + "-")
                        and "/" not in post["temporary"], "Invalid canonical temporary scope")
            _fp_schema(post["before"]); _fp_schema(post["after"])
            phase=post["phase"]
            ranks={"suspended":0,"final":1,"rollback_suspended":2,"restore":3}
            d3._require(phase not in phases and (not phases or ranks[phase] > ranks[phases[-1]]) and (phase != "rollback_suspended" or "final" in phases), "Invalid canonical publication order")
            phases.append(phase)
            expected_record=journal["manifest"]["enrollment"]["record"] if phase == "final" else _scoped_suspended(journal,rollback=phase=="rollback_suspended") if phase in ("suspended","rollback_suspended") else prior
            expected_sha=hashlib.sha256(json.dumps(expected_record,sort_keys=True,ensure_ascii=True).encode()+b"\n").hexdigest() if expected_record is not None else None
            if phase == "restore": expected_sha=e["before"]["raw_sha256"]
            d3._require(post["raw_sha256"] == expected_sha and post["revision"] == (expected_record.get("revision") if expected_record else None)
                and post["temporary"] == ".d4-"+journal["transaction_id"]+"-"+phase and post["backup"] == e["backup"] and post["status"] in ("prepared","published")
                and (post["after"]["sha256"] if post["after"] else None) == expected_sha, "Canonical postimage differs from its frozen approved bytes")
            if post["after"] is not None and phase != "restore":
                d3._require(post["after"]["mode"] == 0o600, "Canonical postimage mode changed")
            for key in ("before_binding","prepared_binding","result_binding"):
                if post[key] is not None:
                    from runtime.startup import _canonical_binding
                    _canonical_binding(post[key])
            if post["target"] is not None:
                from runtime.startup import _canonical_target
                _canonical_target(post["target"])
                d3._require(post["target"]["path"] == str(Path(journal["manifest"]["enrollment"]["record"]["project_root"])/PROJECT_FILE)
                    and post["target"]["binding"] == post["result_binding"] and post["target"]["fingerprint"].get("sha256") == expected_sha,
                    "Canonical observed target differs from its owned result")
            d3._require(post["status"] != "published" or post["target"] is not None, "Published canonical target observation missing")
    return journal


def _scoped_owner_bindings(plan):
    for assessment in d3._assessments(plan["assessments"]):
        owner, identity = assessment["owner"], assessment["identity"]
        root = Path(owner["root"])
        d3._require(d3._filesystem_binding(root) == (plan["identity"]["binding"] if owner["kind"] == "project" else identity["binding"]["root"]), "Selected root physical identity changed")
        if owner["kind"] == "repository":
            current, error = d3._checkout_observation(str(root), {"paths":0,"bytes":0})
            d3._require(error is None and all(current[k] == identity[k] for k in ("root","primary_root","git_dir","git_common_dir","binding")), "Selected Git physical identity changed")


def _scoped_parent_guard(target, journal):
    for name, binding in target["parents"].items():
        d3._require(d3._filesystem_binding(Path(name)) == binding, "Scoped target parent physical identity changed")
    for name, receipt in journal["directories"].items():
        if Path(target["path"]).is_relative_to(Path(name)) and receipt["status"] == "owned":
            d3._require(d3._filesystem_binding(Path(name)) == {k:receipt[k] for k in ("device","inode")}, "Owned parent directory changed")


def _scoped_recovery_files(path, journal):
    for action in journal["manifest"]["actions"]:
        receipt = journal["receipts"].get(action["id"])
        if receipt:
            for effect, file in zip(action["effects"],receipt["files"]):
                _scoped_parent_guard(file["target"],journal)
                if file["backup"]:
                    raw = d3._read_file(path / file["backup"],d3.MAX_FILE,private=True)
                    d3._require(hashlib.sha256(raw).hexdigest() == effect["before"]["sha256"], "Scoped backup integrity failed")
    if journal["enrollment"] and journal["enrollment"]["backup"]:
        raw = d3._read_file(path / journal["enrollment"]["backup"],128*1024,private=True)
        d3._require(hashlib.sha256(raw).hexdigest() == journal["manifest"]["enrollment"]["before"]["raw_sha256"], "Canonical backup integrity failed")


def _scoped_fresh(plan, journal):
    for assessment in d3._assessments(plan["assessments"]):
        owner, identity = assessment["owner"], assessment["identity"]
        root = Path(owner["root"])
        d3._require(d3._filesystem_binding(root) == (plan["identity"]["binding"] if owner["kind"] == "project" else identity["binding"]["root"]), "Selected root physical identity changed")
        owned = {e["path"] for a in journal["manifest"]["actions"] if a["owner"] == owner and a["id"] in journal["receipts"] for e in a["effects"]}
        if root == Path(plan["identity"]["project_root"]) and journal["enrollment"] is not None: owned.add(str(PROJECT_FILE))
        if owner["kind"] == "repository":
            observed, error = d3._checkout_observation(str(root), {"paths": 0, "bytes": 0})
            d3._require(error is None and all(observed[k] == identity[k] for k in ("root", "primary_root", "git_dir", "git_common_dir", "binding")), "Selected Git physical identity changed")
            local_actions = [dict(a, id=d3._qualified(owner, a["id"])) for a in assessment["actions"]]
            local = dict(plan, identity=identity["snapshot"], actions=local_actions, schema_version=1)
            view = dict(journal, manifest=dict(journal["manifest"], actions=[a for a in journal["manifest"]["actions"] if a["owner"] == owner]),
                        enrollment=journal["enrollment"] if str(PROJECT_FILE) in owned else None)
            external_owned=[]
            for action in journal['manifest']['actions']:
                if action['owner']['kind']!='project': continue
                receipt=journal['receipts'].get(action['id'])
                if receipt is None: continue
                shared_root=Path(action['owner']['root'])
                for effect,file in zip(action['effects'],receipt['files']):
                    key='instruction:'+str(shared_root/effect['path'])
                    if key not in identity['snapshot']['fingerprints']: continue
                    if _fingerprint(shared_root,effect['path'])!=effect['after']: continue
                    actual=_scoped_target(shared_root,effect['path'])
                    _scoped_parent_guard(file['target'],journal)
                    owned_target=file['owned_target']
                    binding=file['result_binding'] or file['prepared_binding']
                    d3._require(actual==owned_target if owned_target is not None else
                        binding is not None and actual['binding']==binding,'Shared instruction physical ownership changed')
                    external_owned.append(key)
            _fresh(local, view, external_owned=external_owned)
        else:
            for name, fingerprint in identity["fingerprints"].items():
                if name not in owned: d3._require(d3._fingerprint(root, name) == fingerprint, "Unrelated Project file changed")
    d3._require(plan["package_pins"] == d3._package_pins() and not d3._source_blockers(plan, d3._sources(plan["sources"]["declared"])), "Installed package or Toolkit sources changed")


def _scoped_input_digest(manifest):
    root = Path(manifest["enrollment"]["record"]["project_root"])
    return d3._digest(dict(authority=_scoped_target(root, str(PROJECT_FILE)), package_pins=d3._package_pins(),
        effects=[dict(id=a["id"], files=[_scoped_target(Path(a["owner"]["root"]), e["path"]) for e in a["effects"]]) for a in manifest["actions"]]))


def _scoped_suspended(journal, *, rollback=False):
    _,prior=_scoped_prior(journal["plan"])
    final=journal["manifest"]["enrollment"]["record"]
    record=deepcopy(final if rollback else prior if prior and prior.get("schema_version")==2 else final)
    record["revision"]=final["revision"]+1 if rollback else final["revision"]-1
    affected={tuple(m[k] for k in ("repository_id","checkout_id","client")) for m in journal["manifest"]["enrollment"]["affected"]}
    for key,(_,_,entry) in _scoped_entries(record).items():
        if key in affected and entry["configuration"] is not None and (not rollback or entry["activation"]["status"]=="active"):
            entry["activation"]["status"]="suspended"
    return record


def _scoped_publish(path, journal, phase, record):
    root = Path(journal["manifest"]["enrollment"]["record"]["project_root"])
    receipt = journal["enrollment"]
    raw = json.dumps(record, sort_keys=True, ensure_ascii=True).encode() + b"\n" if record else b""
    mode = 0o600
    if phase == "restore" and receipt["backup"]:
        raw = d3._read_file(path / receipt["backup"],128*1024,private=True)
        d3._require(hashlib.sha256(raw).hexdigest() == receipt["before"]["raw_sha256"] and d3.read_request(raw) == record, "Prior authority raw backup changed")
        mode = next((p["before"]["mode"] for p in receipt["postimages"] if p["before"] is not None),0o600)
    after = dict(sha256=hashlib.sha256(raw).hexdigest(), mode=mode) if record else None
    post = next((p for p in receipt["postimages"] if p["phase"] == phase), None)
    if post is None:
        actual = _scoped_target(root, str(PROJECT_FILE))
        post = dict(phase=phase, revision=record.get("revision") if record else None, raw_sha256=after["sha256"] if after else None,
            target=None, backup=receipt["backup"], temporary=".d4-" + journal["transaction_id"] + "-" + phase,
            status="prepared", before=_fingerprint(root, str(PROJECT_FILE)), after=after,
            before_binding=actual["binding"], prepared_binding=None, result_binding=None)
        receipt["postimages"].append(post); _save(path, journal)
    d3._require(post["after"] == after, "Canonical prepared postimage changed")
    _ensure_parents(path, root, str(PROJECT_FILE), journal)
    _scoped_parent_guard(journal["manifest"]["enrollment"]["before"]["target"], journal)
    _scoped_replace(path, root, str(PROJECT_FILE), raw, post["before"], after, post, journal)
    post["target"] = _scoped_target(root, str(PROJECT_FILE)); post["status"] = "published"
    receipt["status"] = "restored" if phase == "restore" else "active" if phase == "final" else "inactive"
    if phase in ("suspended","rollback_suspended","restore"):
        for member in receipt["members"]:
            member["status"]="restored" if phase=="restore" else "suspended"
            member["blocked"]=None
    _save(path, journal)


def _scoped_owned_authority(journal):
    root = Path(journal["manifest"]["enrollment"]["record"]["project_root"])
    current = _scoped_target(root, str(PROJECT_FILE))
    enrollment = journal["enrollment"]
    if enrollment is None: return current == journal["manifest"]["enrollment"]["before"]["target"]
    for post in reversed(enrollment["postimages"]):
        expected = post["result_binding"] or post["prepared_binding"]
        if _fingerprint(root, str(PROJECT_FILE)) == post["after"] and current["binding"] == expected:
            if post["target"] is None or current == post["target"]: return True
            if (post["phase"] == "restore" and post["status"] == "published" and enrollment["status"] == "restored"
                    and post["after"] is None and post["before"] is not None and post["before_binding"] is not None
                    and post.get("delete_intent") is True and current == enrollment["before"]["target"]):
                # Restoring absence can remove the transaction's own recorded parent directories.
                parents = dict(post["target"]["parents"])
                removed = set(parents) - set(current["parents"])
                if not removed: return False
                for name in removed:
                    if journal["directories"].get(name) != dict(status="removed", **parents[name]): return False
                    del parents[name]
                return dict(post["target"], parents=parents) == current
            return False
    return not any(p["status"] == "published" for p in enrollment["postimages"]) and current == enrollment["before"]["target"]


def _scoped_apply_action(path, journal, action, original, observation, checkout_lock):
    root = Path(action["owner"]["root"])
    if action["recovery"] != "file-preimages" or not action["effects"]:
        raise Pending("Scoped operation lacks complete bounded recoverable effects")
    expected_resources = ["checkout"] if action["owner"]["kind"] == "repository" else ["project"]
    if action["resources"] != expected_resources or original["kind"] == "external":
        raise Pending("Shared/global or external effects require manual serialization")
    receipt = journal["receipts"].get(action["id"])
    for assessment in d3._assessments(journal["plan"]["assessments"]):
        for decision in assessment["decisions"]:
            if decision["disposition"] in ("pending","proposed") and (d3._qualified(assessment["owner"],decision["id"]) in original["decision_ids"] or action["id"] in decision["affected_actions"]):
                raise Pending("An applicable scoped adoption decision remains unresolved")
        if any(action["id"] in row["actions"] and (row["blocker"] or row["outcome"] == "blocked") for row in assessment["coverage"]):
            raise Pending("Scoped adoption coverage remains blocked")
    if receipt is None:
        assessment = next(a for a in d3._assessments(journal["plan"]["assessments"]) if a["owner"] == action["owner"])
        files = []
        for index, effect in enumerate(action["effects"]):
            target = effect["target"] if original["kind"] == "command" else assessment["identity"].get("targets", {}).get(effect["path"])
            d3._require(target is not None and _scoped_target(root, effect["path"]) == target, "Scoped target/parent preimage changed")
            backup = _backup(path, root, effect["path"], effect["before"], "backup-" + str(journal["manifest"]["actions"].index(action)) + "-" + str(index))
            files.append(dict(backup=backup, temporary=".d4-" + journal["transaction_id"] + "-" + str(journal["manifest"]["actions"].index(action)) + "-" + str(index),
                target=target, before_binding=target["binding"], prepared_binding=None, result_binding=None, owned_target=None))
        receipt = dict(owner=action["owner"], status="prepared", files=files, returncode=None)
        journal["receipts"][action["id"]] = receipt; _save(path, journal); _checkpoint("prepared")
    for condition in action["preconditions"]:
        d3._require(_fingerprint(root, condition["path"]) == condition["fingerprint"], "Scoped action precondition changed")
    if original["kind"] == "command":
        if action["owner"]["kind"] != "repository" or not action["execution"]["qualification"]:
            raise Pending("Scoped command lacks qualified Repository-local effects")
        if receipt.get("command") and not receipt["command"]["stopped"]:
            proof = next((p for p in observation.get("command_reconciliation", []) if p["id"] == action["id"] and p["attempt_id"] == receipt["command"]["attempt_id"]), None) if observation else None
            if not proof or proof.get("stopped") is not True or not _evidence(proof.get("evidence"), many=True):
                raise Pending("Scoped command and writable descendants remain uncertain")
            receipt["command"]["stopped"] = True; _save(path, journal)
            marker = _command_owner(action["owner"]["git_dir"])
            if marker is not None:
                d3._require(marker == dict(schema_version=1,plan_dir=str(path),transaction_id=journal["transaction_id"],id=action["id"],attempt_id=receipt["command"]["attempt_id"]), "Command owner does not match the reconciled attempt")
                location=_owner_path(action["owner"]["git_dir"]); os.unlink(location)
                descriptor=d3._open_path(location.parent,os.O_RDONLY|os.O_DIRECTORY)
                try: os.fsync(descriptor)
                finally: os.close(descriptor)
        actual = [_fingerprint(root, e["path"]) for e in action["effects"]]
        if receipt.get("command"):
            if actual == [e["after"] for e in action["effects"]] and receipt["returncode"] == 0:
                receipt["status"] = "completed"
                for effect, file in zip(action["effects"], receipt["files"]):
                    d3._require(file["owned_target"] is not None and _scoped_target(root,effect["path"]) == file["owned_target"], "Command output physical ownership is unverified or changed")
                _save(path, journal); return
            if not action["execution"]["idempotency"] or actual != [e["before"] for e in action["effects"]]:
                raise Pending("Scoped command outcome requires reviewed manual recovery")
        cwd_target=d3._physical_target(root,Path(action["execution"]["cwd"]),None,{"paths":0,"bytes":0},directory=True)
        d3._require(cwd_target == action["execution"]["cwd_target"], "Actual command cwd physical identity changed")
        receipt["command"] = dict(attempt_id=uuid.uuid4().hex, stopped=False); receipt["status"] = "started"; _save(path, journal)
        git_dir = action["owner"]["git_dir"]
        d3._require(_command_owner(git_dir) is None, "Another command owns this checkout")
        marker = dict(schema_version=1, plan_dir=str(path), transaction_id=journal["transaction_id"], id=action["id"], attempt_id=receipt["command"]["attempt_id"])
        location = _owner_path(git_dir); _atomic(location.parent, location.name, json.dumps(marker, sort_keys=True).encode())
        _checkpoint("command_started")
        for effect in action["effects"]:
            d3._require(_fingerprint(root, effect["path"]) == effect["before"] and
                _scoped_target(root, effect["path"]) == effect["target"],
                "Scoped command effect preimage or physical identity changed before launch")
        d3._require(d3._physical_target(root,Path(action["execution"]["cwd"]),None,{"paths":0,"bytes":0},directory=True)
            == action["execution"]["cwd_target"], "Actual command cwd physical identity changed before launch")
        process = subprocess.Popen(action["execution"]["argv"], cwd=action["execution"]["cwd"], env={k:v for k,v in os.environ.items() if not k.startswith("GIT_")},
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, pass_fds=(checkout_lock,))
        try: receipt["returncode"] = process.wait(timeout=action["execution"]["timeout_seconds"])
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(); receipt["returncode"] = process.returncode
        if [_fingerprint(root,e["path"]) for e in action["effects"]] == [e["after"] for e in action["effects"]]:
            for effect,file in zip(action["effects"],receipt["files"]):
                file["owned_target"]=_scoped_target(root,effect["path"]); file["result_binding"]=file["owned_target"]["binding"]
        _save(path, journal); _checkpoint("command_finished")
        raise Pending("Scoped command direct process exited; exact descendant lifecycle proof is required")
    for effect, file in zip(action["effects"], receipt["files"]):
        _scoped_parent_guard(file["target"], journal)
        _ensure_parents(path, root, effect["path"], journal)
        raw = original["text"].encode() if original["kind"] == "write" else b""
        _scoped_replace(path, root, effect["path"], raw, effect["before"], effect["after"], file, journal)
        file["owned_target"] = _scoped_target(root, effect["path"])
    receipt["status"] = "completed"; _save(path, journal); _checkpoint("outcome")


def _scoped_restore(path, journal, current_record, authority_owned, observation):
    m = journal["manifest"]
    originals, _, dependencies = _scoped_originals(journal["plan"])
    failed = set()
    current_entries = _scoped_entries(current_record)
    enrollment=journal["enrollment"]
    affected={tuple(member[k] for k in ("repository_id","checkout_id","client")) for member in m["enrollment"]["affected"]}
    supporting=any(receipt["files"] and receipt["status"] != "rolled_back" for receipt in journal["receipts"].values())
    if authority_owned and enrollment and supporting and (any(p["phase"]=="rollback_suspended" for p in enrollment["postimages"]) or
            any(entry["activation"]["status"]=="active" for key,(_,_,entry) in current_entries.items() if key in affected)):
        _scoped_publish(path,journal,"rollback_suspended",_scoped_suspended(journal,rollback=True))
    if not authority_owned:
        _canonical_record(current_record,journal["plan"],current=False)
    for action in reversed(m["actions"]):
        receipt = journal["receipts"].get(action["id"])
        if receipt is None: continue
        try:
            if any(action["id"] in dependencies[i] for i in failed):
                raise Pending("A dependent member has not recovered safely")
            if not authority_owned:
                owner = action["owner"]
                if owner["kind"] == "project" or any(action["id"] in dependencies[i] for i in originals if originals[i]["owner"] != owner):
                    raise Pending("Newer authority blocks shared/dependent rollback")
                entries = [e for key, (_, _, e) in current_entries.items() if key[:2] == (owner["repository_id"], owner["checkout_id"])]
                if not entries or any(e["activation"]["status"] == "active" for e in entries):
                    raise Pending("Newer authority has not suspended this member")
                changed={str(Path(owner["root"])/effect["path"]) for effect in action["effects"]}
                if any(set(entry["configuration"]["shared_dependencies"]) & changed for key,(_,_,entry) in current_entries.items()
                       if key[:2] != (owner["repository_id"],owner["checkout_id"]) and entry["configuration"] is not None):
                    raise Pending("A newer dependent member requires shared-resource reconciliation")
            if receipt.get("command") and not receipt["command"]["stopped"]:
                raise Pending("Command descendants remain unreconciled")
            root = Path(action["owner"]["root"])
            for effect, file in reversed(list(zip(action["effects"], receipt["files"]))):
                actual = _scoped_target(root, effect["path"])
                restore = file.get("restore")
                if receipt["status"] == "rolled_back":
                    d3._require(_fingerprint(root, effect["path"]) == effect["before"] and actual["binding"] == (restore["result_binding"] if restore else file["before_binding"]), "Restored member changed externally")
                    if restore is None:
                        d3._require(actual == file["target"], "Restored original parent identity changed")
                    continue
                if restore is None and _fingerprint(root, effect["path"]) == effect["before"] and actual == file["target"]:
                    # A prepared receipt may precede any mutation; preserve the exact original inode.
                    continue
                if restore is None and file["owned_target"] is not None and actual != file["owned_target"]:
                    raise Pending("Scoped output physical ownership changed before rollback")
                if restore is None:
                    restore = dict(temporary=file["temporary"] + "-restore", before_binding=file["result_binding"], prepared_binding=None, result_binding=None)
                    file["restore"] = restore; _save(path, journal)
                raw = d3._read_file(path / file["backup"], d3.MAX_FILE, private=True) if file["backup"] else b""
                if effect["before"]:
                    d3._require(hashlib.sha256(raw).hexdigest() == effect["before"]["sha256"], "Scoped recovery backup changed")
                _scoped_replace(path, root, effect["path"], raw, effect["after"], effect["before"], restore, journal)
            receipt["status"] = "rolled_back"; _save(path, journal)
        except (Pending, StartupError) as error:
            failed.add(action["id"]); journal["blocked"].append(dict(id=action["id"], reason=str(error)))
    if journal["enrollment"]:
        for member in journal["enrollment"]["members"]:
            local=[a["id"] for a in m["actions"] if a["owner"]["kind"]=="repository" and (a["owner"]["repository_id"],a["owner"]["checkout_id"]) == (member["repository_id"],member["checkout_id"])]
            if local and all(journal["receipts"].get(i,{}).get("status")=="rolled_back" for i in local):
                member.update(status="restored",blocked="authority_recovery_pending")
            elif any(i in failed for i in local): member.update(status="blocked",blocked="recovery_dependency_or_ownership")
    if not authority_owned:
        journal["blocked"].append(dict(id="enrollment", reason="Canonical record changed after this transaction; preserve it for scoped reconciliation"))
    elif not failed and journal["enrollment"] is not None:
        root = Path(m["enrollment"]["record"]["project_root"])
        backup = journal["enrollment"]["backup"]
        prior = d3.read_request(d3._read_file(path / backup, d3.MAX_FILE, private=True)) if backup else None
        if prior and any(e[2]["activation"]["status"] == "active" for e in _scoped_entries(prior).values()):
            if not observation or not observation["prior_compatibility"]:
                raise Pending("Prior active configuration requires fresh trusted prior compatibility before restoration")
            _scoped_qualification(journal,observation,prior)
        _scoped_publish(path, journal, "restore", prior)
        if prior and any(e[2]["activation"]["status"] == "active" for e in _scoped_entries(prior).values()):
            _scoped_qualification(journal,observation,prior,published=True)
        _restore_directories(path, root, journal)


@contextmanager
def _scoped_failure_guard(path, ownership, operation):
    """Persist only validated owned failures before releasing transaction locks."""
    try:
        yield
    except (StartupError,OSError,ValueError,TypeError,KeyError,sqlite3.Error) as error:
        journal=ownership["journal"]
        if journal is not None:
            journal["state"]="rollback_partial" if operation=="rollback" else "blocked"
            journal["blocked"].append(dict(id="transaction",reason=str(error) if isinstance(error,StartupError) else "Scoped state or recovery material is unavailable"))
            if journal["enrollment"]:
                for member in journal["enrollment"]["members"]:
                    if member["status"] != "restored": member.update(status="blocked",blocked="transaction_incomplete")
            _save(path,journal)
        raise


def _run_scoped(plan_dir, request, operation, *, host=None):
    """Internal scoped transaction seam; public _run retains its schema-2 gate."""
    journal = None
    ownership={"journal":None}
    try:
        request=deepcopy(request)
        d3._require(operation in ("apply", "resume", "rollback"), "Unknown scoped operation")
        path = d3._plan_path(plan_dir)
        with d3._locked(path): plan = d3._load(path)
        d3._require(plan is not None, "Scoped D3 proposal is required")
        originals, dependencies, affected, suspend = _validate_scoped(request, plan)
        m = request["manifest"]; root = Path(m["enrollment"]["record"]["project_root"])
        authority, prior = _scoped_prior(plan)
        locations = _scoped_runtime_locations([prior, m["enrollment"]["record"]], affected)
        affected_roots,affected_git=_scoped_writer_roots(m)
        changed_paths=_scoped_changed_paths(m)
        lock_root = d3._plan_path(LOCK_ROOT)
        destination_keys = {"destination:" + str(root / PROJECT_FILE), "parent:" + str(root) + ":" + d3._digest(plan["identity"]["binding"])}
        if authority["binding"]: destination_keys.add("inode:" + d3._digest(authority["binding"]))
        canonical_location = lock_root / ("canonical-" + hashlib.sha256(("destination:" + str(root / PROJECT_FILE)).encode()).hexdigest() + ".lock")
        operation_owner = dict(schema_version=1,plan_dir=str(path),transaction_id=m["transaction_id"],manifest_digest=d3._digest(m))
        with ExitStack() as locks:
            for key in sorted(destination_keys):
                location = lock_root / ("canonical-" + hashlib.sha256(key.encode()).hexdigest() + ".lock")
                if not location.exists():
                    try:
                        descriptor = os.open(location, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600); os.close(descriptor)
                    except FileExistsError: pass
                locks.enter_context(_lock(location))
            held = _authority_owner(canonical_location)
            if held is not None and held != operation_owner:
                raise Pending("Canonical authority has an interrupted or uncertain operation; resume its exact journal")
            git_dirs = {a["owner"]["git_dir"] for a in m["owners"] if a["owner"]["kind"] == "repository"}
            if plan["identity"]["kind"] == "standalone":
                git_dirs.update(a["owner"]["git_common_dir"] for a in m["owners"] if a["owner"]["kind"] == "repository")
            descriptors = {git_dir: locks.enter_context(_worktree_lock(git_dir)) for git_dir in sorted(git_dirs)}
            owner = dict(schema_version=1, plan_dir=str(path), transaction_id=m["transaction_id"], manifest_digest=d3._digest(m))
            locks.enter_context(_scoped_failure_guard(path,ownership,operation))
            journal = _load_journal(path)
            if journal is not None:
                d3._require(journal["schema_version"] == 2 and journal["manifest"] == m and journal["approval"] == request["approval"] and journal["plan"] == plan, "Scoped journal binding changed")
                ownership["journal"]=journal
            else:
                d3._require(operation == "apply" and _scoped_target(root, str(PROJECT_FILE)) == m["enrollment"]["before"]["target"], "Scoped authority preimage changed or no journal to recover")
                if prior:
                    raw = d3._read_file(root / PROJECT_FILE, 128 * 1024)
                    d3._require(hashlib.sha256(raw).hexdigest() == m["enrollment"]["before"]["raw_sha256"] and d3.read_request(raw) == prior, "Canonical approved bytes changed")
            with _scoped_source_guards(locations, owner, m) as (authority_locations,source_contexts):
                writer_locations=_scoped_writer_locations(locations,source_contexts)
                _scoped_writers(writer_locations, affected_roots, affected_git, changed_paths=changed_paths)
                for git_dir in git_dirs:
                    marker = _command_owner(git_dir)
                    d3._require(marker is None or marker["plan_dir"] == str(path) and marker["transaction_id"] == m["transaction_id"], "Unresolved command owns an affected checkout")
                if journal is None:
                    current, blockers = d3._project_current(plan)
                    d3._require(not d3._project_changes(plan, current), "Scoped D3 inputs changed before journal")
                    for action in m["actions"]:
                        for effect in action["effects"]:
                            d3._require(_fingerprint(Path(action["owner"]["root"]),effect["path"]) == effect["before"], "Scoped approved effect preimage changed")
                            if "target" in effect:
                                selected_root=Path(action["owner"]["root"])
                                d3._require(_scoped_target(selected_root,effect["path"]) == effect["target"], "Approved command target/parent physical identity changed")
                                existing=next(p for p in ((selected_root/effect["path"]).parent,*(selected_root/effect["path"]).parent.parents) if p.is_dir())
                                d3._require(checkout(existing)==(selected_root,Path(action["owner"]["git_common_dir"])), "Command effect enters another checkout")
                    journal = dict(schema_version=2, transaction_id=m["transaction_id"], manifest_digest=d3._digest(m), manifest=deepcopy(m), approval=deepcopy(request["approval"]), plan=deepcopy(plan),
                        state="prepared", receipts={}, enrollment=None, blocked=[], directories={}, observations=[])
                    _save(path, journal)
                    ownership["journal"]=journal
                with _d4_publication_batch(path,journal,source_contexts,request,host,owner,[canonical_location,*authority_locations]):
                    _scoped_register_sources(path,journal,source_contexts)
            def settle_sources():
                d3._require(not any(r.get("command") and not r["command"]["stopped"] for r in journal["receipts"].values()),
                    "Scoped command descendants remain uncertain; preserve recovery markers")
                with _scoped_source_guards(locations, owner, m) as (final_locations,source_contexts):
                    writer_locations=_scoped_writer_locations(locations,source_contexts)
                    _scoped_writers(writer_locations,affected_roots,affected_git,changed_paths=changed_paths)
                    with _d4_publication_batch(path,journal,source_contexts,request,host,owner,[canonical_location,*final_locations]):
                        _scoped_register_sources(path,journal,source_contexts)
                        for location in [canonical_location,*final_locations]:
                            d3._require(_authority_owner(location)==owner,'D4 marker changed before final removal')
                        for location in [canonical_location,*final_locations]:os.unlink(Path(str(location)+".json"))
                        descriptor=d3._open_path(lock_root,os.O_RDONLY|os.O_DIRECTORY)
                        try: os.fsync(descriptor)
                        finally: os.close(descriptor)
            journal["blocked"] = []
            observation = request.get("observations")
            if observation:
                _scoped_observation_shape(observation,m)
                d3._require(observation["manifest_digest"] == journal["manifest_digest"] and observation["input_digest"] == _scoped_input_digest(m), "Scoped observations are stale")
                journal["observations"].append(deepcopy(observation)); _save(path, journal)
            _scoped_owner_bindings(plan)
            _scoped_recovery_files(path, journal)
            if journal["state"] == "rolled_back":
                d3._require(operation == "rollback", "Rolled-back transaction cannot apply again")
                for action in m["actions"]:
                    for effect,file in zip(action["effects"],journal["receipts"].get(action["id"],{}).get("files",[])):
                        expected = file.get("restore",{}).get("result_binding",file["before_binding"])
                        d3._require(_fingerprint(Path(action["owner"]["root"]),effect["path"]) == effect["before"] and _scoped_target(Path(action["owner"]["root"]),effect["path"])["binding"] == expected, "Previously restored effect changed")
                last=journal["enrollment"]["postimages"][-1]
                d3._require(_fingerprint(root,str(PROJECT_FILE)) == last["after"] and (last["after"] is None or _scoped_target(root,str(PROJECT_FILE)) == last["target"]), "Restored authority changed")
                settle_sources()
                return dict(state="rolled_back",exit_code=0,blocked=[],activation_status="configured",qualified=False)
            authority_owned = _scoped_owned_authority(journal)
            current_record = d3.read_request(d3._read_file(root / PROJECT_FILE, 128 * 1024)) if (root / PROJECT_FILE).exists() else None
            current_locations = _scoped_runtime_locations([current_record], affected)
            d3._require(set(current_locations) <= set(locations), "New authority needs separately reconciled state guards")
            _scoped_writers(writer_locations, affected_roots, affected_git, changed_paths=changed_paths)
            if operation == "rollback":
                _scoped_restore(path, journal, current_record, authority_owned, observation)
                journal["state"] = "rollback_partial" if journal["blocked"] else "rolled_back"
            else:
                d3._require(journal["state"] not in ("rolled_back", "rollback_partial"), "Rolled back transaction cannot resume application")
                if not authority_owned: raise Pending("Canonical authority changed outside owned postimages")
                _scoped_fresh(plan, journal)
                if journal["enrollment"] is None:
                    before = _fingerprint(root, str(PROJECT_FILE))
                    backup = _backup(path, root, str(PROJECT_FILE), before, "enrollment.backup")
                    journal["enrollment"] = dict(before=deepcopy(m["enrollment"]["before"]), backup=backup, status="prepared", temporary=".d4-"+m["transaction_id"]+"-enrollment", postimages=[], members=[dict(member,status="pending",blocked=None) for member in deepcopy(m["enrollment"]["affected"])])
                    _save(path, journal)
                if suspend and not any(p["phase"] == "final" for p in journal["enrollment"]["postimages"]):
                    suspended = _scoped_suspended(journal)
                    _scoped_publish(path, journal, "suspended", suspended)
                journal["state"] = "applying"; _save(path, journal)
                completed = set()
                for action in m["actions"]:
                    if action["id"] not in m["approved_scope"] or not dependencies[action["id"]] <= completed:
                        journal["blocked"].append(dict(id=action["id"], reason="Scoped action approval/dependency missing")); continue
                    try:
                        if originals[action["id"]]["target"] != str(PROJECT_FILE):
                            _scoped_writers(writer_locations, affected_roots, affected_git, changed_paths=changed_paths)
                            _scoped_apply_action(path, journal, action, originals[action["id"]], observation, descriptors.get(action["owner"].get("git_dir")))
                        completed.add(action["id"])
                    except Pending as error:
                        journal["blocked"].append(dict(id=action["id"], reason=str(error)))
                if not set(m["enrollment"]["requires"]) <= completed:
                    raise Pending("Required scoped adoption effects are incomplete")
                activates = any(e[2]["activation"]["status"] == "active" for key, e in _scoped_entries(m["enrollment"]["record"]).items() if key in affected)
                if activates: _scoped_qualification(journal,observation,m["enrollment"]["record"])
                _scoped_writers(writer_locations, affected_roots, affected_git, changed_paths=changed_paths)
                if not _scoped_owned_authority(journal): raise Pending("Canonical preimage ownership changed before publication")
                _scoped_publish(path, journal, "final", m["enrollment"]["record"])
                if activates: _scoped_qualification(journal,observation,m["enrollment"]["record"],published=True)
                entries=_scoped_entries(m["enrollment"]["record"])
                for member in journal["enrollment"]["members"]:
                    member["status"]=entries[tuple(member[k] for k in ("repository_id","checkout_id","client"))][2]["activation"]["status"]
                    member["blocked"]=None
                journal["state"] = "blocked" if journal["blocked"] else "applied"
            _save(path, journal)
            unsettled = any(r.get("command") and not r["command"]["stopped"] for r in journal["receipts"].values())
            if not unsettled:settle_sources()
            return dict(transaction_id=journal["transaction_id"],state=journal["state"],exit_code=0 if journal["state"] in ("applied","rolled_back") else 2,
                        blocked=deepcopy(journal["blocked"]),members=deepcopy(journal["enrollment"]["members"]),
                        activation_status="active" if operation != "rollback" and journal["enrollment"]["members"] and all(m["status"]=="active" for m in journal["enrollment"]["members"]) else "configured",
                        qualified=operation != "rollback" and bool(journal["enrollment"]["members"]) and all(m["status"]=="active" for m in journal["enrollment"]["members"]) and journal["state"] == "applied")
    except (StartupError, OSError, ValueError, TypeError, KeyError, sqlite3.Error) as error:
        owned=ownership["journal"]
        reason=str(error) if isinstance(error,StartupError) else "Scoped input or state is unavailable"
        return dict(state=owned["state"] if owned else "blocked",exit_code=2,
                    blocked=deepcopy(owned["blocked"]) if owned else [dict(id="transaction",reason=reason)],
                    activation_status="configured",qualified=False)


def _scoped_qualification(journal, observation, record, *, published=False):
    from runtime.startup import decode_project_record, preview_canonical_scope, resolve_canonical_scope
    if not observation or observation["input_digest"] != _scoped_input_digest(journal["manifest"]) and not published:
        raise Pending("Fresh scoped adoption qualification observations are required")
    qualified = []
    for key, (_, _, entry) in _scoped_entries(record).items():
        if entry["activation"]["status"] != "active": continue
        if key not in {tuple(m[k] for k in ("repository_id","checkout_id","client")) for m in journal["manifest"]["enrollment"]["affected"]}: continue
        proof = next((p for p in observation["qualification"] if tuple(p[k] for k in ("repository_id","checkout_id","client")) == key), None)
        if proof is None: raise Pending("Member/client qualification is missing")
        d3._object(proof, ("repository_id","checkout_id","client","requirements","general_review","security_review","scope_observations"))
        rule = next(r for r in journal["manifest"]["enrollment"]["qualification"] if tuple(r[k] for k in ("repository_id","checkout_id","client")) == key)
        seen = set()
        for row in proof["requirements"]:
            d3._object(row,("id","evidence")); d3._require(row["id"] not in seen and row["id"] in rule["requirements"], "Unknown or duplicate qualification requirement")
            seen.add(row["id"]); d3._require(_evidence(row["evidence"],many=True), "Empty mandatory qualification evidence")
        if not set(rule["requirements"]) <= seen or not _evidence(proof["general_review"],many=True) or rule["security_required"] and not _evidence(proof["security_review"],many=True):
            raise Pending("Mandatory general/security/member qualification is incomplete")
        assessment = next(a for a in journal["plan"]["assessments"]["repositories"] if (a["owner"]["repository_id"],a["owner"]["checkout_id"]) == key[:2])
        d3._require(all(assessment["semantic_assessment"].get(k) for k in ("complete","catalog_complete","conflicts_checked","instructions_checked","source_provenance_checked")), "Complete member semantic adoption assessment is required")
        if any(d["disposition"] in ("pending","proposed") for d in assessment["decisions"]):
            raise Pending("Unresolved member adoption decisions prevent activation")
        facts = deepcopy(proof["scope_observations"])
        d3._object(facts,("authority","observation","client","installed"))
        d3._require(facts["client"] == key[2], "Qualification selected another client")
        root = Path(record["project_root"])
        actual = _scoped_target(root,str(PROJECT_FILE))
        if published:
            raw = d3._read_file(root / PROJECT_FILE,128*1024)
            d3._require(d3.read_request(raw) == record and hashlib.sha256(raw).hexdigest() == actual["fingerprint"].get("sha256"), "Published authority reread differs from intended bytes")
            facts["authority"] = dict(path=str(root / PROJECT_FILE),target=actual)
            result = resolve_canonical_scope(decode_project_record(d3.read_request(raw)),**facts)
            if result.status != "active": raise Pending("Published authority failed current qualification: " + result.reason)
            qualified.append(result.scope)
        else:
            d3._require(facts["authority"] == dict(path=str(root / PROJECT_FILE),target=actual), "Preview authority preimage provenance changed")
            result = preview_canonical_scope(decode_project_record(record),**facts)
            if not result.eligible: raise Pending("Proposed authority is not eligible: " + result.reason)
    return qualified


def _scoped_observation_shape(observation, manifest):
    d3._object(observation,("manifest_digest","input_digest","qualification","task_reconciliation","prior_compatibility","command_reconciliation"))
    d3._require(observation["manifest_digest"] == d3._digest(manifest),"Scoped observation belongs to another manifest")
    d3._hash(observation["input_digest"])
    for key in ("qualification","task_reconciliation","prior_compatibility","command_reconciliation"):
        d3._require(isinstance(observation[key],list) and len(observation[key]) <= d3.MAX_PATHS,"Invalid bounded scoped observation rows")
    commands={a["id"] for a in manifest["actions"] if a["execution"] is not None}
    seen=set()
    for proof in observation["command_reconciliation"]:
        d3._object(proof,("id","attempt_id","stopped","evidence"))
        d3._require(proof["id"] in commands and proof["id"] not in seen and isinstance(proof["attempt_id"],str)
            and re.fullmatch(r"[0-9a-f]{32}",proof["attempt_id"]) and proof["stopped"] is True
            and _evidence(proof["evidence"],many=True),"Invalid exact command lifecycle proof")
        seen.add(proof["id"])
    members={tuple(row[k] for k in ("repository_id","checkout_id","client")) for row in manifest["enrollment"]["affected"]}
    for collection in ("qualification","task_reconciliation","prior_compatibility"):
        seen=set()
        for proof in observation[collection]:
            fields=("repository_id","checkout_id","client","requirements","general_review","security_review","scope_observations") if collection=="qualification" else ("repository_id","checkout_id","client","state_dir","evidence")
            d3._object(proof,fields)
            key=tuple(proof[k] for k in ("repository_id","checkout_id","client"))
            identity=(key,proof.get("state_dir"))
            d3._require(key in members and identity not in seen,"Unknown or duplicate scoped proof owner")
            seen.add(identity)
            if collection != "qualification":
                if proof["state_dir"] is not None:
                    from runtime.startup import _canonical_path
                    _canonical_path(proof["state_dir"])
                d3._require(_evidence(proof["evidence"],many=True),"Missing scoped authority reconciliation evidence")
