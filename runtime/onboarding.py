"""Bounded, private D3 review plans. No enrollment, retrieval, or project execution."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import stat
import subprocess
import time
import uuid

from runtime.startup import StartupError, checkout, json_object, policy_digest
from runtime.state import runtime_fingerprint


PACKAGE = Path(__file__).resolve().parents[1]
MAX_REQUEST = 2 * 1024 * 1024
MAX_PLAN = 4 * 1024 * 1024
MAX_FILE = 1024 * 1024
MAX_TOTAL = 8 * 1024 * 1024
MAX_PATHS = 4096
HEX = re.compile(r"[0-9a-f]{64}\Z")
CHECKOUT_INPUTS = ("repository_root", "git_common_dir", "head", "index_digest", "dirty_inventory", "paths")
LIMITS = ["Helpers do not authenticate source ownership, trust, catalog semantics, or agent evidence.",
          "Structural checks do not qualify client execution, enrollment, approval, or merge readiness.",
          "No project commands run; missing baseline and client observations remain agent-recorded gaps."]


def _require(condition, message):
    if not condition:
        raise StartupError(message)


def _object(value, required, optional=()):
    _require(isinstance(value, dict) and set(required) <= value.keys()
             and value.keys() <= set(required) | set(optional), "Invalid onboarding object fields")


def _text(value, empty=False):
    _require(isinstance(value, str) and (empty or bool(value.strip()))
             and len(value) <= 65536 and "\x00" not in value, "Invalid onboarding text")
    return value


def _strings(value, empty=True):
    _require(isinstance(value, list) and len(value) <= MAX_PATHS
             and (empty or bool(value)), "Invalid onboarding list")
    for item in value:
        _text(item)
    _require(len(value) == len(set(value)), "Duplicate onboarding reference")
    return value


def _relative(value):
    _text(value)
    path = PurePosixPath(value)
    _require(not path.is_absolute() and str(path) == value and ".." not in path.parts
             and value != "." and not any(ord(c) < 32 for c in value), "Invalid relative target/source path")
    return value


def _hash(value):
    _require(isinstance(value, str) and HEX.fullmatch(value), "Invalid content hash")
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode()).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat()


def read_request(raw, limit=MAX_REQUEST):
    """Use startup's strict parser for small inputs; retain its rules for larger artifacts."""
    _require(isinstance(raw, bytes) and len(raw) <= limit, "Onboarding JSON size limit exceeded")
    if len(raw) <= 128 * 1024:
        return json_object(raw)

    def unique(pairs):
        value = {}
        for key, item in pairs:
            _require(key not in value, "Duplicate JSON field")
            value[key] = item
        return value

    def invalid_number(_):
        raise StartupError("Non-JSON number")

    result = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_number)
    _require(isinstance(result, dict), "Expected a JSON object")
    return result


def _bounded(value):
    """Bound direct Python callers as well as CLI input; reject private raw record categories."""
    raw = json.dumps(value, allow_nan=False).encode()
    _require(len(raw) <= MAX_REQUEST, "Onboarding request size limit exceeded")
    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        _require(depth <= 30, "Onboarding nesting limit exceeded")
        if isinstance(item, dict):
            _require(all(isinstance(key, str) for key in item), "Expected string object keys")
            _require(not {key.lower() for key in item} & {
                "credentials", "password", "access_token", "api_key", "environment", "transcript",
                "raw_environment", "raw_output", "secret"}, "Use sanitized summaries, never private raw data")
            stack.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            _require(len(item) <= MAX_PATHS, "Onboarding list limit exceeded")
            stack.extend((v, depth + 1) for v in item)
        elif isinstance(item, str):
            _text(item, empty=True)
        else:
            _require(item is None or type(item) in (bool, int, float), "Invalid onboarding value")


def _no_links(path):
    for item in (path, *path.parents):
        if os.path.lexists(item):
            _require(not item.is_symlink(), "Onboarding paths must not contain links")


def _private(st, directory=False):
    _require((stat.S_ISDIR(st.st_mode) if directory else stat.S_ISREG(st.st_mode))
             and st.st_uid == os.getuid() and st.st_mode & 0o077 == 0
             and (directory or st.st_nlink == 1), "Onboarding files must be private, owned, regular and unlinked")


