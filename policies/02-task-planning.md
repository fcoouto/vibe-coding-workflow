# Task Planning

Apply with the [shared contract rules](00-index.md).

**Mandatory adoption.** Establish the requested outcome, boundaries and proof of completion before implementation. Match planning depth to ambiguity, dependencies and risk.

**Project Onboarding:** identify canonical product and architecture documents, actual check commands, relevant environments and existing design/plan approval requirements.

| Element | Contract |
| --- | --- |
| Trigger | Before implementation; when resuming work; after material changes to the goal, scope, constraints, risk or acceptance criteria. |
| Decision | Determine the smallest sufficient change, unresolved choices, necessary design/plan depth and observable acceptance criteria. Do not invent requirements or treat assumptions as decisions. |
| Required action | Read affected code and instructions; state the outcome, included/excluded work and relevant constraints. Define acceptance criteria and checks before editing. Keep bounded work in the existing task context; document a plan when complexity, dependencies or multi-session work require one. Give each planned step a verification check and respect its dependencies. |
| Evidence | Retain the request, agreed scope, material assumptions/decisions, acceptance criteria and check commands or observations in the existing task or canonical record. Include the plan when needed and relevant known baseline failures. A planned check is not a passing result. |
| Blocking condition | An unresolved material choice, missing required approval, unavailable prerequisite or unverifiable acceptance condition blocks dependent implementation or completion. Continue independent authorized work; report missing checks rather than treating them as passed. |

## Planning and verification

At the transition to implementation, load the [Thread Naming rules](../clients/workstreams-naming.md)
and follow their activation and title-synchronization procedure for direct or
delegated work. Existing presentation ownership and pauses remain binding.

For an enrolled delivery policy, record the task's effective policy and complete required publication/companion scope before claiming completion. A no-publication decision is explicit. Snapshot the adopted defaults; a task-specific merge override never changes repository settings or grants authority by itself. Keep required unpublished work visible and preserve existing authorization/revocation boundaries.

- Apply [Project Scope](01-project-scope.md) to project boundaries, permissions, instruction conflicts and changed decisions.
- For open or ambiguous requests, expose the plausible interpretations and clarify the intended outcome, boundaries and constraints before coding. Keep questions focused; skip clarification when scope is already clear.
- When this clarification-and-plan procedure is needed or explicitly requested, present steps with observable checks and obtain lightweight confirmation before code. Reconfirm only changed parts; preserve existing authorization. Clear, already-authorized tasks follow applicable project approvals without an added universal planning gate.
- Use existing commands and checks that prove relevant behavior and failures. Fixes need reproduction and regression proof when feasible; trivial edits do not need tests that merely repeat the implementation. Do not add features or infrastructure just to fill a plan.
- For new behavior and bug fixes, write the focused test or executable reproduction first, observe failure for the intended reason, then implement and rerun it. For behavior-preserving refactors, establish a passing baseline and rerun affected tests. Documentation and trivial nonbehavior edits need relevant static checks, not tests that restate the edit. Missing required proof remains a blocker under [Tests and Builds](05-tests-and-builds.md), not an implicit exception. Implementers self-review and report completion, a blocker or a pending decision.
- Run each planned check and report its actual result before marking the step complete. Fix a failed prerequisite before dependent steps; missing or unavailable verification stays explicit.
- On resume, check actual files, Git state, checks and processes before trusting the plan. Reassess affected criteria after material changes and apply [Agent Delegation](03-agent-delegation.md) when its triggers apply. Keep unfinished-work context in the existing task record: goal, verified state, pending work, blockers and next action.

Planning identifies relevant security requirements and checks. It adds no separate security review, checklist, report or approval gate; post-implementation review follows its own contract.

## Example

The user requests a case-insensitive search fix with existing sorting preserved. Inspect matching and sorting, record those two acceptance criteria, and select regression checks. A short task-level plan is sufficient. Switching search providers would change scope and needs a separate decision.
