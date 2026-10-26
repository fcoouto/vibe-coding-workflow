# Codex task runtime

Read this contract only when a Codex task needs explicit task controls, a `doctor` report, or lifecycle troubleshooting. Startup-only projects do not need it. For planned checks, review, completion, or local merge evidence, also read [task checks and review evidence](evidence.md). Shared policy remains in the [policy index](../policies/00-index.md); native qualification status and procedures are in [validation guidance](../docs/d2-validation.md).

## Opt in

The existing checkout-root `.vibe-coding-workflow/project.json` may include this optional field:

```json
"runtime": {"schema_version": 1, "state_dir": "/absolute/private/path"}
```

Choose a canonical absolute state directory outside all repositories and plugin caches. The directory and files must be private to the current user. Missing `runtime` keeps startup-only behavior. Invalid configuration produces a diagnostic; startup does not create or repair runtime state. Only `task start` initializes it. State lives in `runtime.sqlite3`, outside repositories. Startup may mention its location in Codex context, but does not expose stored task records there.

For enrollment fields or scope diagnostics, read the [shared startup contract](startup.md).

## Controls

Run controls from the installed package's `scripts/workflow.py`, using the enrolled checkout as `--cwd`. Start and update take one JSON object on stdin; status and doctor take flags. Examples:

```sh
python3 -I -B /path/to/package/scripts/workflow.py task start --cwd /checkout < start.json
python3 -I -B /path/to/package/scripts/workflow.py task update --cwd /checkout < update.json
python3 -I -B /path/to/package/scripts/workflow.py task status --cwd /checkout --client codex --session SESSION
python3 -I -B /path/to/package/scripts/workflow.py doctor --cwd /checkout --client codex --executable /path/to/codex
```

`start.json` requires `client:"codex"`, `session_id`, `task_id`, `scope_ref`, `mode` (`editable` or `read-only`), and `decision_ref`. Optional `replaces` is exactly `{task_id, expected_revision}` and is required to explicitly replace a current binding. A new task starts `planned` at revision 1. Repeating the same start identity is idempotent; task identity, mode, references and policy/runtime pins cannot be silently changed. Rebinding preserves history and revokes old continuations.

`update.json` requires `client`, `session_id`, `task_id`, `scope_ref`, positive `expected_revision`, `state`, `reason`, and `reference`. Optional `resolution_ref`, `conditions` and `resolutions` follow the schemas below. A revision conflict requires reading status and preparing a fresh update. States are `planned`, `active`, `awaiting_user`, `blocked`, `verifying`, `ready`, and terminal `cancelled`. Only successful evidence completion verification can set `ready`; ordinary task updates cannot. Allowed transitions are `planned→active`, `active↔verifying`, any non-cancelled state to `awaiting_user`, `blocked`, or `cancelled`, and `awaiting_user`/`blocked` to `planned`, `active`, or `verifying` only with `resolution_ref`. Resume from a wait or block requires `resolution_ref`; cancellation is terminal, even for same-state updates. Same-state updates can revise conditions.

A condition is exactly `{id, kind, action, reason, reference}` with optional `continuation`; `kind` is `blocker`, `decision`, or `runnable`, and `action` is `patch` or `task`. A continuation is exactly `{turn_id, budget}`; budget is integer `0` or `1`, and zero disables continuation. A resolution is exactly `{id, reference}` and resolves a previously recorded condition explicitly. Unknown fields reject. IDs are stable; kind/action cannot change. Omitted or empty conditions preserve history. At most 64 conditions/resolutions per request and 64 condition records per task. Condition IDs are at most 128 characters; other control text is nonblank, printable and at most 1024 characters (except IDs); task IDs are at most 128. References identify evidence or user input; they never grant authorization. Only explicit resolution clears a pending blocker or decision. Mode and pins are immutable.

Success prints a JSON object with `ok:true`, `task` (or null), checkout `generation`, `blockers`, and `limitations`. Errors print `{"ok":false,"error":"..."}`. Controls return 0 on success and 1 on error. `doctor` prints its structured report and exits 0 for passed inspected checks, 1 for detected failure, or 2 for incomplete/unsupported observation. A doctor result does not establish desktop execution.

## Guard and continuation limits

The Codex runtime hooks require configured runtime state; absent configuration preserves startup-only behavior. After a valid runtime scope is established, state or pin failure denies guarded `apply_patch`; invalid configuration itself produces a diagnostic and does not establish the runtime guard. Skipped, crashed or timed-out hooks may allow execution. The only write guard is canonical `apply_patch` during an active editable task without a pending applicable blocker or decision. Other tools, shell commands and external edits remain outside the guard. Post-tool events conservatively advance checkout generation; generation is invalidation metadata, not a check or review result.

Stop continuation is opt-in through one runnable condition, current correlated turn, budget exactly 1, no unresolved blockers/decisions and eligible active/verifying state. At most one continuation is consumed per task/turn, even across conditions, edits, retries, process restarts and concurrent Stop events; a genuinely new bound turn has its own allowance. Consumption occurs before continuation output, so it cannot be rearmed for that task/turn. A PostToolUse event with a previously unseen turn suppresses old-turn continuation without associating that completion with the task or pausing it. If Post arrives before canonical Pre establishes a turn binding, a later Pre for that same turn cannot adopt it; continuation or correlated pause requires a turn first established by canonical Pre. Missing or uncertain correlation passes without continuation. Interrupt can pause a correlated task; see [native qualification limits](../docs/d2-validation.md). Task state and references do not prove permission or task ownership. Readiness requires current evidence verification; status rechecks ready tasks against actual content. A ready result does not grant merge authority.
