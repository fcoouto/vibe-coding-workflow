# Council Runtime Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a pilot that recovers failing Council seats independently and concurrently, using bounded support research, justified fixes and eligible replacement models.

**Architecture:** Extend the existing locked Council state and worker executor. Native seat supervisors use existing subagent/research tools; Python validates attempts, immutable evidence, candidate claims and cumulative budgets. Keep all interdependent lifecycle changes in one implementation task to avoid competing edits to shared state.

**Tech Stack:** Existing Python standard library, unittest, native Codex subagents and research tools; pinned OpenCode/OpenRouter integration.

**Spec:** `docs/superpowers/specs/2026-10-30-council-runtime-recovery-design.md`

## Global Constraints

- One bounded investigation, at most two distinct justified workaround attempts per candidate tenure; at most three replacements per seat across the session.
- Investigation lasts at most 120 seconds, excluding workaround/fix application; all work consumes original phase/session deadlines. At most three searches and five page reads per investigation.
- Preserve default 1200 seconds total and 600/360/240 cumulative phase reserves, existing account limits, privacy, maximum reasoning rules and group topology.
- Preserve original attempts and versions 1/2. New recovery-enabled manifests use a distinct version; counters survive restart and phase changes.
- Free has external participants/chair; native supervisors only coordinate. Providers remain pinned per candidate. Every replacement must meet current selection and transmission requirements.
- Parallel supervisors own disjoint seat state. Atomic shared claims prevent duplicate canonical models. All prior owners must be stopped before phase advancement.
- No dependency, service, arbitrary configuration patch, client upgrade, release archive, paid qualification or comparative evaluation.
- User approved both planning and immediate pilot execution; do not stop for another plan approval.

## Review Focus

- Lost launch responses and supervisor restart must not duplicate inference or reset counters.
- Concurrent replacement claims must preserve distinct participants and release locks during work.
- Critic replacement must not count reports based on different evidence generations together.
- Malicious support text, raw errors and remembered fixes must not grant permissions or expose secrets.
- Deadline exhaustion and cancellation must stop new work while retaining exact owners and unknown costs.

---

### Task 1: Integrated recovery pilot

**Files:**
- Modify: `runtime/council.py`, `scripts/council.py`, `scripts/openrouter_workers.py`.
- Create if needed: `runtime/council_recovery.py` for bounded recovery state helpers, avoiding a generic framework.
- Modify if compatible reuse needs it: `scripts/openrouter_proposals.py` for private operational history.
- Modify: `skills/council/references/procedure.md`, `clients/codex-council.md`, `docs/policy-sources.md`, `docs/council-validation.md`.
- Test: `tests/test_council_flow.py`, `tests/test_openrouter_workers.py`, `tests/council_fixtures.py`; add `tests/test_council_recovery.py` for recovery-specific scenarios.

**Interfaces:**
- Consumes existing `prepare`, `packet`, `verify_external`, `record_native`, `status`, `cancel`, worker preparation/execution and sealed snapshots.
- Produces documented validated Council recovery CLI actions to open/record investigation, issue a supported correction, replace a candidate and publish a coherent critique generation. Keep action names identical in runtime, CLI, instructions and tests. Exact field layouts belong to implementation, with no opaque arbitrary configuration payload.
- Status exposes candidate/attempt lineage, remaining investigation/fix/replacement allowances, current role bindings, coherent accepted coverage, all-owner stop requests and accounting across every attempt.

- [x] **Step 1: Establish red proof.** Add behavioral tests for one investigation capped at 120 seconds with application excluded, two distinct corrections, three replacements, fourth denied, restart/phase persistence, unsupported workaround rejection, no-workaround immediate replacement, claims collision and concurrent seat progress. Observe intended failures before production changes.
- [x] **Step 2: Implement guarded recovery state.** Extend existing admission/launch guards with immutable candidate/attempt identities and versioned state. Validate replacement eligibility and constrained corrections. Retain every owner, session and cost; never infer acceptance from a supervisor assertion. Add safe transport classification without publishing raw error text. Ensure interim/final response distinction and consistent copied-marker tool boundary where feasible inside the existing qualified profile; qualification changes must be disclosed and locally proven.
- [x] **Step 3: Implement phase integration.** Preserve accepted independent investigations; critic replacement performs fresh independent catch-up and creates a new immutable critique generation, superseding dependent critiques. Allow fresh synthesis-only chair replacement using original chair allowance and correct group. Preserve versions 1/2 and prior-phase stop barriers.
- [x] **Step 4: Prove lifecycle cases.** Add failure-before/after-spawn, lost response, stale diagnosis/history, malicious workaround, cancellation, exhausted reserve, replaced-native receipt, canonical alias collision, rejected/reused sessions, superseded-generation accounting and unknown billing tests. Run affected tests and fix only changes caused by this task.
- [x] **Step 5: Connect native parallel supervision.** Update the procedure and Codex adapter with isolated per-seat subagent briefs, research budget, supported recovery action flow, main-coordinator acceptance, capacity reservation, actual progress, cleanup and source-backed local learning. Use skill-creator guidance. Keep entry point below 150 words and authoring provenance outside runtime loading paths.
- [x] **Step 6: Exercise pilot locally.** Use isolated synthetic clients to demonstrate a failed candidate, documented correction, replacement, unaffected concurrent seat success, coherent critique and fresh synthesis. Do not claim real endpoint success from fixtures. Run `python3 -B scripts/validate.py`, affected unittest modules and `git diff --check`. Record package validation separately from observed client execution.
- [x] **Step 7: Self-review and report.** Write the exact red/green commands, results, changed interfaces, limitations and any spec rulings to the private task report. Coordinator commits the implementation and sends a frozen diff to independent review.

### Task 2: Independent review and completion

**Files:** Same implementation files only when a confirmed finding needs a fix; private review evidence and this plan's checkboxes.

**Interfaces:** Consumes Task 1's frozen base/candidate diff, report and approved spec. Produces independent spec/quality verdict and final integrated review.

- [x] **Step 1:** Review Task 1 for spec compliance and quality, focusing on the five failure classes above. Do not rerun already passing tests without a specific evidence gap.
- [x] **Step 2:** Resolve confirmed findings through a scoped fix and focused regression proof; record rulings and independently re-review changed behavior.
- [x] **Step 3:** Obtain one final broad review of the pilot. Report runtime support, actual local proof and remaining live uncertainty. Leave comparative evaluation deferred.

## Self-review

All design sections map to Task 1: counters/diagnosis, selection and phases, ownership/accounting, concurrent supervisors and private learning, compatibility and proof. Task 2 supplies independent review. State and permission changes are deliberately serialized in one implementation task; seat concurrency is product behavior, tested with disjoint workers. The 120-second user correction supersedes the draft's 60 seconds and never includes fix application. No second approval gate is introduced.
