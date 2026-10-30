# LLM Council runtime groups

Approved direction: the user requested implementation and a live test after the
Astra/xhigh selection review and architecture addendum. This document records
those decisions; it adds no fixed commercial roster.

## Behavior

On explicit LLM Council invocation, first ask **Frontier / Balanced / Free**.
Do not construct all three rosters before asking. Resolve only the chosen group
at runtime from applicable native guidance and existing bounded OpenRouter
discovery, refreshing under its existing cache rules. Show actual identities,
routes, reasoning, listed rates, scope and finite bounds before inference. Reuse
applicable authorization; ask only for genuinely missing scope or approval.
Pin the resulting roster for this session, not future sessions.

- Frontier selects the strongest eligible native model plus two strong external
  candidates using current relevant benchmarks, capabilities and family variety.
- Balanced selects a capable group-appropriate native model and two capable
  external candidates with a defensible lower-cost tradeoff. Do not inherit the
  Frontier native choice or promise measured native quota savings. Overlap in
  external candidates is acceptable when justified.
- Free selects three distinct eligible free external models. One selected member
  is the chair and synthesizes in a fresh external
  session. No native investigator, critic, synthesizer or fallback participates.
  Native host coordination and verification remain outside Council membership
  and still use the host's normal allowance.

All groups keep three independent investigations, exactly one anonymous critique
round and fresh synthesis. Paid groups use their selected native member as chair.
Models, routes and efforts are observations at runtime, never hardcoded lists.
The user's subsequent vendor clarification requires seeking three eligible model
developers first, with developer reuse allowed when bounded discovery cannot find
three. Native membership and replacements follow the same rule; hosting providers
are separate from model developers. The complete rule is maintained in the common
procedure's [vendor selection contract](../../../skills/council/references/selection.md#model-vendor-diversity).
Use maximum supported reasoning when selectable, or documented fixed behavior.
The user clarified during implementation that capability and the Intelligence,
Coding and Agentic indexes are primary; missing scores remain unknown, and task
fit determines emphasis without an invented combined score. For Free, absent
effort labels alone must not exclude a capable model. An exact route's documented
reasoning-enabled default may be preserved without an effort/budget override,
with maximum mapping explicitly unverified. Do not relabel that mode as fixed
high/max or claim observed upstream settings. Required tool/privacy compatibility
still precedes ranking. Free request variants must survive canonical resolution;
all applicable external inference rates must be zero. No paid/provider/model
fallback, native takeover for Free, or extra inference retry is introduced.

## Smallest architecture

Retain the existing Python manifest, snapshots, worker records, admission locks,
progress and CLI. Add an explicit grouped request format with three neutral member
IDs and a pinned chair, dispatching by seat kind rather than member name. Legacy
ungrouped requests/manifests remain readable and keep their historical outcome
meaning. Do not migrate or relabel retained qualification evidence.

Paid grouped rosters contain one native and two external members, with native
chair. Free rosters contain three external members with a free external chair.
Selection rationale and bounded price/identity observations travel with the
session, using existing fields where sufficient. Reject malformed topology,
duplicate model seats and Free variant/rate violations before any inference.
An unavailable full roster is disclosed; a smaller run is never started silently.

External synthesis needs its own sealed packet containing original approved
evidence, accepted initial reports, accepted critiques, research and anonymous
execution observations. It must not reuse the earlier critique snapshot or inflate
the existing 16,000-character objective. Reserve snapshot file/byte capacity for
all synthesis artifacts before launch. Freeze and recover these artifacts with
the existing no-clobber and identity checks.

Extend the existing external worker contract to synthesis. Record actual distinct
OpenCode sessions for grouped external phases; synthesis must be a new session
with no inherited conversation. Unknown freshness blocks synthesis acceptance,
but does not erase local-stop ownership or reported costs. Host verification
still checks scope, citations and acceptance. It must not replace failed external
synthesis with its own substantive verdict.

For grouped runs, complete means three accepted investigations, three accepted
critiques and accepted fresh chair synthesis. Incomplete means at least two same
members accepted in both rounds plus accepted fresh synthesis. Otherwise report
partial evidence. Coverage and synthesis availability remain separate facts,
independent of native participation. All external attempts, including chair
synthesis, contribute to progress, nullable accounting and exact stop requests.

## Preserved constraints

Separate saved Council consent and original revision; approved immutable bytes;
semantic secret review and provider-specific transmission scope; exact pinned
OpenCode 1.19.5 and `council-readonly-v2` tool boundary; qualified permissions;
maximum supported reasoning where selectable and truthful documented-default
handling for Free; finite per-model allowances and the default
1200-second cumulative ceiling; source-based criticism and decisive dissent;
safe diagnostics; no duplicate inference; proven local-stop ownership; advisory
presentation targets with explicit hard requirements preserved; unknown upstream
settings, cancellation and billing stay unknown. No coordinator/account change,
new service, dependency, ranking engine, UI, release or comparative evaluation.

## Live proof

After implementation and independent review, use the authorized disposable scope
and existing OpenRouter setup. Default to Free unless the user chooses another
group. Resolve and show actual eligible routes and finite bounds before launch.
Use a short harmless synthetic evidence file, not private repository source or
permission-denial probes inside member questions. One Council session permits
three investigations, three critiques and one fresh synthesis assignment, with
no outer replay or hidden replacement. Existing bounded client retries remain.

Check source-supported findings, full membership/freshness, artifact hashes,
progress, accounting and local stop. Report incomplete or blocked participation
honestly. Package tests, local wire fixtures and live endpoint observations are
separate evidence. If Free lacks three eligible routes, do not buy replacements
or relax constraints; report the specific blocker and continue any independent
local proof. No paid experiment or broad suite replay is implied.

## Alternatives and decision

A shared strongest native across groups was rejected by the user. A static preset
list was rejected: selection must happen at runtime. A generic orchestration or
ranking framework adds no required behavior. The selected approach extends the
existing three-member executor and keeps selection in the existing coordinator
procedure. The bounded Astra review is retained in the private Council evidence
workspace; portable runtime instructions do not load that authoring history.
