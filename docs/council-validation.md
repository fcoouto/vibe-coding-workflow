# Council validation

Reviewed on **30 October 2026**, Europe/Amsterdam. The original
[Council design](superpowers/specs/2026-10-29-council-design.md) is dated
29 October. Council is a user extension, with
[source coverage](policy-sources.md) maintained during authoring. This document
records qualification; it does not authorize a Council run or activate a route.

## Evidence classes

| Evidence | Result and scope | Remaining limit |
| --- | --- | --- |
| Package validation | `python3 -B scripts/validate.py`: PASS; Council entry 107 words, within 150; skill-directory discovery includes Council | Reports `client_execution: not_checked`; does not prove installed-client visibility or loading |
| Skill validation | OpenAI skill-creator `quick_validate.py skills/council`: valid; UI metadata names Council, default prompt includes `$council`, implicit invocation disabled | Frontmatter/scaffold validation is not behavioral qualification |
| Local contract checks | Local Markdown targets/anchors, UI YAML and whitespace checked; request/receipt descriptions reviewed against implemented runtime and CLI | No authenticated model or host settings inferred from prose |
| Focused runtime tests | Integrated fix `3b8b097`: Council 64 tests and OpenRouter 85 tests, all 149 PASS; exact fixed-file and retained-log hashes checked | These focused results cover the final correction; no full-suite replay or real endpoint qualification |
| Full repository suite | Original source `3f1bdcc`: 1,362 tests, 5,757.524 seconds, exit 1; 21 failures, 6 errors, 1 skip; source unchanged | All 27 FAIL/ERROR case IDs reproduce before Council; the full gate still failed and predates the final correction |
| Independent implementation/security review | Whole-branch review through `e024129`, then scoped review of `3b8b097`; both P2 findings and the P3 summary issue closed | Review does not establish the missing live execution observations |
| Controlled OpenCode tool qualification | Observed pinned OpenCode 1.19.5 read/glob/grep allow and deny behavior, including the v2 shared-output correction described below | Local SSE fixtures supplied tool calls; no real endpoint inference or actual model reasoning/token behavior observed |
| Instruction paths | Six Task 5 author walkthroughs over explicit raw fixtures, described below | Static source review by the author; later native canary is separate and does not establish installed-skill loading |
| Nonsecret host identity observation | In this task's existing delegated shell, `CODEX_THREAD_ID` identified a distinct child UUID while `CODEX_SESSION_ID` retained the parent session UUID | One host observation only; not a Council run, universally portable identity API or independent authentication |
| Native functional canary | **Observed**, with synthetic external process reports; three fresh native children, one critique round and fresh synthesis; local runtime outcome `complete` | Configured native controls and completed host states verified; execution model/effort telemetry unknown; no forced cancellation, long-wait cadence or real three-provider concurrency qualification |
| Actual cross-provider Council | **Observed incomplete**, four paid external assignments and three fresh native phases in 1,014.271 seconds; all local execution stopped | Opus investigation failed with a reported content filter; its critique exceeded the word bound and was rejected. Full-roster qualification, settled billing and upstream settings remain unverified |
| Runtime groups and Free execution | Grouped runtime and local admission checks pass; fresh Free session observed all seven external assignments, distinct sessions and local stops in 254.020 seconds | Outcome **partial**: three accepted investigations, one accepted critique, rejected synthesis; no usable Free Council verdict or full-roster qualification |
| Comparative quality/cost | **Deferred separate experiment** | Operation does not establish superiority, reliability rate, token savings or avoided spending |

Task-local raw logs, source resolution and walkthrough inputs/reviews are retained
privately under `.superpowers/sdd/2026-10-29-council/` in the development worktree.
They are authoring evidence, not required installed runtime assets. The Task 5 and
Task 6 reports inventory their exact paths, commands, targets and comparison
artifacts. Package checks and this table do not replace missing actual execution
observations.

## Pinned tool boundary: observed

The controlled qualification used OpenCode **1.19.5**, executable SHA256
`feaafead8cd563af0c2dcb386b0757e4355e327ebb6bd1aaad5440fe2f83596c`, with a
throwaway private data/auth directory, approved harmless text and a local SSE
fixture that supplied tool calls without inference. No account credential or real
provider request was used. Profile **`council-readonly-v2`** supersedes v1.

