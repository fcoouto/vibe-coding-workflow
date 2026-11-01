# Council Cost Discovery Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for the focused instruction update and independent review.

**Goal:** Discover task-relevant capability and cost evidence for Council using its existing metadata cache.

**Architecture:** Extend Council selection instructions, retaining the existing cache schema, refresh ownership and per-seat selection notes. No new runtime service, scoring algorithm or Delegation integration.

**Tech Stack:** Markdown contracts and existing Python cache/package validators.

**Spec:** The user's approved Council-first design: reuse the existing cache, keep the change simple, and leave Delegation unchanged. Shared discovery was considered and rejected because the workflows have different candidate pools, cost models and reasoning policies.

## Global Constraints

Keep maximum reasoning, advisory token targets, privacy, eligibility, vendor diversity and original session bounds. Free stays disabled; comparative evaluation stays deferred. No paid inference or installed configuration changes.

## Review Focus

- Fresh but incomplete cache: no forced refresh or invented coverage.
- Missing provider/effort: no assumed equivalence with pinned maximum-reasoning execution.
- Life versus Python questions: relevant evidence, no universal benchmark ranking.
- Unknown usage or replacement catch-up: distinguish observed rates from estimated remaining cost.
- Delegation, Frontier and Free: preserve their existing behavior.

## Task 1: Council discovery guidance

**Files:** Modify `skills/llm-council/references/selection.md`, `docs/policy-sources.md` and `docs/council-validation.md`.

**Interfaces:** Existing `models`, `endpoints`, `benchmarks`, `task_usage`, `coverage` snapshot and per-seat `selection` text; no schema changes.

- [x] Add bounded task-relevant benchmark queries, comparable run metadata, exact-route pricing and explicit unknowns to selection. Permit one original-source page lookup per roster or replacement selection within existing bounds; no forced refresh or model probes.
- [x] Clarify that replacement estimates cover remaining work and required catch-up.
- [x] Check representative life/Python, missing metadata, cache ownership and replacement scenarios independently. Record results and update source coverage.
- [x] Run package validation, skill validation, existing cache tests and whitespace checks; report instruction/package proof separately from live execution.
- [x] Commit the focused change without merging or pushing.
