# Approved policy contracts

These contracts follow the [three-stage design](onboard-my-project-plan.md#2-stages-and-policy-decisions): Installation provides capabilities; Project Onboarding adopts and qualifies mandatory policies; Runtime determines applicable actions and verifies their outcomes. Agents assess meaning, risk and capability; scripts enforce recorded permissions, limits, ownership and evidence requirements. A completed record alone does not prove a correct decision.

## Delegation and Model Selection

**Mandatory adoption.** Meet acceptance criteria with the least necessary model usage and coordination.

**Project Onboarding:** establish approved clients/subscriptions, selection constraints, concurrency limits, finite task budgets and fallback rules.

| Element | Contract |
| --- | --- |
| Trigger | Before starting a task or dispatching a worker; reassess after material scope changes, failed attempts or capacity changes. |
| Decision | Choose deterministic tooling, direct execution or delegation. Delegate for useful context isolation, specialization, required independence or independent parallel work. Select the lightest capable model and supported reasoning level, considering uncertainty, consequences, retries and review effort. |
| Required action | Give each worker its objective, relevant context/instructions, writable scope, dependencies, resources, acceptance criteria and checks. Reserve mutable resources before dispatch. Parallel writers need independent scopes; reviewers remain read-only. The coordinator validates integration. |
| Evidence | Record the rationale, task/worker identity, requested/configured/observed model and effort, resource ownership and verified outcome. Unobservable settings remain unknown. |
| Blocking condition | No suitable authorized execution option, unresolved ownership or exhausted task budget. Use a qualified, already-approved fallback when available; otherwise block dependent work. |

Rules:

- Preserve the main agent's selected model and authentication. Route workers only within approved paid subscriptions; no local-model, proxy or API-billing fallback.
- Discover actual models and controls; keep commercial names out of this portable contract. Unsupported selection permits inheritance only when consistent with the approved policy; record the limitation.
- Diagnose failures before retrying: context, implementation, tooling or capability. Escalate when warranted; an unchanged attempt needs new evidence. Escalation does not reset the task budget.
- Required independent review cannot be satisfied by the implementing agent's self-review.
- Provider changes require an approved route and a qualified execution mechanism. Installation alone authorizes neither new providers nor billing.

Source: [toolkit delegation and model-selection guidance][delegation]. Resource-enforcement details belong to the [runtime design](onboard-my-project-plan.md#ownership-and-merge-assurance).

## Proportional Security Review

**Mandatory adoption.** Match security coverage to the actual change's exposure and consequences.

**Project Onboarding:** identify sensitive areas, qualified review mechanisms, required reviewer capabilities and merge-blocking criteria. Planning defines relevant requirements and tests; this policy adds no planning-time review, checklist, report or approval gate.

| Element | Contract |
| --- | --- |
| Trigger | After implementing a deliverable, before accepting completion or allowing a merge. A deliverable may be a task or wave. Reassess after changes that affect review coverage or evidence. |
| Decision | Assess the actual changes and affected security boundaries. Determine necessary scope, depth, checks and independent specialist involvement. Investigate uncertainty before selecting additional review. |
| Required action | Follow the toolkit's security procedure for the exact candidate/base and relevant working-tree changes. Inspect connected callers, contracts and shared controls as needed. Reviewers stay read-only; authorized fixes return to the responsible writer. |
| Evidence | Record candidate/base, policy and procedure versions, scope, reviewer provenance, actual checks, findings and disposition. Keep sensitive evidence in a private, redacted report outside reviewed repositories. |
| Blocking condition | Required review is missing or stale, a blocking finding remains unresolved, or material security uncertainty remains. Unavailable review capacity cannot make review inapplicable. |

Rules:

- Every completed change receives a security-impact assessment; a separate specialist is required only when risk warrants it. Reduced coverage needs a reason based on the actual change, not its file extension alone.
- Use compatible Trail of Bits `differential-review` when available. Its absence permits qualified manual analysis under the same procedure; it never waives required independence or coverage.
- Confirmed high/critical findings block completion and merge. Medium/low findings require a recorded resolution or authorized disposition. Separate confirmed findings from hypotheses and hardening suggestions.
- After fixes, reassess affected coverage and rerun relevant checks. Reuse unaffected evidence only with a recorded justification; no fixed reviewer panel or repeated full audit without new evidence or unresolved risk.
- General requirements, behavior and regression review remains required. Security coverage can share a review only when the actual scope and reviewer qualification satisfy both requirements.

Sources: [security procedure][security] and [review by risk and evidence][review]. Use the recorded upstream revision for a run; resolve updates through the [source policy](onboard-my-project-plan.md#1-authority-and-scope). These contracts do not vendor upstream prompts.

[delegation]: https://github.com/soumatheusgomes/vibe-coding-toolkit/blob/790a895304e0c08b70a5b215c9d334f1c86b816c/docs/tools/02-subagent-orchestration.md#part-b--model-selection-discipline
[security]: https://github.com/soumatheusgomes/vibe-coding-toolkit/blob/790a895304e0c08b70a5b215c9d334f1c86b816c/docs/prompts/13-security-review.md
[review]: https://github.com/soumatheusgomes/vibe-coding-toolkit/blob/790a895304e0c08b70a5b215c9d334f1c86b816c/docs/prompts/12-existing-project-setup.md#10-review-by-risk-and-evidence