Original qualification observed approved read/glob/grep success; outside
read/glob/grep errors; unavailable bash/edit/webfetch; no shell marker and unchanged
input. The narrower follow-up reproduced a bypass in OpenCode's automatically
allowed prior-run truncated tool-output directory: glob and grep could expose a
harmless shared-output canary even though ordinary outside access was denied.

The shared executor now adds the exact canonical selected data directory's
`opencode/tool-output/*` deny that suppresses OpenCode's automatic allow. It retains
that same selected `XDG_DATA_HOME` and does not copy keys or change authentication.
The corrected controlled transcript checks twelve generated calls: approved input
read/glob/grep complete; ordinary outside read/glob/grep, shared cached-output
read/glob/grep and bash/edit/webfetch fail. Canary text is absent from every
successful output; the shell marker is absent and approved input unchanged.

Task 3 retains the RED/GREEN transcripts (`task-3-shared-output-red.json` and
`task-3-shared-output-green.json`), controlled harness and assertion results.
Task 5 reviewed that provenance and implementation; it did not rerun the probe.
The version-specific source basis is recorded in the [source map](policy-sources.md).
A new executable/version/profile requires requalification. The shared fix applies
to ordinary workers too, with their resource defaults unchanged. It denies rereading
this run's own truncated cached output as well; approved input reads remain usable.

These are OpenCode application permissions and POSIX file protections, not an OS
sandbox against another process with the same user identity. Qualification
references are coordinator-selected observations, not signed worker attestations.
Native filesystem isolation is not supplied; actual native restrictions and their
limits must be reported independently. Fresh native conversation control remains
required.

## Instruction-path source review

Each raw case has a request, synthetic source/status/report evidence and a separate
author review artifact. The author manually compared consequential claims and
objections with the fixture and the applicable local procedure; no claim-ID parser,
automated prose grade or model self-verification supplied the verdict. For explicit
requests the intended runtime path is the Council entry, common procedure, Codex
controls and applicable worker-selection/discovery sections. Management loads only
for requested activation; machine preparation, enrollment, source provenance and
unrelated pilot execution procedures remain outside ordinary deliberation.

| Case | Source review and required behavior | Avoided actions/loading |
| --- | --- | --- |
| Thread splitting | Separate log analysis has an independent evidence boundary; schema/API dependency and shared test database require keeping work together or serialization. Check handoff, ownership and capacity before recommending threads | No new thread-orchestration feature or automatic implementation |
| Unsupported premise | A report claiming automatic whole-history inheritance conflicts with fresh-context controls and scoped briefs. Challenge the premise and retain unobserved general host behavior as unknown | No fabricated host capability or inherited permission |
| Confident false claim | Fixture reports a known external subtotal with unknown total/upstream billing. Critique rejects the assertion that cancellation means zero charge; synthesis preserves the distinction | No balance lookup, billing invention or repeat inference |
| Decisive minority | Two reports favor parallel work based on disjoint files; one identifies a verified shared mutable database. Preserve that objection and its implications despite the majority | No vote-based truth, forced consensus or silent dissent removal |
| Unavailable selected model | Preserve the unavailable seat; native plus the same external accepted in both rounds and accepted fresh synthesis is incomplete. Missing synthesis would be partial | No replacement, provider cascade, reduced effort or new hidden attempt |
| Ordinary coding request | Explicit-only description/UI policy excludes Council. Follow normal task instructions and relevant checks | No Council procedure/client/discovery/management loading or external call in the prospective runtime path |

**Actual actions:** the author read local documents and the raw synthetic evidence,
wrote these private walkthrough artifacts, reviewed prose and API consistency and
ran local validation. No Council `prepare`/`member`, account mutation, model call or
new native child was performed for these cases. The ordinary-coding row states a
prospective runtime loading decision, not an observed automatic skill-selection
trace. These cases establish source coverage and usable instructions; actual model
compliance and generated prose quality were **not run in Task 5**. The later native
functional canary is separate below. Independent pressure cases and baseline/candidate
behavioral comparisons were not performed under Task 5's no-subagent/no-inference
constraints.

## Task 6 functional qualification

