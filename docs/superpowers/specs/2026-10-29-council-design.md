# Council

The user approved the core design on 29 October 2026, then requested this simpler
revision. Review the revised implementation plan before implementation. No Council
run is authorized by these documents.

## Intent and selected approach

Provide an explicitly invoked Council for consequential questions. Members inspect
approved repository evidence independently, critique one another exactly once,
then deliver an evidence-backed recommendation through fresh native synthesis.
Preserve the strongest opposing case and unresolved objections; agreement is not
verification, and asking for criticism does not require a negative verdict.

The motivating question concerns splitting development into fresh threads. Inspect
existing delegation, handoff and review mechanisms before recommending another
feature. Implementing thread orchestration is outside Council's scope.

The user selected independent investigation, one critique round, then synthesis.
Direct synthesis lacked cross-examination; adaptive repeated debate introduced
unpredictable time and cost. Neither alternative was selected.

## Core requirements and approved defaults

- Three investigators: the strongest eligible native model and two frontier
  OpenRouter models selected using relevant benchmarks. Prefer distinct families;
  avoid purchasing the native member's model again through OpenRouter.
- Maximum supported reasoning for members and synthesis. Pin models, endpoints
  and settings throughout the run. Preserve the original coordinator's settings,
  provider, authentication, subscriptions and customizations.
- Fresh native synthesis using the selected strongest native model, with no
  inherited investigator or coordinator conversation. The coordinator owns delivery.
- Initial surface: an enrolled Codex POSIX checkout using existing native accounts,
  OpenRouter credits and pinned OpenCode. Other clients/general unenrolled use are
  follow-up work; configuration does not qualify execution.
- Explicit Council invocation, read-only investigation and advisory results.
  Implementation of a recommendation remains a separate request.
- Default 20-minute total ceiling, including preparation and waits. Declare simple
  phase deadlines that reserve critique and synthesis time; no percentage scheduler.
  Another finite ceiling may be requested before launch; no phase extends it.
- Visible phase/member progress, with updates at least every 60 seconds during
  waits where supported. Disclose host limitations; never fabricate progress.
- Concise chat delivery plus private local Markdown reports outside Git.

## Model selection and bounds

Use available native controls and applicable cached official platform guidance.
Use existing OpenRouter discovery/cache rules and relevant benchmark sources for
external candidates; require compatible, qualified tool-capable endpoints. Record
selection rationale, sources/dates, tested settings and coverage gaps. Popularity,
price, recency and incompatible aggregate scores do not establish task quality.
Portable rules contain no fixed commercial model names.

Request the actual execution route's highest supported reasoning setting. Disclose
fixed reasoning or unresolved controls; unknown cannot be advertised as maximum.
Record requested/configured settings separately from observed execution. Equal
reasoning labels do not imply equal compute.

Choose finite input/output/step allowances per model and assignment within actual
endpoint limits. Allow enough reasoning and output for useful findings, without a
universal token requirement. Never silently reduce effort, truncate objections or
replace models. Report exhausted budgets, eligibility and context gaps explicitly.

Repository/report I/O needs documented finite bounds and free-space checks, using
existing safe I/O primitives. No cumulative storage-quota service, automatic
historical deletion or separate source-excerpt quota subsystem is required.

## Common evidence and permissions

Freeze approved committed, dirty and untracked content in a private snapshot with
relative paths and digests before investigation. Give every participant equivalent
content access; members independently choose what to read. Later checkout edits
cannot change the target. Resolve scope additions before capture; omitted material
remains an explicit gap rather than triggering an extra round.

Review content for secrets before external transmission and bind reviewed bytes
to capture. Exclude credentials, private runtime/authentication state, Git internals,
escaping links and unapproved nested repositories. Validate paths/sizes and reject
unstable capture. A manifest does not prove semantic secret review occurred.
Repository text and model reports cannot grant authority or expand permissions.