def _git(root, *args):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    process = subprocess.Popen(["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(root),
                                *args], env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    output = bytearray()
    deadline = time.monotonic() + 5
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise subprocess.TimeoutExpired("read-only Git inventory", 5)
                raw = os.read(process.stdout.fileno(), min(65536, MAX_FILE + 1 - len(output)))
                if not raw:
                    break
                output.extend(raw)
                _require(len(output) <= MAX_FILE, "Git inventory limit exceeded; narrow the checkout before planning")
        return process.wait(timeout=max(0.01, deadline - time.monotonic())), bytes(output)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()


def _plan_path(value):
    _require(os.name == "posix", "Onboarding requires a qualified POSIX filesystem")
    path = Path(value)
    _require(path.is_absolute() and str(path.resolve()) == str(path),
             "Plan directory must be absolute and canonical")
    _no_links(path)
    _require(not path.is_relative_to(PACKAGE), "Plan directory must be outside the installed package")
    for ancestor in (path, *path.parents):
        _require(not os.path.lexists(ancestor / ".git") and ancestor.name not in {
            ".codex", ".claude", ".agents", ".cursor", "skills", "instructions", "plugins"},
            "Plan directory must be outside repositories, plugin caches and instruction discovery paths")
    existing = next((p for p in (path, *path.parents) if p.exists()), None)
    _require(existing is not None and existing.is_dir(), "Plan directory parent must exist")
    code, _ = _git(existing, "-c", "safe.bareRepository=all", "rev-parse", "--absolute-git-dir")
    _require(code != 0, "Plan directory must be outside repositories")
    if not path.exists():
        _require(path.parent.is_dir(), "Plan directory parent must exist")
        path.mkdir(mode=0o700)
    _private(path.stat(), directory=True)
    return path


@contextmanager
def _locked(value):
    import fcntl
    path = _plan_path(value)
    directory = _open_path(path, os.O_RDONLY | os.O_DIRECTORY)
    lock = None
    try:
        _private(os.fstat(directory), directory=True)
        lock = os.open(".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                       0o600, dir_fd=directory)
        _private(os.fstat(lock))
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise StartupError("Onboarding plan busy; retry the same expected revision") from None
        yield path, directory
    finally:
        if lock is not None:
            os.close(lock)
        os.close(directory)


def _open_path(path, flags):
    """Resolve every component with no-follow descriptors, closing symlink-swap races."""
    path = Path(path)
    _require(path.is_absolute(), "Expected an absolute onboarding path")
    parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        return os.open(path.name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)


def _read_file(path, limit, private=False):
    descriptor = _open_path(path, os.O_RDONLY)
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if private:
            _private(metadata)
        _require(stat.S_ISREG(metadata.st_mode), "Expected a regular onboarding input file")
        _require(metadata.st_size <= limit, "Onboarding file size limit exceeded")
        raw = stream.read(limit + 1)
        _require(len(raw) <= limit, "Onboarding file size limit exceeded")
        return raw


def _load(path):
    if not os.path.lexists(path / "plan.json"):
        return None
    try:
        plan = read_request(_read_file(path / "plan.json", MAX_PLAN, private=True), MAX_PLAN)
    except OSError:
        raise StartupError("Plan record must be a private regular file without links") from None
    _object(plan, ("schema_version", "plan_id", "revision", "created_at", "identity", "package_pins",
        "sources", "requirements", "inventory", "decisions", "coverage", "actions", "evidence",
        "semantic_assessment", "invalidations", "decision_history", "recovery_requirement", "status",
        "blockers", "verified_at", "review_digest", "current_input_digest", "evidence_limits"))
    _require(plan.get("schema_version") == 1 and type(plan.get("revision")) is int
             and plan["revision"] >= 1, "Unsupported onboarding plan")
    return plan


def _save(plan, path, directory):
    raw = json.dumps(plan, sort_keys=True, indent=2, ensure_ascii=True).encode() + b"\n"
    _require(len(raw) <= MAX_PLAN, "Onboarding artifact size limit exceeded; plan remains unchanged")
    if os.path.lexists(path / "plan.json"):
        _private((path / "plan.json").lstat())
    name = ".plan-" + uuid.uuid4().hex
    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, "plan.json", src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        if os.path.lexists(path / name):
            os.unlink(name, dir_fd=directory)


def _source_record(record, path):
    _bounded(record)
    _object(record, ("schema_version", "clients", "toolkit", "required_sources"))
    _require(type(record["schema_version"]) is int and record["schema_version"] == 1,
             "Unsupported onboarding source schema")
    _strings(record["clients"], empty=False)
    for client in record["clients"]:
        _require(client in ("codex", "claude-code")
                 and (PACKAGE / "clients" / (client + ".md")).is_file(), "Unknown selected native client")
    toolkit = record["toolkit"]
    _object(toolkit, ("commit", "origin", "acquisition", "provenance", "trust", "files", "catalog"))
    _require(isinstance(toolkit["commit"], str) and re.fullmatch(r"[0-9a-f]{40}", toolkit["commit"]),
             "Expected a pinned Toolkit commit")
    for field in ("origin", "provenance"):
        _text(toolkit[field])
    _require(toolkit["acquisition"] in ("online", "offline") and toolkit["trust"] in ("recorded", "pending"),
             "Invalid source acquisition/provenance status")
    _require(isinstance(toolkit["files"], list) and isinstance(toolkit["catalog"], list)
             and len(toolkit["files"]) <= MAX_PATHS and len(toolkit["catalog"]) <= MAX_PATHS,
             "Invalid source manifest/catalog")
    paths = set()
    for item in toolkit["files"]:
        _object(item, ("path", "local_path", "sha256", "required"))
        _relative(item["path"])
        _require(item["path"] not in paths, "Duplicate source path")
        paths.add(item["path"])
        _hash(item["sha256"])
        _require(type(item["required"]) is bool, "Expected source requirement boolean")
        local = Path(_text(item["local_path"]))
        _require(local.is_absolute() and local.is_relative_to(path) and local != path
                 and str(local.resolve()) == str(local) and local.name not in {"plan.json", ".lock"}
                 and not local.name.startswith(".plan-"), "Retain source material inside the private plan directory")
    for name in _strings(record["required_sources"], empty=False):
        _relative(name)
    ids = set()
    for row in toolkit["catalog"]:
        _object(row, ("id", "source", "section", "stage", "mandatory", "dependencies"))
        for field in ("id", "source", "section", "stage"):
            _text(row[field])
        _require(not row["id"].startswith("policy:") and row["id"] not in ids,
                 "Duplicate or reserved catalog ID")
        ids.add(row["id"])
        _require(row["stage"] in ("installation", "project_onboarding", "runtime"),
                 "Invalid catalog lifecycle stage")
        _require(row["source"] in paths or row["source"] in record["required_sources"],
                 "Catalog row must reference a declared source")
        _require(type(row["mandatory"]) is bool, "Expected catalog mandatory boolean")
        _strings(row["dependencies"])
    _dependencies(toolkit["catalog"], ids)


def _dependencies(rows, ids):
    for row in rows:
        _strings(row["dependencies"])
    remaining = {r["id"]: set(r["dependencies"]) for r in rows}
    _require(all(deps <= ids and key not in deps for key, deps in remaining.items()),
             "Unknown or self-referencing dependency")
    while remaining:
        ready = {key for key, deps in remaining.items() if not deps}
        _require(bool(ready), "Cyclic onboarding dependencies")
        remaining = {key: deps - ready for key, deps in remaining.items() if key not in ready}


def _sources(record):
    observed = {}
    total = 0
    for item in record["toolkit"]["files"]:
        if total >= MAX_TOTAL:
            observed[item["path"]] = {"status": "source_total_limit"}
            continue
        try:
            raw = _read_file(Path(item["local_path"]), min(MAX_FILE, MAX_TOTAL - total), private=True)
            total += len(raw)
            _require(total <= MAX_TOTAL, "Retained source total size limit exceeded")
            observed[item["path"]] = {"sha256": hashlib.sha256(raw).hexdigest(), "status": "read",
                                      "bytes": len(raw)}
        except (OSError, StartupError):
            observed[item["path"]] = {"status": "unavailable"}
    return observed


def _fingerprint(root, relative):
    path = root / relative
    try:
        _no_links(path)
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode):
            return {"status": "special"}
        if path.name == ".env" or path.name.startswith(".env.") or path.suffix in {
                ".pem", ".key", ".p12", ".pfx"}:
            return {"status": "excluded", "reason": "potential secret file"}
        if st.st_size > MAX_FILE:
            return {"status": "oversized"}
        raw = _read_file(path, MAX_FILE)
        return {"status": "read", "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    except FileNotFoundError:
        return {"status": "absent"}
    except (OSError, StartupError):
        return {"status": "unreadable_or_link"}


def _file_targets(actions):
    _require(isinstance(actions, list) and len(actions) <= MAX_PATHS, "Invalid proposed actions")
    targets = []
    for action in actions:
        _require(isinstance(action, dict), "Invalid proposed action")
        if action.get("kind") in ("write", "delete"):
            targets.append(_relative(action.get("target")))
    return targets


def _snapshot(root, targets=()):
    identity = checkout(root)
    _require(identity is not None and identity[0] == root, "Selected checkout identity changed")
    code, raw = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    _require(code == 0, "Cannot enumerate checkout files")
    names = sorted(set(os.fsdecode(name) for name in raw.split(b"\x00") if name))
    _require(len(names) <= MAX_PATHS, "Checkout path limit exceeded; inventory remains incomplete")
    fingerprints = {}
    total = 0
    for name in names:
        _relative(name)
        fingerprints[name] = _fingerprint(root, name)
        total += fingerprints[name].get("bytes", 0)
        _require(total <= MAX_TOTAL, "Checkout byte limit exceeded; inventory remains incomplete")
    instructions = []
    directories = {root, *root.parents}
    for name in [*names, *targets]:
        directory = (root / name).parent
        while directory.is_relative_to(root):
            directories.add(directory)
            if directory == root:
                break
            directory = directory.parent
    _require(len(directories) <= MAX_PATHS, "Instruction scope limit exceeded")
    for directory in sorted(directories):
        for name in ("AGENTS.md", "AGENTS.override.md", "CLAUDE.md", ".github/copilot-instructions.md"):
            location = directory / name
            key = "instruction:" + str(location)
            fingerprints[key] = _fingerprint(directory, name)
            if fingerprints[key]["status"] != "absent":
                instructions.append({"path": str(location), "scope": str(directory),
                                     "editable": location.is_relative_to(root)})
    code, index = _git(root, "ls-files", "--stage", "-z")
    _require(code == 0, "Cannot read staged checkout identity")
    code, status = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    _require(code == 0, "Cannot read checkout changes")
    code, head = _git(root, "rev-parse", "--verify", "HEAD")
    return {"repository_root": str(root), "git_common_dir": str(identity[1]),
            "head": head.decode("ascii").strip() if code == 0 else None,
            "index_digest": hashlib.sha256(index).hexdigest(),
            "dirty_inventory": [os.fsdecode(v) for v in status.split(b"\x00") if v],
            "paths": names, "fingerprints": fingerprints, "instructions": instructions}


def _package_pins():
    return {"policy_digest": policy_digest(PACKAGE), "runtime_digest": runtime_fingerprint()}


def _requirements(record):
    rows = [dict(row) for row in record["toolkit"]["catalog"]]
    for path in sorted((PACKAGE / "policies").glob("*.md")):
        if path.name == "00-index.md":
            continue
        rows.append({"id": "policy:" + path.stem, "source": "policies/" + path.name,
                     "section": "complete contract", "stage": "project_onboarding", "mandatory": True,
                     "dependencies": []})
    return rows


def _block(scope, reason, resumption):
    return {"scope": scope, "reason": reason, "resumption": resumption}


def _source_blockers(plan, observed):
    record = plan["sources"]["declared"]
    blockers = []
    if record["toolkit"]["trust"] != "recorded":
        blockers.append(_block("sources", "Source trust/provenance remains pending",
                               "Record explicitly trusted pinned retrieval/copy evidence"))
    required = set(record["required_sources"]) | {
        f["path"] for f in record["toolkit"]["files"] if f["required"]}
    declared = {f["path"]: f for f in record["toolkit"]["files"]}
    for name in sorted(required | {r["source"] for r in record["toolkit"]["catalog"]}):
        if name not in declared or observed.get(name, {}).get("sha256") != declared[name]["sha256"]:
            blockers.append(_block("source:" + name, "Pinned source missing, changed, unsafe or over limit",
                                   "Retain the same pinned source with matching declared hash"))
    if not record["toolkit"]["catalog"]:
        blockers.append(_block("catalog", "Complete upstream catalog is missing", "Discover complete pinned catalog"))
    return blockers


def _current(plan):
    root = Path(plan["identity"]["repository_root"])
    snapshot = _snapshot(root, _file_targets(plan["actions"]))
    sources = _sources(plan["sources"]["declared"])
    package = _package_pins()
    changes = []
    previous = plan["identity"]
    for key in CHECKOUT_INPUTS:
        if snapshot[key] != previous[key]:
            changes.append("checkout:" + key)
    old, new = previous["fingerprints"], snapshot["fingerprints"]
    changes.extend(key for key in sorted(old.keys() | new.keys()) if old.get(key) != new.get(key))
    for name in sorted(plan["sources"]["observed"].keys() | sources.keys()):
        if plan["sources"]["observed"].get(name) != sources.get(name):
            changes.append("source:" + name)
    if package != plan["package_pins"]:
        changes.append("package")
    for action in plan["actions"]:
        if action["kind"] in ("write", "delete"):
            actual = _fingerprint(root, action["target"])
            expected = "absent" if actual["status"] == "absent" else actual.get("sha256")
            if expected != action["before"]:
                changes.append(action["target"])
    current = {"identity": snapshot | {"clients": previous["clients"]},
               "sources": sources, "package_pins": package}
    return sorted(set(changes)), sources, current


def _remember_decision(plan, decision):
    entry = {"revision": plan["revision"], "decision": deepcopy(decision)}
    if entry not in plan["decision_history"]:
        plan["decision_history"].append(entry)


def _invalidate(plan, changes):
    if not changes:
        return
    affected = []
    for decision in plan["decisions"]:
        if set(decision["invalidate_on"]) & set(changes) or "package" in changes:
            if decision["disposition"] != "pending":
                _remember_decision(plan, decision)
                decision["disposition"] = "pending"
            affected.append(decision["id"])
    entry = {"at": _now(), "revision": plan["revision"], "changed_inputs": changes,
             "decisions": affected, "actions": [a["id"] for a in plan["actions"]
                 if a["target"] in changes or set(a["decision_ids"]) & set(affected) or "package" in changes]}
    if not plan["invalidations"] or plan["invalidations"][-1].get("changed_inputs") != changes:
        plan["invalidations"].append(entry)


def _review_digest(plan):
    return _digest({key: plan[key] for key in (
        "identity", "package_pins", "sources", "inventory", "decisions", "coverage", "actions", "evidence",
        "semantic_assessment")})


def _finish(plan, sources, changes, blockers, draft=False, current=None):
    blockers = _source_blockers(plan, sources) + blockers
    pending = [d for d in plan["decisions"] if d["disposition"] in ("pending", "proposed")]
    if changes:
        blockers = [_block(name, "Pinned input changed; dependent assessment is stale",
                           "Reinspect affected inputs and reconcile this plan with current_input_digest; restore changed sources to their pinned hashes")
                    for name in changes] + blockers
        status = "stale"
    elif pending:
        status = "awaiting_decision"
    elif blockers:
        status = "blocked"
    elif draft:
        status = "draft"
    else:
        status = "ready_for_review"
    current = current or {"identity": plan["identity"], "sources": sources, "package_pins": plan["package_pins"]}
    plan.update(status=status, blockers=blockers, verified_at=_now(), review_digest=_review_digest(plan),
                current_input_digest=_digest(current))
    limits = list(LIMITS)
    if plan["sources"]["declared"]["toolkit"]["acquisition"] == "offline":
        limits.append("Offline source freshness is unverified; declared commit/hash is not current upstream proof.")
    plan["evidence_limits"] = limits
    return {"plan_id": plan["plan_id"], "revision": plan["revision"], "status": status,
            "blockers": blockers, "next_decision": pending[0] if pending else None,
            "evidence_limits": limits, "review_digest": plan["review_digest"], "current_input_digest": plan["current_input_digest"],
            "exit_code": 0 if status == "ready_for_review" else 2}


def inspect_project(cwd, plan_dir, source_record):
    """Pin one explicitly selected checkout and declared retained source bundle."""
    _require(Path(cwd).is_absolute(), "Select an absolute target checkout")
    identity = checkout(Path(cwd))
    _require(identity is not None, "Onboarding prerequisite: select an existing Git checkout; do not initialize one")
    root, _ = identity
    with _locked(plan_dir) as (path, directory):
        _source_record(source_record, path)
        plan = _load(path)
        if plan is None:
            snapshot = _snapshot(root)
            sources = _sources(source_record)
            plan = {"schema_version": 1, "plan_id": uuid.uuid4().hex, "revision": 1,
                    "created_at": _now(), "identity": snapshot | {"clients": source_record["clients"]},
                    "package_pins": _package_pins(),
                    "sources": {"declared": source_record, "observed": sources},
                    "requirements": _requirements(source_record), "inventory": {}, "decisions": [],
                    "coverage": [], "actions": [], "evidence": [], "semantic_assessment": {},
                    "invalidations": [], "decision_history": [], "recovery_requirement": "D4 must back up privately and journal before apply"}
            report = _finish(plan, sources, [], [], draft=True)
        else:
            _require(plan["identity"]["repository_root"] == str(root), "Plan belongs to another selected checkout")
            _require(plan["sources"]["declared"] == source_record,
                     "Pinned sources/clients cannot change on resume; start a new plan directory")
            changes, sources, current = _current(plan)
            _invalidate(plan, changes)
            plan["revision"] += 1
            blockers = _validate_proposal(plan) if plan["semantic_assessment"] else []
            report = _finish(plan, sources, changes, blockers, draft=not bool(plan["semantic_assessment"]), current=current)
        _save(plan, path, directory)
        return report


def _rows(value, fields):
    _require(isinstance(value, list) and len(value) <= MAX_PATHS, "Invalid onboarding rows")
    ids = set()
    for row in value:
        _object(row, fields)
        _text(row["id"])
        _require(row["id"] not in ids, "Duplicate onboarding row ID")
        ids.add(row["id"])
    return ids


def _validate_proposal(plan):
    """Validate references and concrete review targets; semantic findings remain agent assertions."""
    inventory = plan["inventory"]
    names = ("product", "critical_flows", "stack", "documents", "quality_commands", "services",
             "client_capabilities", "merge_feasibility", "instructions", "integrations")
    _object(inventory, names)
    _require(isinstance(inventory["documents"], dict) and len(inventory["documents"]) == 9,
             "Map all nine canonical document destinations from the pinned manifest")
    for document in inventory["documents"].values():
        _object(document, ("path", "reason"))
        _text(document["reason"])
        if document["path"] is not None:
            _relative(document["path"])
    fact_records = []
    for key in set(names) - {"documents"}:
        _object(inventory[key], ("facts", "assumptions"))
        _require(isinstance(inventory[key]["facts"], list), "Inventory facts must be a list")
        _strings(inventory[key]["assumptions"])
        for fact in inventory[key]["facts"]:
            _object(fact, ("summary", "evidence"))
            _text(fact["summary"])
            _strings(fact["evidence"])
            fact_records.append((key, fact))
    evidence_ids = _rows(plan["evidence"], ("id", "kind", "summary", "scope", "inputs", "reference"))
    fingerprints = plan["identity"]["fingerprints"]
    input_keys = set(fingerprints) | {"checkout:" + key for key in CHECKOUT_INPUTS} | {"package"} | {
        "source:" + name for name in plan["sources"]["observed"]}
    evidence = {row["id"]: row for row in plan["evidence"]}
    for row in evidence.values():
        _require(row["kind"] in ("observation", "behavior", "configuration", "baseline", "authorization"),
                 "Invalid evidence kind")
        for field in ("summary", "scope", "reference"):
            _text(row[field])
        _require(set(_strings(row["inputs"])) <= input_keys, "Unknown evidence input fingerprint")
    action_ids = _rows(plan["actions"], ("id", "dependencies", "kind", "target", "section", "before", "text",
        "after", "scope", "authorization", "verification", "preservation_exceptions", "decision_ids", "backup_required"))
    decision_ids = _rows(plan["decisions"], ("id", "rule", "source", "scope", "options", "recommendation",
        "selected", "disposition", "provenance", "evidence", "affected_actions", "invalidate_on", "conflict", "mode"))
    coverage_ids = _rows(plan["coverage"], ("id", "source", "section", "stage", "mandatory", "dependencies",
        "applicability", "reason", "current_adoption", "qualification_evidence", "outcome", "actions", "scope",
        "risk", "verification", "blocker", "resumption", "decision_ids"))
    blockers = []
    for key, fact in fact_records:
        _require(set(fact["evidence"]) <= evidence_ids, "Unknown inventory evidence reference")
        if not fact["evidence"]:
            blockers.append(_block("inventory:" + key, "Observed facts need evidence references",
                                   "Supply sanitized observation evidence on pinned inputs"))
    for decision in plan["decisions"]:
        for field in ("rule", "source", "scope", "recommendation", "provenance"):
            _text(decision[field])
        options = _strings(decision["options"], empty=False)
        _require(decision["recommendation"] in options and decision["disposition"] in (
            "confirmed", "inherited", "proposed", "pending"), "Invalid decision disposition/recommendation")
        _require(decision["selected"] is None or decision["selected"] in options, "Unknown decision selection")
        _require(decision["disposition"] not in ("confirmed", "inherited") or decision["selected"] is not None,
                 "Confirmed decisions need a selected value")
        _require(type(decision["conflict"]) is bool and decision["mode"] in (None, "decide", "preserve", "replace"),
                 "Invalid scoped conflict mode")
        _require(decision["conflict"] or decision["mode"] is None, "A mode requires an actual scoped conflict")
        for field, allowed in (("evidence", evidence_ids), ("affected_actions", action_ids), ("invalidate_on", input_keys)):
            _require(set(_strings(decision[field])) <= allowed, "Unknown decision reference")
        if decision["disposition"] == "inherited" and not decision["evidence"]:
            blockers.append(_block(decision["id"], "Inherited choice lacks evidence", "Record its scoped provenance evidence"))
        if decision["conflict"] and decision["mode"] is None:
            blockers.append(_block(decision["id"], "Conflict needs a scoped mode/resolution", "Obtain the missing material decision"))
    decisions = {d["id"]: d for d in plan["decisions"]}
    _dependencies(plan["actions"], action_ids)
    seen = set()
    completed = set()
    for action in plan["actions"]:
        _strings(action["dependencies"])
        _require(set(action["dependencies"]) <= completed, "Actions must be in dependency order")
        completed.add(action["id"])
        _require(action["kind"] in ("write", "delete", "command", "external"), "Unknown proposed action kind")
        _require(action["scope"] in ("checkout", "shared", "global") and action["backup_required"] is True,
                 "Actions require explicit scope and D4 recovery")
        for field in ("target", "authorization", "verification"):
            _text(action[field])
        _strings(action["preservation_exceptions"])
        _require(set(_strings(action["decision_ids"])) <= decision_ids, "Unknown action decision")
        _require(action["section"] is None or isinstance(action["section"], str), "Invalid owned section")
        location = (action["scope"], action["target"])
        if location in seen:
            blockers.append(_block(action["id"], "Proposed actions overlap or duplicate an integration",
                                   "Merge section edits into one full-postimage action per owned file/resource"))
        seen.add(location)
        if action["kind"] in ("write", "delete"):
            _require(action["scope"] == "checkout", "External/shared file changes require a separately scoped external proposal")
            _relative(action["target"])
            _require(action["before"] == "absent" or (isinstance(action["before"], str) and HEX.fullmatch(action["before"])),
                     "File actions need exact before hash/absence")
            if action["kind"] == "write":
                # Text is the full postimage; section describes authorized scope for D4 review.
                _text(action["text"], empty=True)
                _hash(action["after"])
                _require(hashlib.sha256(action["text"].encode()).hexdigest() == action["after"],
                         "Proposed text does not match after hash")
            else:
                _require(action["text"] is None and action["after"] == "absent"
                         and action["section"] is None, "Delete must own one entire existing path")
        else:
            _require(action["section"] is None and action["after"] is None,
                     "External/command actions cannot assert a deterministic file result")
            _require(action["before"] is None, "External preconditions belong in scoped evidence")
            if action["kind"] == "command":
                _require(isinstance(action["text"], list) and 0 < len(action["text"]) <= MAX_PATHS,
                         "Expected a bounded exact argv vector")
                for argument in action["text"]:
                    _text(argument)
            else:
                _text(action["text"])
            if not any(e["kind"] == "authorization" and e["scope"] == action["scope"]
                       for e in evidence.values()):
                blockers.append(_block(action["id"], "External action lacks scoped authorization evidence",
                                       "Record authorization for that resource; no execution occurs in D3"))
    requirements = {r["id"]: r for r in plan["requirements"]}
    _require(coverage_ids <= requirements.keys(), "Unknown coverage component/policy ID")
    for missing in sorted(requirements.keys() - coverage_ids):
        blockers.append(_block(missing, "Coverage assessment is missing", "Assess this pinned catalog/policy row"))
    for row in plan["coverage"]:
        requirement = requirements[row["id"]]
        _require(all(row[key] == requirement[key] for key in requirement),
                 "Coverage must retain pinned requirement metadata")
        _require(row["applicability"] in ("applicable", "inapplicable") and row["current_adoption"] in (
            "absent", "configured", "qualified") and row["outcome"] in ("planned", "reuse", "omit", "blocked"),
                 "Unknown coverage assessment value")
        for field in ("reason", "blocker", "resumption"):
            _text(row[field], empty=True)
        for field in ("scope", "risk", "verification"):
            _text(row[field])
        for field, allowed in (("actions", action_ids), ("qualification_evidence", evidence_ids), ("decision_ids", decision_ids)):
            _require(set(_strings(row[field])) <= allowed, "Unknown coverage reference")
        problem = None
        if not row["reason"]:
            problem = "Applicability/optional omission needs an explicit reason"
        elif row["mandatory"] and row["outcome"] == "omit":
            problem = "Mandatory adoption cannot be omitted by runtime inapplicability"
        elif row["outcome"] == "planned" and not row["actions"]:
            problem = "Planned adoption lacks exact proposed actions"
        elif row["outcome"] == "blocked":
            problem = row["blocker"] or "Required prerequisite is missing"
        elif row["outcome"] == "reuse" and (row["current_adoption"] != "qualified" or not any(
                evidence[ref]["kind"] == "behavior" and evidence[ref]["inputs"] for ref in row["qualification_evidence"])):
            problem = "Equivalent integration lacks observed behavioral evidence on pinned inputs"
        elif row["mandatory"] and any(decisions[ref]["conflict"] and decisions[ref]["mode"] == "preserve"
                                       for ref in row["decision_ids"]):
            problem = "Preserved conflicting behavior blocks mandatory adoption"
        if problem:
            blockers.append(_block(row["id"], problem, row["resumption"] or "Resolve assessment/decision and supply evidence"))
    assessment = plan["semantic_assessment"]
    _object(assessment, ("complete", "catalog_complete", "conflicts_checked", "instructions_checked",
                         "source_provenance_checked", "native_evaluation"))
    for field in set(assessment) - {"native_evaluation"}:
        _require(type(assessment[field]) is bool, "Semantic assessment fields must be booleans")
        if not assessment[field]:
            blockers.append(_block("semantic:" + field, "Agent semantic assessment remains incomplete",
                                   "Complete the scoped assessment; structural checks cannot replace it"))
    native = assessment["native_evaluation"]
    _object(native, ("method", "smoke_cases"))
    _text(native["method"], empty=True)
    _strings(native["smoke_cases"])
    if not native["method"] or not native["smoke_cases"]:
        blockers.append(_block("native_evaluation", "Native harness method/initial smoke cases missing",
                               "Plan required native evaluation; keep optional paid labs separate"))
    for key, value in fingerprints.items():
        if value["status"] not in ("read", "absent"):
            blockers.append(_block(key, "File inventory has an explicit assessment gap: " + value["status"],
                                   "Resolve safely or record a scoped independent assessment prerequisite"))
    return blockers


def record_plan(plan_dir, request):
    """Replace one agent-authored proposal using an expected revision; never execute it."""
    _bounded(request)
    _object(request, ("expected_revision", "inventory", "decisions", "coverage", "actions", "evidence", "semantic_assessment"), ("reconcile",))
    _require(type(request["expected_revision"]) is int, "Expected an integer plan revision")
    with _locked(plan_dir) as (path, directory):
        plan = _load(path)
        _require(plan is not None, "Inspect the selected checkout before recording a plan")
        _require(request["expected_revision"] == plan["revision"], "Onboarding revision conflict; inspect the current plan")
        previous = {d["id"]: deepcopy(d) for d in plan["decisions"]}
        _require(isinstance(request["decisions"], list), "Invalid decisions")
        _require(all(isinstance(d, dict) and isinstance(d.get("id"), str) for d in request["decisions"]),
                 "Every decision needs a string ID")
        incoming = {d["id"]: d for d in request["decisions"]}
        _require(previous.keys() <= incoming.keys(), "Existing decision dispositions/history must be retained")
        changes, sources, current = _current(plan)
        _invalidate(plan, changes)
        if "reconcile" in request:
            reconciliation = request["reconcile"]
            _object(reconciliation, ("input_digest", "reason"))
            _hash(reconciliation["input_digest"])
            _text(reconciliation["reason"])
            _require(reconciliation["input_digest"] == _digest(current),
                     "Onboarding reconciliation inputs changed; inspect again")
            _require(current["identity"]["repository_root"] == plan["identity"]["repository_root"]
                     and current["identity"]["git_common_dir"] == plan["identity"]["git_common_dir"],
                     "Checkout authority changed; select a new plan")
            for item in plan["sources"]["declared"]["toolkit"]["files"]:
                observed = sources[item["path"]]
                _require(observed["status"] != "read" or observed["sha256"] == item["sha256"],
                         "Changed source bytes cannot be reconciled to a pinned source")
            plan["identity"] = current["identity"]
            plan["package_pins"] = current["package_pins"]
            plan["sources"]["observed"] = sources
            plan["requirements"] = _requirements(plan["sources"]["declared"])
            plan["invalidations"].append({"at": _now(), "revision": plan["revision"],
                "reconciled_inputs": changes, "input_digest": reconciliation["input_digest"],
                "reason": reconciliation["reason"]})
            changes = []
        for key in request.keys() - {"expected_revision", "reconcile"}:
            plan[key] = deepcopy(request[key])
        for key, old in previous.items():
            if incoming[key] != old:
                _remember_decision(plan, old)
        # New file destinations add instruction scopes even when Git ignores their directories.
        expanded = _snapshot(Path(plan["identity"]["repository_root"]), _file_targets(plan["actions"]))
        fingerprints = plan["identity"]["fingerprints"]
        fingerprints.update({key: value for key, value in expanded["fingerprints"].items()
                             if key.startswith("instruction:") and key not in fingerprints})
        known = {row["path"] for row in plan["identity"]["instructions"]}
        plan["identity"]["instructions"].extend(row for row in expanded["instructions"] if row["path"] not in known)
        blockers = _validate_proposal(plan)
        # New action absence/content must be checked too, including ignored destinations.
        new_changes, sources, current = _current(plan)
        changes = sorted(set(changes) | set(new_changes))
        _invalidate(plan, changes)
        plan["revision"] += 1
        report = _finish(plan, sources, changes, blockers, current=current)
        _save(plan, path, directory)
        return report
