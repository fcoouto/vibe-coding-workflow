# Packaged Instruction Runner Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans. Root implements the cohesive refactor; a fresh independent reviewer checks it before native qualification and benchmarking.

**Goal:** Reduce repeated model-generated loader code while preserving automatic instruction draining and every delivery check.

**Architecture:** The existing fixed helper becomes the complete runner. A short native launcher validates its helper envelope, then calls it with the original selection and native callbacks.

**Tech Stack:** Existing Python reader, native JavaScript and real-reader Node/Python tests; no new dependency.

**Spec:** `docs/superpowers/specs/2026-11-03-packaged-instruction-runner-design.md`

## Global Constraints

One helper command per selection is explicitly approved, including small loads. Preserve all 8,000/9,500/24,000-byte bounds, source authority/freshness and failure behavior. Keep RTK, other plugins and native settings unchanged. No new protocol, cache, runtime controls or automatic source grouping. One paired benchmark, no automatic retries, no merge/live installation.

## Review Focus

The short launcher must reject clipped, empty, wrong-kind/version, nonzero or unfinished helper output before evaluation. Moving instruction checks must not lose first-page/mode, revision, target, Unicode or pending/cancelled behavior. Notifications and the final receipt must remain awaited. Source text and shell-sensitive paths must stay data. Existing helper containment and runtime fingerprints remain in force.

### Task 1: Move the loader into the fixed runner

**Files:** `scripts/drain_instructions.js`, `clients/codex.md`, `tests/instruction_drain.cjs`, `docs/policy-sources.md`, generated `clients/instruction-map.json`. Keep the reader CLI and runtime pin list unchanged.

**Interfaces:** `drainInstructions({root, paths, external, exec, emit})` performs all instruction reads and returns the unchanged complete receipt. The launcher obtains only the fixed `--helper` envelope and supplies `tools.exec_command`/`notify`.

- [x] Update real-bootstrap tests for helper-first loading, one helper for small/large selections and zero instruction reads after invalid helper delivery. Observe the small/helper tests fail against the previous launcher.
- [x] Move command construction and instruction validation into the existing helper; shorten the documented launcher without weakening its helper gate. Preserve the existing continuation loop and failure probes.
- [x] Update source coverage and regenerate the instruction map. Run `python3 -B -m unittest tests.test_prepared_instructions tests.test_instruction_drain tests.test_startup tests.test_package_compatibility`, `python3 -B scripts/validate.py` and `git diff --check`. Expected: focused suite and package checks pass.
- [x] Obtain one fresh independent review against `1fc4dfa`, resolve confirmed findings with regression evidence, and commit the reviewed product.

### Task 2: Native qualification and paired benchmark

**Files:** Private qualification and harness/evidence under `/tmp/vibe-runner-qualification-20261103` and `/tmp/vibe-runner-benchmark-20261103`; outcome recorded in this plan.

**Interfaces:** Frozen baseline `1fc4dfaf58deb6dda9be7cf246d08ec470af88d6`, reviewed candidate, existing same-task prompts/acceptance/model settings. The analyzer recognizes the actual short launcher, preserves notifications and normalizes resumed cumulative counters.

- [ ] Qualify the actual launcher: small selection, Graphify, maximum batch, forced child clipping and early yield/wait. Independently match delivered source bytes.
- [ ] Freeze fresh controls, stage/trust/preflight both arms under existing authorization and execute implementation, independent review and one resume per arm. Stop on drift/timeout.
- [ ] Independently audit source delivery and normalized overhead. Record mixed results and limitations accurately; keep the slice unmerged.
