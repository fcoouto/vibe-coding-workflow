# D10: Review my Project

D10a/b instructions implemented · 27 October 2026 · The approved focused source-structure instruction slice is implemented; D10c behavioral qualification and managed retention integration remain incomplete.

**Goal:** let the user review selected repositories or an umbrella, enrolled or not, without required or silent enrollment. The skill is **Review my Project**, ID `review-my-project`. D10 is a separate deliverable in the [canonical implementation plan](onboard-my-project-plan.md#5-small-deliverables); it does not block D6/D7 or become a mandatory onboarding step.

For an enrolled Project, reuse [canonical membership](onboard-my-project-plan.md#project-and-repository-model) and qualified D3/D4/startup resolution. An unenrolled umbrella is temporary explicit review scope, without enrollment, standing join authority or auto-joining; standalone unenrolled review remains available. Follow [shared retention](onboard-my-project-plan.md#evidence-retention) using canonical target-to-owner references in existing private evidence metadata: repeated/subset/aliased reviews keep original ages/allowances, enrolled members keep their Project accounting, and overlaps reuse reconciled owners. Unresolved identity limits detailed retention, never creates another allowance or registry. D10's review owner integrates this with existing D5 artifact metadata. Preserve per-repository evidence/actual cwd; workflow diagnostics belong to last-deliverable [D11](d11-workflow-diagnostics-plan.md).

## Select the review

Select repositories first, then one or more areas or **Full Scan**. Use native multi-select when supported, with a simple numbered/text fallback. Preserve both selections.

| Area | Coverage |
| --- | --- |
| Code quality | Lint, file size, duplication, responsibility and maintainability |
| Correctness and tests | Bugs, edge cases, important missing tests and existing test/build results |
| Security and dependencies | Relevant security risks and dependency findings supported by available inspection/tools |
| Architecture and performance | Boundaries, complexity, evidence-backed risks and measured findings where available |

Full Scan covers all applicable areas only in the selected repositories, at a stated bounded depth with exclusions and gaps. Workflow health and context/token efficiency diagnostics remain separate, including under Full Scan; project review does not start them.

## Planned focused source-structure assessment

The user-approved [oversized-file and agent-context flow](onboard-my-project-plan.md#oversized-files-and-agent-context) adds a focused assessment under Code quality, using the existing skill. The selected review entry and procedure now load its focused instructions only with matching explicit approval; ordinary structural observations remain available under Full Scan. Its scope, analysis-only approval, subsequent refactoring approval and distinction from D11 measured diagnostics are defined there. This instruction slice is implemented but not behaviorally or natively qualified.

The selected review procedure permits context-burden estimates only in the explicitly approved focused assessment, without activating workflow/usage diagnostics. It rechecks shortlist freshness, distinguishes per-repository counted/inspected/excluded/unknown coverage, groups large reports within each repository, and treats priorities as sample selection only. Keep repositories-before-areas selection, safe deduplicated checks, temporary unenrolled scope, separate installation authority and the existing retention boundary. Full Scan alone never loads the focused instructions. Actual refactoring remains a separately approved normal-development follow-up, not a mutation mode of review. The D3 five-minute onboarding screen remains deferred; this review instruction does not claim it is implemented.

Complete D10c by observing the focused path on supported clients: fresh and stale shortlists, grouped partial umbrella coverage, explicit unknowns and sample-only priorities, plus an ordinary Full Scan that never starts the focused assessment. Verify analysis approval permits no source changes, accepting the report grants no implementation authority, and only specifically approved refactoring proceeds through normal checks. Preserve chat-only detailed reporting while managed retention is unavailable; distinguish likely structural impact from measured savings. No new skill or review engine is introduced.

## Inspect safely and reuse evidence

Read project rules and inspect command definitions/effects before running existing safe local lint, tests and builds by default. Do not trigger GitHub Actions, recurring/startup/periodic scans or automatic adjustments. Unsafe, unavailable or out-of-scope commands leave explicit gaps while independent inspection continues.

Reuse project tooling, relevant current evidence and installed review capabilities, such as a scoped Ponytail audit; create no duplicate audit engine. Project rules are authoritative. Where standards are absent, present recommendations rather than invented requirements. Reuse D5/D6 evidence when available and applicable, without requiring enrolled state for standalone review.

Run each canonical command once per unchanged input and share its result across categories. Rerun only affected checks after relevant changes. Do not add a second file-size checker when lint already covers it. Report actual inspected, executed, reused and unverified coverage, with evidence freshness and limits. Missing observations never count as passing; do not claim exhaustive assurance or invent measurements.

Preserve project content, except specifically approved installation effects. Use existing privacy/isolation arrangements for reports and disposable artifacts; inspect check effects accordingly. No unapproved auto-fix mode is allowed.

## Keep installations and fixes separate

If a missing tool, package or library would help, explain its package, purpose, installation scope and affected files, including manifests and lockfiles. Prefer existing or isolated tooling. Obtain explicit approval **before installation**; approval to scan does not authorize installation. Declined or unavailable tooling leaves a coverage gap, not a pass, and does not stop independent inspection.

Each finding gives evidence/location, impact, confidence, the smallest useful fix and effort. Present selected fixes for separate approval. Scan or installation approval never authorizes fixes. Only the separately approved fix scope proceeds through the applicable normal project workflow, without silent enrollment or unrelated edits.

## Delivery ownership and boundaries

**Canonical owner:** project-review authoring/implementation owner, with independent review. Preserve the user's coordinator settings and existing task/scope-based worker-selection rules. Follow the [instruction authoring standard](../AGENTS.md#instruction-authoring): eventual entry point at most 150 words, containing purpose, essential boundaries and selective loading triggers; detailed procedures load only for the selected review. Existing project workflow and evidence contracts remain their rule owners.

| Subdeliverable | Dependencies and boundary | Acceptance evidence |
| --- | --- | --- |
| D10a — interaction and procedure | Canonical enrolled membership or temporary unenrolled selection, project rules and available capabilities; no new audit engine | Short entry point; repositories-before-areas selection/fallback; explicit installation and fix boundaries |
| D10b — review integration | D10a; reuse existing command/evidence facilities and privacy/isolation | Deduplicated safe checks, accurate coverage and actionable findings; no changes to D6/D7 ownership |
| D10c — behavioral qualification | Reviewed D10a/b; disposable repositories and supported client surfaces | Observed cases below, reported separately from document/package checks |

Acceptance examples: an unenrolled repository and temporary umbrella work without enrollment/auto-joining; repeated/subset/aliased/overlapping temporary reviews preserve ages, reconciled owners and enrolled Project allowances, with unresolved identity limiting detail; repository selection precedes areas; code-quality-only stays selected; Full Scan states depth/coverage only for selected repositories; categories reuse one unchanged local check at its real cwd; named installation requires approval and denial preserves a gap; installation does not authorize a fix; only selected approved fixes proceed; project review excludes workflow/token diagnostics. The [D10 validation record](d10-validation.md) covers the implemented instruction slice and one bounded procedure probe. These acceptance cases remain incomplete until D10c, owner/retention integration, and relevant qualification are completed; no membership authority is added.

## Related onboarding direction

Applicable lint installation belongs to the [canonical onboarding owner](onboard-my-project-plan.md#project-and-repository-model), while D10 keeps separate installation approval. Adapt the Toolkit's 350-line reference to accepted project counting rules and protections. This records direction only; onboarding implementation/qualification remain with D3/D4 and accepted check definitions with D5.
