# Project Onboarding

Apply with the [shared contract rules](00-index.md).

**Mandatory adoption.** Assess the complete workflow and enroll the selected project through verified, recoverable changes.

**Setup inputs:** the target project, complete current component catalog and recorded source revision, observed client capabilities, existing project decisions and authorized scope. Locate the inventory/source record through the canonical setup document mapped by [Context and Handoff](07-context-and-handoff.md); first-time setup must supply and record that input before coverage decisions. A partial plugin inventory is not the full catalog.

For each new setup/update, resolve the current Toolkit revision once and use catalog guides, procedures and templates from that revision. Resume interrupted setup at its recorded revision. A trusted versioned copy may support offline setup with freshness explicitly unverified; unavailable sources block only their dependent setup work.

| Element | Contract |
| --- | --- |
| Trigger | Explicit project enrollment, an authorized setup update/repair, or expansion to additional repositories or clients. |
| Decision | Determine each component's need, compatibility, existing equivalent, required action and verification; resolve conflicts without waiving mandatory policies. |
| Required action | Inventory, plan full coverage, apply authorized changes in dependency order, verify actual behavior and retain recovery records. |
| Evidence | Record target/source revision, decisions, complete coverage matrix, before/after checks, configuration and execution observations, backups, pending interventions and rerun results. |
| Blocking condition | A mandatory requirement lacks adoption or qualified operation, a material decision is unresolved, or a required prerequisite/source is unavailable. Keep enrollment incomplete for that scope; continue independent authorized setup work. |

## Inspect and plan

1. Apply [Project Scope](01-project-scope.md). Keep machine preparation, new-project creation and existing-project enrollment distinct. Do not configure this plugin's own repository as an application merely because the agent is working here; confirm the actual destination.
2. Inventory product and critical flows, stack/runtime/package manager, lockfiles, workspaces, Git changes, canonical documents, quality commands, services and client capabilities. Separate facts from assumptions. Run safe available baseline checks and record existing failures before edits.
3. For every selected Repository, cover every catalog component, including additions beyond previously known names. Record need, current state, action, scope, dependencies, risk and validation criterion. Outcomes include install/update/integrate, reuse a verified equivalent, justified inapplicability, or a blocker with its resumption condition. Optional choices in a partial-adoption path cannot silently remove items from this full assessment. A non-Git Project shared-file owner assesses its named shared changes without a second software adoption matrix. Connect shared changes to affected Repository actions/evaluation; every Repository still covers the complete catalog and policies. Shared configuration or authorization does not qualify another Repository's behavior.
4. Use [Task Planning](02-task-planning.md) and the selected conflict mode for the concrete design and changes. Reuse prior decisions; obtain only missing material decisions. Separate configuration from working integration and required features from optional additions.

## Apply compatible changes

- Preserve product contracts, data, customizations, local changes and the existing stack. Reuse working tools and canonical documents. Install missing pieces at the narrowest supported scope through [Tool Integrations](11-tool-integrations.md); out-of-project changes require authorization covering that scope.
- Update dependencies/configuration in compatible groups after checking stable versions, changelogs, peers, engines and lockfiles. Do not force installs, apply automatic audit downgrades, add redundant dependencies or migrate frameworks/providers to match an example. Major incompatibilities, production/data migrations, new costs and destructive changes need a specific scoped decision.
- Refactor only for observed responsibility, dependency or duplication problems. Preserve public behavior, validation, error handling, accessibility and tests; broad architectural changes are separate decisions. Apply quality-rule changes through [Tests and Builds](05-tests-and-builds.md).
- Before altering meaningful configuration, retain a recoverable private backup and record original location/content identity. Bind the change plan to the target and current content; journal applied operations. Replace only authorized sections in mixed files and retire obsolete registrations as well as their files. Keep backups outside source control and instruction discovery paths.
- Resume from verified actual state. Restore only content still matching this operation's output; subsequent user edits require reconciliation. Do not overwrite them during rollback. Preserve recovery records even when some setup components remain blocked.

## Verify and finish

Establish the native evaluation method and relevant initial smoke cases through [Workflow Maintenance](09-workflow-maintenance.md). Compare a disposable improvement candidate only for an observed failure; optional labs and paid experiments are separate choices.

Use [Tests and Builds](05-tests-and-builds.md) for project behavior and [Tool Integrations](11-tool-integrations.md) for real client loading/execution. Check safe reruns for duplicate sections, servers, hooks, skills and scripts while preserving customizations; do not reinstall everything to prove repeatability. A restart, login or trust step remains a precise pending intervention until observed.

Update canonical records through [Context and Handoff](07-context-and-handoff.md), including commands, decisions, coverage, validated versus configured-only capabilities and maintenance/recovery instructions. Apply required [Code Review](06-code-review.md), including post-implementation security coverage. Repository gates follow [Merge Readiness](08-merge-readiness.md) as a selected plugin requirement, not an implied permission to alter live rules or publish.

Finish authorized setup work when applicable items are resolved or have evidenced external blockers, relevant checks have run, introduced regressions are fixed and records match reality. Mark enrollment successful only after every mandatory requirement qualifies. Report what changed, actual proof, limits, interventions and the next action; confirm successful onboarding once.
