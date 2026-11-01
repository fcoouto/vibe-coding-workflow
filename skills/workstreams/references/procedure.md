# Workstreams controls

For enable, disable and status, this procedure defines the complete interface.
Load implementation code or additional runtime sections only to diagnose a failed
control or answer an explicit implementation question.

Use the installed package's `scripts/workflow.py delegation workstreams` controls in
the explicitly selected, supported enrolled checkout. Reuse its accepted private
runtime authority. Do not enroll another checkout, initialize state or change
authentication through this control route. An account connection, installation or copied
handoff does not enable Workstreams.

```text
python3 -I -B <package>/scripts/workflow.py delegation workstreams status --cwd <checkout>
python3 -I -B <package>/scripts/workflow.py delegation workstreams enable --cwd <checkout>
python3 -I -B <package>/scripts/workflow.py delegation workstreams disable --cwd <checkout>
```

Supply one JSON object on stdin. Status uses `{"client":"codex"}`; mutations use
`{"client":"codex","expected_revision":N}` with the exact revision returned by
status. On conflict reread and reconcile intent; never overwrite another change.
Report the selected scope and saved result. Repeated identical controls preserve
the setting. First task creation in a new supported Codex runtime scope saves
enabled revision 1. Existing scopes retain their preference; an absent legacy
preference stays disabled. The first explicit disable is saved even if already
off; later identical controls preserve its revision. Status is offline and read-only.
Unsupported or invalid authority is an error, never evidence of disabled state.

Enablement permits suitable Workstreams work under the [execution contract](../../../clients/workstreams.md).
It performs no native dispatch, graph build, provider setup or model call.
Other integrations retain their independent enablement, route permissions and supervision.

Disable stops new managed implementer admissions/continuations. Necessary D5
review of existing output remains available so acceptance can finish. Existing results still require
collection, independent review and reconciliation; uncertain owners retain their
claims. Show disabled-but-active work explicitly. Stopping a worker is a separate
user request. Normal delegation may continue once ownership is reconciled.
Re-enable cannot revive stale dispatch permission or reset consumed budgets.

Human continuation after shutdown reads the current mode and actual native/file
state first. Preserve pauses and limits. Saved enablement and successful local
controls do not establish observed native execution. For an explicit capability
or readiness question, consult the
[latest readiness report](../../../docs/workstreams-main-port.md);
routine controls do not require reading qualification history.

The status field `unresolved_assignments` counts managed implementer reservations,
including prepared and uncertain attempts; it does not establish known-running
worker count. `drained` applies to those reservations, not all native activity.
Inspect existing D5/D6 records separately for pending reviewers or ordinary jobs
before claiming that every owner stopped or taking over resources.

## Registered parent cleanup

When disabling a checkout with registered recovery parents, load the
[temporary monitor procedure](../../../clients/workstreams-recovery.md). Withdraw
only registrations for that checkout, then reconcile the shared schedule. Delete
it when no eligible parents remain; other checkouts may still need it. Status
requests can report monitor membership and suspension without creating a schedule.
