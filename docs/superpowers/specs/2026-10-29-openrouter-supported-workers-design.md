# Supported OpenRouter coding workers

Authoring baseline: published `65408fd777b7b48ed095a7c43cdd775e7bfb4387`.
Genesis owns integration with its evolving native runtime APIs and all shared
Git, policy, onboarding, README, source-map and canonical-plan changes.

## Intent and approved scope

Make OpenRouter a supported optional integration for implementation and testing
through background OpenCode workers in local Git worktrees. Codex remains the
coordinator, preserves its selected native model and authentication, and owns
assignment, independent verification, Git operations and integration.

The user selected local worktrees as the single execution mode. Manage OpenRouter
Integration enables editing and testing without an execution-mode selector.
Reviewer and investigation assignments still receive the tools their tasks need;
integration enablement does not make every assignment a writer.

The user approved replacing the initial fixed file-count, response-token and
single-run restrictions with scoped workspace access, task-appropriate finite
limits and capacity-aware parallelism. Published benchmarks and cached endpoint
capabilities guide selection. They do not replace native verification of results.

Keep activation outside Onboard my Project. Successfully qualified onboarding
may offer Manage OpenRouter Integration afterward. Native routes remain the
default when the optional integration is disabled or unsuitable for the task.

## Approaches and implementation choice

Extend the existing manager, proposal helper, worker runner and visibility adapter,
using the native workflow's ownership and verification owners. This preserves
the approved user workflow and avoids a second authority for the same task.

A separate executor with its own competing task/claim database would duplicate
coordination and complicate recovery. A wording-only promotion would leave the
requested editing/testing behavior absent. The selected extension is the smallest
coherent approach; exact internal helper names remain implementation decisions.

## Management and saved authorization

Enabling the worker integration authorizes scoped worktree edits and declared
check execution in the selected enrolled checkout's tasks. State that effect in
the management flow. Do not add a mode picker or repeated per-task approval where
the user's saved authorization already covers the work.

Retain private settings, current scope/physical bindings, offline status, revision
checks and short guarded launch admission. Configuration remains initially off.
OpenRouter manages monetary limits; configuration stores no money cap or key.

Introduce a versioned consent contract for the expanded worker capability. A
legacy read-only record never silently authorizes edits or test execution. Status
reports that renewed enablement is required without rewriting the record. The
explicit management enable flow renews consent through current-revision guarded
updates, retaining valid nonsecret runtime references and history. Direct legacy
callers cannot gain expanded rights by omitting a field or replaying an old brief.

Already-admitted work may settle under its original contract. Prepared work must
pass the current launch check; disable or a consent revision change invalidates
stale preparation. Disable blocks new work and retains results, history and
verification access. Account connections and direct MCP access remain separate.

## Assignment and workspace contract

Each job has a stable identity and an immutable brief binding:

- The authorized source checkout, selected source snapshot and accepted task/job.
- Objective, applicable instructions, dependencies and acceptance criteria.
- Readable context, editable paths and separately declared mutable resources.
- Registered checks, model/provider/effort and finite execution/output allowances.
- Stop conditions, recovery owner and genuine native supervisor identity.

The coordinator selects or creates a managed worktree for the job and records its
physical Git identity. It never treats a sibling worktree as independently enrolled
or infers authorization from common-Git membership. Its execution authority comes
from the accepted source task and its explicitly bound worker assignment.

Capture relevant staged, unstaged and selected untracked source inputs before
dispatch. Materialize an approved dirty overlay when required, without moving or
rewriting the user's source index or branch. Keep the source snapshot stable and
record file contents/modes needed for later comparison. Worktree setup, cleanup
and Git operations belong to the coordinator rather than the model.

Replace the 16-file copy restriction with a scoped project workspace. Workers read
context on demand; available files need not all enter the prompt. Review the
transmission scope and exclude credential-bearing or unrelated content. Respect
explicit user/provider data restrictions and applicable native instructions.

Read/write permissions follow the job's declared paths. Test commands execute
with host authority; worktree separation and OpenCode permissions are cooperative
scope controls, not operating-system isolation. Do not claim otherwise. Inspect
actual changes and relevant shared effects independently before acceptance.

## Editing and check execution

Grant OpenCode the file tools required for the assignment. Read-only assignments
retain their read-only tool profile. Coding assignments can create, change and
delete declared paths, with the resulting candidate collected independently.

Expose registered check execution through a small packaged local tool bridge.
The worker requests an accepted check ID rather than arbitrary shell text. The
bridge binds the request to the assignment, execution worktree, current candidate,
check definition, resource claims and remaining deadline. It runs the exact
declared command with the approved environment and captures actual process exit,
output references and descendants outside worker-editable result storage.

Keep generic shell execution unavailable through the worker tool profile. Adding
a needed check follows the coordinator's existing task/check-plan amendment path.
Registered checks still execute project code, including worker changes; the bridge
is command/lifecycle control and evidence capture, not a host security boundary.

