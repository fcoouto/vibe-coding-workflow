# Vibe Coding Workflow

[Vibe Coding Toolkit](https://github.com/soumatheusgomes/vibe-coding-toolkit), packaged for your coding agent.

**Early development.** The workspace skill and package metadata exist. Project onboarding, automatic activation, runtime and enforcement are not implemented. Installed-client execution is not yet qualified.

## Prepare your Workspace

Open this checkout in a coding agent with terminal access to the destination machine:

```text
Read skills/prepare-my-workspace/SKILL.md and use it to prepare this machine.
```

For local plugin testing, run `codex plugin marketplace add .` from this checkout, then restart Codex desktop. Select `vibe-coding-workflow-local`, install `vibe-coding-workflow`, and invoke `prepare-my-workspace`, which uses the same instructions. Refresh the installed copy after changes. See [OpenAI's marketplace guide](https://developers.openai.com/plugins/build/plugins#add-a-marketplace-from-the-cli).

[Development guide](AGENTS.md)
