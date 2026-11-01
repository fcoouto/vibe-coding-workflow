# Workstreams dispatch and continuation protocol

Load before preparing or sending a managed worker dispatch or continuation.
For context planning, ownership, naming and acceptance, use the
[execution contract](workstreams.md). This file owns execution request fields and
one-use delivery mechanics; it is unnecessary for management-only requests.

Use the installed package's `scripts/workflow.py delegation workstreams ACTION --cwd CHECKOUT`
with one JSON object on stdin. Management actions are defined in the
[management procedure](../skills/workstreams/references/procedure.md).
Execution mutations carry the existing task identity (`client`, `session_id`,
`task_id`, `scope_ref`, `expected_revision`) and the exact `attempt_id`.
Use current revisions returned by the runtime; a conflict requires reconciliation.
Preparation returns the token, revision, child binding and remaining allowance
without repeating the prompt. Send-admitted consumption returns the exact stored
prompt for delivery. `record-continuation` returns a delivery acknowledgment
without repeating that prompt; private continuation evidence remains complete.

Workstream worker `delegation prepare` adds `workstream_revision` and `workstream_limits` together.
The latter records `context_id`, `rationale`, `output_tokens`, `context_tokens`,
`max_steps`, `max_seconds`, `max_continuations` and `backoff_seconds`. Choose values
for the assignment. These native allocations are admission records, not hard
execution or billing controls. Ordinary prepare omits the pair.

| Action | Additional request fields and effect |
| --- | --- |
| `consume-dispatch` | `workstream_revision`; consume the existing attempt's send permission against current enablement immediately before one native spawn. |
| `prepare-continuation` | `workstream_revision`, `reason` (`follow-up`, `review-fixes`, `transient`), `prompt`, `human_continue`, `host_proof`; optional `retry_at` epoch. Bind a pending intent to the existing child and current evidence. |
| `consume-continuation` | `workstream_revision`, returned `token`; consume that intent immediately before one native follow-up to the bound child. |
| `record-continuation` | Returned `token`, `delivery` (`sent` or `uncertain`), `delivery_ref`; retain the coordinator's delivery assertion for subsequent independent observation. |

`host_proof` is the existing private D6 stopped-writer proof `{path,sha256}`;
follow [native reconciliation](delegation.md) for its exact bindings and trusted
inspection. A delivery assertion cannot prove that a native tool executed or all
writers stopped. Do not resend on replay, a lost response or an uncertain result.
Use new observed native turns and D6 reconciliation to assess the actual outcome.
After a lost delivery record, human continuation requires a different observed
turn on the same child and fresh exact stopped-writer proof; never resend the old
consumed intent merely because its acknowledgment is missing.


## Immutable native names

For family `W42`, use worker `workstream_limits.context_id:"WS42.01"` or review
`workstream_context_id:"WS42.03"`. The adapter derives
`worker_ws42_01_build_<attempt>` or `review_ws42_03_review_<attempt>` from those
immutable requests, retaining the complete attempt suffix and native lineage.
Ordinary delegation keeps its original markers. Review grouping remains available
when mode is off. Context IDs are `WS` plus alphanumerics, a dot and a positive
decimal ordinal; use short labels to fit the validated 64-character creation marker.
Never truncate identity or use a display title as native lineage.
