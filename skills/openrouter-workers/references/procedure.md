# Background worker pilot

Use only within explicit OpenRouter authorization. This pilot supports read-only
investigation over copied UTF-8 files. OpenCode owns the external tool loop; Codex
owns original files, integration and acceptance. The original proposal route remains
separate. Its successful tests do not qualify tool use or autonomous editing.

## Prepare

1. Follow the project's native worker selection and declaration contract. Reserve
   the private run directory and give a genuine native supervisor the assignment,
   exact runner/runtime paths, role, specialty, copied inputs, checks and stop rule.
   Keep its native model identity truthful. Use `Task (via Model Display Name)` in
   progress details; the native card represents the supervisor, not OpenRouter.
2. Reuse discovery/triage from `../../openrouter-proposals/references/procedure.md`;
   refresh only under its cache rules. Require endpoint tool support and compatible
   effort. Benchmarks guide selection; independently qualify actual agent behavior.
   Do not call the proposal route's `begin`/`record` for a multi-step agent run.
3. Use a separately installed, pinned OpenCode 1.19.5. The runner never installs it.
   Authenticate OpenRouter through OpenCode's own login with the same private
   `XDG_DATA_HOME` passed as `--auth-data`. Never extract or repurpose MCP credentials.
   Do not paste keys in chat, briefs or arguments. Keep auth and state owner-only.
4. Obtain fresh `get-credits` evidence through the authorized OpenRouter MCP. Store
   observed time and remaining account credit in the brief. OpenRouter manages
   spending limits; this is not a reservation or proof of the separate key's limit.
   Use one supervisor/run at a time during this pilot. No automatic paid retries.

## Run

Invoke the packaged runner using Python 3.11+ on POSIX with Git available, and feed
one JSON brief on stdin:

```text
python3 -I -B <plugin-root>/scripts/openrouter_workers.py run
  --root <private-canonical-runs-directory>
  --opencode <absolute-pinned-executable>
  --auth-data <private-opencode-data-directory>
```

The brief contains exactly `task_id`, `role`, `specialty`, `coordinator_chat_id`,
`model`, `model_display_name`, `provider`, `effort`, `objective`, `source_root`,
`files`, `timeout_seconds`, `steps`, `credit`, and `approval_ref`. Use the actual
root coordinator chat UUID for the Habblaud parent; retain the genuine native
supervisor UUID separately in evidence. This keeps both workers visible in consumers
whose sidebar does not render nested children. Do not invent a native identity. Model is an
OpenRouter author/slug; provider is the selected endpoint routing slug. File names
are nonhidden relative paths under the canonical source root, without symlinks.
Explicitly inspect the selected files for secrets before approving transmission.
Credit is `{ "observed_at": <Unix seconds>, "remaining": <USD> }` from a lookup
within 60 seconds. Choose 1–8 steps and 1–300 seconds. The runner currently caps
requested output at 2048 tokens per model response. These controls do not set money
limits, and API requests already in flight may still be billed after cancellation.

The runner copies at most 16 files, each at most 128 KiB, into its private workspace
and initializes an empty private Git repository there. OpenCode's read permissions
match worktree-relative filenames; without Git it may resolve the worktree to `/`.
Canonical filenames cannot contain wildcard characters. Git is a runtime prerequisite;
initialization uses no global configuration or templates and creates no commit.
It denies shell, edits, network tools, external directories and nested agents through
OpenCode permissions. This is application-level restriction, not an OS sandbox.
Use only reviewed test inputs until the pinned runtime's permission behavior is
qualified. A run ID cannot be reused, even after failure. State must stay outside
repositories and plugin installations. Do not rerun under another ID to conceal an
unresolved attempt. Background execution uses the host's normal process facility;
the supervisor remains responsible for collecting its final result.

## Visibility

Add `--visibility-plugin <trusted-installed-local-model-delegation-root>`,
`--habblaud-endpoint <literal-loopback-HTTP-url>`, and
`--habblaud-account <observed-Codex-account-id>` to reuse the installed transport.
This pilot was developed against Local Model Delegation 0.3.16; it imports its
`Client` and event formatter. Requalify this private interface after plugin upgrades.
Do not mutate that plugin's job database or fabricate Codex transcripts.

Read `progress.jsonl` for sanitized observed events, `result.json` for the private
response/accounting, and `visibility.json` for delivery receipts. The current CLI
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
Native fallback stays with the coordinator until uncertain execution is settled.

Package tests, fixture processes, actual OpenCode tool execution, Habblaud rendering
and genuine native dispatch are separate evidence classes. Do not publish or enable
this pilot globally on the strength of package validation alone.
