# Instruction Scope Routing Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans. Root implements this cohesive slice; a fresh independent reviewer checks it before native qualification and benchmarking.

**Goal:** Route explicit mixed instruction selections safely through the existing runner and remove the observed ad hoc recovery detour.

**Architecture:** Python determines per-source authority inside the existing read. One automatic selection revision binds all ordered sources; the existing JavaScript runner drains it with fixed child budgets and separate notifications.

**Tech Stack:** Python standard library, packaged native JavaScript and existing Python/Node tests.

**Spec:** `docs/superpowers/specs/2026-11-03-instruction-scope-routing-design.md`

## Global Constraints

Preserve all source/path/hash/target and delivery checks, 8,000/9,500/24,000-byte bounds, explicit legacy modes and exceptional native recovery. No separate resolver, cache, raw recovery API, dependency or hook. RTK, other plugins, model, reasoning and authentication stay unchanged. One paired benchmark; no automatic retries or merge/live installation.

## Review Focus

Automatic routing must never reclassify a package escape as external or replace a known alias's prepared key. Revisions must reject target/authority/mode changes even with identical bytes. Invalid later sources must fail before stdout. Mixed clipping recovery must retain ordered exact-once source delivery and fixed budgets. Exceptional recovery guidance must retain its existing availability without aggregating output or bypassing hash checks in the reader.

### Task 1: Automatic authority and owning recovery route

**Files:** `scripts/read_instructions.py`, `scripts/drain_instructions.js`, `clients/codex.md`, generated `clients/instruction-map.json`, `docs/policy-sources.md`, `tests/test_prepared_instructions.py`, `tests/instruction_drain.cjs`.

**Interfaces:** `load_page/load_batch(..., auto=False)` retain existing defaults. `--auto` selects per-source validation and a mode-bound revision. Automatic JSON envelopes expose `mode="auto"`; the runner uses `--auto`, removes the global external choice and otherwise retains its read/drain contract.

- [x] Add mixed-source, authority/alias, revision and CLI tests; observe failure against the existing reader/runner.
- [x] Implement per-source classification and mode-bound identity with unchanged legacy behavior. Update the runner and sole owning contract, including one-result recovery budgets; retain all existing delivery tests.
- [x] Regenerate the map. Run `python3 -B -m unittest tests.test_prepared_instructions tests.test_instruction_drain tests.test_startup tests.test_package_compatibility`, package validation and diff checks. Expected: focused suite and package checks pass.
- [x] Obtain fresh independent review of the complete diff against `2179691`; resolve confirmed findings with regression evidence and commit the product.

### Task 2: Native qualification and same-task benchmark

**Files:** Private artifacts under `/tmp/vibe-scope-qualification-20261103` and `/tmp/vibe-scope-benchmark-20261103`; outcome in this plan.

**Interfaces:** Frozen baseline `2179691387316eee3f5154430a371b249aeac861`, reviewed candidate, unchanged fixture/prompts/settings. Analyzer handles per-source automatic routing separately from legacy explicit-mode counts.

- [ ] Qualify the actual mixed selection, automatic draining, clipping recovery and early yield; independently audit source bytes and budgets.
- [ ] Freeze fresh controls, stage/trust/preflight both arms under existing authorization and run implementation, independent review and one resume per arm. Stop on drift/timeout.
- [ ] Independently audit source selection, delivery, recovery budgets and normalized usage. Record limitations and leave the slice unmerged.

## Local review and validation

The focused reader/drain/startup/package-compatibility suite passed 103 tests, including 25 real-reader bootstrap scenarios. Package validation and `git diff --check` passed. Independent Astra review found no actionable issues; isolated probes also passed legacy parity, mixed exact reconstruction and bounds, alias/escape/private-target rejection, revision identity changes, no partial stdout, later clipping recovery without replay, awaited notification failure and metadata tampering. Review evidence: `/tmp/vibe-scope-review-20261103/review.md`. These are package and local execution checks; native delivery and benchmark results are recorded separately below.
