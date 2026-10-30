# Council runtime recovery and parallel seat supervision

Status: approved by the user on 30 October 2026, with a 120-second investigation allowance excluding fix application. The recovery limits and parallel seat
supervision below are user decisions. Details labeled implementation decisions
are proposals. This document does not enable recovery or authorize a new live run.

## Intent and approaches

Deliver a usable Council verdict despite recoverable model or integration
failures. Persist toward the requested outcome, preserve successful work, and
explain actual progress. A failed model should not end the Council while eligible
recovery remains. Completion still requires verified evidence; no system can
guarantee availability or a usable answer within a finite budget.

The earlier approach stopped after a failed assignment, with only original-client
transient retries. A second approach would apply known fixes but only suggest
remedies for unfamiliar failures. The user selected bounded runtime investigation,
source-supported workaround attempts, and automatic replacement, with independent
seat supervisors working in parallel. Arbitrary self-modification and unlimited
retries are outside scope.

This amends the no-extra-attempt/no-model-replacement rules for newly created
recovery-enabled sessions. Historical sessions and their outcomes are unchanged.
Comparative evaluation remains deferred.

## User requirements and limits

- Each failing candidate gets one bounded investigation and up to two justified
  workaround attempts. A workaround requires applicable official support or
  community evidence, or a previously verified correction with that provenance.
  If none is found, move directly to the next eligible model.
- Each seat permits at most three replacements: the original candidate plus up
  to three distinct replacements. Counts persist across phases, process restarts
  and changes of supervisor. Never revisit an exhausted candidate in the same seat.
- All research, waiting, retries, replacements, validation and synthesis consume
  the original session budget. Limits are ceilings, not a requirement to exhaust
  every option. Stop new work at the applicable deadline or exhausted allowance.
- Each seat has an isolated subagent whose objective is to obtain a valid working
  model and an independently verified contribution. Run independent seat work
  concurrently within observed host and provider capacity.
- Preserve the selected group, maximum supported reasoning or existing permitted
  Free default, transmission scope, privacy requirements and account limits.
  Free uses free external members and an external chair. Native supervisors remain
  coordination and verification, not Free Council participants.

Implementation decision: the investigation and two-correction allowance belong
to a candidate's tenure in a seat, not to each failure or phase. Up to four
candidate tenures are possible per seat. Later failures reuse the remaining
allowance; they cannot reset it. A fresh synthesis-only candidate follows the
chair rules below and uses that seat's remaining replacement allowance.

## Parallel ownership and progress

The main coordinator creates the session, supplies current ranked eligible
candidates, and assigns a separate private workspace and immutable brief to each
seat supervisor. These are task subagents, not new user-owned sidebar chats.
Supervisors retain the coordinator's native model, reasoning and authentication
through supported inheritance. They inspect only their own operational evidence
and the approved source packet; independent investigators never receive peer
answers before the critique barrier.

A supervisor handles candidate selection, bounded public research, permitted
corrections, dispatch and evidence collection for its seat. It cannot edit another
seat's files, global settings, plugin code, the source checkout or sealed evidence.
It cannot generate the Council member's substantive report as a fallback.
The main coordinator independently verifies acceptance and publishes shared state
through the existing locked runtime. No worker self-verification grants acceptance.

Candidate claims and launches are serialized briefly under the existing ownership
mechanism; research and inference run outside locks. Canonical model claims prevent
two active seats from selecting the same model. Different advertised aliases of
one canonical model do not provide independence. Failed claims do not consume an
inference attempt. Each seat may have only one live participant attempt at a time.

Reserve native capacity for actual participant dispatch. If the host cannot fit
three supervisors plus needed native participants, the main coordinator owns a
seat directly or queues its supervision while other seats continue. Do not consume
all native slots with supervisors waiting for children. State observed concurrency
honestly; no new scheduler service is needed.

Progress identifies each seat as selecting, working, investigating a failure,
trying correction 1/2 or 2/2, replacing candidate 1/3 through 3/3, accepted, or
exhausted. Report actual progress or a truthful wait at least every 60 seconds.
Successful seats remain accepted while another seat recovers, unless their report's
input evidence changes as described below.

## Bounded diagnosis and permitted corrections

Retain the failing layer: transport, request compatibility, tool execution,
response decoding, resource exhaustion, or substantive report rejection. Preserve
safe machine facts and unknown origin separately. Do not expose raw provider
messages, credentials, source excerpts or private model text in progress or web
queries. Preserve the existing privacy boundary while retaining enough private
evidence to distinguish a model answer from client processing.

