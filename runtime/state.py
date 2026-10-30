"""Private, bounded SQLite task controls and atomic deterministic hook decisions."""

from contextlib import ExitStack, closing, contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import stat
import time
from types import MappingProxyType

from runtime.engine import HookResult, evaluate, guarded_mutation
from runtime.startup import (StartupError, AcceptedScope, RuntimeSettings, PROJECT_FILE, json_object, _canonical_plain, _canonical_freeze,
    _canonical_path, _canonical_binding, _canonical_ref, _canonical_hash, _budgeted_source_read)


SCHEMA_VERSION = 2
APPLICATION_ID = 0x56494245
PACKAGE = Path(__file__).resolve().parents[1]
LIMITATIONS = ["Supported Codex apply_patch and Claude Code Edit/Write/NotebookEdit guards only; shell and external edits remain possible",
               "Hooks alone do not establish client execution, filesystem locality or current completion evidence"]
STATES = {"planned", "active", "awaiting_user", "blocked", "verifying", "ready", "cancelled"}
TABLE_SQL = {
    "checkouts": """CREATE TABLE checkouts(scope_id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
        repository_root TEXT NOT NULL, git_common_dir TEXT NOT NULL, generation INTEGER NOT NULL)""",
    "tasks": """CREATE TABLE tasks(scope_id TEXT, client TEXT, session_id TEXT, task_id TEXT, data TEXT NOT NULL,
        PRIMARY KEY(scope_id,client,session_id,task_id))""",
    "bindings": """CREATE TABLE bindings(scope_id TEXT, client TEXT, session_id TEXT, task_id TEXT NOT NULL,
        PRIMARY KEY(scope_id,client,session_id))""",
    "turns": """CREATE TABLE turns(scope_id TEXT, client TEXT, session_id TEXT, turn_id TEXT, task_id TEXT,
        continuation_consumed INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(scope_id,client,session_id,turn_id))""",
    "receipts": """CREATE TABLE receipts(scope_id TEXT, client TEXT, session_id TEXT, turn_id TEXT, tool_call_id TEXT,
        kind TEXT, fingerprint TEXT NOT NULL, conflicted INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(scope_id,client,session_id,turn_id,tool_call_id,kind))""",
    "assignments": """CREATE TABLE assignments(id TEXT PRIMARY KEY, scope_id TEXT NOT NULL, client TEXT NOT NULL,
        session_id TEXT NOT NULL, task_id TEXT NOT NULL, dispatch_id TEXT NOT NULL, data TEXT NOT NULL,
        UNIQUE(scope_id,client,session_id,task_id,dispatch_id))""",
}
CANONICAL_SCHEMA_VERSION = 3
CANONICAL_TABLE_SQL = TABLE_SQL | {
    "checkouts": TABLE_SQL["checkouts"][:-1] + ", physical_identity TEXT NOT NULL)",
    "evidence_metadata": """CREATE TABLE evidence_metadata(name TEXT PRIMARY KEY, digest TEXT NOT NULL,
        owner_key TEXT NOT NULL, class TEXT NOT NULL, created_at INTEGER NOT NULL, closed_at INTEGER,
        status TEXT NOT NULL, bytes INTEGER NOT NULL, data TEXT NOT NULL)""",
    "retired_identities": """CREATE TABLE retired_identities(kind TEXT NOT NULL, identity_digest TEXT NOT NULL,
        data TEXT NOT NULL, assignment_id TEXT, PRIMARY KEY(kind,identity_digest))""",
}
CANONICAL_INDEX_SQL = {
    "evidence_lifecycle": "CREATE INDEX evidence_lifecycle ON evidence_metadata(owner_key,class,status,closed_at,created_at,name)",
    "assignment_owner": "CREATE INDEX assignment_owner ON assignments(scope_id,client,session_id,task_id)",
    "retired_assignment_id": "CREATE UNIQUE INDEX retired_assignment_id ON retired_identities(assignment_id) WHERE kind='assignment'",
}
TABLES = set(TABLE_SQL)


class StateError(StartupError):
    """Sanitized task/state diagnostic, without private record contents."""


def _runtime_sources():
    return sorted([*(PACKAGE / "runtime").glob("*.py"), *(PACKAGE / "runtime/adapters").glob("*.py"), PACKAGE / "scripts/workflow.py"])


def runtime_fingerprint(*, budget=None):
    """Pin installed runtime sources, dispatcher and adapter contents, by relative path."""
    digest = hashlib.sha256()
    for path in _runtime_sources():
        digest.update(str(path.relative_to(PACKAGE)).encode() + b"\0" + _budgeted_source_read(path, budget) + b"\0")
    return digest.hexdigest()


def _validate_pins(pins, *, version=None):
    _fields(pins, ("schema_version", "policy_digest", "runtime_digest"), ("accepted_scope_digest",))
    actual = pins["schema_version"]
    if type(actual) is not int or actual not in (1, 2, 3) or version is not None and actual != version:
        raise StateError("Unsupported stored task pin schema")
    _fields(pins, ("schema_version", "policy_digest", "runtime_digest", "accepted_scope_digest") if actual == 3
            else ("schema_version", "policy_digest", "runtime_digest"))
    for key in ("policy_digest", "runtime_digest"):
        _text(pins[key], "stored " + key)
    if actual == 3:
        for key in ("policy_digest", "runtime_digest", "accepted_scope_digest"):
            if not isinstance(pins[key], str) or not re.fullmatch(r"[0-9a-f]{64}", pins[key]):
                raise StateError("Invalid canonical task pins")
    return actual


def _accepted_identity(value):
    try:
        identity = json_object(json.dumps(_canonical_plain(value), ensure_ascii=True))
        _fields(identity, ("version", "project_id", "repository_id", "checkout_id", "project_root", "project_binding",
            "primary_root", "repository_root", "git_dir", "git_common_dir", "bindings", "client", "membership", "configuration", "shared_policy"))
        if type(identity["version"]) is not int or identity["version"] != 1:
            raise StateError("Unsupported accepted identity")
        for key in ("project_id", "repository_id", "checkout_id", "client"):
            _text(identity[key], key, 128)
        if (not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", identity["project_id"])
                or identity["repository_id"] == identity["checkout_id"]):
            raise StateError("Invalid canonical identities")
        for key in ("project_root", "primary_root", "repository_root", "git_dir", "git_common_dir"):
            _canonical_path(identity[key])
        _canonical_binding(identity["project_binding"])
        _fields(identity["bindings"], ("root", "primary_root", "git_dir", "git_common_dir"))
        locations = {identity["project_root"]: identity["project_binding"]}
        for key, binding in identity["bindings"].items():
            _canonical_binding(binding)
            path = identity["repository_root" if key == "root" else key]
            if path in locations and locations[path] != binding:
                raise StateError("Canonical directory bindings disagree")
            locations[path] = binding
        _fields(identity["membership"], ("included", "authorization"))
        if identity["membership"]["included"] is not True:
            raise StateError("Canonical task requires accepted membership")
        _canonical_ref(identity["membership"]["authorization"])
        config = identity["configuration"]
        _fields(config, ("policy_digest", "runtime_digest", "runtime"))
        for key in ("policy_digest", "runtime_digest"):
            _canonical_hash(config[key])
        _fields(config["runtime"], ("schema_version", "state_dir"))
        if type(config["runtime"]["schema_version"]) is not int or config["runtime"]["schema_version"] != 3:
            raise StateError("Canonical task requires schema 3")
        _canonical_path(config["runtime"]["state_dir"])
        shared = identity["shared_policy"]
        if not isinstance(shared, list) or len(shared) > 4096:
            raise StateError("Invalid accepted dependencies")
        for item in shared:
            _fields(item, ("path", "sha256"))
            _canonical_path(item["path"]); _canonical_hash(item["sha256"])
        paths = [item["path"] for item in shared]
        if paths != sorted(set(paths)):
            raise StateError("Accepted dependency paths must be unique and sorted")
        return identity
    except (StartupError, ValueError, TypeError, KeyError, RecursionError):
        raise StateError("Canonical accepted identity is invalid") from None


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def _physical_identity(identity):
    return {key: identity[key] for key in ("version", "project_id", "repository_id", "checkout_id", "project_root",
        "project_binding", "primary_root", "repository_root", "git_dir", "git_common_dir", "bindings")}



def _frozen_snapshot(value):
    if isinstance(value, MappingProxyType):
        return all(isinstance(key, str) and _frozen_snapshot(item) for key, item in value.items())
    if isinstance(value, tuple):
        return all(_frozen_snapshot(item) for item in value)
    return value is None or isinstance(value, (str, int, bool))



def _owner_time():
    try:
        value = int(time.time())
        _integer(value, "owner creation time")
        return value
    except (ValueError, OverflowError):
        raise StateError("Owner creation time is unavailable") from None


def _artifact_reference(value):
    _fields(value, ("name", "digest"))
    if not isinstance(value["name"], str) or not re.fullmatch(r"[0-9a-f]{32}\.json", value["name"]):
        raise StateError("Invalid retained artifact reference")
    _canonical_hash(value["digest"])


def _task_lifecycle(task):
    """Validate stored dates only; absence/closure never establishes safe cleanup."""
    if "lifecycle" not in task:
        return None
    value = task["lifecycle"]
    _fields(value, ("created_at", "safe_closed_at", "closure", "compact"))
    _integer(value["created_at"], "original task creation time")
    if value["compact"] is not None:
        _artifact_reference(value["compact"])
    if value["safe_closed_at"] is None:
        if value["closure"] is not None:
            raise StateError("Closure has no owner-proved closure time")
    else:
        _integer(value["safe_closed_at"], "safe closure time", value["created_at"])
        closure = value["closure"]
        _fields(closure, ("version", "task_revision", "dependency_digest", "observed_at", "evidence"))
        if type(closure["version"]) is not int or closure["version"] != 1:
            raise StateError("Unsupported stored closure receipt")
        _integer(closure["task_revision"], "closure task revision", 1)
        _integer(closure["observed_at"], "closure observation time", value["created_at"])
        _canonical_hash(closure["dependency_digest"])
        if not isinstance(closure["evidence"], list) or len(closure["evidence"]) > 4096:
            raise StateError("Invalid closure evidence references")
        for reference in closure["evidence"]:
            _artifact_reference(reference)
    return value


def _retired_identity(kind, identity):
    fields = {
        "task": ("scope_id", "client", "session_id", "task_id"),
        "assignment": ("scope_id", "client", "session_id", "task_id", "dispatch_id"),
        "turn": ("scope_id", "client", "session_id", "turn_id"),
        "receipt": ("scope_id", "client", "session_id", "turn_id", "tool_call_id", "kind"),
    }
    if kind not in fields:
        raise StateError("Unsupported retired identity kind")
    _fields(identity, fields[kind])
    _canonical_hash(identity["scope_id"])
    for field, value in identity.items():
        _text(value, "retired " + field, 128 if field == "task_id" else 4096)
    return _digest(identity)