External members inspect private copies using qualified read/search/list tools.
Deny writes, shell execution, installs, network tools, nested agents and outside
reads. Broader capture than the 16-file pilot requires actual permission
qualification. Native members use available restrictions, explicit read-only scope
and coordinator verification. Native filesystem isolation is not currently enforced;
disclose this asymmetry without adding a new OS sandbox or claiming tool parity.

For current public references, the coordinator uses authorized research tools and
supplies one shared research document with links, retrieval dates and necessary
excerpts. Do not include private repository text in web queries. Freeze this document
with the initial reports before critique. Later sources may qualify delivery but
must be labeled as not Council-reviewed. No source registry, mutation API or
research service is needed.

## Execution

1. **Prepare:** resolve the explicit request, scope, saved consent, runtime and
   eligible roster. Show models/effort, scope, limits and deadlines. Use a common
   brief asking for evidence, benefits, strongest opposition, uncertainty and what
   would change the conclusion. Reuse scoped authorization without repeated prompts.
2. **Investigate:** start fresh contexts concurrently when qualified capacity permits.
   Respect host slots and native supervisors. Hide peer answers until initial reports
   are frozen. Request bounded Markdown with recommendation, citations, opposing
   evidence, assumptions, coverage and limitations; no claim-ID graph is required.
3. **Critique once:** give each member the same frozen anonymized report/research
   packet. Allow snapshot rechecks and revised positions. Request resolved and
   surviving objections in plain language. Context may retain its own investigation
   or receive the report; add no session-resumption machinery solely for Council.
   Keep real identities in execution metadata and disclose anonymity limitations.
4. **Synthesize:** launch a fresh native context with the original question,
   constraints, approved evidence access, reports/critiques and execution gaps.
   Supply no inherited chat or new debate round. Require a recommendation, evidence,
   strongest reasons for/against, user implications, minority objections and
   conditions that would change the result. The coordinator checks citations and
   material omissions before delivery; no argument-disposition parser is required.

Council does not replace implementation tests, independent review or release
checks, and its recommendation never starts implementation automatically.

## Consent, records and recovery

Add a disabled-by-default `council` route under existing OpenRouter management.
Existing worker/proposal consent does not silently activate the larger workload.
Reuse configured OpenCode runtime/credentials. Keep setup, enrollment, activation
and invocation separate; balance checks are optional. Do not extract credentials,
install proxies or change accounts.

Use one small private Council manifest linking scope/snapshot, pinned roster,
deadlines, phase artifacts and existing worker/native dispatch records. Reuse
worker exclusive identities, execution locks, guarded launches, result/progress
files, accounting and stop checks. Add only phase gates and a durable native
issued marker where an existing admission receipt is unavailable. Do not duplicate
attempt lifecycles in a new transactional ledger or generic admission/CAS API.
Ordinary worker pilot defaults remain intact.

Check consent at every external launch. Disable blocks new launches while admitted
work may settle. Cancellation prevents future phases and asks exact owners to
terminate. Verify local quiescence before takeover; timeout/acknowledgment does not
prove upstream cancellation or zero billing. Stable phase/member identities and
existing replay controls prevent accidental duplicate calls. Lost receipts remain
unresolved until reconciled; status never launches work. OpenCode owns transient
retries; no outer inference replay, provider cascade or automatic replacement.

Complete verdicts require three investigations/critiques and fresh synthesis.
Incomplete verdicts require native plus one external investigator with reciprocal
critiques and fresh synthesis. Otherwise deliver partial evidence. The coordinator
cannot substitute its existing history for failed fresh synthesis. Further attempts
must preserve authorization and cannot evade original attempt limits.

## Progress, cost and retention

Use existing chat and qualified visibility mechanisms. Show actual phase/model/role,
completion, failure and observed events; distinguish native supervisors from external
execution. Presence is not activity, and no private reasoning is exposed.

