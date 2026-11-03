# Codex

## Startup behavior

Apply the [shared policies](../policies/00-index.md) within the recorded checkout scope. Startup enrollment alone supplies orientation only. Runtime controls require separate opt-in. Only for explicit task controls, a `doctor` report, or lifecycle troubleshooting, read the [Codex task runtime contract](runtime.md). Bounded CLI qualification and bundled core lifecycle checks are recorded; a controlled bundled Interrupt passed while Stop output was held, with general read-first correlation still limited. See [validation details](../docs/d2-validation.md).

Actual Desktop startup orientation and D5 check/review/completion behavior are qualified for the recorded version and disposable scope; see [D5 validation](../docs/d5-validation.md). This does not extend the guard or continuation guarantees above.

The plugin registers one `SessionStart` command through `hooks` in `.codex-plugin/plugin.json`. Read the policy index and applicable contracts when the hook supplies their local paths. Normal activation adds model context without an activation announcement. A warning means orientation did not load; report that limitation and resolve it before claiming this startup integration works. It does not by itself block native editing, tests or review.

The [adapter](../runtime/adapters/codex.py) validates session identity, absolute `cwd`, event name and source (`startup`, `resume`, `clear`, `compact`, `fork`). Supplied model and permission mode remain observations; absent values, client version and UI surface remain unknown. The [shared startup code](../runtime/startup.py) resolves the nearest Git checkout and common Git directory. Parent and neighboring enrollment never extends scope.

No enrollment produces no output. Each lifecycle event can reload context after resume, fork or compaction; it does not run on every tool call. D1 has no persistent event deduplication because the native event supplies no unique invocation ID.

Ordinary Codex editing, tests, review and handoffs use the native workflow; they
need no runtime database, mandatory task-state transition or default patch
blocker. Load task-runtime and qualification procedures only when managed task
controls are explicitly selected. Their failure must not disable status,
configuration recovery or file undo. Preserve selected controls and existing
repository protections.

## Instruction output budgets

Keep instruction reads within the complete outer tool response budget. Child output limits do not raise that shared limit. With `functions.exec`, set a supported outer `max_output_tokens` budget covering the selected child limits and response wrappers, or use smaller, separate batches. Keep large diagnostics, diffs and third-party guides out of a batch already filling that budget.

Required procedures must arrive completely. When a response is truncated, retain the complete material already received and recover only missing files or sections before proceeding. Required review, freshness checks and context recovery still apply.

## Startup implementation

Read [startup implementation and qualification](codex-startup-implementation.md) when implementing or diagnosing startup, preparing enrollment, qualifying a client adapter, or changing hook registration, trust or packaging.
