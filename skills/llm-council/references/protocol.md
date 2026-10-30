# Council protocol

Read the section for the action you are about to take. The [procedure](procedure.md)
owns workflow and verification; [selection](selection.md) owns eligibility.
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

`prepare` accepts exactly these fields plus optional `timeout_seconds`. New grouped
requests require `group` and `chair`. Supply `recovery: true` for new version-3
sessions and the preapproved `fallbacks` shortlist in [selection](selection.md#preapprove-recovery-candidates). Omission preserves
version-2 execution and its original no-replacement rules:

| Field | Value |
| --- | --- |
| `run_id` | Fresh lowercase ASCII `[a-z0-9][a-z0-9_-]{0,31}`; never reuse after failure |
| `question`, `constraints` | Bounded objective and read-only scope, uncertainty and acceptance requirements |
| `coordinator_chat_id` | Actual coordinator UUID |
| `approval_ref` | Actual native authorization reference for this scope |
| `approved_files` | Nonempty mapping of reviewed relative paths to exactly `{sha256, size}` for exact UTF-8 bytes |
| `research` | Shared Markdown, empty permitted |
| `phase_seconds` | Exactly positive integer `investigate`, `critique`, `synthesis`, totaling declared timeout |
| `group` | Exactly `Frontier`, `Balanced` or `Free` |
| `chair` | One selected member ID; the native seat for paid groups, selected external seat for Free |
| `roster` | Exactly `member-one`, `member-two`, `member-three`, using kind-specific schemas below |
| `timeout_seconds` | Optional integer 1..2**31-1, default 1200 |
| `recovery` | Optional exact Boolean `true`; grouped requests only; enables version 3 |
| `fallbacks` | Version 3 only: all three member IDs mapped to lists of zero to three full eligible replacement-seat records, ranked within the approved transmission/spending scope |

Question, constraints, approval, selection and supervisor text are at most 16,000
UTF-8 bytes each. Every generated external objective, including the combined question,
constraints and phase instructions, must also fit the worker's 16,000-character
limit. Preparation validates every executable phase brief, including external synthesis,
before any member work. If any objective exceeds that limit, shorten the question/constraints
or move supporting context into explicitly approved evidence files; never truncate it.
File paths must satisfy snapshot safety checks: canonical checkout,
reviewed relative files, no symlinks or unsafe segments. External permission
patterns additionally reject wildcard names. Reserved credential/runtime paths and
nested repositories are excluded; inspect capture coverage rather than assume every
approved path was included.
`__council__` is reserved for generated phase evidence. Capture limits are 2,000
files, 512 KiB/file and 32 MiB total. Reports and research are each at most 128 KiB.
Before launch, grouped preparation reserves six maximum reports, research and
anonymous observations and verification feedback within the same limits: nine free
file slots and 1.125 MiB for newly prepared grouped runs.
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
`source`, `observed_at`; Free requires both rates exactly zero. Retain discovery
provenance in selection. These checks and the pinned original contract are checked
again at launch; editing a worker brief cannot select a paid variant.
`capabilities` has exactly `model`, `provider`, `context_length`,
`max_output_tokens`, `tools: true`, `reasoning`, `observed_at`, `source`, plus
optional `max_input_tokens`. Model/provider must match the seat. `reasoning` is
exactly `{"efforts":[...]}` or `{"fixed":"<observed effort>"}`; external supported
labels in order are `minimal`, `low`, `medium`, `high`, `xhigh`, `max`.
For adjustable reasoning choose the greatest label; fixed reasoning emits no
override. Grouped Free alone also accepts exactly `{"default_enabled":true}`
with `effort: "default"`; `true` must be Boolean. Existing capability `source` and
`observed_at` retain positive exact-route documentation, not inferred support from
missing catalog metadata. This transport marker adds no ordered effort level;
`fixed: "default"`, combined declarations and paid/legacy default modes are invalid.
Its omission/uncertainty rules are defined in [selection](selection.md#pin-the-roster-and-reasoning). Numeric token values are positive integers at most 2**31-1; requested
output fits endpoint output, input fits any narrower observed input limit, and
input plus output fits context. Steps are integers 1..64. OpenCode's input limit
is context-planning metadata, not a hard exact-token transport counter.

`permission_qualification` contains exactly `opencode_sha256`, `version: "1.19.5"`,
`profile: "council-readonly-v2"`, `evidence`. Supply the actual qualified executable
SHA256 and native controlled-observation reference. Selection, capabilities and
qualification are coordinator observations, not authenticated model self-reports.

`prepare` returns exactly `run`, `snapshot`, `remaining_seconds`. Keep the returned
private run path under the saved `council_root`; do not substitute worker roots or
another checkout. The manifest links every immutable candidate/attempt and its
original ownership and accounting. Failed preparation may leave private partial evidence for recovery.

## Verify external reports

For grouped runs, settle every external phase through Python
`council.verify_external(Path(run), phase, member, "accepted"|"rejected", checks)`
or Council CLI `verify-external` with required `{run, phase, member, disposition,
checks}` and optional `findings` as defined below. The Python function accepts the
same optional keyword. Host verification binds the original attempt, frozen evidence, phase,
deadline and observed session. Acceptance requires an actual nonempty session ID
distinct from every earlier external attempt; unknown/reused freshness blocks
acceptance, including synthesis. A manually set accepted flag or legacy worker
verification cannot supply grouped freshness proof. Rejection and terminal failure
retain true stop/cost evidence without inventing a session. The helper records
coordinator observations, not independent authentication of provider telemetry. The exact worker path is returned by the Python packet API and
retained in Council status/manifest; do not create another attempt to recover it.

Version 3 preserves
all assistant text privately but passes only final-step text into verified reports.
Malformed final content still requires rejection; separating interim text alone
does not repair it.

## Verification findings

Newly prepared grouped runs support optional `findings` on external verification
and native receipts. Each finding is exactly `{claim, correction, evidence}`:
nonempty strings of at most 2,000 UTF-8 bytes each. `correction` records the supported
correction or explicitly unresolved uncertainty; `evidence` cites approved source
locations or public references. Limit each submission to eight findings and 16,000
serialized JSON bytes. Acceptance with nonempty findings is rejected. Once the
report addresses them, record actual source checks through the existing `checks`.

The coordinator reviews these notes for scope, factual support and anonymity before
submission. Never copy raw private checks, diagnostics, credentials or identities
into findings. The runtime validates structure, not truth or semantic privacy.
Presentation warnings remain private checks, not outstanding factual findings.

Later critique/synthesis packets include `__council__/verification-feedback.md`,
frozen with their phase generation. Rejected reports remain excluded; only reviewed
findings are shared. Native packets also expose its Markdown as
`verification_feedback`. Independent investigations and critic catch-ups receive
no earlier answers or findings. A same-phase retry gets only its own prior rejection
findings added to a separately sealed attempt packet; peers retain their original
packet. Superseded critique generations do not contribute critique findings.
Late or cancelled findings stay private. The combined feedback retains the existing
128 KiB report limit; overflow blocks dispatch rather than truncating or increasing
allowances. Frozen original reports and shared phase evidence never change.

Older runs without feedback support retain their original verification contract;
nonempty findings are unavailable there. Do not retrofit their manifests or renew
the session budget. Feedback does not grant another attempt, round or provider call.

## Older runs and native receipts

Ungrouped legacy requests/manifests remain version 1, with original
`native`, `external-one`, `external-two` IDs, optional unavailable external seats,
unchanged seat fields and original outcome meaning. They retain the old worker
verification route:

```text
python3 -I -B <plugin-root>/scripts/openrouter_workers.py verify --root <saved-council-root>
```

Its JSON is `{"task_id":"<original worker task_id>","disposition":"accepted",
"checks":["<actual native check and result>"]}` (or `"rejected"`). IDs are
`<run_id>-<phase>-<external member>` under the exact Council root. Native reports
use `record-native` with exactly `{run, phase, member: "<selected native seat>", receipt}`;
the receipt and native supervision requirements live in the Codex contract.

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
