# Reduce repeated preparation, handoffs, and monitoring

Status: proposed design; implementation requires user approval.

## Intent and agreed direction

Reduce avoidable work during a typical coding task with implementation and independent review. Preserve the full Toolkit workflow, acceptance checks, security, ownership, permissions, and the user's model/provider/reasoning choices.

The user selected shared rules plus support in existing runtime paths over instructions alone. They requested concrete mechanisms and protection against stale facts. They have endorsed the direction, not this implementation design. The reported anecdote identifies possible waste; it is not a measurement of this plugin.

## Approaches

1. **Instructions only:** amend existing policies to prefer compact results, selective preparation, and durable fixes. Lowest implementation cost, but every agent must independently follow the advice.
2. **Shared rules plus existing runtime support, selected:** expose compact observations from existing records, retain scoped failures at their existing execution owner, and preserve authoritative verification. Small deterministic changes make efficient behavior easier to follow and test.

No additional coordinator, generic tool interception layer, service, dashboard, database, model call, or continuous monitoring system is included.

## Scope and explicit design calls

The initial path is direct implementation plus required native independent review. Existing external-worker status is included as another existing output surface; this work never enables an external route or changes its approved task scope. Council topology, model selection, billing, and recovery semantics remain unchanged.

Enforcement applies only to plugin-owned calls and state. Shared instructions cover ordinary shell and connector use; the plugin cannot prevent arbitrary agent calls outside its managed paths. This boundary is a proposed scope choice, not an assertion of universal enforcement.

Routine successful reuse remains quiet. Rechecking reasons are retained in the existing evidence and surfaced when they change the next action or block progress. This is the author's proposed default because the user did not select a notification preference.

## Existing implementation

- `runtime/delegation.py` already manages bounded briefs, ownership, admissions, and a guidance cache with failed-refresh suppression. `delegation_status` returns detailed assignment records.
- `scripts/openrouter_workers.py` persists execution in `result.json`; its CLI status returns the full saved result, including response content. Council already has structured status and event-oriented supervision guidance.
- `runtime/evidence.py:evidence_status` captures current candidate content and evaluates blockers. It is a verification operation, not a cheap progress heartbeat.
- Policies 03, 05, 07, 09, and 11 already require proportionate delegation, reusable valid evidence, selective loading, durable lessons, and capability-based qualification.
- Startup has no network/model calls or writes. This design does not add startup storage, probes, or deduplication claims.

The inspected checkout contains other uncommitted changes. Implementation must reconcile their final interfaces and preserve them; this design does not claim installed-client qualification.

## Runtime behavior

### Compact progress from existing records

Add an explicit compact view to existing delegation and external-worker status interfaces. Preserve existing detailed responses for compatibility; managed instructions use the compact view for progress. Derive it on demand from the authoritative records without a second persisted summary or an LLM summarizer.

Return the task/attempt identity, recorded execution state, observation identity/time when available, result availability/reference, bounded failure category, ownership/stop uncertainty, blockers, and limitations needed for the next action. Do not include report bodies, raw output, full prompts, assignment history, or repeated tool events. A bounded response must disclose omitted detail and provide its existing retrieval location; it must not silently truncate blockers into an apparently healthy state.

Recorded state is explicitly an observation, not proof of current liveness or accepted completion. A running record after a crash remains uncertain until the existing lifecycle mechanism reconciles it. A changed observation identity is a change-detection hint, not evidence freshness or authority.

Fetch the final report for review/assessment when available. Retrieve diagnostic detail by the exact attempt/reference only when a failure, inconsistency, missing proof, or requested investigation needs it. Keep full evidence under existing private ownership and retention rules.

### Wait without repeatedly validating the task

Use the host's existing completion/attention notifications, or bounded process waits when notifications are unavailable. Do not add a polling scheduler or background collector. On an event or wait completion, inspect compact progress as needed; a repeated unchanged result does not justify rereading its report or logs.

User-visible progress follows existing host requirements and may truthfully report waiting without another diagnostic read. Live output remains appropriate when it is necessary to diagnose a stall or satisfy the task; this is not a blanket ban on logs.

Keep authoritative verification at acceptance, relevant changes, and completion. Compact progress never invokes evidence verification merely to see whether a worker finished, and never replaces it. Preserve stop/descendant proof before releasing ownership.

### Preparation and stale facts

Reuse only observations whose relevant dependencies are still compatible. Use existing owner records and evidence references; do not create a universal fact cache. Each reusable observation identifies its scope, original verification evidence/time, dependencies, and invalidation conditions.

| Observation | Required handling |
| --- | --- |
| Stable tool/configuration qualification | Compare relevant executable, configuration, surface, and capability dependencies. Requalify affected behavior after a relevant change or contradictory result. |
| Test/check success | Preserve existing source, command, dependency, environment, and candidate validation. Current HEAD alone is insufficient. |
| Official guidance | Preserve existing compatible-cache reuse, refresh triggers, original timestamps, and failed-refresh suppression. |
| Credentials, authorization, capacity, remote availability | Historical success cannot establish current permission or availability. Keep required live checks at use. |
| Worker completion and stopped ownership | Use the existing trusted lifecycle and reconciliation mechanisms; a saved status is insufficient. |

