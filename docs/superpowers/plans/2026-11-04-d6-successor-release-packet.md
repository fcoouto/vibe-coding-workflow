# D6 successor release packet

**On hold. Live execution allowance is zero.** This packet defines a proposed
qualification sequence for one disposable Codex CLI scope. Release requires
separate authorization of the reviewed packet and its exact effects. The
[held pilot plan](2026-11-03-d6-managed-lifecycle-pilot.md) owns the acceptance
criteria and ceilings. The Lima/Docker preflight is retired. The next gate is
the [approved cooperative contract alignment](../../d6-native-delegation-plan.md#pending-implementation-and-offline-acceptance)
and its offline acceptance. This packet remains a held draft until the runtime
supports that contract and the complete sequence has been independently reviewed.

## Historical source checkpoint

These pins describe the earlier packet. Re-pin the reviewed implementation and
exact native frontend before any later release. The cooperative planning update
does not repin historical evidence or grant execution allowance.

| Item | Pinned planning input |
| --- | --- |
| `origin/main`, verified 4 November 2026 | `c9d670c15ba9e1786b22fb514d1683a4e0780539` ([PR #79](https://github.com/fcoouto/vibe-coding-workflow/pull/79)) |
| Git tree | `219b1bfb1a5cf9355c4252de845cb0fb669c624b` |
| Package and schemas | `0.1.8`. Canonical project authority 2, runtime configuration and SQLite 3. |
| Policy digest | `12a8ecdf666fd6408a510008a4c0e2c7eb906f41b3b9b371b62a4c362cd6607e` |
| Runtime digest | `c15e071395a0e7439feffed86c24027d503cd2119c43bcd03b79998bf136ca1a` |
| Earlier CLI planning input | Codex `0.165.0`, Linux x86_64 musl. Cached archive SHA-256 `be635d3486a5bd060d0fff582ae6d30160280c31344dd85719707fa920e187f0`. Archive member SHA-256 `c06a67fd8ac76508dc78bd99ce20c9f317b8d568beda59485f3f4134df9962d5`. Re-pin the executable and frontend if a supported native route is selected. |

[PR #78](https://github.com/fcoouto/vibe-coding-workflow/pull/78) supplied the
reviewed child guard and paired receipt fix. Its 272 affected tests passed
offline. [PR #77's D5 result](../../d5-validation.md#managed-review-readiness-on-codex-cli-01650)
belongs to a different runtime digest and disposable scope. Keep the earlier
D4 failed claim and all receipts with their original authority.

Retain the earlier disposable probes and run dispositions under their original
identities. Same-parent managed continuation, actual child hooks and cooperative
completion remain pending. Historical version-2 claims retain their original
proof requirements.

## Freeze before requesting release

- [ ] Bind one approved disposable environment and one standalone canary
  checkout to the exact executable, package contents, Git/Python, effective
  client settings and hook registrations. Record absolute canonical
  checkout, Git, D4 journal, native home and private schema-3 authority
  paths and physical identities in the private packet.
  Carry those identities across phases. Keep package files read-only.
- [ ] Name the coordinator and independent reviewer/observer in the private packet.
  Record the existing native account route and trust boundary. The canary check
  uses local public fixture data. Any proxy or account change requires a
  separately scoped decision. Verify actual
  capacity, native catalog, compatible guidance and supported observe/resume
  controls.
- [ ] Freeze the public canary preimage, postimage, exact `apply_patch` bytes,
  immutable test and candidate inventory. The worker changes only `canary.py`
  from `0` to `42`. The reviewer and D5 checks receive the same read-only
  candidate. Record allowed foreground tools and the cooperative scope limits.
  Reserve any coordination read path explicitly. Assign runtime, evidence and
  coordination files to the coordinator and independently check their preservation.
  Background jobs, mutable services and nested delegation are outside this pilot.
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

Use the pinned Python executable with `-I -B -c` and the exact
argument `import sys; sys.path.insert(0, "."); import test_canary` from the
canonical checkout. The baseline must fail on the assertion with the exact
preimage. Both registered post-edit executions must exit zero on the reviewed
postimage. Freeze the interpreter path, timeout of at most 10 seconds, minimal
environment and read-only effects in the D5 plan.

## Cooperative completion and held ownership

Use the [approved D6 contract](../../d6-native-delegation-plan.md#normal-completion-and-uncertain-ownership)
for future worker/reviewer completion. Bind actual native identity, successful
turn completion, complete tool activity and independent candidate inspection
to the original claims. Account for foreground command termination and any
pending host retry or continuation before release. Unknown activity retains
ownership, capacity and consumed budgets. Automatic takeover remains deferred.

The exact canary patch exercises child guard behavior. The native frontend may
expose other tools under its ordinary trust boundary. The brief limits their use
to approved foreground work. Enforced patch-only capability is deferred.

**Historical capability finding, 4 November 2026.** The inspected OpenAI docs
describe custom-agent feature reductions such as `features.shell_tool=false`.
Custom agents inherit parent sandbox, approval settings and MCP servers.
The spawn control exposed in this Codex chat has no custom-agent selector
or per-worker tool allowlist. The local Homebrew path points to CLI
`0.165.0`. The earlier Linux candidate is a separate build of that version.
Current docs are unpinned to either build and leave the exact boundary
unverified.
Tool hooks have coverage exceptions, and the package’s write guard covers
only canonical `apply_patch`. Complete enforcement remains unverified. The
approved cooperative scope accepts this limitation. D6 stays on hold pending
runtime alignment, offline review and a separately released packet.
[OpenAI subagent controls](https://learn.chatgpt.com/docs/agent-configuration/subagents#custom-agent-file-schema),
[OpenAI hook coverage](https://learn.chatgpt.com/docs/hooks#tool-coverage),
[runtime guard limits](../../../clients/runtime.md#guard-and-continuation-limits).

Current [version-2 proof fields](../../../clients/delegation-proofs.md) retain
their stronger meaning. The implementation must represent cooperative completion
explicitly and audit dependency/readiness consumers before this packet can use
it. D5 check/coordinator proof and D7 requirements retain their own acceptance
rules. Keep the D5 review digest separate from the D6 ledger digest. Any
unsupported transition ends the sequence with its original claims retained.

## Staged child guard checks

| Stage | Required observation and decision |
| --- | --- |
| D4 bootstrap | Under the separately released setup effects, capture genuine CLI provenance, restricted SessionStart context, bootstrap policy rejection, hook trust and registration, and independent canary facts. Use the exact disposable qualification-purpose task and original allocations. `task-start` and `task-patch` require the pre-tool key. Worker admission requires post-tool, Stop and Interrupt keys. Reviewer admission adds review-readiness. An allocation permits the listed bounded probe with pending cases. It does not mark those cases verified. |
| Observe the child before allowing mutation | Accept the D5 plan, then the D6 plan. Prepare one worker and use its native launch permit once. Capture the actual parent turn and spawn item. Use `delegation observe` to record the exact child session and first turn as `inProgress`. Before launch, validate one supported same-turn barrier within the approved foreground work. Proposed barrier is one bounded wait of at most 60 seconds on a fresh, private readiness marker controlled by the observer. The observer publishes it only after the exact receipt and working parent are confirmed. Include its read claim, time and owner in the packet. The child's brief permits only reading that marker. If the frontend cannot wait and patch in the same turn, hold. |
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
   and cooperative completion evidence. An incomplete-evidence reconciliation
   request must retain ownership. Reconcile the real worker through the reviewed
   completion path before any dependent check. Uncertain activity ends this pilot
   with claims retained and no automatic takeover.
3. Run the registered D5 acceptance check, close its phase and reconcile it.
   Resume the same native parent through the supported control path only after
   prior claims settle. Prepare the reviewer through `evidence review prepare`,
   collect and independently assess its report, then close and reconcile it.
   Run the final planned check, reconcile it, and use the existing D5 verifier.
   Retain partial observations when a prerequisite fails.

The proposed schedule reserves one worker, one reviewer and two registered
passing check executions. Bind distinct dispatch IDs for executions and retain
stable IDs for replays. Fit the failing baseline, blocked exclusion request,
incomplete-evidence request, optional parent pre case, up to two worker self-checks and
all observations into the approved schedule before release. Count any admitted
coordinator operation in the original qualification allocation. Account for the
D5 completion barrier according to source. The original ceiling is eight
admitted operations and two resource units. Native capacity remains two attempts
and two units with concurrency one. Retain the 60-minute window, five model
turns, 32 controls including at most 12 observations, one review round, and
zero retries or replacements. Reserve the second check phase explicitly.
Count all bootstrap and setup turns and contexts in the exact schedule.
Overflow or an incompatible managed resume means hold before launch.

**Release decision remains pending.** Reviewed cooperative reconciliation and
offline acceptance are the first gates. The private identity and effect pins,
exact ledger schedule, same-turn barrier and native guard route then need review.
The complete sequence must satisfy each consumer's evidence requirements.
Actual native observations require separate release. Keep the base pilot free of optional
Habblaud, Desktop, external models and D7 enforcement. Report software checks,
native guard observations and reconciled ownership separately. No live step
was taken to prepare this packet.
