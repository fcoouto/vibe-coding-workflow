"""Read-only startup orientation shared by client adapters."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from types import MappingProxyType


MAX_INPUT = 128 * 1024
PROJECT_FILE = Path(".vibe-coding-workflow/project.json")


class StartupError(ValueError):
    """A safe, actionable startup diagnostic with no input contents."""


class RuntimeScopeError(StartupError):
    """Accepted runtime scope whose installed policy/client source is incompatible."""


@dataclass(frozen=True)
class StartupEvent:
    client: str
    session_id: str
    cwd: Path
    source: str
    model: str | None = None
    permission_mode: str | None = None


@dataclass(frozen=True)
class RuntimeSettings:
    schema_version: int
    state_dir: Path


@dataclass(frozen=True)
class ProjectScope:
    project_id: str
    repository_root: Path
    git_common_dir: Path
    policy_digest: str
    runtime: RuntimeSettings | None = None


def json_object(raw, *, limit=MAX_INPUT):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise StartupError("Duplicate JSON field")
            result[key] = value
        return result

    def invalid_number(_):
        raise StartupError("Non-JSON number")

    if type(limit) is not int or limit < 1:
        raise StartupError("Invalid JSON byte limit")
    size = len(raw.encode('utf-8')) if isinstance(raw, str) else len(raw)
    if size > limit:
        raise StartupError("JSON exceeds 128 KiB" if limit == MAX_INPUT else "Internal JSON exceeds its byte limit")
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


def runtime_settings(record, package, common):
    """Validate opt-in location without creating or opening runtime state."""
    if "runtime" not in record:
        return None
    settings = record["runtime"]
    if not isinstance(settings, dict) or type(settings.get("schema_version")) is not int or settings["schema_version"] != 2:
        raise StartupError("Unsupported runtime configuration schema")
    value = settings.get("state_dir")
    if not isinstance(value, str) or not value or len(value) > 4096 or any(not char.isprintable() for char in value):
        raise StartupError("Invalid runtime state directory")
    path = Path(value)
    if not path.is_absolute() or str(path.resolve()) != value:
        raise StartupError("Runtime state directory must be absolute and canonical")
    if path.is_relative_to(package.resolve()) or path.is_relative_to(common):
        raise StartupError("Runtime state directory must be outside repositories and plugin caches")
    for ancestor in (path, *path.parents):
        if os.path.lexists(ancestor) and not ancestor.is_dir():
            raise StartupError("Runtime state directory ancestors must be directories")
        if os.path.lexists(ancestor / ".git") or (
                ancestor.name == "plugins" and ancestor.parent.name in {".codex", ".claude"}) or (
                ancestor.name == "cache" and ancestor.parent.name == "plugins"):
            raise StartupError("Runtime state directory must be outside repositories and plugin caches")
    existing = next(ancestor for ancestor in (path, *path.parents) if ancestor.is_dir())
    # Bare repositories have no .git marker; discover from the nearest existing directory.
    discovery = subprocess.run(
        ["git", "-c", "safe.bareRepository=all", "-C", str(existing),
         "rev-parse", "--absolute-git-dir"],
        env={**{key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
             "GIT_DISCOVERY_ACROSS_FILESYSTEM": "1"},
        capture_output=True, text=True, timeout=2, check=False,
    )
    if discovery.returncode == 0:
        raise StartupError("Runtime state directory must be outside repositories and plugin caches")
    return RuntimeSettings(2, path)


def resolve_project(event, package) -> ProjectScope | None:
    """Resolve accepted checkout scope, preserving silence outside enrollment."""
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
    runtime = runtime_settings(record, package, common)
    scope_error = RuntimeScopeError if runtime is not None else StartupError
    try:
        installed_policy = policy_digest(package)
    except (StartupError, OSError):
        raise scope_error("Installed policy sources are unavailable") from None
    if record.get("policy_digest") != installed_policy:
        raise scope_error("Installed policies differ from the accepted enrollment")
    client_file = package / "clients" / f"{event.client}.md"
    if not client_file.is_file():
        raise scope_error("Installed client instructions are missing")
    return ProjectScope(record["project_id"], root, common, record["policy_digest"],
                        runtime)


def orient(event, package):
    scope = resolve_project(event, package)
    if scope is None:
        return None
    client_file = package / "clients" / f"{event.client}.md"
    context = (
        "Vibe Coding Workflow applies to this enrolled checkout. Read the client instructions at "
        f"{json.dumps(str(client_file))}, the policy index at "
        f"{json.dumps(str(package / 'policies/00-index.md'))}, and accepted project configuration at "
        f"{json.dumps(str(scope.repository_root / PROJECT_FILE))}. Load only triggered policies and applicable "
        "project/directory instructions. Activate silently; explain useful task steps, blockers or "
        "decisions. Startup supplies orientation only; it does not establish enforcement or readiness."
    )
    if scope.runtime is not None and event.client == "codex":
        context += (f" Runtime state: {json.dumps(str(scope.runtime.state_dir / 'runtime.sqlite3'))}; "
                    f"native Codex session: {json.dumps(event.session_id)}. Read existing task status with task status; startup never changes bindings or pins.")
        if len(context.split()) > 150:
            raise StartupError("Runtime startup orientation exceeds the context limit")
    return context


# Pure schema-2 APIs are deliberately separate from production startup resolution.
CANONICAL_MAX_ROWS = 4096


@dataclass(frozen=True)
class CanonicalRecord:
    data: object


@dataclass(frozen=True)
class AcceptedScope:
    project_id: str
    repository_id: str
    checkout_id: str
    project_root: Path
    authority_path: Path
    authority_target: object
    authority_revision: int
    repository_root: Path
    primary_root: Path
    git_dir: Path
    git_common_dir: Path
    bindings: object
    client: str
    policy_digest: str
    runtime_digest: str
    runtime: RuntimeSettings
    accepted_identity: object
    accepted_scope_digest: str
    qualification_provenance: object


@dataclass(frozen=True)
class ScopeResolution:
    status: str
    scope: AcceptedScope | None
    reason: str


def _canonical_require(condition):
    if not condition:
        raise StartupError("Invalid canonical scope data")


def _canonical_fields(value, keys):
    _canonical_require(isinstance(value, dict) and set(value) == set(keys.split()))


def _canonical_text(value, limit=4096):
    _canonical_require(isinstance(value, str) and 0 < len(value) <= limit
                       and bool(value.strip()) and value.isprintable())
    return value


def _canonical_path(value, *, relative=False):
    _canonical_text(value)
    path = Path(value)
    _canonical_require(path.is_absolute() != relative and str(path) == value
                       and os.path.normpath(value) == value and ".." not in path.parts
                       and not value.startswith("//"))
    return path


def _canonical_hash(value):
    _canonical_require(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value))


def _canonical_binding(value):
    _canonical_fields(value, "device inode")
    _canonical_require(all(type(v) is int and v >= 0 for v in value.values()))


def _canonical_ref(value):
    _canonical_fields(value, "reference sha256")
    _canonical_text(value["reference"])
    _canonical_hash(value["sha256"])


def _canonical_rows(value):
    _canonical_require(isinstance(value, list) and len(value) <= CANONICAL_MAX_ROWS)
    return value


def _canonical_unique(values):
    try:
        _canonical_require(len(values) == len(set(values)))
    except TypeError:
        raise StartupError("Invalid canonical scope data") from None


def _canonical_hook(value):
    _canonical_fields(value, "root binding source sha256")
    root, source = (_canonical_path(value[k]) for k in ("root", "source"))
    _canonical_require(source.is_relative_to(root))
    _canonical_binding(value["binding"])
    _canonical_hash(value["sha256"])


def _canonical_qualification(value):
    _canonical_fields(value, "client surface version configuration_digest hook_owner accepted_scope_digest receipt")
    for key in ("client", "surface", "version"):
        _canonical_text(value[key], 128)
    for key in ("configuration_digest", "accepted_scope_digest"):
        _canonical_hash(value[key])
    _canonical_hook(value["hook_owner"])
    _canonical_ref(value["receipt"])


def _canonical_freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _canonical_freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_canonical_freeze(item) for item in value)
    return value


def _canonical_plain(value):
    if isinstance(value, (dict, MappingProxyType)):
        return {key: _canonical_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_plain(item) for item in value]
    return value


def _canonical_copy(value):
    try:
        raw = value if isinstance(value, (bytes, str)) else json.dumps(_canonical_plain(value), ensure_ascii=False)
        return json_object(raw)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise StartupError("Invalid canonical scope JSON") from None


def _canonical_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True).encode()).hexdigest()


def decode_project_record(record) -> CanonicalRecord:
    """Validate and snapshot proposed canonical enrollment, without observing IO."""
    value = _canonical_copy(record)
    _canonical_fields(value, "schema_version revision project_id project_root kind project_binding membership shared_policy repositories")
    _canonical_require(type(value["schema_version"]) is int and value["schema_version"] == 2
                       and type(value["revision"]) is int and value["revision"] > 0)
    _canonical_require(isinstance(value["project_id"], str)
                       and re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", value["project_id"]))
    project = _canonical_path(value["project_root"])
    _canonical_binding(value["project_binding"])
    _canonical_require(value["kind"] in ("standalone", "umbrella"))
    membership = value["membership"]
    _canonical_fields(membership, "include exclude future_join authorization")
    _canonical_require(type(membership["future_join"]) is bool)
    _canonical_ref(membership["authorization"])
    for key in ("include", "exclude"):
        paths = [_canonical_path(p, relative=True) for p in _canonical_rows(membership[key])]
        _canonical_unique(paths)
        _canonical_require(not any(a != b and a.is_relative_to(b) for a in paths for b in paths))
    _canonical_require(bool(membership["include"]))
    shared = _canonical_rows(value["shared_policy"])
    for item in shared:
        _canonical_fields(item, "path sha256")
        _canonical_path(item["path"])
        _canonical_hash(item["sha256"])
    _canonical_unique([item["path"] for item in shared])
    shared_paths = {item["path"] for item in shared}
    ids, roots, common_roots, rows = [], [], [], len(shared)
    repositories = _canonical_rows(value["repositories"])
    _canonical_require(bool(repositories))
    for repo in repositories:
        _canonical_fields(repo, "repository_id primary_root git_common_dir binding membership checkouts")
        ids.append(_canonical_text(repo["repository_id"], 128))
        primary = _canonical_path(repo["primary_root"])
        common = _canonical_path(repo["git_common_dir"])
        roots.append(str(primary)); common_roots.append(str(common))
        _canonical_require(repo["membership"] in ("joined", "removed"))
        _canonical_fields(repo["binding"], "primary_root git_common_dir")
        for binding in repo["binding"].values():
            _canonical_binding(binding)
        checkouts = _canonical_rows(repo["checkouts"])
        _canonical_require(bool(checkouts))
        rows += 1 + len(checkouts)
        for selected in checkouts:
            _canonical_fields(selected, "checkout_id root git_dir binding clients")
            ids.append(_canonical_text(selected["checkout_id"], 128))
            root = _canonical_path(selected["root"])
            _canonical_path(selected["git_dir"])
            _canonical_fields(selected["binding"], "root git_dir")
            for binding in selected["binding"].values():
                _canonical_binding(binding)
            if value["kind"] == "umbrella":
                _canonical_require(not project.is_relative_to(root) and not project.is_relative_to(primary) and not project.is_relative_to(common))
            clients = _canonical_rows(selected["clients"])
            rows += len(clients)
            _canonical_unique([c.get("client") for c in clients if isinstance(c, dict)])
            for client in clients:
                _canonical_fields(client, "client configuration activation")
                _canonical_require(re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", _canonical_text(client["client"], 128)))
                config, activation = client["configuration"], client["activation"]
                _canonical_fields(activation, "status qualification accepted_scope_digest transaction_id evidence qualification_binding")
                _canonical_require(activation["status"] in ("pending", "configured", "active", "suspended")
                                   and activation["qualification"] in ("pending", "qualified"))
                for field in ("accepted_scope_digest",):
                    if activation[field] is not None:
                        _canonical_hash(activation[field])
                if activation["transaction_id"] is not None:
                    _canonical_text(activation["transaction_id"], 128)
                for proof in _canonical_rows(activation["evidence"]):
                    _canonical_ref(proof)
                if activation["qualification_binding"] is not None:
                    _canonical_qualification(activation["qualification_binding"])
                if config is None:
                    _canonical_require(activation == dict(status="pending", qualification="pending",
                        accepted_scope_digest=None, transaction_id=None, evidence=[], qualification_binding=None))
                    continue
                _canonical_fields(config, "policy_digest runtime_digest runtime shared_dependencies evidence")
                for field in ("policy_digest", "runtime_digest"):
                    _canonical_hash(config[field])
                runtime = config["runtime"]
                if runtime is not None:
                    _canonical_fields(runtime, "schema_version state_dir")
                    _canonical_require(type(runtime["schema_version"]) is int and runtime["schema_version"] == 3)
                    _canonical_path(runtime["state_dir"])
                dependencies = _canonical_rows(config["shared_dependencies"])
                _canonical_unique(dependencies)
                _canonical_require(all(p in shared_paths for p in dependencies))
                rows += len(dependencies)
                for proof in _canonical_rows(config["evidence"]):
                    _canonical_ref(proof)
                if activation["status"] == "active":
                    _canonical_require(activation["qualification"] == "qualified"
                        and activation["accepted_scope_digest"] is not None
                        and activation["transaction_id"] is not None and bool(activation["evidence"])
                        and activation["qualification_binding"] is not None)
    _canonical_require(rows <= CANONICAL_MAX_ROWS)
    _canonical_unique(ids); _canonical_unique(roots); _canonical_unique(common_roots)
    checkout_roots = [c["root"] for r in repositories for c in r["checkouts"]]
    _canonical_unique(checkout_roots)
    locations = {value["project_root"]: value["project_binding"]}
    for repo in repositories:
        entries = [(repo[k], b) for k, b in repo["binding"].items()]
        entries += [(selected[k], b) for selected in repo["checkouts"] for k, b in selected["binding"].items()]
        for path, binding in entries:
            _canonical_require(path not in locations or locations[path] == binding)
            locations[path] = binding
    if value["kind"] == "standalone":
        _canonical_require(len(repositories) == 1 and repositories[0]["primary_root"] == str(project))
    return CanonicalRecord(_canonical_freeze(value))


def _canonical_target(value):
    _canonical_fields(value, "path binding parents fingerprint")
    path = _canonical_path(value["path"])
    if value["binding"] is not None:
        _canonical_binding(value["binding"])
    _canonical_require(isinstance(value["parents"], dict) and 0 < len(value["parents"]) <= CANONICAL_MAX_ROWS)
    for name, binding in value["parents"].items():
        parent = _canonical_path(name)
        _canonical_require(parent != path and path.is_relative_to(parent))
        _canonical_binding(binding)
    fingerprint = value["fingerprint"]
    _canonical_require(isinstance(fingerprint, dict))
    if fingerprint.get("status") == "read":
        _canonical_fields(fingerprint, "status sha256 bytes")
        _canonical_hash(fingerprint["sha256"])
        _canonical_require(type(fingerprint["bytes"]) is int and fingerprint["bytes"] >= 0
                           and value["binding"] is not None and str(path.parent) in value["parents"])
    else:
        _canonical_fields(fingerprint, "status")
        _canonical_require(fingerprint["status"] == "absent" and value["binding"] is None)


def _canonical_provenance(value, kind):
    _canonical_fields(value, "kind reference sha256")
    _canonical_require(value["kind"] == kind)
    _canonical_ref({key: value[key] for key in ("reference", "sha256")})


def _canonical_runtime_location(value):
    if value is None:
        return
    _canonical_fields(value, "path existing_ancestors git_probe exclusions provenance")
    _canonical_path(value["path"])
    for ancestor in _canonical_rows(value["existing_ancestors"]):
        _canonical_fields(ancestor, "path binding kind")
        _canonical_path(ancestor["path"])
        _canonical_require(ancestor["kind"] in ("directory", "absent", "link", "other", "unreadable"))
        if ancestor["kind"] in ("absent", "unreadable"):
            _canonical_require(ancestor["binding"] is None)
        else:
            _canonical_binding(ancestor["binding"])
    _canonical_fields(value["git_probe"], "cwd result")
    _canonical_path(value["git_probe"]["cwd"])
    _canonical_require(value["git_probe"]["result"] in ("outside", "repository", "bare", "unknown"))
    _canonical_fields(value["exclusions"], "package_root software_roots git_roots plugin_cache_roots")
    _canonical_path(value["exclusions"]["package_root"])
    for key in ("software_roots", "git_roots", "plugin_cache_roots"):
        for path in _canonical_rows(value["exclusions"][key]):
            _canonical_path(path)
    if value["provenance"] is not None:
        _canonical_provenance(value["provenance"], "runtime-location-observer")


def resolve_canonical_scope(record, *, authority, observation, client, installed) -> ScopeResolution:
    """Compare internal observer facts; external JSON never authenticates scope.

    Authority targets are supplied freshness provenance. The future IO wrapper
    must parse and fingerprint one bounded byte snapshot before supplying it.
    This pure comparison cannot authenticate receipt or observer provenance.
    """
    _canonical_require(isinstance(record, CanonicalRecord))
    # Revalidate even manually constructed wrappers; never retain caller-owned data.
    data = _canonical_plain(decode_project_record(_canonical_plain(record.data)).data)
    facts = _canonical_copy(dict(authority=authority, observation=observation, client=client, installed=installed))
    authority, observation, client, installed = (facts[k] for k in ("authority", "observation", "client", "installed"))
    _canonical_text(client, 128)
    _canonical_fields(authority, "path target")
    _canonical_path(authority["path"]); _canonical_target(authority["target"])
    _canonical_fields(installed, "policy_digest runtime_digest clients package_root")
    for field in ("policy_digest", "runtime_digest"):
        _canonical_hash(installed[field])
    _canonical_path(installed["package_root"])
    for name in _canonical_rows(installed["clients"]):
        _canonical_text(name, 128)
    _canonical_fields(observation, "project_root project_binding root primary_root git_dir git_common_dir binding membership conflicting_authorities dependencies qualification runtime_location")
    for field in ("project_root", "root", "primary_root", "git_dir", "git_common_dir"):
        _canonical_path(observation[field])
    _canonical_binding(observation["project_binding"])
    _canonical_fields(observation["binding"], "root primary_root git_dir git_common_dir")
    for binding in observation["binding"].values():
        _canonical_binding(binding)
    _canonical_require(observation["membership"] in ("included", "excluded", "outside", "unknown"))
    for path in _canonical_rows(observation["conflicting_authorities"]):
        _canonical_path(path)
    dependencies = _canonical_rows(observation["dependencies"])
    for dep in dependencies:
        _canonical_fields(dep, "path status target")
        _canonical_path(dep["path"])
        _canonical_require(dep["status"] in ("read", "absent", "unreadable", "unknown"))
        if dep["target"] is None:
            _canonical_require(dep["status"] in ("unreadable", "unknown"))
        else:
            _canonical_target(dep["target"])
    qualification = observation["qualification"]
    if qualification is not None:
        _canonical_fields(qualification, "current receipt binding provenance")
        _canonical_fields(qualification["current"], "client surface version configuration_digest hook_owner")
        for key in ("client", "surface", "version"):
            _canonical_text(qualification["current"][key], 128)
        _canonical_hash(qualification["current"]["configuration_digest"])
        _canonical_hook(qualification["current"]["hook_owner"])
        _canonical_ref(qualification["receipt"])
        if qualification["binding"] is not None:
            _canonical_qualification(qualification["binding"])
        if qualification["provenance"] is not None:
            _canonical_provenance(qualification["provenance"], "trusted-coordinator")
    location = observation["runtime_location"]
    _canonical_runtime_location(location)

    def result(status, reason):
        return ScopeResolution(status, None, reason)

    directories = {data["project_root"]: data["project_binding"]}
    for repo in data["repositories"]:
        directories.update({repo[k]: b for k, b in repo["binding"].items()})
        for selected in repo["checkouts"]:
            directories.update({selected[k]: b for k, b in selected["binding"].items()})
    observed_directories = {observation["project_root"]: observation["project_binding"]}
    observed_directories.update({observation[k]: b for k, b in observation["binding"].items()})
    for path, binding in observed_directories.items():
        if path in directories and directories[path] != binding:
            return result("conflict", "identity_changed")
        directories[path] = binding
    for path, binding in authority["target"]["parents"].items():
        if path in directories and directories[path] != binding:
            return result("conflict", "authority_conflict")
        directories[path] = binding

    expected_authority = str(Path(data["project_root"]) / PROJECT_FILE)
    if (observation["conflicting_authorities"] or authority["path"] != expected_authority
            or authority["target"]["path"] != expected_authority
            or authority["target"]["fingerprint"]["status"] != "read"
            or authority["target"]["parents"].get(data["project_root"]) != data["project_binding"]):
        return result("conflict", "authority_conflict")
    if any(observation[k] != data[k] for k in ("project_root", "project_binding")):
        return result("conflict", "identity_changed")
    location_state = None
    if location is not None:
        chain = location["existing_ancestors"]
        exclusions = location["exclusions"]
        configured_paths = [Path(location["path"]), *Path(location["path"]).parents]
        known_roots = {data["project_root"], observation["primary_root"], observation["root"]}
        known_git = {observation["git_common_dir"], observation["git_dir"]}
        roots = [exclusions["package_root"], *exclusions["software_roots"],
                 *exclusions["git_roots"], *exclusions["plugin_cache_roots"],
                 *[r["primary_root"] for r in data["repositories"]],
                 *[r["git_common_dir"] for r in data["repositories"]],
                 *[c[k] for r in data["repositories"] for c in r["checkouts"] for k in ("root", "git_dir")]]
        unsafe = (exclusions["package_root"] != installed["package_root"]
            or any(Path(location["path"]).is_relative_to(Path(root)) for root in roots)
            or any(a["kind"] in ("link", "other") for a in chain)
            or location["git_probe"]["result"] in ("repository", "bare")
            or any((p.name == "plugins" and p.parent.name in (".codex", ".claude"))
                   or (p.name == "cache" and p.parent.name == "plugins") for p in configured_paths))
        if unsafe:
            return result("conflict", "runtime_location_unsafe")
        existing = next((a for a in chain if a["kind"] == "directory"), None)
        incomplete = ([a["path"] for a in chain] != [str(p) for p in configured_paths]
            or any(a["kind"] == "unreadable" for a in chain)
            or any(a["kind"] == "absent" for a in chain[next((i for i, a in enumerate(chain) if a["kind"] == "directory"), len(chain)):])
            or existing is None or location["git_probe"]["cwd"] != existing["path"]
            or location["git_probe"]["result"] == "unknown" or location["provenance"] is None
            or not known_roots <= set(exclusions["software_roots"])
            or not known_git <= set(exclusions["git_roots"]))
        if incomplete:
            location_state = "unobserved"
    else:
        location_state = "unobserved"

    repos = [r for r in data["repositories"] if r["primary_root"] == observation["primary_root"]]
    if not repos:
        for known in data["repositories"]:
            if (observation["git_common_dir"] == known["git_common_dir"]
                    or observation["binding"]["primary_root"] == known["binding"]["primary_root"]
                    or observation["binding"]["git_common_dir"] == known["binding"]["git_common_dir"]
                    or any(observation["binding"]["root"] == c["binding"]["root"] for c in known["checkouts"])):
                return result("conflict", "identity_changed")
        primary = Path(observation["primary_root"])
        project = Path(data["project_root"])
        membership = data["membership"]
        if (not any(primary.is_relative_to(project / p) for p in membership["include"])
                or any(primary.is_relative_to(project / p) for p in membership["exclude"])
                or observation["membership"] in ("excluded", "outside")):
            return result("outside", "excluded")
        if observation["membership"] == "unknown":
            return result("conflict", "identity_changed")
        return result("pending", "member_pending")
    repo = repos[0]
    if (repo["git_common_dir"] != observation["git_common_dir"]
            or any(repo["binding"][k] != observation["binding"][k] for k in repo["binding"])):
        return result("conflict", "identity_changed")
    selected = next((c for c in repo["checkouts"] if c["root"] == observation["root"]), None)
    if selected is None:
        if any(c["binding"]["root"] == observation["binding"]["root"] for c in repo["checkouts"]):
            return result("conflict", "identity_changed")
        primary = Path(repo["primary_root"])
        project = Path(data["project_root"])
        membership = data["membership"]
        if (repo["membership"] == "removed"
                or not any(primary.is_relative_to(project / p) for p in membership["include"])
                or any(primary.is_relative_to(project / p) for p in membership["exclude"])
                or observation["membership"] in ("excluded", "outside")):
            return result("outside", "excluded")
        if observation["membership"] == "unknown":
            return result("conflict", "identity_changed")
        return result("pending", "member_pending")
    bindings = repo["binding"] | selected["binding"]
    if (repo["git_common_dir"] != observation["git_common_dir"] or selected["git_dir"] != observation["git_dir"]
            or bindings != observation["binding"]):
        return result("conflict", "identity_changed")

    config_entry = next((c for c in selected["clients"] if c["client"] == client), None)
    config = config_entry["configuration"] if config_entry is not None else None
    if (location is not None and config is not None and config["runtime"] is not None
            and location["path"] != config["runtime"]["state_dir"]):
        return result("conflict", "runtime_location_unsafe")

    primary = Path(repo["primary_root"])
    project = Path(data["project_root"])
    membership = data["membership"]
    included = any(primary.is_relative_to(project / p) for p in membership["include"])
    excluded = any(primary.is_relative_to(project / p) for p in membership["exclude"])
    if repo["membership"] == "removed" or excluded or not included or observation["membership"] in ("excluded", "outside"):
        return result("outside", "excluded")
    if observation["membership"] == "unknown":
        return result("conflict", "identity_changed")
    if config_entry is None:
        return result("pending", "member_pending")
    config, activation = config_entry["configuration"], config_entry["activation"]
    if config is None:
        return result("pending", "activation_pending")
    if (client not in installed["clients"] or any(config[k] != installed[k] for k in ("policy_digest", "runtime_digest"))):
        return result("suspended", "configuration_changed")
    shared = sorted((s for s in data["shared_policy"] if s["path"] in config["shared_dependencies"]), key=lambda s: s["path"])
    if (len(dependencies) != len(shared) or [d["path"] for d in dependencies] != [s["path"] for s in shared]
            or any(d["status"] != "read" for d in dependencies)):
        return result("suspended", "dependency_unobserved")
    for dependency in dependencies:
        for path, binding in dependency["target"]["parents"].items():
            if path in directories and directories[path] != binding:
                return result("suspended", "dependency_changed")
            directories[path] = binding
    if any(d["target"]["path"] != d["path"] or d["target"]["fingerprint"].get("sha256") != s["sha256"]
           for d, s in zip(dependencies, shared)):
        return result("suspended", "dependency_changed")
    identity = dict(version=1, project_id=data["project_id"], repository_id=repo["repository_id"],
        checkout_id=selected["checkout_id"], project_root=data["project_root"], project_binding=data["project_binding"],
        primary_root=repo["primary_root"], repository_root=selected["root"], git_dir=selected["git_dir"],
        git_common_dir=repo["git_common_dir"], bindings=bindings, client=client,
        membership=dict(included=True, authorization=membership["authorization"]),
        configuration={k: config[k] for k in ("policy_digest", "runtime_digest", "runtime")}, shared_policy=shared)
    digest = _canonical_digest(identity)
    if activation["accepted_scope_digest"] is not None and activation["accepted_scope_digest"] != digest:
        return result("suspended", "configuration_changed")
    if qualification is not None and qualification["binding"] is not None:
        binding = qualification["binding"]
        if (binding != activation["qualification_binding"] or qualification["receipt"] != binding["receipt"]
            or any(qualification["current"][k] != binding[k] for k in qualification["current"])
            or binding["accepted_scope_digest"] != digest or binding["client"] != client):
            return result("suspended", "qualification_changed")
    if activation["status"] == "suspended":
        return result("suspended", "activation_suspended")
    if (qualification is None or qualification["binding"] is None or qualification["provenance"] is None
            or activation["qualification"] != "qualified" or activation["qualification_binding"] is None):
        return result("configured", "qualification_unobserved")
    if config["runtime"] is None or location_state == "unobserved":
        return result("configured", "runtime_location_unobserved")
    if location["path"] != config["runtime"]["state_dir"]:
        return result("conflict", "runtime_location_unsafe")
    if activation["status"] == "configured":
        return result("configured", "activation_configured")
    if activation["status"] == "pending":
        return result("pending", "activation_pending")
    scope = AcceptedScope(data["project_id"], repo["repository_id"], selected["checkout_id"], project,
        Path(authority["path"]), _canonical_freeze(authority["target"]), data["revision"], Path(selected["root"]),
        primary, Path(selected["git_dir"]), Path(repo["git_common_dir"]), _canonical_freeze(bindings), client,
        config["policy_digest"], config["runtime_digest"], RuntimeSettings(3, Path(config["runtime"]["state_dir"])),
        _canonical_freeze(identity), digest, _canonical_freeze(qualification["provenance"]))
    return ScopeResolution("active", scope, "active")
