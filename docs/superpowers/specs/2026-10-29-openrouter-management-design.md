# Manage OpenRouter Integration

Implementation requested by the user on 2026-10-29, following the management
options discussed in this chat. This slice adds real saved controls, not a
guidance-only skill. The decisions below use the existing implementation boundaries.

## Intent and approach

Provide one management skill with configure, status, enable, and disable controls.
Native execution remains the default. Setup and activation stay outside project
onboarding; completed qualified onboarding may offer a short optional follow-up.
Invoking or installing the skill does not itself configure or enable anything.

Use the current accepted Codex checkout and existing private runtime authority.
Canonical umbrella membership is not publicly dispatched yet. Do not create an
OpenRouter membership registry, broaden checkout enrollment, initialize native
task state, or treat readonly accounting facts as consent.

The selected approach is a small dedicated OpenRouter settings owner using current
scope/private-file/authority-lock/atomic-publication primitives. A common framework
extracted from Observability was considered and rejected: that would change a
separately owned integration without being necessary for these controls. A skill
without enforced saved state was rejected because disable would not govern dispatch.

## Saved state and scope

Store a bounded, versioned private JSON record in the existing runtime authority,
under a separate `openrouter` namespace, keyed by the existing checkout scope ID.
Use private directories and regular files, bounded reads, no symlinks/hardlinks,
atomic durable publication, optimistic revisions, and serialized mutations.

Bind the record to stable checkout identity and physical repository, common-Git,
private-directory and database identities. Re-resolve accepted enrollment before
every operation. Ordinary task/database content changes and benign reenrollment
with the same identities do not erase consent. Changed ownership, scope or storage
does not silently repin it; preserve the record and report a protected prerequisite.

The record contains a version, revision, binding, selected routes, desired opt-in,
and nonsecret OpenCode executable/auth-directory references. Routes are `workers`
(the existing read-only copied-input pilot) and `proposals` (the existing text-only
route). Configuration explicitly selects routes. OpenCode references are required
only for workers. No keys, prompts, responses, money caps, model defaults or
observability settings belong in this record.

Derive each checkout's private discovery store and worker-runs directory from this
owner. Old standalone pilot stores remain untouched and inspectable; they cannot
authorize managed dispatch. Do not silently migrate unrelated history or credentials.

## Control behavior

- Configure validates selected routes and local nonsecret references, stores the
  revisioned configuration initially off, and prepares only its private namespace.
  Reconfiguration requires the current revision and a disabled integration.
- Enable requires matching current configuration/revision and valid local
  references. It records opt-in without inference, account queries or secret reads.
- Status reads saved consent and local configuration only. It creates no files,
  acquires no credentials and contacts no service. Missing settings means off;
  invalid or changed authority is an error, not a fabricated disabled state.
  Saved enablement does not prove a live connection or client qualification.
- Disable serializes with admission, records off, and blocks subsequent admissions.
  It does not cancel already-admitted work, change account keys/limits, remove
  history, disable observability or claim upstream cancellation.

Mutating requests use `expected_revision`. Duplicate enable/disable at the current
revision is harmless; stale revisions cannot overwrite a newer decision. Status
must distinguish configured, enabled, selected routes, local readiness and unknown
connection/qualification. It does not scan all jobs or invent an active-worker count.

## Enforced admission and disable boundaries

Both public executor paths must check the same current settings. Missing, disabled,
unsupported or mismatched settings select native execution; an approval-reference
string or a populated cache cannot bypass this gate. Direct user access to MCP or
OpenRouter is outside these helper controls and is neither disconnected nor revoked.

Proposal `begin` is the admission point for its one bounded call. Persist admission
with the settings revision and scope while the local consent guard is held. An
already-issued proposal attempt may finish after disable; no second call or task-ID
evasion is authorized. Recording outcomes and inspecting history remain possible.

Worker preparation is not launch admission. Recheck current consent immediately
before the single OpenCode process launch, serialized with disable. Disable between
prepare and launch must prevent that launch. A process launched before disable may
finish and undergo native verification without re-enabling. Caller executable,
authentication directory, run-root and proposal-store references must match the
configured/derived references. Copied inputs must resolve to that enrolled checkout.

Retain cached selection, per-task eligibility, one-run pilot limits, OpenCode-owned
retries, original deadlines, partial accounting, replay protection and independent
native verification. Never introduce credit preflights, outer retry loops, provider
cascades, an installer, a credential proxy or a measurement collector in this slice.

## Skill and onboarding behavior

The entry point stays within 150 words and loads its local procedure only for
management. Ordinary native tasks do not load management or provider setup steps.
Routine eligible external work loads only its executor and checks saved consent;
it does not repeatedly ask for activation already authorized within that scope.

Offer the skill only after successful apply/resume completes qualified onboarding,
when relevant and not already declined or handled. The offer never invokes controls,
reads credentials, joins onboarding dependencies or blocks completion. Preserve
existing integration files and user choices during later onboarding operations.
Root owns the shared onboarding/README/source-map changes and receives exact-base
owned-hunk proposals for serialized integration.

## Verification and limits

Test saved state across processes, off-by-default behavior, revision conflicts,
unsafe files, replaced authority, scope separation, local-only status, disabled
admission in both executors, disable after worker preparation, and continued
verification/accounting for work admitted before disable. Existing executors must
retain all earlier replay, permission, deadline and recovery checks.

Use disposable accepted scopes and synthetic workers. Qualify the installed pinned
OpenCode client with controlled local responses if needed, without real credentials
or account traffic. Perform independent instruction-path/security review and report
package/helper tests separately from client/provider observations. No live project
is enabled by implementing or testing this feature.
