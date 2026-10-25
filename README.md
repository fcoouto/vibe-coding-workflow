# Vibe Coding Workflow

[Vibe Coding Toolkit](https://github.com/soumatheusgomes/vibe-coding-toolkit), packaged for your coding agent.

**Early development.** Codex has opt-in task controls and read-only diagnostics, with bounded CLI and bundled app-server qualification, including a controlled Interrupt case. General turn correlation, desktop UI behavior, and Claude lifecycle remain unqualified. See the [client contracts](clients/index.md) for current scope and [D2 validation](docs/d2-validation.md).

## Prepare your Workspace

Open this checkout in a coding agent with terminal access to the destination machine:

```text
Read skills/prepare-my-workspace/SKILL.md and use it to prepare this machine.
```

For local plugin testing, run `codex plugin marketplace add .` from this checkout, then restart Codex desktop. Select `vibe-coding-workflow-local`, install `vibe-coding-workflow`, and invoke `prepare-my-workspace`, which uses the same instructions. Refresh the installed copy after changes. See [OpenAI's marketplace guide](https://developers.openai.com/plugins/build/plugins#add-a-marketplace-from-the-cli).

For Claude Code local testing, launch `claude --plugin-dir .` from this checkout. See the [Claude Code contract](clients/claude-code.md) for loading and qualification. Superset uses the underlying native adapter; its [host integration](clients/superset.md) requires separate launch qualification.

[Development guide](AGENTS.md)