def _retired_record(kind, digest, raw, assignment_id):
    try:
        value = json_object(raw)
        _fields(value, ("version", "identity", "pins_digest", "request_digest", "created_at", "retired_at", "outcome", "evidence_expired",
                        *(["assignment_id"] if kind == "assignment" else [])))
        if (type(value["version"]) is not int or value["version"] != 1
                or _retired_identity(kind, value["identity"]) != digest
                or value["outcome"] not in ("completed", "failed", "cancelled", "unknown", "ready", "verifying") or kind=="assignment" and value["outcome"] in {"ready","verifying"}
                or type(value["evidence_expired"]) is not bool
                or value["evidence_expired"] and value["outcome"] != "unknown"):
            raise StateError("Retired identity marker is corrupt")
        if kind == "assignment":
            if (not isinstance(assignment_id, str) or not re.fullmatch(r"[0-9a-f]{32}", assignment_id)
                    or value["assignment_id"] != assignment_id):
                raise StateError("Retired native assignment identity differs from its scalar")
        elif assignment_id is not None:
            raise StateError("Only assignment markers may have a native assignment ID")
        for field in ("pins_digest", "request_digest"):
            if value[field] is not None:
                _canonical_hash(value[field])
        if (kind in ("task", "assignment") and value["pins_digest"] is None
                or kind in ("assignment", "receipt") and value["request_digest"] is None):
            raise StateError("Retired identity is missing replay digests")
        _integer(value["created_at"], "original marker creation time")
        _integer(value["retired_at"], "marker retirement time", value["created_at"])
        return value
    except (StartupError, ValueError, TypeError, KeyError, RecursionError):
        raise StateError("Retired identity marker is corrupt or incompatible") from None


def _retired(db, kind, identity):
    """Point replay lookup for exact owner-written retirement markers."""
    version = db.execute("pragma user_version").fetchone()[0]
    if version in (1, 2):
        return None
    if version != 3:
        raise StateError("Unsupported marker authority")
    digest = _retired_identity(kind, identity)
    row = db.execute("select data,assignment_id from retired_identities where kind=? and identity_digest=?", (kind, digest)).fetchone()
    if row is None:
        return None
    value = _retired_record(kind, digest, *row)
    if value["identity"] != identity:
        raise StateError("Retired identity differs from its lookup key")
    return value


def _retired_assignment(db, assignment_id):
    """Resolve the original native ID through its scalar index, never lifetime scans."""
    version = db.execute("pragma user_version").fetchone()[0]
    if version in (1, 2):
        return None
    if version != 3 or not isinstance(assignment_id, str) or not re.fullmatch(r"[0-9a-f]{32}", assignment_id):
        raise StateError("Unsupported retired native assignment lookup")
    row = db.execute("select identity_digest,data,assignment_id from retired_identities "
                     "where kind='assignment' and assignment_id=?", (assignment_id,)).fetchone()
    return _retired_record("assignment", *row) if row else None


def _metadata(db, name):
    """Read stored shape/accounting columns; no file or dependency trust is implied."""
    if db.execute("pragma user_version").fetchone()[0] != 3:
        return None
    _text(name, "metadata name", 4096)
    row = db.execute("select name,digest,owner_key,class,created_at,closed_at,status,bytes,data "
                     "from evidence_metadata where name=?", (name,)).fetchone()
    if row is None:
        return None
    try:
        return _metadata_record(row)
    except (StartupError, ValueError, TypeError, KeyError, RecursionError):
        raise StateError("Evidence metadata is corrupt or incompatible; content remains protected") from None