Implementation decision: one investigation episode lasts at most 120 seconds and
uses at most three targeted public searches and five source-page reads. Its
deadline is clipped by the current phase and session deadline. It may consult a
matching local recovery record first and end early. Prefer official support and
version-specific reports; community posts provide hypotheses, not instructions or
authorization. Store URLs, checked dates, applicability and the precise proposed
correction. Never post a support ticket or private logs automatically.

Only attempt a correction when the evidence reasonably matches the failure and
our client, provider and request. Two attempts must test distinct justified
corrections; repeating an unchanged failed request is not a second workaround.
A documented transient-connection retry may be one correction. The investigation
may yield two alternatives in its single episode; it need not yield any.

The first implementation supports these bounded changes through validated fields:

- Clarify the actual copied-workspace root, approved relative paths, phase input
  locations and required task result. Do not change source evidence or conclusions.
- Apply a documented request-parameter representation supported by the pinned
  adapter while preserving model, pinned provider, required tools and reasoning
  semantics. No arbitrary configuration object or executable patch is accepted.
- Adjust per-attempt output/step allowances within the originally declared seat
  envelope and remaining phase budget. Do not lower requested reasoning or claim
  OpenCode's prompt-based step threshold is a hard tool-call limit.
- Wait for a documented retry delay or start a fresh owned session/connection once
  the previous local execution is known stopped, when a source-supported transport
  correction applies. Never disable TLS verification or broaden network access.

An unsupported remedy, such as changing a parser, installing a dependency or
upgrading the client, is retained as a proposed maintenance change. It cannot be
applied by an arbitrary script downloaded from a support page. Continue to the
next eligible candidate when that is useful. A confirmed shared-harness defect,
revoked authorization or broken evidence boundary blocks affected work rather
than cycling through models. Unaffected independent work may continue.

Each correction gets a fresh immutable attempt linked to its failure and source
evidence. It is a diagnostic hypothesis until the main coordinator verifies both
operational behavior and substantive contribution. Do not sanitize an unusable
answer into an accepted verdict or ask another model to certify its own success.

## Selection and phase consistency

Reuse runtime discovery and Intelligence, Coding and Agentic evidence with the
existing task-fit and missing-score rules. Prepare an ordered fallback shortlist
as metadata permits, without calling every candidate in advance. Recheck endpoint,
price, reasoning and privacy eligibility before launch. A successful actual
investigation is the initial qualification; do not add a separate paid canary to
every selection. Success in one phase does not guarantee later success.

Replacement is an explicit new candidate with its own validated route. Provider
fallback within one request stays disabled. Choose another eligible candidate
already covered by the session's transmission and spending scope, not a silently
expanded provider or paid route. If none qualifies, preserve the specific blocker.

### Investigation

Replace a failed investigator independently on the same original snapshot, without
peer reports. Preserve other accepted investigations. Close investigation when all
seats settle, or stop remaining owned work at its deadline and proceed with the
available evidence once every prior-phase owner is observed stopped. A deadline
closes admission; it does not prove cleanup or permit crossing the phase barrier.
Do not stop at the first failed seat while recoverable work remains.

### Critique

A correction for the same candidate reruns only its failed critique over the same
sealed packet. A genuinely new candidate must first investigate the original source
without seeing peer reports. This catch-up work consumes the current critique
budget; it does not reopen the investigation deadline.

Its accepted investigation changes the active initial-report set. Publish a new
immutable critique generation and rerun critiques whose input packet changed.
Retain previous generations as superseded evidence; never overwrite them or count
critiques of different report sets as one complete round. Batch concurrent seat
replacements into one new generation after their catch-up work settles. These are
recovery attempts toward one accepted critique round, not extra debate rounds.
Generation rebuilds do not refresh research, repair or replacement counters.

When the critique deadline arrives, use the most recent coherent frozen generation
that supports the existing reduced-panel threshold. Do not sacrifice the synthesis
reserve to obtain a perfect panel. If no generation qualifies, retain partial
evidence and explain the exact limitation.

### Fresh synthesis

Correct or replace a failed chair within the original synthesis reserve. Preserve
accepted investigations and critiques. The replacement chair receives the same
sealed synthesis packet in a genuinely fresh session and performs only synthesis.
It does not inherit another candidate's earlier participation.

Approved implementation decision: allow a synthesis-only chair
replacement without replacing valid earlier contributions or rebuilding critique.
For Free, first prefer another eligible already-successful external participant,
then an eligible new free model. Paid groups retain a group-appropriate native
chair. Choosing another existing participant as chair is a role transfer and still
consumes one replacement from the original chair seat's allowance. The original
seat owns this allowance throughout; changing chair does not obtain another seat's
unused budget. Record distinct investigator, critic and synthesis identities.

