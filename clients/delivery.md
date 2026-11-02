# Delivery workspace and publication controls

Load this contract for delivery preparation, publication, merge reconciliation or remote cleanup. Follow the applicable scope, planning, evidence and merge policies. Naming remains in the existing Thread Naming contracts.

## Prepare the destination

Separate implementation worktrees are the default; preserve an explicit opt-out. Read-only inspection needs no new checkout. Inspect native attachments first and reuse a suitable task-owned worktree. Otherwise use the client's supported native creation tool, retain its returned operation and attachment identity, and continue at the returned directory. After a lost creation response, inspect native status/attachments; unresolved ownership never permits blind duplicate creation. Native client storage and cleanup remain client-owned.

Discover the actual Git repository and common directory independently of the native attachment. Reload applicable instructions in the destination. For managed workflow tasks, admit that exact checkout/client through existing onboarding before starting its editable task; never transplant the source task's accepted identity. Ordinary unenrolled source development does not imply managed activation.

## Bind an admitted workspace

The callable `scripts.delivery_coordinator.DeliveryOperationOwner` binds an independently verified host decision to exact scope, action and request digest. It has no JSON CLI, default native source or authority to manufacture admission. Host observations and decision references bind facts; the caller must independently establish their source and meaning.

After recording the task delivery plan, `owner.run(scope, 'bind-worktree', request)` takes the existing task identity/revision plus stable `operation_id`. Its native source supplies `observe_worktree(root)` with actual root, client owner, native attachment and observation reference. The package independently observes Git identity and HEAD, then commits immutable workspace evidence through existing task/artifact storage. An unresolved or foreign attachment cannot bind. An exact completed replay returns the existing binding; changed inputs cannot reuse that identity. No transaction spans native observation.

This binding creates no worktree, edits no product file, grants no dispatch/merge permission and performs no cleanup. Publication remains unavailable until its implementation and evidence requirements are satisfied. Do not treat a software fixture or a manually supplied observation as live client qualification.

## Completion and retention

An editable task under an adopted delivery policy needs an explicit delivery scope decision, including when no PR is needed. Completion consumes its retained plan; a caller's merge claim or title cannot satisfy it. Local proof remains `implementation_verified` when delivery is pending. `verified` answers the requested overall completion; `delivery_complete` answers delivery alone. `merge-evidence` checks implementation without requiring that a merge already happened.

Only after all independent accepted work passes, required pending delivery sets the task to `WAITING` with its specific merge condition. While other work can advance, keep the actual working/review state. Existing Thread Naming renders this state below five cells; no provider call occurs during rendering. An accepted parent scope includes its required companions and integration; children do not assign the parent's state or meter.

Preserve pending delivery and recovery evidence through cancellation and retention. Resolve the specific wait through existing `resolution_ref` handling before another completion verification; unrelated decisions, blockers and explicit pauses remain effective. Publication/reconciliation is still under implementation, so a required publication remains pending until its qualified observation path is available. Do not substitute synthetic proof to clear it.

## Inspect pending delivery

`python3 -B scripts/workflow.py delivery status --cwd PATH --client codex --session SESSION` returns the current task's retained scope and requirements. `delivery pending --cwd PATH --client codex` inspects at most 32 known task records in that authority. Optional `--cursor` continues the same authority; `--limit` is between 1 and 32. A non-null cursor means more known records remain, even when this page has no pending deliveries. No page claims to discover unknown PRs or inventories in other authorities.

These controls call no provider, scan no checkout and perform no cleanup. Pending inventory can read the original task's retained facts after a client removes its checkout, through a surviving admitted checkout in the same authority. Missing current local proof still prevents claiming fresh completion. Public JSON/CLI cannot submit merged facts or invoke a delivery mutation.
