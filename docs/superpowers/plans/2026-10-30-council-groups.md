# LLM Council Runtime Groups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement runtime-selected groups, including a fully external Free panel,
then perform one authorized bounded live session.

**Architecture:** Extend the existing three-member manifest with group, neutral
slot IDs and chair. Reuse executor, frozen artifacts, consent, accounting and stop
ownership; runtime selection remains in the common coordinator procedure.

**Tech Stack:** Python standard library/unittest, existing Codex controls,
pinned OpenCode 1.19.5 and the user's existing OpenRouter setup.

**Spec:** [Approved direction](../specs/2026-10-30-council-groups-design.md).

## Global Constraints

- Ask Frontier/Balanced/Free first; resolve only the chosen group at runtime.
- No hardcoded commercial roster or new ranking/service/UI/dependency.
- Exactly three members, one critique round, and fresh chair synthesis.
- Native selection varies for paid groups; Free contains no native participant
  or native fallback, including synthesis.
- Preserve saved consent/revision, approved immutable bytes, provider scope,
  qualified read-only profile, maximum effort where selectable and honest
  documented-default handling for Free, finite bounds, cumulative deadline,
  no duplicate inference, exact stop ownership and nullable accounting.
- Old manifests retain their historical interpretation; do not mutate evidence.
- Preserve coordinator/authentication/subscriptions; no paid fallback or outer
  inference replay. Comparative evaluation remains deferred.
- Use skill-creator for workflow instructions; entry point stays within 150 words.
- Validate with `python3 -B scripts/validate.py`; report client execution separately.

## Review Focus

- A free canonical alias loses its variant or price changes: reject before launch.
- A third external member or synthesis has unknown stop: retain ownership and block.
- Synthesis misses critiques or inherits an earlier session: reject acceptance.
- A snapshot interruption or changed input appears: preserve bytes and fail safely.
- Historical native rosters and outcome meanings remain inspectable after update.

---

### Task 1: Group-aware execution, synthesis and local contracts

**Files:** `runtime/council.py`, `scripts/council.py`,
`scripts/openrouter_workers.py`, `tests/test_council_flow.py`,
`tests/test_openrouter_workers.py`, owning snapshot tests/fixtures where needed,
`skills/llm-council/references/procedure.md`, `clients/codex-council.md`,
`docs/policy-sources.md`, `README.md` and Council validation only if needed.

**Interfaces:** Grouped `prepare` adds `group` and `chair`; roster keys exactly
`member-one`, `member-two`, `member-three`, with existing kind-specific seat data.
Chair must name one selected seat. New manifests use version2. Ungrouped requests
continue to use version1 and original `native`/`external-one`/`external-two` keys.
External grouped seats also carry nonempty `canonical_model` from observed
discovery (separate from the routable request ID) and bounded `pricing` with numeric nonnegative
`prompt_usd_per_million`, `completion_usd_per_million`, and nonempty `source` and
`observed_at`. Free requires a `:free` request ID and both rates exactly zero.
Keep canonical observations in selection provenance without replacing the request
variant. Distinct external seats must not resolve to the same canonical model.
Free group/price/identity constraints must remain checked at launch, not only at
prepare, so a changed worker brief cannot purchase a paid variant. Legacy request
shapes remain valid.

User clarification during implementation: selection considers Intelligence,
Coding and Agentic indexes and task fit; missing effort labels alone do not prove
a model incapable. Add Free-only `capabilities.reasoning: {default_enabled: true}`
with `effort: "default"` for an exact route's documented reasoning-enabled default.
Existing capability source/date must retain that positive documentation. Omit the
reasoning object entirely from OpenCode options for this mode. Do not force generic
`enabled:true`, infer an effort/budget mapping, or claim maximum verification.
Other selectable/fixed modes retain their existing checks. Add focused RED/GREEN
for acceptance only in Free, absence of unsupported wire overrides, malformed
default declarations, and preserved phase/identity guards. This replaces the
earlier inference that missing selector metadata necessarily makes Free ineligible.

Native seat fields stay unchanged. Free requires three external seats; paid groups
one native plus two external seats and native chair. Require three distinct model
identities for grouped runs, full qualified roster at prepare, and pinned chair.
Existing packet/resume/status/cancel actions accept the new member IDs; dispatch
uses seat kind. Synthesis dispatch is restricted to the chair, external or native.
All external grouped phases retain observed distinct session IDs at acceptance.
External synthesis is verified through an additive `council.verify_external(run,
phase, member, disposition, checks)` route and CLI `verify-external` so freshness,
frozen evidence, phase/time and original worker ownership are checked before
acceptance. Legacy worker verification remains supported for legacy runs; grouped
observations must not trust a bypassed manual accepted flag as freshness proof.
Do not create a general receipt service.

- [x] **Step 1: Write focused failing tests.** Cover all-free full 3+3+1 acceptance,
  group-specific native selection, wrong topology/native Free/paid Free/duplicate
  models rejection, chair restriction, complete/incomplete/partial coverage,
  old manifest/request behavior and all seven external attempts in accounting/stop.
  Capture RED before implementation.
