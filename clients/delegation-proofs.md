# Reconciliation proof fields

Load only for independently reconciling an admitted operation. These schemas
describe bindings; they do not establish that a process or its descendants stopped.
Retain the actual independent host observation. Write its JSON to a private,
absolute, nonsymlink path outside repositories and installed package/cache trees;
submit its exact SHA-256 through `host_proof`. Never infer stopping from elapsed
time, a report, a parent exit, or an empty process group.

Every version-2 proof has exactly these common fields:

| Field | Source |
| --- | --- |
| `version` | Integer `2` |
| `kind` | Role value below |
| `identity` | Original `client`, `session_id`, `task_id`, `scope_ref` |
| `expected_pins` | Original task pins, unchanged |
| `expected_revision` | Current positive task revision |
| `scope_id`, `attempt_id`, `dispatch_id` | Original admitted assignment |
| `assignment_digest` | Digest of its immutable assignment artifact |
| `claims_digest` | Digest of its canonical admitted claims |
| `observation_ref`, `coordinator_ref` | Nonempty references to the independent observation and assessment |

Digests are lowercase SHA-256. Use retained runtime values; do not hash a rendered
prompt when an assignment artifact digest is required. Unknown fields reject.
Recapture after relevant task, candidate, observation or ownership changes.

## Worker or reviewer

Use `kind:"assignment-writer-reconciliation"`. Add `candidate_digest` from the
original admission, a freshly captured `current_candidate_digest`, `d6_plan_digest`,
`observation_digest`, `result_digest`, `native_identity`, `launch_state`,
`stopped:true` and `descendants_stopped:true`.

`native_identity` contains exactly `client_surface`, original `native_version`,
`parent_session_id`, `task_name`, `parent_turn_id`, `spawn_item_id`, `worker_id`,
`worker_turn_id`, `result_item_id`. The first four come from admission; the last
five come from the latest observed native receipt, including null when absent.
`observation_digest` is that observation artifact's digest; `result_digest` is
the receipt's result digest. Neither is a digest of the report text.

`launch_state` is `observed` when an observation exists. A truly unlaunched
admission uses `not-started`, null observation/result digests and null receipt
identity fields, backed by independent inspection of the exact parent/task marker.
Missing history does not establish this branch. Review proofs also require the
original linked D5 review attempt and plaintext assignment binding.

## Check

Use `kind:"check-writer-reconciliation"`. Add original `candidate_digest`, fresh
`current_candidate_digest`, `plan_digest`, `execution_digest`, `stopped:true` and
`descendants_stopped:true`. The execution digest is the exact ledger observation
digest, or null if no execution result was durably recorded. Missing execution
cannot prove success. Check semantics and legacy readers remain in
[check reconciliation](evidence-checks.md).

## Coordinator operation

Use `kind:"coordinator-operation-reconciliation"`. Add the original `decision_ref`,
`operation_id`, `operation_digest`, `operation_evidence`, `resource_observations`,
`operation_stopped:true` and `operation_descendants_stopped:true`.

The two evidence fields are registered artifact references `{name,digest}`.
Each artifact must contain matching `operation_id`, `operation_digest` and
`claims_digest`, alongside the independently observed facts. Include
`d5_plan_digest` and/or `d6_plan_digest` exactly when the admitted operation has
those plans. Include original `candidate_digest` and fresh
`current_candidate_digest` exactly when admission has a candidate. Task-only
operations must not invent these optional bindings.
