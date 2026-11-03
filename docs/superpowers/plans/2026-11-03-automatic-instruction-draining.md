# Automatic Instruction Draining Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans. Root implements the cohesive change; a fresh independent reviewer checks it before native qualification and benchmarking.

**Goal:** Remove model decisions between instruction batches while preserving complete delivery, freshness and scope.

**Architecture:** Add machine envelopes to the existing reader and a fixed Vibe-owned JavaScript continuation helper. The initial Codex native call owns the single-batch fast path and conditional helper loading; the awaited helper delivers each batch separately.

**Tech Stack:** Python standard library, native JavaScript, existing Python unittest and Node for deterministic host-callback tests only.

**Spec:** `docs/superpowers/specs/2026-11-03-automatic-instruction-draining-design.md`

## Global Constraints

Preserve all source requirements and existing 8,000/9,500/24,000-byte bounds. No external plugin/model/settings edits, new hook, server, dependency, persistent cache or task controls. Keep per-batch freshness checks. One paired benchmark; no automatic reruns or unrelated state-guard repair.

## Review Focus

Incomplete JSON/body counts must never be emitted as complete. Source text and shell-sensitive paths must not become executable control data. Failed/cancelled/unfinished calls must not report success. Fallback must cover exactly the missing ranges while preserving revision/target identity. A one-batch selection must not load the helper.

### Task 1: Reader, helper and owning route

**Files:** `scripts/read_instructions.py`, new `scripts/drain_instructions.js`, `runtime/state.py` (existing runtime fingerprint list only), `clients/codex.md`, `clients/instruction-map.json`, `docs/policy-sources.md`, `scripts/validate.py`, `tests/test_prepared_instructions.py`, new `tests/test_instruction_drain.py` and `tests/instruction_drain.cjs`.

**Interfaces:** Add `--json` and exclusive `--helper`; preserve existing page APIs and plain CLI. Envelope fields and injected helper callbacks follow the spec. The Node test executes the actual Codex bootstrap with real Python reader calls and controlled native transport failures.

- [x] Add meaningful CLI and native-bootstrap tests; observe unsupported JSON/helper behavior fail before code changes.
- [x] Implement envelopes, bounded helper, fast path and canonical loading contract. Verify exact text reconstruction and the specified failures, without model calls.
- [x] Update authoring coverage and package validation; regenerate the instruction map. Run focused reader/drain/startup checks and package validation.
- [x] Obtain fresh independent review of the whole slice against `385ff3e`; resolve confirmed findings and commit the reviewed product.

### Task 2: Native qualification and paired benchmark

**Files:** Owned private harness/evidence under `/tmp/vibe-drain-benchmark-20261103`; recorded outcome in this plan.

**Interfaces:** Existing same-task harness, baseline `385ff3e`, frozen reviewed candidate, unchanged prompts/model/authentication/settings. Preserve each separate notification in model-visible evidence and normalize cumulative resume counters.

- [x] Qualify actual notification delivery for the failed four-file selection, near-limit batches and an early native yield; count completeness separately from test assertions.
- [ ] Freeze controls, stage/trust/preflight both arms using prior authorization, and run implementation, independent review and one resume per arm. Stop on external drift or timeout.
- [ ] Independently audit exact selected-source delivery, native route adoption, acceptance and normalized overhead. Record limitations and keep incomplete work unmerged.
