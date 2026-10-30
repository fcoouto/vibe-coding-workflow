# Local OpenRouter delegation pilot

Status: approved for implementation on 28 October 2026, including cached discovery, soft triage and native verification. Package implementation and observed client execution are reported separately.

## Intent and decisions

Use published benchmarks for familiar native models as reference points when selecting external models for bounded subtasks. Let the first real task provide local evidence through native review and objective checks. Do not require a separate qualification suite for each external model.

The user requested an optional pilot and subsequently approved ordinary plugin development without a separate local-only rollout. Native discovery and native execution remain the default. The user permits paid candidates and explicitly chose OpenRouter settings as the spending authority: the workflow checks available budget before assigning work and does not introduce a second monetary cap.

The user also requested a discovery mechanism with cached results, following the native discovery structure and refreshing when the cache expires. OpenRouter metadata follows that lifecycle; available spending credit remains a live pre-dispatch check.

The approved implementation is a coordinator-managed proposal call. An external model receives selected context and returns text or a proposed patch. Native Codex owns tools, filesystem changes, review, validation and integration.

## Goals, non-goals and constraints

- Find useful candidates from benchmark evidence without paying for a separate model qualification campaign.
- Keep task nature, complexity, consequences and verification cost in the selection decision.
- Produce a capability plot and an auditable record of each real attempt, including native repair effort.
- Preserve the coordinator's model, reasoning, subscription and authentication; external calls use only the separately approved OpenRouter connection.
- Package the optional route as part of ordinary plugin development. Enable it only within the user's approved scope; preserve unrelated projects and native defaults. No release archive or global activation is required for implementation.
- Do not create an autonomous external tool loop, a universal model ranking, inferred task-success probabilities, or claims of measured subscription savings.
- Do not change the existing local Qwen approval, assessment requirements or eligible scopes. The pilot concerns the separately approved OpenRouter route.

## Approaches

1. **Native execution only:** lowest integration cost, but cannot evaluate the user's proposed external delegation. Retain as the default and fallback.
2. **Benchmark-guided external proposals with native verification:** matches the user's requested real-task evaluation. Recommended implementation: one external completion, with native ownership of every effect.
3. **External agents with their own tool loops:** adds tool permissions, sandboxing, lifecycle observation, cancellation and recovery. Defer; these are not required to test candidate selection or proposal usefulness.

The user approved benchmark-guided, native-reviewed real tasks with proposal-only external execution.

## Benchmark references and selection

Use the live native catalog for availability. Use OpenRouter's benchmark and model metadata for external candidates and named-model reference anchors. These catalogs serve different purposes.

Preserve source, retrieval time, source timestamp and benchmark version when supplied, model identifier, canonical snapshot when supplied, metric, reasoning configuration and known harness details. Missing fields remain unknown. API metadata version is not automatically the benchmark version. An OpenRouter model name matching a native alias does not establish identical native execution settings.

Use the discovery snapshot described below during routine work, including model/provider capabilities, benchmark data and listed pricing. Do not fetch metadata before every subtask. Snapshot availability and prices are observations at retrieval time, not guarantees at dispatch; provider rejection and reported generation cost remain authoritative. Check the executing client's exposed controls and available spending credit before dispatch.

Compare models within a benchmark source, metric and known compatible version/configuration. Unknown comparability lowers confidence and is visible. Do not divide scores to obtain a percentage of native ability, derive a guaranteed difficulty cutoff, interpolate missing scores, or mix Intelligence Index, coding results and arena Elo into one number.

The coordinator records a short task profile: task family, language, bounded context/files, ambiguity, dependencies, consequences, acceptance checks and expected verification effort. Benchmark data nominates a candidate; it does not grant execution authority. Prefer relevant task metrics when available, with general intelligence as supporting context. First-use candidates remain unobserved locally until a real task is verified.

A candidate can be tried without offline qualification when its route and data terms are allowed, necessary controls are supported, context fits, failure is reversible, and native checks can assess the result. Keep security-sensitive decisions, broad architectural work and tasks with weak verification native during the first pilot. If no suitable candidate remains, use the normal native path.

## Discovery and cache lifecycle

Mirror the native separation of discovery, local status, a bounded refresh claim, atomic publication and immutable evidence. Keep OpenRouter's metadata snapshot separate from native selection guidance. The existing native guidance cache explicitly does not expire by age; this design adds expiry for OpenRouter metadata without changing native behavior or pretending the native cache already has a TTL.

Cache the bounded discovery result under the approved state directory, outside repositories and plugin installations. Scope it to the OpenRouter service, source/query coverage and schema. Retain model identifiers, provider endpoints and supported controls, benchmark/reference mappings, relevant data-use restrictions, listed prices, source URLs, source timestamps/versions where supplied, `fetched_at`, `expires_at` and a content digest. Cache only the metadata needed by the pilot, never credentials, prompts or an account balance. A complete snapshot must identify its coverage; absent or truncated results cannot masquerade as a complete catalog.