**Task 6 remains partial.** At original source
`3f1bdccae93edaae2199a412cbe6a4044107238e`, focused Council/OpenRouter suites
passed 59/83 tests. The single full command
`python3 -B -m unittest discover -s tests -v` then ran **1,362 tests in
5,757.524 seconds**, ending **exit 1: 21 failures, 6 errors, 1 skip**. The outer
harness recorded 5,758.013 seconds and `source_unchanged: true`. This full gate
**failed**; its result is not a full-suite pass for the later fix.

All **27 final FAIL/ERROR case IDs** reconcile to retained comparison artifacts.
Each reproduced at exact pre-Council
`517ef2546b46a6658551183602c907099c43f23e`, with matching complete traces after
normalizing only worktree paths and elapsed timing. No case passed only in the
focused comparison, differed, lacked a baseline test or remained unclassified.
The inventory retains exact commands, candidate/source/baseline refs and owning
source hashes. Several failures stop at fixture publication without a trusted host;
others concern chronology, content admission, delivery rechecks and cross-store
SQLite nesting. Classification did not repair unrelated core behavior or infer
unprinted detailed errors. The bounded watcher stopped after final reconciliation;
it did not replay the full suite.

Independent whole-branch/security review of `517ef25..e024129` found two P2
preparation issues and one P3 summary inconsistency. The integrated correction
`3b8b09771e4e6f6624828b55a28a24a96f90b49e` retains original admission and preflights
complete external briefs; scoped independent re-review closed all three findings,
with no new Critical/Important issue confirmed. Its focused commands
`python3 -B -m unittest discover -s tests -p 'test_council_*.py' -v` and
`python3 -B -m unittest discover -s tests -p 'test_openrouter_*.py' -v` passed
**64 tests in 32.080 seconds** and **85 tests in 46.481 seconds**. Seven integrated
fixed-file hashes and six retained raw proof hashes matched before this factual
update; those 149 tests were not repeated. Package validation is separate and
retains `client_execution: not_checked`.

At original source `3f1bdcc`, a disposable enrolled fixture used real fresh native
children and a fake local external executable, empty private auth directory and
harmless immutable evidence.
External model/provider/capability/profile objects are explicitly synthetic; the
fixture neither uses credentials nor makes external inference requests. The
controlled OpenCode v2 evidence above is retained unchanged, with its original
RED/GREEN provenance, and is not inferred from this fake executable.

All three native phases completed within the 1200-second cumulative budget, with
about **807.6 seconds remaining** at final status. The coordinator verified three
distinct actual child UUIDs through host activity and direct thread records, each
completed/idle with zero commands and file changes. Investigation, one critique
round and fresh synthesis used `gpt-6-astra`, `ultra`, `fork_turns: none` dispatch
controls; actual execution model/effort telemetry remains null. Each accepted native
receipt preserves that distinction and the coordinator's source/stop checks.

The final packet supplied all six hash-verified frozen initial/critique reports and
anonymous execution gaps. The generated synthesis preserved the shared-database
objection, the conditional recommendation, unknown total versus stipulated source
subtotal and local-stop billing caveat. It did not convert agreement into proof.
An advisory caveat remains: the initial investigator's no-peer statement was correct
for its initial phase; the later critic's current-snapshot distinction is not a
decisive original-stage error. Reports remain verbatim; this observation is not a
quality/effectiveness evaluation.

Runtime status was `complete`, all local execution stopped, no outstanding stop
requests, external total null, known subtotal zero and upstream cancellation
unconfirmed. Those are synthetic execution records; the source's stipulated 0.25 USD
subtotal is test data, not canary billing. The source remained unchanged. Explicit
read-only/no-tool briefs and observed zero tool use do not disable tools or provide
filesystem isolation. Resource allowances are supervised budgets, not asserted hard
native transport limits. Forced native cancellation, long-running progress cadence,
three simultaneous real roster members, real endpoint execution and costs remain
**unobserved**.

Private Task 6 evidence retains the exact requests, packets, briefs, reports, native
controls/host checks/receipts, frozen manifests, synthetic worker results/progress,
read-only assertions and SHA256 inventory. No auth directory, credentials, Git
internals or real account configuration was copied into that retained evidence.