Complete means three accepted independent investigations, a coherent accepted
critique from the same three active participants, and an accepted fresh synthesis.
The chair may be a disclosed replacement. The existing reduced-panel threshold of
two same participants accepted in both rounds plus accepted synthesis remains
`incomplete`; otherwise the result is `partial`. A useful reduced-panel verdict is
delivered prominently with its limits, rather than replaced by a generic error.

## Deadlines, ownership and accounting

Keep the current default 1200-second total and cumulative 600/360/240 phase
reserves unless the user requested different bounds before preparation. All seats
share those absolute deadlines; parallelism does not multiply the time allowance.
Keep sufficient synthesis reserve by abandoning further repairs when they cannot
fit the current phase. The configured attempt and replacement counts are maximums.

Token/step allowances remain finite supervised bounds, not a reservation of dollars.
OpenRouter account limits remain the monetary authority. Every retained attempt
contributes known usage/cost; totals stay unknown where accounting is incomplete.
Declare the recovery envelope before inference and preserve any stricter explicit
user spending cap. Do not increase a cap to finish the Council.

Client transport retries and Council workaround attempts are separate. Inventory
and expose the pinned client's bounded internal retries; the outer two-attempt cap
must never be described as a two-HTTP-request cap. They consume the same deadline
and reported account usage. Do not layer additional unrecorded retry loops.

Before any correction or replacement, prove the preceding local owner stopped.
Uncertain local ownership blocks that seat's relaunch while other independent
seats may continue within the current phase. Preserve the existing phase barrier:
every admitted prior-phase execution, including superseded attempts, must be
observed locally stopped before critique or synthesis begins. Supervisors attempt
cleanup using exact owned handles within the remaining budget. If stop cannot be
confirmed, retain ownership and partial evidence; do not manufacture a reduced-panel
verdict by ignoring the unresolved execution. Unknown upstream completion and
billing remain explicitly unknown. For these read-only
workers, they do not falsely establish local ownership or reserve funds. Do not
claim upstream cancellation was confirmed. Preserve admission, cancellation and
scope-revocation checks at every launch, including recovery launches.

Cancellation stops new research/inference and requests termination of exact owned
supervisors and participants. Retain ownership until observed stop. Interrupted
supervision resumes the same state and counters, never a fresh session budget.

## Local learning and smallest implementation

Save a bounded private recovery record with the failure signature, exact model and
provider route, client/adapter/profile version, relevant configuration, source
URLs, correction, verification and outcome. Keep source content and credentials
out. Reuse existing private discovery/history storage and atomic locking where
compatible; no new database, background crawler, shared service or training job.

One verified success is provisional evidence. Reuse only on matching conditions
with fresh capability checks, independently verify every resulting report, and
invalidate a reused correction on failure or incompatible version/configuration.
Failed trials prevent repeating the same correction under the same conditions.
Learning never rewrites permissions, claims benchmark superiority, or treats a
connection problem as proof that a model lacks intelligence.

Use a new manifest version for recovery-enabled runs. Add bounded candidate and
attempt histories, source-backed correction records, role bindings and immutable
critique-generation references to the existing Council runtime. Read versions 1/2
without changing their old acceptance, replay or accounting semantics. Make shared
claims/counters and launches atomic; keep research and deliberation outside locks.

Expected change surface: `runtime/council.py`, `scripts/council.py`,
`scripts/openrouter_workers.py`, the existing proposal-history helper if needed,
Council procedure and Codex adapter, affected tests/fixtures, source coverage and
validation documentation. Keep the skill entry point short. The main coordinator
uses existing native subagent and public research tools; the Python runtime owns
validated state transitions, not a general autonomous research framework.

The planning step must also address the confirmed diagnostic projection loss and
the inconsistent read/grep treatment of internal snapshot metadata without
broadening permissions. Response assembly must distinguish interim versus final
text, while preserving original evidence and not claiming that separation alone
fixes malformed final output.

## Required proof and exclusions

Before live use, prove limits persist across phases/restarts; no-workaround skips
to replacement; two corrections cannot become unlimited retries; fourth replacement
is denied; simultaneous claims cannot duplicate a model; one slow seat does not
block another; cancellation and uncertain ownership prevent unsafe relaunch; and
all attempts count toward deadlines and nullable accounting.

Exercise replacement during each phase, coherent critique-generation rebuilding,
independent catch-up, synthesis-only replacement, Free/native topology and old
manifest compatibility. Include adversarial support-page content, secret-bearing
errors, stale learning, duplicated corrections and exhausted synthesis reserve.
Verify substance through representative instruction walkthroughs and isolated
synthetic executions, then run `python3 -B scripts/validate.py`.

Report package validation separately from observed client execution. Any later live
qualification uses the approved disposable scope and an explicitly applicable
group/budget authorization; it is not comparative evaluation. No release archive,
new provider setup, dependency upgrade or unrelated harness rewrite is included.
