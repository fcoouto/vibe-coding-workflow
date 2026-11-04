# Thread Naming

For adoption, event repair and manual edits, read [title synchronization](workstreams-titles.md).

## Automatic implementation naming

Activate title synchronization immediately before the first authorized
implementation action, including a test-first change or implementation-worker
dispatch. A request such as “Fix this bug” needs no later “Implement it” phrase.
Apply this to solo work and delegated work, regardless of Workstreams preferences
or runtime activation. Question-only, exploratory and planning chats do not
activate naming, even when they delegate work.

Once active, keep naming through tests, review, fixes, waits and integration.
Native children supporting that implementation, including read-only investigators
and independent reviewers, are eligible. A follow-up question alone does not
reopen a completed task. Explicit naming-only requests remain supported without
starting implementation. Naming changes display metadata only; it does not
activate managed task controls.

At activation, reserve or reuse the parent's family code even when no children
exist. Before dispatch, allocate the next unused child ordinal only for a new
eligible native context in the existing task plan.
After the native tool returns the actual child identity, record that identity
against its ordinal and adopt
the display title through the title procedure. Keep the prepared native
`task_name`, attempt marker, lineage and ownership unchanged. Continuations keep
their existing family/member mapping; replacement contexts receive new ordinals.

Follow the title procedure's initial-adoption and later baseline-comparison rules.
Preserve known manual titles, explicit title instructions and paused
synchronization; do not configure again or resume merely because another worker
starts or a feature preference changes. The title
procedure owns manual-edit reconciliation for both runtime-bound and ordinary
native work. Touch only the current implementation family or explicitly requested
titles, not unrelated chats. If title controls or the procedure's required
observations are unavailable, report the naming limitation without guessing a
title, identity or successful update.

Start every managed title with one `U+FFFB` (interlinear annotation terminator),
immediately followed by five visible meter cells. Put one ASCII space
between the meter and status. The examples include the leading character.

```text
<U+FFFB><meter> <STATUS> · [W<number>] <P|C<number>> · <short_topic>
```

```text
￻▰▰▱▱▱ WORKING · [W1] P · Thread naming
￻▰▰▰▰▰ DONE · [W1] C1 · Naming rules
￻▰▰▰▰▱ REVIEW · [W1] C2 · Status tags
￻▰▰▰▱▱ BLOCKED · [W1] C3 · Search support
￻▰▰▰▱▱ WAITING · [W1] C4 · Client check
￻▰▱▱▱▱ WORKING · [W2] P · Solo fix
```

The literal brackets enclose the shared family code. `P` identifies the parent;
`C1`, `C2` and subsequent positive ordinals identify distinct children, including
reviewers. Keep each family's parent and child identities stable through fixes,
renames, replacement attempts and status changes. Never reuse a child ordinal for
a different context. A coordinator parenting its own workers uses `P` in its own
family; record any relationship to an enclosing family in the existing task plan.

## Allocate a family once across projects

Before naming a new family, reserve its code with the package helper:

```text
python3 -I -B <package>/scripts/workstreams_family.py --client codex --parent <native_parent_id>
```

Use the actual client identifier and stable native parent identity, never a title
or checkout path. The helper returns `{"ok": true, "family": "W1"}`. It serializes
allocation in `~/.vibe-coding-workflow/workstreams-families.sqlite3`, shared across
all projects, linked checkouts and package copies for this OS user. The same
client/parent returns the same code; distinct parents receive different codes.
Keep this register when a family completes, is cancelled or is archived. Never
reset it, delete allocations or choose a project-local counter. It stores identity
bindings only; progress and acceptance stay in the existing task plan.

Record the returned code and each child ordinal with existing task/native bindings.
For existing native contexts, preserve their immutable creation markers and record
the display-family mapping. A title alone cannot authorize adopting an old code.
On allocation failure, report the naming limitation; do not guess an ID or reset
the register. This allocator covers projects sharing the user register, not separate
machines or OS accounts; those require one coordinated allocation authority before
claiming a shared namespace.

The intended search keys are `[W1]` for a family and `[W1] C` for its children.
Verify literal matching on the current client before promising those search results;
search behavior and proportional fonts may prevent exact filtering or alignment.
Keep topics short and recognizable. Shorten only standard
activity words: `Implementation` becomes `Impl.` and `Refactoring` becomes
`Refactor`, regardless of original capitalization. Keep task-specific identifying
words in full. Leave `Review`, `Test`, `Fix`, family/member codes and statuses
unchanged. Keep each topic stable through fixes; add a distinguishing suffix only
when needed. Reviewer topics start with `Review`.

## Status and accepted progress

Use exactly one uppercase status immediately after the meter:

| Status | Use when |
| --- | --- |
| `TRIAGE` | A thread has just been created and scope needs assessment. |
| `READY` | Scope and prerequisites are clear and work can start. |
| `WORKING` | Work is underway. This describes active task effort. |
| `REVIEW` | A result awaits review or review is underway. |
| `WAITING` | Work awaits an expected reply, dependency or event. |
| `BLOCKED` | Work cannot continue without intervention. |
| `PAUSED` | Work was deliberately put aside. |
| `DONE` | The thread's agreed scope is complete and verified. |
| `CANCELLED` | Work was closed without completing its agreed scope. |

Compute each thread's progress from currently accepted milestones in its existing
task plan, with task-appropriate weights when outcomes differ substantially.
Parent progress covers the combined deliverable, including required independent
review and integration; do not average child meters or count work twice. Child
progress covers its own scope. Elapsed time, token consumption and worker
self-reports do not establish acceptance. Reopened or invalidated milestones stop
counting and may reduce the meter or reopen a `DONE` thread.

Fill `▰` cells from the left and use `▱` for remaining cells. With measurable
milestones, each filled cell represents a completed 20% step. Round down and cap
unfinished work at four cells. Without measurable milestones, show one filled
cell during `WORKING` as an activity indicator. Other unfinished statuses use
an empty meter in that case. At adoption, use the actual phase. Newly started
implementation uses `WORKING`, not an automatic `TRIAGE` reset.
Reserve `▰▰▰▰▰` for verified `DONE`, keeping both the full meter and that label.
Show no numeric percentage or `% done`. Measured progress comes from accepted
milestones. `BLOCKED`, `WAITING` and `PAUSED` retain
accepted progress; `CANCELLED` retains partial progress and never implies completion.

Update display titles on meaningful milestone, phase or blocker changes during
existing handling, without extra model turns, polling or a progress registry.
For naming-only requests, change display metadata without enabling Workstreams,
starting work or altering task state. Apply this convention to requested existing
titles through supported controls; do not bulk-rename unrelated threads.

Internal responsibilities remain coordinator, deliverable owner and independent
reviewer, assigned from each objective. Models/reasoning stay in metadata. Title
changes grant no authority and do not alter immutable native identity.

Use supported client display-title controls. Preserve native creation markers,
lineage and task ownership. If a client cannot expose the requested parent/child
association, report that limitation before dispatch. Display titles do not qualify
native execution or authorize new work.
