# Release notes

## 0.1.15

- Enable Usage Routing even when other Codex work is active. Account for unrelated activity when attributing pilot measurements. Live admission still requires its existing qualification and safeguards. [PR #88](https://github.com/fcoouto/vibe-coding-workflow/pull/88)

## 0.1.14

- Include the delegation configuration and visibility changes from [PR #87](https://github.com/fcoouto/vibe-coding-workflow/pull/87) in the Git-backed marketplace release.

## 0.1.13

- Publish the Codex marketplace from a Git release branch so Codex can upgrade it while preserving the existing marketplace and plugin IDs.

- Fix onboarding inventory to fingerprint large, unchanged assets without loading whole files into memory. Preserve source and action body limits, aggregate budgets, secret exclusions, file identity and change detection. Add focused regression coverage for large assets, changed inputs and budget exhaustion.
