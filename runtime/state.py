"""Private, bounded SQLite task controls and atomic deterministic hook decisions."""

from contextlib import closing, contextmanager
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import stat
from types import MappingProxyType

from runtime.engine import HookResult, evaluate
from runtime.startup import (StartupError, AcceptedScope, RuntimeSettings, PROJECT_FILE, json_object, _canonical_plain,
    _canonical_path, _canonical_binding, _canonical_ref, _canonical_hash)


SCHEMA_VERSION = 2
APPLICATION_ID = 0x56494245
PACKAGE = Path(__file__).resolve().parents[1]
LIMITATIONS = ["Supported apply_patch guard only; shell and external edits remain possible",
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
CANONICAL_TABLE_SQL = TABLE_SQL | {"checkouts": TABLE_SQL["checkouts"][:-1] + ", physical_identity TEXT NOT NULL)"}
TABLES = set(TABLE_SQL)


class StateError(StartupError):
    """Sanitized task/state diagnostic, without private record contents."""


def runtime_fingerprint():
    """Pin installed runtime sources, dispatcher and adapter contents, by relative path."""
    digest = hashlib.sha256()
    paths = sorted((PACKAGE / "runtime").glob("*.py")) + sorted((PACKAGE / "runtime/adapters").glob("*.py"))
    paths.append(PACKAGE / "scripts/workflow.py")
    for path in sorted(paths):
        digest.update(str(path.relative_to(PACKAGE)).encode() + b"\0" + path.read_bytes() + b"\0")
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


def _identity(request):
    for name in ("client", "session_id", "task_id", "scope_ref"):
        _text(request.get(name), name, 128 if name == "task_id" else 1024)
    if request["client"] != "codex":
        raise StateError("Unsupported task client")


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
    tables = TABLES - {"assignments"} if version == 1 else TABLES
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
        elif kind != "index" or sql is not None:
            raise StateError("Runtime database contains unsupported schema objects")


def _initialize(path, *, version=SCHEMA_VERSION):
    missing = []
    directory = path.parent
    while not directory.exists():
        missing.append(directory)
        directory = directory.parent
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            _private(directory, True)
    _private(path.parent, True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(descriptor)
    with closing(sqlite3.connect(path, timeout=0.1)) as db, db:
        db.executescript("BEGIN IMMEDIATE;\n" + ";\n".join((CANONICAL_TABLE_SQL if version == 3 else TABLE_SQL).values()) + ";")
        db.execute("pragma application_id=" + str(APPLICATION_ID))
        db.execute("pragma user_version=" + str(version))


@contextmanager
def _database(scope, write=False, initialize=False):
    db = None
    try:
        path = _path(scope)
        if not os.path.lexists(path):
            if initialize:
                try:
                    _initialize(path, version=_scope_version(scope))
                except FileExistsError:
                    pass
            else:
                yield None
                return
        _sidecars(path)
        db = sqlite3.connect(path.as_uri() + ("?mode=rw" if write else "?mode=ro"), uri=True, timeout=0.1)
        db.execute("pragma busy_timeout=100")
        db.execute("pragma trusted_schema=off")
        _schema(db, version=_scope_version(scope))
        db.execute("begin immediate" if write else "begin")
        yield db
        if write:
            _sidecars(path)
            db.commit()
    except StateError:
        raise
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        raise StateError("Runtime state is unavailable, corrupt, locked or incompatible") from None
    finally:
        if db is not None:
            db.close()


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
        raise StateError("Runtime task binding is corrupt")
    version = db.execute("pragma user_version").fetchone()[0]
    task = json_object(row[0], limit=4 * 1024 * 1024) if version == 3 else json.loads(row[0])
    _fields(task, ("client", "session_id", "task_id", "scope_ref", "mode", "decision_ref", "state", "revision",
                   "pins", "reason", "reference", "conditions", "turn_id", "turn_uncertain", *(["accepted_identity"] if version == 3 else [])), ("resolution_ref", "evidence", "retirement", "delegation"))
    _identity(task)
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
        validate_evidence(task["evidence"])
    if "delegation" in task:
        from runtime.delegation import validate_delegation
        validate_delegation(task["delegation"])
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
            if old["accepted_identity"] != task["accepted_identity"] or old["pins"] != task["pins"]:
                raise StateError("Stored task identity and pins are immutable")
    if "delegation" in task:
        from runtime.delegation import validate_delegation
        validate_delegation(task["delegation"])
    if 'evidence' in task:
        from runtime.evidence import validate_evidence
        validate_evidence(task['evidence'])
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
    if client != "codex":
        raise StateError("Unsupported task client")
    from runtime.evidence import revalidate_ready
    revalidate_ready(scope, client, session_id)
    with _database(scope) as db:
        return _status(db, scope, client, session_id)


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
    _identity(request)
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
    with _database(scope, write=True, initialize=True) as db:
        scope_id = _scope_id(scope)
        _checkout_row(db, scope, initialize=True)
        current = _task(db, scope_id, request["client"], request["session_id"])
        if current and current["task_id"] == request["task_id"]:
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
            current["revision"] += 1
            for condition in current["conditions"]:
                if "continuation" in condition:
                    condition["continuation"]["revoked"] = True
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
    _identity(request)
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
        if isinstance(scope, AcceptedScope) and event.client != scope.client:
            raise StateError("Event client differs from accepted scope")
        with _database(scope, write=True) as db:
            if db is None:
                raise StateError("Task state has not been initialized")
            scope_id = _scope_id(scope)
            _checkout_row(db, scope)
            task = _task(db, scope_id, event.client, event.session_id)
            _compatible(scope, task)
            identity = (scope_id, event.client, event.session_id, event.turn_id)
            row = db.execute("select task_id,continuation_consumed from turns where scope_id=? and client=? and session_id=? and turn_id=?", identity).fetchone() if event.turn_id else None
            receipt_identity = (*identity, event.tool_call_id, event.kind)
            receipt = db.execute("select fingerprint,conflicted from receipts where scope_id=? and client=? and session_id=? and turn_id=? and tool_call_id=? and kind=?", receipt_identity).fetchone() if event.turn_id and event.tool_call_id else None
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
        if event.kind == "PreToolUse" and event.tool_name == "apply_patch":
            return HookResult(event.kind, "deny", "Runtime state is missing, unsafe or incompatible; inspect task status")
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
    from runtime.evidence import _artifact, _read_host_proof
    proof = _read_host_proof(scope, request['stop_proof'])
    _fields(proof, ('version', 'kind', 'identity', 'expected_revision', 'expected_pins', 'observed_turn_id',
                    'stopped', 'descendants_stopped', 'attempt_ids', 'observation_ref', 'coordinator_ref'))
    for field in ('observation_ref', 'coordinator_ref'):
        _text(proof[field], 'host proof ' + field)
    if (type(proof['version']) is not int or proof['version'] != 1 or proof['kind'] != 'stopped-writer-reconciliation' or
            proof['stopped'] is not True or proof['descendants_stopped'] is not True):
        raise StateError('Trusted stopped-writer and descendant reconciliation remains missing')
    retained_proof = _artifact(scope, proof)
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
        task.update(state='cancelled', reason=request['reason'], reference=request['reference'],
                    retirement=dict(proof_digest=request['stop_proof']['sha256'], proof=retained_proof, observation_ref=proof['observation_ref'],
                                    coordinator_ref=proof['coordinator_ref'], previous_revision=task['revision']))
        for condition in task['conditions']:
            if 'continuation' in condition:
                condition['continuation']['revoked'] = True
        task['revision'] += 1
        _save(db, scope_id, task)
    return dict(ok=True, task=task, limitations=['Cancellation only; host-proof authority is coordinator-verified, not authenticated by local JSON'])
