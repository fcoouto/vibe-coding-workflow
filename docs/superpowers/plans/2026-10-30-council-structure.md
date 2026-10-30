# Council instruction reorganization

**Approved design:** The user approved four focused references: the main procedure,
selection, protocol and recovery, retaining the existing Codex adapter. Reorganize
without behavior changes, then reassess the pending verification fix separately.

**Boundary:** Preserve current runtime contracts, defaults, safeguards, versions,
schemas, recovery limits and all existing uncommitted task-aware selection work.
No runtime code, external inference, installation or verification-feature changes.

- [x] Capture current instructions and passing package baseline.
- [x] Extract selection, exact protocol and recovery into focused references;
      organize the main procedure around actions and verification gates.
- [x] Route entry/client reads by applicable stage, update consumers and maintain
      source-to-contract coverage for every original instruction block.
- [x] Independently review coverage and apply representative Free/paid/recovery/
      interruption/failed-synthesis loading scenarios; validate package and skill.
- [x] Reassess the verification proposal against the reorganized contract and
      report it as pending, without implementing it.

Readiness, transmission review, backup approval, finite allowances and ownership
must be available before inference. Unknown stop ownership never releases work.
Conditional loading must preserve complete action schemas and legacy behavior.
Compare against the retained before-copy, not only the latest Git commit, because
the approved task-aware instructions already include uncommitted work.

## Pending verification fix: review after reorganization

The new verification step already requires independent source checks. Another
broad instruction to be careful would duplicate that contract. The remaining gap
is the handoff of known defects: private verification checks do not enter the
anonymous phase evidence, and synthesis retries reuse the sealed packet without
rejection feedback. Fresh context alone does not repair contaminated evidence.

Recommend one bounded addition, still pending approval:

1. At verification, distinguish presentation warnings from false or unresolved
   consequential claims. An otherwise useful answer must not treat a known false
   claim as verified. Record a short anonymous correction with a source reference;
   keep unsupported suspicions explicitly unresolved.
2. Carry reviewed, transmission-safe corrections into later critique/synthesis and
   give a replacement chair the specific rejection reason. Preserve original
   reports and frozen generations; seal feedback separately for each new attempt.
   Never forward raw private `checks`, identities or diagnostics automatically.
3. Before acceptance, independently check that each flagged issue is corrected,
   properly qualified or omitted without hiding a material disagreement. Check
   Council participation claims against runtime facts. The model's assurance is
   not verification.

The main procedure should own this short decision gate. Exact feedback fields and
packet handling belong in protocol/runtime; replacement handling belongs in
recovery. Keep the same roster, critique count, retry allowances and original
budget. Add no evaluator role or scoring framework. Regressions should reproduce
the observed SQLite error and stale participation claims, verify feedback reaches
a replacement chair, and preserve privacy and immutable evidence.

This proposal reduces recurrence of known errors; it cannot promise discovery of
all new false claims. No verification behavior or runtime code changed here.

## Subsequent approval

The user subsequently approved implementing the verification feedback fix without
extra rounds or budget. Execution and validation are recorded in the
[verification plan](2026-10-30-council-verification.md); the reorganization above
remains the completed behavior-preserving checkpoint.