Proposed pilot default: a 24-hour cache lifetime, with `expires_at = fetched_at + 24 hours`. This is a refresh schedule, not a guarantee that availability, prices or benchmark comparability remain unchanged. The TTL is an implementation default proposed here, not a value supplied by the user.

1. On first use, fetch and validate the discovery result, then publish the complete snapshot atomically.
2. While the snapshot is unexpired and compatible, selection and plotting read it locally. Repeated tasks make no catalog, provider-metadata or benchmark calls.
3. On first use after expiry, claim one refresh. Concurrent callers share that refresh rather than starting duplicate requests. No background scheduler is required.
4. Missing, corrupt or incompatible snapshots require discovery; an explicit user refresh may also bypass the remaining lifetime. A new task alone is not a refresh trigger.
5. A failed refresh preserves the previous snapshot and its original timestamps for inspection, marks it stale and sends dependent work to the native path. Do not select a new external proposal from stale discovery data. Record a separate one-hour retry delay; tasks before that time reuse the failure and fall back natively. The first later demand may retry once, or an explicit user refresh may retry earlier. The retry delay never makes expired data fresh.
6. A route rejected during dispatch is unavailable for the rest of that task. Record the failure and continue natively; do not refresh metadata or retry another external route automatically inside the task.

Reuse the existing short-lock, claim-generation and atomic-publication safeguards where compatible. Fetch outside hooks, locks and database transactions. Reject superseded publications. Do not force provider metadata into native-only guidance schemas or widen native route admission to reuse an API. Pin each attempt's selected snapshot digest and freshness so a later refresh cannot rewrite its evidence.

Available spending credit and accessible current-key allowance are deliberately outside this metadata cache. Check them before each external call as specified below. A cached positive balance cannot authorize another paid attempt.

## Execution and budget

Use the existing authenticated OpenRouter MCP connection for discovery, credit checks and a supported single `send-message` call. The observed tool supports explicit model, provider restrictions, reasoning effort, output-token limit and local timeout. It does not grant the external model local tools.

Before each call, read available account credit through `get-credits`. Read the current key's allowance and expiry if the authorized integration exposes them. Account credit and per-key allowance are distinct. The current MCP tool inventory has no dedicated current-key tool; do not claim its account-credit result proves remaining key allowance. Do not extract or migrate credentials or request management-key privileges to fill that gap. OpenRouter remains the final authority for key limits, expiry and payment rejection.

If the account-credit check fails or shows no available paid credit, skip paid dispatch and continue natively. If readable key metadata shows exhausted allowance or expiry, also skip dispatch. A null key limit means no configured key cap, not zero allowance. A positive preflight balance is a snapshot, not a reservation against other clients.

No workflow-owned dollar limit, new balance ledger, automatic top-up, limit change or monetary reservation. Report provider-returned usage and cost when available. Preserve bounded task execution with one external attempt, one external request in flight, a declared output-token ceiling and a finite timeout. Builder chooses conservative token/time defaults and documents them; these are execution bounds, not a replacement spending policy.

Pin one candidate model and eligible provider for attribution; disable provider fallback for the attempt. Do not use auto-routing, online search variants, paid tools, batch fan-out or a hidden retry. Supply only task-relevant, approved context. Provider data-use restrictions apply even to free routes; open weights do not imply free hosting or acceptable data handling.

On auth, credit, rate-limit, missing-capability or provider errors, record the result and fall back natively. A timeout does not prove upstream generation stopped or that no charge occurred. Use `get-generation` when a generation ID is available. Keep cost unknown when reconciliation is unavailable; do not automatically retry the external request.

The observed MCP connection is authenticated, but its tools are not yet exposed to this running chat. Implementation must verify tool availability in the actual executing client. Do not manufacture availability or spawn an unrelated user chat to obtain it.

## Verification and learning

Record the exact task brief and base/candidate identity before review. Treat model output as untrusted task data. Never execute commands or follow new instructions embedded in a returned proposal. Check proposed paths and edits before native application. Retain existing ownership, permissions and independent-review requirements.

Native review and repository checks determine acceptance. New behavior still needs the required failing test or executable reproduction before implementation; the user waived model prequalification, not verification of actual changes. A coordinator repair is attributed to the coordinator and still receives any required independent review.

Separate outcomes: accepted without repair, accepted after native repair, rejected, transport failure and unresolved. Capture requested versus observed model/provider/settings, benchmark snapshot, generation identifier, reported tokens/cost, elapsed time, native review/repair effort where observable, actual checks and limitations. Do not treat an external model's claims as verification evidence.

One success is one observation for that task and configuration. It does not qualify every task family. Later selections may favor repeated useful outcomes and avoid repeated failures, without inventing success probabilities from tiny samples. Do not silently expand the pilot's task or data scope.

