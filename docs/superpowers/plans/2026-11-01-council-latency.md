# Council Latency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove avoidable Council coordination delays and make native packet forwarding deterministic.

**Architecture:** Extend existing native packets and private timing records. Keep the three-phase runtime and supported host dispatch; no scheduler or transport change.

**Tech Stack:** Python standard library, unittest, existing Codex native controls.

**Spec:** [Approved design](../specs/2026-11-01-council-latency-design.md).

## Global Constraints

- Maximum supported reasoning remains required; tokens remain advisory.
- Preserve 1200 seconds and cumulative 600/360/240 phase allowances.
- Free stays disabled; use the plugin integration branch as merge destination.
- Preserve immutable evidence, fresh native contexts, ownership and technical-only verification.
- No streaming, new service, automatic acceptance or new dependency.

## Review Focus

- Unicode, multiline and contradictory peer reports survive prompt assembly unchanged.
- Synthesis observations are included once; storage/auth/selection identities remain outside prompts.
- Repository packets retain independent inspection and do not acquire a text-only shortcut.
- Timing records never replenish budgets or imply upstream completion/cancellation.
- A terminal response can still be rejected technically; timeout accounting remains nullable.

### Task 1: Native packets, timing and operational guidance

**Files:**
- Modify: `runtime/council.py`, `scripts/openrouter_workers.py`.
- Test: `tests/test_council_direct.py`, `tests/test_council_flow.py`.
- Modify: `clients/codex-council.md`, `skills/llm-council/references/procedure.md`, `skills/llm-council/references/protocol.md`.
- Record coverage: `docs/policy-sources.md`, `docs/council-validation.md`.

**Interfaces:**
- Consumes: existing `council.packet`, sealed snapshot manifests, native receipts and worker progress.
- Produces: text-native `prompt` and `prompt_sha256`; status `timings` with runtime-observed `issued_at`/`verified_at`; local transport response progress.

- [ ] Write failing tests for exact evidence/report/observation forwarding, digest, settings, repository exclusion and timing boundaries.
- [ ] Run focused unittest cases and observe the missing fields/events fail.
- [ ] Assemble the complete native text prompt before publishing its issued marker; verify source snapshots and preserve existing identity/deadline guards.
- [ ] Record issuance/verification in existing member records and local response arrival in existing worker progress; expose current member timing without changing admission.
- [ ] Update operational contracts for prompt forwarding, capacity-aware parallel dispatch, completion waits, prompt settlement and post-session bookkeeping.
- [ ] Run Council regressions, package validation and skill validation; conduct representative text/repository/timeout instruction walks.
- [ ] Obtain an independent whole-change review and resolve blocking findings with focused proof.
- [ ] Run one isolated paid Frontier validation on the same frozen question, with Free disabled and original reasoning/deadline controls. Record exact participation, measured overhead and unknown costs honestly.
- [ ] Commit the reviewed changes and merge into `codex/project-repository-adjustments`, preserving unrelated local edits. Recheck merged invariants and package validation. Do not push or publish an archive.
