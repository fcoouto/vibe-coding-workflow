# Onboard my Project

Design and implementation plan · 25 October 2026 · **Stages, feature baseline, activation behavior, client scope and all eleven policy contracts approved; D1 startup, D2 Codex runtime and D3 private planning implemented; bounded native D2 qualification recorded**

Outcome: enroll a project once, then activate its agreed workflow during ordinary coding requests. Qualify each client's actual behavior. Codex startup, opt-in D2 task controls and the D3 private inspect/plan workflow exist. D3 does not enroll or modify projects; D4 application/recovery, qualification and merge enforcement remain outstanding.

Contract loading: [policy index](../policies/00-index.md). The user approved all eleven contracts on 25 October 2026.

Track draft approvals in development records; release packages include only approved contracts.

Contract approval does not establish client execution or project adoption. D1 startup qualification and bounded D2 native execution evidence are recorded separately.

D1 startup implementation is recorded in [Codex validation](codex-validation.md). D2 controls and bounded native observations are in [D2 validation](d2-validation.md); the bundled controlled Stop-held Interrupt case passed, while ordinary read-first correlation, desktop UI and model policy compliance remain unqualified.

The [concrete D2 plan](d2-runtime-plan.md) scopes native state, guards, invalidation, Stop handling and diagnostics. Superset remains optional; no backend integration or onboarding choice is added in D2.

