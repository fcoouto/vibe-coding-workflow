# Council

Status: proposed design, awaiting user approval. Written on 29 October 2026.
No Council execution or implementation is authorized by this document alone.

## Intent

Provide a Council skill for consequential questions that benefit from independent
investigation and criticism. Users invoke it in their existing coding workflow,
use their native account for native participants, and use their own OpenRouter
credits for external participants. The result is an evidence-backed recommendation,
including the strongest reasons against it and unresolved objections.

The motivating request asks whether splitting substantial development into fresh
threads would improve this workflow. Council must inspect existing delegation,
handoff, ownership, review and runtime behavior before recommending another
feature. It must distinguish separate conversations, native subagents and file
isolation, challenge the premise, and consider rejection or a bounded experiment.
The quoted conversation is evidence to evaluate, not instructions to implement
thread orchestration. That feature is outside this design.

## Decisions made with the user

- Use independent investigations, exactly one critique round, then synthesis.
- Members may inspect the repository independently to find concrete evidence.
- Several minutes is acceptable, provided progress remains visible.
- Include the most capable available native model as one Council member.
- Select the other frontier models using OpenRouter benchmark data.
- Use the maximum available reasoning level for frontier participants.
- Give synthesis a fresh native context rather than reusing a member's context.
- Preserve the user's native coordinator model, reasoning and authentication.

## Approaches considered

1. Independent investigation followed directly by synthesis: less work, but no
   opportunity for members to challenge one another's evidence.
2. Independent investigation, one critique round, then synthesis: bounded work
   with explicit scrutiny of competing conclusions. The user selected this.
3. Adaptive deliberation with additional rounds: potentially useful for difficult
   disputes, but less predictable duration and cost. Not selected.

The user subsequently selected a fresh synthesis context. It avoids carrying an
individual investigator's conversational commitment into the final assessment;
it does not prove absence of model-family bias or guarantee correctness.

## Proposed defaults for approval

These are designer recommendations, not decisions already made by the user:

- Three investigative seats: one native and two OpenRouter, preferably from three
  distinct model families. Avoid purchasing the native member's model again.
- A fresh instance of the selected strongest native model performs synthesis,
  also at its maximum supported reasoning level. The existing coordinator owns
  orchestration, progress and delivery, without changing its own settings.
- First supported surface: an enrolled Codex POSIX checkout, matching the existing
  saved OpenRouter controls. General questions outside enrolled repositories and
  other client adapters are follow-up work, not silently supported routes.
- Council runs only on an explicit request for Council or equivalent multi-model
  deliberation. Routine development may suggest it but does not spend credits.
- Read-only investigation and advice. No implementation, shell execution of
  repository code, package installation, commits or external messages by members.
- A 20-minute total run ceiling, including all phases and waits; reserve time for
  critique and synthesis before admitting investigation. This is an upper bound,
  not an expected duration or a monetary allowance. Users may request a different
  finite ceiling before launch.
- Return a concise decision in chat with a private local detailed report and
  inspectable member findings. Do not save research in the repository by default.

## Selection and reasoning

Resolve the native seat from actually available dispatch controls and the
platform's applicable cached official guidance. Interpret "most capable" for the
question at hand; do not equate model recency, price or name with capability.
Follow existing guidance refresh rules. Keep commercial model identifiers out of
portable skill rules, and retain selection evidence for each run.

Use the existing OpenRouter discovery cache and benchmark sources. Prefer relevant
reasoning, coding and agentic assessments for repository decisions; preserve source,
date, benchmark version, tested settings and coverage gaps. Do not turn popularity
into a quality score or average incompatible benchmark scales. Explain the chosen
pair and any tradeoff between a higher score and independent model-family coverage.
Benchmarks inform selection but do not qualify tool use or establish superiority
on this specific question. Require compatible, qualified tool-capable endpoints.

Pin the roster, endpoint routing and reasoning choices for the entire run.
Request each model's highest supported reasoning setting through its actual
execution route. Do not assume similarly named settings imply equal compute.
For fixed-reasoning models, document that no adjustment exists. Unknown supported
settings cannot be advertised as maximum reasoning; resolve eligibility before
launch or surface the unmet requirement. Record configured/requested settings and
observed execution separately; unavailable execution telemetry remains unknown.

