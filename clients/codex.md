# Codex

## Startup behavior

Apply the [shared policies](../policies/00-index.md) within the recorded checkout scope. Startup enrollment alone supplies orientation only. Runtime controls require separate opt-in. Only for explicit task controls, a `doctor` report, or lifecycle troubleshooting, read the [Codex task runtime contract](runtime.md). Bounded CLI qualification and bundled core lifecycle checks are recorded; a controlled bundled Interrupt passed while Stop output was held, with general read-first correlation still limited. See [validation details](../docs/d2-validation.md).

Actual Desktop startup orientation and D5 check/review/completion behavior are qualified for the recorded version and disposable scope; see [D5 validation](../docs/d5-validation.md). This does not extend the guard or continuation guarantees above.

The plugin registers one `SessionStart` command through `hooks` in `.codex-plugin/plugin.json`. Read the policy index and applicable contracts when the hook supplies their local paths. Normal activation adds model context without an activation announcement. A warning means orientation failed; resolve the affected integration before claiming workflow readiness.

The [adapter](../runtime/adapters/codex.py) validates session identity, absolute `cwd`, event name and source (`startup`, `resume`, `clear`, `compact`, `fork`). Supplied model and permission mode remain observations; absent values, client version and UI surface remain unknown. The [shared startup code](../runtime/startup.py) resolves the nearest Git checkout and common Git directory. Parent and neighboring enrollment never extends scope.

No enrollment produces no output. Each lifecycle event can reload context after resume, fork or compaction; it does not run on every tool call. D1 has no persistent event deduplication because the native event supplies no unique invocation ID.

## Startup implementation

Read the [shared startup contract](startup.md) when implementing, diagnosing or preparing enrollment. It defines the record format, runtime limits and package/fixture checks.

Codex 0.163.0 and desktop-bundled 0.164.0-alpha.11.1 discover these hooks only with the compatibility manifest. A root `plugin.json` suppresses discovery in both tested builds, including with a compatibility overlay. Requalify before changing that packaging.

Package validation and fixture tests establish package behavior only. They do not establish native execution or qualification.

For client qualification, install the reviewed package into a disposable Codex environment, inspect its exact definition with `/hooks` or `hooks/list`, trust that definition, and observe startup in an enrolled fixture and an unrelated repository. Verify changed/untrusted definitions remain skipped. Record the executable version, surface, package digest and observed output. CLI or app-server evidence does not establish desktop UI behavior or an agent's policy compliance.

The [official hook contract](https://learn.chatgpt.com/docs/hooks) defines payloads and trust; [plugin packaging](https://developers.openai.com/plugins/build/plugins#hooks) defines registration and `PLUGIN_ROOT`. Installing the plugin does not grant hook trust.
