# Policy source map

For policy authoring, setup, reviewed updates and coverage audits only. Runtime reads the local policy index and applicable contracts; it does not need this file, Toolkit access or a permanent source snapshot.

Vibe Coding Toolkit remains the workflow authority. The contracts express its applicable requirements in local wording, with the user's extensions identified below. `vibe-setup` is an implementation reference only.

## Reviewed sources

These contracts were checked against Toolkit revision `790a895304e0c08b70a5b215c9d334f1c86b816c`. This records the reviewed basis, not a claim that it is still the latest revision.

| Source | Relevant scope |
| --- | --- |
| [Subagent orchestration][delegation] | Capability/effort selection, context boundaries, bounded workers, safe parallelism, review and recovery |
| [Security review, Prompt 13][security] | Review authority, reproducible targets, threat analysis, safe evidence, reporting and completion |
| [Existing-project setup, Prompt 12][setup] | Sections 1–5: scope, preservation, decisions and durable working agreements; section 10: review by risk and evidence |
| [Brainstorm to plan, Prompt 04][planning] | Conditional clarification, verifiable plans, lightweight confirmation and checked implementation |
| [Shared AGENTS template][agents] | Working agreements, authorization, execution continuity, canonical documents and honest evidence |
| [Toolkit overview][overview] and [tool catalog][catalog] | Setup paths, complete component assessment and scope-dependent applicability |
| [Harness evaluation guide][evaluation-guide] and [Prompt 14][evaluation] | Disposable behavioral cases, independent observations and repeatable verification |
| [Harness improvement, Prompt 15][improvement] and [method guide][harness-method] | Native baseline/candidate comparison, bounded changes, recovery and separately authorized external labs |

## Requirement coverage

