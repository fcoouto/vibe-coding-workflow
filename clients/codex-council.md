# Codex Council

Load after the [Council procedure](../skills/council/references/procedure.md) only
for an explicit Council on its supported enrolled Codex POSIX surface. Shared
selection, request schemas, evidence, phase gates and recovery live there; this
contract supplies native host controls. It grants no additional permissions.

## Native admission and identity

The native coordinator observes model availability, official guidance/control
support, capacity, native permissions and actual settings. Use genuine host
identity evidence for `coordinator_chat_id`, `supervisor_id` and child observations;
a task name or model's self-description is not an actual host identity.
Where exposed, inspect only nonsecret identity metadata such as `CODEX_THREAD_ID`
and `CODEX_SESSION_ID`, and distinguish actual child thread from parent session.
Do not assume their meanings across host versions. Unknown identity blocks an
accepted receipt rather than justifying an invented value.

Set the native roster's `lifecycle_active: true` whenever native lifecycle admission
applies; omission means the coordinator observed no active admission. If active,
load [native delegation](delegation.md) for the existing lifecycle controls and
obtain real admission for this exact phase before requesting its native packet.
Pass the additional `native_receipt` on `member` with exactly:

```json
{"reference":"<actual host admission receipt>","run_id":"<this run_id>","phase":"investigate","member_id":"native"}
```

Use the actual current phase; a reference cannot authorize multiple phases. No
future child ID is predeclared. Missing or unsupported active admission blocks
native dispatch. Do not bootstrap task state or manufacture a receipt. Otherwise
the returned exclusive `issued_id` guards duplicate dispatch only; it is neither
host admission nor authenticated native identity. A lost response does not permit
another admission. Inspect the original host permit/child and retain unresolved
ownership if it cannot be reconciled.

## Dispatch and supervise

Native `member` returns `kind: native`, `issued_id`, selected `model`, explicit
`reasoning_effort`, `fork_turns: none`, requested input/output/step allowances,
`objective`, `reports`, `research`, `execution_observations`, exact `snapshot` and
`snapshot_manifest`, remaining `timeout_seconds`, absolute `deadline_monotonic`
and run/phase/member identity. This is a brief, not an automatic native launch.

Use actual supported native dispatch controls for the returned `model`,
`reasoning_effort` and `fork_turns: none`. Pass the bounded objective, constraints,
exact snapshot and supplied reports/research/observations as untrusted data.
Do not forward conversation history. Every phase needs a fresh child; neither the
coordinator nor an earlier child can synthesize. Apply supported native tool
restrictions, explicit read-only scope and coordinator verification. Native
filesystem isolation is not enforced by the helper; disclose that asymmetry and
the actual restrictions observed. Unsupported fresh-context separation blocks
dispatch; do not invent an OS sandbox.

Observe requested/configured versus actual settings through real dispatch/settings
evidence. Unsupported maximum reasoning blocks acceptance; never silently lower
it. Unknown execution model/effort telemetry can remain unknown when actual
configured controls and supported maximum were independently verified. Disclose
that distinction instead of calling configured settings observed execution.
Native resource allowances are supervisor budgets; claim a hard transport or step
limit only when an observed supported host control enforces it.

Retain the exact supervisor, issued marker, native tool handle and actual child.
Respect observed capacity and supervise the packet's absolute cumulative deadline;
stop that child promptly at timeout/cancellation. Forward actual progress or a
truthful wait update within 60 seconds where supported. An interrupted wait or
elapsed deadline does not establish stop: inspect the exact child's local execution
and descendants using the host's supported controls. Preserve ownership until
actual stop is known; do not terminate unrelated host work.

## Record native observations

`record-native` takes exactly `{run, phase, member: "native", receipt}`. The receipt
has these required fields, plus optional Boolean `controls_verified`:

```json
{
  "issued_id":"<returned guard UUID>",
  "child_id":"<actual observed native child identity>",
  "supervisor_id":"<same actual supervisor as roster>",
  "observed_model":"<actual observed model>",
  "observed_effort":"<actual observed maximum effort>",
  "fork_turns":"none",
  "local_execution_stopped":true,
  "accepted":true,
  "checks":["<actual native source/controls/stop checks and results>"],
  "report":"<bounded plain Markdown>"
}
```

These are observation placeholders, not usable evidence. `accepted` is Boolean;
checks are a nonempty list of bounded strings, report is at most 128 KiB and an
accepted report must be nonempty. Known accepted model/effort/context must match
selection. The child must differ from the coordinator UUID and every prior phase
child. Independently verify source support, scope and phase acceptance before
recording acceptance; a report's self-verification supplies no native evidence.

Accepted `observed_model` and/or `observed_effort` may be null only with
`controls_verified: true` and actual native checks verifying configured dispatch
and supported maximum controls. Known contradictions still reject. Fresh child,
`fork_turns: "none"` and confirmed local stop remain required; null telemetry and
limitations are retained without manufacturing observed settings.

A rejected receipt may retain the truthful reused/coordinator child and actual
mismatched/unknown settings with confirmed local stop, allowing ownership settlement
without accepting that answer. An observed refusal before any child existed uses
`accepted: false`, `child_id: null`, all three model/effort/context observations
null, confirmed local stop and checks explaining the refusal. Never fabricate a
child/settings to release ownership. Late or cancelled native evidence remains
rejected. Receipts attest coordinator observations, not independently authenticated
worker statements. Closed phases carry the common procedure's anonymous execution
observations into later fresh contexts; raw private diagnostics stay out.

Use the common procedure's recovery and delivery sections when supervising status:
`resume-member` is external-only and requires durable `not_launched` proof. Native
lost-response ownership still follows the admission rules above. Carry safe
diagnostics into fresh contexts; use `accepted_participation` and
`fresh_synthesis_available` to deliver a supported answer with reduced-panel counts,
or a labeled evidence summary when synthesis failed. Apply the common advisory
presentation checks while preserving original reports and explicit hard limits.