Public-only OpenRouter metadata collected on 30 October makes the remaining
preapproval request concrete: `anthropic/claude-opus-5.5` (observed canonical
`20260921`), provider `anthropic`, maximum `max`; and `google/gemini-4-argon`
(canonical `20261013`), provider `google-ai-studio`, maximum `high`, with no fallback.
The distinct-family shortlist uses benchmark observations with retained sources and
timestamps, not an effectiveness claim. Endpoint input maxima and endpoint-specific
effort enums were not exposed; model-level controls and advertised endpoint
parameters are discovery evidence, not observed execution adherence.

The private `task-6-live-request.md` specifies the same harmless source, a
1200-second total including preparation/waits, 600/360/240 phase reserves, three
fresh native children and four external worker assignments. Proposed external
allowances are 32,768 input tokens, 16,384 output tokens and eight steps per
assignment. Each assignment can issue multiple model/API requests for tool steps
and internal transient retries; request/charge counts are variable. OpenRouter owns
monetary enforcement; these resource bounds are not a hard money cap.

The user approved the exact bounded paid request on 30 October. Offline preflight
in the Council development checkout returned `existing_enrolled_runtime_required`;
no Council run or member was created. The approved request excludes automatic
enrollment and configuration changes, so preflight did not create a runtime or
enable Council. Paid authorization is retained; it does not supply checkout setup.

The user then separately authorized temporary enrollment and Council activation
using the existing OpenRouter setup. The approved operational attempt below
completed; the earlier readiness failure did not become an inference retry.

## Authorized paid operational attempt

At source `a4d95fc`, a new disposable Git fixture received temporary schema-1
enrollment, runtime schema 2 and a production `task start` bound to the actual root
session and user authority. Council alone was configured and enabled at revision 2
using the unchanged existing OpenCode/authentication references. This is authorized
temporary enrollment for client observation, not completed project onboarding,
canonical schema-3 adoption or installed-skill enforcement. No key was read or
copied by the coordinator; existing account and billing settings were preserved.

The executable remained OpenCode 1.19.5 with the qualified v2 hash. Public metadata
revalidated both approved aliases/canonical snapshots and exact provider tags.
Requested controls remained Astra/ultra, Opus 5.5/max and Gemini 4 Argon/high, with
the approved finite allowances and no provider fallback. Four original external
assignments and three actual fresh native children ran, with one critique round
and fresh synthesis. Final receipt was recorded after **1,014.271 seconds**, with
**185.729 seconds** left in the 1200-second cumulative ceiling.

| Seat | Investigation | Critique | Synthesis |
| --- | --- | --- | --- |
| Native | Accepted | Accepted | Accepted, fresh child |
| Opus 5.5 | Failed; owned session reports `ContentFilterError` | Rejected: 809 visible words exceeded the approved 800-word bound | Not a synthesis seat |
| Gemini 4 Argon | Accepted | Accepted, 785 visible words | Not a synthesis seat |

Visible-word checks remove only Markdown structural list/heading/horizontal-rule
markers. Reports were not truncated or rewritten. The failed investigation and
rejected critique were excluded from frozen evidence. A pre-attempt admission
returned busy before any first-seat worker directory or member marker existed;
the identical control request then admitted that original seat. No inference was
replayed, no member replaced, and all four approved assignments were used once.

The runtime outcome is **`incomplete`**, not `complete`: native plus the same
external member supplied accepted reports in both rounds and fresh synthesis.
All local execution was observed stopped, with no outstanding stop requests.
Source, copied workspaces and frozen report hashes verified unchanged. Actual
Gemini session records independently show permitted read/glob/grep and denial of
the harmless outside canary and unapproved snapshot-marker read. Denied-tool
errors can expose local permission-rule paths; no outside file content returned.
These application controls remain distinct from OS isolation.

The four owned OpenCode sessions contain 12 assistant model steps, each assignment
within its eight-step ceiling. This does not establish an HTTP request count or
exclude internal retries. OpenCode's known reported external cost subtotal is
**0.6935693 USD**; `external_total_usd` remains **null** and upstream cancellation
unconfirmed. The source-stipulated 0.25 USD is unrelated to that actual-run subtotal.
No independent provider billing receipt/generation ID was observed. Input planning
and per-call output controls are not aggregate transport or monetary caps.

