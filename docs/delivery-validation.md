# Delivery lifecycle implementation evidence

2 November 2026. Review branch: `codex/delivery-lifecycle-foundations`, based on published main `9c364e5d9bd80ec23aa677b8b237f4bd00a7d718`. Main PR #35's canonical gate envelope support is included unchanged. Only feature commits were replayed; the original development branch remains intact. The [implementation plan](superpowers/plans/2026-11-02-delivery-lifecycle.md) remains the full target. This source slice is incomplete and must not be presented as qualified end-to-end delivery.

## Implemented source behavior

Canonical adoption records an explicit version-1 delivery policy: manual merge and separate worktrees are defaults, with preserved opt-outs, task overrides, exact targets/methods and separate authorization references. Policy participates in accepted identity and existing D4 recovery. Historical records retain their meaning. References bind decisions; they do not authenticate effects.

Managed task artifacts retain complete publication scope. Accepted extensions preserve existing obligations, record previous-plan dependencies and atomically revise accepted milestones before weighted progress. A completed task reopens to review; explicit pauses, blockers and waits remain effective.

Workspace binding independently checks native attachment and physical Git identity, including checkout replacement. Exact replay preserves its binding. It creates or deletes no checkout. Production native creation/admission is not supplied by this library.

Bounded GitHub reads validate immutable repository identity, PR, target, branch, head and merged facts. Existing-PR reconciliation binds native ownership and a committed candidate. A surviving admitted producer in the same authority/project can retain subsequent observations after original checkout removal, without replacing the original accepted identity, pins or local proof. Checks/reviews remain unobserved; provider observations do not manufacture readiness.

Ordinary and linked completion consume required delivery before `DONE`. Verified implementation remains distinct from overall completion. Only retained readiness with no remaining independent work permits merge `WAITING`; unpublished/unready work remains working/review. User conditions and pauses still apply. Thread Naming retains its vocabulary, weighted meter, manual-title controls and existing event repair. No renderer or startup hook calls a provider.

Pending inventory reads at most 32 known task records per page with an authority-bound cursor; it neither scans checkouts nor claims discovery of unknown PRs. Required delivery, known optional PRs, authorized unresolved remote cleanup and unfinished effect records protect retained evidence. Own completion and retention completion remain separate.

Guarded transport primitives cover draft discovery/replay, workflow labels, append-only operation-marked checkpoint comments, readiness withdrawal, separately disabled synchronous merge, and expected-OID remote deletion. Existing PR title/description are never overwritten. Mutations have no default source and are not wired into the high-level owner. Git destination/configuration/hook inspection, bounded no-follow regular-file hook reads and post-effect readback protect the conditional transport seam. No product path removes a local branch or worktree.

## Evidence and limits

The final combined delivery, compatibility, configuration, ledger, unenrolled-entry, title, hook and repository-gate run passed **186 tests in 311.097 seconds** on published main `9c364e5`, including PR #35. The preceding run passed 181 tests in 308.826 seconds on `96e182e`. `python3 -B scripts/validate.py` and `git diff --check` pass. Package validation reports client execution `not_checked`; it is separate from behavior and production qualification.

Earlier immutable source snapshots provide scoped evidence, not proof of later edits:

- `completion-source-nw4e_tjv`: 54 ordinary evidence, retention and linked-closure tests passed in 1315.206 seconds.
- `reconcile-source-4lwegefh`: 127 delivery, adoption, workspace, provider, completion, inventory, CLI, reconciliation, title, hook and repository-gate tests passed in 310.926 seconds.
- Later focused source checks passed for accepted scope/milestones, optional-publication retention, lost acknowledgments, metadata races, and Git deletion. Ten real disposable Git tests passed, including a ref advancing during deletion, actual hook execution, lost acknowledgment, alias rejection, a FIFO replacement and cleanup through a surviving checkout. These tests qualify software behavior, not a production transport source.

Native read-only review independently reproduced defects before their regression fixes: policy bool/integer equality, read-only delivery completion, replaced checkout binding, dirty candidate binding, user-condition collision, linked retention bypass, concurrent human PR edits, wrong-target merge exposure, changed operation replay, remote alias redirection and hook FIFO replacement. Focused rechecks passed. Review used the selected native coordinator model at high reasoning; no provider, authentication or model route was changed. No outstanding source-library blocker was reported at the reviewed boundary.

