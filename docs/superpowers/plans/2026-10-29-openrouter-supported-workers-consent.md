# Supported OpenRouter Workers: Consent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved editing/testing enablement contract without
silently widening historical read-only consent.

**Architecture:** Extend the existing private settings owner and CLI. Version 2
means the single supported worker capability, worktree editing and registered
checks. Enabling workers explicitly acknowledges this version; status remains
offline/read-only and both executors keep their shared admission guard.

**Tech Stack:** Python 3.11+ standard library and existing private/CAS authority
primitives; unittest disposable enrollment fixtures.

**Spec:** [Supported OpenRouter coding workers](../specs/2026-10-29-openrouter-supported-workers-design.md).

## Global Constraints

- The human approved the design and implementation on 29 October 2026. Execute
  inline without another design, plan or execution-method approval pause.
- Root owns all Git integration, shared policies/docs and native runtime seams.
  No root-tree edits, competing task ledger or inferred worktree enrollment.
- Preserve native defaults, selected model/reasoning/authentication, private
  bindings, revisions, route references and independently verified results.
- Keep a single worker execution mode, with no selector in management.
- OpenRouter manages monetary limits. No keys, account requests, installation,
  live activation or inference; combined live E2E waits for Langfuse.
- This is the independently testable consent slice of the approved delivery.
  Worktree execution/checks and full-path qualification follow agreed Genesis
  interfaces; finishing this slice alone does not qualify coding dispatch.

## Review Focus

- Historical `enabled:true` records must not gain editing rights from a software
  update, omitted request field or replayed preparation.
- A consent renewal is a real revision change even when saved opt-in was already
  true; it invalidates old preparation without erasing history.
- Boolean/string acknowledgements must not pass as integer version 2.
- Proposal-only consent and historical settlement remain independently usable.
- Status, missing-scope and rejected mutation paths must not write or bootstrap
  runtime state, expose credentials or hide ownership changes.

---

### Task 1: Versioned consent and guarded admission

**Files:** Modify `runtime/openrouter_settings.py`, `tests/test_openrouter_settings.py`,
`tests/openrouter_fixtures.py`; the CLI `scripts/openrouter.py` retains its interface.

**Interfaces:** Existing `status/configure/enable/disable(cwd, request)` and
`admission(cwd, route, ...)` remain the public functions. Stored records accept
versions 1 and 2 with their existing exact fields. Configuration remains disabled and unacknowledged until explicit worker enable
records version 2. Initial worker enable/legacy renewal requires `consent_version: 2` alongside
`expected_revision`; subsequently authorized enable and proposal-only enable keep
their existing request contract.
Status adds `consent_version`, `worker_capability` and
`enablement_renewal_required`; capability is `worktree_edit_and_test`,
`renewal_required` or `not_applicable`. Worker admission requires version 2.

- [x] Run the current settings tests to establish the passing baseline.
- [x] Add `test_legacy_worker_consent_is_readable_but_cannot_admit`: create a
  private version-1 enabled record, assert read-only status reports renewal,
  reject worker admission and preserve all bytes.
- [x] Add `test_enable_explicitly_renews_legacy_consent_once`: require exact
  integer 2; a successful renewal changes version and revision, retains paths
  and history, and rejects stale prepared revision. Duplicate current-version
  enable is idempotent only under the current revision.
- [x] Add tests for a new worker enable without acknowledgement, invalid values
  `true`, `"2"`, `1`, unknown operation/fields, proposal-only enable, and disable
  after renewal. Failed mutations retain the saved bytes.
- [x] Observe the expected RED before changing implementation. Update existing
  settings tests and the worker fixture helper to explicitly acknowledge the
  new capability; do not weaken earlier assertions.
- [x] Extend exact version validation and local report fields. Validate request
  fields by operation. Apply acknowledged version changes before the old
  idempotent-enabled shortcut; retain the same private CAS/atomic path.
- [x] Gate new worker admission on renewed consent, without gating historical
  record/verify operations or proposal-only actions.
- [x] Run `python3 -B -m unittest tests.test_openrouter_settings` to GREEN.
  Exercise the isolated CLI enable/status path with version acknowledgement.

### Task 2: Management instructions and slice verification

**Files:** Modify `skills/manage-openrouter/SKILL.md` and
`skills/manage-openrouter/references/procedure.md`; source-to-contract/shared
guidance changes remain owned-hunk proposals to Genesis.

**Interfaces:** Manage OpenRouter Integration states that enabling workers permits
scoped worktree edits and registered checks. It sends the explicit version-2
acknowledgement; it offers no execution-mode choice. A legacy record reports a
renewal prerequisite. Preserve the separate onboarding offer and offline status.

- [x] Update the entry point within 150 words and define the consent procedure
  once in its local reference, using OpenAI skill-creator guidance.
- [x] Walk through fresh enable, legacy renewal, rejected stale requests,
  proposal-only status and post-disable settlement; load only relevant procedures.
- [ ] Run affected settings/proposal/worker tests on the agreed implementation
  base, `python3 -B scripts/validate.py`, skill validation and whitespace checks.
  Separate package/helper proof from observed client execution.
- [ ] Freeze exact owned-file pre/post hashes, RED/GREEN logs and shared hunk
  proposals. Send Genesis for its independent Astra review and serialized commit;
  independently compare the integrated bytes. Do not commit or publish from this
  worker, and continue the remaining approved delivery afterward.
