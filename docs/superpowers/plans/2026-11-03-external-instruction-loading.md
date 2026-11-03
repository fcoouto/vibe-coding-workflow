# External Instruction Loading Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans. Root implements the cohesive reader/route change; a fresh independent reviewer checks it.

**Goal:** Deliver all applicable external instructions through the existing bounded reader without adding routine coordination or changing external sources.

**Architecture:** Add explicit external source selection before existing validated page packing; reuse rendering, batches and revision-bound continuation. Preserve the existing advisory and native fallback.

**Tech Stack:** Existing Python standard-library reader and unittest.

**Spec:** `docs/superpowers/specs/2026-11-03-external-instruction-loading-design.md`

## Global Constraints

Preserve every source requirement, authority, applicability, freshness and package-path check. Keep existing 8,000 / 9,500 / 24,000 byte bounds. No external edits, new hooks, state, dependencies or model/settings changes. One paired benchmark; no automatic repeat or unrelated state-guard repair.

## Review Focus

External mode must not bypass packaged-source validation, follow references, accept non-Markdown symlink targets, mix stale revisions or emit partial text before discovering an invalid later source. Metadata counts toward bounds. Normal fitting reads stay one invocation.

### Task 1: Reader and loading route

**Files:** `scripts/read_instructions.py`, `tests/test_prepared_instructions.py`, `clients/codex.md`, `clients/instruction-map.json`, `docs/policy-sources.md`.

**Interfaces:** Add keyword-only `external=False` to `load_page` and `load_batch`, and CLI `--external`. Preserve existing defaults/schema. External results carry `external=True`; render an external header and repeat `--external` in continuation. Share source-range preparation with existing authoring.

- [x] Write and observe failing external CLI and exact reconstruction tests; include freshness, target changes, source-read count, invalid paths and no partial stdout.
- [x] Implement explicit external selection and reuse bounded packing/rendering. Expected: prepared-reader tests pass with all existing package checks retained.
- [x] Update the owning Codex route and source coverage; regenerate the package map. Expected: focused startup/read tests and `python3 -B scripts/validate.py` pass.
- [x] Verify the actual Graphify source reconstructs exactly without changing it. Obtain fresh independent review, resolve confirmed findings, and commit the reviewed slice.

### Task 2: Native paired benchmark

**Files:** Private copies of the existing harness under `/tmp`; no product benchmark framework.

**Interfaces:** Frozen baseline `541c928`, reviewed candidate, same private candidate identity/path and native account/settings. External reader evidence uses exact external source snapshots; no unbounded parser campaign.

- [ ] Stage/trust/preflight each frozen arm using existing authorization; run the same implementation, independent review and one resume with Vibe enabled in both.
- [ ] Verify actual model-visible Vibe and selected external instruction completeness, task acceptance, source/settings preservation, normalized usage and round trips.
- [ ] Record observed outcomes and limitations separately from package validation; do not infer savings from omitted required text.
