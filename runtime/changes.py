"""Bounded D4 transactions; trusted coordinators verify approval and effect claims.

A manifest declares an approved effect contract. It is not a command sandbox or
an authentication mechanism. Receipts prove local file observations only.
"""

from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import uuid

from runtime import onboarding as d3
from runtime import state as task_state
from runtime.startup import (PROJECT_FILE, ProjectScope, StartupError, checkout,
                             policy_digest, runtime_settings)

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
    runtime = runtime_settings(record, d3.PACKAGE, Path(record["git_common_dir"]))
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


def _atomic(directory, name, raw, mode=0o600, target=False, guard=None, temporary=None):
    """Replace one bounded regular file and durably publish its directory entry."""
    d3._require(len(raw) <= MAX_JOURNAL, "D4 artifact size limit exceeded")
    fd = d3._open_path(directory, os.O_RDONLY | os.O_DIRECTORY)
    temporary = temporary or ".d4-" + uuid.uuid4().hex
    created = False
    try:
        output = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=fd)
        created = True
        with os.fdopen(output, "wb") as stream:
            stream.write(raw)
            if target:
                _checkpoint("temp_write")
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
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
        os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
        if target:
            _checkpoint("rename")
        os.fsync(fd)
        if target:
            _checkpoint("parent_fsync")
    finally:
        if created:
            try:
                os.unlink(temporary, dir_fd=fd)
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


def _fresh(plan, journal=None):
    """Normalize only receipt-owned paths; unrelated inputs retain D3 freshness checks."""
    root = Path(plan["identity"]["repository_root"])
    current = d3._snapshot(root, d3._file_targets(plan["actions"]))
    previous = plan["identity"]
    owned = _owned(journal) if journal else {}
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


def _writers(plan, prior, observation):
    scope = _record(prior, plan, current=False)
    if scope.runtime is None:
        return
    if not observation or not observation["task_reconciliation"]:
        raise Pending("Confirm stopped writers and reconcile their task/evidence records")
    active = False
    with task_state._database(scope) as db:
        if db is None:
            return
        rows = db.execute("select t.scope_id,t.client,t.session_id,t.task_id from tasks t join checkouts c on t.scope_id=c.scope_id where c.repository_root=? and c.git_common_dir=?",
                          (str(scope.repository_root), str(scope.git_common_dir))).fetchall()
        for scope_id, client, session, task_id in rows:
            task = task_state._task(db, scope_id, client, session, task_id)
            active |= task["mode"] == "editable" and task["state"] != "cancelled"
    if active:
        raise Pending("Affected task writers remain active or unreconciled; stop and reconcile them first")


def _guard_writers(path, root, journal, observation):
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
    seen = set()
    for record in records:
        runtime = record.get("runtime")
        key = d3._digest(runtime)
        if key not in seen:
            _writers(journal["plan"], record, observation)
            seen.add(key)


def _ensure_parents(path, root, relative, journal):
    parts = Path(relative).parent.parts
    for number in range(1, len(parts) + 1):
        name = str(Path(*parts[:number]))
        location = root / name
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
