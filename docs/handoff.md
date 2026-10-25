# Handoff

25 October 2026 · Continue from this repository's actual state.

## Read first

1. [Development rules](../AGENTS.md).
2. [Approved policy contracts](policy-contracts.md).
3. [Design and delivery plan](onboard-my-project-plan.md).

## Current state

- Present: plugin manifest, local marketplace, concise README, `prepare-my-workspace` skill and package validator.
- Approved: Installation / Project Onboarding / Runtime; mandatory policy adoption with conditional runtime actions; the feature baseline; Delegation and Model Selection; Proportional Security Review.
- Security review runs after implementation, before accepting a task/wave as complete or merging. Planning includes relevant requirements/tests without a separate security-review gate.
- Pending implementation: `onboard-my-project`, adapters, runtime, hooks, resource coordination and repository merge enforcement. Other policy details and architectural choices remain proposals.
- No target project has been onboarded or qualified. PHIOON has nine repositories; rollout starts with the planned pilot.

## Preserve these decisions

- Vibe Coding Toolkit is primary; `vibe-setup` is a secondary reference. Reference upstream procedures without vendoring prompts. Resolve one current revision per new onboarding/update run; resume an interrupted run at its recorded revision.
- Keep instructions concise, skill entry points within 150 words and each wrapper rule in one place.
- Use approved paid subscriptions; preserve the main model and authentication. No local-model or new API-billing default.
- Reuse the selected conflict mode: Decide with me / Preserve my workflow / Replace my workflow. None waives mandatory policy adoption.
- Export release archives only when requested.

## Next checkpoint

Prepare the concrete **D1: Codex adapter and startup hook** implementation plan. Inspect the actual checkout and target client first. Define the smallest event/response contract, project-root resolution, manifest wiring, fixtures and live startup probe. Reuse approved decisions; identify only material unresolved choices. Approval of these two contracts does not approve every proposed runtime detail or PHIOON rollout.

Live plugin-hook qualification needs a supported local-only Work or Codex session. Cloud orchestration does not execute local/plugin hooks even when tools run on the computer. Verify the exact client surface, version and hook trust against [official hook documentation](https://learn.chatgpt.com/docs/hooks). File creation, fixture checks and actual client execution are separate evidence.

## Validation and transfer

Run `python3 -B scripts/validate.py` and `git diff --check`. The validator checks packaging and instruction length; it does not prove runtime enforcement.

The release contains the complete tracked plugin folder, including marketplace metadata. Extract it into the intended checkout, preserving its Git history and unrelated files. Use that checkout's actual path; the prior chat's temporary filesystem is not the destination machine.