def _metadata_record(row):
    name = row[0]
    value = json_object(row[8])
    _fields(value, ("version", "owner", "created_at", "class", "bytes", "status", "closed_at",
                    "dependencies", "targets", "export", "managed"), ("screening", "screening_result"))
    if type(value["version"]) is not int or value["version"] not in (1, 2):
        raise StateError("Unsupported evidence metadata")
    owner = value["owner"]
    if not isinstance(owner, dict):
        raise StateError("Invalid evidence metadata owner")
    if owner.get("kind") == "temporary":
        _fields(owner, ("kind", "id", "created_at"))
        if not isinstance(owner["id"], str) or not re.fullmatch(r"[0-9a-f]{32}", owner["id"]):
            raise StateError("Invalid temporary evidence owner")
        _integer(owner["created_at"], "original owner creation time")
        owner_key = "temporary:" + owner["id"]
    else:
        _fields(owner, ("kind", "project_id", "task"))
        if owner["kind"] != "project" or not isinstance(owner["project_id"], str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", owner["project_id"]):
            raise StateError("Invalid Project evidence owner")
        owner_key = "project:" + owner["project_id"]
        if owner["task"] is not None:
            _task_reference(owner["task"])
    _integer(value["created_at"], "artifact original creation time")
    _integer(value["bytes"], "observed artifact bytes")
    if value["closed_at"] is not None:
        _integer(value["closed_at"], "first artifact closure time", value["created_at"])
    if value["class"] not in ("detail", "compact") or value["status"] not in ("live", "delete_pending", "expired"):
        raise StateError("Invalid evidence metadata class/status")
    if row[:8] != (name, row[1], owner_key, value["class"], value["created_at"], value["closed_at"], value["status"], value["bytes"]):
        raise StateError("Evidence metadata columns disagree with stored values")
    _canonical_hash(row[1])
    managed = value["managed"]
    _fields(managed, ("path", "binding", "parents", "sha256", "mode", "bytes"))
    path = _canonical_path(managed["path"])
    _canonical_binding(managed["binding"])
    _metadata_parents(path, managed["parents"])
    if str(path.parent) not in managed["parents"]:
        raise StateError("Managed content lacks its parent binding")
    _integer(managed["mode"], "observed managed mode")
    _integer(managed["bytes"], "observed managed bytes")
    if managed["mode"] > 0o777 or managed["sha256"] != row[1] or managed["bytes"] != value["bytes"]:
        raise StateError("Managed content metadata disagrees with observed columns")
    if value["export"] is not None:
        _fields(value["export"], ("kind",))
        if value["export"]["kind"] != "managed-copy":
            raise StateError("Unsupported managed export")
    elif path.name != name or not re.fullmatch(r"[0-9a-f]{32}\.json", name):
        raise StateError("Artifact name differs from its managed content")
    for field in ("dependencies", "targets"):
        if not isinstance(value[field], list) or len(value[field]) > 4096:
            raise StateError("Invalid bounded evidence metadata references")
    # Actual owner-specific dependencies and physical trust are composed by the later evidence owner.
    for dependency in value["dependencies"]:
        _fields(dependency, ("kind", "reference"))
        if dependency["kind"] not in ("task", "artifact", "assignment", "recovery", "delivery") or not isinstance(dependency["reference"], dict) or not dependency["reference"]:
            raise StateError("Invalid typed evidence dependency")
    for target in value["targets"]:
        _fields(target, ("path", "binding", "parents", "git"))
        target_path = _canonical_path(target["path"])
        _canonical_binding(target["binding"])
        _metadata_parents(target_path, target["parents"])
        if target["git"] is not None:
            git = target["git"]
            _fields(git, ("root", "primary_root", "git_dir", "git_common_dir", "binding"))
            _fields(git["binding"], ("root", "primary_root", "git_dir", "git_common_dir"))
            for field in git["binding"]:
                _canonical_path(git[field]); _canonical_binding(git["binding"][field])
    if "screening" in value:
        _screening_record(value["screening"])
        if (owner["kind"] != "temporary" or value["class"] != "compact"
                or value["status"] != "live" or value["closed_at"] is not None
                or not value["targets"] or value["dependencies"] or value["export"] is not None
                or value["created_at"] != owner["created_at"]):
            raise StateError("Screening accounting requires its live temporary owner anchor")
    if "screening_result" in value:
        pointer = _screening_result(value["screening_result"])
        if ("screening" not in value or value["screening"]["revision"] != 2
                or value["screening"]["last_receipt"]["ticket"] != pointer["ticket"]):
            raise StateError("Screening result requires its exact terminal receipt")
    return value


def _screening_result(value):
    _fields(value, ("version", "ticket", "plan_directory", "directory_binding", "plan_id", "projection_digest"))
    if type(value["version"]) is not int or value["version"] != 1:
        raise StateError("Unsupported screening result")
    _screening_ticket(value["ticket"])
    path = _canonical_path(value["plan_directory"])
    binding = value["directory_binding"]
    _fields(binding, ("directory", "parents"))
    _canonical_binding(binding["directory"])
    _metadata_parents(path, binding["parents"])
    if set(binding["parents"]) != {str(p) for p in path.parents}:
        raise StateError("Incomplete screening plan parent bindings")
    if not isinstance(value["plan_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", value["plan_id"]):
        raise StateError("Invalid screening plan identity")
    _canonical_hash(value["projection_digest"])
    return value


def _screening_ticket(value):
    _fields(value, ("sequence", "nonce", "ceiling_ms"))
    if (type(value["sequence"]) is not int or value["sequence"] != 1
            or type(value["ceiling_ms"]) is not int or value["ceiling_ms"] != 300000
            or not isinstance(value["nonce"], str) or not re.fullmatch(r"[0-9a-f]{32}", value["nonce"])):
        raise StateError("Invalid screening ticket")
    return value


def _screening_record(value):
    _fields(value, ("version", "birth", "limit_ms", "revision", "charged_ms", "settled_sequence",
                    "reservation", "last_receipt"))
    for name in ("version", "limit_ms", "revision", "charged_ms", "settled_sequence"):
        _integer(value[name], "screening " + name)
    if (value["version"] != 1 or value["birth"] != "temporary-owner-publication"
            or value["limit_ms"] != 300000):
        raise StateError("Unsupported screening accounting")
    reservation, receipt = value["reservation"], value["last_receipt"]
    if reservation is not None:
        _screening_ticket(reservation)
    if receipt is not None:
        _fields(receipt, ("ticket", "disposition"))
        _screening_ticket(receipt["ticket"])
        if receipt["disposition"] != "charged-full":
            raise StateError("Unsupported screening disposition")
    shape = (value["revision"], value["charged_ms"], value["settled_sequence"],
             reservation is not None, receipt is not None)
    if shape not in ((0, 0, 0, False, False), (1, 0, 0, True, False), (2, 300000, 1, False, True)):
        raise StateError("Inconsistent screening accounting")
    return value


def _metadata_parents(path, parents):
    if not isinstance(parents, dict) or not parents or len(parents) > 4096:
        raise StateError("Invalid metadata parent observations")
    for name, binding in parents.items():
        parent = _canonical_path(name)
        if parent == path or not path.is_relative_to(parent):
            raise StateError("Metadata parent escapes its target")
        _canonical_binding(binding)


def _task_reference(value):
    _fields(value, ("authority", "scope_id", "client", "session_id", "task_id"))
    _retired_identity("task", {k: value[k] for k in ("scope_id", "client", "session_id", "task_id")})
    authority = value["authority"]
    _fields(authority, ("directory", "database", "directory_binding", "database_binding"))
    directory, database = (_canonical_path(authority[k]) for k in ("directory", "database"))
    if database != directory / "runtime.sqlite3":
        raise StateError("Task reference database differs from its authority")
    _canonical_binding(authority["directory_binding"]); _canonical_binding(authority["database_binding"])


def _lifecycle_identity(db, kind, reference):
    """Read bounded original identity/age from one exact existing schema-3 authority."""
    from runtime import delegation, evidence
    if db is None or not db.in_transaction:
        raise StateError("Lifecycle identity requires its existing authority transaction")
    if kind == "task":
        _task_reference(reference)
        identity = {key: reference[key] for key in ("scope_id", "client", "session_id", "task_id")}
    elif kind == "assignment":
        _fields(reference, ("authority", "id", "owner", "assignment"))
        if not isinstance(reference["id"], str) or not re.fullmatch(r"[0-9a-f]{32}", reference["id"]):
            raise StateError("Invalid lifecycle assignment ID")
        _retired_identity("assignment", reference["owner"])
        _artifact_reference(reference["assignment"])
        identity = dict(id=reference["id"], owner=reference["owner"])
    else:
        raise StateError("Unsupported lifecycle identity kind")

    context = evidence._existing_authority_context(reference["authority"], db=db)
    authority = _canonical_plain(context.authority_set[0])
    if reference["authority"] != authority:
        raise StateError("Lifecycle identity authority is not canonical")
    _schema(db, version=CANONICAL_SCHEMA_VERSION)

    if kind == "task":
        marker = _retired(db, "task", identity)
        row = db.execute("select 1 from tasks where scope_id=? and client=? and session_id=? and task_id=?",
                         tuple(identity[key] for key in ("scope_id", "client", "session_id", "task_id"))).fetchone()
        if row is None:
            if marker is None:
                raise StateError("Lifecycle task identity or original age is unavailable")
            return _canonical_freeze(dict(status="expired" if marker["evidence_expired"] else "retired",
                identity=identity, pins_digest=marker["pins_digest"], request_digest=marker["request_digest"],
                created_at=marker["created_at"]))
        if marker is not None:
            raise StateError("Live task conflicts with its retired identity marker")
        task = _task(db, identity["scope_id"], identity["client"], identity["session_id"], identity["task_id"])
        lifecycle = _task_lifecycle(task)
        if task["pins"]["schema_version"] != CANONICAL_SCHEMA_VERSION or lifecycle is None:
            raise StateError("Lifecycle task lacks canonical pins or an original creation time")
        return _canonical_freeze(dict(status="live", identity=identity, pins_digest=_digest(task["pins"]),
            request_digest=None, created_at=lifecycle["created_at"]))

    marker_owner = _retired(db, "assignment", reference["owner"])
    marker_id = _retired_assignment(db, reference["id"])
    row = db.execute("select id,scope_id,client,session_id,task_id,dispatch_id,data from assignments where id=?",
                     (reference["id"],)).fetchone()
    if row is None:
        if marker_owner is None or marker_id is None or marker_owner != marker_id:
            raise StateError("Lifecycle assignment identity or original age is unavailable")
        if marker_id["identity"] != reference["owner"] or marker_id["assignment_id"] != reference["id"]:
            raise StateError("Retired assignment identity differs from its reference")
        # The marker intentionally retains identity, not the old concrete assignment artifact pointer.
        return _canonical_freeze(dict(status="expired" if marker_id["evidence_expired"] else "retired",
            identity=identity, pins_digest=marker_id["pins_digest"], request_digest=marker_id["request_digest"],
            created_at=marker_id["created_at"]))
    if marker_owner is not None or marker_id is not None:
        raise StateError("Live assignment conflicts with its retired identity marker")
    record = delegation._record(None, row, db=db, context=context)
    if (record["id"] != reference["id"] or record["owner"] != reference["owner"] or
            record["data"]["assignment"] != reference["assignment"]):
        raise StateError("Live assignment differs from its exact identity reference")
    task_owner = record["owner"]
    task = _task(db, task_owner["scope_id"], task_owner["client"], task_owner["session_id"], task_owner["task_id"])
    if (task["pins"] != record["body"]["pins"] or
            task.get("accepted_identity") != record["body"].get("accepted_identity")):
        raise StateError("Live assignment differs from its original task pins")
    lifecycle = record["data"].get("lifecycle")
    if lifecycle is None:
        raise StateError("Lifecycle assignment lacks an original creation time")
    _fields(lifecycle, ("created_at",))
    _integer(lifecycle["created_at"], "original assignment creation time")
    return _canonical_freeze(dict(status="live", identity=identity,
        pins_digest=_digest(record["body"]["pins"]), request_digest=record["data"]["request_digest"],
        created_at=lifecycle["created_at"]))


def inspect_dependencies(db, task_ref):
    """Observe bounded existing rows; this is not closure or deletion permission."""
    from runtime import evidence
    _task_reference(task_ref)
    context=evidence._existing_authority_context(task_ref['authority'],db=db)
    selected_identity=_lifecycle_identity(db,'task',task_ref)
    authority=_canonical_plain(context.authority_set[0])
    def bounded(sql):
        rows=db.execute(sql+' limit 4097').fetchall()
        if len(rows)>4096:raise StateError('Lifecycle current history exceeds its observation bound')
        return rows
    tasks=[];requirements=[];blockers=[]
    for scope_id,client,session,task_id in bounded('select scope_id,client,session_id,task_id from tasks order by scope_id,client,session_id,task_id'):
        reference=dict(authority=authority,scope_id=scope_id,client=client,session_id=session,task_id=task_id)
        task=_task(db,scope_id,client,session,task_id)
        tasks.append(dict(reference=reference,task=task))
        if reference!=task_ref:requirements.append(dict(owner=reference,kind='task',reference=reference,need='raw'))
    selected=next((row['task'] for row in tasks if row['reference']==task_ref),None)
    if selected is None and selected_identity['status']=='live':raise StateError('Lifecycle task body is unavailable')
    assignments=bounded('select id,scope_id,client,session_id,task_id,dispatch_id,data from assignments order by id')
    for row in assignments:
        requirements.append(dict(owner=dict(authority=authority,id=row[0]),kind='assignment',
            reference=dict(authority=authority,id=row[0],owner=dict(zip(('scope_id','client','session_id','task_id','dispatch_id'),row[1:6]))),need='raw'))
        if tuple(row[1:5])==tuple(task_ref[k] for k in ('scope_id','client','session_id','task_id')):
            blockers.append('Assignment body requires original task; exact assignment certificate integration is required')
    turns=bounded('select scope_id,client,session_id,turn_id,task_id,continuation_consumed from turns order by scope_id,client,session_id,turn_id')
    receipts=bounded('select scope_id,client,session_id,turn_id,tool_call_id,kind,fingerprint,conflicted from receipts order by scope_id,client,session_id,turn_id,tool_call_id,kind')
    owner=tuple(task_ref[k] for k in ('scope_id','client','session_id'))
    known_tasks={tuple(row['reference'][k] for k in ('scope_id','client','session_id','task_id')) for row in tasks}
    for row in turns:
        if tuple(row[:3])==owner and tuple(row[:3])+(row[4],) not in known_tasks:
            blockers.append('Turn task ownership is ambiguous')
    for row in receipts:
        if tuple(row[:3])==owner and row[7]:blockers.append('Conflicted receipt ownership remains protected')
        if tuple(row[:3])==owner and not any(tuple(t[:4])==tuple(row[:4]) and t[4] is not None for t in turns):
            blockers.append('Receipt task ownership is ambiguous')
    metadata=[]
    for row in bounded('select name,digest,owner_key,class,created_at,closed_at,status,bytes,data from evidence_metadata order by name'):
        metadata.append(dict(reference=dict(name=row[0],digest=row[1]),metadata=_metadata_record(row)))
    checkouts=bounded('select scope_id,project_id,repository_root,git_common_dir,generation,physical_identity from checkouts order by scope_id')
    if not any(row[0]==task_ref['scope_id'] for row in checkouts):raise StateError('Lifecycle checkout is unavailable')
    bindings=bounded('select scope_id,client,session_id,task_id from bindings order by scope_id,client,session_id')
    result=dict(task=selected,tasks=tasks,assignments=assignments,turns=turns,receipts=receipts,metadata=metadata,
        checkouts=checkouts,bindings=bindings,requirements=requirements,blockers=sorted(set(blockers)))
    result=_canonical_plain(_canonical_freeze(result))
    result['digest']=_digest(result)
    return result


def _assert_open(task):
    if task is not None and task.get('lifecycle',{}).get('safe_closed_at') is not None:
        raise StateError('Safely closed task cannot admit mutations or new evidence')


def _ready_stop_bindings(context,db,task):
    """Actual complete original owner snapshot, without lifecycle or stop-envelope recursion."""
    from runtime import delegation
    scope_id=_digest([3,task['accepted_identity']['project_id'],task['accepted_identity']['repository_id'],task['accepted_identity']['checkout_id']])
    records=[r for r in delegation._ledger(None,db,context=context) if r['owner']['scope_id']==scope_id and
        all(r['owner'][k]==task[k] for k in ('client','session_id','task_id'))]
    if any(r['data']['status']!='settled' for r in records):raise StateError('Unresolved original ready owner remains protected')
    return dict(task_digest=_digest({k:v for k,v in task.items() if k not in {'lifecycle','writer_stop'}}),
        attempts_digest=_digest(task.get('evidence',{}).get('attempts',[])),
        assignments_digest=_digest(sorted(records,key=lambda r:r['id'])),
        generation=db.execute('select generation from checkouts where scope_id=?',(scope_id,)).fetchone()[0])


def _writer_stop_shape(value):
    _fields(value,('version','task_revision','proof_digest','proof','observation_ref','coordinator_ref','generation','candidate','verification','request_digest','inputs'),('linked',))
    if type(value['version']) is not int or value['version']!=1:raise StateError('Unsupported retained ready stop')
    _integer(value['task_revision'],'ready stop revision',1);_integer(value['generation'],'ready stop generation')
    for key in ('proof_digest','request_digest'):_canonical_hash(value[key])
    for key in ('proof','candidate','verification',*(['linked'] if 'linked' in value else [])):
        if key=='verification' and value[key] is None and 'linked' in value:continue
        _artifact_reference(value[key])
    for key in ('observation_ref','coordinator_ref'):_text(value[key],key)
    if not isinstance(value['inputs'],dict) or len(value['inputs'])>4096:raise StateError('Ready input observation exceeds bound')
    for path,info in value['inputs'].items():
        _canonical_path(path)
        if info is not None and (not isinstance(info,list) or len(info) not in (4,8) or any(type(n) is not int for n in info) or len(info)==4 and not stat.S_ISDIR(info[2])):
            raise StateError('Ready input physical observation is corrupt')


def _ready_stop_local_inputs(context,db,task):
    from runtime import evidence
    evidence._check_context(context,db)
    stop=task.get('writer_stop');_writer_stop_shape(stop)
    proof=evidence._read(None,stop['proof'],context=context,db=db)
    bindings=_ready_stop_bindings(context,db,task)
    candidate=evidence._read(None,stop['candidate'],context=context,db=db)
    linked=evidence._read(None,stop['linked'],context=context,db=db) if 'linked' in stop else None
    verification_ref=evidence._stop_verification(context,db,task,allow_absent=linked is not None and linked['version']==2)
    if linked is not None:evidence._linked_stop_shape(linked)
    return dict(proof=proof,bindings=bindings,candidate=candidate,linked=linked,verification_ref=verification_ref)


def _check_ready_stop_local_inputs(context,db,task,inputs):
    from runtime import evidence
    stop=task['writer_stop'];proof=inputs['proof'];bindings=inputs['bindings'];candidate=inputs['candidate']
    linked=inputs['linked'];verification_ref=inputs['verification_ref']
    evidence._ready_stop_proof(task,proof,bindings,candidate,verification_ref,linked)
    if (stop['task_revision']!=task['revision'] or stop['generation']!=bindings['generation'] or
        stop['verification']!=verification_ref or
        any(proof[k]!=stop[k] for k in ('observation_ref','coordinator_ref'))):
        raise StateError('Retained ready stop envelope changed')
    evidence._candidate_projection(candidate,task)
    if linked is None or task['lifecycle']['safe_closed_at'] is None:evidence._check_ready_inputs(stop['inputs'],directory_identity=True)
    verification=evidence._read(None,stop['verification'],context=context,db=db) if stop['verification'] is not None else None
    if task['state']=='ready' and (verification is None or verification['candidate_digest']!=proof['candidate_digest']):raise StateError('Retained ready verification changed')
    return proof


def _ready_stop_local(context,db,task):
    """Validate raw local stop inputs; a returned linked job still needs complete validation."""
    from runtime import evidence
    inputs=_ready_stop_local_inputs(context,db,task)
    proof=_check_ready_stop_local_inputs(context,db,task,inputs)
    linked=inputs['linked']
    job=None if linked is None else dict(reference=evidence._linked_basis_root(linked),
        authorities=linked['authorities'],expected=linked)
    return dict(proof=proof,bindings=inputs['bindings'],candidate=inputs['candidate'],linked=job)


def _ready_stop(context,db,task,*,observe=False,read_context=None,read_roster=None):
    from runtime import evidence
    member=(dict(authority=evidence._canonical_plain(context.authority_set[0]),scope_id=evidence._task_scope_id(task),
        **{k:task[k] for k in ('client','session_id','task_id')}) if read_context is not None or read_roster is not None else None)
    stop=task.get('writer_stop');_writer_stop_shape(stop)
    if read_roster is not None:
        linked=evidence._read(None,stop['linked'],context=context,db=db) if stop.get('linked') else None
        read_roster=evidence._matching_linked_read_roster(read_roster,linked)
    if stop.get('linked') and task['lifecycle']['safe_closed_at'] is not None:
        linked=evidence._read(None,stop['linked'],context=context,db=db)
        if evidence._linked_component_closed(evidence._linked_basis_root(linked),writer=(context,db)):
            retained=evidence._linked_retained_component(evidence._linked_basis_root(linked),evidence._linked_read_authorities(read_context,linked,member=member,writer=(context,db),read_roster=read_roster),writer=(context,db))
            if retained.get('discovered_authorities'):raise StateError('Retained linked stop requires complete source guards')
            own=next(m for m in retained['members'] if m['reference']['authority']==evidence._canonical_plain(context.authority_set[0]) and
                m['reference']['scope_id']==evidence._task_scope_id(task) and all(m['reference'][key]==task[key] for key in ('client','session_id','task_id')))
            if own['task']!=task or own['preparation']['content']['stopped']['writer_stop']!=stop:raise StateError('Historical linked stop owner changed')
            return evidence._finish_linked_read_context(own['preparation']['content']['stopped']['proof'],read_context,read_roster=read_roster)
    inputs=_ready_stop_local_inputs(context,db,task)
    linked=inputs['linked']
    if linked is not None:
        if evidence._linked_stopped_basis(evidence._linked_basis_root(linked),evidence._linked_read_authorities(read_context,linked,member=member,writer=(context,db),read_roster=read_roster),writer=(context,db))!=linked:raise StateError('Linked complete-stop basis changed')
    proof=_check_ready_stop_local_inputs(context,db,task,inputs)
    if observe and linked is None:evidence._ready_stop_candidate(context,task,inputs['candidate'],read_context=read_context,read_roster=read_roster)
    return evidence._finish_linked_read_context(proof,read_context,read_roster=read_roster)


def _retain_ready_stop(scope,request,*,linked_basis=None):
    """Private complete host stop, preserving original outcome/revision and age."""
    from runtime import evidence,changes
    if not isinstance(scope,AcceptedScope) or _scope_version(scope)!=3:raise StateError('Ready stop requires actual accepted schema3 scope')
    _fields(request,('client','session_id','task_id','scope_ref','expected_revision','expected_pins','stop_proof'),('linked_verification',))
    _identity(request);_integer(request['expected_revision'],'ready stop request revision',1);_validate_pins(request['expected_pins'])
    context=evidence._evidence_context(scope)
    if linked_basis is not None and 'linked_verification' in request:raise StateError('Select one actual linked stop source')
    pointer=linked_basis if linked_basis is not None else request.get('linked_verification')
    request_digest=_digest(dict(request=request,linked_basis=linked_basis)) if linked_basis is not None else _digest(request)
    guards=evidence._linked_stop_guards(pointer,_canonical_plain(context.authority_set)) if pointer is not None else changes._authority_guards([context.directory])
    with guards as authorities:
        with evidence._context_database(context) as db:
            task=_task(db,_scope_id(scope),request['client'],request['session_id'],request['task_id'])
            _compatible(scope,task)
            if task['revision']!=request['expected_revision'] or task['pins']!=request['expected_pins'] or task['scope_ref']!=request['scope_ref']:
                raise StateError('Ready stop request changed original task pins/revision')
            if task.get('writer_stop'):
                if linked_basis is not None:
                    retained=evidence._read(None,task['writer_stop']['linked'],context=context,db=db)
                    if evidence._linked_basis_root(retained)!=pointer:raise StateError('Ready stop replay common basis changed')
                _ready_stop(context,db,task,observe=True,read_context=evidence._bind_linked_read_context(pointer,authorities,writer=(context,db),basis=evidence._read(None,task['writer_stop']['linked'],context=context,db=db)) if pointer is not None and task['writer_stop'].get('linked') else None)
                if task['writer_stop']['request_digest']!=request_digest or task['writer_stop']['proof_digest']!=request['stop_proof']['sha256']:
                    raise StateError('Ready stop replay payload changed')
                return dict(ok=True,task=task,replayed=True)
            _assert_open(task)
            if task['state'] not in ({'ready','verifying','cancelled'} if pointer is not None else {'ready','cancelled'}) or 'evidence' not in task:
                raise StateError('Independent ready stop requires actual ordinary ready verification')
            snapshot=_ready_stop_bindings(context,db,task)
            verification_ref=evidence._stop_verification(context,db,task,allow_absent=linked_basis is not None)
            plan=evidence._read(None,task['evidence']['plan'],context=context,db=db)
        proof=evidence._read_host_proof(scope,request['stop_proof'])
        linked=evidence._linked_stop_basis(pointer,authorities) if pointer is not None else None
        if linked is not None:
            selected=[row for row in linked['members'] if row['task']['authority']==_canonical_plain(context.authority_set[0]) and
                row['task']['scope_id']==_scope_id(scope) and all(row['task'][k]==task[k] for k in ('client','session_id','task_id'))]
            if len(selected)!=1:raise StateError('Linked stop task is outside the complete approved set')
        candidate=evidence.capture_candidate(scope,plan)
        files=selected[0]['inputs'] if linked is not None else evidence._ready_stop_candidate(context,task,candidate)
        with evidence._context_database(context,write=True) as db:
            current=_task(db,_scope_id(scope),request['client'],request['session_id'],request['task_id'])
            if current!=task or _ready_stop_bindings(context,db,current)!=snapshot:raise StateError('Ready owner changed during stop capture')
            evidence._check_ready_inputs(files)
            owner=evidence._artifact_owner(scope,task)
            # Validate before registering any artifact; the candidate ref digest is its actual canonical content.
            evidence._ready_stop_proof(task,proof,snapshot,candidate,verification_ref,linked)
            if linked is not None and evidence._linked_stop_basis(pointer,authorities)!=linked:raise StateError('Linked stop changed before owner commit')
            stop=dict(version=1,task_revision=task['revision'],proof_digest=request['stop_proof']['sha256'],
                proof=evidence._artifact(scope,proof,owner=owner,db=db),observation_ref=proof['observation_ref'],
                coordinator_ref=proof['coordinator_ref'],generation=snapshot['generation'],
                candidate=evidence._artifact(scope,candidate,owner=owner,db=db),verification=verification_ref,request_digest=request_digest,inputs=files)
            if linked is not None:
                dependencies=[dict(kind='artifact',reference=dict(authority=pointer['authority'],artifact=pointer['reference']))]
                dependencies += [dict(kind='task',reference=row['task']) for row in linked['members']]
                with evidence._bound_stop_registration(scope,request,context,db,owner,linked,dependencies,
                        proof,candidate,verification_ref,authorities) as retained_owner:
                    stop['linked']=evidence._artifact(scope,linked,owner=retained_owner,db=db)
            task=dict(task,writer_stop=stop);_writer_stop_shape(stop)
            raw=json.dumps(task,separators=(',',':'))
            if len(raw.encode())>4*1024*1024:raise StateError('Ready stop exceeds the original task record bound')
            db.execute('update tasks set data=? where scope_id=? and client=? and session_id=? and task_id=?',
                (raw,_scope_id(scope),task['client'],task['session_id'],task['task_id']))
            _ready_stop(context,db,task,read_context=evidence._bind_linked_read_context(pointer,authorities,writer=(context,db),basis=evidence._read(None,task['writer_stop']['linked'],context=context,db=db)) if pointer is not None and task['writer_stop'].get('linked') else None)
            evidence._check_ready_inputs(files)
            if linked is not None and evidence._linked_stop_basis(pointer,authorities)!=linked:raise StateError('Linked stop source changed during registration')
            return dict(ok=True,task=task,replayed=False)


def _close_lifecycle(db, task_ref, observations, compact):
    """Owner-only same-revision write; general _save never permits lifecycle changes."""
    from runtime import evidence
    context=evidence._existing_authority_context(task_ref['authority'],db=db)
    facts=evidence._check_closure_observation(context,db,task_ref,observations,new_compact=compact)
    task=_task(db,task_ref['scope_id'],task_ref['client'],task_ref['session_id'],task_ref['task_id'])
    _assert_open(task)
    if task['revision']!=facts['task']['revision'] or task['state']!=facts['task']['state'] or (task['state'] not in {'cancelled','ready'} and not ('linked' in facts and task['state']=='verifying')):
        raise StateError('Closure original stopped owner changed')
    closed_at=_owner_time()
    original_age=max([task['lifecycle']['created_at']]+[item['created_at'] for item in facts['certificate'].get('assignments',[])]+
        [item['created_at'] for item in facts['projection']['numerical']+facts['projection']['verifications']])
    if closed_at<original_age:raise StateError('Closure clock regressed before original owner age')
    task['lifecycle']=dict(created_at=task['lifecycle']['created_at'],safe_closed_at=closed_at,compact=compact,
        closure=dict(version=1,task_revision=task['revision'],dependency_digest=_digest(facts),observed_at=closed_at,evidence=facts['artifacts']))
    _task_lifecycle(task)
    db.execute('update tasks set data=? where scope_id=? and client=? and session_id=? and task_id=?',
        (json.dumps(task,separators=(',',':')),task_ref['scope_id'],task_ref['client'],task_ref['session_id'],task_ref['task_id']))
    evidence._check_closure_observation(context,db,task_ref,observations,new_compact=compact)
    return task


def retire_closed(db, task_ref, closure):
    """Atomically mark exact identities before removing rows; never delete evidence files."""
    from runtime import evidence
    context=evidence._existing_authority_context(task_ref['authority'],db=db)
    facts=evidence._check_closure_observation(context,db,task_ref,closure,assignments_retired=True)
    assignment_markers=[(item['reference']['id'],_retired_assignment(db,item['reference']['id']))
        for item in facts['certificate'].get('assignments',[])]
    task=_task(db,task_ref['scope_id'],task_ref['client'],task_ref['session_id'],task_ref['task_id'])
    lifetime=_task_lifecycle(task)
    if lifetime is None or lifetime['safe_closed_at'] is None or evidence._read(None,lifetime['compact'],context=context,db=db)!=evidence._retirement_content(facts):
        raise StateError('Retirement requires exact current retained closure support')
    identity={k:task_ref[k] for k in ('scope_id','client','session_id','task_id')}
    if db.execute('select 1 from assignments where scope_id=? and client=? and session_id=? and task_id=?',tuple(identity.values())).fetchone():
        raise StateError('Surviving assignment still requires its original task')
    observed=inspect_dependencies(db,task_ref)
    if observed['blockers']:raise StateError('; '.join(observed['blockers']))
    retired_at=_owner_time()
    if retired_at<lifetime['safe_closed_at']:raise StateError('Retirement clock regressed before safe closure')
    pins_digest=_digest(task['pins']);age=lifetime['created_at'];markers=[]
    def marker(kind,key,request_digest=None):
        if _retired(db,kind,key):raise StateError('Live identity conflicts with its retired marker')
        data=dict(version=1,identity=key,pins_digest=pins_digest,request_digest=request_digest,
            created_at=age,retired_at=retired_at,outcome=task['state'],evidence_expired=False)
        digest=_retired_identity(kind,key);raw=json.dumps(data,separators=(',',':'))
        _retired_record(kind,digest,raw,None)
        db.execute('insert into retired_identities values(?,?,?,NULL)',(kind,digest,raw))
        markers.append((kind,key,data))
    turns=[row for row in observed['turns'] if tuple(row[:3])==tuple(identity.values())[:3] and row[4]==identity['task_id']]
    receipts=[row for row in observed['receipts'] if any(tuple(row[:4])==tuple(turn[:4]) for turn in turns)]
    if any(row[7] for row in receipts):raise StateError('Conflicted event receipt ownership remains protected')
    marker('task',identity)
    for row in turns:
        key=dict(zip(('scope_id','client','session_id','turn_id'),row[:4]));marker('turn',key)
    for row in receipts:
        key=dict(zip(('scope_id','client','session_id','turn_id','tool_call_id','kind'),row[:6]));marker('receipt',key,_digest(row[6]))
    for row in receipts:db.execute('delete from receipts where scope_id=? and client=? and session_id=? and turn_id=? and tool_call_id=? and kind=?',row[:6])
    for row in turns:db.execute('delete from turns where scope_id=? and client=? and session_id=? and turn_id=?',row[:4])
    db.execute('delete from bindings where scope_id=? and client=? and session_id=? and task_id=?',tuple(identity.values()))
    db.execute('delete from tasks where scope_id=? and client=? and session_id=? and task_id=?',tuple(identity.values()))
    evidence._check_closure_observation(context,db,task_ref,closure,new_compact=lifetime['compact'],retired=True)
    for kind,key,data in markers:
        if _retired(db,kind,key)!=data:raise StateError('Retirement marker changed before commit')
    if any(_retired_assignment(db,identity)!=marker for identity,marker in assignment_markers):
        raise StateError('Assignment retirement marker changed before commit')
    evidence._check_context(context,db)
    return dict(retired=True,identity=identity,outcome=task['state'])


def _scope_version(scope):
    if isinstance(scope, AcceptedScope):
        if (not all(isinstance(getattr(scope, key), MappingProxyType) and _frozen_snapshot(getattr(scope, key))
                    for key in ("accepted_identity", "bindings", "authority_target", "qualification_provenance"))
                or not all(isinstance(getattr(scope, key), Path) for key in
                    ("project_root", "repository_root", "primary_root", "git_dir", "git_common_dir", "authority_path"))
                or not isinstance(scope.runtime, RuntimeSettings) or type(scope.runtime.schema_version) is not int):
            raise StateError("Canonical scope requires immutable supported snapshots")
        identity = _accepted_identity(scope.accepted_identity)
        expected = dict(project_id=scope.project_id, repository_id=scope.repository_id, checkout_id=scope.checkout_id,
            project_root=str(scope.project_root), primary_root=str(scope.primary_root), repository_root=str(scope.repository_root),
            git_dir=str(scope.git_dir), git_common_dir=str(scope.git_common_dir), client=scope.client,
            bindings=_canonical_plain(scope.bindings))
        if (any(identity[key] != value for key, value in expected.items()) or scope.runtime is None
                or scope.runtime.schema_version != 3 or identity["configuration"] != dict(policy_digest=scope.policy_digest,
                    runtime_digest=scope.runtime_digest, runtime=dict(schema_version=3, state_dir=str(scope.runtime.state_dir)))
                or _digest(identity) != scope.accepted_scope_digest
                or scope.authority_path != scope.project_root / PROJECT_FILE):
            raise StateError("Canonical scope differs from its accepted projection")
        return 3
    if scope.runtime is None or scope.runtime.schema_version != SCHEMA_VERSION:
        raise StateError("Runtime state is not configured with a supported schema")
    return SCHEMA_VERSION


def _pins(scope):
    version = _scope_version(scope) if isinstance(scope, AcceptedScope) else SCHEMA_VERSION
    runtime = runtime_fingerprint()
    if version == 3 and runtime != scope.runtime_digest:
        raise StateError("Installed runtime differs from accepted canonical scope")
    pins = dict(schema_version=version, policy_digest=scope.policy_digest, runtime_digest=runtime)
    if version == 3:
        pins["accepted_scope_digest"] = scope.accepted_scope_digest
    return pins


def _scope_id(scope):
    if isinstance(scope, AcceptedScope):
        _scope_version(scope)
        return _digest([3, scope.project_id, scope.repository_id, scope.checkout_id])
    return hashlib.sha256(json.dumps([scope.project_id, str(scope.repository_root), str(scope.git_common_dir)]).encode()).hexdigest()


def _checkout_row(db, scope, *, initialize=False):
    version, scope_id = _scope_version(scope), _scope_id(scope)
    row = db.execute("select * from checkouts where scope_id=?", (scope_id,)).fetchone()
    expected = (scope_id, scope.project_id, str(scope.repository_root), str(scope.git_common_dir))
    physical = _physical_identity(_accepted_identity(scope.accepted_identity)) if version == 3 else None
    if row is not None:
        if (row[:4] != expected or type(row[4]) is not int or row[4] < 0
                or version == 3 and json_object(row[5]) != physical):
            raise StateError("Checkout row differs from accepted physical identity")
    elif initialize:
        if version == 3:
            db.execute("insert into checkouts values(?,?,?,?,0,?)", (*expected, json.dumps(physical, separators=(",", ":"))))
        else:
            db.execute("insert into checkouts values(?,?,?,?,0)", expected)
        row = db.execute("select * from checkouts where scope_id=?", (scope_id,)).fetchone()
    return row


def _task_projection(db, scope_id, task):
    version = db.execute("pragma user_version").fetchone()[0]
    _validate_pins(task.get("pins"), version=version)
    if version != 3:
        if "accepted_identity" in task:
            raise StateError("Legacy task cannot acquire canonical identity")
        return
    identity = _accepted_identity(task.get("accepted_identity"))
    row = db.execute("select * from checkouts where scope_id=?", (scope_id,)).fetchone()
    database_path = Path(db.execute("pragma database_list").fetchone()[2])
    if (identity["configuration"]["runtime"]["state_dir"] != str(database_path.parent)
            or identity["client"] != task["client"] or _digest(identity) != task["pins"]["accepted_scope_digest"]
            or any(identity["configuration"][k] != task["pins"][k] for k in ("policy_digest", "runtime_digest"))
            or _digest([3, identity["project_id"], identity["repository_id"], identity["checkout_id"]]) != scope_id
            or row is None or row[:4] != (scope_id, identity["project_id"], identity["repository_root"], identity["git_common_dir"])
            or json_object(row[5]) != _physical_identity(identity)):
        raise StateError("Task snapshot, pins and physical checkout differ")


def _text(value, field, limit=1024):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or not value.isprintable():
        raise StateError("Invalid " + field)
    return value


def _fields(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or not set(required) <= set(value):
        raise StateError("Invalid task control fields")


def _identity(request, *, allow_claude=False):
    for name in ("client", "session_id", "task_id", "scope_ref"):
        _text(request.get(name), name, 128 if name == "task_id" else 1024)
    if request["client"] != "codex" and not (allow_claude and request["client"] == "claude-code"):
        raise StateError("Unsupported task client")


def _require_claude_scope(scope, client):
    if client == "claude-code" and (not isinstance(scope, AcceptedScope) or scope.client != client):
        raise StateError("Claude Code runtime controls require an accepted canonical client scope")


def _integer(value, field, minimum=0):
    if type(value) is not int or value < minimum:
        raise StateError("Invalid " + field)


def _private(path, directory=False):
    info = path.lstat()
    if (info.st_uid != os.getuid() or info.st_mode & 0o077 or
            not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)) or
            (not directory and info.st_nlink != 1)):
        raise StateError("Runtime state requires private current-user directories and regular files")


def _path(scope):
    _scope_version(scope)
    directory = scope.runtime.state_dir
    if not directory.is_absolute() or directory.resolve() != directory:
        raise StateError("Runtime state path must be canonical and have no symlinks")
    for path in (directory, *directory.parents):
        if os.path.lexists(path) and (path.is_symlink() or not path.is_dir()):
            raise StateError("Runtime state ancestors must be directories without symlinks")
    if directory.exists():
        _private(directory, True)
    return directory / "runtime.sqlite3"


def _sidecars(path):
    _private(path)
    for suffix in ("-journal", "-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        if os.path.lexists(sidecar):
            _private(sidecar)
            if suffix != "-journal":
                raise StateError("Unsupported runtime journal mode")


def _schema(db, *, version=SCHEMA_VERSION):
    # Version 1 is accepted only by D4's private read-only transition inspector.
    tables = TABLES - {"assignments"} if version == 1 else set(CANONICAL_TABLE_SQL) if version == 3 else TABLES
    objects = db.execute("select type,name,sql from sqlite_master").fetchall()
    if (version not in (1, SCHEMA_VERSION, CANONICAL_SCHEMA_VERSION) or
            db.execute("pragma application_id").fetchone()[0] != APPLICATION_ID or
            db.execute("pragma user_version").fetchone()[0] != version or
            {name for kind, name, _ in objects if kind == "table"} != tables or
            db.execute("pragma journal_mode").fetchone()[0] != "delete"):
        raise StateError("Runtime database is unowned or has an incompatible schema")
    for kind, name, sql in objects:
        if kind == "table":
            if "".join(sql.split()).lower() != "".join((CANONICAL_TABLE_SQL if version == 3 else TABLE_SQL)[name].split()).lower():
                raise StateError("Runtime database has an incompatible schema")
        elif kind == "index" and version == 3:
            if sql is None:
                allowed = {"sqlite_autoindex_" + table + "_1" for table in CANONICAL_TABLE_SQL} | {"sqlite_autoindex_assignments_2"}
                if name not in allowed:
                    raise StateError("Runtime database contains unexpected indexes")
            elif name not in CANONICAL_INDEX_SQL or sql.strip() != CANONICAL_INDEX_SQL[name]:
                raise StateError("Runtime database has incompatible admission indexes")
        elif kind != "index" or sql is not None:
            raise StateError("Runtime database contains unsupported schema objects")
    if version == 3 and {name for kind, name, sql in objects if kind == "index" and sql is not None} != set(CANONICAL_INDEX_SQL):
        raise StateError("Runtime database is missing required lifecycle indexes")


_CREATION_ISSUER = object()


@dataclass(frozen=True)
class _AuthorityCreation:
    authority: object
    created_at: int
    descriptor: int
    issuer: object


def _authority_identity(path):
    def binding(item):
        info = item.lstat()
        return dict(device=info.st_dev, inode=info.st_ino)
    return dict(directory=str(path.parent), database=str(path),
        directory_binding=binding(path.parent), database_binding=binding(path))


def _check_creation(path, creation, db=None):
    if not isinstance(creation, _AuthorityCreation) or creation.issuer is not _CREATION_ISSUER:
        raise StateError('Fresh authority creation witness is required')
    info = os.fstat(creation.descriptor)
    authority = _canonical_plain(creation.authority)
    _private(path.parent, True)
    _private(path)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
            or info.st_mode & 0o077 or dict(device=info.st_dev, inode=info.st_ino) != authority['database_binding']
            or _authority_identity(path) != authority):
        raise StateError('Fresh database physical identity changed')
    if db is not None:
        if db.execute('pragma database_list').fetchall() != [(0, 'main', str(path))]:
            raise StateError('Fresh database connection differs from creation witness')


def _prepare_directory(directory):
    missing = []
    ancestor = directory
    while not ancestor.exists():
        missing.append(ancestor)
        ancestor = ancestor.parent
    for item in reversed(missing):
        try:
            item.mkdir(mode=0o700)
        except FileExistsError:
            _private(item, True)
    _private(directory, True)


def _initialize(path, *, version=SCHEMA_VERSION, expected_directory=None, initialize_metadata=None):
    if initialize_metadata is None:
        _prepare_directory(path.parent)
    else:
        _private(path.parent, True)
    if version == 3:
        parent_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            directory_info = os.fstat(parent_descriptor)
            binding = dict(device=directory_info.st_dev, inode=directory_info.st_ino)
            if expected_directory is not None and binding != expected_directory:
                raise StateError('Authority directory differs from the guarded physical identity')
            descriptor = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=parent_descriptor)
        finally:
            os.close(parent_descriptor)
    else:
        directory_info = path.parent.lstat()
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    creation = None
    try:
        if version == 3:
            info = os.fstat(descriptor)
            authority = dict(directory=str(path.parent), database=str(path),
                directory_binding=dict(device=directory_info.st_dev, inode=directory_info.st_ino),
                database_binding=dict(device=info.st_dev, inode=info.st_ino))
            creation = _AuthorityCreation(_canonical_freeze(authority), _owner_time(), descriptor, _CREATION_ISSUER)
            _check_creation(path, creation)
            if initialize_metadata is not None:
                from runtime.changes import _checkpoint
                _checkpoint('birth-unreceipted')
        else:
            os.close(descriptor)
            descriptor = None
        with closing(sqlite3.connect(path, timeout=0.1)) as db, db:
            if creation is not None:
                _check_creation(path, creation, db)
            statements = list((CANONICAL_TABLE_SQL if version == 3 else TABLE_SQL).values())
            if version == 3:
                statements += list(CANONICAL_INDEX_SQL.values())
            db.executescript('BEGIN IMMEDIATE;\n' + ';\n'.join(statements) + ';')
            db.execute('pragma application_id=' + str(APPLICATION_ID))
            db.execute('pragma user_version=' + str(version))
            if creation is not None:
                _check_creation(path, creation, db)
            if initialize_metadata is not None:
                initialize_metadata(db, creation)
                _check_creation(path, creation, db)
        if creation is not None:
            os.fsync(creation.descriptor)
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try: os.fsync(directory)
            finally: os.close(directory)
        return creation
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        raise


