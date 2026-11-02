# Background worker pilot

Use only within explicit OpenRouter authorization. This pilot supports read-only
investigation over copied UTF-8 files. OpenCode owns the external tool loop; Codex
owns original files, integration and acceptance. The original proposal route remains
separate. Its successful tests do not qualify tool use or autonomous editing.

An explicitly requested [LLM Council](../../llm-council/SKILL.md) uses its own saved route,
snapshot limits, endpoint-aware allowances and three-phase procedure. Load that
procedure instead of this ordinary pilot's prepare/run instructions; do not apply
its one-supervisor, 16-file, 1–8-step, 300-second or 2048-output defaults to Council.
Council reuses this executor's retry ownership and native verification mechanics;
it does not enable or alter the ordinary pilot route.

## Prepare

Read `scripts/openrouter.py status --cwd <selected-checkout>` with `{}` on stdin.
Require saved enablement, selected route `workers` and ready local configuration.
Use exactly its `worker_root`, `opencode` and `auth_data` references. Requested
control changes belong to `../../manage-openrouter/SKILL.md`; ordinary delegation
does not load that procedure or activate a route. An account connection, copied
cache or an `approval_ref` alone does not replace saved checkout consent.

1. Follow the project's native worker selection and declaration contract. Reserve
   the private run directory and give a genuine native supervisor the assignment,
   exact runner/runtime paths, role, specialty, copied inputs, checks and stop rule.
   Keep its native model identity truthful. Use `Task (via Model Display Name)` in
   progress details; the native card represents the supervisor, not OpenRouter.
2. Load only the discovery/cache and triage sections of
   `../../openrouter-proposals/references/procedure.md`. Use the status response's
   `proposal_store` as the shared metadata cache even when `proposals` is disabled;
   workers require only their own route. Refresh only under those cache rules.
   Require endpoint tool support and compatible
   effort. Benchmarks guide selection; independently qualify actual agent behavior.
   Do not call the proposal route's `begin`/`record` for a multi-step agent run.
3. Use a separately installed, pinned OpenCode 1.19.5. The runner never installs it.
   Authenticate OpenRouter through OpenCode's own login with the same private
   `XDG_DATA_HOME` passed as `--auth-data`. Never extract or repurpose MCP credentials.
   Do not paste keys in chat, briefs or arguments. Keep auth and state owner-only.
4. OpenRouter enforces spending limits. No credit preflight is required; optional
   balance inspection cannot establish the separate OpenCode key's allowance.
   Warm cached discovery does not require a fresh MCP call. Use one supervisor/run
   at a time during this pilot and follow retry ownership below.

The runner disables OpenCode's background catalog fetch. The workflow's discovery
cache remains the selection source; the pinned client uses its bundled catalog and
explicit model configuration.

## Run

Invoke the packaged runner using Python 3.11+ on POSIX with Git available, and feed
one JSON brief on stdin:

```text
python3 -I -B <plugin-root>/scripts/openrouter_workers.py run
  --root <saved-worker-root>
  --opencode <saved-pinned-executable>
  --auth-data <saved-opencode-data-directory>
```

The brief contains exactly `task_id`, `role`, `specialty`, `coordinator_chat_id`,
`model`, `model_display_name`, `provider`, `effort`, `objective`, `source_root`,
`files`, `timeout_seconds`, `steps`, and `approval_ref`. Use the actual
root coordinator chat UUID for the Habblaud parent; retain the genuine native
supervisor UUID separately in evidence. This keeps both workers visible in consumers
whose sidebar does not render nested children. Do not invent a native identity. Model is an
OpenRouter author/slug; provider is the selected endpoint routing slug. File names
are nonhidden relative paths under the canonical source root, without symlinks.
Explicitly inspect the selected files for secrets before approving transmission.
Legacy optional `credit` is ignored and discarded. Choose 1–8 steps and 1–300 seconds. The runner currently caps
requested output at 2048 tokens per model response. These controls do not set money
limits, and API requests already in flight may still be billed after cancellation.

The runner copies at most 16 files, each at most 128 KiB, into its private workspace
and initializes an empty private Git repository there. OpenCode's read permissions
match worktree-relative filenames; without Git it may resolve the worktree to `/`.
Preparation saves the consent scope and revision but does not admit external
execution. Immediately before process creation, the runner rechecks enablement,
selected route, scope, revision and configured runtime paths under the shared
short guard. Disable after preparation blocks launch; re-enable does not revive
stale preparation. Already-launched workers keep their original deadline and may
finish and receive native verification after disable. Historical status and
verification never require re-enabling. Disable does not revoke the account key.
Canonical filenames cannot contain wildcard characters. Git is a runtime prerequisite;
initialization uses no global configuration or templates and creates no commit.
It denies shell, edits, network tools, external directories and nested agents through
OpenCode permissions. This is application-level restriction, not an OS sandbox.
Use only reviewed test inputs until the pinned runtime's permission behavior is
qualified. A run ID cannot be reused, even after failure. State must stay outside
repositories and plugin installations. Do not rerun under another ID to conceal an
unresolved attempt. Background execution uses the host's normal process facility;
the supervisor remains responsible for collecting its final result.

## Shared tool-output boundary

