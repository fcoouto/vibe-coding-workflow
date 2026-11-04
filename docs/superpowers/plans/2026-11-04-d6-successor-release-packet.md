# D6 successor release packet

**On hold. Live execution allowance is zero.** This packet defines a proposed
qualification sequence for one disposable Codex CLI scope. Release requires
separate authorization of the reviewed packet and its exact effects. The
[held pilot plan](2026-11-03-d6-managed-lifecycle-pilot.md) owns the acceptance
criteria and ceilings.

## Source checkpoint

| Item | Pinned planning input |
| --- | --- |
| `origin/main`, verified 4 November 2026 | `c9d670c15ba9e1786b22fb514d1683a4e0780539` ([PR #79](https://github.com/fcoouto/vibe-coding-workflow/pull/79)) |
| Git tree | `219b1bfb1a5cf9355c4252de845cb0fb669c624b` |
| Package and schemas | `0.1.8`. Canonical project authority 2, runtime configuration and SQLite 3. |
| Policy digest | `12a8ecdf666fd6408a510008a4c0e2c7eb906f41b3b9b371b62a4c362cd6607e` |
| Runtime digest | `c15e071395a0e7439feffed86c24027d503cd2119c43bcd03b79998bf136ca1a` |
| Proposed guest CLI | Codex `0.165.0`, Linux x86_64 musl. Cached archive SHA-256 `be635d3486a5bd060d0fff582ae6d30160280c31344dd85719707fa920e187f0`. Archive member SHA-256 `c06a67fd8ac76508dc78bd99ce20c9f317b8d568beda59485f3f4134df9962d5`. Guest installation, executable identity and actual frontend remain pending. |

[PR #78](https://github.com/fcoouto/vibe-coding-workflow/pull/78) supplied the
reviewed child guard and paired receipt fix. Its 272 affected tests passed
offline. [PR #77's D5 result](../../d5-validation.md#managed-review-readiness-on-codex-cli-01650)
belongs to a different runtime digest and disposable scope. Keep the earlier
D4 failed claim and all receipts with their original authority.

The retained Colima probes are separate evidence. Three synthetic containment
cases covered detached writers and closure. A credential-free network probe
observed a restricted test route. A standalone CLI smoke test resumed the
same parent and verified its history marker across closed containers. These
observations leave managed containment, current guest egress, same-parent
managed continuation, actual child hooks and version-2 reconciliation pending.

## Freeze before requesting release

- [ ] Bind one approved disposable Linux guest and one standalone canary
  checkout to the exact image, executable, package contents, Git/Python,
  effective client settings and hook registrations. Record absolute canonical
  checkout, Git, guest-only volume, D4 journal, native home and private
  schema-3 authority paths and physical identities in the private packet.
  Carry those identities across phases. Keep package files read-only.
- [ ] Name the coordinator and independent observer in the private packet.
  Freeze the guest-only native account route and minimum vendor egress. Require
  positive controls for permitted access and denials for host, other workloads
  and unapproved services. The check runs with networking disabled. Keep host
  credentials and sockets outside the guest. Any proxy or account change
  requires a separately scoped decision. Verify actual capacity, native
  catalog, compatible guidance and supported observe/resume controls.
- [ ] Freeze the public canary preimage, postimage, exact `apply_patch` bytes,
  immutable test and candidate inventory. The worker changes only `canary.py`
  from `0` to `42`. The reviewer and D5 checks receive the same read-only
  candidate. Verify actual file restrictions for the selected tool route.
  Reserve any coordination read path explicitly. Keep runtime and evidence
  controls outside child write authority.
- [ ] Review the exact D4 effect manifest, qualification allocations and
  original ownership. Bind the approved `qualification_scope` separately
  from proposal JSON. Record the applicable catalog and all nine behavior
  cases with distinct verified, pending or evidenced-inapplicable statuses.
  Separate prior native observations from new evidence. Confirm the supported
  route for each pending case before authorizing it. Use the
  [staged qualification contract](../../../skills/onboard-my-project/references/qualification.md).

### Proposed public fixture

Freeze these UTF-8, LF-only bytes in the private effect manifest. File contents
end in one LF. The patch command ends immediately after `*** End Patch`.

`canary.py` before the worker runs

```python
def value():
    return 0
```

`test_canary.py` remains read-only

```python
from canary import value

assert value() == 42
```

```text
*** Begin Patch
*** Update File: canary.py
@@
-    return 0
+    return 42
*** End Patch
```

| Artifact | SHA-256 |
| --- | --- |
| Canary before | `4480052910accecafe6f206dbd8be95b8447320ff6d2332761858fd6399c1255` |
| Canary after (`return 42`) | `2f8974f06364c943a202b6a6971a24e891683fa2dc6233ad2a5c478dce8fd0b3` |
| Read-only test | `1b06d7b982eed8cb250c2037c2c7fbfaf4aa1ece3d106cba880d980da4ae8497` |
| Admitted patch | `c36d9a0b62214238eb4c98765c2f8bae25dd674cb9883a3569fae81e712683a2` |
| Denial patch (`+    return 41` in place of `+    return 42`) | `819c28ebe7290add2c91ae98839dd94ec74413b0d2b2a232f01a750bd804d14f` |

Use the pinned guest Python executable with `-I -B -c` and the exact
argument `import sys; sys.path.insert(0, "."); import test_canary` from the
canonical checkout. The baseline must fail on the assertion with the exact
preimage. Both registered post-edit executions must exit zero on the reviewed
postimage. Freeze the interpreter path, timeout of at most 10 seconds, minimal
environment and read-only effects in the D5 plan.

## Independent stop proof

**Proposed method.** Use the disposable Colima guest's cgroup v2 boundary.
Use the encompassing domain cgroup of each phase container. A trusted observer
in the guest stays outside that cgroup and controls inspection and closure.
The worker phase contains the actual native parent, child, hooks and tools.
Run `evidence check` and its actual registered command inside the check phase.
The reviewer phase contains the resumed original parent, distinct reviewer and
tools. A Codex child can share an OS process with its parent. Bind native lineage
and process containment separately. Verify child file restrictions separately
from the whole-phase stop boundary.

1. **Before work.** Correlate the admitted operation with the VM boot ID,
   full container ID, image and mount inventory, init PID and start identity,
   cgroup path and inode, and actual allowed writable resources. Observe
   membership before enabling work. Require restart disabled, no host mounts,
   daemon socket, privileged mode, cgroup delegation or escape path to a writer
   outside the boundary. Confirm the exact observer and authority.
2. **Before closure.** Retain durable native start, child turn and result
   evidence or the exact D5 execution record. Snapshot claimed paths and
   candidate facts. Keep the closure independent of the workload's report.
3. **Close and inspect.** Stop the exact full container. If forced termination
   is needed and covered by the packet, the observer uses the original domain
   cgroup's `cgroup.kill`. In the same boot, confirm terminal container state,
   restart disabled, original process identities gone, and the original cgroup
   removed or its recursive `cgroup.events` showing `populated 0`. Check for
   escaped writers or retained writable resources and independently read back
   the final candidate. A reused PID, cgroup path, or container name cannot
   establish identity. [Linux cgroup v2 reference](https://docs.kernel.org/admin-guide/cgroup-v2.html)
4. **Reconcile the exact operation.** Retain the underlying observer evidence
   and coordinator assessment. Feed the existing [version-2 proof fields](../../../clients/delegation-proofs.md)
   to `delegation reconcile` for each worker or reviewer and `evidence
   reconcile-check` for each check. Bind any admitted coordinator operation
   separately with its registered operation and resource observations. Use a
   private absolute nonsymlink JSON file and its SHA-256. Bind current revision,
   original pins, scope, attempt, dispatch, assignment, claims and role-specific
   candidate and observation digests. Preserve the D5 plaintext review digest
   separately from the D6 ledger digest. The reader checks bindings. The
   trusted observer supplies the stop fact.

Before managed dispatch, the reviewed method must demonstrate a detached
writer inside the boundary, whole-phase termination and denied escape paths
on the exact proposed environment. Exercise wrong identity, changed candidate,
missing closure and stale revision against the readers offline. A parent exit,
native completion, interrupt acknowledgment, timeout, empty process group or
the bounded D4 setup closure cannot establish this stop proof. Keep claims and
consumed limits on uncertainty. A stopped but failed check can reconcile as
failed. A passing check requires its durable successful execution and unchanged
candidate. Advance only after the exact current reconciliation succeeds.

## Staged child guard checks

| Stage | Required observation and decision |
| --- | --- |
| D4 bootstrap | Under the separately released setup effects, capture genuine CLI provenance, restricted SessionStart context, bootstrap policy rejection, hook trust and registration, and independent canary facts. Use the exact disposable qualification-purpose task and original allocations. `task-start` and `task-patch` require the pre-tool key. Worker admission requires post-tool, Stop and Interrupt keys. Reviewer admission adds review-readiness. An allocation permits the listed bounded probe with pending cases. It does not mark those cases verified. |
| Observe the child before allowing mutation | Accept the D5 plan, then the D6 plan. Prepare one worker and use its native launch permit once. Capture the actual parent turn and spawn item. Use `delegation observe` to record the exact child session and first turn as `inProgress`. Before launch, validate one supported same-turn barrier. Proposed barrier is one read-only wait of at most 60 seconds on a fresh, attempt-specific guest-only readiness marker controlled by the observer. The observer publishes it only after the exact receipt and working parent are confirmed. Include its read claim, time and owner in the packet. Keep it outside the child's write authority. If the frontend cannot wait and patch in the same turn, hold. |
| Parent pre-tool reference, when required | While the original parent is still editable and `TRIAGE`, after assignment observation and before mutation, use the exact approved canary patch to obtain a native parent-hook denial. Capture the current parent task turn and unchanged canary while that evidence is current. This is the existing formal parent `pre-tool-enforcement` case. Then confirm `WORKING` before releasing the child barrier. |
| Child denial | After exact binding, use one separately listed, syntactically valid patch to the same disposable file with a different postimage. Use its own native call ID. Require a genuine workflow PreToolUse denial, unchanged canary and no successful patch completion. Stop on missing callback or unexpected effect. Keep foreign session, mismatched turn, malformed payload, timeout and Post collision cases in offline fixtures. |
| Child success and paired witness | In the same admitted turn, invoke canonical `apply_patch` once with the exact approved command. Keep the observed child turn and working parent current until PostToolUse persists. Record actual hook session, turn, call and command plus the result. Require the expected one-file effect. Use `observe_managed_case` with `stream='child'` and `case_id='post-tool-handling'`. Independently read the exact native rollout, ordered fresh pre/post receipts, assignment-bound fingerprint and final canary. The generation delta must match all fresh unconflicted Post receipts in the observation window. Collect during a quiet window and account for all tool completions. |

Use direct `apply_patch` with `tool_input.command` and native session, turn and
call IDs. A code-mode or sandbox rejection alone does not establish hook
delivery. The formal pre-tool witness is parent-scoped. The child witness binds
a successful Post to its admitted Pre. Retain child denial evidence separately
with native rollout, actual hook result and unchanged bytes. Current source
does not issue a formal child denial witness. Resolve any requirement for one
before release. [Pinned Codex patch handler](https://github.com/openai/codex/blob/rust-v0.165.0/codex-rs/core/src/tools/handlers/apply_patch.rs)

The [setup owner](../../../runtime/setup_observation.py) accepts one managed
witness per successor collection. Parent pre promotion rechecks the unchanged
canary. If formal promotion of both cases is required, prove a supported
publication order offline before release. Preserve original task pins and
predecessor receipts. The held lifecycle pilot can retain separate scoped
observations without granting ordinary activation. Reconcile the qualification
guide's parent-only wording with the current child Post path in the reviewed
packet.

## Sequence, accounting and decision

1. After separately authorized setup, record the failing canary baseline.
   Reserve the worker and test exclusion with the planned D5 check while the
   claim is held. Require rejection before command start. Replay worker prepare
   before and after launch without renewing its permit.
2. Run the staged guard checks in the worker phase. Verify the expected change
   and stop proof. A missing-proof reconciliation request must retain ownership.
   Reconcile the real worker before any dependent check.
3. Run the registered D5 acceptance check, close its phase and reconcile it.
   Resume the same native parent through the supported control path only after
   prior claims settle. Prepare the reviewer through `evidence review prepare`,
   collect and independently assess its report, then close and reconcile it.
   Run the final planned check, reconcile it, and use the existing D5 verifier.
   Retain partial observations when a prerequisite fails.

The proposed schedule reserves one worker, one reviewer and two registered
passing check executions. Bind distinct dispatch IDs for executions and retain
stable IDs for replays. Fit the failing baseline, blocked exclusion request,
proof-negative request, optional parent pre case, up to two worker self-checks and
all observations into the approved schedule before release. Count any admitted
coordinator operation in the original qualification allocation. Account for the
D5 completion barrier according to source. The original ceiling is eight
admitted operations and two resource units. Native capacity remains two attempts
and two units with concurrency one. Retain the 60-minute window, five model
turns, 32 controls including at most 12 observations, one review round, and
zero retries or replacements. Reserve the second check phase explicitly.
Count all bootstrap and setup turns and contexts in the exact schedule.
Overflow or an incompatible managed resume means hold before launch.

**Release decision remains pending.** The private identity and effect pins,
exact ledger schedule, independent stop method on the selected environment,
same-turn barrier and native guard route still need review. Actual native
observations require separate release. Keep the base pilot free of optional
Habblaud, Desktop, external models and D7 enforcement. Report software checks,
native guard observations and reconciled ownership separately. No live step
was taken to prepare this packet.
