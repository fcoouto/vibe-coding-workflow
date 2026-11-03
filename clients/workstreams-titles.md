# Thread Naming title synchronization

Load for eligible implementation naming, adopting a managed title, recording
task progress, resolving a manual rename, or diagnosing missed title updates.
The [naming contract](workstreams-naming.md) owns the format and adoption trigger.
For runtime-bound tasks, render canonical state verbatim; there is no separate
display-status list.

## Adopt a parent or child

First inspect the existing title and any recorded presentation ownership. Reuse
an adopted family/member mapping, reconcile manual edits before writing, and
retain any manual-title pause. A known user-selected title is an override even
before managed adoption; preserve it until the user explicitly requests adoption.
Explicit title instructions and recorded pauses also take precedence over
automatic adoption.

For a verified fresh native context whose first turn starts implementation or
supports an active implementation, with no prior turns, fork, resumption or
continuation, the approved naming policy authorizes the first managed title
without a separate naming request. Standalone question, planning and review
contexts do not acquire this permission. Do not
require a native title-author signal on this path: the client may expose the
initial title without its origin. This is workflow permission to adopt the
initial title, not proof that the title was automatic. For a nonfresh or
historical context with unknown title ownership, retain the conservative guard:
report that limitation instead of replacing the title. An eligible context's
independently observed automatic/default title also permits adoption when no
known override or pause applies.

Observe the initial title, then re-read it after preparation immediately before
writing. Preserve any observed intervening change instead of overwriting it.
The first successful write and matching readback establish the last verified
managed title. Retain an uncertain write as pending and reconcile it against that
same native identity; do not restart adoption or reset the baseline to each new
observation.

When a workflow task is already bound, configure an eligible title once through
the enrolled package, using the naming rule as the workflow decision
reference. Use the current task identity and revision:

```text
python3 -I -B <package>/scripts/workflow.py task title configure --cwd <checkout> < title.json
```

Parent request:

```json
{
  "client": "codex",
  "session_id": "<native_thread_id>",
  "task_id": "<bound_task_id>",
  "scope_ref": "<bound_scope_reference>",
  "expected_revision": 1,
  "reference": "<user_or_workflow_decision>",
  "topic": "Thread naming"
}
```

For an explicitly associated child, also provide `parent_session_id` and `member`
(for example `C1`). The parent session must differ from the child's session;
`P` is reserved for the family's own parent. Allocate each child ordinal once in
the existing task plan. These labels never establish native lineage, ownership or
dispatch authority. Existing delegation admission remains required.

Configuration reserves the shared family code, records the current title, then
synchronizes the managed format. The same bound task cannot be configured twice. After an authorized task
replacement in the same native thread, an explicit configuration or resumption
request rebinds presentation to the new task and archives the old presentation.
The family/member identity remains stable; an existing manual-title pause survives
configuration until the user explicitly requests resumption. Unmanaged threads and unrelated chats stay outside
automatic title synchronization.

Choose the path per native thread: a bound parent does not bind its workers or
reviewers. For an already-adopted bound thread, use `task title sync` rather than
configure again. A failed runtime synchronization retains its pending state;
do not bypass it with a direct write.

For ordinary native work without a bound runtime task, use supported client
display-title controls directly after observing the actual native identity. Keep
the family/member mapping, last verified managed title, pending delivery and any
manual-title pause in the existing task plan. Apply the manual-title rules below
before every write and acknowledge delivery by readback. Resolve an uncertain
write against that same identity before retrying. Update titles during existing
milestone, phase and blocker handling using accepted plan progress. Do not create
a runtime task or runtime database, watcher or extra model turn solely for naming. This
direct path does not acquire the runtime event-repair guarantees below.

## Record status and accepted progress

For an adopted runtime-bound thread, the coordinator records a task transition when the
user's instruction, acceptance or next action changes. Discussion, design, investigation,
implementation and fixes use `WORKING`. A concrete result awaiting acceptance uses
`REVIEW`. Approval that starts another agreed phase returns to `WORKING`; it does
not complete the whole task. A neutral acknowledgment changes no state.