def _source_baseline_name(authority):
    return _digest(['authority-source-baseline', authority])[:32] + '.json'


def _source_baseline(scope, db, *, context=None):
    """Return fresh-owner provenance only; no source completeness or cleanup permission."""
    if (scope is None) == (context is None):
        raise StateError('Select exactly one existing evidence authority')
    if db is None or context is None and _scope_version(scope) != 3:
        return None
    from runtime import evidence
    selected = context
    context = context or evidence._evidence_context(scope)
    evidence._check_context(context, db)
    authority = _canonical_plain(context.authority_set[0])
    name = _source_baseline_name(authority)
    metadata = _metadata(db, name)
    if metadata is None:
        return None
    reference = dict(name=name, digest=metadata['managed']['sha256'])
    content = evidence._read(None if selected else scope, reference, context=selected, db=db)
    _fields(content, ('version', 'kind', 'source_contract', 'authority', 'project_id', 'created_at', 'runtime_digest'), ('birth_expectation',))
    if (type(content['version']) is not int or content['version'] != 1 or content['kind'] != 'authority-source-baseline'
            or type(content['source_contract']) is not int or content['source_contract'] not in (1, 2)
            or content['authority'] != authority or metadata['class'] != 'compact'
            or metadata['owner'] != dict(kind='project', project_id=content['project_id'], task=None)
            or metadata['created_at'] != content['created_at'] or metadata['closed_at'] is not None
            or metadata['targets'] or metadata['export'] is not None):
        raise StateError('Authority source baseline provenance is invalid')
    if 'birth_expectation' in content:
        expectation = content['birth_expectation']
        _fields(expectation, ('version', 'identity', 'intent_digest'))
        _fields(expectation['identity'], ('plan_dir', 'transaction_id', 'manifest_digest'))
        if expectation['version'] != 1 or type(expectation['version']) is not int or content['source_contract'] != 2:
            raise StateError('Unsupported original birth expectation')
        _canonical_path(expectation['identity']['plan_dir'])
        _text(expectation['identity']['transaction_id'], 'birth transaction')
        _canonical_hash(expectation['identity']['manifest_digest'])
        _canonical_hash(expectation['intent_digest'])
    _canonical_hash(content['runtime_digest'])
    _integer(content['created_at'], 'original authority creation time')
    for dependency in metadata['dependencies']:
        if dependency['kind'] != 'recovery':
            raise StateError('Authority baseline has an unsupported source dependency')
        _fields(dependency['reference'], ('identity', 'artifact'))
        _fields(dependency['reference']['identity'], ('plan_dir', 'transaction_id', 'manifest_digest'))
        _canonical_path(dependency['reference']['identity']['plan_dir'])
        _text(dependency['reference']['identity']['transaction_id'], 'recovery transaction identity')
        _canonical_hash(dependency['reference']['identity']['manifest_digest'])
        _artifact_reference(dependency['reference']['artifact'])
    return _canonical_freeze(dict(reference=reference, content=content, dependencies=metadata['dependencies']))


