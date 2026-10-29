# OpenCode retry ownership and native recovery

Status: approved by the user on 2026-10-29; implementation and qualification follow
the linked [implementation plan](../plans/2026-10-29-opencode-retry-recovery.md).

## Intent and selected approach

Reuse the retry mechanism in the qualified OpenCode runtime. Do not add a worker
restart loop after that mechanism fails. The user reconsidered the earlier
three-retry proposal after learning that pinned OpenCode already retries failing
requests. This design follows that direction and keeps Codex responsible for
terminal recovery, original files, verification, and integration.

The smallest change is a retry-aware recovery adapter around one OpenCode run.
It does not replace OpenCode's classifier, backoff, or retry count. It introduces
no scheduler, monetary limits, provider registry, runtime fork, or background probe.

## Observed upstream behavior

The following observations concern official source and tests at tag `v1.19.5`,
checked on 2026-10-29. Source inspection is not a live provider execution test.

- `session/retry.ts` permits five retries after the initial failing execution.
  Eligibility includes the SDK retryable flag, server status codes of at least
  500, and recognized rate-limit, overload, capacity, connection, and timeout text.
  This is not a strict HTTP-status allowlist. Context overflow is excluded.
- Backoff begins at two seconds, doubles, and adds up to 25% positive jitter.
  `retry-after-ms` takes precedence over `retry-after`, which supports seconds and
  HTTP dates. The 30-second cap applies when response headers are absent;
  header-directed waits can be longer.
- `session/processor.ts` installs the schedule around each processor stream
  execution. Five retries is not a whole-worker request budget. Later assistant
  steps can have their own retries. Terminal failures publish a session error.
- The default AI SDK dispatch supplies zero SDK retries unless explicitly
  overridden. This does not establish every provider's internal attempt count.
- The noninteractive JSON CLI forwards session errors but does not forward retry
  status updates. Silence does not establish that a retry occurred or was exhausted.

Sources:

- https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/session/retry.ts
- https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/test/session/retry.test.ts
- https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/session/processor.ts
- https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/session/llm.ts
- https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/cli/cmd/run.ts

## Ownership and behavior

OpenCode owns transient request retries within the single launched worker. The
existing runner deadline continues across retries, waits, and tool steps; no event
resets it. The deadline may stop the worker before all five retries occur. Report
that outcome as a deadline, not as exhausted retries.

| Observed outcome | Plugin and native coordinator behavior |
| --- | --- |
| Worker is active | Allow OpenCode to recover within the original deadline and read-only permissions. Do not start another worker. |
| Terminal capacity, rate, or service failure | Retain the structured cause, stop and reconcile owned local execution, then continue natively. Do not restart the same route. |
| Terminal budget, authentication, permission, or invalid-input failure | Give one concise reason and continue natively after local quiescence. Do not infer zero balance from a generic 402. |
| Deadline, interruption, malformed output, or lost process evidence | Preserve an unresolved outcome and known usage. Establish local quiescence before takeover; uncertain upstream billing remains separately unresolved. |
| Completed usable response | Independently verify it against the original inputs and task checks. A rejected solution does not enter a transport retry loop. |

Capacity and transport failures are availability observations, not model-quality
failures. Do not globally disqualify a model because one route failed.

The qualified pilot retains its pinned model/provider and disabled provider fallback.
After exhaustion, native takeover is the default. Automatic model/provider cascades
would create additional retry loops and require a separate, bounded routing design.
A later task may select a different already-approved, compatible route using cached
triage; it must not disguise a replay of the original task.

This policy applies to OpenCode workers. The one-shot MCP proposal executor does
not inherit OpenCode's retry behavior and must not claim that it does.

## Minimal implementation

Update `scripts/openrouter_workers.py` to retain a bounded, allowlisted terminal
failure summary instead of dropping the error payload into a generic flag. Useful
facts include the observed HTTP status, recognized machine category or limit source,
and valid retry timing when supplied. Treat payloads as untrusted data. Do not
persist raw response bodies, arbitrary headers, provider messages, or stderr for
classification. Missing evidence remains unknown.

Retain the existing single execution identity, cleanup, result states, independent
native acceptance, and private accounting. Add no retry-count field pretending to
measure events that the CLI does not expose. A terminal error alone does not prove
that OpenCode used all five retries.

Update the worker procedure to describe upstream retry ownership and terminal
native takeover accurately. Local quiescence is required; settlement of uncertain
upstream billing is not required before independent native work on original inputs.
Preserve known cost subtotals and incomplete-accounting flags across failures.

Removing mandatory credit preflights remains an agreed companion simplification.
OpenRouter owns spending enforcement. It must be updated consistently in both
executors and their contracts; a fresh balance lookup is not a retry prerequisite.
Management enablement and observability exports remain separate work.

## Verification

Use the existing fixture-process tests to cover terminal structured API errors,
budget versus permission failures, unknown or malformed error payloads, preserved
partial usage, deadlines, and child-process cleanup. Assert one OpenCode process
launch per run and no outer replay. Ensure private sentinel messages never enter
progress or the retained failure summary. Keep successful responses awaiting native
verification.

Run the affected tests and package validator. Observe client recovery separately
with an authorized controlled failure; do not claim that a fixture is an actual
OpenRouter rejection or deliberately exhaust account credits.

## Alternatives and remaining limits

- An outer three-retry worker loop was considered and rejected: it duplicates
  upstream recovery and can repeat completed work or multiply requests.
- Replacing OpenCode's retry policy was considered and rejected for this slice:
  no qualified control is established, and a runtime fork would add maintenance.
- Exact retry counts and countdowns require a separately qualified OpenCode
  session-status interface. Until then, progress reports only observed events.

OpenCode's broad classifier can internally retry some misleadingly worded errors.
The wrapper generally sees their structured cause only at termination. Retaining
the existing deadline bounds the worker without claiming an immediate stop for
every budget error. Partial streams and internal retries can incur charges even
when the final task falls back to native execution. Application-level read-only
permissions do not constitute an operating-system sandbox.
