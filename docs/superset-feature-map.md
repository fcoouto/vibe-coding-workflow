# Superset feature map

25 October 2026. Compare the [approved policies](../policies/00-index.md) and [D1–D9 plan](onboard-my-project-plan.md#5-small-deliverables) with current Superset documentation and installed Superset 1.40.0.

**Decision:** use native delegation by default. Leave initial onboarding unchanged; offer Superset later through a separate connection skill. One shared policy and evidence layer governs both. Codex-only users need neither Claude nor Superset; Claude-only users need neither Codex nor Superset.

This is design evidence, outside routine policy loading. “Reuse” identifies an implementation candidate, not qualified behavior. No live Superset agents or integrations were exercised during this mapping.

## Delegation backend

The native client runs the coordinator and lifecycle hooks. The selected delegation backend supplies worker discovery and execution:

- **Native:** discover and dispatch through that client's supported capabilities.
- **Superset:** use Superset's configured workers and exposed model/effort controls as the execution catalog. Do not merge in a separate native catalog or silently switch backends. Workflow policy still determines permitted routes and required evidence.

The shared skill guides selection; supported controls and runtime checks validate it. Reuse existing orchestration commands and guidance. The minimal backend interface covers discovery, launch, observation, result collection and safe stop; it does not require another orchestrator or routing service.

One task may use workers from different vendors, such as a Codex coordinator and Claude reviewer. Independent assignments may run in parallel; dependent or conflicting work is sequenced. Review independence requires a distinct qualified reviewer where applicable, not a different vendor.

Configured agents, supported settings and account access are separate facts. Superset agent discovery exists; a complete usable-model/effort inventory remains unverified. Missing capabilities stay explicit and block only dependent work.

Local models are a future optional route. Assess reuse of the existing Local Model Delegation plugin, qualify the route and revise the current subscriptions-only contract before enabling it.

## Planned connection skill

Working name: **Connect Superset** (`connect-superset`). Plan the skill now; implement it with the qualified Superset integration.

Do not ask about Superset during initial onboarding or enable it merely because it is installed. Describe it in optional integrations guidance, or mention it when the user requests a capability their native setup lacks.

**Recommended scope:** reuse environment-level installation, authentication and host configuration; enable delegation per explicitly selected project. Connecting one project does not change other projects or global defaults. Shared setup changes retain their own scope and authorization.

The skill discovers the selected host and workers, presents a short capability/permission summary, qualifies the requested routes and saves the project choice only after successful validation. Reuse valid setup evidence on later connections; do not repeat full onboarding or copy credentials.

Apply backend changes to new tasks; active tasks retain their backend and ownership until finished or explicitly reconciled. Disconnecting returns new tasks to native delegation without uninstalling shared tools. Unexpected Superset unavailability blocks dependent work rather than silently switching backends.

## Feature mapping

| Planned feature | Existing capability to reuse | What we still need to build or qualify |
| --- | --- | --- |
| **Installation and startup — D1, D8** | Superset runs native agents and installs its own status hooks. [Host model](https://docs.superset.sh/superset-model). | Keep our existing native startup adapters. Qualify coexisting hooks, launch arguments, trust and permissions in Superset; qualify Desktop surfaces separately. |
| **Project scope — policy 01** | Project/workspace identities and Git worktrees. [Host model](https://docs.superset.sh/superset-model). | Explicit enrollment tied to checkout/client and accepted policy. Registering a Superset project cannot enroll its neighboring repositories or all clients. |
| **Task planning — policy 02, D2** | Native tasks, issue links, statuses, descriptions and workspace assignment. [Tasks](https://docs.superset.sh/tasks). | Planning depth, acceptance criteria, applicability and decision provenance. Reference host task IDs; retain only missing workflow state. |
| **Onboarding — policy 10, D3–D4** | Existing project tooling and Superset workspace setup/teardown commands. [Lifecycle scripts](https://docs.superset.sh/setup-teardown-scripts). | Complete Toolkit coverage, conflict modes, equivalents, reviewed changes, adoption evidence, recovery journal and safe resume/rollback. Workspace setup is not policy adoption. |
| **Action guards and completion — D2** | Native Codex/Claude lifecycle hooks and permission mechanisms; Superset provides status observations. | Supported pre-action checks, evidence invalidation, bounded Stop handling and independent `doctor`. Measure actual blocking and failure behavior. |
| **Agent dispatch — policy 03, D6** | `workspaces create`, `agents create`, terminal read/send/wait and existing orchestration. [Orchestration](https://docs.superset.sh/orchestration). | A small dispatch integration: approved route, bounded brief, recorded IDs, ownership and verified results. No new process launcher or workspace manager. |
| **Model and effort selection — policy 03, D6** | Installed agent launch accepts `--model` and `--effort`; configured agents can be discovered. [CLI reference source](https://github.com/superset-sh/superset/blob/main/apps/docs/content/docs/cli/cli-reference.mdx). | Selection policy and requested/configured/observed evidence. Validate supported values and final arguments before dispatch; installed code can silently omit selections. Then qualify actual execution. Preserve coordinator, provider, account and subscription choices. |
| **Budgets and capacity — policy 03, D6** | Superset documents account quotas, token analytics and machine resources. [Usage](https://docs.superset.sh/usage). | Finite task/attempt/time/resource budgets and authorized concurrency. No suitable enforcement controls were found in installed dispatch schemas. Usage estimates are not spend authorization or hard limits. |
| **Concurrent ownership — policy 03, D6** | Worktrees and parallel sessions. [Orchestration](https://docs.superset.sh/orchestration). | Atomic claims over overlapping paths and shared mutable resources, dependencies and confirmed stop/takeover. Worktrees do not isolate shared databases, services or every port. |
| **Tests and builds — policy 05, D5** | Existing project commands and CI; Superset displays GitHub check results. [Pull requests](https://docs.superset.sh/pull-requests). | Select applicable checks, collect trusted results and invalidate stale evidence. Reuse test runners; do not build another CI system. |
| **Code and security review — policies 04, 06, D5** | Agent dispatch, diff/review UI and GitHub review observations. [Pull requests](https://docs.superset.sh/pull-requests). | Postimplementation security assessment, general review before every merge, risk-based independence, reviewer provenance and finding disposition. A displayed approval alone does not prove required coverage. |
| **Context and handoff — policy 07, D6** | Resume, fork and cross-agent handoff, including a context-size control. [Agent sessions](https://docs.superset.sh/agent-sessions). | Selective briefs, canonical decisions and reconciliation against files, evidence and ownership. Automatic terminal-history forwarding can expose sensitive output; use an appropriate scoped summary. |
| **Merge readiness — policy 08, D7** | Superset displays checks/reviews and invokes GitHub merges. [Pull requests](https://docs.superset.sh/pull-requests). | Trusted final verification through repository CI/rules, bound to current candidate/base and merge-queue cases. Qualify bypasses and all supported merge paths. Reuse GitHub enforcement. |
| **Maintenance — policy 09, D9** | Native session observations, existing evaluation tools and documented usage views. [Usage](https://docs.superset.sh/usage). | Capability requalification, active-version compatibility, reversible updates and relevant native harness/pilot cases. No generic benchmark service. |
| **Tool integrations — policy 11** | Superset documents plugin MCP tools, skills and account connections for supported agents. [Plugins](https://docs.superset.sh/plugins/overview). | Qualify required discovery, permissions and execution; preserve existing configurations. No new connector credential store. Installed CLI gaps are listed below. |
| **Scheduled work — optional** | Superset provides scheduled/event automations, subject to plan and integration prerequisites. [Automations](https://docs.superset.sh/automations). | Reuse only when requested and qualified. No scheduler to build; recurring work is not required for ordinary workflow activation. |

These rows map every approved policy; the contracts remain authoritative. They do not replace D3's complete Toolkit catalog assessment for each project.

## Installed evidence and limits

Read-only inspection used `/Applications/Superset.app/Contents/Resources/resources/bin/superset` (`--help`, `schema` and command help) and packaged `app.asar` source. No account contents or credentials were inspected.

| Installed 1.40.0 finding | Implementation consequence |
| --- | --- |
| Workspace creation supports worktree/local checkout, task/PR links and agent launch. Agent creation supports model/effort, resume/fork/handoff. | Reuse these primitives. Select the intended local/remote host explicitly; do not inherit an unintended cloud destination. Local checkout shares files. |
| Launch argument builders return no model argument for an uncurated/unsupported model and no effort argument for an unsupported/invalid effort. | A syntactically accepted selection can fall back to client defaults. Validate supported values and final arguments; never count a dropped selection as honored. |
| `agents wait` exposes `settled`, `idle`, `blocked`, `working`; terminal close/send/read/wait are available. | A settled turn can need input. It is not task completion. Qualify cancellation and stopped writers before releasing claims. |
| Dispatch schemas expose no permission/tool allowlist, task budget, concurrency cap or resource claims. Chat sessions expose mode/model but not the same effort control. | Keep capabilities specific to the launch surface. Use native controls where qualified; unsupported restrictions remain explicit. |
| `plugins --help`, `mcp --help` and `skills --help` return `Unknown command`, despite bundled skills advertising them. | Do not implement against advertised commands without checking the installed version. This does not establish absence of the corresponding desktop features. |
| Packaged Codex wrapper adds hook-trust bypass; default native launch commands contain permission bypasses. | Resolve launch behavior against the user's choices before claiming Superset qualification. See [existing inspection evidence](claude-and-superset-validation.md#superset-inspection). |
| PR handlers fetch check/review state but merge through GitHub without our workflow-evidence parameter. | Presentation and merge permission do not establish our verdict. Repository enforcement remains necessary. |

Additional source anchors inside `app.asar`: `dist/main/host-service.js:79009–79027` (agent launch schema), `12433–12463` and `78793–78802` (model/effort argument filtering and use), `78054–78117` (PR state), `83072–83103` and `88873–88900` (merge capability/handlers). These anchors describe this installed build only.

Official documentation and source establish reuse candidates. Installed command schemas establish exposed controls. Only observed execution can qualify model/account preservation, hook behavior, cancellation and reliable evidence collection.

## Build scope after mapping

1. **D2:** implement narrow policy state, guards and diagnostics over native hooks. Reference existing session/task IDs instead of mirroring host histories or building a task dashboard.
2. **D3–D4:** implement explicit onboarding and recoverable adoption. Reuse existing tools and setup commands after verifying equivalence.
3. **D5:** implement applicability and evidence freshness/provenance over project checks and reviewers. Preserve adopted/qualified, applicable and satisfied as separate facts. Include dirty-tree content, base, relevant environment/check definitions and accepted policy; HEAD alone is insufficient.
4. **D6:** implement selection, budgets, reservations and result verification through the selected backend. Reuse qualified native or Superset dispatch/monitoring. Persist only missing workflow records and atomic claims; SQLite remains a proposed choice, not a second orchestration database.
5. **D7–D9:** connect the trusted verifier to existing repository controls, complete native-client qualification and run the bounded pilot.

There is no current need for a Superset fork, generic SDK wrapper, orchestration daemon, workspace/session manager, dashboard, scheduler or credential proxy. Superset-specific code should appear only when an end-to-end slice needs it.

**Next:** retain D2 as the next runtime slice. Prove a complete Codex-only task with delegation and review before adding Superset dispatch. Test standalone Codex and Claude with Superset absent. Then qualify Superset discovery and one mixed-vendor task, including final launch arguments, model/effort/account, startup, wait/blocked behavior, cancellation and stopped-writer evidence. Keep local-model integration for a later slice. These checks preserve the approved requirements; this document does not authorize application or repository settings changes.