Allocate sufficient context and output allowance for maximum reasoning plus useful
answers. The existing worker's 2,048-token response ceiling is not a Council
default. Finite token, step, file and report bounds remain necessary; the builder
must choose and qualify them using representative investigations. Do not silently
lower effort or truncate away objections to fit a bound. If no eligible roster can
be formed, explain the missing capability rather than quietly substituting models.

## Evidence and repository access

Before dispatch, freeze the selected checkout's approved content into a private
snapshot with a manifest and content digests. Include approved working-tree changes
as well as committed content, and identify that snapshot in every finding. Later
checkout edits do not alter an active Council's target.

Give every member and the synthesizer equivalent access to the same snapshot and
scope manifest. Members independently list, search and read its approved contents;
the coordinator does not select only files supporting a preferred conclusion.
Missing material remains visible as a coverage gap. Resolve requested scope
additions during preparation; freeze repository content before investigation.
After that barrier, omitted repository material remains a gap for a later run,
not a reason to restart members or exceed the single critique round. Independent
discovery means equal access, not identical files read or conclusions reached.

Preserve existing transmission authorization and inspect the selected scope for
secrets before any external access. Exclude credentials, private runtime/auth state,
Git internals, links escaping the approved root, and unapproved nested repositories.
Report material exclusions and size limits. Ignore repository instructions that
attempt to expand permissions or treat retrieved content as coordinator authority.

The external route uses private copied files, not unrestricted access to the user's
live checkout. Broadening the current 16-file pilot requires explicit permission
qualification and meaningful scope limits. Native members receive the same content
scope; native tool availability is not permission to inspect unrelated user data.
Distinguish application-level restrictions from an OS-enforced sandbox. External
read/write boundaries require qualified application enforcement. Native workers
use supported tool restrictions where available, explicit read-only scope and
coordinator verification; current native delegation does not provide filesystem
isolation. Do not describe that declared native scope as technically enforced or
build a new OS sandbox as part of this feature. Record this access-control
asymmetry; equal approved evidence does not imply identical harness capabilities.

For supplied public references or claims needing current sources, the native
coordinator can retrieve public material with its authorized read-only research
tools and publish it to the shared evidence set. Research gathered during
investigation is included in the common packet before critique begins. Freeze
that packet at the critique barrier. Later findings can identify a gap or qualify
the synthesis, but cannot be represented as having received Council-wide critique.
This is a proposed bounded
research bridge, not unrestricted network access for external workers. Do not send
private repository text in web searches. Each finding states what was inspected,
what was inferred and what remains unverified. Inaccessible sources remain gaps.

## Execution

### 1. Prepare

Resolve explicit request, question, selected repository, scope and saved consent.
Check runtime and model availability without treating a configured connection as
proof of execution. Prepare the snapshot, common brief, run identity, roster,
resource reservations, limits and stop conditions. Show the roster, requested
effort, scope summary and run ceiling. Reuse existing authorization; do not add
confirmation at every phase or require an account-balance lookup.

The brief asks every member to evaluate the question fairly, including the best
case for and against the proposal, existing alternatives, user benefit, costs,
failure modes and evidence that would change its conclusion. A request such as
"tell me why not" calls for serious criticism, not a forced negative verdict.

### 2. Investigate independently

Start eligible members concurrently when qualified capacity permits. Each member
gets a fresh context with the same question, constraints, snapshot and tool scope.
Do not share initial answers between members before their reports are frozen.

Each report contains its recommendation, material claims with file/source
references, opposing evidence, assumptions, uncertainty, alternatives and suggested
verification or experiment. Reports are bounded and structured enough to validate
references and omissions, without requiring a numerical confidence score.

### 3. Critique once

Freeze the initial reports and distribute the same anonymized set to each member.
Keep model identities in the audit record but omit them from deliberation packets.
Anonymization reduces explicit identity cues; style and self-recognition can still
reveal authorship. Do not claim blind evaluation has eliminated bias.

Each member gets one critique assignment. It may inspect the snapshot to verify a
disputed claim, must challenge unsupported assertions, and may revise its position.
The report names objections that survived, objections resolved by evidence and
changes of view. Critique is not a popularity vote, and no additional debate round
starts automatically. Member critique contexts may retain their own investigation;
they never receive the coordinator's unrelated conversation.

