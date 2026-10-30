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
| Actual cross-provider Council | **Not run** | Real external model/endpoint behavior, tool/model request counts, actual billing, upstream cancellation and full real-provider deliberation need separate observed qualification |
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

The request remains **not dispatchable**: explicit bounded paid approval, saved
route/runtime readiness, current capacity and alias-to-canonical revalidation are
still required. Real provider inference, endpoint behavior and billing remain
unobserved. No external provider inference, comparative evaluation, credential
read, account change, install or release was performed. Package, controlled-tool,
native-canary and focused-test proof do not fill the missing real-provider,
forced-cancellation, concurrency, sustained-progress or installed-skill observations.

## Next qualification

A separately authorized operational run should retain real model/effort controls,
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
