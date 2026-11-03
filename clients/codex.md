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

Use `python3 -I -B <package>/scripts/read_instructions.py --batch <paths>` for Vibe instructions; paths are package-relative (`policies/02-task-planning.md`). Select triggered files and follow every continuation before relying on a contract. Return each batch alone. If a batch clips, retain complete text and omit `--batch` to recover missing pages with the same selection and revision, or use bounded native reads of missing sections. On reader failure, report the limitation and use bounded native source reads. Never run `--prepare` during routine tasks.

Size each child instruction read for its complete selected files or sections. With `functions.exec`, use supported child `max_output_tokens` limits and an outer `max_output_tokens` budget covering their sum plus response wrappers. A larger outer budget cannot restore child-truncated text. Use available size information without adding a sizing command to every read; split large or uncertain reads into smaller, contiguous sections. Keep large diagnostics, diffs and third-party guides separate when they would exhaust either budget.

Required procedures must arrive completely. Requested limits may be capped; inspect both child and outer results for truncation or omitted text. Success exit codes, summaries and previews do not establish completeness. Retain complete material already received and recover only missing files or sections before proceeding, adjusting the limit or selection at the layer that omitted them. Required review, freshness checks and context recovery still apply.

In enrolled checkouts, the existing `PostToolUse` hook surfaces the observed child-truncation marker as a short recovery notice. The notice is advisory: stdout can imitate the marker. It does not replace completed output, run recovery commands or observe later outer clipping. Normal results remain silent.

## Startup implementation

Read [startup implementation and qualification](codex-startup-implementation.md) when implementing or diagnosing startup, preparing enrollment, qualifying a client adapter, or changing hook registration, trust or packaging.