An earlier onboarding run on the older base reproduced the same 4 failures and 22 errors in an immutable baseline. That historical result is not attributed to current main, and does not waive any current gate. Private logs and immutable snapshot identities remain under ignored `.superpowers/sdd/2026-11-02-delivery-lifecycle/`.

## Representative instruction paths

| Task | Loaded contract and observed boundary |
| --- | --- |
| Adopt policy or preserve opt-out | Policy 10 and onboarding procedure; strict policy/D4 fixtures preserve explicit choices and recovery. No runtime activation occurred. |
| Override task merge mode | Policy 02 and delivery plan; accepted decision changes effective policy, not target authority. |
| Inspect status/pending | Delivery client contract and public read-only controls; no provider, mutation or checkout scan. |
| Extend accepted scope | Delivery plan revision; exact previous plan and accepted decision, preserved obligations, revised weighted milestones. |
| Finish required publications | Evidence completion and delivery requirements; implementation proof alone cannot produce `DONE`. Missing readiness cannot produce automatic merge `WAITING`. |
| Remove original checkout | Client owns removal; surviving-authority fixtures retain inventory and existing-PR facts without fresh local proof or recreated checkout. |
| Retire evidence | Evidence retirement plus delivery retention; optional known PRs and unresolved authorized cleanup prevent loss. |
| Publish, promote READY, merge or clean remotely | Delivery client contract identifies missing orchestration/source authority; no direct primitive bypass is authorized. |

## Remaining implementation and qualification

The high-level owner supports plan/workspace binding and existing-PR observation. It does not yet orchestrate durable checkpoint commit/push/PR effects, READY/reopen evidence writers, authorized agent merge or remote cleanup. Positive companion settlement and the complete twelve-case acceptance campaign remain unfinished. Required companions conservatively remain pending. Readiness and cleanup consumers do not imply a production writer exists.

Production Native Clients execution and independently observed stop of **all descendants** are separate owners' prerequisites. In particular, `runtime.delegation._validate_role_proof` needs bound operation/claims plus `operation_stopped=True` and `operation_descendants_stopped=True`. HookStarted/Completed or process exit zero does not satisfy this contract. The user chose to wait for that work rather than expand this branch.

D7 protected-source qualification and target enforcement are also required. Stock GitHub expected-head merge does not atomically bind the intended target. The separate target-binding merge source remains unavailable; default metadata capability cannot enable it. Queue/auto-merge paths are unsupported. Caller JSON, `evidence_valid`, decision references and fixture callbacks cannot qualify any production authority.

The dedicated pilot remains sole live qualification owner. After the user confirmed rollback, the pilot confirmed both owned onboarding files absent and installed entry resolution `outside/not_enrolled`. Ordinary source work resumed without reenrollment. No live provider mutation, native admission, activation campaign, credential change, watcher or local cleanup was performed. Full discovery and live disposable-target acceptance have not been completed for this source slice.

## Provider authoring basis

Requests select API version `2022-11-28`, retaining `merge_commit_sha`; newer API [breaking changes](https://docs.github.com/en/rest/about-the-rest-api/breaking-changes) remove it. [Versioning](https://docs.github.com/en/rest/about-the-rest-api/api-versions) documents explicit headers. [Conditional request guidance](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api#use-conditional-requests) supplies no conditional unsafe PATCH guarantee. Workflow labels and append-only comments therefore preserve human PR title/description under concurrent edits.

The [merge API](https://docs.github.com/en/rest/pulls/pulls?apiVersion=2022-11-28) provides exact-head synchronous merge. The [CLI](https://cli.github.com/manual/gh_pr_merge) can implicitly queue or enable auto-merge, so that command is excluded. [Git push](https://git-scm.com/docs/git-push) specifies exact expected-ref leases; [ls-remote](https://git-scm.com/docs/git-ls-remote) distinguishes successful absence. Disposable tests exercise those contracts without establishing live authorization.
