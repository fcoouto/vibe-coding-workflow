# Background OpenRouter Workers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Run bounded OpenRouter investigations through OpenCode with truthful Codex and Habblaud progress.

**Architecture:** An additive Python runner launches pinned OpenCode against copied inputs. A native supervisor consumes progress and verifies results; the existing local-delegation transport supplies Habblaud events.

**Tech Stack:** Python standard library, OpenCode 1.19.5, existing installed Habblaud transport.

**Spec:** ../specs/2026-10-28-openrouter-workers-design.md

## Global Constraints

- Preserve coordinator settings and existing provider authentication.
- Only copied, explicitly supplied read-only input files enter the worker workspace.
- No shared Genesis files, global activation, automatic retries or publication.
- OpenRouter manages monetary spending limits; timeout and step bounds limit execution.

## Review Focus

- Path traversal and symlink inputs must fail before launch.
- Duplicate run identities must never launch a second paid attempt.
- Errors, timeouts and malformed event streams must never become verified success.
- Credentials, source text and raw tool output must not enter progress or Habblaud events.
- Cancellation must terminate the owned process group and retain uncertain upstream billing.

### Task 1: Runner and boundary tests

Files: scripts/openrouter_workers.py; tests/test_openrouter_workers.py.

- [x] Write failing behavioral tests for input isolation, replay refusal, event/accounting reduction and failed/timeout execution.
- [x] Implement a private run directory, restrictive OpenCode configuration, bounded subprocess lifecycle and sanitized progress.
- [x] Reuse installed Habblaud transport; qualify event delivery against the actual local Habblaud receiver.
- [x] Run focused tests, package validation and the full repository suite; record their separate results below.

### Task 2: Supervisor contract and qualification

Files: skills/openrouter-workers/SKILL.md; skills/openrouter-workers/references/procedure.md.

- [x] Write the native supervisor, discovery/credit, permission, verification and recovery procedure.
- [x] Prepare a secure local OpenRouter login prompt.
- [x] Run a small real assignment through a genuine native supervisor; observe Habblaud and verify the answer independently.
- [x] Request fresh independent code/security review, fix confirmed findings and rerun affected tests.
- [x] Send Genesis additive file inventory and evidence, leaving shared integration until resume.

## Observed qualification

OpenCode 1.19.5 first rejected file reads because permission patterns are relative
to its detected Git worktree; a folder without Git resolves to `/`. Two failed
canaries were preserved. The runner now initializes a private empty Git repository
and allows only canonical, non-wildcard copied filenames. A non-inference server
preflight established the exact workspace and permission configuration before the
third attempt. That attempt completed one glob and two read tools; the native
supervisor independently verified the returned CSV calculation. Habblaud's actual
sidebar showed the role/model badge. Earlier failure states remained rejected.

Independent review found and verified fixes for descendant cleanup, malformed
events, incomplete cost reporting, unavailable visibility initialization and
filename permission patterns. Eleven focused tests pass. OpenCode's three-run
reported costs differ from OpenRouter's actual key usage; provider billing remains
authoritative. Private run receipts and reviewer-bound source hashes are kept
outside the repository. No broad write/permission capability is qualified.

Package and skill validation pass; eleven worker tests and twenty-two existing
proposal tests pass. The initial full repository run was interrupted after more than twenty
minutes in the unchanged core evidence/lifecycle tests. It had emitted one failure;
the test at that progress position passed on a focused rerun. The exact earlier
failure traceback was not available, so its cause remains unresolved. The final
interrupt stack was in `LinkedVerificationTests.test_linked_non_success_mixed_required_merged_history_survives_d4_retirement`,
through lifecycle recovery and repeated linked snapshots. That initial run did not establish
a full-suite pass or release approval. Genesis received that separate regression gap;
its reserved core implementation remains untouched.

## Remaining verification, 29 October 2026

The pilot was applied cleanly to primary revision
`cb4bac920d31927a7d6f5ddef90d51c8b42c0a56` in the isolated verification checkout.
Candidate `6cf0c6912295ba64c506f77e385f30b8a53aa1ac` has tracked tree
`d024a4d885cd6c4247da5e01a66d451aa5707aee`, identical to Genesis's local integration
`26f5590dcf3c5a072816e55045ef32b945519f4e`. All 108 tracked source hashes remained
unchanged throughout the run.

The complete verbose, fail-fast repository suite passed: **962 tests in
5933.361 seconds, exit code 0**. The full named log, source hashes, command, Python
version and timings are retained in private verification evidence. The earlier
uncaptured failure did not recur; its original cause remains unknown. SQLite
ResourceWarnings were retained in the log and are separate from test failures.
No runtime changes or additional OpenRouter inference were needed for this pass.

A no-inference check against isolated OpenCode 1.19.5 confirmed the pilot's final
wildcard permission denies skill access. The pinned runtime's system-prompt builder
returns before listing skills under that denial. Global external-skill discovery
may occur internally; this is not evidence of model access or an OS sandbox.
Package validation, skill validation and whitespace checks pass separately.

This full-suite result applies to the bounded read-only pilot integration above.
Later Observability caller revision `9a6e060a610c65590381151a22989af57903beec` and
unintegrated Genesis core changes are not covered by this frozen run. Their owners
retain their separate validation responsibilities. External editing, global
activation and publication remain outside this verification outcome.
