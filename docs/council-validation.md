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
| Runtime tests | Council snapshot/flow and worker tests exercise synthetic scopes, harmless processes, bounds, replay, phase gates, stop/launch ordering and unknown accounting | Fixture behavior is local contract proof; final integration test results must be reported separately |
| Controlled OpenCode tool qualification | Observed pinned OpenCode 1.19.5 read/glob/grep allow and deny behavior, including the v2 shared-output correction described below | Local SSE fixtures supplied tool calls; no real endpoint inference or actual model reasoning/token behavior observed |
| Instruction paths | Six author walkthroughs over explicit raw fixtures, described below | Static source review by the author; no independent agent, native runtime loading or live generated critique/synthesis observed |
| Nonsecret host identity observation | In this task's existing delegated shell, `CODEX_THREAD_ID` identified a distinct child UUID while `CODEX_SESSION_ID` retained the parent session UUID | One host observation only; not a Council run, universally portable identity API or independent authentication |
| Actual cross-provider/native Council | **Not run** | Strongest-native availability/controls, external model/endpoint controls, native permission/context/stop behavior, capacity, progress, actual costs and a complete deliberation need separate observed qualification |
| Comparative quality/cost | **Deferred separate experiment** | Operation does not establish superiority, reliability rate, token savings or avoided spending |

Task-local raw logs, source resolution and walkthrough inputs/reviews are retained
privately under `.superpowers/sdd/2026-10-29-council/` in the development worktree.
They are authoring evidence, not required installed runtime assets. The Task 5
report inventories their exact paths and commands. Package checks and this table
do not replace missing actual execution observations.

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
compliance and generated prose quality remain **not run**. Independent pressure
cases and baseline/candidate behavioral comparisons were not performed under this
task's no-subagent/no-inference constraints.

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
