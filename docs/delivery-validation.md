# Delivery lifecycle implementation evidence

2 November 2026. Implementation branch: `codex/delivery-lifecycle`, based on fetched main `44de11fa14bb2dddef02a3fbabb521d9bc10ecc4`. The [implementation plan](superpowers/plans/2026-11-02-delivery-lifecycle.md) remains the execution scope. Main `5a6bcd2c5d882c8e777b29b549f391eb9a09af75` was integrated after the user confirmed onboarding rollback. This record separates source/fixture progress from production qualification; end-to-end delivery is still in progress.

## Implemented source behavior

Canonical repositories can explicitly adopt a version-1 `delivery_policy` containing merge mode, separate-worktree preference, exact targets/methods and separate authorization references. Policy participates in the accepted scope digest and existing D4 postimage/recovery machinery. Historical records without that field retain their original meaning; no machine enrollment or active runtime was updated.

`runtime.delivery` validates the policy and task override, records one task-owned delivery plan as a managed artifact, and returns local status/completion requirements. Empty publication scope is an explicit decision; an editable task under an adopted policy without that decision reports a blocker. Read-only work requires no delivery decision. Submitted policy values, targets, publication dependencies and history are bounded and validated. These references bind decisions but cannot authenticate publication or merge authority.

Admitted workspace binding now records independently observed native attachment and physical Git identity, including protection against replacement of the accepted checkout. Exact replay preserves its original binding; the coordinator source participates in runtime pins. A bounded read-only GitHub adapter validates repository/PR/ref identities and merged facts. Checks and reviews remain unobserved. Provider publication, manual-merge reconciliation, agent merging and remote cleanup remain in progress; these slices alone do not enforce the full lifecycle.

## Tests and independent review

- `python3 -B -m unittest tests.test_delivery tests.test_delivery_coordinator tests.test_github_delivery -q`: **25 passed** (33.879 seconds). The original adoption subset contains **11 passing tests**, including strict embedded policy types, task-policy isolation, canonical identity binding, actual fixture D4 adoption, read-only/no-publication behavior, rejection of policy edits against pinned tasks, and preservation of policy/allocation after interrupted D4 birth.
- `python3 -B -m unittest tests.test_startup tests.test_onboarding tests.test_changes tests.test_state -q`: **192 tests, 4 failures and 22 errors**. The reported failures/errors are all in `tests.test_onboarding.OnboardingTests`.
- An immutable `git archive HEAD` baseline reproduced the complete onboarding result: `python3 -B -m unittest tests.test_onboarding -q`: **29 tests, the same 4 failures and 22 errors**, with identical test/subcase identities. Inspection returns revision 2 while these tests expect revision 1 or submit a stale revision. The unrelated screening/revision behavior was not changed to clear this gate.
- `python3 -B scripts/validate.py` and `git diff --check`: **passed**.

The initial focused tests failed before implementation. Fresh native read-only review found two defects: Python boolean/integer equality could bypass embedded-policy validation, and read-only tasks could report incomplete delivery without a requirement. Both received observed failing regressions, fixes, and a scoped independent recheck. The reviewer found no related regression. Requested review settings were the current native model at high reasoning; no external provider or local-model route was used. Review execution was observed through native delegation; model internals are not claimed as independently measured.

Private test logs, failure identity comparison, selection guidance and progress are retained in this plan's ignored `.superpowers/sdd/2026-11-02-delivery-lifecycle/` workspace. Passing package checks and synthetic owner qualification do not establish native-client execution or repository enforcement. The full suite was not run for this incomplete source slice.

## Representative instruction paths

| Task | Applicable path and observed result |
| --- | --- |
| Onboard delivery defaults or preserve an opt-out | Policy 10 and the onboarding procedure describe explicit canonical adoption. Pure/actual D4 fixtures accept valid policy, retain `separate_worktrees:false`, bind the projection, and preserve the manifest after interruption. Routine task execution does not load Toolkit or this provenance record. |
| Record a task-specific merge override | Policy 02 and `effective_policy` keep saved policy unchanged and require a decision reference. Changing the effective mode cannot fabricate target merge authority. |
| Inspect a delivery decision or read-only task | `operate(..., 'status', ...)` reads local task/artifact state. No provider operation, worktree creation or cleanup is called. Read-only tasks report no pending delivery requirement. |
| Start implementation in a new native worktree | Not yet qualified. Existing native creation tools do not admit the checkout into canonical runtime state. Source and destination tasks must keep distinct accepted identities. |

## Native admission prerequisite

Independent interface review established the safe sequence: inspect native attachments; create/adopt a worktree through the native owner outside SQLite transactions; independently observe Git identity; reacquire from the destination; enroll its exact checkout/client through D3/D4 with actual qualification; only then start a distinct editable task and record its workspace evidence. A lost native-create result requires discovery; the available create tool has no caller idempotency key, so unresolved outcomes cannot be retried blindly.