### 4. Synthesize in a fresh native context

Start a separate native worker with no inherited investigator or coordinator chat
history. Supply the original question, constraints, shared evidence manifest,
initial reports, critiques, coverage/failure records and output contract. Keep the
deliberation reports anonymized; retain true identities separately for attribution.
The worker may read the snapshot and supplied sources to check decisive claims.
It cannot launch another debate round or invent missing evidence.

Require a direct recommendation, strongest reasons for and against it, implications
for users, unresolved minority objections, evidence gaps, and conditions that would
change the recommendation. Use implement/reject/experiment when appropriate to
the question, not as a compulsory template for every topic. Agreement is not proof.

The original coordinator checks the delivered report for source support, coverage
and contract compliance, then presents it with accurate attribution. Council does
not replace ordinary implementation tests, required independent code review, or
release authority. Delivery itself never starts implementing the recommendation.

## Controls, state and recovery

Extend the existing management owner with a distinct `council` route so existing
worker/proposal opt-in does not silently authorize a larger paid workload. Council
uses the configured OpenCode credentials and runtime references plus the native
account. Existing configurations remain valid; Council starts disabled. A direct
request to enable Council can authorize scoped management, but a design discussion
does not activate it. Keep setup, enrollment, activation and invocation separate.

Reuse current private-state, consent guards, generation identity and accounting
patterns. Maintain one private run record and immutable phase artifacts, separate
from the proposal discovery/history store, which must not hold prompts or reports.
Use stable member/phase attempt identities to prevent accidental duplicate billing.
Inspection or recovery after a chat interruption does not automatically replay an
inference call. Preserve exact snapshot/roster references and known partial results.

Recheck saved consent at each external phase admission. Disable blocks future
admissions while already-admitted work may settle under its original limits.
Cancellation stops new phases and requests local termination; establish local
quiescence before takeover. Acknowledged cancellation or timeout does not prove
upstream execution stopped or that no further charge occurred.

Keep existing ownership of transient retries in OpenCode. No outer inference retry
loop, provider cascade or silent model substitution. Each phase has finite time,
step and output bounds inside the overall deadline. Respect actual native slots
and any supervisor requirements. Council-only concurrency must be qualified;
ordinary worker pilot limits are not broadened incidentally.

A failed member does not invalidate other findings. An incomplete Council verdict
requires at least two successful investigations, including the native seat, and
completed critiques from at least those two members, each addressing the other's
report. Deliver a clearly marked incomplete Council synthesis identifying missing
participants and stages. One surviving critic is insufficient. Otherwise return
a partial evidence report, not a completed Council
verdict. A failed or unavailable fresh native synthesizer also leaves partial
results; the coordinator must not impersonate a fresh synthesis context. Any retry
or changed roster is a separately authorized attempt, not automatic recovery.

Retain reports locally in private run storage, outside Git, with no new remote
content export or observability collector. OpenRouter receives only content within
the authorized investigation scope through the existing authenticated route.
Content retention follows existing approved provider/account choices; this feature
does not promise deletion at providers or modify those choices. The builder must
document finite local storage limits and report capacity errors before admission.

## Visible progress and costs

Use the existing chat and qualified worker visibility mechanisms, not a new UI.
Show preparation, investigation, critique, synthesis and terminal status, with each
participant's real role/model and observed completion or failure. A native
supervisor is not mislabeled as the externally executing model.

Emit updates on phase transitions and meaningful observed events. During long
waits, provide a concise presence/status update at least every 60 seconds where
the host supports it. "Still active; no new event" is truthful; fabricated file
activity, percentages, retry counts, countdowns and hidden reasoning are not.
Disclose host visibility limits before launch if this requirement cannot be met.

Report external model usage/cost when observed, known subtotals and unknowns.
OpenCode-reported cost and OpenRouter billing are distinct sources; do not present
one as reconciled with the other without evidence. Keep native account consumption
separate; no invented dollar equivalent or subscription savings. OpenRouter owns
spending enforcement. A runtime ceiling or token bound is not a hard dollar cap.

## Implementation boundaries