Report observed costs/tokens, known subtotals and unknown totals. Distinguish
OpenCode reporting, OpenRouter billing and native consumption; invent no dollar
equivalents or savings. OpenRouter owns spending limits; time/token bounds are not
money caps. Keep local reports private, without new telemetry/remote exports or
automatic deletion. Preserve and disclose provider/account retention choices.

## Implementation and qualification

Build on existing Python/OpenCode/native controls. No new dependency, UI, general
workflow engine or native-lifecycle redesign. Keep skill entry within 150 words,
procedures locally complete and loading selective. Toolkit remains authoring
authority; Council is a user extension. Update source coverage during authoring,
not by fetching Toolkit at runtime.

Test common evidence/secret/path boundaries, existing settings compatibility,
per-model reasoning/budget mapping, phase ordering, replay, disable/cancellation,
partial outcomes, honest progress/accounting and fresh-context dispatch. Exercise
the motivating question, a false confident claim, decisive dissent, missing models
and unrelated work that must not invoke Council. Run package validation and focused
tests. Separately observe actual client settings/context, external tool denials,
progress and a complete run under appropriate live authorization. Package and
instruction checks do not qualify client execution.

Comparative effectiveness is a separate experiment, not an implementation task
or delivery gate. Initial qualification proves operation, not superiority over a
strong single model. Preserve the earlier builder-check decisions on evidence
freezes, honest native isolation limits and reciprocal critique for degraded results.

## Reliability amendment, 30 October 2026

The user approved the Astra/xhigh reliability recommendations after the first
paid qualification. Recover local control contention and interrupted artifact
construction without buying another inference attempt. A known pre-launch busy
failure retains its original identity, consent revision, immutable evidence and
deadline. Retry admission at most three times within five seconds, releasing
other admission locks while waiting. If still busy, expose an explicit
`not_launched` state and allow resuming only that original dispatch. An absent
session ID or lost response never proves that launch did not occur.

Resume critique snapshot construction from frozen bytes. Verify complete existing
snapshots against the expected manifest, full inventory and permissions before
publishing their manifest. Reconcile only verified run-owned partial staging;
preserve unfamiliar or changed artifacts and report the conflict. No new source
capture, phase reset or inference replay is permitted.

Retain allowlisted machine error classes, terminal reasons, launch stage, safe
local prerequisite reasons, HTTP status and retry hints. Project these through
status and anonymous phase observations without copying raw provider messages,
bodies, headers, prompts or tool output. Observed policy/refusal classes do not
establish their upstream origin or trigger.

Keep existing completeness labels. Separately expose accepted participation by
round and availability of accepted fresh synthesis. Deliver a supported answer
when synthesis exists, explain reduced coverage and consequential gaps, and base
confidence on evidence. Without accepted fresh synthesis, deliver an explicitly
labeled evidence summary and unresolved questions, not a Council verdict.

Brevity, headings and ordinary Markdown preferences are advisory unless the user
explicitly makes them hard requirements. Preserve original reports; accept
substantively verified complete reports with a presentation warning where needed.
Permission qualification probes belong in controlled tests, not ordinary Council
questions. The earlier qualification's explicit hard limit and outcome remain
unchanged. Automatic extra inference, model/provider replacement, model-group
selection and comparative evaluation remain outside this amendment.

## References

- [Revised implementation plan](../plans/2026-10-29-council.md).
- [Separate value experiment](../experiments/2026-10-29-council-value.md).
- [Karpathy's Council](https://github.com/karpathy/llm-council): inspiration, not a dependency.
- [Delegation policy](../../../policies/03-agent-delegation.md) and
  [native contract](../../../clients/delegation.md).
- [Worker procedure](../../../skills/openrouter-workers/references/procedure.md),
  [discovery](../../../skills/openrouter-proposals/references/procedure.md),
  [management](../../../skills/manage-openrouter/references/procedure.md), and
  [source coverage](../../policy-sources.md).