- [x] **Step 2: Extend the existing runtime and worker contract.** Add version-aware
  three-slot/chair helpers; external synthesis support; preflight all executable
  phase briefs; zero-rate/variant checks; phase-aware sealed synthesis packet and
  headroom for six reports, research and observations. Preserve no-clobber recovery,
  source hashes and absolute deadlines. Avoid unrelated refactoring.
- [x] **Step 3: Prove synthesis and ownership.** Add RED/GREEN tests for critiques
  and anonymous observations present in the external packet, frozen changes blocked,
  distinct original sessions, missing/reused synthesis session rejected, bypassed
  accepted flag excluded, terminal failure settlement, original lost response,
  cancel/disable/stale consent and ambiguous spawn retaining owner. Keep reports
  in files rather than exceeding the objective envelope. No extra inference retry.
- [x] **Step 4: Update runtime instructions once.** Invocation asks the group first;
  current guidance/cache supplies eligible group-specific participants and chair,
  with no fixed names or group-wide catalog prefetch. Show concrete scope/roster,
  reuse authorization, preserve free variant and handle unavailable full group.
  Specify fresh Free chair, no native fallback, host verification and truthful
  coverage/cost. Update source coverage and representative loading walkthroughs.
- [x] **Step 5: Verify and self-review.** Run affected Council/OpenRouter modules,
  skill validation, package validation and diff checks; retain raw RED/GREEN logs.
  No historical 90-minute broad discovery replay. Coordinator owns commits and
  independent task review; fix material findings with scoped covering checks.

### Task 2: One bounded live session and final evidence

**Files:** private plan workspace qualification harness/reports only, followed by
factual `docs/council-validation.md` and plan status. No new product service.
Actual first live concurrency exposed local control defects. A narrow operational
correction may touch `scripts/openrouter_workers.py`, `runtime/council.py`,
`runtime/openrouter_settings.py` and their owning tests: include grouped deadline
admission in safe bounded control handling and classify only demonstrated
nonblocking D4 lock contention as busy. Active/uncertain D4 ownership and unrelated
storage failures remain blocked. Preserve the first partial run and all original
records; do not reset terminal attempts or replay its inference. After focused
proof and independent scoped review, one fresh Free qualification on changed code
is authorized within the implementation/live-test task, with the same harmless
scope, zero paid fallback and 1200-second session ceiling. First-run owners must
be proven locally stopped before starting it.

**Interfaces:** Use Task1 grouped prepare/packet/verify/status contracts on the
already authorized disposable checkout and saved Council scope. Reuse existing
pinned binary/auth references without reading or copying credentials. Default live
group Free unless the user selects another. Existing temporary enrollment exception
is not full project adoption. Do not enroll or change a live project.

- [x] **Step 1: Resolve readiness.** Confirm actual existing disposable scope is
  idle and configured. Use bounded public discovery for selected group, exact
  routing/effort/zero-price evidence and any concrete pinned wire-control question.
  A credential-free local fixture may establish outgoing parameter behavior; no
  real model call is a substitute for missing readiness. Show resolved roster,
  scope and budgets before inference. Stop dependent live work on a real blocker,
  without silently downgrading, replacing or purchasing a fallback.
- [x] **Step 2: Run authorized live proof.** Three investigations, three critiques,
  one fresh chair synthesis; default 1200s with 600/360/240 cumulative phase budgets.
  Use a harmless synthetic dependency/evidence question; no real source or probe
  instructions. Keep finite model-specific allowances, advisory report brevity,
  native supervision, actual session handles and progress. No outer replay.
- [x] **Step 3: Verify evidence and stop.** Independently check source claims,
  original snapshot/frozen reports, accepted phase membership/freshness, all local
  owners and reported nullable costs. Retain sanitized original result/progress
  records and exact unknowns. Do not label an incomplete run complete.
- [x] **Step 4: Final review and report.** One strongest-native review of the
  integrated feature/proof, one consolidated fix wave if needed and scoped re-review.
  Record package checks separately from actual live observations, remaining limits
  and comparative deferral. Coordinator commits factual evidence; no push/merge,
  account change or release archive.

## Self-review

The tasks share runtime schemas only in dependency order; Task2 consumes reviewed
Task1 contracts. All five Review Focus cases have Task1 owning tests. Group-first
selection and native variation are instruction policy, not a new ranking engine.
The user already approved implementation and live testing after the reviewed
direction; no redundant plan/approach approval is requested.

## Execution status

Task1 implemented and independently reviewed through `bad0f92`. Task2 reproduced
and corrected two local startup defects at `1754424`, with independent scoped
review and 162 affected tests passing. First partial live run is preserved and all
its owners are stopped. One fresh changed-code Free run completed all seven
external assignments in 254.020 seconds with distinct sessions and confirmed local
stops. Its result is **partial**, with 3/3 accepted investigations, 1/3 critiques
and no accepted synthesis. No inference retry, replacement or native Council
fallback was used. Final integrated Astra/xhigh review found no blocking source finding. Its minor
approved-path guidance recommendation was corrected at `9ae3c4b`, passed ten
focused checks and received a clean scoped re-review. No further live inference
was performed. Implementation and bounded test execution are complete; full Free
qualification and comparative evaluation remain open.
