# Superset

Read this when launching or qualifying the workflow inside Superset. Superset hosts native agents; it has no independently qualified `SessionStart` protocol for this plugin. Use the [Codex](codex.md) or [Claude Code](claude-code.md) adapter for the agent actually running.

Install the plugin through that native client's supported mechanism. Enroll the native client and exact checkout through the [shared startup contract](startup.md). `SUPERSET_WORKSPACE_ID`, `SUPERSET_WORKSPACE_PATH`, `SUPERSET_ROOT_PATH` and `SUPERSET_TERMINAL_ID` are context hints, never enrollment authority. Superset workspace setup scripts do not replace per-session startup hooks.

Preserve Superset's existing status hooks and the user's model, provider, account and permission choices. Connector availability does not establish model-routing or lifecycle-hook support.

## Qualification boundary

Installed Superset 1.40.0 has no `plugins` CLI command. Its bundled Codex wrapper adds a hook-trust bypass; default agent commands also contain permission bypasses. Do not reproduce these flags in this plugin or claim that this launch path preserves normal native trust. No real Superset launch has been qualified.

Before activation is considered qualified in Superset, inspect the selected launch path and final arguments, resolve permission/trust differences under the user's existing choices, and observe native hook execution in a disposable workspace. Backend CLI evidence alone is insufficient. A newer Superset release or a different launch configuration needs fresh observations.

References: [agent integration](https://docs.superset.sh/add-agent-support), [plugin capabilities](https://docs.superset.sh/plugins/overview), [environment controls](https://docs.superset.sh/cli/env-vars).