@contextmanager
def _database(scope, write=False, initialize=False, *, guard_existing=False):
    db = creation = None
    with ExitStack() as guards:
        try:
            path = _path(scope)
            version = _scope_version(scope)
            if initialize and version == 3:
                if not write:
                    raise StateError('Fresh schema3 bootstrap requires its write transaction')
                _prepare_directory(path.parent)
                directory_binding = _authority_identity(path)['directory_binding'] if path.exists() else dict(
                    device=path.parent.lstat().st_dev, inode=path.parent.lstat().st_ino)
                from runtime.changes import _authority_guards
                guards.enter_context(_authority_guards([path.parent]))
                info = path.parent.lstat()
                if dict(device=info.st_dev, inode=info.st_ino) != directory_binding:
                    raise StateError('Authority directory changed before bootstrap guard')
            elif guard_existing and version == 3:
                if not write:
                    raise StateError('Existing canonical task guard requires its write transaction')
                _private(path.parent, True)
                authority = _authority_identity(path)
                from runtime.changes import _authority_guards
                guards.enter_context(_authority_guards([path.parent]))
                if _authority_identity(path) != authority:
                    raise StateError('Existing authority physical identity changed before task guard')
            if not os.path.lexists(path):
                if initialize:
                    try:
                        if version == 3:
                            creation = _initialize(path, version=version, expected_directory=directory_binding)
                        else:
                            creation = _initialize(path, version=version)
                    except FileExistsError:
                        pass
                else:
                    yield None
                    return
            _sidecars(path)
            if creation is not None:
                _check_creation(path, creation)
            db = sqlite3.connect(path.as_uri() + ('?mode=rw' if write else '?mode=ro'), uri=True, timeout=0.1)
            if creation is not None:
                _check_creation(path, creation, db)
            db.execute('pragma busy_timeout=100')
            db.execute('pragma trusted_schema=off')
            _schema(db, version=version)
            db.execute('begin immediate' if write else 'begin')
            if creation is not None:
                from runtime.evidence import _register_source_baseline
                _register_source_baseline(scope, db, creation)
                _check_creation(path, creation, db)
            yield db
            if write:
                _sidecars(path)
                if creation is not None:
                    _check_creation(path, creation, db)
                db.commit()
                if creation is not None:
                    _check_creation(path, creation, db)
        except StateError:
            raise
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
            raise StateError('Runtime state is unavailable, corrupt, locked or incompatible') from None
        finally:
            if db is not None:
                db.close()
            if creation is not None:
                os.close(creation.descriptor)


