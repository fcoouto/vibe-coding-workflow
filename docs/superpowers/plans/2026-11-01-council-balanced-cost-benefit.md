# Balanced Cost-Benefit Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for this focused instruction update. The coordinator owns edits; one read-only native reviewer checks the result.

**Goal:** Choose better-value Balanced participants and replacements at runtime while preserving maximum reasoning.

**Architecture:** The existing coordinator applies the rule through each seat's `selection` rationale. Runtime schemas, execution, accounting and recovery stay intact.

**Tech Stack:** Local Markdown skill contracts and existing Python package validation.

**Spec:** User-approved option 1, recorded under Approved design below. The user explicitly requested immediate implementation.

## Approved design

Balanced first identifies models capable of the task, then favors lower expected session cost among comparably capable eligible alternatives. A materially more expensive choice needs a clear task-specific capability advantage; small benchmark gains do not justify a large premium. Current route prices and comparable usage evidence inform the decision, with uncertainty disclosed. Apply this rule to initial seats, fallback ranking and replacements using existing selection notes.

Approaches considered: strengthen the existing evidence-based rule (chosen); numerical quality/cost thresholds (rejected because they add rules across incomparable tasks and benchmarks).

## Global constraints

- Preserve maximum supported reasoning and advisory token targets.
- Preserve task fit, vendor diversity/reuse, eligibility, consent and original session bounds.
- Keep Free disabled and comparative evaluation deferred. Do not adopt a new benchmark or run paid comparisons.
- Preserve Frontier's capability-first selection and separate native usage from OpenRouter spending.

## Review focus

- A tiny comparable benchmark gain with a large premium favors the cheaper capable candidate.
- A material task-specific capability advantage can justify a premium.
- Reasoning volume affects cost; count billed tokens once and disclose uncertain estimates.
- Vendor constraints and missing evidence must not produce invented capability or cost claims.
- Replacements inherit the rule; Frontier and disabled Free retain their existing behavior.

## Steps

- [x] Update only the shared selection contract and its existing callers where needed.
- [x] Update source-to-contract coverage and representative validation scenarios.
- [x] Independently review the diff and walk the scenarios using synthetic metadata only.
- [x] Run package/skill validation and diff checks; record limits and commit the focused change.
