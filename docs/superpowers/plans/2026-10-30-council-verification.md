# Council verification feedback

Approved: implement the pending correction handoff and validate both false claims
from the life/Python live tests, without extra rounds, attempts or budget.

- [x] Add failing local regression tests for rejected false claims, later-phase
      feedback, replacement-chair feedback, privacy and immutable packets.
- [x] Add optional bounded source-backed findings to existing verification inputs.
      Acceptance with outstanding findings fails. Seal reviewed findings for each
      relevant packet; preserve original evidence and phase generations. Reuse
      existing coordinator checks to verify flagged issues before acceptance.
- [x] Update the existing verification, protocol, recovery and native contracts;
      preserve progressive loading and source coverage.
- [x] Run focused regression and compatibility checks, package/skill checks and
      one independent review. Record local proof separately from live execution.

Implementation choices: findings contain only claim, correction/uncertainty and
approved evidence references. Raw private checks never become participant input.
Initial investigators remain isolated; critique catch-ups receive source only.
Feedback to later phases is frozen with the phase; retries receive their own prior
rejection feedback in separately sealed per-attempt inputs. No new reviewer,
scoring system, research service or automatic semantic truth classifier.

Local reproduction uses the observed SQLite isolation-level mistake and stale
peer-report/count assertions. No new provider inference or comparative evaluation.
All existing uncommitted selection/reorganization work remains intact.

Progress: three initial regression failures observed, then all passed. Added native,
CLI, bounds/legacy, peer-isolation/tamper and uncertain-clock checks. The first
144-test Council run exposed a prompt-length regression; the existing boundary
case failed, then passed after shortening phase instructions without increasing
the objective limit. Full-suite validation and independent review are in progress.

Validation scope decision: the broad repository run was started, then deliberately
interrupted (exit 130) after discovering its recorded 96-minute baseline run with
27 unrelated failures/errors. No full-suite result is claimed. Complete Council
and OpenRouter suites cover this change's runtime, shared executor and adapter
boundaries; the rest of the repository remains outside this validation result.
Independent review found no actionable issue and applied the Python, life and
advisory-presentation cases correctly. No fixes or second review were required.

Completed: Council 146/146 (144.303s), OpenRouter 105/105 (54.993s), package and skill
validation, link checks and diff checks passed. Eight new behavioral regressions
cover the approved handoff and its boundaries. Independent review is clean; reviewed
file hashes remain unchanged. Live inference, installed-package update and
comparative evaluation were not performed. No current full-suite result is claimed.
