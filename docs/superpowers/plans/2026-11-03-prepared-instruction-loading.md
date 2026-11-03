# Prepared Instruction Loading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Root implements this cohesive slice; independent reviewers assess the result.

**Goal:** Prepare and deliver applicable Vibe instructions without reconstructing clipped text.

**Architecture:** Keep canonical instruction sources unchanged except for the Codex loading route. Prepare exact line ranges and digests during authoring. A read-only CLI returns bounded pages; existing startup points to it before fanout.

**Tech Stack:** Python standard library, existing hooks and unittest.

**Spec:** `docs/superpowers/specs/2026-11-03-prepared-instruction-loading-design.md`

## Global Constraints

- Preserve all requirements, authority checks, native workflow, permissions and model settings.
- Do not modify RTK, other plugins/skills or the live Vibe installation.
- No runtime database, external dependency, automatic recovery loop or silent task repin.
- Keep source bytes exact; source segments at most 8,000 bytes and rendered pages at most 9,500 bytes.
- Reuse the existing isolated checkout, staged candidate and identical benchmark protocol.

## Review Focus

- Changed source or continuation must not combine incompatible revisions.
- Missing, duplicate, overlapping or out-of-bounds ranges must not hide requirements.
- Absolute paths, traversal and symlinks must not expose files outside packaged instructions.
- Startup-only and unenrolled contexts must not acquire managed runtime prerequisites.
- A bounded child output does not protect arbitrary outer rebatching or third-party reads.

### Task 1: Prepared reader and startup integration

**Files:** Create `scripts/read_instructions.py`, `clients/instruction-map.json`, `tests/test_prepared_instructions.py`. Modify `runtime/startup.py`, `clients/codex.md`, `scripts/validate.py`, affected startup tests and `docs/policy-sources.md`.

**Interfaces:** `build_manifest(root) -> dict`; `load_page(root, paths, page=1, revision=None) -> dict`; `render_page(result) -> str`; CLI `read_instructions.py bootstrap`, or selected paths with `--page` and `--revision`; authoring-only `--prepare`.

- [x] Write and run failing tests for lossless bounded reconstruction, selective reads, stale continuation, malformed ranges and path containment.
- [x] Implement preparation and the read-only reader using only the standard library.
- [x] Route Codex startup to the reader without changing authority or Claude startup behavior; test the emitted command against real packaged sources.
- [x] Generate the manifest, integrate freshness validation, run focused tests and package validation.
- [x] Independently review the full slice and record requirement coverage; fix confirmed findings within scope.
- [ ] Commit the reviewed candidate and preserve the prior candidate separately.

### Task 2: Repeat the paired benchmark

**Files:** New private run directory and copies of the existing benchmark adapter/orchestrator outside the package.

**Interfaces:** Same prompts, fixture, model/effort, implementation/review/one-resume phases and analyzer; add explicit recognition of prepared reader calls.

- [ ] Stage only the reviewed candidate and refresh its existing native hook trust through normal controls.
- [ ] Execute one control/candidate pair, preserving per-phase source fingerprints and configuration receipts.
- [ ] Independently assess source coverage, clipping/recovery, rereads, test outcomes and normalized usage.
- [ ] Report package validation separately from observed native CLI execution, including limits and any unmet acceptance criterion.
