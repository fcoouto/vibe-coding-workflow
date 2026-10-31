# LLM Council simplification

Status: proposed; implementation waits for the user's review of this design and its [plan](../plans/2026-10-31-council-simplification.md).

## Purpose and decision

Restore the Council's division of responsibility: models evaluate substantive answers; the coordinator manages execution, permissions and reporting. Whole-answer factual rejection removed useful perspectives during the Free live test and consumed time before replacements could run.

The user chose the original project's independent answers, anonymous peer review and chair synthesis. Text-only questions use direct requests. Free is temporarily disabled. Existing safety and spending boundaries remain. This design supersedes the substantive acceptance gate and host-authored correction overlays from the earlier verification plan for new sessions; historical evidence remains intact.

Two approaches were considered: keep the current file-agent transport and tune its factual filters, or remove those filters and use a plain request for text-only deliberation. The user selected the second. A wholesale transport rewrite would disturb qualified repository inspection and is outside this change.

## Session flow

1. Ask the user to choose **Frontier** or **Balanced**. Explain that Free is temporarily unavailable. Discover the roster at runtime using the existing task-aware capability ranking, supported maximum reasoning and vendor diversity rules. Vendor reuse remains allowed when three eligible vendors are unavailable. Each group retains its native participant, two external participants and a fresh native chair context. Preserve the coordinator's settings and avoid buying the selected native model again through OpenRouter.
2. Collect independent initial answers in parallel.
3. Give every technically usable initial answer to the parallel critics under anonymous labels. Ask for strengths, errors, assumptions, uncertainty and a preferred ordering. Preserve each usable critique even if its ranking is missing or malformed. Do not add an aggregate scoring subsystem or exclude low-ranked answers.
4. Give all usable initial answers and critiques to the fresh chair. Ask it to resolve disagreements against the approved evidence, distinguish facts from assumptions, and state uncertainty and meaningful dissent. No extra verification round follows. The coordinator reports actual participation, failures and accounting separately from the chair's substantive answer.

“Usable” means a complete, nonempty terminal text response within execution, size and scope boundaries. It does not mean factually certified. A mistaken claim, unsupported inference, refusal expressed as normal text, disagreement or poor ranking does not trigger rejection, correction or replacement. Critics and the chair handle those issues. The coordinator may disclose an observed concern to the user without deleting or silently editing the report.

Malformed transport output, API errors, missing terminal text, truncation, unsolicited tool calls on a tool-free request, violated execution boundaries or an observed privacy/identity disclosure remain technical failures. Keep the original report privately for audit; do not distribute an unsafe report. Checks must not require models to use a bespoke answer JSON schema or treat lack of citations as a transport failure.

## Text and repository modes

Add one required preparation field, `mode`, with exactly `text` or `repository`. The coordinator selects it from the work needed, without another user menu. Both modes are stamped internally with `flow: "peer-review"` and remain fixed throughout the run, including replacement attempts.

**Text:** no independent file inspection is needed. Send the approved question, constraints, shared research and exact approved evidence contents directly to external models, followed by the appropriate anonymous phase reports. A question alone permits `approved_files: {}`. Seal the same private snapshot and question binding; do not create evidence files in the user's checkout. Local snapshot paths and credentials never enter the request. Reject scopes that do not fit the chosen endpoint instead of truncating or silently changing mode.

Use a small Python-standard-library requester for `POST https://openrouter.ai/api/v1/chat/completions`, with `stream: false`, pinned model/provider, `allow_fallbacks: false`, supported reasoning and finite output allowance. No tools, file-agent loop, conversation history or previous response ID. Selection must confirm text-only Chat Completions compatibility; no speculative API conversion. Use `require_parameters: true` for requested controls so unsupported parameters cannot be silently discarded.

Text seats retain the current model, provider, pricing, context and reasoning records. Their `capabilities.tools` is Boolean and need not be true. Add `capabilities.api: "chat-completions"`, backed by the capability record's source and observation time. Their `permission_qualification` is exactly `{profile: "council-text-v1", evidence: "<qualification reference>"}` rather than an OpenCode binary qualification. Set `steps: 1` to declare the single request; recovery owns any further attempts. Repository seats retain the existing tools-required and pinned-binary qualification schema. A text-only seat must never pass repository admission.

The requester runs as an owned child of the existing worker runner. Reuse the runner's admission lock, consent revision, phase deadline, output bound, progress heartbeat and process-group cleanup. Add a transport branch; do not build a second supervision framework. The connector's message call lacks the locally owned stop handle required by this contract, so the owned requester is the selected implementation approach.

