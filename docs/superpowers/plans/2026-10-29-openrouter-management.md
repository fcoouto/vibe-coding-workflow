# OpenRouter Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add saved, scoped OpenRouter enablement/status/disable controls and enforce
them in both existing executors without coupling activation to onboarding.

**Architecture:** A dedicated settings owner consumes public checkout enrollment and
the existing private runtime authority. Shared local admission guards serialize
disable against proposal admission and worker launch. One management skill exposes
the controls; existing executors continue owning discovery, work and verification.

**Tech Stack:** Python 3.11+ standard library, existing runtime scope/private/atomic
primitives, POSIX locks, current OpenCode pilot and unittest fixtures.

**Spec:** [Management design](../specs/2026-10-29-openrouter-management-design.md).

## Global Constraints

- Start from primary `83b1c16`; reuse the existing isolated managed worktree.
- Keep native execution default, settings initially off, and scope checkout-only.
- Use existing accepted runtime authority; never bootstrap native state or membership.
- No credentials, account queries, inference, money caps, installer, outer retry,
  telemetry producer or global native model/provider changes.
- Preserve the accepted retry/recovery behavior and all prior executor boundaries.
- Status must be read-only and offline. Disable blocks new admissions; prepared
  workers need a fresh launch check, while already-admitted work may settle.
- Keep skill entry points within 150 words and load procedures selectively.
- Core and Observability files are reserved. Root serializes all onboarding,
  README, source-map and canonical-plan edits from exact-base private proposals.
- Implement the user's selected behavior inline without another approval pause.

## Review Focus

- A cached model list, raw approval string, alternate store or different executable
  must not authorize external dispatch after disable.
- Disable after preparation must prevent worker launch; in-flight completion and
  accounting must not require re-enabling.
- Status must not create storage, access key contents, execute clients or contact services.
- Clones, replaced files/directories, stale revisions and mismatched authority must
  fail safely without overwriting another user's settings or fabricating off state.
- Onboarding's optional offer must never become activation, a prerequisite or an
  unrelated provider/setup load.

### Task 1: Saved controls and private authority

**Files:** New `runtime/openrouter_settings.py`, `scripts/openrouter.py`,
`tests/test_openrouter_settings.py`; reuse existing runtime primitives read-only.

**Interfaces:** `status(cwd)`, `configure(cwd, request)`, `enable(cwd, request)`,
`disable(cwd, request)` and guarded admission/configuration lookup for executors.
Configure selects `routes` and nonsecret `opencode`/`auth_data` references; mutations
require `expected_revision`. Return control scope, revision, desired enablement,
selected routes, derived private work paths and explicit connection unknowns.

- [x] Write failing tests for default off, persistence/CAS, private files, authority
  changes, no native-state mutation, offline status and valid/invalid references.
- [x] Observe RED, implement the smallest owner and CLI, then run these tests to GREEN.

### Task 2: Executor admission and disable races

**Files:** Both `scripts/openrouter_*.py`, both existing executor test files;
new managed-dispatch integration tests and small disposable enrollment fixtures.

**Interfaces:** Proposal `begin` admits once under current saved consent and binds
the revision/scope. Worker preparation validates managed references; launch takes
fresh guarded admission. Other actions remain usable for recording/verification
after disable. Existing script invocation paths remain installed-package relative.

- [x] Add tests showing disabled proposals issue no token, alternate paths cannot
  bypass consent, and a prepared worker cannot launch after disable.
- [x] Observe RED, add both gates without changing their retry/resource semantics.
- [x] Verify enabled admission, disable-during-run settlement, post-disable native
  verification, revision races and isolation between enrolled checkouts.
- [x] Run all affected settings and executor tests, retaining earlier coverage.

### Task 3: Skill, instruction paths and qualification

**Files:** New `skills/manage-openrouter/SKILL.md`, `references/procedure.md`,
`agents/openai.yaml`; both executor entry points/procedures. Shared onboarding,
README, source-map/canonical-plan changes remain private owned-hunk proposals.

- [x] Create a concise, discoverable management skill with complete local controls,
  authority/prerequisite behavior, admission semantics and honest readiness reporting.
- [x] Update executor contracts to consume saved consent without loading management
  during ordinary tasks or treating direct MCP access as disabled.
- [x] Prepare root's shared-file proposals, including only a post-success onboarding offer.
- [x] Run focused tests, package/skill validation, whitespace and representative
  instruction walkthroughs. Use isolated local client qualification if appropriate.
- [ ] Obtain fresh Astra/high phase/security review and resolve material findings
  with focused RED/GREEN evidence.
- [ ] Freeze source, shared proposals, native reviewer provenance and proof; coordinate
  serialized primary integration with Genesis and independently verify the result.