def _task(db, scope_id, client, session, task_id=None):
    if task_id is None:
        binding = db.execute("select task_id from bindings where scope_id=? and client=? and session_id=?",
                             (scope_id, client, session)).fetchone()
        if binding is None:
            return None
        task_id = binding[0]
    row = db.execute("select data from tasks where scope_id=? and client=? and session_id=? and task_id=?",
                     (scope_id, client, session, task_id)).fetchone()
    if row is None:
        if _retired(db, "task", dict(scope_id=scope_id, client=client, session_id=session, task_id=task_id)):
            raise StateError("Retired task evidence is unavailable or expired")
        raise StateError("Runtime task binding is corrupt")
    version = db.execute("pragma user_version").fetchone()[0]
    task = json_object(row[0], limit=4 * 1024 * 1024) if version == 3 else json.loads(row[0])
    _fields(task, ("client", "session_id", "task_id", "scope_ref", "mode", "decision_ref", "state", "revision",
                   "pins", "reason", "reference", "conditions", "turn_id", "turn_uncertain", *(["accepted_identity"] if version == 3 else [])), ("resolution_ref", "evidence", "retirement", "delegation", *(["lifecycle","writer_stop"] if version == 3 else [])))
    stored_claude = (version == 3 and task.get("client") == "claude-code" and
                     isinstance(task.get("accepted_identity"), dict) and
                     task["accepted_identity"].get("client") == "claude-code")
    _identity(task, allow_claude=stored_claude)
    _integer(task["revision"], "stored revision", 1)
    for field in ("decision_ref", "reason", "reference", "resolution_ref"):
        if field in task:
            _text(task[field], "stored " + field)
    if (task["task_id"] != task_id or task["client"] != client or task["session_id"] != session or
            task["state"] not in STATES or task["mode"] not in {"editable", "read-only"} or
            type(task["turn_uncertain"]) is not bool or not isinstance(task["conditions"], list) or
            len(task["conditions"]) > 64):
        raise StateError("Runtime task record is corrupt")
    if task["turn_id"] is not None:
        _text(task["turn_id"], "stored turn_id", 4096)
    _task_projection(db, scope_id, task)
    if task["client"] == "claude-code" and any(field in task for field in ("evidence", "delegation", "retirement", "writer_stop")):
        raise StateError("Claude Code task records do not support evidence, delegation or retirement")
    if version == 3:
        _task_lifecycle(task)
        if _retired(db, "task", dict(scope_id=scope_id, client=client, session_id=session, task_id=task_id)):
            raise StateError("Live task conflicts with a retired identity marker")
    seen = set()
    for condition in task["conditions"]:
        _fields(condition, ("id", "kind", "action", "reason", "reference", "status"), ("resolution_ref", "continuation"))
        for field in ("id", "reason", "reference", "resolution_ref"):
            if field in condition:
                _text(condition[field], "stored condition " + field, 128 if field == "id" else 1024)
        if (condition["id"] in seen or condition["kind"] not in ("blocker", "decision", "runnable") or
                condition["action"] not in ("patch", "task") or condition["status"] not in ("pending", "resolved") or
                (condition["status"] == "resolved" and "resolution_ref" not in condition)):
            raise StateError("Runtime condition record is corrupt")
        seen.add(condition["id"])
        if "continuation" in condition:
            continuation = condition["continuation"]
            _fields(continuation, ("turn_id", "budget", "consumed", "revoked"))
            _text(continuation["turn_id"], "stored continuation turn_id", 4096)
            if (condition["kind"] != "runnable" or type(continuation["revoked"]) is not bool or any(
                    type(continuation[field]) is not int or continuation[field] not in (0, 1)
                    for field in ("budget", "consumed"))):
                raise StateError("Runtime continuation record is corrupt")
    if "evidence" in task:
        from runtime.evidence import validate_evidence
        validate_evidence(task["evidence"], canonical=version == 3)
    if "delegation" in task:
        from runtime.delegation import validate_delegation
        validate_delegation(task["delegation"])
    if "writer_stop" in task:_writer_stop_shape(task["writer_stop"])
    if "retirement" in task:
        retirement = task["retirement"]
        _fields(retirement, ("proof_digest", "proof", "observation_ref", "coordinator_ref", "previous_revision"))
        for field in ("proof_digest", "observation_ref", "coordinator_ref"):
            _text(retirement[field], "stored retirement " + field)
        _integer(retirement["previous_revision"], "stored retirement revision", 1)
        if task["state"] != "cancelled" or retirement["previous_revision"] >= task["revision"]:
            raise StateError("Retired task must remain terminal with original history")
    return task


