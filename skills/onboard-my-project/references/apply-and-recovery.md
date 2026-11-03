# Configure, activate and recover

Load this guide for authorized `apply`, `resume`, or `rollback`. Follow [Project Onboarding](../../../policies/10-project-onboarding.md) for configuration and [Project Scope](../../../policies/01-project-scope.md) for affected ownership. Load command, runtime, qualification and merge procedures only when the selected operation uses them.

## Authority and entry

The coordinator verifies actual user or standing authority for the exact operation and effects. Follow [onboarding authority](../../../policies/10-project-onboarding.md#onboarding-authority), including full-request coverage and limited-request boundaries. References, JSON and digests bind the decision but cannot authenticate intent. Keep the approved plan, manifest and original source/package pins unchanged throughout recovery.

For canonical schema 2, call [`run_verified_operation(verified_decision, plan_dir, proposal)`](../../../scripts/onboard_coordinator.py). The decision binds the operation, private plan directory, frozen plan digest and approved manifest/approval. `bookkeeping_scope` names subjects and authorities only for selected runtime bookkeeping. Omit `creation` for file configuration. The bare JSON CLI cannot supply verified coordinator authority.

Retained schema 1 uses `apply_plan`, `resume_plan`, or `rollback_plan`, or `onboard apply|resume|rollback --plan-dir PATH` with bounded JSON on stdin. Its discovery record is active; it has no configured state. Use its installed schema and active-enrollment rules. Do not translate a canonical operation into legacy deletion or invent an inactive flag.

## File configuration and undo

A file-only canonical operation contains local write/delete actions, `execution:null`, exact preimages/postimages and file-preimage recovery. Prior and proposed client entries must be configured, with no shared-policy transition. Commands, external changes, activation, prior active enrollment and shared dependencies use their scoped procedures below.

Keep seven protections:

1. Verified authority for the exact operation and effects.
2. A supported, bounded journal whose consumed effects, receipts and backups agree.
3. Correct checkout identity and safe target paths, parents and links.
4. Current bytes, modes and physical ownership matching a recorded transaction state.
5. Valid original backup bytes/modes or recorded original absence.
6. Overlapping-operation locks and checks for relevant live or uncertain writers.
7. Durable intent before mutation, atomic replacement/deletion, fsync, readback and resumable receipts.

Keep recovery material private, outside repositories and instruction discovery. Accept bounded regular files; reject unsafe links. Before mutation, preserve originals and flush the backup and prepared receipt. Record transaction-created directories before using them. Recheck mutable ownership immediately before replacement and after external actions or released locks. Advisory locks do not prevent external editors.

Rollback restores owned preimages in reverse dependency order. Preserve user edits, replacement files and uncertain ownership. Remove only recorded transaction-created empty directories. A partial rollback continues with `rollback`; `resume` continues application. Repeated completed rollback verifies the restored state and performs no duplicate effects.

Undo reads the supported journal, receipts and backups. It does not require the original executing package, available Toolkit sources, unchanged unrelated files or HEAD, machine-wide review history, native qualification, or runtime evidence republication. Preserve original provenance and retained databases/evidence. A missing or replaced previously allocated runtime leaves writer ownership uncertain and blocks affected recovery. Runtime retirement and evidence cleanup are separately scoped operations.

Configuration publishes the exact approved configured record and completes with exit 0 when its effects succeed. It grants no managed task readiness. Use `runtime:null` when runtime state is not needed; a planned runtime location does not create a database. Defer database birth until an explicitly selected managed-runtime preparation/activation operation requires it.

## Apply selected setup changes

Use the plan-pinned Toolkit procedures for setup actions that need them. Preserve complete catalog assessment and mandatory coverage; do not rebuild assessment during undo. Missing sources block only dependent setup actions. Apply compatible dependency groups, preserve product behavior, data, customizations, local changes and the current stack. Check relevant versions, peers, engines and lockfiles before dependency changes. Reuse verified equivalents. No forced installs, automatic audit downgrades, redundant dependencies or framework/provider migration to match examples.

Major incompatibilities, migrations, new costs, destructive or out-of-project changes require authority covering those effects. A reviewed section label does not authorize losing other content. Metadata-only inventory is not an exact preimage or recovery backup. Safe reruns preserve existing sections and registrations.

## Commands, active runtime and shared changes

Commands require exact bounded effects/resources, preconditions and a concrete recovery method. Persist attempt identity and retain exclusion while running. Reconcile the command and all writable descendants before completion, rollback or replay; uncertain termination remains pending. Never perform generic command rollback or blind replay. Require proven idempotency before replay. Missing proof blocks dependent work only.

Active runtime and shared-policy changes retain their existing authority, source identity, current permission, dependency and affected-writer checks. Preserve unrelated members and history. Suspend only owned affected active entries before changing supporting configuration. Restore prior active enrollment only after fresh compatibility and stopped-writer proof. Later joins, external authority changes or unresolved shared consumers require scoped reconciliation. File-only recovery cannot bypass these controls.

Explicit runtime preparation uses owned D4 birth for an absent database, original baseline and receipts. Startup and task start never create it. This is a separate effect requiring explicit scope; it is not a prerequisite for file configuration or undo.

## Activation and reporting

### Staged disposable qualification

Use staged acceptance only for an explicitly approved disposable qualification target. Ordinary projects and the primary pilot retain full activation prerequisites. Observe the actual selected frontend, source identity, relevant configuration and host safety before startup acceptance. These observations do not establish the Toolkit bound-task guard, PostToolUse, Stop, Interrupt or other unobserved behaviors. Keep all nine behavior cases and the complete actual manifest/catalog requirements recorded as verified, pending or evidenced inapplicable; the pilot's 44 requirements are not a product-wide fixed count.

Pass genuine Native-issued frontend witnesses and independently verified assessments separately from proposal JSON. The existing D4 owner retains immutable setup receipts and approved attempt scope in its private journal. Each upgrade uses a new exact D4 operation and references its predecessor; preserve original receipts, source pins and recovery material. Later startup compares bounded local observable configuration, without native subprocesses or per-session frontend proof.

For vendor-owned native state, use `CoordinatorOperationOwner.observe_native_source(identity, attempt_ref, observer)` with the independently verified original allocation, explicit external effects and manual serialization. The same D4 journal retains its claim before the owner launches the exact child; failures consume the allocation and uncertain descendants retain exclusion. Reconcile that exact claim with independently verified direct-child and descendant-stop evidence through `reconcile_native_source`. This path grants no project-file recovery exemption. Retained managed command observations keep their original effect and recovery rules.

The CLI keeps closed stdin and retains only its actual header/source, executable and non-secret launch facts. A separately approved metadata allocation and pinned journal may consume the reconciled CLI reference. Its app-server reads only the existing CLI thread and actual registration/configuration origins; it cannot create or resume a thread. Keep raw metadata transient and retain only Core's filtered setup observation. Native hook enumeration can initialize user `.hook-trust` baselines, including unrelated enumerated plugins. The actual campaign must authorize those vendor-owned effects; source implementation or repository-local command authorization supplies no permission to execute them.

The trusted coordinator supplies `qualification_scope` separately from proposal JSON. Only its exact live callback process can acquire observation authority. `collect_setup` consumes Native's private witness plus independently verified assessment. New external observations use the existing journal's `native_observations` claims; preserve older `command.setup_capture` and full setup receipts unchanged. After exact stop reconciliation, `collect_retained_setup` constructs a successor for a separately verified activation operation. Preserve original native transactions and typed source references; a full receipt predecessor references only another full setup receipt. Never alter the approved manifest to insert a learned receipt hash.

Bootstrap acceptance requires actual native frontend/configuration provenance, the source-backed submitted-write policy rejection and independent original writable-canary before/after facts. Claim only that native policy rejected the submitted write: this does not prove effective-input identity, protection of a particular canary or local operating-system enforcement. Keep this native safety assessment separate from all nine Toolkit cases. Qualification-only SessionStart supplies restricted context and creates no task or title-repair effect. Ordinary basic work requires genuinely verified Toolkit startup and pre-tool behavior; editing additionally requires post-tool behavior. Supported managed observations use the actual parent task stream, retained assignment before-artifact and independently read receipts/generation; child-stream behavior remains pending.

Until the Toolkit guard is genuinely verified, admit only its exact bounded qualification attempt. Pending capabilities remain blocked for ordinary dependent use. Bind the attempt to the approved disposable repository/checkout, actual task and native identities, permitted operations, original finite budgets, claims and stopping condition. Admission uses existing task/assignment accounting; it cannot reset consumed limits. Expiry, exhaustion or interruption stops further effects, preserves uncertain writer claims and requires separately authorized recovery.

A qualification task keeps its purpose even after capability evidence improves. Canary outcomes may support only their verified qualification entries; they cannot become ordinary READY, DONE, publication, merge or primary activation authority. Successful onboarding still requires all actual applicable requirements, reviews and repository enforcement. Report startup acceptance, pending capabilities and full onboarding separately.

Ordinary activation requires qualified mandatory adoption, native mechanisms and applicable repository enforcement. Configured hooks, valid record shape and stored labels do not prove actual client execution. Use an authorized disposable scope for native evaluation; preserve its actual budgets and settings. Report package/helper validation separately from native observations.

For Codex, use the [approved activation guarantee](../../../policies/01-project-scope.md#authority-and-activation): preserve actual setup behavioral evidence and compare later observable configuration. Do not claim proof of each later session's loaded controls or repeat setup solely because a new session starts. A changed or missing required observation leaves dependent activation pending.

Canonical activation observations use `{manifest_digest,input_digest,qualification,task_reconciliation,prior_compatibility,command_reconciliation}`. All four collections are lists. Bind current input through `changes._scoped_input_digest(manifest)`. Each qualification row names `repository_id`, `checkout_id`, `client`, requirement evidence, general/security review evidence and `scope_observations`. Reconciliation rows bind the affected member, state directory and evidence; command rows bind `id`, `attempt_id`, `stopped:true` and evidence. Follow the installed `_scoped_observation_shape` and `_scoped_qualification` schemas. Observations supplement evidence; they cannot change approved effects.

An approved configured postimage needs a separate exact activation operation. Verify that existing onboarding authority covers its effects, including any runtime allocation; ask only when the authority rules identify a missing material decision. Never widen the original frozen manifest or reuse its effect digest for changed effects. An already approved active postimage may resume with fresh qualification observations under its existing approval. Missing mandatory activation evidence returns pending, not a false success. Native restart, login or trust interventions remain pending until observed. These instructions do not supply the production qualification reader or substitute recorded claims for trusted observations.

Update the [Reviewed Configuration](reviewed-configuration.md) with actual changes, preserved conflicts, operation state and the next required action. Exit 0 means the selected operation completed; nonzero means invalid, blocked or partial work. Successful configuration or rollback does not mean runtime activation, qualified client execution or merge readiness.
