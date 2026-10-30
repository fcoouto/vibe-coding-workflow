# Council recovery

Read the applicable section when a seat fails or is rejected, an action is
interrupted, cancellation needs cleanup, or a round needs replacement. Before
inference, [selection](selection.md#preapprove-recovery-candidates) declares the
candidate envelope and the [Codex supervisor contract](../../../clients/codex-council.md#isolated-recovery-supervisors)
assigns ownership. No failure may expand that envelope. General command and consent
contracts live in the [protocol](protocol.md#status-cancellation-and-consent).

## Retry boundaries

OpenCode owns transient request retries inside the original deadline; pinned 1.19.5
permits up to five retries per failing processor stream, not per whole worker. Versions 1/2 add no outer inference replay or replacement. Version 3 records
every supported correction and candidate replacement; it never resets its run ID
or original deadlines to conceal failure. Preserve terminal failure categories and partial
answers. If an unavailable member or exhausted attempt prevents full participation,
continue only the permitted remaining phases within budget and report the outcome.
Do not replace an exhausted Council attempt with native takeover; Free synthesis
failure leaves evidence and gaps rather than a host-produced Council verdict.

## Lost responses and interrupted preparation

Recover lost responses from original identities: an external worker remains at its
deterministic existing path; a lost native brief remains issued. Inspect original
host/worker state and preserve unresolved ownership when unknown. Do not obtain a
second permit, replay a round, delete unknown files or reset deadlines. No upstream
cancellation or billing result is inferred from a local stop.

The executor retries known pre-spawn settings/Council contention at most three
times within five seconds, releasing other admission locks before waiting. If
contention persists, `not_launched` proves this original dispatch did not spawn.
Then use `resume-member` with exactly `{run, phase, member}` for that external
seat. Version 3 additionally permits a provably still-`prepared` owned attempt
whose packet response was lost; it verifies the exact brief/copy before reusing it.
Known before-spawn preparation contention may leave no worker directory yet;
`resume-member` claims that same reserved identity and prepares it with its original
brief allowance, consent and absolute deadline. Genuine preparation defects remain
blockers. A concurrent resume cannot claim a second preparation.
It reuses the original worker path, consent revision, evidence and durable
absolute worker deadline, also bounded by the unchanged phase/total ceiling.
Current checkout, phase, cancellation, consent, snapshot, qualified executable,
duplicate and stop guards still apply. Never resume an ordinary terminal,
ambiguous or running attempt; missing session telemetry proves no such permission.
Interrupted critique or synthesis artifact construction resumes only from frozen bytes after
full inventory/hash/permission checks. Unfamiliar or changed artifacts remain for
inspection and block recovery; do not recapture source or delete conflicts.

## Parallel seat ownership

Use isolated native seat supervisors through the [Codex supervisor contract](../../../clients/codex-council.md#isolated-recovery-supervisors), concurrently
within observed capacity. Each receives only its immutable own-seat brief and
approved source/phase packet. Supervisors research and execute outside runtime
locks; short claims, counters and launches use the existing locked actions. A busy
claim can be retried after the lock releases: it consumes no candidate or inference
allowance. Canonical aliases collide. Never synthesize a member's answer inside
supervision. The main coordinator verifies reports and alone publishes acceptance
and shared generations. Preserve successful independent work while another seat
recovers; report actual selecting/working/investigating/correction/replacement/
accepted/exhausted progress at least every 60 seconds.

## Actions

All recovery JSON includes exactly `run`, `phase`, `member`, plus the action's field
below. `publish-generation` takes only `{run}`. Use these exact CLI action names:

| Action | Additional field and result |
| --- | --- |
| `investigate-failure` | No extra field. Opens the tenure's only investigation after an observed failed/rejected stopped attempt; returns `candidate_id`, `failure_id`, safe failure facts, fixed `deadline_monotonic` and advisory matching private history. |
| `record-investigation` | `evidence` is exactly `{candidate_id, failure_id, searches, reads, sources, corrections}`. Records one episode, never accepts a report. |
| `correct-candidate` | `correction`: zero-based index in that recorded episode. Retires the failed attempt and enables one fresh immutable attempt; returns `not_before_monotonic` for a supported delay. Wait outside locks, checking cancellation/deadlines, before `member`. |
| `replace-candidate` | `seat`: full current eligible seat record on the preapproved shortlist, with the same kind and original envelope. Retires the stopped failed attempt, atomically claims the new canonical model and enables `member`. An eligible successful Free participant may transfer to synthesis chair without appearing in the shortlist. |
| `publish-generation` | No phase/member. Once all pending independent catch-ups are accepted and all critique owners stopped, freezes their new initial-report set, supersedes the old generation and enables fresh critiques for all three active participants. |
| `record-supervisor` | `supervisor`: exactly `{supervisor_id, local_execution_stopped, checks}` with the actual native handle, Boolean observation and nonempty coordinator checks. Register before supervision; record exact observed stop before advancing phases. A new handle cannot erase a live one. Stop settlement remains available after cancellation. |

## Investigate and apply supported corrections

An episode lasts **at most 120 seconds excluding fix application**, clipped by
current cumulative phase/session deadlines, with at most **three searches and five
page reads**. Its clock never resets on restart or supervisor replacement. Read
matching history first when useful. Use non-sensitive public queries based on safe
machine facts; prefer exact-version official support, treating community reports
as hypotheses. Never send private errors, model text, source content, credentials
or logs to search/support. Do not create tickets automatically. Each `sources`
entry is exactly `{url, checked_at, authority, applicability}`: public HTTPS URL
without credentials/query/fragment, current Unix check time (within one day),
`official` or `community`, and at most 1,000 UTF-8 bytes explaining the condition
match. Keep source excerpts out. `searches`/`reads` are actual integer counts within
the bounds. The coordinator checks applicability independently; runtime validation
cannot certify what a supervisor read. Expired or no-remedy investigations move
directly to an eligible replacement without a speculative correction.

Record at most two distinct `corrections`. Each has `source`, a zero-based source
index, and exactly one supported shape:

- `{kind: "workspace_guidance", source}` clarifies the copied root, approved relative
  paths and required result without changing source evidence or conclusions.
- `{kind: "output_steps", source, output_tokens, steps}` sets positive integers
  within the original seat envelope; at least one changes. OpenCode's step setting
  is a prompt threshold, not a hard tool-call cap. Preserve supported reasoning.
- `{kind: "request_representation", source, representation: "output_limit_only"}`
  removes the duplicate provider-specific output option while retaining the pinned
  adapter's model output limit, model/provider/tools and reasoning. This is the
  sole supported parameter-representation alternative; it is a hypothesis until
  actual report verification.
- `{kind: "fresh_connection", source, retry_delay_seconds}` waits 0..120 seconds,
  then creates a fresh owned worker session after the prior local owner stopped.
  Use only for matching transport/service/rate-limit/interruption evidence, with
  the delay fitting the remaining phase. Never weaken TLS or network boundaries.

Other remedies, including parsers, upgrades, dependencies and arbitrary executable
configuration, remain proposed maintenance in private operational notes; do not
apply them. A shared harness/evidence defect, revoked permission, account-limit
or authentication blocker stops affected recovery rather than cycling models.
Other seats may continue. Two unchanged requests are not distinct corrections.
Client-internal retries remain separate: pinned OpenCode permits up to five retries
per failing processor stream, using headers or bounded backoff (normally capped
at 30 seconds without headers), all under the same external deadline; two outer
corrections do not mean two HTTP requests. Status retains unknown origin and
upstream billing/cancellation separately from safe transport codes.

## Phase-specific replacement

During investigation, replace only that seat on the original sealed source. During
critique, a new candidate's `member` packet first contains independent source only,
under the current critique deadline; it must not see peers. After the main
coordinator accepts all pending catch-ups and stops their supervisors, batch them
through `publish-generation`. Rerun every critique whose packet changed. Same
candidate corrections reuse the same generation. Accepted superseded critiques
remain private evidence and accounted usage, never mixed into the active round.
At the critique deadline, an unsettled-but-stopped catch-up is excluded and the
newest retained qualifying coherent generation supplies the entire synthesis
packet and its participant bindings, even if a published successor did not obtain
a usable critique. Reports from different generations never combine; no running
owner can be ignored. No recovery borrows the synthesis reserve.

A failed chair can be corrected or replaced during synthesis only, in a fresh
session over the same sealed phase evidence. Its separately sealed attempt packet
adds reviewed [verification findings](protocol.md#verification-findings) from prior
chair rejections, when available. Apply the existing verification gate to those
issues before accepting the replacement; no additional round or budget is granted.
Free prefers an eligible already-successful
external participant, then an eligible new free shortlist candidate. Paid groups
keep an eligible native chair. Its original chair seat owns the three-replacement
allowance even on role transfer. This does not rebuild valid earlier rounds;
status discloses separate investigation/critique/synthesis identities.

## Status and cancellation

Version-3 `status` adds candidate/attempt lineage, remaining per-tenure allowances,
role bindings, `critique_generation`, selected `synthesis_generation`, superseded generations, all-owner stop
requests and accounting across accepted, failed, rejected and superseded attempts.
Cancellation stops new research and inference; terminate every returned exact
supervisor/participant handle and retain uncertainty until observed stopped.
Proven local stop never claims upstream cancellation. Preparation/launch retain
the original consent revision, scope and admission checks. Lost responses resume
the original identity or block; never invent a new tenure to bypass ownership.

## Bounded learning

Private bounded learning uses `council-recovery-history.json` beside the existing
private discovery store, with the same private atomic-file/locking helpers and at
most 256 records. Records retain route, client/profile/configuration signature,
source URLs/check dates, correction and host-verified outcome without source
content or credentials. One success is provisional; matching conditions, current
capabilities and independent report verification are required on reuse. A failed
trial blocks the same correction/signature and invalidates an earlier provisional
success. Changed client/profile/configuration does not inherit old evidence.
