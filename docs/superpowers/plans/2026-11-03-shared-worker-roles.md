# Shared worker roles implementation plan

**Goal:** carry explicit workflow roles and custom role names to optional Habblaud
visibility for ordinary/managed native and OpenRouter workers, without changing
execution authority, settings or identity.

**Architecture:** one versioned metadata validator, label renderer and optional
transport adapter. Native contexts use independently observed native identities;
OpenRouter contexts keep their external display identity and real supervisor.
Store declarations in existing assignment/run contexts, not a new registry.

**Baseline:** main `499512e0d332be4c6e65c680ca8ec4aaa3adca41`, package `0.1.3`.
The user approved implementation of the all-worker requirement from the bounded
D6 pilot plan. That earlier uncommitted plan remains untouched in its worktree.
No installation, external inference or live qualification is authorized.

## Constraints and decisions

- Preserve canonical role and specialty separately from optional custom role
  name. Render the full custom name when supplied; otherwise retain `Role · Model`.
- Keep D6 authority roles, immutable task names, pins, digests, ownership, review
  independence and limits unchanged. Optional metadata participates in the
  original assignment digest; absent legacy metadata remains absent.
- Ordinary native contexts require no enrollment or runtime database. Observe
  actual native parent/child lineage before publishing. Continuations preserve
  identity; genuine fallback/new attempts use their own observed identities.
- Freeze declaration before first display binding. Replays preserve it. Reject
  conflicting existing bindings; the receiver has no supported role override.
- Use existing loopback-only transport; no native logs, invented native child,
  raw prompt/source forwarding, route enablement or model/provider/auth changes.
- Visibility failure changes no execution or acceptance result. Unsupported
  rendering and first-binding races remain explicit and unqualified.

## Tasks

1. [x] Add a real OpenRouter custom-name regression; confirm current preparation
   rejects it. Add shared metadata/transport tests for canonical/custom labels,
   Unicode/bounds, first binding, replay, conflict, delivery failure and identities.
2. [x] Implement `runtime/worker_visibility.py` and a database-free native helper
   in `scripts/worker_visibility.py`. Native observation belongs in the existing
   Codex adapter. Test real boundary behavior with in-memory native/transport
   fixtures; no live client or Habblaud connection.
3. [x] Forward optional metadata through D6/D5 preparation, replies and same-child
   continuation. Reuse the shared publisher in OpenRouter; retain legacy briefs,
   external identities and launch/verification semantics. Test replay rejection,
   read-only reviewer authority, identity preservation and failed launch.
4. [x] Author one local visibility contract and load it from native delegation
   and OpenRouter paths. Refresh the instruction map at authoring time. Validate
   package, affected suites, broader tests and representative loading paths.
5. [x] Obtain one fresh independent whole-change review, fix blocking findings
   with regression proof, and record actual validation and remaining limits.

## Review focus

Check metadata cannot acquire authority; old records remain readable; a custom
label never replaces a task/child identity; replay/fallback cannot duplicate a
native character; and transport/first-binding failures cannot prevent ordinary
work. No commit, publication, installation or live qualification is part of this
request. Preserve original WIP and the original historical handoff.

## Source validation

The final checkout passed 88 selected tests: 76 native, package and instruction
checks; seven OpenRouter cases; and five managed delegation/review cases. Earlier
broader runs passed 95 D6 and 32 Workstreams cases. Three OpenRouter fixtures
initially raced prompt delivery; their input handshakes were corrected and all
three passed on the final checkout. This was not a repository-wide test run.

Independent review found and closed defects in native spawn correlation, full
label bounds, optional delivery isolation, private path checks, receiver reset
and receipt preservation. Source validation is complete. Existing WIP and
installed packages were preserved. No installation or live qualification ran.