Worker check feedback supports implementation and repair within the original job
limits. It does not establish native acceptance. Codex inspects the actual diff,
performs the required independent checks/review and assesses task completion.
Reuse a worker check receipt only if the native evidence owner independently
qualifies its source, bindings and applicability; otherwise rerun the required check.

## Limits, discovery and parallelism

Reuse cached discovery with the existing expiry and refresh rules. Include actual
model/endpoint context, output and tool-interface capabilities in eligibility;
use benchmark/native anchors and comparable task history for capability estimates.
OpenRouter models do not need a new general assessment before every assignment.
Unavailable or missing evidence remains explicit rather than becoming a fabricated
capability or success probability.

Choose finite output, step, wall-time and artifact allowances for the assignment,
using task requirements and available controls. Output reservations include
reasoning where the provider counts it there and fit the remaining context window
and endpoint maximum. Limits are recorded, inspectable and overridable within the
authorized task plan. Do not replace the previous constants with another universal
small-task ceiling or remove bounded parsing, output and cleanup protections.

Longer runs need bounded tool-output summaries and retained log/artifact references.
Keep raw logs and source content out of progress publications. Any client context
management used for longer sessions must preserve the original job identity,
deadline, accounting and stop rules; it cannot create an unbounded resume loop.

Admit independent workers concurrently under the native ownership/capacity owner.
Reserve target paths, execution worktrees, Git and shared mutable resources before
launch. Conflicting or dependent work waits. Capacity reflects verified local
resources, configured task limits and route availability rather than a fixed
single-worker rule. Do not introduce a separate competing reservation ledger.

Retain OpenCode's existing request retry ownership without an outer replay loop.
Capacity failures, rate limits and uncertain outcomes do not authorize a new run
identity or reset consumed allowances. Apply the established native fallback after
confirmed local stop; preserve partial work and uncertain billing.

## Result, recovery and integration

Collect a base-bound candidate from the actual worktree, including relevant new
files, deletions and modes. Reject unexpected paths, unsafe aliases, altered Git
ownership or changes that conflict with concurrent source work. Native integration
preserves unrelated edits and applies only reviewed changes against current inputs.
Worker-written reports and passing-looking output are not authoritative proof.

Use one absolute execution deadline across admission, launch, input delivery,
tools and test execution. Track the actual worker and writable check descendants.
Keep capacity and ownership reserved until the host owner verifies stop; a timeout
or CLI exit alone is insufficient. Failed/cancelled work retains partial diffs and
observed usage for reconciliation and native recovery.

## Progress and accounting

Retain the genuine native supervisor and its truthful native model identity.
Publish the external worker's role/model and observed file/check activity through
the existing Codex commentary and Habblaud transport. A heartbeat reports presence;
it does not establish progress or acceptance. Display completion is separate from
the authoritative job result. Never fabricate native agent logs or model statistics.

Keep requested/configured/observed model, provider and effort distinct. Attribute
reported tokens/cost to their actual source; missing or partial data stays unknown.
Provide sanitized job/attempt/check correlation to the Langfuse integration owner.
Do not add analytics activation, raw prompt/response export or another collector.

## Required shared interfaces and ownership

The OpenRouter owner implements its manager, runner, local check bridge, scoped
tests and skill procedures. Genesis owns these required native seams:

1. Bind a worker's execution worktree to its authorized source task/job without
   creating enrollment or bypassing existing path ownership checks.
2. Reserve and reconcile external worker/check resources through the native owner,
   retaining uncertainty and preventing duplicate launch or early release.
3. Supply accepted check definitions and host evidence bindings to the local
   bridge; separate worker feedback from qualified native verification.
4. Accept base-bound candidate collection and sanitized visibility/accounting
   correlation through existing owners.

These are explicit interface proposals, not permission to edit the evolving native
runtime from the OpenRouter branch. Agree and qualify each shared seam with Genesis
before dependent dispatch is presented as supported. README, shared policies,
source-map, canonical plan and onboarding edits are composed by Genesis.

## Verification and delivery

Prove management consent migration, default-off behavior, re-enablement and disable
races; actual edits/new files/deletions and registered test execution; independent
candidate verification; larger file sets and response budgets; parallel independent
jobs and rejected conflicts; endpoint capacity errors; replay, interruption,
deadline, descendant stop and partial-accounting preservation. Include changed
source/claims/settings and unsafe-path cases at public helper boundaries.

Use disposable worktrees, fixture processes and controlled local provider responses
for implementation proof. Package checks, native client observations, visible
progress, provider accounting and Langfuse correlation remain separate evidence.
The combined live end-to-end run stays after Langfuse is ready, as requested.

Describe the active feature as OpenRouter integration/coding workers. Preserve
historical evidence and user paths, and report exactly which current capabilities
have observed proof. Development or documentation changes do not install the plugin,
enable a live project, change credentials, publish a release or establish live
provider qualification.
