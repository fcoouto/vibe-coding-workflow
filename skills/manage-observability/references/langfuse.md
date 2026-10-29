# Langfuse connection controls

Load only for selected Langfuse setup, connection checks, probes or forwarding questions. Follow the common procedure for authorization, payload scope and evidence; this reference adds provider-specific controls.

## Select a destination

Identify the user's Langfuse Cloud region or self-hosted destination and intended Langfuse project. A workflow Project is not automatically a Langfuse project. Several selected workflow Projects may share one authorized destination with qualified Project/Repository filters; separate destinations retain their access boundaries and separate dashboard links.

Langfuse is the first supported connection provider. Native workflow collection and its exporter remain pending. A proposal alone does not authorize account access or a synthetic record. Reuse explicit matching setup/test authorization and the user's selected destination. Never paste credentials into chat, Git, a report or a destination URL.

Use an HTTPS origin without userinfo, path, query or fragment and the exact Langfuse project ID from the selected dashboard. EU Cloud uses `https://cloud.langfuse.com`; another region or self-hosted origin requires the user's actual destination. Do not substitute an account, follow redirects or provision a project. Configuration stores the selected nonsecret origin/project only, under the common procedure's existing private owner.

## Credentials and connection verification

For this slice, the user supplies project-scoped `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` through an existing secure environment injection. The helper reads them only for explicit `enable` or `probe` operations. A CLI login, `LANGFUSE_HOST`, SDK setup, MCP connection or previously verified key pair is not used as a fallback. API keys belong to the selected Langfuse project, not to a workflow Repository.

OS secure-storage UX remains a pending choice; this package installs no keyring backend or credential UI. If no secure injection is available, explain that prerequisite and stop before connection access. Do not ask for secret values in chat, put them in shell history/arguments or a committed environment file, print them, or send them to model workers. Status and disable need no credentials.

Each live operation uses its current injected pair for `GET /api/public/projects` and requires exactly the selected project. `enable` stores desired connection opt-in after that verification; it sends no trace and starts no native collector. Local status reports the cached verification timestamp, never current remote health. Changed/expired keys must pass a new check before any probe ingestion.

## Fixed synthetic probe

Run `probe` only when the user has authorized a real synthetic record and the exact current checkout configuration is opted in. It writes one complete fixed OTLP span to `/api/public/otel/v1/traces` with JSON, Basic project-key authentication and ingestion version `4`. The span contains only fixed service/type/name markers, fresh opaque trace/span IDs, timestamps and explicit synthetic metadata. It contains no actual workflow identifiers, prompts, completions, source, paths, tokens or costs. It consumes destination quota. It does not configure Broadcast, MCP, global client settings or SDK auto-instrumentation.

The helper queries only the generated trace through Observations API v2, with short request/readback budgets and at most five reads. It checks the exact trace, observation, selected project, fixed name/type and metadata, with absent input/output and user/session content. An ingestion partial rejection, wrong project, redirect or mismatched/content-bearing record cannot report verified success. Remote bodies and credentials never enter the result.

`accepted:true, verified:true` proves only this synthetic write/readback. `accepted:true, verified:false, status:"pending"` means ingestion acknowledged the record but readback did not establish the required proof. `ingestion_outcome_unknown` means the write may have arrived despite a missing/failed acknowledgement. Never retry ingestion automatically or manufacture token/cost zeros; usage and charges stay unknown. A later explicit probe creates another record, so do not rerun it to hide an incomplete result.

Do not assume an installed SDK, account connection or synthetic probe qualifies the actual workflow. Native completion needs explicit canonical Project opt-in, authorized payload/destination handling and qualified source collection; the existing source qualification order, including prior repository-gate proof for D9b and a real native-only coordinator/worker/reviewer measurement case, remains intact. Use Context7 or official version-specific documentation for requested API troubleshooting or authoring changes, not routine disabled tasks.

## Source coverage and forwarding

OpenRouter Broadcast observes OpenRouter-routed requests only. Native coordinator/worker and local-model measurements require their own qualified sources; do not reroute them for visibility. Qualify the actual connector's request identity and correlation fields rather than inferring support from API documentation or matching by timing.

Broadcast destination filtering, sampling and privacy settings are independent of Langfuse SDK controls. Verify authorized source-side scope and the actual exported metadata; a privacy-mode checkbox alone does not prove the payload is safe. Do not enable account-wide forwarding to bypass missing task/Repository filtering. Report any separately configured forwarding that remains active when plugin collection is disabled.

## Retention, limits and dashboards

Langfuse Cloud Hobby can be selected within its current supported limits. Check current plan limits only for requested setup or explicit troubleshooting, not routine coding. A history-access window does not delete older data. The user accepts disclosed destination retention for eligible metrics-only exports; do not add plugin deletion logic or promise remote erasure. Required local evidence keeps its existing rules independently of remote history.

Reuse Langfuse's existing dashboards and Usage Management view. No custom reporting application, offline snapshot or unit counter is needed. Dashboard access does not authorize provisioning or overwriting user customizations. Supported filters and widgets need target-version qualification; missing history or source support remains explicit. Dashboard qualification remains the last deliverable and is not a prerequisite for D9b source acceptance. The connection controls and synthetic probe qualify none of those native views.
