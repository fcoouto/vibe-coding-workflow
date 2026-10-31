# LLM Council Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore model-led peer evaluation, use direct requests for text-only questions, and disable Free without weakening execution safeguards.

**Architecture:** Keep the existing Council state machine and worker supervision. Add a tool-free HTTP child transport, distinguish technical usability from substantive judgment, and retain the qualified read-only repository transport. Historical runs remain auditable without further inference.

**Tech Stack:** Existing Python runtime and unittest suite; Python standard library HTTP and subprocess support; existing Codex native dispatch. No new dependency or service.

**Spec:** [Council simplification design](../specs/2026-10-31-council-simplification-design.md).

## Global Constraints

- Implement only after the user reviews this plan. Preserve the existing approved subagent execution preference.
- New requests require `mode: "text" | "repository"`; persist `flow: "peer-review"`. Free is unavailable; Frontier/Balanced selection stays runtime and task-aware.
- Keep native model/authentication settings, group-specific participant, fresh native chair, maximum supported reasoning, provider pins and disabled provider fallback.
- Keep the original 1,200-second session budget and default 600/360/240-second phase allocation. Keep current size/token limits and consent/snapshot/ownership/cancellation boundaries.
- Recovery remains one investigation of at most 120 seconds, three searches/five reads, two evidenced workaround attempts and three replacements per seat, within the original budget. Do not retry factual disagreement.
- Entry points stay within 150 words. Maintain `docs/policy-sources.md`. Comparative evaluation, Free qualification and paid live inference are deferred.

## Review Focus

- A late response after cancellation or a closed phase cannot enter the next packet; Task 1/3 test this race.
- A bare question with no source files must work without checkout writes; Task 1/2 exercise the empty snapshot.
- An HTTP 200 error, reasoning-only reply, refusal or malformed ranking must be classified by completion semantics, not answer agreement; Task 2/3 distinguish these cases.
- A historical Free run must remain readable and stoppable while every inference path is blocked; Task 1 tests both.
- Saved auth changes, redirects or unsupported controls must not expose credentials or silently change the request; Task 2 tests these boundaries.

---

### Task 1: Pin the simplified session contract and disable Free

**Files:** Modify `runtime/council.py`, `runtime/council_snapshot.py`, `runtime/council_recovery.py`, `scripts/council.py`; test `tests/test_council_flow.py`, `tests/test_council_recovery.py`, `tests/test_council_snapshot.py`, `tests/council_fixtures.py`.

**Interfaces:** `council.prepare(cwd: Path, request: dict) -> dict` requires mode on new runs and stamps the flow. Existing `packet`, `resume_member`, `external_launch_guard`, replacement and receipt paths share a new internal `_require_current_flow(value: dict) -> None` admission check. `snapshot.capture(checkout: Path, destination: Path, approved: dict, *, allow_empty: bool = False) -> dict` permits empty evidence only when the caller explicitly selects text mode.

- [ ] Add tests: `test_new_run_requires_mode`, `test_text_question_allows_no_files_without_checkout_writes`, `test_repository_requires_approved_files`, `test_free_prepare_and_all_inference_paths_blocked`, `test_historical_status_cancel_and_settlement_only`, `test_closed_phase_rejects_late_result`. Assert invalid mode fails before creation; new Free prepare fails before inference; historical artifacts retain their hashes; status/cancel and operational settlement still work.
- [ ] Run `python3 -B -m unittest tests.test_council_flow tests.test_council_recovery tests.test_council_snapshot`. Confirm new assertions fail for the missing behavior.
- [ ] Implement mode/flow admission in the shared boundary, including native dispatch, direct/worker launches and all recovery entry points. Permit historical stop/accounting receipts, but reject new verdicts or dispatch. Keep snapshot safety and phase headroom; do not bump every historical manifest version or delete history parsers.
- [ ] Run the same command. Require all relevant tests to pass; update existing fixture prepares to explicitly declare the intended current mode or historical status.
- [ ] Commit the contract change after review.

### Task 2: Add a direct text request inside existing worker ownership

**Files:** Create `scripts/council_direct.py`, `tests/test_council_direct.py`; modify `scripts/openrouter_workers.py`, `runtime/council.py`, `runtime/council_recovery.py`, `scripts/council.py`; test `tests/test_openrouter_workers.py`, `tests/test_openrouter_settings.py`.

**Interfaces:** Extend the existing Council worker brief with an internal `transport: "openrouter-chat" | "opencode"` chosen only from sealed mode. The new child provides `send(payload: dict, auth_data: Path, timeout: float) -> dict` and `main() -> int`; stdin holds the sealed payload, never a key. Return one bounded terminal JSON object with `response`, optional `generation_id`, reported model/usage/cost and a typed technical failure. Existing worker `execute(...) -> dict` retains ownership and result persistence, stores `transport` and local `attempt_id`, and leaves `session_id` null for direct calls.