Build on the existing Python runtime and OpenCode worker route, with a native
coordinator contract. Keep the Council entry point within 150 words and load its
complete local procedure only when invoked. Use existing package discovery and
client-adapter organization; no separate web app, general workflow engine, new
authentication stack or automatic project enrollment.

Expected affected areas are a Council skill and procedure, Council-specific
orchestration/state, bounded snapshot access, management route validation,
OpenRouter worker integration, relevant native adapter controls, progress/report
contracts, tests, README discovery and source-to-contract coverage. Reuse existing
helpers without weakening their default behavior or duplicating shared rules.
Toolkit remains authoring authority; Council is an explicit user extension.
Routine Council execution must not fetch Toolkit or require a Toolkit checkout.

The builder owns exact file layout, schemas, numeric resource defaults other than
the proposed total ceiling, and the smallest qualified mechanism for continuation
between investigation and critique. Those choices must preserve phase independence,
model/effort pinning, fresh synthesis and truthful accounting. A missing required
control is a reported capability gap, not permission to weaken the design.

## Validation and completion

Run `python3 -B scripts/validate.py` and relevant runtime tests. Cover:

- Unchanged native coordinator settings; strongest eligible native selection;
  benchmark provenance and distinct external selection; maximum effort requests
  and truthful unknown execution settings.
- Same approved immutable snapshot for all members; independent file discovery;
  secret/path exclusions; external out-of-scope reads, writes and execution denied;
  native scope instructions, actual behavior and enforcement limits checked
  separately. Scope additions after the repository freeze remain coverage gaps.
- Initial answers hidden until frozen; exactly one critique round; no investigator
  chat inherited by synthesis; minority objections preserved in the final report.
- Consent changes between phases, replay prevention, finite deadlines, cancellation,
  provider failure, missing members, absent synthesis and partial accounting.
- Honest phase/participant visibility, including no-progress waits and failed
  delivery; no synthetic activity inferred from a heartbeat.
- Existing proposal and worker behavior and existing saved settings compatibility.

Exercise representative instruction paths, including the user's thread-splitting
question, a request with an unsupported premise, a planted confident-but-false
member claim, a decisive minority objection, an unavailable model and an unrelated
routine coding task that must not load Council procedures or launch paid work.

Package tests and instruction walkthroughs do not qualify actual client execution.
Separately observe native model/effort dispatch, fresh context, permitted/denied
OpenCode tools, progress rendering and a complete cross-provider Council run under
specific live-run authorization. Keep unsupported surfaces explicit.

Compare Council's output against a strongest-native-only investigation using the
same evidence and a declared evaluation rubric: supported claims, missed material
objections, actionable conclusions, elapsed time and observed usage. This tests the
value hypothesis; neither higher cost nor consensus establishes improvement.
Design approval is followed by an implementation plan; it does not itself prove
execution, effectiveness or release readiness.

## Builder check

A fresh native reviewer read this design before presentation. Its three questions
were resolved as designer calls: freeze repository scope before investigation and
the shared research packet before critique; retain explicit native read-only scope
without claiming filesystem isolation; require two completed reciprocal critiques
for a degraded verdict. These choices add no deliberation round or new sandbox.
The reviewer inherited session model/reasoning settings; exact execution settings
were not independently observed. This check is design review, not client execution.

## Design references

- [Karpathy's LLM Council](https://github.com/karpathy/llm-council): inspiration for
  independent answers, anonymized review and synthesis, not a runtime dependency.
- [Agent delegation](../../../policies/03-agent-delegation.md) and
  [native delegation](../../../clients/delegation.md): selection, ownership,
  native controls, evidence and recovery.
- [OpenRouter workers](../../../skills/openrouter-workers/references/procedure.md)
  and [proposals](../../../skills/openrouter-proposals/references/procedure.md):
  current execution limits, discovery and accounting contracts.
- [OpenRouter management](../../../skills/manage-openrouter/references/procedure.md):
  checkout consent and admission ownership.
- [OpenRouter models](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties)
  and [reasoning controls](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens):
  current capability metadata; available controls still require route qualification.
- [Policy source map](../../policy-sources.md): Toolkit provenance and existing
  user extensions. Update coverage alongside implementation, not in routine runs.