def _save(db, scope_id, task):
    _task_projection(db, scope_id, task)
    if task["pins"]["schema_version"] == 3:
        previous = db.execute("select data from tasks where scope_id=? and client=? and session_id=? and task_id=?",
            (scope_id, task["client"], task["session_id"], task["task_id"])).fetchone()
        if previous:
            old = json_object(previous[0], limit=4 * 1024 * 1024)
            _assert_open(old)
            if old["accepted_identity"] != task["accepted_identity"] or old["pins"] != task["pins"]:
                raise StateError("Stored task identity and pins are immutable")
            if old.get("writer_stop")!=task.get("writer_stop") or ("writer_stop" in old)!=("writer_stop" in task):
                raise StateError("Ready stop belongs to its independent owner writer")
            if old.get("lifecycle") != task.get("lifecycle") or ("lifecycle" in old) != ("lifecycle" in task):
                raise StateError("Original lifecycle age/closure is immutable until owner integration")
        else:
            if "lifecycle" in task or "writer_stop" in task:
                raise StateError("Caller cannot supply task lifecycle age or closure")
            task["lifecycle"] = dict(created_at=_owner_time(), safe_closed_at=None, closure=None, compact=None)
        _task_lifecycle(task)
        owner = dict(scope_id=scope_id, **{k: task[k] for k in ("client", "session_id", "task_id")})
        if _retired(db, "task", owner):
            raise StateError("Retired task cannot be saved or rebound")
    if "delegation" in task:
        from runtime.delegation import validate_delegation
        validate_delegation(task["delegation"])
    if 'evidence' in task:
        from runtime.evidence import validate_evidence
        validate_evidence(task['evidence'], canonical=task['pins']['schema_version'] == 3)
    db.execute("insert or replace into tasks values(?,?,?,?,?)", (scope_id, task["client"], task["session_id"],
               task["task_id"], json.dumps(task, separators=(",", ":"))))


def _compatible(scope, task):
    if task is not None and (task["pins"] != _pins(scope) or isinstance(scope, AcceptedScope)
                            and task["accepted_identity"] != _canonical_plain(scope.accepted_identity)):
        raise StateError("Task policy, runtime or schema pins differ; explicit migration is required")


def _status(db, scope, client, session):
    scope_id = _scope_id(scope)
    task = _task(db, scope_id, client, session) if db else None
    _compatible(scope, task)
    row = _checkout_row(db, scope) if db else None
    return dict(ok=True, task=task, generation=row[4] if row else 0,
                blockers=[condition for condition in task["conditions"] if condition["status"] == "pending" and
                          condition["kind"] in {"blocker", "decision"}] if task else [], limitations=LIMITATIONS)


def task_status(scope, client, session_id):
    _text(client, "client")
    _text(session_id, "session_id")
    if client not in {"codex", "claude-code"}:
        raise StateError("Unsupported task client")
    _require_claude_scope(scope, client)
    if client == "codex":
        from runtime.evidence import revalidate_ready
        revalidate_ready(scope, client, session_id)
    with _database(scope) as db:
        status = _status(db, scope, client, session_id)
        if client == "claude-code" and status["task"] is not None and status["task"]["state"] == "ready":
            raise StateError("Claude Code task readiness is unverified by the available evidence adapter")
        if status['task'] is not None and status['task'].get('lifecycle',{}).get('safe_closed_at') is not None:
            from runtime.evidence import _closed_status
            status['historical']=_closed_status(scope,status['task'])
        return status


def inspect_state(scope):
    """Inspect ownership/schema/pins without creating files or requiring a session."""
    report = dict(configured=scope.runtime is not None, present=False, compatible=False,
                  schema_version=3 if isinstance(scope, AcceptedScope) else SCHEMA_VERSION, policy_digest=scope.policy_digest,
                  runtime_digest=runtime_fingerprint(), tasks=[])
    if scope.runtime is None:
        report["compatible"] = True
        return report
    report["present"] = os.path.lexists(scope.runtime.state_dir / "runtime.sqlite3")
    try:
        with _database(scope) as db:
            if db:
                _checkout_row(db, scope)
                for client, session, task_id in db.execute("select client,session_id,task_id from tasks where scope_id=?", (_scope_id(scope),)):
                    task = _task(db, _scope_id(scope), client, session, task_id)
                    report["tasks"].append(dict(task_id=task_id, pins=task["pins"], compatible=task["pins"] == _pins(scope)))
                report["compatible"] = all(task["compatible"] for task in report["tasks"])
            else:
                report["compatible"] = True
    except StateError as error:
        report["error"] = str(error)
    return report


def _guard_assignments(db, scope, client, session):
    from runtime.delegation import _ledger
    if any(record['owner']['scope_id'] == _scope_id(scope) and record['owner']['client'] == client and
           record['owner']['session_id'] == session and record['data']['status'] != 'settled'
           for record in _ledger(scope, db)):
        raise StateError('Unresolved assignments retain historical session ownership; reconcile exact attempts first')


def start_task(scope, request):
    _fields(request, ("client", "session_id", "task_id", "scope_ref", "mode", "decision_ref"), ("replaces",))
    _identity(request, allow_claude=request.get("client") == "claude-code")
    _require_claude_scope(scope, request["client"])
    _text(request["decision_ref"], "decision_ref")
    if request["mode"] not in ("read-only", "editable"):
        raise StateError("Invalid task mode")
    replacement = request.get("replaces")
    if "replaces" in request:
        _fields(replacement, ("task_id", "expected_revision"))
        _text(replacement["task_id"], "replaced task_id", 128)
        _integer(replacement["expected_revision"], "expected_revision", 1)
    if isinstance(scope, AcceptedScope) and request["client"] != scope.client:
        raise StateError("Task client differs from accepted scope")
    pins = _pins(scope)
    if isinstance(scope, AcceptedScope) and not _path(scope).exists():
        raise StateError('Canonical authority birth requires the owned D4 operation')
    with _database(scope, write=True, initialize=not isinstance(scope, AcceptedScope),
                   guard_existing=isinstance(scope, AcceptedScope)) as db:
        if db is None:
            raise StateError('Canonical authority is unavailable')
        if isinstance(scope, AcceptedScope) and _source_baseline(scope, db) is None:
            raise StateError('Canonical authority original baseline is unavailable')
        scope_id = _scope_id(scope)
        if _retired(db, "task", dict(scope_id=scope_id, **{k:request[k] for k in ("client", "session_id", "task_id")})):
            raise StateError("Retired task identity cannot start again; evidence is unavailable or expired")
        _checkout_row(db, scope, initialize=True)
        current = _task(db, scope_id, request["client"], request["session_id"])
        if current and current["task_id"] == request["task_id"]:
            _assert_open(current)
            _compatible(scope, current)
            if any(current[field] != request[field] for field in ("scope_ref", "mode", "decision_ref")):
                raise StateError("Task mode, scope and decision reference are immutable")
            return _status(db, scope, request["client"], request["session_id"])
        if db.execute("select 1 from tasks where scope_id=? and client=? and session_id=? and task_id=?",
                      (scope_id, request["client"], request["session_id"], request["task_id"])).fetchone():
            raise StateError("Historical task identity cannot be rebound or replaced")
        _guard_assignments(db, scope, request["client"], request["session_id"])
        if current:
            _compatible(scope, current)
            if replacement != dict(task_id=current["task_id"], expected_revision=current["revision"]):
                raise StateError("Replacing a bound task requires its identity and current revision")
            if current.get("lifecycle",{}).get("safe_closed_at") is None:
                current["revision"] += 1
            for condition in current["conditions"]:
                if "continuation" in condition:
                    condition["continuation"]["revoked"] = True
            if current.get("lifecycle",{}).get("safe_closed_at") is None:
                _save(db, scope_id, current)
        elif replacement is not None:
            raise StateError("No bound task matches the requested replacement")
        task = {field: request[field] for field in ("client", "session_id", "task_id", "scope_ref", "mode", "decision_ref")}
        task.update(state="planned", revision=1, pins=pins, reason="Task started", reference=request["decision_ref"],
                    conditions=[], turn_id=None, turn_uncertain=True)
        if isinstance(scope, AcceptedScope):
            task["accepted_identity"] = _accepted_identity(scope.accepted_identity)
        _save(db, scope_id, task)
        db.execute("insert or replace into bindings values(?,?,?,?)", (scope_id, request["client"], request["session_id"], request["task_id"]))
        return _status(db, scope, request["client"], request["session_id"])


def _condition(value, task, previous):
    _fields(value, ("id", "kind", "action", "reason", "reference"), ("continuation",))
    for field in ("id", "reason", "reference"):
        _text(value[field], "condition " + field, 128 if field == "id" else 1024)
    if value["kind"] not in ("blocker", "decision", "runnable") or value["action"] not in ("patch", "task"):
        raise StateError("Invalid condition kind or affected action")
    condition = dict(value, status=previous.get("status", "pending") if previous else "pending")
    if previous and previous.get("resolution_ref"):
        condition["resolution_ref"] = previous["resolution_ref"]
    if previous and (value["kind"], value["action"]) != (previous["kind"], previous["action"]):
        raise StateError("A stable condition cannot change kind or action")
    old = previous.get("continuation") if previous else None
    if "continuation" in value:
        continuation = value["continuation"]
        _fields(continuation, ("turn_id", "budget"))
        _text(continuation["turn_id"], "continuation turn_id")
        if type(continuation["budget"]) is not int or continuation["budget"] not in (0, 1):
            raise StateError("Continuation budget must be zero or one")
        if (value["kind"] != "runnable" or task["state"] not in {"active", "verifying"} or
                task["turn_id"] != continuation["turn_id"] or task["turn_uncertain"]):
            raise StateError("Continuation requires a runnable condition and observed current task turn")
        if old and (old["turn_id"] != continuation["turn_id"] or continuation["budget"] > old["budget"]):
            raise StateError("A stable condition cannot change turns or increase its continuation budget")
        condition["continuation"] = dict(continuation, consumed=old["consumed"] if old else 0,
                                         revoked=old["revoked"] if old else False)
    elif old:
        condition["continuation"] = old
    return condition