Actual native child UUIDs and completed/idle turns were independently checked;
each used `fork_turns: none` with no tool events. Execution model/effort telemetry
remains unknown. Recorded intervals for the initial native turn and both external
processes overlap locally; this does not establish upstream server concurrency or
successful full-roster deliberation. Client session model/provider fields and configured maximum effort
are not independent attestation of upstream serving provider or reasoning effort.
Presence updates were recorded during the longer critique, but exact end-to-end
UI update cadence and forced cancellation were not independently qualified.
Native inline briefs preserved substantive frozen evidence with Markdown/whitespace
formatting differences; canonical helper packets and exact source/report bytes
remain retained. Provider/account retention settings were not independently
inspected. No comparative arm or effectiveness/savings claim was made.

Private `task-6-live-evidence/` retains allowlisted records, snapshots, original
reports, receipts, filtered session observations and a SHA256 inventory. It contains
no authentication directory, Git internals or private reasoning text. The temporary
Council scope remains enabled for its explicitly selected checkout, with no running
workers; source implementation and live-project enrollment were not changed.

## Reliability follow-up: local proof, 30 October

The user-approved reliability amendment is implemented in `7f1c394`, with
no-clobber publication corrected in `7a7a575` and ambiguous-spawn stop ownership
corrected in `67799dd`. Known pre-launch contention can recover the original
dispatch; critique construction resumes from verified frozen artifacts. Safe
diagnostics, accepted participation and fresh-synthesis availability support
useful reduced-panel delivery. Presentation preferences remain advisory unless
explicitly hard. Original qualification results remain unchanged.

Independent task review closed the artifact-publication race. Final Astra/xhigh
whole-branch review found one further stop-proof integration issue; its scoped
re-review confirmed the correction and found no new Critical/Important breakage.
This is source review, not a new client qualification or a green full-suite gate.

Local proof includes the 172-test affected regression, eight focused checks after
the isolated router-metadata correction, and 78 Council tests after the publication
fix. The final stop-ownership correction passed 114 affected worker/Council flow
tests. These runs overlap; their counts must not be added. Raw RED/GREEN commands
and review reports remain in the private plan workspace. Package and skill
validation passed; the Council entry remains 107 words. Package output continues
to report `client_execution: not_checked`.

Unknown spawn/stop ownership intentionally blocks phase advancement and fallback
until independently reconciled. Abrupt-kill temporary artifacts and a completion
marker with incorrect sealing remain conservative recovery blockers; uncertain
files are preserved. The historical 21 failures and six errors were not replayed
or repaired. No new paid inference, full-roster qualification, model replacement
or comparative evaluation was performed.

## Runtime model groups and Free qualification

The [runtime-groups plan](superpowers/plans/2026-10-30-council-groups.md) adds
Frontier, Balanced and Free selection at invocation, followed by current discovery
for only the chosen group. Commercial rosters are not fixed in the package.
Intelligence, Coding and Agentic indexes inform task-specific selection; missing
scores remain unknown. Paid groups select an appropriate native member, while
Free uses three distinct external models and a fresh external chair, with no
native Council member or fallback. Host coordination and verification still use
the native allowance.

Local proof includes 171 affected tests for the core change, focused checks for
Free documented-default reasoning, 83 Council flow tests after retained-session
history correction, and 162 affected tests after the local admission correction.
These runs overlap and must not be added. Independent task review closed the
freshness-history issue and approved the narrow admission fixes. Package validation
continues to report `client_execution: not_checked`; live observations below are
separate.

Final integrated Astra/xhigh review found no Critical or Important source finding.
Its nonblocking discovery-guidance recommendation was corrected at `9ae3c4b` and
approved in one scoped re-review. Council workers now receive bounded phase-aware
directions to source, peer reports, research and anonymous observations in their
copied workspace. The internal snapshot marker is explicitly denied and unnecessary.
No full file inventory is appended, and ordinary worker prompts, objectives,
permissions and execution limits remain unchanged. Ten focused checks passed,
including three actual local synthetic phase executions. This wording correction
received no further live inference and does not change the partial result below.

