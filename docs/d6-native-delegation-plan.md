# D6: Native delegation and ownership

Implementation plan · 26 October 2026 · Cooperative scope approved 4 November 2026. Runtime alignment and native lifecycle qualification remain pending. D6 is on hold.

**Goal:** select native subagents, reserve their work before dispatch, and verify results before integration. D6 is the canonical owner of duplicate-dispatch, resource-conflict and uncertain-interruption controls. Native Codex is the first adapter target; qualify CLI and Desktop separately. Initial onboarding stays unchanged.

The coordinator always retains the user's chosen model and reasoning. For each delegated task, it selects worker model/effort using current official platform guidance and available controls. Implementation assignments below name roles, not fixed models.

Any non-native model or execution route requires explicit approval; local models also require assessment. Their assessment workflow and non-native execution support are deferred, outside D6.

**Basis:** the [D6 deliverable](onboard-my-project-plan.md#5-small-deliverables), [Agent Delegation](../policies/03-agent-delegation.md), [Context and Handoff](../policies/07-context-and-handoff.md) and [D5 evidence controls](d5-checks-and-reviews-plan.md). These contracts retain every requirement. Use Python 3.11+, the standard library and OpenAI's `skill-creator` authoring standard.

## Approved cooperative scope

The user approved cooperative native delegation on 4 November 2026. Use the
native client's existing trust boundary. Reserve each worker's files and shared
resources, dispatch once, observe its actual identity and independently verify
its result. Worker briefs define allowed edits and bounded foreground commands.
The first pilot uses one leaf worker and one read-only reviewer sequentially.

Enforced patch-only tools, per-worker filesystem containment and universal
descendant shutdown proof are deferred guarantees. The canary still uses an
exact patch to exercise its existing hook. Instructions and reservations rely
on participating workers respecting their scope. Unexpected background writers
and uncontrolled external edits remain explicit limitations.

### Normal completion and uncertain ownership

A future cooperative completion path must bind the reserved assignment to the
exact native child and successfully completed turn, account for all observed
tool activity and completed foreground work, and independently inspect the
resulting candidate and effects. Require complete history and no pending host
retry or continuation. Applicable checks and independent review still decide
acceptance. A worker report or a terminal status alone cannot release claims.
This observation supports cooperative completion under the stated trust
assumption. Keep its evidence distinct from proof that every descendant stopped.

Ambiguous launch, missing or contradictory observations, interruption, timeout,
failed attempts, unfinished commands, undeclared activity, unexpected background
work or unexplained effects retain the assignment's ownership, capacity and
consumed budgets. Dependent work stays
blocked. Defer automatic takeover, replacement and recovery from those states.
Separate resolution must establish what happened before any later handoff.
Elapsed time, a cancellation acknowledgement or a fresh run ID cannot clear
uncertainty. Further work by a previously completed child needs new admission
and conflict checks before another turn can write. Before releasing ownership,
recheck the exact assignment, observations, pins, checkout generation, current
candidate and competing reservations in the release transaction. New activity
invalidates the prior assessment.

### Pending implementation and offline acceptance

Current `reconcile_assignment()` and version-2 host proofs require stopped
descendants even for successful native assignments. The adapter deliberately
reports `descendants_stopped=False`. These existing controls continue to apply
until a reviewed implementation supports the cooperative contract. Historical
proofs, failed claims and pinned authorities retain their original meaning.

- [ ] Align native worker and reviewer completion in `runtime/delegation.py`
  and `runtime/adapters/codex.py`, with the dependent consumers in
  `runtime/evidence.py`, `runtime/state.py`, `runtime/changes.py` and
  `runtime/repository_gate.py` identified before edits. Reuse existing identities,
  ledger and observations. Represent
  cooperative completion explicitly without setting stopped-descendant proof
  flags to true. D4 recovery, D5 checks/coordinator operations and D7 consumers
  retain any stronger evidence requirements until separately aligned and reviewed.
  Audit every consumer of `settled` before using that status for cooperative
  release. Dependency admission and readiness must preserve their evidence rules.
- [ ] Add focused offline acceptance cases in `tests/test_delegation.py` and
  affected native/evidence tests. Cover a fully observed normal worker and
  reviewer, wrong identity, missing command completion, stale candidate,
  interruption, timeout, lost dispatch response, unexpected background activity,
  replay and resumed-child conflict. Uncertain cases retain claims and budgets
  and grant no replacement or takeover. Older strict consumers must reject
  cooperative evidence where stronger proof is required.
- [ ] Align `clients/delegation.md`, `clients/delegation-proofs.md` and affected
  runtime/evidence guidance with that implementation, preserving source coverage.
  Independently review the change and run affected offline checks plus package
  validation. Freeze a new [held pilot packet](superpowers/plans/2026-11-04-d6-successor-release-packet.md)
  only after its complete worker, reviewer and check sequence is supported.

The immediate work is this bounded contract alignment. D6's live allowance
remains zero. The sections below retain the implemented foundation and historical
delivery sequence. This approved scope supersedes their universal descendant
proof requirement for the future normal native worker/reviewer path only.

## Existing capabilities and boundaries

- Reuse `runtime/state.py` for identities, pins, revisions and short SQLite transactions; `runtime/evidence.py` for immutable artifacts, candidate capture, review and host reconciliation; and `runtime/adapters/codex.py` for bounded native observation.
- The coordinator already has native delegation tools. It calls `collaboration.spawn_agent` after reservation. Python validates and records the assignment; it does not create another launcher, scheduler or generic backend layer. The inspected app-server schema exposes no native subagent spawn RPC.
- Read-only inspection of CLI 0.163.0 confirmed `model/list` availability and supported efforts. Combine the current surface's available models and dispatch controls with cached official guidance; CLI results do not qualify Desktop. Native explicit worker model/effort overrides require `fork_turns="none"`. Do not alter coordinator settings or global defaults.
- The inspected native tools expose no per-worker working directory, sandbox, writable paths, tool allowlist or descendant limit. Reservations coordinate participating agents. Cooperative scope uses explicit briefs within the native trust boundary. Work that separately requires enforced isolation stays blocked when that capability is unavailable.
- Native spawn records report settings resolved at creation. Thread metadata reports current configuration, not per-turn execution. Keep requested worker settings, configured settings and observed-at-creation settings distinct; unknown execution settings stay unknown. Existing D5 receipts need version-aware interpretation, not rewritten history.

**Approved follow-up, not accepted package proof:** D6 owns the [single-repository worker and linked-job seam](onboard-my-project-plan.md#cross-repository-tasks-and-delivery) in `runtime/delegation.py`, `runtime/state.py` and report/recovery integration in `runtime/evidence.py`. One Repository/worktree limits editable software scope; separately declared shared build/service resources remain possible only when actual effects are covered. Absolute claims/current-scope Git protection do not prove cross-root write/report/recovery coverage, including foreign Git metadata. Reuse the shared ledger, serialize unknown aliases/resources and retain uncontrolled-writer limits. Under policy 03, update `clients/delegation.md`/`clients/runtime.md` with implementation; prove linked jobs, shared effects, hook/path ownership, out-of-scope rejection and preserved pins. With D2/D5 owners, [retirement](onboard-my-project-plan.md#evidence-retention) must cover task/assignment history beyond shared-state-authority-wide 4096 bounds, preserving relevant live/dependency owners and compact replay/reference identity without restored passing evidence. If all remain needed, block dependent admission and allow bounded truthful read-only status/recovery; never truncate uncertainty or switch database/authority. These future obligations do not change accepted D6 scope or native qualification.

## 1. Discover routes, cache guidance and observe workers

**Owner: adapter worker.** Extend `runtime/adapters/codex.py` and focused adapter tests. Extract shared parent/activity/child correlation from `collect_native_review()` without weakening D5's report validation. Reuse the bounded read-only protocol handling in `runtime/doctor.py`.

Provide `discover_native_workers(scope, control_observation)` and `observe_native_worker(scope, attempt, parent_turn_id, spawn_item_id)`. The coordinator verifies exposed dispatch/model/effort controls and supplies a bound observation; Python collects the native catalog and metadata. The inspected API cannot discover the coordinator's tool schemas. Installation, catalog visibility or JSON claims grant no execution authority. Bind observations to client surface/version and invalidate changed capabilities. No credential inspection, configuration changes or model turns for capability discovery.

Reassess delegation and worker selection before dispatch and after material scope, failure or capacity changes. Apply the [model authorization rule](../policies/03-agent-delegation.md#select-capability-and-dispatch): native models are automatically approved; every other model or route needs explicit approval. The coordinator uses the worker platform's official guidance, task complexity/risk, available account access, supported controls and remaining budget to choose the lightest capable model/effort. Preserve the coordinator's user-selected settings, provider and authentication. Prefer direct execution or deterministic tooling when sufficient. When explicit worker selection is unsupported, record the limitation and use documented inheritance only if suitable. Authorization does not establish adapter or cross-client dispatch support; D6 provides no automatic non-native fallback.

**Local guidance cache (runtime worker):** use one small UTF-8 JSON file at `state_dir/model-guidance/<client-surface>.json`, shared by projects using that approved state directory. Cache selection advice, not an availability catalog. The coordinator verifies the official sources and summary; helpers validate shape and freshness, not factual truth. Implement this in `runtime/delegation.py`, reusing private paths and immutable evidence artifacts.

| Cached field | Content |
| --- | --- |
| `schema_version`, `client_surface` | Record format and native surface, such as Codex CLI or Desktop. |
| `checked_at`, `applicability` | UTC verification time, inspected client version and relevant capability fingerprint. |
| `sources` | Official URLs and content digests; recommendations reference these source entries. |
| `recommendations` | Short task profiles: applicable work/risk, recommended model identifiers and reasoning choices, selection conditions and documented limitations. Include only advice supported by the sources; omit unsupported specifics. |

Model names may change in this data without changing policy. At dispatch, intersect recommendations with the current native catalog and controls; cached names never establish access or approval. Load only the selected platform's relevant task profiles. Do not cache full manuals, prompts, conversations, credentials, account details or speculative prices/benchmarks. Compute an immutable snapshot digest for assignment evidence; keep refresh attempts/failures separate so they cannot rewrite the last verified content or check time.

For Codex, use OpenAI's [subagent guidance](https://learn.chatgpt.com/docs/agent-configuration/subagents#choosing-models-and-reasoning) and [model guidance](https://learn.chatgpt.com/docs/models#pick-a-reasoning-effort), checked 26 October 2026. Other adapters later use their own platform's official sources. Do not turn current commercial model recommendations into permanent policy or fixed implementation assignments. Toolkit remains the workflow authority; its checkout is not a runtime dependency.

**Refresh:** populate on first use; refresh for relevant client/catalog changes, missing/corrupt guidance, explicit request and periodic environment maintenance. Review age during maintenance without a fixed daily expiry or a new scheduler. Attempt once per trigger; after failure, routine tasks reuse the recorded outcome until a later maintenance run, relevant change or explicit retry. Future timestamps cannot establish freshness. No 24-hour validity promise or one-hour retry requirement.

Keep only the concurrency safeguards needed for a shared file: a bounded refresh claim under a short lock, bound to applicability and the prior snapshot; atomic publication by the current claim holder; rejection of late/superseded results. Concurrent callers reuse the claim. An abandoned claim may expire without releasing worker ownership. Fetch outside hooks, locks and database transactions. No new database or service; documentation never grants execution authority.

If refresh fails, report stale/unavailable guidance and retain its original check time. A previously verified recommendation may be reused only while its surface/applicability and currently available controls remain compatible; otherwise use a qualified suitable fallback or keep only dependent dispatch blocked. Continue independent coordinator work. Pin the selected guidance snapshot/digest and freshness to each assignment. Refresh affects future choices, never running workers or historical evidence.

Prepare a unique `worker_<attempt_id>` native task name. Observe its prepared parent, native start activity, child origin/path, checkout, version and bounded result. Caller IDs are locators, not proof. A report repeating its assignment digest establishes consistency, not plaintext prompt delivery: native delegation messages are encrypted. Duplicate collection is idempotent; conflicting identities remain unresolved. Version new observation fields so historical D5 `requested_model`/`requested_effort` fields are not mistaken for independently observed dispatch requests.

**Proof:** repeated compatible-cache tasks fetch no documentation; maintenance/change/missing/manual triggers refresh; concurrent or interrupted refresh preserves a complete snapshot; abandoned claims recover and superseded publications are rejected; offline failure suppresses repeated attempts and preserves stale labels. Verify task-appropriate worker selection, new native models without approval prompts, unchanged coordinator settings, unsupported effort/selection controls, unknown observations, mismatched surface/version, wrong children and duplicates. Requested worker settings cannot masquerade as observed execution. Reject unapproved non-native routes; approval alone cannot enable an unimplemented route. A disposable native probe later proves dispatch and observation; schema inspection alone does not.

## 2. Reserve assignments and bound dispatch

**Owner: runtime worker, also responsible for slices 3–4.** Add `runtime/delegation.py` and `tests/test_delegation.py`. Extend `runtime/state.py` and `scripts/workflow.py`; reuse existing identity, expected-revision and artifact formats. Keep the ledger, evidence integration and schema transition in one assignment because they share state and acceptance criteria.

Add one bounded `assignments` table to runtime schema 2. Each record carries its owner/task/pins, coordinator/worker/check role, selection rationale, immutable brief/policy/guidance references, guidance freshness, dependencies, canonical claims, native marker, consumed budgets, requested/observed worker settings, result and reconciliation. Include coordinator-owned resources and mutable D5 check resources in the same ledger. Detailed reports remain private artifacts outside repositories and plugin caches.

| Control | Behavior |
| --- | --- |
| `delegation guidance` | `status` reports cache/freshness; `claim` reserves one bounded refresh attempt; `record` validates its token/current generation and publishes coordinator-verified guidance or a failure observation. These controls never browse or launch models themselves. |
| `delegation plan` | Bind existing route authorization, task/worker-selection constraints, finite time/attempt/resource budgets, concurrency and approved fallback rules. JSON cannot grant authority or reduce accepted requirements. |
| `delegation prepare` | Validate the brief, selected worker settings, guidance evidence and dependencies; reserve claims, capacity and attempt budget atomically for a stable dispatch request. Return launch admission once; request replay returns the existing attempt/state, never fresh permission to spawn. |
| `delegation observe` | Collect native identity/settings/lifecycle through the qualified adapter and bind them to the reserved attempt. |
| `delegation reconcile` | Bind verified results, partial-change assessment and stopped-writer evidence to the exact attempt; release claims only when reconciliation permits. |
| `delegation status` | Report assignments, conflicts, remaining budgets, evidence and limitations without launching work. |

Implement `guidance_status`, `claim_guidance`, `record_guidance`, `plan_delegation`, `prepare_assignment`, `observe_assignment`, `reconcile_assignment` and `delegation_status`. Briefs contain objective, necessary context/instructions, exact files, dependencies/resources, acceptance, checks and stop conditions. Preserve required implementation/check discipline, applicable checks and self-review. Reports state completion, blocker or pending decision, changed paths, evidence and limitations; do not copy the full conversation by default.

Use one approved shared state directory for every participating checkout/session whose resources may overlap. Scan unresolved claims across that database, not only `_scope_id()`, which distinguishes worktrees. Separate databases cannot coordinate shared resources: block overlapping or unknown cross-authority parallel work until owners are reconciled under one authority. Do not silently relocate enrollments or claim host-wide control over external writers.

Within one short write transaction, check pins/revision, conflicts, dependencies, capacity and remaining budget, then insert once. Conflicting reservations are mutually exclusive. Resolve physical paths, existing hard-link aliases, filesystem case behavior and ancestor overlaps; unknown aliases serialize affected work. Identify Git mutations by common Git directory and shared ports, build directories, databases and services by explicit host/resource keys. Direct or transitive dependencies prevent parallel dispatch. Revalidate ownership before integration; branch/worktree separation alone proves no shared-service isolation.

The coordinator owns lockfiles, shared configuration, tracking and Git operations. Workers receive only their assignment. Count all unresolved managed workers against capacity, preserve native host limits and retain one progress entry per wave. Record requested deadlines and stop conditions, but do not claim hard time/token/process enforcement without a qualified mechanism. Exceeding a budget prevents further dispatch; retries and escalation never reset it. Unavailable mandatory limits block dependent work.

**Proof:** fifteen synchronized conflicting requests yield exactly one reservation. Separately replay the same dispatch request before/after launch and after a lost response: at most one managed worker starts, with no extra capacity or budget consumption from replay. Duplicate observation alone does not prove duplicate-dispatch prevention. Cover disjoint work, aliases/ancestors, cross-session/worktree claims, shared Git/services, separate authorities, dependency cycles, capacity/budget races and stale revisions. Native calls, checks and waits never hold the database lock.

## 3. Integrate results, reviews and recovery

**Owner: runtime worker.** Connect delegation to `runtime/evidence.py`, existing task controls and focused evidence/state/dispatcher tests.

Keep execution outcome separate from ownership release. A prepared attempt reserves capacity before spawn. Reconcile the original admission even if its response was lost. Request replay retains the same admission. Apply the [approved completion and uncertainty rules](#normal-completion-and-uncertain-ownership) to the planned cooperative path. Current source still uses D5's strict host-proof boundary, bound to the exact assignment, native identity, pins and original/current candidate. Preserve partial changes and uncertain owners during the transition. Independent authorized work may continue. Qualify the participating-coordinator protocol with its stated native trust assumptions.

Reuse D5's review preparation, collection and coordinator assessment. Link the review attempt to one reservation and retain its `review_<attempt_id>` native marker; do not launch a second reviewer or count the same round twice. Fix the candidate/base, include dirty layers and require independent review where applicable. Set scope, rounds and stop conditions before dispatch; fixes do not reset rounds. Further rounds require new risk, an evidence gap or a user request. Reviewers inspect relevant callers/contracts/tests and remain read-only. Native read-only briefs are cooperative; required enforced isolation remains unavailable until qualified.

Connect D5 `run_check()`/`_reserve()` to the same ledger for declared mutable resources; `reconcile_check()` releases those claims only after verified lifecycle reconciliation. Shared checks must be isolated or serialized against both workers and other checks. Existing unresolved check attempts must also block conflicting reservations.

The coordinator checks changes, findings, dispositions and actual proof, deduplicates root causes and reassesses dependencies before the next wave. Authorized commits remain serialized in task order, with current HEAD recorded before each. Without commit authorization, integrate verified working-tree snapshots. Worker reports cannot establish passing checks, review quality or completion.

Extend `_checkout_attempt_blockers()`, readiness freshness and the final `verify_completion()` transaction to account for relevant unresolved assignments and resources, including other sessions and historical tasks. Hold the verifying coordinator's own claims through verification, then settle/release them atomically with `ready`; all other relevant unresolved writers remain blockers. New conflicting reservations invalidate affected readiness in their transaction. Check ownership when replacing/retiring tasks and during D4 updates. Preserve D5 as the only completion verifier; D7 remains responsible for repository merge enforcement.

**Proof:** crash before/after spawn, duplicate observation, wrong identity, interrupted worker with partial edits, surviving descendants, uncertain release, stale candidate, reviewer mutation and policy changes. Race a reservation against verification; neither side may ignore intervening work. Verify bounded retry/review accounting and no unauthorized commit or route substitution.

## 4. Preserve state and enrollment upgrade safety

**Owner: runtime worker.** Update schema initialization/validation in `runtime/state.py`, nested runtime configuration in `runtime/startup.py`, and the synthetic runtime settings in `runtime/evidence.py::_read_host_proof()`. Top-level enrollment, D3 plan and D4 manifest/journal schemas stay at version 1; nested runtime configuration and SQLite advance to version 2.

Use D5's fresh-state transition, not an in-place database migration: stop and reconcile affected writers with their supported old pinned runtime, retire old tasks safely, then use an authorized D4 enrollment update to select a fresh approved shared schema-2 state directory. Preserve old databases, artifacts, pins and history. New tasks repeat proof; no success evidence or active task is silently repinned.

D4's `runtime/changes.py` currently inspects proposed, actual and backed-up enrollment through the current schema. Add narrowly scoped, read-only schema-1 inspection for `_writers()`/`_guard_writers()` during transition and recovery. Validate private database identity, structure, stored tasks/pins and stopped lifecycle; no legacy writes or broad migration framework. Missing old-runtime reconciliation or unreadable state blocks the affected update. Never replace fresh state inspection with an unbound assertion that writers stopped.

Rollback preserves prior enrollment/configuration as recovery material; it does not make schema-1 state runnable under schema 2. Re-enabling the prior enrollment requires a matching qualified runtime/policy and safe writer reconciliation. New unresolved assignments also prevent an unsafe rollback or authority change.

**Proof:** schema-1 to fresh schema-2 transition, interrupted D4 apply/resume, rollback refusal with active/uncertain workers, retained historical pins/artifacts, incompatible clients, old-state mutation and unrelated enrollment preservation. No live enrollment changes are part of implementation tests.

## 5. Guidance, independent review and qualification

**Owner: guidance worker.** Add selectively loaded `clients/delegation.md`; link it from `clients/runtime.md` only when preparing, observing or recovering delegated work. Update validator coverage, affected guidance and the [source map](policy-sources.md). No new skill is needed. Keep runtime loading free of onboarding procedures and Toolkit sources.

Exercise instruction paths for direct execution, a bounded worker, parallel disjoint work, conflicting/unknown ownership, independent review, unsupported controls, interruption and exhausted budgets. Check every applicable contract requirement and confirm unrelated material stays unloaded. Runtime code owns deterministic checks; instructions own judgment and verified authority, without claiming stronger enforcement.

### Dispatch and review order

Before wave 1, the coordinator records the observation/assignment/guidance field contracts in the task briefs. A and B may work against those agreed interfaces, never another worker's unfinished output; unresolved dependencies serialize the affected work. Each assignment includes its tests and self-review. Apply [test-first discipline](../policies/03-agent-delegation.md#select-capability-and-dispatch): new behavior and bug fixes need an observed failing test before implementation, then passing proof. Missing required proof blocks acceptance. Choose worker model/effort at dispatch; retain the user's coordinator settings.

| Task / wave / owner | Writable files | Depends on | Mutable resources and proof |
| --- | --- | --- | --- |
| A / 1 / adapter | `runtime/adapters/codex.py`, `runtime/doctor.py`, `tests/test_native_reviews.py`, `tests/test_doctor.py` | Agreed field contracts | Unique temporary protocol fixtures, logs and child processes; discovery, correlation, settings and preserved D5 review behavior. |
| B / 1 / runtime | New `runtime/delegation.py`, new `tests/test_delegation.py`; `runtime/state.py`, `runtime/startup.py`, `runtime/evidence.py`, `runtime/changes.py`, `scripts/workflow.py`; `tests/test_state.py`, `tests/test_runtime.py`, `tests/test_evidence.py`, `tests/test_changes.py`, `tests/test_onboarding.py`, `tests/test_startup.py` | Agreed field contracts | Unique temporary Git repositories, private state/cache, locks and race-test processes; slices 1–4 cache, ownership, readiness, recovery and schema-transition proof. |
| C / 2 / guidance | New `clients/delegation.md`; `clients/runtime.md`, `clients/evidence.md`, `docs/policy-sources.md`, `scripts/validate.py`, `tests/test_hook_manifest.py`, `tests/test_startup.py` | A and B reviewed and accepted | Unique temporary package copies; instruction cases, examples, source coverage and package checks. `tests/test_startup.py` transfers from B only after wave 1 closes. |
| D / 3 / qualification | New `docs/d6-validation.md`; private qualification artifacts outside the repository | C reviewed and accepted | Full unit suite; separate disposable CLI/Desktop projects, private state and native workers; lifecycle, selection, review and recovery observations. |

All task fixtures use isolated Git configuration and no production services or fixed shared ports. Reserve exact temporary roots and child-process ownership in each dispatch brief; new files/resources require a brief update before use. `runtime_fingerprint()` reads every runtime module and `scripts/workflow.py`, so temporary databases alone do not isolate checks. In this shared checkout, pause all package writers for red/green checks and reviews; disjoint edits may otherwise proceed together. Run checks concurrently only when their fixtures and processes are independent. Do not change live enrollment during unit tests; reserve actual native probes for D.

For each wave: wait for writers, freeze each task's exact diff/snapshot, verify checks, then obtain independent read-only task review before starting the next wave. Review concurrency, provenance and security where affected; authors cannot provide their own independent verdict. Resolve blocking findings and recheck affected proof before releasing dependencies. Preserve requested review-round limits, serialize any authorized commits with current HEAD per task, and write one coordinator progress entry. Final integration review checks the combined result without replacing wave reviews or repeating unaffected coverage. If qualification exposes a defect, return it to the owning task and review the affected change before rerunning qualification.

Run focused adapter/delegation/state/evidence/onboarding tests, the complete unit suite, `python3 -B scripts/validate.py` and `git diff --check`. Record a disposable native coordinator/worker/reviewer lifecycle, including cached guidance, supported worker model/effort selection, reservation before launch, verified integration and recovery. Qualify CLI and Desktop separately, verify unchanged coordinator settings and record exposed worker settings. Package checks and simulated races do not establish native behavior.

**Completion:** the qualified cooperative native path selects authorized workers, excludes conflicting managed assignments, retains uncertain ownership and accepts only independently checked results. Automatic takeover and enforced containment remain deferred. Claude lifecycle qualification and D7 repository enforcement retain their separate requirements.

**Parallel delivery:** [D7's ownership plan](d7-repository-gate-plan.md#4-parallel-delivery-with-d6) permits independent verifier work after agreeing evidence fields. D6 retains its shared runtime/state/CLI and guidance files until reviewed handoff; pause all package writers for shared checks. Select implementation and independent review workers through the [delegation contract](../policies/03-agent-delegation.md#select-capability-and-dispatch), using applicable cached platform guidance, task risk and available controls. No model or reasoning tier is mandatory for every review. Preserve coordinator settings and existing sessions.

**Downstream evidence:** [D7](d7-repository-gate-plan.md) owns real repository merge assurance. [D9a/D9b](onboard-my-project-plan.md#d9-qualification-usage-and-pilot) reuse D6 identities and worker-control observations for behavioral qualification and native usage reconciliation. Dispatch budgets and lifecycle receipts do not establish measured consumption; usage collection is D9b's bounded deliverable, not a second D6 ledger.