For required PR delivery, use [delivery completion](delivery.md#completion-and-retention).
The existing `WAITING` state covers merge waits; its reason identifies the dependency.
One or several PRs do not change the title format. A child's wait never assigns
the parent's state or progress; the parent follows its own accepted scope.

For direct display controls, use the same phase meanings in the existing task
plan without creating runtime state. For runtime-bound threads, use the existing
task update command and its revision checks. Optional
`milestones` entries are exactly `{id, weight, accepted, reference}`. IDs are
unique; weights are positive bounded integers; accepted is boolean; references
record the coordinator's acceptance decision. Keep milestones in this task plan,
including required review and integration. Do not accept a worker's self-report
as independent acceptance or count child work twice.

The title meter rounds accepted weighted progress down to completed fifths,
with at most four filled cells before `DONE`. No measurable milestones means an
empty meter. `DONE` always uses five filled cells and still requires the normal
completion evidence gate. Reopening work retains accepted milestones unless
scope or evidence invalidates them.

## Event repair and failures

Committed task, evidence and delegation commands repair an adopted title. Existing
`PostToolUse`, `Stop` and `SessionStart`/resume handlers provide additional repair
opportunities. The synchronizer uses the supported Codex App Server protocol,
without starting a model turn. Interrupt's short deadline leaves repair for the
next event. Stop does not imply completion.

Ordinary tool and stop events reuse the saved task status and skip native calls
when revisions are unchanged and no delivery is pending. Startup/resume and
explicit repair revalidate completion evidence and check for manual edits.
Task and evidence controls remain responsible for current completion authority;
a displayed title is the last delivered status, not fresh evidence.
A per-thread lock serializes participating writers. Desired titles are persisted
before writing; readback acknowledges delivery. Lost acknowledgments, changed
revisions, unavailable clients and timeouts leave repair for the next event.
There is no idle watcher, polling loop or automatic retry model turn. Presentation
failures preserve task outcomes, guard decisions and continuation limits.

Private sidecar files in the existing runtime state directory contain title
presentation and delivery metadata only. Task state and accepted milestones remain
in the authoritative task record. Historical task pins and closed evidence are
not modified by title delivery.

## Manual titles

Before an automatic write, reconcile any pending delivery and compare the current
title with the last verified managed title. Apply these rules to both direct
display-title controls and runtime synchronization. An unexplained mismatch
indicates an external change, not who made it; the user, client or another
automation may have changed the title.

- If only the topic changed and the format is unambiguous, adopt the topic and
  continue meter/status updates. Queued updates use the new topic.
- If meter, family, member, status or overall format changed, preserve the title
  and pause title synchronization for that thread. Announce the pause once.
- Resume only after an explicit user request. For runtime-bound titles, use
  `task title resume` with the current task identity, revision and decision
  reference. Optional `topic` supplies the user's intended wording; other managed
  fields come from authority. For direct controls, retain the recorded
  family/member identity and accepted plan progress, read the current title as
  the new baseline, and clear the recorded pause only for that explicit request.

Pausing title synchronization does not pause the task. A manually typed `DONE`
cannot complete work or change family identity or permissions. New turns, runtime
restarts and milestones do not silently resume title synchronization. A concurrent
manual edit can still race a native write; the client currently provides no
verified compare-and-set operation. Detect observed conflicts and preserve them.
On fresh adoption, a manual rename before the very first title observation is
indistinguishable from the initial title without native origin metadata. Do not
claim that this path detects every pre-adoption manual rename. The final
read-to-write race also remains; baseline comparison does not eliminate it.

For a runtime-bound presentation read, use `task title status`; for explicit
repair, use `task title sync`. These take only `{client, session_id}`. Configuration and
resumption require the complete identity/revision request above. Resume retains
the original family/member binding.

## Update and qualification boundary

The task vocabulary is a pinned runtime change. Legacy lowercase records remain
historical; old `ready` meant completion, while new `READY` means eligible to
begin. Do not translate old titles into task state or rewrite old records/pins.
Reconcile affected owners with their original runtime and use the existing
[approved runtime update](runtime.md#change-a-pinned-runtime) procedure with a fresh
state authority. Existing ownership and unresolved assignments remain binding.

An authorized display-format update can reconcile a saved status-last title
before rendering the current format. Preserve its family/member binding,
topic-only edits and manual-title pauses. A user changing the layout remains a
whole-format override. Do not bulk-rewrite titles, replace original runtime
readers or silently repin active tasks for a format change.

Formatting, state, command and hook-boundary tests qualify source behavior.
Installed hook trust and callback delivery, rendering and literal title search
require separate observation. A standalone rename or package validation does not
establish those capabilities.