def update_task(scope, request):
    _fields(request, ("client", "session_id", "task_id", "scope_ref", "expected_revision", "state", "reason", "reference"),
            ("conditions", "resolutions", "resolution_ref"))
    _identity(request, allow_claude=request.get("client") == "claude-code")
    _require_claude_scope(scope, request["client"])
    _integer(request["expected_revision"], "expected_revision", 1)
    for field in ("reason", "reference"):
        _text(request[field], field)
    if "resolution_ref" in request:
        _text(request["resolution_ref"], "resolution_ref")
    if not isinstance(request["state"], str) or request["state"] not in STATES - {"ready"}:
        raise StateError("Only completion evidence verification can declare ready")
    for field in ("conditions", "resolutions"):
        if field in request and (not isinstance(request[field], list) or len(request[field]) > 64):
            raise StateError("Task conditions and resolutions must be bounded lists")
    with _database(scope, write=True) as db:
        if db is None:
            raise StateError("Task state has not been initialized")
        scope_id = _scope_id(scope)
        task = _task(db, scope_id, request["client"], request["session_id"])
        if task is None or task["task_id"] != request["task_id"] or task["scope_ref"] != request["scope_ref"]:
            raise StateError("Task update does not match the current binding")
        _compatible(scope, task)
        if task["revision"] != request["expected_revision"]:
            raise StateError("Task revision conflict")
        old_state, state = task["state"], request["state"]
        allowed = (old_state == state or state in {"awaiting_user", "blocked", "cancelled"} or
                   (old_state, state) in {("planned", "active"), ("active", "verifying"), ("verifying", "active"), ("ready", "active"), ("ready", "verifying")} or
                   (old_state in {"blocked", "awaiting_user"} and state in {"planned", "active", "verifying"} and
                    "resolution_ref" in request))
        if old_state == "cancelled" or not allowed:
            raise StateError("Task state transition is not allowed")
        task.update(state=state, reason=request["reason"], reference=request["reference"])
        if "resolution_ref" in request:
            task["resolution_ref"] = request["resolution_ref"]
        conditions = {condition["id"]: condition for condition in task["conditions"]}
        seen = set()
        for value in request.get("conditions", []):
            condition = _condition(value, task, conditions.get(value.get("id")) if isinstance(value, dict) and isinstance(value.get("id"), str) else None)
            if condition["id"] in seen:
                raise StateError("Duplicate condition identity")
            seen.add(condition["id"])
            conditions[condition["id"]] = condition
        if len(conditions) > 64:
            raise StateError("Task condition history exceeds its bound")
        seen = set()
        for resolution in request.get("resolutions", []):
            _fields(resolution, ("id", "reference"))
            _text(resolution["id"], "resolution id", 128)
            _text(resolution["reference"], "resolution reference")
            if resolution["id"] not in conditions or resolution["id"] in seen:
                raise StateError("Resolution must identify an existing condition once")
            seen.add(resolution["id"])
            conditions[resolution["id"]].update(status="resolved", resolution_ref=resolution["reference"])
        task["conditions"] = list(conditions.values())
        if state in {"blocked", "awaiting_user", "cancelled"}:
            for condition in task["conditions"]:
                if "continuation" in condition:
                    condition["continuation"]["revoked"] = True
        task["revision"] += 1
        _save(db, scope_id, task)
        return _status(db, scope, request["client"], request["session_id"])


def process_event(scope, event):
    """Evaluate and apply in one short transaction; hooks never initialize state."""
    if scope.runtime is None:
        return HookResult(event.kind)
    try:
        _require_claude_scope(scope, event.client)
        if isinstance(scope, AcceptedScope) and event.client != scope.client:
            raise StateError("Event client differs from accepted scope")
        with _database(scope, write=True) as db:
            if db is None:
                raise StateError("Task state has not been initialized")
            scope_id = _scope_id(scope)
            retired_event=False
            event_identity = dict(scope_id=scope_id, client=event.client, session_id=event.session_id, turn_id=event.turn_id)
            if event.turn_id is not None:
                if _retired(db, "turn", event_identity):
                    retired_event=True
                    if event.kind!="PostToolUse":raise StateError("Retired event cannot be rebound")
                if event.tool_call_id is not None:
                    receipt_identity = event_identity | dict(tool_call_id=event.tool_call_id, kind=event.kind)
                    if _retired(db, "receipt", receipt_identity):
                        retired_event=True
                        if event.kind!="PostToolUse":raise StateError("Retired receipt cannot be replayed as new work")
            _checkout_row(db, scope)
            task = _task(db, scope_id, event.client, event.session_id)
            _compatible(scope, task)
            closed=task is not None and task.get("lifecycle",{}).get("safe_closed_at") is not None
            if closed and event.kind!="PostToolUse":_assert_open(task)
            identity = (scope_id, event.client, event.session_id, event.turn_id)
            row = db.execute("select task_id,continuation_consumed from turns where scope_id=? and client=? and session_id=? and turn_id=?", identity).fetchone() if event.turn_id else None
            receipt_identity = (*identity, event.tool_call_id, event.kind)
            receipt = db.execute("select fingerprint,conflicted from receipts where scope_id=? and client=? and session_id=? and turn_id=? and tool_call_id=? and kind=?", receipt_identity).fetchone() if event.turn_id and event.tool_call_id else None
            if closed or retired_event:
                # External completions still invalidate the physical checkout, without resuming a terminal owner.
                result,changes=evaluate(event,dict(task=None,turn=None,receipt={"fingerprint":receipt[0],"conflicted":receipt[1]} if receipt else None))
                if changes['generation_delta']:
                    db.execute('update checkouts set generation=generation+? where scope_id=?',(changes['generation_delta'],scope_id))
                if changes.get('poison_receipt'):
                    db.execute('update receipts set conflicted=1 where scope_id=? and client=? and session_id=? and turn_id=? and tool_call_id=? and kind=?',receipt_identity)
                return HookResult(event.kind,'context','Terminal task remains closed; external completion freshness was observed')
            result, changes = evaluate(event, dict(task=task, turn={"task_id": row[0], "continuation_consumed": row[1]} if row else None,
                                                   receipt={"fingerprint": receipt[0], "conflicted": receipt[1]} if receipt else None))
            if changes["generation_delta"]:
                _checkout_row(db, scope, initialize=True)
                db.execute("update checkouts set generation=generation+? where scope_id=?", (changes["generation_delta"], scope_id))
            if "receipt" in changes:
                db.execute("insert into receipts values(?,?,?,?,?,?,?,0)", (*receipt_identity, changes["receipt"]))
            if changes.get("poison_receipt"):
                db.execute("update receipts set conflicted=1 where scope_id=? and client=? and session_id=? and turn_id=? and tool_call_id=? and kind=?", receipt_identity)
            if "turn" in changes:
                db.execute("insert into turns values(?,?,?,?,?,0)", (*identity, changes["turn"]["task_id"]))
            if changes.get("consume_turn"):
                db.execute("update turns set continuation_consumed=1 where scope_id=? and client=? and session_id=? and turn_id=?", identity)
            if "task" in changes:
                _save(db, scope_id, changes["task"])
            return result
    except (StateError, KeyError, TypeError):
        if guarded_mutation(event):
            reason = ("Runtime state is missing, unsafe or incompatible; inspect task status"
                      if event.client == "codex" else
                      "Runtime state is missing, unsafe or incompatible; inspect the bound task")
            return HookResult(event.kind, "deny", reason)
        if event.kind == "Stop":
            return HookResult(event.kind)
        return HookResult(event.kind, "context", "Runtime state is unavailable; event processing and coverage are unverified")


def retire_task(scope, request):
    """Cancel one exact historical writer using retained host reconciliation evidence.

    Like D4, this binds coordinator-verified host proof; local JSON cannot
    authenticate host/operator authority or create success evidence.
    """
    _fields(request, ('client', 'session_id', 'task_id', 'scope_ref', 'expected_revision', 'expected_pins',
                      'reason', 'reference', 'stop_proof'))
    _identity(request)
    _integer(request['expected_revision'], 'expected_revision', 1)
    for field in ('reason', 'reference'):
        _text(request[field], field)
    _validate_pins(request['expected_pins'])
    from runtime.evidence import _artifact, _artifact_owner, _read_host_proof
    proof = _read_host_proof(scope, request['stop_proof'])
    _fields(proof, ('version', 'kind', 'identity', 'expected_revision', 'expected_pins', 'observed_turn_id',
                    'stopped', 'descendants_stopped', 'attempt_ids', 'observation_ref', 'coordinator_ref'))
    for field in ('observation_ref', 'coordinator_ref'):
        _text(proof[field], 'host proof ' + field)
    if (type(proof['version']) is not int or proof['version'] != 1 or proof['kind'] != 'stopped-writer-reconciliation' or
            proof['stopped'] is not True or proof['descendants_stopped'] is not True):
        raise StateError('Trusted stopped-writer and descendant reconciliation remains missing')
    with _database(scope, write=True) as db:
        if db is None:
            raise StateError('Task state has not been initialized')
        scope_id = _scope_id(scope)
        task = _task(db, scope_id, request['client'], request['session_id'], request['task_id'])
        identity = {key: task[key] for key in ('client', 'session_id', 'task_id', 'scope_ref')}
        if (identity != {key: request[key] for key in identity} or task['revision'] != request['expected_revision'] or
                task['pins'] != request['expected_pins'] or task['pins']['schema_version'] != _scope_version(scope) or
                'retirement' in task):
            raise StateError('Retirement requires exact supported stored identity, pins and revision')
        _guard_assignments(db, scope, request['client'], request['session_id'])
        attempts = [a['id'] for a in task.get('evidence', {}).get('attempts', []) if a['status'] in {'reserved', 'running', 'uncertain'}]
        if (proof['identity'] != identity or proof['expected_revision'] != task['revision'] or proof['expected_pins'] != task['pins'] or
                proof['observed_turn_id'] != task['turn_id'] or proof['attempt_ids'] != attempts):
            raise StateError('Stopped-writer proof does not match exact historical task and attempts')
        retained_proof = _artifact(scope, proof, owner=_artifact_owner(scope, task), db=db)
        task.update(state='cancelled', reason=request['reason'], reference=request['reference'],
                    retirement=dict(proof_digest=request['stop_proof']['sha256'], proof=retained_proof, observation_ref=proof['observation_ref'],
                                    coordinator_ref=proof['coordinator_ref'], previous_revision=task['revision']))
        for condition in task['conditions']:
            if 'continuation' in condition:
                condition['continuation']['revoked'] = True
        task['revision'] += 1
        _save(db, scope_id, task)
    return dict(ok=True, task=task, limitations=['Cancellation only; host-proof authority is coordinator-verified, not authenticated by local JSON'])