Current `scripts/workflow.py` calls canonical entry acquisition without a production qualifier. The Codex adapter observes delegated worker/reviewer execution, not managed-worktree ownership/create recovery; the Claude adapter does not supply that source either. Starting an editable source task before D4 adoption would also create an affected writer that needs exact stop reconciliation. Read-only preparation cannot acquire mutable coordinator claims as a workaround.

Production native-client admission remains a prerequisite to live managed workspace binding. It is not a prerequisite to ordinary source/fixture development. After the user confirmed onboarding rollback, the pilot owner confirmed both owned onboarding files absent and installed entry resolution `outside/not_enrolled`. The branch resumed source work and integrated current main. No enrollment or live activation was performed. Native qualification and D7 production-source/enforcement remain prerequisites for live READY and agent merge; synthetic fixtures do not supply them. No watcher was configured.

## Provider read boundary

Independent review reproduced and fixed invalid expected-ref handling and subprocess timeout sanitization. Eight provider tests pass independently. Requests explicitly select GitHub API version `2022-11-28`, which retains `merge_commit_sha`; the [2026 breaking changes](https://docs.github.com/en/rest/about-the-rest-api/breaking-changes) remove that field from newer PR responses. The [versioning contract](https://docs.github.com/en/rest/about-the-rest-api/api-versions) documents explicit version headers. An unsupported or unavailable response remains pending, never inferred success. No live provider request or credential change was performed.

## Completion gating and pending inventory

Ordinary and linked completion now consume adopted delivery requirements before writing `DONE`. Local implementation verification remains separate from required PR delivery. A missing explicit scope decision blocks overall completion; required pending publications produce `WAITING` only after independent work passes. No-publication scope preserves ordinary completion. Title formatting and the nine-state vocabulary are unchanged. Linked aggregate inputs retain managed delivery-plan sources; ordinary closure and factual/aggregate linked lifecycle paths protect pending delivery.

Independent review reproduced a user-condition ID bypass and a factual linked-retention bypass. Both received failing regressions, fixes, and independent scoped rechecks. Further tests preserve resolved user condition history and bind the generated wait marker to its exact verification and plan. Current status requires an actual current verification receipt. Eight completion fixtures passed before the final receipt test; three focused wait/status regressions and the stale-plan marker regression then passed. The earlier completion/status/title command passed 48 tests. The broader evidence, retention and linked closure command passed **54 tests in 1315.206 seconds** against immutable snapshot `completion-source-nw4e_tjv`. Later marker, status, inventory and reconciliation changes have separate focused proof; this snapshot result is not attributed to those later edits.

The pending inventory reads at most 32 retained task records per page and returns an authority-bound continuation cursor. Three inventory fixtures passed; an additional actual canonical fixture removed one peer checkout and still discovered both tasks through the survivor. Nine public CLI/hook tests passed. Public controls expose only local status/pending reads; no merged JSON claim, mutation, provider call or checkout scan is accepted. These observations do not qualify manual-merge reconciliation, agent merging or cleanup, which remain implementation work.

The ordinary evidence fixture review helper accepts findings as its first positional argument; a temporary purpose-routing test passed coverage strings there incorrectly. That test now uses the actual native-review fixture chain with `review()` and passes without mocking the verifier. Publication-state review also corrected a scope gap: unpublished/unready PRs still leave agent work, so they remain WORKING/REVIEW. Automatic merge WAITING requires retained readiness, and an observed manual merge cannot manufacture missing readiness provenance.

## Existing-PR reconciliation

The callable owner can now record facts for an existing independently native-owned PR. Initial binding requires the original admitted workspace, exact local branch and a committed candidate snapshot; uncommitted contents are rejected except the existing narrow canonical enrollment-record exception. Candidate binding retains the immutable repository ID as well as PR/ref/head and snapshot identity. Authoritative merged facts remain distinct from local verification and readiness provenance. Closed-unmerged, replaced repository, changed head, or missing readiness cannot manufacture overall completion.

A surviving admitted producer task can record an observation for the original task in the same physical authority. The transaction rechecks both revisions and original plan, registers explicit original-task/source dependencies, and updates the original delivery record atomically. It preserves original accepted identity, pins and evidence. The original pinned package must remain compatible; no missing checkout is recreated and no observation declares DONE or resolves a wait. Eight reconciliation fixtures passed, including deleting the original checkout and observing through the survivor. Independent review reproduced dirty snapshot binding, then independently confirmed its fix and the surviving-producer regression.

The combined delivery/adoption/workspace/provider/completion/inventory/CLI/reconciliation/status/title/hooks/repository-gate command passed **127 tests in 310.926 seconds** from immutable snapshot `reconcile-source-4lwegefh`. Its runtime digest matches the current candidate. Package validation and whitespace checks also pass. Publication, READY/reopen mutations, agent merge, remote cleanup and their live qualification remain subsequent implementation work.