The shared executor also denies the exact canonical selected data directory's
`opencode/tool-output/*` exception, preventing prior-run cached tool output from
escaping the copied-input boundary. It denies rereading this run's truncated cache
too; use narrower reads of approved files. This shared security correction changes
no ordinary pilot resource defaults, credentials or authentication choice.

## Retry ownership and native recovery

OpenCode owns transient request retries within the original worker deadline.
Pinned 1.19.5 permits up to five retries per failing processor stream, not per
whole worker. The deadline covers all retries and waits and may expire first.
Never add an outer retry loop, restart the worker, switch providers/models, or
invent another run ID after exhaustion. Keep the qualified pinned route.

`result.json` retains `failure`: null or a bounded summary with controlled
`category` and optional observed `status_code`, recognized `limit_source`, and
`retry_after_seconds`. These are terminal observations, not an upstream retry
count or permission to retry. Raw provider messages, headers and bodies are not
retained in this summary. Generic 402 does not prove zero balance; known budget
403 remains distinct from permission 403. Capacity and service failures are
availability observations, not evidence of model-quality failure.

On terminal failure, give one concise warning and use native execution only after
the supervisor confirms owned local execution stopped. `local_execution_stopped`
reports process-group absence; `native_fallback_ready` indicates a failed,
unresolved or natively rejected result with that observation. These local reports
do not authenticate approval or replace the supervisor's trusted host evidence.
If stop cannot be confirmed, retain unresolved ownership and reconcile it first.
Unknown upstream cancellation or billing does not prevent independent native work
once local quiescence is confirmed. Preserve partial results and known accounting;
independently establish any finding reused during takeover.

The current JSON CLI does not forward OpenCode's internal retry status. Report
only observed events or presence; never claim an exact retry number, countdown,
or five exhausted retries from silence or a generic terminal error. OpenCode can
internally retry some quota-like errors through its broad classifier; the wrapper
usually learns their cause only at termination. Do not duplicate that classifier.

## Visibility

Add `--visibility-plugin <trusted-installed-local-model-delegation-root>`,
`--habblaud-endpoint <literal-loopback-HTTP-url>`, and
`--habblaud-account <observed-Codex-account-id>` to reuse the installed transport.
This pilot was developed against Local Model Delegation 0.3.16; it imports its
`Client` and event formatter. Requalify this private interface after plugin upgrades.
Do not mutate that plugin's job database or fabricate Codex transcripts.

Use completion events or bounded process waits, then `scripts/openrouter_workers.py status --root <saved-worker-root> --compact` with `{"task_id":"<run-id>"}` on stdin for compact recorded progress. Omit `--compact` to retrieve the response/accounting when verification or diagnostics need it. Compact status includes sanitized failure facts, nullable stop observations and a path/SHA-256 reference to the bytes read; it never rewrites `result.json`. A response being available does not prove a complete or accepted report, current liveness or stopped ownership. If the saved result changes before verification, inspect the current result and use its actual binding.

Read `progress.jsonl` for a specific observed-event diagnostic and `visibility.json` for delivery receipts. The current CLI
emits tool events at completion/error; while a tool is running, report only that
the worker is active. A heartbeat is presence, not evidence of progress. Forward
events through native supervisor commentary. Do not imply exact native-card parity.

Habblaud displays `Role · Model Display Name`, but retains Codex account/provider
association. Its Stats model/token fields are not populated by these hooks. Failure
or interruption may look like completion; the runner's state remains authoritative.
No prompts, raw tool results, credentials or model reasoning enter Habblaud events.
Habblaud delivery failure does not change task acceptance. Display entries can affect
native counts and World projection, as in the existing local-worker adapter.

## Verify and stop

Only `awaiting_verification` is eligible for native acceptance. Independently inspect
the returned answer against the original input and predeclared checks. For the live
agent canary, require at least one successful permitted tool call and an observed
Habblaud child, plus the genuine supervisor's observed native identity. Record failed
or missing outcomes separately. Never use the worker's self-report as proof.

Call `verify` with the same root and JSON containing `task_id`, `disposition`
(`accepted` or `rejected`) and nonempty native `checks`. Supply the same visibility
arguments to publish the final outcome. These receipts record the supervisor's
claims; the helper cannot independently attest verification. `status` reads an
existing run with `{ "task_id": "..." }` and starts no work.

Reported cost/tokens come from OpenCode step-finish events, not native usage or an
independent OpenRouter billing reconciliation. Live qualification found that OpenCode's
reported costs differed from provider charges. Prefer OpenRouter's actual usage for
billing; retain any account/key delta's concurrent-use attribution limits. A missing
step cost leaves the complete reported total unknown and preserves a known subtotal.
Preserve unknown accounting and
requested-versus-observed model/provider/effort differences. Reject unsupported
event streams. On timeout, interruption or uncertain execution, report `unresolved`,
confirm the owned local process stopped, and never assume upstream cancellation.
Apply the local-stop and native-recovery rules above; unsettled billing remains
unknown rather than becoming an automatic worker replay or a zero-cost claim.

Package tests, fixture processes, actual OpenCode tool execution, Habblaud rendering
and genuine native dispatch are separate evidence classes. Do not publish or enable
this pilot globally on the strength of package validation alone.
