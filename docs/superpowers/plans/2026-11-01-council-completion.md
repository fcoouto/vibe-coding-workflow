# Council Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Complete every Council phase through bounded recovery with reliable native delivery.

**Architecture:** Reuse the manifest, immutable input publisher, and existing recovery controls. New manifests use per-request deadlines and full-panel phase barriers; historical manifests retain their original semantics.

**Tech Stack:** Python standard library, unittest, Markdown runtime contracts.

**Spec:** `docs/superpowers/specs/2026-11-01-council-completion-design.md`

## Global Constraints

- Maximum reasoning and advisory token targets remain intact.
- No phase or session time cap; each request defaults to 1200 seconds.
- No new dependencies, paid inference, request deadline renewal, merge, or push.
- Free is text-only with zero-cost routing; Balanced remains recommended.

## Review Focus

- A native packet changes after dispatch: reject acceptance but permit stop settlement.
- A phase target expires: continue; preserve each issued request deadline.
- One participant fails: preserve successful reports and recover before advancing.
- A critique replacement changes reports: require one coherent completed generation.
- A historical session is inspected: preserve its recorded deadlines and evidence.

### Task 1: Runtime and regression coverage

**Files:** `runtime/council.py`, `runtime/council_recovery.py`, `tests/test_council_flow.py`, `tests/test_council_recovery.py`, `tests/test_council_direct.py`.

**Interfaces:** `prepare` marks new scheduling/completion contracts; attempt deadline helpers preserve each issued timeout; `packet` returns a short prompt and immutable packet path/hash; `record_native` checks integrity; `_phase` requires the full preceding panel. Existing recovery actions retain identity and bounds.

- [x] Add failing tests for short packet delivery, tampering, request timeouts, phase barriers, and recovered full completion.
- [x] Implement through existing helpers and preserve historical manifest behavior.
- [x] Run `python3 -B -m unittest tests.test_council_flow tests.test_council_recovery tests.test_council_direct tests.test_council_snapshot` and resolve regressions.

### Task 2: Runtime instructions and verification

**Files:** `clients/codex-council.md`, `skills/llm-council/references/{procedure,protocol,recovery}.md`, `docs/policy-sources.md`, `docs/council-validation.md`.

**Interfaces:** Instructions consume the generated packet and existing recovery commands. The user receives the completed decision support, recovery progress, or a concise final blocker only when necessary.

- [x] Update affected contracts without duplicating rules or changing unrelated selection behavior.
- [x] Check representative activation, packet-read, recoverable-failure, exhausted-recovery, and normal completion paths.
- [x] Run `python3 -B scripts/validate.py` and review the final diff independently.
- [x] Report package results separately from observed client execution; no paid live qualification claimed.