The [D3 plan and validation record](d3-onboarding-plan.md) describe the implemented private inspect/plan workflow and its limits; D4 applies an approved plan. Native operation remains the default, with no Superset question during initial onboarding. The separate [Enable/Disable Superset skill](superset-feature-map.md#planned-project-control-skill) is planned with qualified Superset integration in D6; explicit disable restores native routing for new tasks.

The user authorized the same startup layer for the next clients. Claude Code now reuses the shared startup protocol; Superset is documented as a host for native adapters. See [Claude and Superset validation](claude-and-superset-validation.md). This advances startup support only; D8's full lifecycle qualification still follows the required runtime/onboarding slices.

## 1. Authority and scope

1. **Vibe Coding Toolkit defines the workflow.** [Prompt 12][setup] governs existing-project onboarding. Follow its complete applicable procedure and current catalog, including native harness evaluation. New-project creation and machine setup retain their separate entry points.
2. **The user's decisions define project-specific choices and extensions.** Automatic workflow controls, shared coordination and required merge review are our requested extensions. The toolkit itself excludes Git hooks, branch/worktree requirements and commit/push protections from ordinary setup. Do not introduce those as toolkit requirements.
3. **Official client documentation defines adapter behavior.** An unsupported capability remains unsupported.
4. **`vibe-setup` supplies implementation lessons only.** Reuse concepts after evaluation; implement small modules against the new contracts.

Reviewed toolkit revision: `790a895304e0c08b70a5b215c9d334f1c86b816c`. Secondary reference: `vibe-setup` at `aa72e11fd05252fbedc3258813b9c6144ddb3101`; both matched `main` during research.

For authoring, setup and reviewed updates, consult Toolkit as the workflow authority. For every new onboarding/update run, resolve current toolkit `main` once; read required sources at that revision outside the project and record it. Resume interrupted setup at its recorded revision. A trusted available copy may support offline setup with freshness explicitly unverified; unavailable sources block only dependent setup work.

Runtime uses complete, locally authored contracts and accepted project configuration. It requires no Toolkit checkout, permanent snapshot or upstream fetch, including agent-side policy reads after hooks. Keep source provenance and requirement coverage in the [maintenance source map](policy-sources.md), outside routine loading paths. Temporary source retrieval during authoring/setup is sufficient; do not ship a copied repository or mirrored prompt collection. Review Toolkit changes before updating contracts; never silently change an active task's rules.

## 2. Stages and policy decisions

The user approved these three stages, the feature tables, activation behavior below and all eleven policy contracts. Implementation choices for unbuilt stages remain proposals.

| Stage | Responsibility | Evidence |
| --- | --- | --- |
| **1. Installation** | Make the plugin's capabilities available in the selected clients | Package discovery and working required adapters, hooks, runtime and diagnostics |
| **2. Project Onboarding** | Resolve conflicts, adopt mandatory policies and configure their mechanisms for the selected project | Recorded decisions, qualified project configuration and complete toolkit coverage |
| **3. Runtime** | Evaluate adopted policies for each task and enforce their required actions | Applicability decisions and current check, review and completion evidence |

### Activation and communication

The [Scope contract](../policies/01-project-scope.md#authority-and-activation) defines activation and communication. D1 must verify enrolled, unenrolled and broken-integration behavior; silent activation does not establish integration health.

### Project Onboarding steps

The entry point is **Onboard my Project**, skill ID `onboard-my-project`; keep its entry instructions within 150 words. It calls the current upstream procedure and the plugin's small onboarding helpers.

| Step | Agent does | User sees |
| --- | --- | --- |
| Inspect | Resolve target, read instructions, classify features and adoption, identify policy conflicts, assess merge-gate feasibility and run safe baseline checks | A feature table with requirements, adoption, evidence and conflicts |
| Decide | Select an onboarding mode when conflicts exist, then resolve unknowns without waiving required features | One focused question at a time, recommendation, impact and reversibility |
| Plan | Build the full toolkit coverage matrix and exact proposed changes | Reviewable design/plan, outstanding choices and applicable authorization |
| Apply | Execute approved changes in dependency order with recovery records | Progress and specific blockers |
| Prove | Check configuration, new-session loading, actual execution and reruns | Evidence, remaining limitations and next actions |

### Installation capabilities

| Feature | Mandatory? | Installation establishes |
| --- | --- | --- |
| Plugin package and entry skills | Yes | Discovery of the workspace, onboarding and maintenance entry points |
| Client adapter and automatic hooks | Yes | Required events load and execute in each selected client; additional clients remain a separate choice |
| Workflow engine, state and diagnostics | Yes | Policy evaluation, durable progress and detection of broken integration |
| Configuration, update and recovery mechanisms | Yes | Planned changes, apply, resume and rollback |

Installation makes capabilities available. Project adoption and task compliance are established in their respective stages.

### Project policies and runtime decisions

**Mandatory policies are non-negotiable in every onboarding mode.** Adopt the policy and qualify its mechanism during Project Onboarding; evaluate its applicability during Runtime. Conditional execution never makes adoption optional. This approved feature baseline supplements the complete upstream catalog; no target project has been assessed.

| Feature / policy | Mandatory adoption? | Runtime decision or behavior | Project adoption |
| --- | --- | --- | --- |
| [Project Scope](../policies/01-project-scope.md) | Yes | Resolve the repository, instructions, permissions and task state | Not assessed |
| [Project Onboarding](../policies/10-project-onboarding.md) | Yes | Assess the complete catalog, required integrations, equivalents and justified exclusions; qualify enrollment | Not assessed |
| [Task Planning](../policies/02-task-planning.md) | Yes | Determine planning depth and completion criteria | Not assessed |
| [Tests and Builds](../policies/05-tests-and-builds.md) | Yes | Select relevant checks and require current results before completion | Not assessed |
| [Security Review](../policies/04-security-review.md) | Yes | After implementation, assess actual changes and require applicable security coverage before completion or merge | Not assessed |
| [Code Review](../policies/06-code-review.md) | Yes | Review requirements, behavior and regressions before every merge; determine independence and specialist involvement by risk | Not assessed |
| [Agent Delegation](../policies/03-agent-delegation.md) | Yes | Select execution mode, worker capability and effort; coordinate resource ownership and bounded escalation | Not assessed |
| [Context and Handoff](../policies/07-context-and-handoff.md) | Yes | Update affected records and preserve enough context for reliable continuation | Not assessed |
| [Merge Readiness](../policies/08-merge-readiness.md) | Yes | Permit a merge only after applicable checks and reviews pass for the current changes | Not assessed |
| [Workflow Maintenance](../policies/09-workflow-maintenance.md) | Yes | Revalidate affected capabilities after relevant changes and investigate observed failures | Not assessed |
| [Tool Integrations](../policies/11-tool-integrations.md) outside required scope | No | Use selected additional integrations with their prerequisites; required catalog/project capabilities remain mandatory | Not assessed |

Security Review covers security; Code Review covers general requirements, behavior and regressions. Neither requires a separate specialist agent for every change. Stack-specific tools follow the complete onboarding assessment, including its default native evaluation method. Capabilities and implementation choices remain distinct: durable state is required; SQLite is proposed.

### Readiness and evidence

Track three facts separately: **policy adopted and mechanism qualified**, **action applicable**, and **action satisfied**. A policy-based reason may make an action inapplicable. Missing prerequisites, unavailable reviewers or failed checks cannot provide that reason. Unknown applicability remains unresolved; it cannot count as satisfied.

Proposed feature records: `id, stage, mandatory_adoption, basis/source, execution_rule, adoption, verification, evidence_or_blocker`. Stage values are `installation`, `project_onboarding` and `runtime`. Adoption is `not_assessed`, `adopted`, `reused_equivalent`, `not_adopted` or `blocked`; verification is separate (`not_run`, `passed`, `failed`). Runtime decisions record the policy/task identity, applicability, reason, required actions and current evidence. Installed/configured alone is insufficient; existing equivalents require behavioral evidence.

**Project readiness:** apply the [mandatory-adoption rule](#project-policies-and-runtime-decisions) throughout the accepted scope. Missing adoption or mechanism qualification leaves Project Onboarding incomplete, with the blocker and remedy. Qualification proves the policy can operate; it does not require executing every possible future review or preapprove any future task. Runtime enforces triggered actions again. An unavailable required specialist blocks dependent completion or merge while independent authorized work continues. Optional omissions may remain explicit.

### Choose how to handle existing policies

Use the [scope contract's conflict rules](../policies/01-project-scope.md#when-instructions-conflict) for the three modes, required decisions and runtime boundaries.

Record `onboarding_mode`, repository/client scope and the decision reference in project policy. The enrollment journal binds authorization to the reviewed migration scope. Optional omissions use `not_adopted` with reason `deferred_by_user_policy`; required conflicts remain `blocked`.

**Proposed replacement boundary, awaiting refinement:** replace the selected project's AI workflow instructions, hooks and agent configuration; retain product requirements, application code, architecture constraints, credentials and unrelated tooling. Shared/global integrations require separate scope decisions. The mode does not override host or organization controls, or authorize new costs and production changes.

“Replace” means the entire legacy workflow layer within that scope, including compatible old process rules, rather than only conflicting rules. Working tools may be reused under the new policy. List preservation exceptions in the migration preview so the resulting workflow has one clear authority.

Archive whole files only when they contain exclusively superseded workflow material. For mixed files, back up the original and replace only reviewed sections. Keep backups outside the repository and client instruction/skill discovery paths; record original locations, hashes and restoration steps. Retire obsolete hook registrations as well as their files, then verify behavior in a new session. Rollback preserves subsequent user edits through the existing conflict checks.

The agent identifies semantic conflicts; scripts validate and apply recorded resolutions under the scope contract.

### Questions within the selected mode

Use the [scope contract's decision rules](../policies/01-project-scope.md#when-instructions-conflict). The following record format and question transport are proposed implementation details.

Record each material decision as `id, scope, options, selected_value, provenance, status, affected_actions, invalidation_trigger`. Provenance distinguishes user confirmation, existing project rules, observed facts and assumptions. Status is `confirmed`, `inherited`, `proposed` or `pending`. Store the evidence/reference behind inherited choices. The enrollment journal also binds approvals to a design/plan digest, scope and user-message reference. Material revisions reopen only affected decisions and approvals.

Use the host's question UI when available and ordinary conversation otherwise. Hook subprocesses never attempt an interactive questionnaire. In a noninteractive run, return the pending question and continue independent authorized work.

## 3. Architecture

Keep shared workflow contracts in `policies/`, entry skills in `skills/`, and design, plans and source mapping in `docs/`.

The [Superset feature map](superset-feature-map.md) identifies existing host capabilities to reuse and the workflow guarantees still needed. Consult it when scoping D2–D6; it preserves the approved contracts and standalone client targets.

### Client scope and adapter organization

Support targets are Codex, Superset, Claude Code and Claude Desktop's Code and Cowork surfaces. Claude Chat is out of scope. Keep client implementations under `runtime/adapters/`; add modules or subdirectories only when implementing that client. Share policy and procedures, loading only the adapter instructions needed for the current task.

Codex and Claude Code share the compatible `SessionStart` JSON subset in `runtime/adapters/session_start.py`, with a thin module per native client. Superset launches those agents rather than supplying another startup protocol; preserve that distinction and qualify its launch/permission behavior separately.

Organize client interface specifications under `clients/`, using `index.md` and descriptive client names such as `codex.md`. No numeric prefixes are needed.

The index identifies each client's scope and when to load its specification. Add files with their implementation slice, without empty placeholders. Runtime modules retain language-appropriate names under `runtime/adapters/`.

Qualify Desktop Code and Cowork separately; reuse Claude Code behavior where capabilities match. [Desktop local/SSH Code sessions support plugin installation](https://code.claude.com/docs/en/plugins/install). [Cowork supports hooks and subagents](https://support.claude.com/en/articles/13837440-use-plugins-in-claude). Package availability alone does not establish full workflow support. Missing mandatory mechanisms keep that surface unqualified under the existing readiness rules.

```mermaid
flowchart TD
    H["Client event"] --> A["Client adapter"]
    A --> E["Shared workflow engine"]
    P["Accepted project policy"] --> E
    S["Task state and evidence"] <--> E
    E --> R["Client response"]
```

**Proposed runtime:** Python 3.11+ and its standard library, including SQLite for local coordination. Detect the interpreter; a missing runtime becomes a workspace prerequisite. Keep code in the installed plugin. Project repositories receive policy and necessary documentation/configuration, without duplicated runtime scripts.

| Component | Responsibility |
| --- | --- |
| `runtime/adapters/codex.py` | Probe the actual client surface/version; normalize Codex events; render supported responses |
| `runtime/adapters/claude_code.py` | Later, provide the same contract through Claude's native mechanisms |
| `runtime/engine.py` | Evaluate accepted policy and task state; return decisions without host-specific JSON |
| `runtime/state.py` | Short transactions, event deduplication, task identity and resource ownership |
| `runtime/onboarding.py` | Inventory, source revision, decision records and coverage plan |
| `runtime/changes.py` | Planned edits, fingerprints, backups, apply/resume/rollback |
| `runtime/evidence.py` | Check/review provenance, freshness and completion requirements |
| `scripts/workflow.py` | One command entry point for hooks, diagnosis and enrollment operations |

Add modules only with their deliverable. Avoid an SDK, daemon, dashboard or separate orchestration service at this stage.

### Adapter contract

```text
probe(target)                 -> capabilities + observations
normalize(native_event)        -> Event | UnsupportedEvent | InvalidEvent
evaluate(event, policy, state) -> pass | deny | context | pending_decision
render(result, native_event)   -> stdout JSON + exit status
plan_config(existing)          -> owned edits + conflicts + validation
```

`Event` contains a schema version, client/surface/version, native event and call IDs, session/actor identity, resolved repository/worktree, operation and observable settings. Missing data stays unknown. Internal `pending_decision` is never blindly serialized as a client hook response. `pass` preserves the client's existing permissions; it does not grant additional access.

Capabilities distinguish `documented`, `configured`, `trusted`, `observed` and `unsupported`. Qualification is bound to client version, surface, adapter/runtime digest and relevant configuration. A successful mock is not observed client execution.

`doctor` runs independently of the hooks it diagnoses. Missing, disabled or untrusted hooks and changed qualification inputs invalidate current protection claims; old observations remain history. Where current trust or execution cannot be observed, report unverified.

### Persistence

| Location | Contents |
| --- | --- |
| `.vibe-coding-workflow/project.json` | Versioned project ID, schema version, accepted feature requirements/adoption and policy, onboarding mode/scope, source revision, selected clients and canonical-document mappings |
| Existing canonical project docs | Toolkit setup record, decisions that affect architecture, quality commands and maintenance; reuse upstream's nine-destination map |
| One machine-local data directory | Enrollment journals, private backups, capability evidence and SQLite task/ownership state; shared by qualified clients |

The shared data directory is selected during enrollment and stays outside Git and plugin installation caches. Do not assume two vendors' `PLUGIN_DATA` directories share state. Exclude secrets and raw transcripts from routine records. Use SQLite only on a supported local filesystem.

Identity is `(project_id, local checkout/common Git directory, worktree, session, task_id)`. Resolve nested directories, linked worktrees and separate clones explicitly. A parent directory containing several repositories does not authorize enrolling all children. Register cross-repository membership only when selected.

Bind active tasks to policy, source and runtime versions. Defer incompatible enrollment/runtime/state-schema updates until affected writers are confirmed stopped; then reconcile pending tasks and evidence. Never silently switch an active task's rules. Other clients using shared state must pass schema/version compatibility checks.

## 4. Hooks and enforcement

| Native event | Intended behavior | Limit |
| --- | --- | --- |
| `SessionStart` | Resolve enrollment; inject a short policy pointer and outstanding state | Unenrolled repositories receive no workflow changes |
| `PreToolUse` | Check supported guarded actions, approved task scope and resource claims | Unknown tool paths are not advertised as protected |
| `PostToolUse` | Record observable results and mark affected evidence stale | A completed action cannot be undone by this hook |
| `SubagentStart` / `SubagentStop` | Correlate workers and observed lifecycle | A start event alone is too late to prevent dispatch |
| `Stop` | Check explicit task completion state; request a bounded continuation when useful | Never loop on unanswered questions, cancellation or external blockers |

Use host-specific hook files, such as `hooks/codex.json` and later `hooks/claude-code.json`, with explicit manifest references. Inspect existing interceptors and preserve RTK or other working integrations. Register each handler once.

Runtime rules:

- Validate a top-level JSON object and event-specific fields; bound input size and execution time. Serialize only supported responses.
- Keep the fast path local: no upstream fetch, model call, full test suite or expensive rescan per event. Inject context on relevant transitions; unchanged events normally emit nothing.
- Orientation failures produce a short diagnostic. Failure of a required check prevents a success/ready verdict. A live guard denies an affected action only through a mechanism proven to block in that client; timeout or missing-hook behavior must be measured separately.
- Keep transactions brief. No model, network or long-running process executes while holding a state lock.
- Track native call IDs where available. Handle duplicate and out-of-order events without double-applying state changes; use idempotent transitions when the host supplies no unique event ID.
- Default to at most one automatic continuation for the same unresolved stop condition. Respect smaller user limits and explicit pauses. Ending with `blocked` or `awaiting_user` remains valid.

**Verified platform constraints:** Codex requires trust of the current plugin hook definition. Its current `PreToolUse` does not support `permissionDecision: "ask"`; that response can fail the hook and allow the tool to continue. Cloud-orchestrated ChatGPT Work does not support plugin hooks. Qualify local Codex first, and show unsupported surfaces honestly. Claude has different output and registration semantics. [Client sources: 4–7 below.]

### Evidence, general review and Security Review

Task states: `planned`, `active`, `awaiting_user`, `blocked`, `verifying`, `ready`, `cancelled`. Within the runtime API, only the verifier can transition to `ready`; an agent's success message is insufficient. Accept independent review provenance from a correlated reviewer execution observed by a qualified adapter, or a trusted external integration. A report's own claimed identity cannot establish provenance. Local records protect workflow integrity; they are not a security boundary against processes with the same filesystem permissions. Repository enforcement has a separate trust boundary below.

Bind results to the candidate content, base revision, relevant check definitions, policy digest and reviewer/executor provenance. Account for staged, unstaged and relevant untracked content; HEAD alone is insufficient. A change to those inputs invalidates affected evidence. Recheck actual content before completion because a missing hook must not preserve stale success.

The [Review contract](../policies/06-code-review.md#choose-coverage) defines general coverage and risk-based independence. The [Security Review contract](../policies/04-security-review.md) defines its separate timing, scope and blockers; [Tests and Builds](../policies/05-tests-and-builds.md) defines proof and freshness. The runtime must implement these decisions without treating an unavailable required reviewer as inapplicable.

Worker routing follows the approved [Delegation contract](../policies/03-agent-delegation.md). Cross-vendor execution is a later integration, not an assumed feature of a hook adapter.

### Ownership and merge assurance

The [delegation contract](../policies/03-agent-delegation.md#ownership-and-parallel-work) defines ownership, parallelism and recovery. D6 implements transactional reservations and qualifies which restrictions the client actually enforces.

The [Merge contract](../policies/08-merge-readiness.md) defines the repository gate, trusted evidence, bypass/queue qualification and authorized merge behavior. D7 implements and qualifies those controls; client hooks alone do not establish repository enforcement. [GitHub sources: 8–9 below.]

## 5. Small deliverables

Each deliverable receives its own reviewable change and evidence. Unit/fixture validation and actual client qualification are reported separately. A missing target client does not prevent implementing independent slices.

| ID | Deliverable | Concrete output | Acceptance |
| --- | --- | --- | --- |
| **D1** | Codex adapter and startup hook | Event contract, root resolver, `codex.py`, `hooks/codex.json`, dispatcher and manifest wiring | Nested/worktree fixtures resolve correctly; unrelated repo is untouched; a real installed/trusted hook loads the policy once |
| **D2** | Deterministic hook runtime | Local state, guarded-action responses, post-tool invalidation, bounded Stop handling and `doctor` | Actual denial blocks; pass preserves native permissions; missing/untrusted/disabled hooks, crash and timeout produce honest health; pending decisions cause no continuation loop or implicit permission grant |
| **D3** | Guided onboarding plan | `onboard-my-project` skill/procedure, inspect/plan CLI, private versioned plan and exact proposal schema | Three stages distinguished; full catalog covered; mandatory policies separated from conditional actions; no mode waives a policy; equivalents require evidence; merge feasibility established |
| **D4** | Reversible Project Onboarding and toolkit adoption | Transaction module, approved component execution, mode-aware configuration/docs, inactive backups, `apply`, `resume`, `rollback` | Missing mandatory policy/mechanism qualification prevents readiness; future task evidence remains separate; required conflicts resolve or block; recovery preserves unrelated content |
| **D5** | Checks, general review and security review evidence | Accepted check/review policies, applicability decisions, check runner and completion verifier | Security review runs after implementation with no planning-time review gate; every merge receives general and applicable security coverage; missing/stale required evidence or blocking findings prevent readiness |
| **D6** | Worker routing and concurrent ownership | Approved delegation contract, model/effort evidence, bounded native dispatch, atomic reservations and stop reconciliation; optional qualified Superset integration and its separate enable/disable skill | Fifteen concurrent claims cannot acquire overlapping resources; limits/approved fallbacks hold; unsupported selection is explicit; uncertain ownership survives; reviewer restrictions and policy updates are tested; explicit Superset disable routes new tasks natively without migrating active tasks |
| **D7** | Repository merge gate | Trusted evidence integration, disposable enforcement qualification and exact ruleset plan, delivered separately below | Missing/stale review or failed checks prevent merge through supported UI/API/CLI paths; absent trust/access remains blocked |
| **D8** | Claude Code adapter | Native manifest/config adapter and shared contract fixtures | The same scenarios pass in an actual Claude session; no duplicate handlers or policy fork; settings evidence remains truthful |
| **D9** | PHIOON pilot | One Python and one Next.js repository, then one bounded cross-repository task | Ordinary requests activate workflow without skill mentions; shared-resource coordination and relevant upstream harness cases pass; overhead is measured |

Sequence: **D1 → D2 → D3 → D4**, then **D5 → D6 → D7**. D3 planning is implemented; D4 adoption/application is the next onboarding stage. D8 can follow D4 independently; D9 follows the capabilities selected for the pilot. D7 includes a distinct review of the concrete repository settings before any live changes. Multi-repository rollout follows the pilot, not automatic enrollment of all nine repositories.

Scope Superset and Claude Desktop surfaces as separate follow-up slices after capability discovery; do not infer their qualification from D8. Qualify the implemented D1 startup slice before extending the runtime.

Keep the larger items reviewable:

- **D3a:** mandatory policy adoption, separate runtime applicability, conflict inventory and mode selection. **D3b:** complete the plan under the selected mode. Validate required and optional conflicts, a verified equivalent, a missing prerequisite, a duplicate integration, a mixed instruction file and a shared policy. Mode 1 asks how to satisfy requirements, mode 2 preserves compatible behavior and blocks required conflicts, and mode 3 proposes scoped replacement. Every mode rejects missing mandatory policies as ready; a task's inapplicable specialist action does not disable its policy.
- **D4a:** transaction engine and disposable recovery tests. **D4b:** execute approved toolkit adoption through upstream procedures, one dependency group at a time. Include applicable installations/updates/reuse, quality work, integration checks and initial native harness evaluation. A configuration-only result cannot mark adoption complete. Blocked components retain their exact resumption condition; do not build a parallel catalog of custom installers.
- **D7a:** trusted evidence source and final-verifier contract. **D7b:** disposable-repository enforcement, including stale base, altered candidate, failed/cancelled/skipped evidence and applicable merge-queue cases. **D7c:** review and apply the exact live ruleset changes under the user's authorization. A verifier job must explicitly succeed after checking its prerequisites; upstream jobs being skipped must not manufacture success.
- **D9:** include relevant instruction-discovery, partial-blocker, stale-handoff, stop/resume and unchanged-rerun cases from the toolkit, alongside the project checks.

### First implementation slice: D1

Add only the dispatcher, Codex normalization/response module, root resolution, startup handler, fixtures and manifest reference. Use a disposable enrolled-project fixture. Extend the existing package validator to check hook paths. Keep enforcement handlers for D2.

Implemented with the [Codex client contract](../clients/codex.md). Native probes required the sole `.codex-plugin/plugin.json` compatibility manifest: the tested builds suppress hook discovery when root `plugin.json` exists. See [validation evidence and limits](codex-validation.md) before reusing the pattern.

Implementation steps:

1. Normalize documented `SessionStart` payloads and resolve the nearest Git checkout, including linked worktrees. Check nested, neighboring and inherited-environment cases.
2. Read only that checkout's enrollment record. Require matching checkout/common-Git identity, selected client and local policy digest; copied or stale records must not activate another checkout. Use fixtures until D4 supplies enrollment.
3. Return a short local client/policy pointer for enrolled scope, nothing for unenrolled scope, and a diagnostic for invalid integration. Wire one manifest handler with bounded input and execution; test malformed input, missing files and unchanged permissions.
4. Run package and behavior checks, then observe installed hook discovery, trust and execution in an isolated real Codex process. Report that evidence separately from desktop UI and model behavior.

Run package validation, fixture checks, `git diff --check`, then a real new-session startup probe on the target client. Record client surface/version and hook trust. If that client is unavailable here, report the live probe as not run. Do not change PHIOON as part of D1.

Check the [approved activation behavior](#activation-and-communication) in enrolled, unenrolled and broken-integration scenarios, distinguishing internal context loading from user-facing messages.

### Project Onboarding transaction rules for D4

Bind the apply plan to target identity, source/policy revision and before-file hashes. Back up changed owned content; write each file atomically and journal progress. Filesystem edits are not a single atomic transaction: recovery reconciles each applied operation. Resume from verified state. Rollback restores only content still matching the plugin's recorded output; concurrent user edits become explicit conflicts. Privileged/external changes remain separate operations with their own authorization and recovery.

## 6. Improvements to measure

| Reference lesson | Proposed improvement | Evidence |
| --- | --- | --- |
| Hooks copied into each project | One installed runtime and small per-project policy | Update touches runtime once; project customizations survive |
| Large instructions injected into workers | Short transition-specific context and on-demand references | Captured hook output size and observed tokens where available |
| Briefs declare writable files | Atomic ownership before managed dispatch | Concurrent conflict tests |
| Native logs treated as qualification | Capability-specific provenance and honest unknowns | Contradictory/missing settings fixtures plus client probes |
| Independent installation/update write paths | One recovery-aware change module | Interrupted apply/resume/rollback cases |

Proposed performance targets, to validate on the target machine: routine local hook p95 below 100 ms, context output within 150 words, and zero network/model calls in the hook fast path. Record end-to-end task latency, introduced regressions, review findings, retries and observed usage. Do not claim token savings from output length alone.

Upstream's native harness method supplies the evaluation procedure: run relevant baseline cases, change one demonstrated weakness, compare a bounded disposable candidate and preserve working behavior. Do not automatically start paid benchmark runs.

## Sources

1. [Toolkit existing-project setup, Prompt 12][setup] — primary onboarding contract.
2. [Toolkit hooks guidance][toolkit-hooks] and [shared instructions][toolkit-agents].
3. [Toolkit native harness improvement, Prompt 15][harness].
4. [Codex hook events, responses and trust](https://learn.chatgpt.com/docs/hooks).
5. [OpenAI plugin packaging](https://developers.openai.com/plugins/build/plugins).
6. [ChatGPT/Codex plugin surface support](https://learn.chatgpt.com/docs/plugins).
7. [Claude Code hooks](https://code.claude.com/docs/en/hooks).
8. [GitHub rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets).
9. [GitHub required-check behavior](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks).
10. Secondary reference: [`vibe-setup` workflow transactions][reference-workflow], [subagent hooks][reference-hooks] and [native qualification][reference-native].
11. [Instruction authoring standard](../AGENTS.md#instruction-authoring).

[setup]: https://github.com/soumatheusgomes/vibe-coding-toolkit/blob/790a895304e0c08b70a5b215c9d334f1c86b816c/docs/prompts/12-existing-project-setup.md
[toolkit-hooks]: https://github.com/soumatheusgomes/vibe-coding-toolkit/blob/790a895304e0c08b70a5b215c9d334f1c86b816c/docs/tools/10-hooks-best-practices.md
[toolkit-agents]: https://github.com/soumatheusgomes/vibe-coding-toolkit/blob/790a895304e0c08b70a5b215c9d334f1c86b816c/templates/AGENTS.md.template
[harness]: https://github.com/soumatheusgomes/vibe-coding-toolkit/blob/790a895304e0c08b70a5b215c9d334f1c86b816c/docs/prompts/15-harness-improvement.md
[reference-workflow]: https://github.com/fcoouto/vibe-setup/blob/aa72e11fd05252fbedc3258813b9c6144ddb3101/skills/vibe-setup/workflow.py
[reference-hooks]: https://github.com/fcoouto/vibe-setup/blob/aa72e11fd05252fbedc3258813b9c6144ddb3101/.codex/hooks/subagents.py
[reference-native]: https://github.com/fcoouto/vibe-setup/blob/aa72e11fd05252fbedc3258813b9c6144ddb3101/skills/vibe-setup/native_qualification.py
