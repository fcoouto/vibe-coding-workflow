# Bounded D6 managed-lifecycle pilot plan

**Status: on hold.** The user authorized this plan, including role-mapping
planning. Installation, trust changes, runtime preparation/activation and live
qualification are not authorized. Current live execution allowance is **zero**.
The limits below are proposed ceilings for a later, explicitly released packet;
neither this document nor a passing fixture supplies that release.
The Lima/Docker preflight is retired. Managed writable handoffs remain
blocked on effective native tool restrictions and independent stop evidence.

**Goal:** observe one managed Codex CLI coordinator, one leaf worker and one
independent reviewer, with admission before launch and independently verified
ownership reconciliation. Report a bounded result without claiming full D6 release.

**Architecture:** reuse D4 setup/birth/recovery, the D6 assignment ledger and native
observer, and D5 checks/review/verification. The coordinator uses its actual native
delegation tool. Add no launcher, scheduler, state registry or substitute proof.

**Tech stack:** Python 3.11+, existing package controls and the selected native
Codex account. CLI and Desktop are separate qualification targets.

**Spec:** [D6 requirements](../../d6-native-delegation-plan.md),
[current runtime](../../../clients/runtime.md),
[native delegation](../../../clients/delegation.md) and
[staged qualification](../../../skills/onboard-my-project/references/qualification.md).
The historical D6 implementation sequence does not override current schemas.

## 1. Source and preservation boundary

The original reviewed plan used main as observed on 3 November 2026.

| Identity | Baseline |
| --- | --- |
| Main commit | `13d409dfbe571a35ae015ff10d696a1cca191e48` (PR64) |
| Git tree | `5f628fd0a440fca35272bfedc89bb678c2455351` |
| Package version | `0.1.2`; version alone does not establish matching contents |
| Policy digest | `1ab48d6f72b59027fa072f25b51b717df67466227964ec5070f00eb1adcdab6b` |
| Runtime digest | `6915ddd4d8c92cf7705766846854bd7579c6538a5b065cd488f194dc9ab5d268` |
| Current schemas | Canonical Project authority 2; runtime configuration and SQLite 3 |
| Existing software evidence | PR64 records cumulative 207/207 selected cases; this is not native qualification or a repository-wide suite |

### 4 November 2026 offline checkpoint

