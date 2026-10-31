# Council protocol

Read the section for the action you are about to take. The [procedure](procedure.md)
owns workflow and technical admission; [selection](selection.md) owns eligibility.
Recovery action schemas live in [recovery](recovery.md#actions).

## Prepare and seat schemas

Invoke the packaged helper (paths are relative to the installed package):

```text
python3 -B <plugin-root>/scripts/council.py ACTION --cwd /canonical/enrolled/checkout
```

Feed one JSON object on stdin, at most 2 MiB; duplicate keys and nonfinite numbers
are rejected. `ACTION` is exactly `prepare`, `member`, `resume-member`,
`record-native`, `verify-external`, `status`, `cancel`, `investigate-failure`,
`record-investigation`, `correct-candidate`, `replace-candidate`,
`publish-generation` or `record-supervisor`. These actions validate fixed schemas;
there is no arbitrary source/configuration patch or research service.

Prepare current grouped runs with `group`, `chair`, required `mode`, and the fields
below. Supply `recovery: true` and the preapproved `fallbacks` shortlist for version
3. Without recovery the run is version 2, with no outer retry/replacement. The
runtime stamps `flow: "peer-review"`; mode/flow remain fixed across attempts:

| Field | Value |
| --- | --- |
| `run_id` | Fresh lowercase ASCII `[a-z0-9][a-z0-9_-]{0,31}`; never reuse after failure |
| `question`, `constraints` | Bounded objective and read-only scope, uncertainty and acceptance requirements |
| `coordinator_chat_id` | Actual coordinator UUID |
| `approval_ref` | Actual native authorization reference for this scope |
| `approved_files` | Mapping of reviewed relative paths to exactly `{sha256, size}` for exact UTF-8 bytes; text permits `{}`, repository requires files |
| `research` | Shared Markdown, empty permitted |
| `phase_seconds` | Exactly positive integer `investigate`, `critique`, `synthesis`, totaling declared timeout |
| `mode` | Exactly `text` or `repository`, selected from the required work |
| `group` | Exactly `Frontier` or `Balanced` |
| `chair` | Selected native member ID |
| `roster` | Exactly `member-one`, `member-two`, `member-three`, using kind-specific schemas below |
| `timeout_seconds` | Optional integer 1..2**31-1, default 1200 |
| `recovery` | Optional exact Boolean `true`; grouped requests only; enables version 3 |
| `fallbacks` | Version 3 only: all three member IDs mapped to lists of zero to three full eligible replacement-seat records, ranked within the approved transmission/spending scope |

Question, constraints, approval, selection and supervisor text are at most 16,000
UTF-8 bytes each. Every generated external objective, including the combined question,
constraints and phase instructions, must also fit the worker's 16,000-character
limit. Preparation validates executable phase briefs before member work. If an
objective exceeds that limit, shorten the question/constraints or move supporting
context into approved evidence files; never truncate it.
File paths must satisfy snapshot safety checks: canonical checkout,
reviewed relative files, no symlinks or unsafe segments. External permission
patterns additionally reject wildcard names. Reserved credential/runtime paths and
nested repositories are excluded; inspect capture coverage rather than assume every
approved path was included.
`__council__` is reserved for generated phase evidence. Capture limits are 2,000
files, 512 KiB/file and 32 MiB total. Reports and research are each at most 128 KiB.
Before launch, grouped preparation reserves six maximum reports, research and
anonymous observations within the same limits: eight free file slots and 1 MiB.
Impossible scopes fail before investigation; reduce
scope explicitly rather than truncate evidence or increase limits silently.

Native seat required keys are `kind: "native"`, `model`, `effort`,
`supported_efforts`, `input_tokens`, `output_tokens`, `steps`, `selection`,
`supervisor_id`; optional Boolean `lifecycle_active` follows the
[Codex contract](../../../clients/codex-council.md). Native effort labels in order
are `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, `ultra`; choose the
greatest observed supported label. Token allowances are integers 1..2**31-1 and
steps 1..64. These are supervisor declarations, not proof of hard native limits.

Each available external seat has exactly `kind: "external"`, `model`,
`model_display_name`, `provider`, `effort`, `input_tokens`, `output_tokens`, `steps`,
`selection`, `capabilities`, `permission_qualification`, `canonical_model`, `pricing`.
`canonical_model` is the nonempty observed model identity, separate from `model`,
the exact routable request ID. `pricing` contains exactly numeric nonnegative
`prompt_usd_per_million`, `completion_usd_per_million`, and nonempty bounded
`source`, `observed_at`. Retain discovery
provenance in selection. These checks and the pinned original contract are checked
again at launch; editing a worker brief cannot change the pinned contract.
`capabilities` requires `model`, `provider`, `context_length`, `max_output_tokens`,
`tools`, `reasoning`, `observed_at`, `source`; optional `max_input_tokens` supplies
a narrower input limit. Model/provider match the seat. `reasoning` is exactly
`{"efforts":[...]}` or `{"fixed":"<observed effort>"}`. Selectable labels in order
are `minimal`, `low`, `medium`, `high`, `xhigh`, `max`; choose the greatest observed
supported label. Fixed behavior emits no reasoning override. Positive integer token
values are at most 2**31-1: output fits endpoint output, input fits its input limit,
and input plus output fits context. Steps are integers 1..64, with the text
restriction below. OpenCode input limits are planning metadata, not exact counters.

| Mode | Additional capability and qualification fields |
| --- | --- |
| `text` | `api: "chat-completions"` with capability source/date; `tools` is Boolean, either value; `steps: 1`; `permission_qualification` exactly `{profile: "council-text-v1", evidence: "<qualification reference>"}` |
| `repository` | `tools: true`; no `api` field; `permission_qualification` exactly `{opencode_sha256: "<actual qualified SHA256>", version: "1.19.5", profile: "council-readonly-v2", evidence: "<controlled-observation reference>"}` |

Selection/capability/qualification records are coordinator observations, not model
self-reports. Each mode rejects the other's qualification.

### Direct text transport

The owned worker child `scripts/council_direct.py` sends one nonstreaming request
to fixed `https://openrouter.ai/api/v1/chat/completions`, with one fresh user
message, pinned model/provider, `allow_fallbacks: false`, `require_parameters: true`,
supported reasoning and finite output. It accepts no tools, history, prior response
ID, endpoint override or redirects and adds no HTTP retry layer. Only approved
question/constraints, exact evidence, shared research and applicable anonymous
phase packets enter the payload; local storage/authentication paths stay private.
UTF-8 input bytes plus a 1,024-byte envelope reserve must fit `input_tokens` before
send. Oversize input blocks; nothing is truncated.

Only the child reads the saved `openrouter` provider record in
`<auth_data>/opencode/auth.json`, requiring `type: "api"` and private-file checks.
Missing/unsupported records fail before send. No credential copy/migration/logging,
alternative environment key/proxy or prompt-supplied endpoint is used. Saved pinned
OpenCode setup references remain prerequisites; text execution does not invoke it.
The existing runner owns admission, deadlines, progress and process-group cleanup.

`prepare` returns exactly `run`, `snapshot`, `remaining_seconds`. Keep the returned
private run path under the saved `council_root`; do not substitute worker roots or
another checkout. The manifest links every immutable candidate/attempt and its
original ownership and accounting. Failed preparation may leave private partial evidence for recovery.

## Verify external reports

For current grouped runs use Python
`council.verify_external(Path(run), phase, member, disposition, checks, failure=None)`
(the optional `failure` is keyword-only), or CLI `verify-external` with required
`{run, phase, member, disposition, checks}` and optional `failure`.
`disposition` is `accepted` or `rejected` under the procedure's
[technical admission](procedure.md#4-verify-reports-and-phase-completion).
`checks` is a nonempty list of bounded strings describing observed completion,
ownership, privacy, scope and identity. `findings` is invalid.

Acceptance binds the original stopped attempt, frozen evidence, phase and deadline.
Repository transport requires a real nonempty OpenCode session ID distinct from
earlier attempts. Text transport uses `transport: "openrouter-chat"`, sealed local
`attempt_id` and immutable `request_sha256` from the fresh stateless launch;
`session_id` is null. A returned provider generation ID is separate and optional.
Preserve nullable cost/usage and reported model without inventing observed effort.
Neither a manually accepted flag nor worker verification bypasses grouped proof.
Keep the existing worker path returned by the packet API/status; do not create
another attempt to retrieve it. Receipts attest observations, not authenticated
upstream telemetry. Version-3 repository reports use final-step text; the aggregate
assistant text stays private. Version-2 repository reports include aggregate
assistant text from interim and final steps. Failed/truncated direct responses
retain bounded message text privately with no usable `final_response`.

### Technical failure schema

`failure` is absent/null for usable reports. Rejecting complete nonempty text
requires an explicit dictionary with a recognized `category`: `transport`,
`context`, `policy`, `unknown`, `authentication`, `budget`, `permission`,
`rate_limit`, `service`, `invalid_request`, `runtime`, `incomplete_output`,
`deadline`, `integration`, `runtime_or_output` or `interrupted`. Use the observed
technical condition, never a factual disagreement. Safe known diagnostic fields
are retained; arbitrary/private fields are dropped. Blank rejection may derive
`incomplete_output`; observed lateness may derive `deadline`. Acceptance with a
failure is invalid. Native receipts use this same optional failure contract.

## Older runs and native receipts

Runs without `flow: "peer-review"` are historical: status, cancellation and
operational stop/accounting settlement remain available without inference. Keep
original Free records, prices, reports, verdicts and feedback readable and unchanged.
No new member/resume/recovery inference or verdict mutation is permitted. Use a
new identity with current consent and mode for new deliberation; never retrofit
old manifests. Free is blocked at preparation and every inference entry, including
direct helpers and replacements. Historical native owner cleanup uses the
[stop-only receipt](../../../clients/codex-council.md#historical-native-stop-settlement),
not current-run report admission.

Ungrouped IDs remain `native`, `external-one`, `external-two`. For a current
ungrouped external result only, the worker-owned verify route is:

```text
python3 -I -B <plugin-root>/scripts/openrouter_workers.py verify --root <saved-council-root>
```

Its JSON is `{task_id, disposition, checks}` with optional `failure` under the same
technical contract. `task_id` is `<run_id>-<phase>-<external member>`.
Grouped results require Council verification. Native results use `record-native`
with exactly `{run, phase, member: "<selected native seat>", receipt}`; receipt
fields and supervision live in the [Codex contract](../../../clients/codex-council.md).

## Execution observations

Bounded
`execution_observations` in native packets (empty during investigation) preserve
anonymous Participant 1/2/3 states, failure categories, missing verification,
late/unreviewed evidence, local stop and unknown telemetry. Pass this Markdown with
reports/research for critique and synthesis. Excluded reports are not evidence;
private raw reasons/checks and model/provider/child/session identities do not enter
these allowlisted observations. Unavailable reasons are generic in deliberation;
exact details remain in private audit records. Grouped synthesis receives the
sealed observations file described in the [synthesis step](procedure.md#3-run-the-three-phases); native packets also expose Markdown.
Known machine error classes, typed router codes, terminal reasons, launch stage,
fixed prerequisite reasons, HTTP status and retry hints are diagnostic evidence.
They do not establish upstream origin or trigger. A client `ContentFilterError`
supports saying the client reported a content-filter stop; it does not explain why.
Never copy raw provider messages, response bodies, headers, prompts or tool output
into diagnostics or progress. Retry hints do not authorize another inference.

## Status, cancellation and consent

`status` and `cancel` accept exactly `{"run":"<returned path>"}`. They perform
no inference or balance lookup. Status reports phase/member states, remaining time,
timing certainty and `outcome`. Accounting keys are `known_external_subtotal_usd`
and nullable `external_total_usd`; `upstream_cancellation_confirmed: false` means
unconfirmed, not proof that billing stopped. Stop keys are
`all_local_execution_stopped` and exact owners in `stop_requests`.
Cancel records stop-new-work
intent and returns owners to terminate; it is not evidence that they stopped. Stop
those exact owned processes/children and inspect actual local-stop evidence before
releasing ownership. The executor acquires saved-settings admission before a short
Council launch guard held through spawn only. Cancellation before that boundary
prevents launch; an admitted process needs owner termination. Disable blocks new
external admission and retains historical results and settlement.
External preparation and launch retain the Council's original consent revision and
checkout scope. Disable/re-enable or reconfiguration makes old runs stale for new
external work, including unprepared later members. Use a fresh run identity under
the approved current configuration; never refresh an old run's authorization.

## Accounting and qualification reporting

All external attempts, including chair synthesis, contribute to progress, exact
stop ownership and nullable accounting. Report actual selected/requested and observed settings separately. Unknown model or
effort telemetry stays unknown even when configured controls were verified. Report
known external cost subtotal with missing coverage; do not turn it into a total,
zero billing or native usage. OpenCode step-finish costs can differ from provider
charges; only observed provider usage supports billing claims, with concurrent-use
attribution limits. Preserve unknown upstream cancellation and accounting. Do not
promise savings or Council superiority without a separate comparable evaluation.

Package checks, controlled pinned OpenCode tool qualification, actual cross-provider
inference and native host Council execution are distinct evidence classes. Their
recorded scope and remaining qualification live in
[Council validation](../../../docs/council-validation.md), for validation/reporting
only; ordinary runs need not load authoring provenance or evaluation history.