| Local contract section | Requirements carried locally | Basis |
| --- | --- | --- |
| [Agent Delegation: select capability](../policies/03-agent-delegation.md#select-capability-and-dispatch) | Preserve coordinator settings; discover controls and current client guidance; policy-consistent inheritance; risk/total-effort selection; scoped context, tools, briefs and reports | Orchestration Parts A/B and context/decomposition guidance |
| [Agent Delegation: ownership](../policies/03-agent-delegation.md#ownership-and-parallel-work) | File/resource/dependency isolation, uncertainty, concurrency limits, coordinator tracking and serialized authorized Git operations | Orchestration parallel-wave guidance |
| [Agent Delegation: integration](../policies/03-agent-delegation.md#review-integration-and-recovery) | Fixed review targets, read-only independent review, bounded rounds, verified findings, reassessed dependencies, escalation and stopped-worker recovery | Orchestration review/recovery guidance |
| [Security: target and limits](../policies/04-security-review.md#establish-the-target-and-limits) | Inspection authority, diff and dirty layers, baseline scope, excluded paths, safe isolated commands, execution settings and disclosure limits | Prompt 13 scope, target and authority |
| [Security: boundaries](../policies/04-security-review.md#review-relevant-boundaries) | Tool/manual capability, threat model, relevant vulnerability classes, counterevidence, safe reproduction and versioned references | Prompt 13 capabilities and review procedure |
| [Security: evidence](../policies/04-security-review.md#evidence-and-completion) | Severity/confidence/provenance, redacted private reports, repository integrity, honest limits, risk-scaled independence and relevant rechecks | Prompt 13 reporting/completion; Prompt 12 section 10 |
| [Project Scope: authority](../policies/01-project-scope.md#authority-and-activation) | Actual target and instructions, canonical project rules, preserved permissions/customizations, verified resumption and scoped decisions | Prompt 12 sections 1–5; AGENTS working agreements/continuity |
| [Project Scope: conflicts](../policies/01-project-scope.md#when-instructions-conflict) | Material choices, preservation, prior authorization, assumptions versus decisions, and dependent blockers | Prompt 12 sections 2–5; AGENTS working agreements/continuity |
| [Task Planning: contract and procedure](../policies/02-task-planning.md#planning-and-verification) | Outcome/boundaries/constraints, observable acceptance, proportional plans, conditional confirmation, actual per-step checks, regression proof and verified resumption | Prompt 04; Prompt 12 durable agreements; AGENTS working agreements/continuity |
| [Tests and Builds: executable proof](../policies/05-tests-and-builds.md#select-and-run-proof) | Actual commands, behavior/regression proof, isolated safe checks, baseline failures and honest distinctions between kinds of evidence | Prompt 12 sections 5, 9, 11; AGENTS working agreements |
| [Tests and Builds: quality and freshness](../policies/05-tests-and-builds.md#preserve-quality-and-evidence) | Native tooling/self-check, compatible typed lint, measured runner cost, adapted size limits, legacy warning adoption, preserved gates and current-content evidence | Prompt 12 section 8; accepted evidence design |
| [Code Review: coverage and findings](../policies/06-code-review.md#choose-coverage) | Complementary risk-based scopes, exact target, read-only review, qualified independence, substantiated/deduplicated findings, dispositions and bounded rechecks | Prompt 12 section 10; AGENTS delegation/review; accepted merge-review baseline |
| [Context and Handoff: records](../policies/07-context-and-handoff.md#canonical-documents-and-selective-retrieval) | Canonical document mapping, client-specific loading, selective memory, source/verification/invalidation and privacy | Prompt 12 sections 5, 7; AGENTS documentation/memory |
| [Context and Handoff: continuation](../policies/07-context-and-handoff.md#handoff-and-resumption) | Temporary handoff, actual-state reconciliation, uncertain worker ownership, explicit pauses and authorized remaining work | Prompt 12 durable agreements; AGENTS execution continuity |
| [Merge Readiness](../policies/08-merge-readiness.md) | Current candidate/base/queue, required successful evidence, trusted verifier/reviewer provenance, repository rules/bypasses, scoped authority and observed outcome | User-approved merge-enforcement extension; original design's repository gate constraints |
| [Workflow Maintenance: qualification](../policies/09-workflow-maintenance.md#requalify-affected-behavior) | Fresh-context/client distinctions, seven scoped cases, private isolated fixtures, independent evaluators, unavailable observations and safe reapplication | Prompt 12 section 9; evaluation guide and Prompt 14 |
| [Workflow Maintenance: improvement](../policies/09-workflow-maintenance.md#one-bounded-improvement) | Observed failure, comparable baseline/candidate, fixed evaluators/inputs/settings, one-candidate default, measured outcomes and authorized adoption | Prompt 15 and method guide native procedure |
| [Workflow Maintenance: updates/labs](../policies/09-workflow-maintenance.md#updates-and-optional-external-labs) | Active-task versions, stopped writers, compatibility/recovery, external lab isolation, credential-free demo and separately authorized model/benchmark budgets | Prompt 15 and method guide conditional lab procedure; accepted runtime design |
| [Project Onboarding](../policies/10-project-onboarding.md) | Separate setup paths, complete catalog matrix, preserved equivalents, compatible modernization, recoverable changes, real validation, reruns and honest readiness | Overview; complete tool catalog; Prompt 12 sections 1–5, 7–11 |
| [onboard-my-project apply and recovery](../skills/onboard-my-project/references/apply-and-recovery.md) | Trusted user/session authority distinct from JSON binding; frozen source/plan pin; effect-scoped approval; current-input-bound observations; durable backups, journal and crash reconciliation; ownership-safe rollback; dependency-group adoption; mandatory dependency-closure qualification; exact approved enrollment postimage; separate package and actual client evidence | Project Onboarding; Project Scope; D4 approved plan; Toolkit setup, tool integration, review, harness evaluation and security sources |
| [Tool Integrations](../policies/11-tool-integrations.md) | Required versus optional capability, reuse, scoped configuration/authentication, current client formats, distinct discovery/trust/execution, safe probes and invalidation | Catalog scope matrix; Prompt 12 sections 2, 7, 9 |
| [onboard-my-project procedure](../skills/onboard-my-project/references/procedure.md) | Resolve one source revision for a new run; load Prompt 12's required source bundle including explicit guides 17–23; enumerate named catalog components across sources, apply stage-specific mandate/applicability, group only explicit members with shared disposition, preserve immutable source declarations and partial assessment checkpoints; retain pinned/offline resume semantics; distinguish planning from application and qualification | Prompt 12; overview; complete tool catalog; project defaults and document manifest; required guides 17–23 |

The local contract tables also retain their triggers, onboarding decisions, evidence and blockers. Model catalogs, installation examples and external skill internals are not runtime requirements. Clients discover actual controls; setup handles integrations. A worker retains the task's applicable development/check discipline without importing another skill as a universal dependency.

## User-approved extensions and boundaries

- Explicit project/client enrollment, silent activation, the three conflict-resolution modes and mandatory policy adoption are plugin decisions. Project identity/state mechanisms remain implementation proposals until qualified.
- Subscription-only worker routes, no local-model/proxy/API-billing fallback, resource reservations, observed settings and trusted reviewer provenance supplement Toolkit guidance.
- Security review runs after implementation, includes relevant delivery working-tree layers and blocks completion/merge for confirmed high/critical findings. Medium/low findings require resolution or authorized disposition. A repository baseline is performed when requested; no separate planning-time security gate is added.
- General review before every merge and a trusted repository-controlled gate are plugin requirements. Ordinary Toolkit setup excludes branch/worktree requirements and commit/push protections; those controls are not inherited installation permissions.
- Runtime contracts are locally complete. Remote Toolkit use is limited to authoring, setup and reviewed updates. This supersedes the earlier runtime instruction to follow linked upstream procedures; it does not prohibit task-specific technical research or authorized network operations.
- The user approved all eleven contracts on 25 October 2026. Approval is recorded in development documentation; runtime files carry no approval-status labels.

## Updating contracts

During an authorized update, resolve Toolkit once and inspect the changed requirements plus their applicable dependencies at that revision. Rewrite the affected local behavior, update this map and record material decisions separately from upstream requirements. Do not copy whole prompts or maintain a mirrored repository.

Before delivery, compare requirement coverage and run representative instruction-path cases using only the local runtime documents. Check both required actions and unnecessary loading/gates. Package checks and static simulations do not prove client execution. Preserve the accepted version for active tasks until an update is reviewed and safely applied.

[delegation]: https://github.com/soumatheusgomes/vibe-coding-toolkit/blob/790a895304e0c08b70a5b215c9d334f1c86b816c/docs/tools/02-subagent-orchestration.md
[security]: https://github.com/soumatheusgomes/vibe-coding-toolkit/blob/790a895304e0c08b70a5b215c9d334f1c86b816c/docs/prompts/13-security-review.md
[setup]: https://github.com/soumatheusgomes/vibe-coding-toolkit/blob/790a895304e0c08b70a5b215c9d334f1c86b816c/docs/prompts/12-existing-project-setup.md
[planning]: https://github.com/soumatheusgomes/vibe-coding-toolkit/blob/790a895304e0c08b70a5b215c9d334f1c86b816c/docs/prompts/04-brainstorm-to-plan.md
[agents]: https://github.com/soumatheusgomes/vibe-coding-toolkit/blob/790a895304e0c08b70a5b215c9d334f1c86b816c/templates/AGENTS.md.template
[overview]: https://github.com/soumatheusgomes/vibe-coding-toolkit/blob/790a895304e0c08b70a5b215c9d334f1c86b816c/docs/00-overview.md
[catalog]: https://github.com/soumatheusgomes/vibe-coding-toolkit/blob/790a895304e0c08b70a5b215c9d334f1c86b816c/docs/tools/README.md
[evaluation-guide]: https://github.com/soumatheusgomes/vibe-coding-toolkit/blob/790a895304e0c08b70a5b215c9d334f1c86b816c/docs/07-harness-evaluation.md
[evaluation]: https://github.com/soumatheusgomes/vibe-coding-toolkit/blob/790a895304e0c08b70a5b215c9d334f1c86b816c/docs/prompts/14-harness-evaluation.md
[improvement]: https://github.com/soumatheusgomes/vibe-coding-toolkit/blob/790a895304e0c08b70a5b215c9d334f1c86b816c/docs/prompts/15-harness-improvement.md
[harness-method]: https://github.com/soumatheusgomes/vibe-coding-toolkit/blob/790a895304e0c08b70a5b215c9d334f1c86b816c/docs/tools/23-harness2.md
