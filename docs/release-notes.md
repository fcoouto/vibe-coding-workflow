# Release notes

## 0.1.18

- Capture each subagent's role once while preparing its assignment. Reuse existing native, OpenRouter and Usage Routing metadata without blocking execution when display preparation fails. [PR #90](https://github.com/fcoouto/vibe-coding-workflow/pull/90)
- Bundle the Habblaud receiver fix for onboarding and upgrades: preserve nested child identity and immediate parents, retain early activity, and keep the original fallback when no role is available.
- Verified first observed badges in a fresh native check: `Coordinator · GPT-6-Astra` and nested `Reviewer · GPT-6-Astra`. No new external-provider or Claude Code live execution was performed. Native cache activation remains a separate client refresh; preserve active chats using older package paths.

## 0.1.17

- Enable live Manual and Smart Balance after the user connects an OpenAI project key and activates a regular routing policy. Comparisons and smoke tests are optional.
- Isolate smoke-test budgets from ordinary routing. Require explicit regular-budget setup and preserve prior charges and reservations. [PR #89](https://github.com/fcoouto/vibe-coding-workflow/pull/89)

## 0.1.15

- Enable Usage Routing even when other Codex work is active. Account for unrelated activity when attributing pilot measurements. Live admission still requires its existing qualification and safeguards. [PR #88](https://github.com/fcoouto/vibe-coding-workflow/pull/88)

## 0.1.14

- Include the delegation configuration and visibility changes from [PR #87](https://github.com/fcoouto/vibe-coding-workflow/pull/87) in the Git-backed marketplace release.

## 0.1.13

- Publish the Codex marketplace from a Git release branch so Codex can upgrade it while preserving the existing marketplace and plugin IDs.

- Fix onboarding inventory to fingerprint large, unchanged assets without loading whole files into memory. Preserve source and action body limits, aggregate budgets, secret exclusions, file identity and change detection. Add focused regression coverage for large assets, changed inputs and budget exhaustion.