Cheap local identity comparisons may detect changes; they cannot replace mandatory current validation. A version change alone is not incompatibility, and an unchanged version alone is not proof of compatibility. Unknown dependencies leave only the dependent action unqualified. Do not hash the entire environment, fetch documentation, or probe remote services on every status read.

### Stop repeating a known managed invocation failure

Repair verified invocation/configuration defects in their existing owner so subsequent calls use the corrected definition. Updating a lesson without changing the faulty invocation is not a completed repair.

For an unresolved deterministic setup/invocation failure, extend the affected owner's existing private control/evidence records with a bounded failure observation. Identify the operation and scope, relevant input/configuration/executable dependencies, original evidence/time, classification, and permitted recheck trigger. No credentials, raw remote response, or unbounded log enters the lookup key or summary.

Before the same plugin-managed operation launches again, compare that failure's dependencies. If unchanged, return the retained blocker and evidence reference without relaunching. Suppression is not success and must not mark a required check inapplicable. A relevant change, later authorized maintenance, or explicit retry permits one bounded recheck under existing attempt/deadline/ownership rules. Reuse existing owner locking to prevent simultaneous callers from multiplying that recheck; never reset task budgets or release uncertain workers.

The first implementation must select one concrete deterministic managed invocation failure and its owner during planning. A locally missing configured executable is the proposed case. This is a narrow extension, not a general classifier for arbitrary tool errors. Normal failing tests, ambiguous failures, authentication errors, transient network/service errors, and unknown process outcomes retain their existing treatment. Existing guidance suppression remains its own working implementation.

Store at most the current applicable failure per selected operation/scope, with its original evidence reference. Superseded audit evidence follows existing retention. Missing/corrupt state never establishes passing evidence or turns a required check into an optional one. A repair check that cannot be recorded does not claim durable repair; preserve execution/ownership uncertainty as appropriate.

### Bounded handoff and independent review

Use direct implementation when sufficient and the existing required reviewer path. Do not introduce another lead, council, or supervisor for this workflow. Preserve any supervisor already required by an explicitly selected external route.

Reuse the existing brief/report contracts: objective, authorized scope, applicable instruction references, candidate identity, relevant files, acceptance criteria, checks/evidence references, ownership, and stop condition. Do not transmit the entire conversation or repeat unchanged transcripts. The reviewer must load applicable instructions and inspect the actual diff and necessary context; the implementer's summary cannot replace independent inspection.

Coordinator acceptance still verifies findings, actual checks, current candidate, and ownership. Reuse unaffected evidence only under existing rules. Do not rerun everything because a status was requested, or skip independent proof merely because the worker reported success.

## Instruction ownership and authoring

Keep coordination rules in policy 03, proof reuse in policy 05, selective retrieval/durable records in policy 07, maintenance in policy 09, and capability qualification in policy 11. Change only rules that need clarification; reference their existing owners instead of repeating them in every client/skill.

Update affected client/worker procedures with exact compact/detail loading triggers and observation limitations. Keep skill entry points within 150 words. Follow Skill Creator and preserve source-to-contract coverage in `docs/policy-sources.md`. Any necessary Toolkit research belongs to authoring, never routine execution.

## Verification and completion

Use focused behavioral tests and representative instruction walks:

1. Compact output exposes state, failures, blockers, uncertainty, and retrieval references without full reports/logs; detailed callers retain their existing response.
2. Progress inspection neither runs checks nor grants readiness, changes ownership, launches workers, or makes model/network calls.
3. Repeated identical deterministic setup failure produces one attempted operation and retained blockers. Relevant dependency change or explicit retry permits a bounded recheck; concurrent rechecks do not multiply launches.
4. Source/configuration changes invalidate affected facts. Contradictory evidence wins over historical success. Missing evidence and volatile permissions cannot become cached authorization.
5. An implementation-and-review walk loads required procedures, avoids unrelated setup/Council material, preserves independent review, and performs authoritative completion verification.
6. Existing negative tests continue to reject stale candidates, forged results, and uncertain stopped ownership. Package validation remains `python3 -B scripts/validate.py`.

After implementation checks, compare one baseline/candidate coding task from equivalent isolated starting states with the same model/effort, permissions, acceptance criteria, and required review. Include a verified deterministic setup defect so recurrence behavior can be observed across invocations. Use native execution only within available authorization; no paid/external benchmark is implied.

Measure repeated context/log reads, response bytes, launches/retries, elapsed time, acceptance outcome, and attributable tokens if exposed. Count preparation, review, and verification overhead. Compare unchanged quality first, then observed overhead; do not infer tokens from bytes or claim general savings from one run. Keep test artifacts and evaluation notes under existing owners, without a permanent telemetry subsystem.

Completion requires current package/check evidence and an explicit report of actual client execution versus unobserved behavior. If the client comparison cannot run, report implementation proof separately and leave measured effectiveness unproven.

## Builder discretion and remaining approval

The builder chooses exact compact-view syntax, bounded field sizes, test placement, and the smallest compatible extension of the selected failure owner's record. Existing CLI schemas and runtime state migrations must remain readable or have an explicit compatibility transition; do not silently change old meanings. If the selected owner lacks a safe existing persistence/locking boundary, return that design issue instead of introducing a general failure registry.

The user must approve this design before implementation planning. No implementation, runtime installation, configuration change, external execution, release archive, or measured-savings claim is authorized by this document alone.
