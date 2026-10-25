# Agent Delegation

Apply with the [shared contract rules](00-index.md).

**Mandatory adoption.** Meet acceptance criteria with the least necessary model usage and coordination.

**Project Onboarding:** establish approved clients/subscriptions, selection constraints, concurrency limits, finite time/attempt/resource budgets and fallback rules. Qualify available dispatch, model/effort controls and ownership mechanisms.

| Element | Contract |
| --- | --- |
| Trigger | Before starting a task or dispatching a worker; reassess after material scope changes, failed attempts or capacity changes. |
| Decision | Use deterministic tooling or direct execution when sufficient. Delegate for useful context isolation, specialization, required independence or genuinely independent parallel work. Choose capability by complexity, ambiguity, consequences and total effort, including retries and review. |
| Required action | When delegating, define a bounded worker brief, select an authorized model/effort route, reserve its writable files and mutable resources, and verify returned work before integration. Apply the procedures below. |
| Evidence | Record the rationale, task/worker identity, requested/configured/observed model and effort, ownership, actual checks, verified outcome and limitations. Unknown settings remain unknown; do not invent usage or savings measurements. |
| Blocking condition | No suitable authorized execution option, unresolved ownership or exhausted task budget. Use a qualified, already-approved fallback when available; otherwise block dependent work. |

## Select capability and dispatch

- Preserve the main agent's selected model and authentication. Route workers only within approved paid subscriptions; no local-model, proxy or API-billing fallback. Provider changes require an approved route and qualified execution mechanism; installation grants no new authority.
- Without an authorized selection policy, inherit the session model. With one, discover available controls and consult the client's current capability recommendations. Choose the lightest capable model and supported effort. Verifiable mechanical work may use lighter capability; security, architecture, migrations, concurrency and uncertain causes need judgment proportionate to their risk. Do not downgrade solely for price.
- Set model and effort through supported controls. Use configuration or inheritance only when consistent with the approved policy; record unsupported controls rather than inventing parameters. Keep commercial model names out of portable rules.
- Give each worker its objective, necessary context/instructions, exact files, dependencies, mutable resources, acceptance criteria, checks and stop condition. Request a short report of paths, findings, evidence and limitations. Grant only necessary tools and permissions; avoid copying the whole conversation or loading an unused specialist roster.
- Preserve the task's implementation/check discipline, including test-first work when required. Implementers run applicable checks, self-review and report an explicit completion, blocker or pending-decision status; parallel dispatch does not relax these requirements.
- Split work at separable context boundaries. Keep tightly coupled work together. Use narrow specialist roles with distinct triggers; retain a standing role only for a recurring need.

## Ownership and parallel work

1. Reserve canonical writable files and mutable resources before dispatch, including path aliases, ancestor overlaps, ports, build directories, databases and services. Parallel tasks need disjoint files, independent or isolated mutable resources, and no direct or transitive dependencies. Unknown scope means serialize or combine the affected tasks. Different sections of one file are not independent scopes.
2. Make conflicting reservations mutually exclusive. Describe ownership/read-only restrictions as enforced only when the qualified mechanism prevents violations; otherwise record the limitation. Uncontrolled external writers remain a limitation. Branch names and worktrees alone do not isolate shared services.
3. Cap concurrency by actual authorized slots, host resources and the task budget. For waves, retain each task's brief, start eligible workers together, wait for their results before integration, and let the coordinator record one progress entry per wave.
4. The coordinator owns lockfiles, shared configuration, tracking records and Git operations. Serialize authorized commits in task order, recording current HEAD immediately before each. If commits are not authorized, review recorded working-tree snapshots instead; workers must not commit or publish implicitly.

## Review, integration and recovery

- Before review, fix the target base/candidate or working-tree snapshot, including staged, unstaged and relevant untracked changes. Reviewers inspect the diff and relevant callers, contracts and tests. They remain read-only; checks with shared mutable resources must be isolated or serialized. Review does not authorize fixes, commits or publishing.
- Required independent review cannot be replaced by the implementer's self-review. Choose review scope and specialists by risk and evidence; apply [Security Review](04-security-review.md) when its trigger applies. Set review scope, requested rounds and stop conditions before dispatch. Internal fixes do not restart the round count. Further rounds need new risk, an evidence gap or a user request.
- The coordinator inspects the diff, deduplicates findings by root cause, checks their evidence and disposition, validates integration, and records actual checks and residual uncertainty. When findings overlap, reassess dependencies before the next wave. Verify reviewer identity through observed dispatch or a trusted integration; a report's claimed identity or success is insufficient.
- Diagnose failure before retrying: context, implementation, tooling or capability. Escalate only when warranted; an unchanged attempt needs new evidence. Escalation never resets the task budget.
- Confirm an interrupted worker has stopped before taking over its files. Inspect partial changes and resume from verified state. Uncertain workers retain ownership; elapsed time alone does not release it. Continue independent authorized work while dependent work waits.
