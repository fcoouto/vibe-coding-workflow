# Release notes

## 0.1.13

- Publish the Codex marketplace from a Git release branch so Codex can upgrade it while preserving the existing marketplace and plugin IDs.

- Fix onboarding inventory to fingerprint large, unchanged assets without loading whole files into memory. Preserve source and action body limits, aggregate budgets, secret exclusions, file identity and change detection. Add focused regression coverage for large assets, changed inputs and budget exhaustion.
