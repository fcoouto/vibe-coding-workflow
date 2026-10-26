# Vibe Coding Workflow

[Vibe Coding Toolkit](https://github.com/soumatheusgomes/vibe-coding-toolkit), packaged for your coding agent.

**Early development.** Codex has opt-in task controls and read-only diagnostics, with bounded CLI and bundled app-server qualification, including a controlled Interrupt case. General turn correlation, desktop UI behavior, and Claude lifecycle remain unqualified. See the [client contracts](clients/index.md) for current scope and [D2 validation](docs/d2-validation.md).

Codex task runtime is opt-in. For accepted checks, general and applicable security review, and completion verification, read the [task runtime](clients/runtime.md) and its selectively loaded [evidence contract](clients/evidence.md). [D5 validation](docs/d5-validation.md) records independent review and actual native execution. Local readiness is evidence for the current content; repository merge enforcement remains a separate D7 gate.

## Prepare your Workspace

Open this checkout in a coding agent with terminal access to the destination machine:

```text
Read skills/prepare-my-workspace/SKILL.md and use it to prepare this machine.
```

For local plugin testing, run `codex plugin marketplace add .` from this checkout, then restart Codex desktop. Select `vibe-coding-workflow-local`, install `vibe-coding-workflow`, and invoke `prepare-my-workspace`, which uses the same instructions. Refresh the installed copy after changes. See [OpenAI's marketplace guide](https://developers.openai.com/plugins/build/plugins#add-a-marketplace-from-the-cli).

For Claude Code local testing, launch `claude --plugin-dir .` from this checkout. See the [Claude Code contract](clients/claude-code.md) for loading and qualification. Superset uses the underlying native adapter; its [host integration](clients/superset.md) requires separate launch qualification.

## Enroll a project

For an explicitly selected existing project, use [onboard-my-project](skills/onboard-my-project/SKILL.md) to inspect and prepare a private enrollment plan. Planning does not change the target. After trusted approval binds the exact plan and application manifest, `onboard apply` makes recoverable changes and activates enrollment only after required adoption evidence qualifies. `onboard resume` reconciles interrupted work; `onboard rollback` restores transaction-owned changes. Each command uses `--plan-dir` and a bounded JSON request on stdin. See [application and recovery](skills/onboard-my-project/references/apply-and-recovery.md). Package validation and adoption evidence do not qualify client execution.

[Development guide](AGENTS.md)
