# OpenCode Retry and Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reuse OpenCode's request retries, expose sanitized terminal recovery facts,
and remove mandatory credit preflights without adding an outer retry loop.

**Architecture:** Keep one pinned OpenCode invocation per read-only worker. Its
existing deadline bounds all internal retries. Codex consumes terminal failure and
local-stop evidence before independent native takeover; both executors rely on
OpenRouter's spending enforcement.

**Tech Stack:** Python 3.11+ standard library, POSIX process groups, Git, pinned
OpenCode 1.19.5, existing unittest fixture processes and optional Habblaud transport.

**Spec:** [Approved design](../specs/2026-10-29-opencode-retry-recovery-design.md).

## Global Constraints

- No outer worker retry, provider/model cascade, monetary cap, scheduler, or new dependency.
- Preserve copied-input read-only permissions, native settings, independent acceptance, replay protection, and original deadline.
- Preserve known usage and incomplete accounting; upstream cancellation and internal retry count remain unknown.
- Store only bounded, recognized failure fields; no raw errors, headers, response bodies, or stderr.
- Keep skill entry points within 150 words and maintain source-to-contract coverage.
- Genesis owns core runtime and serializes README/source-map edits; provide a private patch for those two files.
- User approved implementation through verification; execute inline without another plan-approval pause.

## Review Focus

- Budget 403 must remain distinguishable from permission 403; generic 402 must not imply zero balance.
- Malformed/oversized/nested provider bodies and invalid retry hints must never leak raw text or invent a cause.
- Terminal errors, stream truncation, and the global deadline must never trigger another OpenCode process.
- Failed cleanup must withhold native-takeover readiness; partial usage must survive both terminal errors and interruption.
- Legacy optional credit observations must neither gate dispatch nor become stored authority; capability and replay checks must remain intact.

### Task 1: Remove credit admission requirements

**Files:** `scripts/openrouter_proposals.py`, `scripts/openrouter_workers.py`,
`tests/test_openrouter_proposals.py`, `tests/test_openrouter_workers.py`.

**Interfaces:** Preserve existing actions and the `prepare` call signature. New
requests need no `credit`; legacy optional worker credit is discarded before
storage. New proposal records omit the obsolete credit-check timestamp. Existing
advisory history remains readable.

- [x] Write tests for admission without credit, ignored legacy observations, unchanged execution bounds, cache/route compatibility and replay checks.
- [x] Run focused tests and observe failures caused by the old credit requirement.
- [x] Remove credit freshness/free-price admission logic and unused Decimal handling; retain all unrelated checks.
- [x] Rerun both OpenRouter test modules and record the result.

### Task 2: Retain terminal failure and local recovery evidence

**Files:** `scripts/openrouter_workers.py`, `tests/test_openrouter_workers.py`.

**Interfaces:** Add `terminal_failure(error)` for a small summary with a controlled
`category` and optional observed `status_code`, recognized `limit_source`, and
finite `retry_after_seconds`. Add `stop_process(proc)` returning observed local
process-group quiescence. Result fields `failure`, `local_execution_stopped`, and
`native_fallback_ready` describe evidence, not approval or proof of upstream stop.

- [x] Add fixture tests for structured 402/403/429/503, context overflow, malformed errors, retry hints, secret exclusion, one invocation, partial charges, deadline and cleanup refusal.
- [x] Observe RED before implementation.
- [x] Implement bounded failure parsing and best-effort cleanup with explicit quiescence observation. Keep the existing OpenCode execution loop; never add replay.
- [x] Mark failed/unresolved results ready for native fallback only after confirmed local stop. Completed answers still require independent native verification; rejected answers may fall back after that same stop evidence.
- [x] Run focused tests to GREEN, including existing descendants and incomplete-accounting checks.

### Task 3: Align contracts and verify the complete slice

**Files:** Both OpenRouter `SKILL.md` and `references/procedure.md` files;
approved design/plan. Proposed README and `docs/policy-sources.md` changes go only
to the private handoff patch owned by Genesis.

**Interfaces:** Instructions load the matching executor only, use no mandatory
balance lookup, preserve proposal once-only admission, explain OpenCode-owned
request retries and distinguish observed local recovery from unknown billing.

- [x] Update instructions and prepare the exact-base shared-file patch without touching Genesis-owned files.
- [x] Exercise representative instruction paths: ordinary native task, bounded proposal, active worker, terminal budget/permission error, deadline and native verification.
- [x] Run `python3 -B -m unittest discover -s tests -p 'test_openrouter_*.py'`, `python3 -B scripts/validate.py`, and whitespace checks.
- [x] Qualify real pinned OpenCode against an isolated loopback fixture when supported, with a fixture-only credential, no account traffic, and explicit evidence labels. Check retry exhaustion, terminal error shape and native recovery independently.
- [x] Obtain one fresh Astra/high whole-change review; fix material findings with focused RED/GREEN evidence.
- [x] Freeze the source commit and private shared-file patch, record hashes and scoped evidence, and hand them to Genesis for serialized integration. No full-suite rerun without a new reason.
