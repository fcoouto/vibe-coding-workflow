# Pilot readiness

Working coordination plan, 2 November 2026. Baseline: main `ed6c45b`.

Goal: reach a verified Codex self-host pilot-ready state while coordinating the workstreams in parallel. Actual pilot activation and the approved Python, Next.js and bounded cross-repository rollout follow readiness. Native operation remains the default. OpenRouter and Langfuse are coordinated here as optional integrations.

## Current goal: ready to activate the self-host pilot

Reach a verified pilot-ready state from reviewed main by completing setup observation and retained lookup, applicable native lifecycle and usage qualification, evidence/recovery, local repository enforcement and manual delivery. Coordinate these owners in parallel with OpenRouter and Langfuse, while serializing shared writes. Keep implementations small, preserve the approved observable-configuration promise and native defaults, and merge completed reviewed slices into main.

The goal is complete only when scoped evidence establishes every mandatory self-host prerequisite, installed behavior is observed, recovery and enforcement checks pass, and the exact authorized onboarding/activation steps are prepared. Green source tests, accepted record shapes and merged helpers alone are insufficient. Optional integrations need their own qualification when selected; unrelated expansion does not delay the bounded native pilot. Actual activation and the broader rollout remain explicit milestones.

Parallel assignments use the existing owners: core implements the genuine setup producer/journal/local reader; Native Clients prepares and qualifies applicable behavior and writer reconciliation; Merge Assurance completes the trusted local gate; Evidence Lifecycle checks the bounded pilot's evidence/recovery requirements; delivery connects verified readiness to manual-merge reconciliation. OpenRouter and Langfuse prepare their selected source/connection qualification alongside these dependencies. The pilot owner integrates matching reviewed outputs and reports readiness.

## Coordination

Root owns dependencies, final reviews and PR merges into main. Reuse the existing core, OpenRouter, Langfuse and delivery chats. Native workers implement bounded independent tasks; Workstreams concepts organize ownership without requiring activation of the plugin's managed runtime. Keep coupled files with one owner and serialize shared state/evidence changes.

Use Sol for coupled implementation and review, Luna for suitable small fixtures and documentation, and Astra for difficult capability decisions or unresolved stalls. Preserve the user's coordinator settings. Select actual worker settings under the existing delegation policy.

## Current slices

| Slice | Next complete outcome | Exit condition |
| --- | --- | --- |
| Activation | The Codex comparison consumes the approved current fields; next implement the genuine setup observer, existing-journal receipts and file-backed production reader. | Genuine observed qualification, current observable inputs and scoped history support activation. The [approved limitation](activation-guarantee-proposal.md) remains explicit; consumer tests alone do not activate the pilot. |
| OpenRouter | Source integration completed in PR41; actual optional client/provider qualification remains separate. | All 90 distinct controls have staged passing evidence, plus package/skill validation and independent review. Controls stay opt-in; installed/live execution is not qualified. |
| Langfuse | Source compatibility completed in PR43; native collection and live connection/source qualification remain separate. | 65 distinct local controls have staged passing evidence, including local HTTPS/fake-keyring CLI/terminal cases. Native-default tasks remain independent; actual usage and D11 remain unqualified. |
| Evidence | Port reviewed execution-provenance improvements in coherent slices; finish compact retention only with matching producers and consumers. | Current-task/recovery requirements pass. A bounded legacy pilot may proceed only if its applicable limits and retention operations already work; unqualified compact/cap behavior remains explicit. |
| Merge and manual delivery | Complete the smallest path from verified candidate to PR readiness and observed manual merge, reusing existing delivery/Git primitives. Define and qualify the local trusted verifier/publisher. | Required checks/reviews and writer reconciliation precede readiness. Disposable enforcement passes before an authorized live settings change. Tests remain local. |
| Pilot | Freeze a reviewed main revision, reuse workspace preparation, update the qualification candidate and establish applicable native behavior and usage in the qualification scope. | All mandatory prerequisites have scoped observed evidence, recovery and enforcement checks pass, and exact authorized self-host activation steps are prepared. Actual activation, a pilot task and the broader D9 rollout remain subsequent milestones. |

Run independent source work in parallel. Agree shared interfaces before overlapping changes. Native activation, D6 stop evidence and D7 trust sources are prerequisites where their claims are required; optional integrations do not supply those missing facts.

## Simplicity review

For each complex control, identify the concrete failure and affected user outcome. Reuse an existing native mechanism or owner when it already protects that outcome. Consolidate repeated observations within their valid scope; rerun only affected proof after relevant changes. Keep technical receipts out of ordinary user flows and load operation-specific procedures only when needed.

Retain checks that protect real authority, uncertain writers, duplicate effects, current candidate/review evidence and recoverable user edits. Do not add a second journal, signer, registry, scheduler or service without an observed requirement. A hard native capability gap needs a supported narrower claim or a material decision, rather than another metadata wrapper.

## Later work

Agent-initiated merge and remote cleanup remain separate from the manual pilot path. Claude's full lifecycle, wider membership/autojoining, project-review tooling and D11's direct Langfuse dashboards follow their existing plans. The structural large-file scanner change already landed in PR29; do not rebuild it. Plugin upgrades remain a separate maintenance assessment.

Recent onboarding PR30–34 and existing source/history remain preserved. This plan creates no live activation, trust grant, credential access, provider call or repository-protection change.