The user selected Free for the live test. Runtime public metadata selected
`thinkingmachines/inkling-small:free` and `thinkingmachines/inkling:free`, both
requesting their observed maximum `max`, plus
`nvidia/nemotron-3.5-super-vl:free`. The latter exact route documents reasoning on
by default but exposes no effort selector. Its default was preserved by omitting
the entire reasoning option; the upstream maximum mapping remains **unverified**.
The initial chair was Inkling Small. These are this session's observed selections,
not future defaults or a universal quality ranking. Exact route rates were zero.
NVIDIA's free endpoint excludes confidential/personal input; only the existing
392-byte harmless synthetic evidence was supplied.

The first test at `bad0f92` exposed two local startup defects before the affected
models launched: a Council lock error escaped bounded admission, and an exact D4
lock-busy error was masked as unavailable storage. One Inkling investigation
completed and was accepted; the session was cancelled and remains **partial**.
The unstarted prepared owner subsequently observed cancellation through the
existing execution guard, with OpenCode launch explicitly prohibited. All original
owners were then confirmed stopped. Original unsettled and settled records remain
retained; no terminal attempt or model inference was replayed.

The narrow correction at `1754424` moves the original Council ceiling into final
bounded admission and recognizes only the exact plain D4 lock-busy error. Active
or uncertain ownership and unrelated storage failures still block. Real-lock and
three-process fixtures prove bounded original-owner recovery without increasing
inference retries or deadlines. A scoped independent review approved the patch
before one fresh changed-code qualification.

That fresh session executed all seven original external assignments under the
same 1200-second cumulative ceiling and 600/360/240 phase reserves. Per-assignment
allowances remained 32,768 input tokens, 16,384 output tokens and eight steps.
At verification, elapsed time was **254.020 seconds**. All seven actual session
IDs were distinct and every local execution was confirmed stopped. Original
source, copied workspaces and frozen report hashes verified unchanged.

| Seat | Investigation | Critique | Fresh synthesis |
| --- | --- | --- | --- |
| Inkling Small | Accepted | Failed after launch; retained client category `unknown` | Rejected: malformed interruption/internal-state text and unsupported claims |
| Inkling | Accepted | Rejected: report said source and peer contents remained unread and requested bypassing deny rules | Not chair |
| Nemotron 3.5 Super VL | Accepted | Accepted with an explicit unsupported report-availability caveat | Not chair |

Acceptance records source-grounded substantive findings, not endorsement of every
incidental inference. All original reports remain verbatim. In particular, some
reports incorrectly describe anonymous reports as unavailable; later-phase frozen
peers were supplied. The malformed synthesis was rejected for usability and
evidence problems, not its advisory word count. No permission was broadened in
response to the rejected request. No model was retried, replaced or given a
native fallback.

Final outcome is **`partial`**, with 3/3 investigations, 1/3 critiques and 0/1
accepted synthesis. `fresh_synthesis_available` is false; no usable Council verdict
was delivered. The client-reported known external subtotal is **0 USD** and six
assignments reported complete zero-cost accounting, but the failed critique leaves
`external_total_usd` **null**. Source-stipulated historical 0.25 USD is unrelated.
No independent provider billing or serving-model/effort attestation was observed.
This test establishes bounded all-external execution and truthful failure handling;
it does not qualify reliable Free deliberation or comparative effectiveness.

Private evidence is retained under
`.superpowers/sdd/2026-10-30-council-groups/`, including original partial records,
the fresh run's approved request, packets, source checks, result/progress copies,
frozen manifests and SHA256 inventory. Credentials and auth-directory contents
were neither read nor copied. Existing temporary enrollment and saved consent
were reused without account, provider-billing or configuration changes.

## Next qualification

Full three-member qualification remains open. A further authorized run should retain real model/effort controls,
context and identity evidence, exact native admission/stop ownership when active,
approved immutable bytes, observed progress, external permission qualification and
actual nullable accounting through fresh synthesis. Check cancellation and degraded
outcomes using safe scopes and existing limits. Never change accounts, permissions,
provider or billing to fill a missing observation. Report unavailable conditions
rather than replacing them with fixtures.

The [value experiment](superpowers/experiments/2026-10-29-council-value.md) remains
separate and deferred. It must compare a strong native baseline and Council from
the same initial task/evidence under comparable recorded controls, with independent
source-based judgments, observed costs and predefined limits. No quality or savings
claim follows from this implementation or the controlled tool probe.