- [ ] Add fake-server tests: `test_text_wire_has_only_approved_material_and_no_tools`, `test_fixed_provider_max_reasoning_and_no_fallback`, `test_private_auth_only_and_redirect_rejected`, `test_terminal_content_and_error_classification`, `test_direct_cancel_and_deadline_stop_owned_process`, `test_fresh_attempt_hash_not_fake_session`, `test_repository_still_uses_qualified_opencode`. Cover HTTP errors/200 error envelopes, blank/reasoning-only output, length truncation, unsolicited tools, missing accounting, valid refusal text, changed consent/auth bindings and blocked Free helper dispatch. Assert no key or unapproved path/source appears in saved output; no OpenCode process launches for text.
- [ ] Run `python3 -B -m unittest tests.test_council_direct tests.test_openrouter_workers tests.test_openrouter_settings`; confirm the new tests fail before the implementation exists.
- [ ] Implement the tool-free requester with `urllib.request`, a fixed HTTPS destination, no redirects or hidden retries, bounded response reads and the saved API record. Keep credential loading in the owned child. Do not return raw exception bodies or headers to logs.
- [ ] Branch the existing worker spawn/parser by sealed transport while retaining its locks, admission guard, timer, progress, output bound and cleanup. Apply the spec's text capability/qualification schema without requiring tool support or an OpenCode binary hash; reject that schema for repository execution. Build messages from the verified snapshot and phase packets; exclude local storage/auth paths. Retain setup prerequisites. Extend verification/recovery identity checks to use direct attempt plus request/result hashes; retain actual OpenCode session proof for repository and historical records. Validate text context/output fit before send. Do not turn intermediate or truncated output into terminal text.
- [ ] Run the same command plus Task 1's tests. Require pass; confirm forced timeout/cancel stops the owned child and does not claim upstream billing cancellation.
- [ ] Commit the transport change after review.

### Task 3: Remove substantive filtering and host correction overlays

**Files:** Modify `runtime/council.py`, `runtime/council_recovery.py`, `scripts/council.py`; test `tests/test_council_flow.py`, `tests/test_council_recovery.py`, `tests/test_council_direct.py`, `tests/council_fixtures.py`.

**Interfaces:** Existing `verify_external(...)` and `record_native(...)` record technical disposition for new runs. New peer-review requests do not accept substantive `findings`; historical decoding remains intact. `_critique_snapshot` and `_seal_inputs` distribute every usable report unchanged under anonymous labels. `_objective` owns the one critique/ranking prompt and fresh synthesis prompt. `_status` reports participation without truth-certification wording.

- [ ] Add `test_disputed_claims_reach_critique_and_synthesis_unchanged` using the live-test claim types in the spec. Assert all three complete safe answers appear in both packets, even when a critic disagrees or ranks one last. Add `test_missing_ranking_keeps_critique`, `test_no_host_feedback_files_or_semantic_retry`, `test_real_technical_failure_uses_bounded_recovery`, `test_no_initial_answer_stops_without_chair`, `test_partial_counts_and_failed_chair_are_honest`. Preserve existing tamper, anonymity, original-deadline and cancellation cases. A late terminal response cannot reopen a closed phase.
- [ ] Run `python3 -B -m unittest tests.test_council_flow tests.test_council_recovery tests.test_council_direct`; confirm the substantive-filter regressions fail first.
- [ ] Remove the new-run semantic verdict and correction-overlay branches. Keep technical checks, immutable raw reports, observed failure details and historical audit support. Ask critics to evaluate assumptions and rank preferences; pass all usable answers/reviews to the chair. Delete obsolete new-run tests of semantic rejection and replace them with the preservation assertions, retaining their applicable security coverage. No extra phase, judge or scoring engine.
- [ ] Run the same command. Require pass and a synthetic end-to-end text run with three initial answers, three critiques and a fresh chair. Verify a deliberately mistaken answer survives to peer review and uncertainty survives synthesis.
- [ ] Commit the flow change after review.

### Task 4: Replace the runtime instructions and verify the complete slice

**Files:** Modify `skills/llm-council/SKILL.md`, `skills/llm-council/references/procedure.md`, `selection.md`, `protocol.md`, `recovery.md` in that references directory; `clients/codex-council.md`, `skills/manage-openrouter/references/procedure.md`, `README.md`, `docs/policy-sources.md`, `docs/council-validation.md`.

**Interfaces:** Skill entry routes to the existing stage references. Procedure owns the flow; selection owns paid group/task/API eligibility; protocol owns mode and transport-specific schemas; recovery owns only technical failure handling. Define each rule once.

- [ ] Replace superseded paragraphs instead of appending exceptions. Document Free unavailable, no silent paid substitution, current/history distinction, direct auth support and retained setup prerequisite. Retain explicit invocation and `LLM Council` naming. Align native receipt wording with technical admission and fresh chair ownership.
- [ ] Walk three representative tasks through the instructions: bare life question uses text mode and Frontier/Balanced selection; Python inspection uses repository mode and qualified tools; attempted Free invocation stops before launch while historical cancellation remains available. Record loaded references and expected decisions in `docs/council-validation.md`; label these instruction checks, not observed provider execution.
- [ ] Run `python3 -B -m unittest tests.test_council_flow tests.test_council_recovery tests.test_council_snapshot tests.test_council_direct tests.test_openrouter_workers tests.test_openrouter_settings` and `python3 -B scripts/validate.py`. Require relevant suites and package validation to pass. Inspect the final diff and source-to-contract coverage; report unrelated baseline failures separately rather than claim a full-suite pass.
- [ ] Obtain the independent implementation review required by project policy, address material findings, and rerun affected checks. Record exact checks and remaining unknowns. Commit this completed slice after review; do not install, merge or run paid inference without the next requested step.

## Approval checkpoint

Review the proposed requester reuse, mode field, historical read-only policy and retained safeguards before implementation. No runtime, installed package, credentials or paid sessions are changed by this plan. A later authorized paid end-to-end run should exercise one text question and one repository question; comparative evaluation remains separate.