[PR #78](https://github.com/fcoouto/vibe-coding-workflow/pull/78) merged into
`main` as `4ec6860458a5963c3595f10f6f802e80e4023caf`. The reviewed fix is
`a020394868d1b9032fce9bf67354bb188d4823c1`. Record the merged source as the
offline evidence checkpoint. A future release requires its own exact pins.

| Identity | PR #78 checkpoint |
| --- | --- |
| Git tree | `2c785936422247953971b1c3d82859a624eaf12e` |
| Source package version | `0.1.8` |
| Source policy digest | `12a8ecdf666fd6408a510008a4c0e2c7eb906f41b3b9b371b62a4c362cd6607e` |
| Source runtime digest | `c15e071395a0e7439feffed86c24027d503cd2119c43bcd03b79998bf136ca1a` |

The regression first reproduced the legitimate child's denial through the
hook and owner code with a disposable native transport fixture. The fix admits
the exact observed child and turn for the approved one-file canary, denies
unbound or foreign children, mismatched turns and out-of-scope patches, and
binds the PostToolUse receipt to the same child, turn, call and assignment.

All 272 affected tests passed (51 native-hook, frontend-witness
and manifest tests, 214 runtime, qualification, admission, delegation and
readiness tests, and 7 retention and linked-closure tests). Package validation
and diff checks passed. Independent behavior and security review cleared the
reviewed diff after focused rechecks. Two focused regressions and package
validation passed again before merge. Full discovery was superseded by the
affected-suite runs. Live managed child hook delivery and stop proof remain
unverified.

Recheck main, package contents, applicable instructions and observed capabilities
before release. A changed relevant source requires a reviewed successor packet and
affected checks. Never overwrite original pins, receipts, consumed limits or old
evidence. Installation must not replace a same-version cache used by another task.

Use one new public-data canary repository and its explicit standalone membership,
one fresh private runtime authority, one private D4 journal and a frozen package
copy. Exact canonical paths, physical bindings and native configuration effects
belong in the release packet. No parent/sibling enrollment or future auto-joining.
Preserve primary WIP, all other worktrees, installed packages, native homes and
existing authority/evidence. Do not hide or move machine history to force absence;
D4 must use genuine ready history or its genuine version-2 absence witness.

## 2. Role mapping: existing contract and next source slice

The [OpenRouter procedure](../../../skills/openrouter-workers/references/procedure.md#prepare)
already requires the supervisor assignment's explicit role and specialty. Its
[brief](../../../skills/openrouter-workers/references/procedure.md#run) carries
`role`, `specialty`, `model_display_name` and the actual coordinator UUID. Current
Habblaud presentation is `Role · Model Display Name`; specialty is separate metadata.
The earlier OpenRouter implementation plan is retained in the primary checkout,
outside this main baseline; do not import that older branch or superseded controls.

Current OpenRouter worker roles are `Scout`, `Builder`, `Tester`, `Reviewer`,
`Scribe` and `Investigator`. These are validated roles, not arbitrary custom names.
The installed local-delegation visibility contract also has `Coordinator` and
requires explicit assignment labels rather than inference from names or models.
At the original planning baseline, the review found no separate
`custom_role_name` contract or native D6-to-Habblaud binding. Shared worker
roles subsequently landed in [PR #70](https://github.com/fcoouto/vibe-coding-workflow/pull/70).
Its [retained observations](2026-11-03-shared-worker-roles.md) cover bounded
Desktop and OpenRouter receiver behavior. Managed CLI display still needs its
own evidence if selected.

**Original source requirement for the optional Habblaud check.** Carry the declared
workflow role and specialty through native D6 admission and observer binding,
reusing the existing visibility transport. Keep D6 authority roles (`worker`,
`review`, `coordinator`, `check`) distinct from presentation responsibility:

| Assignment | Declared presentation role for this pilot |
| --- | --- |
| Coordinator | `Coordinator` |
| Canary implementation worker | `Builder` |
| Independent review | `Reviewer` |

Other assignments must declare their actual responsibility; do not label every
worker Builder. Record any task-specific custom role name separately from the
canonical role and specialty. Decide its supported field and visible presentation
with the adapter contract before implementation: current badges do not display
specialty, and current validators do not accept arbitrary role names. Do not
silently substitute or discard a user-declared custom name.
Use versioned, compatible metadata without rewriting existing admissions or
sticky observer bindings; this does not promise retroactive relabeling.

### Shared mechanism for every worker path

The user's requirement covers **all native and OpenRouter workers**, not only the
three roles in this canary. Use one semantic declaration contract and reuse each
route's existing adapter; do not build separate naming policies or a new registry.

| Path | Required source coverage |
| --- | --- |
| Ordinary native delegation | Declare metadata in its existing task/assignment context; bind the real native child without requiring enrollment or a managed runtime database. |
| Managed D6 workers and D5 reviewers | Preserve native admission, actual identity and D5/D6 digest domains; presentation cannot change their authority role. |
| OpenRouter/OpenCode workers | Carry the same declared role, specialty and custom name from the frozen external brief to Habblaud; retain the actual external model/provider and genuine supervisor identity. |
| Native supervisors, continuations and approved fallback | Keep each real assignment's labels and lineage through handoff/recovery. Preserve existing identities for continuation/recovery; bind a new actual identity only when a genuine new attempt or fallback creates one. Never fabricate a native replacement. |
| Other already-approved worker adapters | Preserve the same contract before claiming display parity; this requirement enables no additional execution route. |

New visibility-enabled assignments must declare their canonical `role`,
`specialty` and `custom_role_name` when explicitly supplied. Use the
[versioned assignment metadata](../../../clients/worker-visibility.md). The
custom name must reach visible role text and full accessible text when the UI
clips it. Keep the canonical role and specialty separate. Without a custom name, preserve
the existing `Role · Model Display Name` convention. Unsupported display
capabilities or missing labels stay explicit; do not guess a role or silently
substitute a generic Worker badge.

Required source tests must cover the complete path matrix; different declared
roles on the same model; the same role on different models; custom-name
round-tripping, Unicode/length/rejection cases; first-binding ordering; replay
without duplicate characters; preserved labels through approved fallback and
continuation; truthful supervisor/external identities; and legacy unknown labels.
Visibility failure must leave execution, permissions, saved route choices,
provider/model settings and acceptance unchanged. A missing required display
observation blocks that display claim, not unrelated ordinary work. Test external
forwarding with offline fixtures; no OpenRouter call is authorized by this plan.

Source acceptance must cover declared role/specialty/custom-name preservation for
native and already-approved OpenRouter assignments; immutable task markers and
actual parent/child identities; unsupported-name diagnostics; and unchanged model,
provider, permissions, budgets and acceptance. Declare labels before dispatch and
bind them before the first observer registration, because first visible labels
are sticky. Prove that ordering; renaming a title afterward is not a substitute.
Emit nothing for a proposed or failed-to-launch child and create no synthetic
native log. Use only sanitized existing transport metadata, never prompts or code.

This plan authorizes neither that implementation nor Habblaud/OpenRouter activation.
Habblaud verification is an optional, separately selected display check; its
failure cannot become false execution failure or success. OpenRouter inference,
credentials, spending and live qualification remain outside the native D6 pilot.
A release that selects display must pin the actual role binding and verify
first managed CLI display. The base lifecycle pilot does not require Habblaud.

## 3. Required go/no-go checks before any managed child launch

| Gate | Required evidence; otherwise hold dependent work |
| --- | --- |
| Exact target and authority | Frozen canary/package/journal paths and original D4 effects; fresh schema-3 state through supported D4 birth; current pins and physical membership. Birth alone grants no qualification. |
| Native frontend and authentication | Actual CLI executable/surface, account route, creation provenance, supported native spawn/catalog/observation controls and compatible guidance. Preserve the user's coordinator model, reasoning, provider and authentication. No credential copying, proxy, billing or global configuration change. |
| Staged admission and guards | Genuine setup witnesses and an exact qualification-purpose attempt; current startup/pre-tool and, for editing, post-tool evidence for the selected path. PR #78 provides offline child-guard coverage. The release packet must identify the staged path to genuine child PreToolUse and PostToolUse evidence. A stored label or fixture cannot supply it. |
| Independent stop source | Identify a qualified method that can prove the exact worker/reviewer/check and every writable descendant stopped. Per-attempt evidence is collected after execution; the method must exist before launch. |
| Actual isolation and ownership | One known shared authority, exact file/Git/resource claims, no conflicting or uncertain owners, and effective restrictions for the exact native child. The proposed worker uses one synchronous canonical patch and read-only tools. Shell, code execution, mutable connectors, and nested worker routes must be unavailable. Missing or unknown restrictions block launch. |
| Capacity and settings | Observe available capacity and suitable native selection/inheritance. Keep requested, configured, spawn-observed and execution settings separate; unknown stays unknown. No non-native fallback. |
| Display, only if selected | Reviewed native role binding and an explicitly approved existing Habblaud connection. Custom-name support must be demonstrated, not assumed from the badge. |

**Known stop-evidence gap:** the adapter deliberately returns
`descendants_stopped=False` and unknown execution model/effort. A completed turn,
interrupt/close acknowledgement, parent exit or empty process group is insufficient.
[Version-2 reconciliation](../../../clients/delegation-proofs.md) needs independent
exact-identity and stopped-descendant evidence. The limited
`bounded-native-source-v1` setup closure does not relax D6 reconciliation.
If no genuine source exists, finish preflight as **blocked/unqualified** without
launching workers. Resolving a missing host capability is separate source work,
not an excuse to spend this pilot debugging or to fabricate proof flags.

## 4. Proposed finite ceilings for one future CLI release

| Resource | Hard admission/protocol ceiling |
| --- | --- |
| Overall window | 60 minutes from the first authorized campaign effect; one absolute deadline |
| Phase windows | Read-only preflight 10 min; controlled setup/bootstrap 15 min; managed scenario 20 min; reconciliation/report 15 min. These sum to 60, not extra time. |
| Native contexts | One coordinator and two children total; worker and reviewer run sequentially |
| New model turns | At most five: coordinator bootstrap/scenario/closure at most three; worker one; reviewer one |
| Native attempts/resources | D6 `max_attempts=2`, `max_resource_units=2`; each child consumes one unit; each native job `max_attempts=1` |
| Concurrency | `max_parallel_workers=1`; record actual host capacity and evidence of an available slot; do not relabel physical capacity as one |
| Original qualification allocation | At most eight unique admitted ledger operations and two resource units, including applicable check/coordinator history; verifier-barrier accounting follows current source |
| Child windows | Worker 5 min; reviewer 7 min, both inside the managed-scenario window |
| Review | One independent review round; blocking findings end this pilot rather than start a fix/retry campaign |
| Checks | At most three D5 check executions and two worker self-check commands; each exact canary command has a 10-second timeout |
| Control traffic | At most 32 D5/D6 control requests, including at most 12 status/observation acquisitions; denied probes and replays count as requests |
| Replay/negative cases | Two prepare replays, one blocked check-conflict request and one missing-stop-evidence reconciliation request; no extra native send |
| Retries and replacements | Zero; no child continuation, replacement, nested agent, fallback route or automatic Stop continuation |
| Reports | At most 8 KiB each, validated without truncating evidence into success; reuse existing artifact/output and retention limits |

Before release, bind these ceilings into the actual D4 qualification allocation,
D5 plan and D6 plan, and verify the exact operation schedule fits all three. D6's
native counters differ from the qualification allocation's check/coordinator
history; do not copy one counter into the other. If the packet does not fit, revise
and review it before release, never inflate a live budget. Unused slots authorize
no extra job or attempt. Each planned model turn has one purpose, not a retry pool.

Timeouts limit new effects/admission; they do not kill or prove stopped writers.
Native token/currency limits are not claimed where the frontend cannot enforce
them. Record observed usage only. Do not change models or authentication to obtain
more capacity. At expiry stop new effects; preserve unresolved claims, consumed
budgets and evidence. Further recovery needs its own existing or separately scoped
authority, not a new run ID, state directory or reset deadline.

## 5. Future sequence and acceptance

Every step below is **not run**. The owner is the coordinator unless stated.

1. **Freeze the release packet.** Record current source/pins, actual client and
   guidance, explicit allowed effects, target/native identities, operation
   schedule, deadlines, checks and recovery. Keep catalog/behavior requirements
   verified, pending or evidenced inapplicable; do not invent a fixed requirement
   count. Review actual native-home and hook-trust effects before any release.
2. **Prepare one disposable scope.** Only after release, perform its exact D4
   setup/birth and genuine staged bootstrap. Do not copy credentials or historical
   successful receipts. Use qualification-purpose admission, not ordinary
   activation. A required restart, login, trust intervention or unavailable source
   remains pending until genuinely observed within the approved effects.
3. **Freeze the public canary.** `canary.py` initially returns `0`; the immutable
   `test_canary.py` requires `42`. The worker may change only `canary.py`; the test,
   instructions, configuration, Git and evidence are coordinator-owned. Accept
   the D5 plan before the immutable D6 plan. Record the real failing baseline as
   baseline evidence, never as a passing acceptance check.
4. **Reserve once and test exclusion.** Prepare `worker-edit` with one stable
   dispatch ID and exact claims. Replay that preparation before and after the
   actual launch: same admission/identity, no renewed launch permit or counters.
   While its write claim is held, request the already-planned read-only D5 canary
   check. Require a resource-conflict refusal before command execution; do not
   attribute a native-capacity refusal to path exclusion. No second child is sent.
5. **Run one worker.** Use only the actual once-only native launch permit, exact
   `worker_<attempt_id>` marker and prompt. The worker observes the failing check,
   makes the one-file fix, runs its passing self-check and returns the required
   bounded report. Parent/turn/spawn/child/origin/candidate identities must bind
   to the admission. Encrypted native prompt delivery remains unverified.
6. **Prove uncertainty and reconcile.** Completion metadata alone must not release
   claims. A reconciliation request without genuine stop proof must reject or
   retain uncertainty without new permission. Then independently inspect effects,
   current candidate and real stop/descendant evidence; submit the exact original
   version-2 proof and assessment. Missing proof blocks the reviewer and retains
   claims. Never manufacture `not-started` from missing history.
7. **Run the accepted check and independent reviewer.** After worker reconciliation,
   execute the planned D5 canary check. Use only D5 `evidence review prepare` for
   the read-only `review` job, dependent on `worker-edit`. Preserve the D5 plaintext
   assignment digest separately from the D6 ledger digest. The reviewer covers
   general/behavior/security impact, changes nothing, and runs one bounded turn.
   Observe, collect, assess and independently reconcile its actual stop/effects.
8. **Verify the final candidate.** Run the final planned check, compare the exact
   candidate, policy, review and all relevant settled claims, and use D5's verifier.
   A qualification-purpose result remains qualification evidence: ordinary
   `verified`, `implementation_verified`, READY, DONE, publication/merge and primary
   activation do not become available. Record explicit partial results if blocked.
9. **Reconcile and report.** Keep any partial canary edits and original receipts.
   Use supported file-only undo only for owned matching outputs and authorized
   recovery effects; preserve later edits and runtime history. Do not delete the
   fixture/native home or clear uncertain owners to make cleanup look complete.

| Acceptance ID | Required independent observation |
| --- | --- |
| A1 — source/scope | Exact source, installed contents, current schemas, identities and genuine qualified admission match the frozen release. |
| A2 — once-only | One worker and one reviewer native start; prepare replays supply no additional permit, budget or context. |
| A3 — exclusion | The planned check conflicts with the held writer, starts no command and changes no accepted evidence/ownership counters. |
| A4 — result | Real initial failure, exact one-file fix and independently accepted final passing canary command; no unexplained effects. |
| A5 — reconciliation | Missing stop proof retains ownership; genuine exact per-attempt proof is required before releasing claims or starting dependent work. |
| A6 — independent review | Genuine different child, D5/D6 digest domains preserved, reviewed bytes unchanged, findings independently assessed. |
| A7 — preservation | Primary/unrelated work, native settings/auth, old pins/history and saved optional feature choices unchanged. |
| A8 — bounds | Every effect fits its original wall, model-turn, admission, command and review limits; no resets or hidden replacement. |
| A9 — visibility, if selected | Actual CLI children receive declared role/custom-name metadata through the approved native adapter before first display binding; no guessed roles or fake native agents. OpenRouter forwarding is assessed offline in its source slice, not natively qualified by this pilot. |
| A10 — honest outcome | Separate software checks, native source observations, scoped pilot coverage, pending requirements and unresolved ownership; no full-D6/other-surface claim. |

## 6. Evidence, exclusions and completion

Use existing private D4/D5 artifacts outside repositories and plugin/cache trees.
Retain source/command/check identities, original and current candidate digests,
admission/replay/conflict receipts, actual native identities/settings, per-attempt
stop evidence, reviewed bytes, findings, counters and supported recovery records.
No raw transcript, prompt, source dump, credential or private accounting enters
public docs or Habblaud. Existing Project caps/retention remain; uncertainty is not
deleted to fit a limit. The final public summary belongs in `docs/d6-validation.md`
only after actual observations exist, with source/surface-specific limits.

This first pilot excludes Desktop/Claude qualification, parallel native children,
crash/ambiguous-native-send fault injection, cross-authority/shared-service races,
legacy migration/repinning, D7 enforcement, D9 campaigns/usage collection, external
models, telemetry, automatic cleanup and release publication. Existing software
tests do not become native evidence for those cases. Full D6 completion retains
its full-suite and broader native requirements; this bounded attempt cannot waive
an applicable mandatory prerequisite or certify complete onboarding.

### What remains before resumption

The 3 November probes remain historical observations for their original
environment. Preserve the earlier failed D4 claim for reconciliation under
its original authority.

1. **Check native controls read-only.** Determine whether the exact frontend
   can enforce the patch-only worker described in §3. If the controls are
   unavailable or unverified, leave writable managed D6 on hold. Record the
   capability finding in the [successor packet](2026-11-04-d6-successor-release-packet.md#independent-stop-proof).
2. **Freeze and independently review a successor packet if the route is supported.**
   Bind the current package and selected CLI to one disposable checkout, one
   private D4 journal and authority, the actual hook trust and supported account route, exact
   claims and the original finite limits. Confirm that the selected route's
   egress, isolation, capacity and operation schedule meet the gate in §3.
3. **Establish an independent stop source before managed dispatch.** Bind the
   trusted observer to exact phase and operation identities. Collect actual
   version-2 proof that the admitted operation and its writable descendants
   stopped before releasing its claims or advancing.
4. **Define the staged native guard proof.** Use the exact supported CLI and
   tool route to observe D4 bootstrap, same-parent managed continuation, the
   admitted and denied child patch calls, and the successful assignment-bound
   PostToolUse receipt. Observe the canonical `apply_patch` callback. A
   code-mode or sandbox rejection alone cannot establish managed guard
   delivery. The current reader uses the parent
   stream for the pre-tool enforcement witness and the child stream for the
   paired post-tool witness. Specify how to retain independently verifiable
   child denial evidence. Resolve any missing reader or callback capability
   before relying on it. If Habblaud is selected, add its separate first
   managed CLI display check.
5. **Obtain explicit release for the exact packet before any live effect.**
   Until release, the live allowance is zero. After release, run only the
   authorized staged qualification. Stop at the first unresolved go/no-go
   condition and retain original claims, evidence and consumed limits.

No live pilot step has run. The pilot remains on hold.
