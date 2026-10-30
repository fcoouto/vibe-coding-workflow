# Shared startup contract

Read this when implementing or diagnosing startup, or preparing enrollment records. Ordinary tasks follow the [policy index](../policies/00-index.md) and their selected client instructions.

The shared runtime resolves the nearest Git checkout and common Git directory. Parent, neighboring and host workspace paths never extend enrollment. No enrollment produces no output; invalid integration produces a diagnostic. Startup supplies orientation only, without onboarding, task state, action guards or merge enforcement.

## Enrollment input

Read `.vibe-coding-workflow/project.json` only at the checkout root. Startup tests use disposable fixtures; D4 will create this record through explicit onboarding. A fixture does not establish completed onboarding or qualified enforcement.

Private Project-plan schema 2 is not an enrollment record. Startup still reads schema-1 checkout-root enrollment; private inspection/proposal support does not implement umbrella discovery/adoption or future-member activation. The nested runtime/SQLite schema is a separate version contract.

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer `1` |
| `project_id` | Stable identifier, 1–128 letters, digits, underscores or hyphens |
| `repository_root` | Exact canonical absolute checkout/worktree path |
| `git_common_dir` | Exact canonical absolute common Git directory |
| `clients` | Nonempty list of selected native client IDs: `codex`, `claude-code` |
| `policy_digest` | SHA-256 over sorted `policies/*.md`: filename, NUL, file bytes, NUL, repeated |
| `runtime` (optional) | Codex D2 opt-in: schema version and private external state directory; see the [runtime contract](runtime.md) |

Additional project fields remain available to later slices. Require the current native client in `clients`. This startup record does not distinguish host surfaces; qualify the actual launch separately.

The current public schema-1 resolver applies optional `runtime` only to Codex. A dual-client record keeps Claude `SessionStart` orientation but does not enable Claude file guards or task controls. Internal read-only canonical acquisition now observes and compares project authority, checkout, physical bindings, dependencies, runtime location and qualification; public startup/task dispatch still uses schema-1 enrollment. Only independently observed qualification facts can yield an active canonical scope. See [Claude's prepared guard boundary](claude-code.md#prepared-file-guard).

A copied checkout record, changed policy digest, malformed JSON, link or special-file record produces a diagnostic. Reconcile accepted scope/version through onboarding; never silently rewrite it during startup. Omitting `runtime` preserves startup-only behavior. This field does not enable Claude lifecycle controls.

## Runtime limits

Require Git and Python 3.11+ on the hook PATH. Current file operations require POSIX; Windows and non-Git projects remain unqualified. Input is limited to 128 KiB, Git lookup to two seconds and each hook to five seconds. Startup performs no writes, network requests or model calls. Interpreter isolation prevents project Python files or environment imports from replacing runtime modules.

Each lifecycle event may refresh context after resume, fork or compaction. There is no persistent deduplication: native events supply no unique invocation ID. Supplied model and permission settings remain observations; missing values, client version and UI surface remain unknown. Never infer approval from environment variables or hook output.

Run `python3 -B scripts/validate.py` and `python3 -B -m unittest discover -s tests`. These establish package and fixture behavior. Native qualification must separately observe one handler, actual output, permissions and the client's installation/trust rules.