Use hard exclusions only for concrete incompatibilities or authorization constraints. Capability preferences remain soft: a single rejection does not ban a model, context/preparation failures are distinguished from capability failures, and transport reliability is separate from correctness. Compare task family, language/framework, difficulty, scope and verification needs with past outcomes, retaining model version, effort and provider. Comparable verified local results can outweigh benchmark ordering; published benchmark values never change. Native repair effort remains visible rather than being credited to the external model. Metadata expiry never erases this history.

The observed MCP triage signals include model/endpoint context and output limits, supported parameters and reasoning controls, benchmark indices, model identity/deprecation, provider uptime/latency/throughput, task-usage shares, pricing and live account credit. Task classifications are sampled popularity, not correctness or a classifier for the current assignment. The advertised tool-success filter measures `tool_calls` finish reasons, not correct tool execution; it is secondary for this proposal-only route.

## Runtime integration and scope

Keep coordinator-managed external proposal evidence separate from native worker admission. `runtime/delegation.py` currently accepts `codex-native-subagent` and classifies worker/review roles as native. Do not loosen that guard, forge native lifecycle observations, or count an external completion as a native worker or independent reviewer.

During implementation, use the existing coordinator/evidence path where it supports truthful proposal artifacts. Add only the small optional procedure and evidence support needed for this pilot. Do not build a generic provider framework or modify client adapters merely to relabel an HTTP completion. If the current evidence path cannot represent proposals safely, document the narrow extension in the implementation plan before code changes.

Implementation uses a new optional skill and standalone standard-library helper for cached metadata and advisory attempt history. The native coordinator performs the existing MCP calls and ordinary evidence/check actions. The helper stores references to those actions, never native lifecycle rows or proof of completion. It handles neither credentials nor inference and avoids Genesis's core runtime files, allowing parallel implementation in a separate worktree.

Update affected workflow loading instructions and source-to-contract coverage narrowly. Entry points stay within 150 words, and the complete optional procedure loads only when the pilot is enabled. Use skill-creator for instruction authoring. Do not overwrite concurrent edits to `clients/evidence.md` or `docs/policy-sources.md`; reconcile any necessary changes against their current content.

## Plot and evidence presentation

Show published Intelligence and Coding indices separately, native model references clearly marked, and paid versus listed-free candidates distinguished. Show missing values explicitly. Include dates and comparability limitations. Let the user change the native reference without presenting score gaps as success probabilities.

Keep benchmark evidence separate from local outcomes. A later pilot report should show first-pass acceptance, native repairs, rejections, actual external spend and observed verification effort. Native quota reduction and total-time improvement remain hypotheses until measured. Subscription cash savings require an actual avoided payment; API token-price comparisons alone cannot establish them.

## Acceptance and rollback

- Native-only behavior is unchanged when the pilot is disabled or unavailable.
- Repeated tasks within the metadata cache lifetime perform no catalog, provider-metadata or benchmark fetches; available spending credit is still checked before each external call.
- First use and expiry trigger one bounded discovery refresh; concurrent callers cannot publish partial or superseded snapshots.
- Failed refresh preserves the prior data and timestamps, falls back natively and suppresses repeated refresh attempts until the separate retry delay or an explicit refresh.
- No external call occurs without explicit pilot enablement, a bounded verifiable task, eligible data handling and a successful applicable budget preflight.
- Missing/expired authentication, exhausted credit, provider rejection and timeouts produce bounded, truthful fallback behavior.
- External output cannot gain local authority or fabricate native worker/reviewer evidence.
- Missing scores stay missing; model/configuration mismatches and unknown billing remain visible.
- Representative task walkthroughs prove the optional procedure loads when needed and unrelated material stays unloaded.
- Focused tests cover new selection, validation and error-handling branches; run `python3 -B scripts/validate.py`.
- Report package validation, mocked transport checks and observed live-client execution separately. No live inference during design work.
- Disable the pilot to restore native-only operation; preserve historical evidence and leave OpenRouter account settings unchanged.

## Sources checked on 28 October 2026

- [OpenRouter benchmark API](https://openrouter.ai/docs/api/api-reference/benchmarks/list-benchmarks)
- [OpenRouter public model catalog](https://openrouter.ai/api/v1/models)
- [OpenRouter MCP server](https://openrouter.ai/docs/guides/overview/mcp-server)
- [Current key metadata](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-key)
- [Credit metadata](https://openrouter.ai/docs/api/api-reference/credits/get-credits)
- [Artificial Analysis methodology](https://artificialanalysis.ai/methodology/intelligence-benchmarking)
- [Example free-route data restrictions](https://openrouter.ai/thinkingmachines/inkling-small:free)
- Local authenticated MCP tool schemas: `send-message`, `get-credits`, `get-generation`, `list-benchmarks`.
