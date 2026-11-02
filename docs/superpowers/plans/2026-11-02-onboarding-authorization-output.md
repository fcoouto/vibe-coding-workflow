# Onboarding authorization and readable configuration implementation plan

> **For agentic workers:** Use `superpowers:executing-plans` for the implementation and an independent final review. Steps use checkbox notation for actual completion.

**Goal:** Carry an authorized full onboarding request through routine setup and qualified activation without repeated consent, and explain the reviewed configuration in plain language.

**Architecture:** Keep authorization semantics in the onboarding policy. Route the skill and its existing inspect/apply procedures to that policy and one conditionally loaded presentation reference. Reuse main's file transactions and configured ordinary-entry behavior; do not create another approval record or replace runtime admission.

**Tech stack:** Markdown instructions; existing Python package validator and transaction/entry tests.

**Spec:** [Onboarding simplification design](../specs/2026-11-02-onboarding-simplification-design.md).

## Global constraints

- Base: reviewed main `a0f1767e36d3433df5b24154eaa34bf3dd8c398f`; isolated branch `codex/onboarding-flow`.
- Preserve the primary checkout, its branch features, unstaged edits and retained pilot history.
- Keep skill entry points at or below 150 words and each rule with one owner.
- Full onboarding authority covers only its actual agreed effects. Inspect, plan and configuration-only requests retain their limits.
- Keep exact frozen operation bindings, mandatory checks, source matching, recovery and later user edits intact.
- File-only configuration and undo require neither runtime birth nor native qualification.
- No installation, pilot activation, new service, registry, permission bypass or optional integration.
- This plan owns the independently implementable instruction/output slice. Completing it does not complete the wider runtime design or authorize an unqualified merge of that wider claim.

## Review focus

- A narrow planning request must not be interpreted as full onboarding authority.
- A full request must not trigger another confirmation solely because an internal transaction or stage changes.
- An additional cost, external scope or permission must remain a real decision when existing authority does not cover it.
- A configured-only or unknown native state must not be reported as active or complete.
- Human-readable output must preserve exact change locations, unresolved requirements, recovery limits and links to concrete technical records.

### Task 1: Establish the current baseline

**Files:** existing startup tests and package validator; no source edits.

- [x] Inspect current entry, transaction and instruction contracts and request the shared implementation boundary from Genesis.
- [x] Create an isolated worktree from reviewed main, preserving primary local changes.
- [x] Run `python3 -B -m unittest tests.test_unenrolled_checkout`; expect all existing configured/suspended/membership cases to pass.
- [x] Run `python3 -B scripts/validate.py`; package validation passes separately from native execution.

### Task 2: Implement the instruction and output contract

**Modify:** `policies/10-project-onboarding.md`, `skills/onboard-my-project/SKILL.md`, `skills/onboard-my-project/references/procedure.md`, `skills/onboard-my-project/references/apply-and-recovery.md`, `docs/policy-sources.md`.

**Create:** `skills/onboard-my-project/references/reviewed-configuration.md`.

**Consumes:** Actual user/session authority, the existing complete scoped proposal and current operation/evidence results.

**Produces:** The agent-written Reviewed Configuration document, with human-readable scope, changed paths and purpose, current status, next action, material decisions, recovery and technical record links. It is a presentation artifact, never authority.

- [x] Define full-request and limited-request authority once in onboarding policy. Require questions only for unresolved material exceptions.
- [x] Remove procedural wording that invents a separate conversational approval for every stage, while preserving independent verification of each exact operation.
- [x] Add the conditional presentation reference and route to it when presenting a reviewed configuration. Keep internal codes and hashes in technical records, with no new runtime schema.
- [x] Preserve configured-versus-active reporting and explicit missing qualification. Do not claim this instruction change supplies a production qualification reader.
- [x] Record user-authorized policy provenance and source-to-contract coverage.
- [x] Run package validation and local reference/anchor checks; expect valid links and all entry points within 150 words.

### Task 3: Independent behavioral qualification and review

**Read-only input:** Exact candidate diff, relevant policy/skill references and credential-free scenario facts. Reports remain in task-owned private storage.

- [x] Have a fresh native evaluator follow the candidate skill for five cases: full onboarding with passed checks, plan-only, configuration-only, a new paid/external effect, and missing native qualification with interrupted recovery.
- [x] Evaluate selected loads, next actions, authority boundaries and generated Reviewed Configuration. The first case must continue covered effects without another confirmation; narrow scopes and material exceptions must stop only dependent work; missing qualification must remain incomplete.
- [x] Give the evaluator the requests and raw facts, not the expected decisions. No real enrollment, external sends, provider calls or pilot changes.
- [x] Independently review the frozen diff for requirements, authorization/security consequences and preserved recovery. Fix supported blocking findings and rerun affected checks.
- [x] Record actual model/effort observations and limits. A fresh native evaluator proves only the observed instruction cases, not production hook activation.

### Task 4: Integrate the qualified instruction changes

- [ ] Merge the independently qualified instruction/output candidate under the user's existing authorization. Keep the broader runtime design explicitly undelivered.

### Dependent runtime work: unresolved interface

- [ ] Obtain the agreed owner-issued qualification/current-observation interface and prior-active history source through Genesis coordination before touching shared runtime files.
- [ ] Write the concrete dependent runtime plan against those interfaces. Do not infer qualification from JSON, stored flags or a fixture callback, or introduce a signer/registry to fill an unknown contract.
- [ ] Prove the full design's runtime acceptance cases and applicable native observations in an authorized disposable scope. Preserve existing budgets and the reverted pilot.
- [ ] Review and qualify the runtime candidate before a separate merge; preserve unrelated branch work.

## Execution ledger

- User authorized implementation, review, qualification and merge on 2 November 2026. That instruction supersedes an additional routine plan-approval round.
- Coordinator model/effort remains unchanged and is not independently exposed. Recommendation: GPT-6.1 Sol High for implementation, GPT-6 Astra High for final review; current official guidance was checked. No API route or global model setting changed.
- Original baseline selector `tests.test_startup.CanonicalScopeTests` does not exist on main; corrected to the existing `tests.test_unenrolled_checkout` suite. This was a selection error, not a runtime failure.
- Shared runtime ownership/interface confirmation is pending. Independent instruction work may proceed; no activation proof is fabricated.

- Baseline: seven existing ordinary-entry tests passed in 2.097 s. Package validation passed; onboarding entry is 127 words.
- Independent instruction exercise completed all five cases; general/security review found no blocking instruction findings. All six reviewed hashes matched. No production runtime source changed.
- Genesis confirms this chat owns the proposed shared reader/classification/activation slice, but no production host issuer/read implementation exists. Core evidence/state/retention remains separately owned; the existing native campaign budget is not reused for a new lifecycle campaign.

- Ruling: integrate the independently qualified instruction/output slice separately while retaining the wider runtime work as unresolved. Its missing production observation/history contracts cannot be supplied by wording, fixture callbacks or invented authority. This delivers the approved simplification without claiming full activation delivery.
- Reviewer dispatch requested `gpt-6-astra` with `high` effort; the worker could not independently observe actual execution settings. Instruction evaluator inherited the coordinator settings; exact model/effort is unobserved.
- Evidence and remaining limits: [qualification record](../../onboarding-authorization-qualification.md).

- Final instruction candidate: 24 focused tests passed in 30.533 seconds; package validation, 100 links/anchors and unchanged six-file review hashes passed. Records-only review found no misleading completion claim.
