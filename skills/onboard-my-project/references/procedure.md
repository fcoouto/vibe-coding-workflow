# Existing-project onboarding

Use for an explicitly selected existing project, authorized update, repair or recovery. Basic onboarding inspects relevant instructions/configuration, assesses the complete Toolkit component catalog for relevance, makes authorized changes recoverably, and leaves useful guidance, working project commands, relevant checks, limitations and an undo location. Do not turn it into a whole-file census or client qualification campaign.

## Basic onboarding

Read the [policy index](../../../policies/00-index.md), [Project Scope](../../../policies/01-project-scope.md), [Project Onboarding](../../../policies/10-project-onboarding.md), applicable local instructions and linked policies. For setup authoring, resolve the canonical [Vibe Coding Toolkit](https://github.com/soumatheusgomes/vibe-coding-toolkit) revision once. Assess every component in its complete catalog for relevance, current adoption or an equivalent, and any useful action. Read the component guidance and linked sources needed for the selected work; keep provenance in authoring records, not routine task loading.

1. Confirm the selected checkout and applicable instructions. Keep workspace preparation and new-project creation separate; do not enroll the toolkit checkout just because it is the current working directory.
2. Inspect relevant project configuration, commands and paths. Separate observed facts from assumptions, and preserve user changes, data, permissions, model/provider choices and existing protections.
3. Make only authorized, useful changes. Retain a recoverable private backup before meaningful configuration changes; use the [configuration and undo contract](apply-and-recovery.md#file-configuration-and-undo) for managed file operations. Load detailed procedures only for a selected capability.
4. Run useful project commands and relevant local/client checks. Report what they establish and what remains unknown. Leave the user useful guidance, working commands, limitations and an undo location.

When using packaged file tools for standalone basic setup, select `project_scope.inspection_scope: "relevant"`. This inspects only the project inputs needed for the requested edits: applicable ancestor/directory instructions, selected inputs and targets, their preimages, and the physical target scope. The tools capture planned write/delete/evidence paths; unrelated checkout state and a full file census are outside this partial snapshot. It grants no command execution inside the file transaction, runtime activation or managed authority. Run ordinary project checks natively under existing permission. Keep the Toolkit component-catalog assessment complete even when only selected files are inspected. Explain this as “inspect relevant project files”; do not ask users to select an internal JSON mode.

Basic onboarding is complete when these outputs are usable and authorized changes can be recovered without overwriting later edits. This does not establish AcceptedScope, task readiness, managed runtime activation, qualification, merge readiness or external authority.

## Selected managed planning

Read [managed-plan](managed-plan.md) only when the selected operation uses the canonical managed dispatcher. It defines its pinned source bundle, bounded plan/inventory schemas, review and recovery bindings. Do not use its task-state or qualification prerequisites to block ordinary development. “Managed planning” refers to that dispatcher; standalone file-only authoring may still use packaged file tools without managed runtime, task state or managed authority.

## Selected advanced capabilities

Read the relevant command, runtime, adapter qualification, delivery or external-route procedure only when that capability is selected. Preserve its actual permissions, known-writer ownership, data-loss protections, review and recovery constraints. Adapter qualification campaigns are maintainer validation, not basic project onboarding.
