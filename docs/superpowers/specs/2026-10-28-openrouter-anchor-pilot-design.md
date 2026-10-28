# Local OpenRouter delegation pilot

Status: proposed design for approval. No external inference or workflow activation has occurred.

## Intent and decisions

Use published benchmarks for familiar native models as reference points when selecting external models for bounded subtasks. Let the first real task provide local evidence through native review and objective checks. Do not require a separate qualification suite for each external model.

The user requested an optional pilot in this local checkout before publication. Native discovery and native execution remain the default. The user permits paid candidates and explicitly chose OpenRouter settings as the spending authority: the workflow checks available budget before assigning work and does not introduce a second monetary cap.

The proposed implementation is a coordinator-managed proposal call. An external model receives selected context and returns text or a proposed patch. Native Codex owns tools, filesystem changes, review, validation and integration. This implementation choice is proposed for approval.

## Goals, non-goals and constraints

- Find useful candidates from benchmark evidence without paying for a separate model qualification campaign.
- Keep task nature, complexity, consequences and verification cost in the selection decision.
- Produce a capability plot and an auditable record of each real attempt, including native repair effort.
- Preserve the coordinator's model, reasoning, subscription and authentication; external calls use only the separately approved OpenRouter connection.
- Keep the pilot explicitly enabled only for this local workflow copy. Do not publish, create release archives, enable unrelated projects or change native defaults.
- Do not create an autonomous external tool loop, a universal model ranking, inferred task-success probabilities, or claims of measured subscription savings.
- Do not change the existing local Qwen approval, assessment requirements or eligible scopes. The pilot concerns the separately approved OpenRouter route.

## Approaches

1. **Native execution only:** lowest integration cost, but cannot evaluate the user's proposed external delegation. Retain as the default and fallback.
2. **Benchmark-guided external proposals with native verification:** matches the user's requested real-task evaluation. Recommended implementation: one external completion, with native ownership of every effect.
3. **External agents with their own tool loops:** adds tool permissions, sandboxing, lifecycle observation, cancellation and recovery. Defer; these are not required to test candidate selection or proposal usefulness.

The user selected benchmark-guided, native-reviewed real tasks. Proposal-only execution is the narrow implementation recommended here; it is not yet approved as the implementation design.

## Benchmark references and selection

Use the live native catalog for availability. Use OpenRouter's benchmark and model metadata for external candidates and named-model reference anchors. These catalogs serve different purposes.

Preserve source, retrieval time, source timestamp and benchmark version when supplied, model identifier, canonical snapshot when supplied, metric, reasoning configuration and known harness details. Missing fields remain unknown. API metadata version is not automatically the benchmark version. An OpenRouter model name matching a native alias does not establish identical native execution settings.

Read existing cached metadata during routine work. Refresh on explicit request, relevant catalog change or scheduled maintenance through the existing guidance-maintenance pattern. Do not contact every benchmark service before each subtask. Check current route availability, pricing and budget at dispatch.

Compare models within a benchmark source, metric and known compatible version/configuration. Unknown comparability lowers confidence and is visible. Do not divide scores to obtain a percentage of native ability, derive a guaranteed difficulty cutoff, interpolate missing scores, or mix Intelligence Index, coding results and arena Elo into one number.

The coordinator records a short task profile: task family, language, bounded context/files, ambiguity, dependencies, consequences, acceptance checks and expected verification effort. Benchmark data nominates a candidate; it does not grant execution authority. Prefer relevant task metrics when available, with general intelligence as supporting context. First-use candidates remain unobserved locally until a real task is verified.

A candidate can be tried without offline qualification when its route and data terms are allowed, necessary controls are supported, context fits, failure is reversible, and native checks can assess the result. Keep security-sensitive decisions, broad architectural work and tasks with weak verification native during the first pilot. If no suitable candidate remains, use the normal native path.

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

## Runtime integration and scope

Keep coordinator-managed external proposal evidence separate from native worker admission. `runtime/delegation.py` currently accepts `codex-native-subagent` and classifies worker/review roles as native. Do not loosen that guard, forge native lifecycle observations, or count an external completion as a native worker or independent reviewer.

During implementation, use the existing coordinator/evidence path where it supports truthful proposal artifacts. Add only the small optional procedure and evidence support needed for this pilot. Do not build a generic provider framework or modify client adapters merely to relabel an HTTP completion. If the current evidence path cannot represent proposals safely, document the narrow extension in the implementation plan before code changes.

Update affected workflow loading instructions and source-to-contract coverage narrowly. Entry points stay within 150 words, and the complete optional procedure loads only when the pilot is enabled. Use skill-creator for instruction authoring. Do not overwrite concurrent edits to `clients/evidence.md` or `docs/policy-sources.md`; reconcile any necessary changes against their current content.

## Plot and evidence presentation

Show published Intelligence and Coding indices separately, native model references clearly marked, and paid versus listed-free candidates distinguished. Show missing values explicitly. Include dates and comparability limitations. Let the user change the native reference without presenting score gaps as success probabilities.

Keep benchmark evidence separate from local outcomes. A later pilot report should show first-pass acceptance, native repairs, rejections, actual external spend and observed verification effort. Native quota reduction and total-time improvement remain hypotheses until measured. Subscription cash savings require an actual avoided payment; API token-price comparisons alone cannot establish them.

## Acceptance and rollback

- Native-only behavior is unchanged when the pilot is disabled or unavailable.
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