Read only the saved OpenRouter API-key record from `<auth_data>/opencode/auth.json` inside that child, using the existing private auth directory. Validate its provider and `type: "api"`; unsupported or missing credentials fail before sending. Do not copy, migrate or log credentials, accept prompt-supplied endpoints, follow redirects or inherit alternative API-key overrides. Keep the current setup/settings schema and installation prerequisites; removing OpenCode as an installation prerequisite is deferred, although text execution never invokes it.

Persist a real provider generation ID when returned, nullable usage/cost, a sealed local attempt identity and the actual transport. A generation ID is not an OpenCode session ID. Direct freshness is proven by the owned attempt, immutable request hash and fresh stateless launch. Never invent observed model, effort, cost or upstream cancellation confirmation.

**Repository:** retain the existing qualified OpenCode read-only inspection of the approved snapshot. Apply the same peer-review flow without substantive filtering. Require compatibility with the actual installed API path and tools. Models requiring Responses for tool calling are ineligible on an unqualified Chat Completions route; a speculative OpenCode upgrade is outside scope. Do not replace independent inspection with a coordinator-only summary.

## Boundaries retained

- Saved Council consent, project/scope and settings revision must still match at launch. External transmission stays within the approved question, evidence, research and generated phase reports. No new provider, authentication setup or paid fallback is authorized by a failed call.
- Preserve immutable originals, snapshot/path safety, anonymous phase packets, native supervisor ownership, fresh contexts and cancellation. No new capabilities or writes enter repository workers.
- Preserve the original 1,200-second session budget and default 600/360/240-second phase allocation. Preparation, coordination, waits, recovery and synthesis consume that budget. Preserve current finite token/output allowances and snapshot limits: 2,000 files, 512 KiB/file, 32 MiB total; reports and research are each at most 128 KiB. Reserve phase headroom without the removed correction-note files. Preserve the 2 MiB control-request bound.
- Keep bounded recovery for technical failures: parallel isolated seat work, one investigation of at most 120 seconds excluding workaround application, at most three searches/five page reads, two evidenced workaround attempts and three replacements per seat. Apply all attempts within the original phase/session time and approved spending scope. No community investigation for ordinary answer disagreement. No new retry layer inside the HTTP requester.
- Show ongoing progress and honest complete/partial/incomplete outcomes. Use existing participation rules, now counting technical usability rather than substantive agreement. Never label a single surviving perspective as a full Council. If no initial answer survives, stop; if the chair fails, report the incomplete result and preserve available reports.

## Disable Free and preserve history

Hide Free from new selection and reject `group: "Free"` at preparation and every inference launch, including resume, replacement and direct helper entry. Never substitute paid models automatically. Retain historical Free manifests, prices, reports and accounting.

Runs without `flow: "peer-review"` are historical and read-only except cancellation and operational stop/accounting settlement. Status remains available. New inference or verdict mutation requires a new run with the current consent and modes; never reinterpret or rewrite a past verdict. Keep the old decoding and audit checks needed for those records, but do not expose the old semantic-feedback mechanism in new runs.

## Delivery and proof

Change the shared runtime and its callers once; keep `LLM Council` and the existing `council` settings route. Update the short skill and stage references rather than append another exception section. Maintain source-to-contract coverage. Defer comparative evaluation, Free requalification, fallback-pool redesign and any universal Responses adapter.

Prove the flow with the actual disputed fixture types: “no external forcing function,” an assumed three-hour drive and an unsupported relocation conclusion. All complete safe answers must reach critics and the chair unchanged. Prove tool-free direct requests, private credential handling, fixed routing, cancellation/deadlines, technical-failure recovery, blocked Free launches, historical readability and unchanged repository inspection using fake endpoints and synthetic evidence. Package validation and observed live execution must be reported separately. A new paid end-to-end run is a separate explicit step after approval; this planning task performs none.

## Sources checked during authoring

- [Original Council flow](https://github.com/karpathy/llm-council/blob/master/backend/council.py): independent answers, anonymous rankings and synthesis from returned reports.
- [OpenRouter provider routing](https://openrouter.ai/docs/guides/routing/provider-selection): explicit provider selection, disabled fallbacks and required parameters.
- [OpenRouter reasoning](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens): model-specific supported reasoning controls.
- [Pinned OpenCode auth contract](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/auth/index.ts): provider-keyed API record and saved auth file. No user credentials were read during planning.

The small requester, mode field and historical read-only policy are proposed implementation choices, not previously approved product requirements. Review them with this plan.
