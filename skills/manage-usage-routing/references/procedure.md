# Usage Routing local management

Manual and Smart Balance share one runner and budget. Setup starts OFF. Local
enablement saves the selected mode and returns a best-effort funding warning.
The public controls return `live_dispatch:false`. A live request needs a trusted
Codex host, current admission evidence and the required qualification. The
[foreground host adapter](codex-host.md) has offline coverage. The existing
live canary qualified only its fixed request.

Warn at enablement/status that the provider may consume other credits or trigger
auto-reload despite local controls. Routine decisions use a compact warning code.
Reserve the next request's full maximum against the selected grant and limits;
stop earlier when coverage or expiry is doubtful and hand remaining work to native
when permitted. Never initiate a purchase or silently switch to a paid API pool.

## Set up and select a mode

1. Use `status` in the selected enrolled Codex checkout. Show the requested mode
   and whether local consent is enabled. Keep status read-only.
2. For a requested new connection, use [Keychain setup](keychain-setup.md).
   Confirm the selected organization, project, billing cycle and one monthly
   ceiling: **No ceiling**, **Monthly subscription benefit only**, or **Specify
   an amount**. Confirm the approved profile and proposal scope. Save settings
   with `configure`. Use verified values for pricing, expiry and limits, and
   report any prerequisite that is missing. Saving settings leaves routing OFF.
3. Only on an explicit enable request, pass the current `revision` as
   `expected_revision` and `mode: manual` or `mode: smart` to `enable`. Other Codex
   activity does not delay enablement. Do not ask the user to pause other work.
   Warn about account funding and explain the current live or shadow limit. Reuse
   the existing connection and shared allowance when changing modes. Do not create
   a second key.
4. In Manual, use the API only for explicitly selected tasks within the approved
   scope. Smart Balance evaluates suitable assignments at the task boundary.
   It stays in shadow while live host or class qualification is missing. Read
   [delegation](delegation.md) for proposal and review handling.
5. Use `disable` on an explicit stop request. Recheck status and report OFF. On a
   stale revision, show current status before applying a changed selection.

## Read-only status, quoting and selection

From the package root:

```sh
python3 -I -B scripts/usage_routing.py status --cwd /absolute/project/path
python3 -I -B scripts/usage_routing.py quote < synthetic-quote.json
python3 -I -B scripts/usage_routing.py evaluate --cwd /absolute/project/path < task.json
```

Status creates no state or credentials. It reports enrollment separately from
qualification. A suspended/uncertain source package does not undo existing
onboarding; resolve it through the user's accepted workflow instead of silently
changing enrollment. Evaluate is a read-only shadow decision; `eligible` plus
`simulation_only:true` never authorizes a send. A paused/unknown decision is not a
reason to start another provider after an API attempt.

Quote input has exactly `version:1`, `packet`, `profile`, `now`. Packet fields:
`version`, `model`, `reasoning`, `text`, `input_tokens`, `max_output_tokens`.
Profile fields: `model`, `reasoning`, `tier` (`default`), `input_rate`,
`cached_input_rate`, `cache_write_rate`, `output_rate`, `max_input_tokens`,
`max_output_tokens`, `verified_at`, `valid_until`, `count_maximum`. Rates are integer
USD micro-units per million tokens; times are integer UTC epoch seconds.
The quote uses the highest input rate and total output including reasoning.
Counting has its own maximum charge. A digest binds inputs without authenticating
counts/prices or granting spending permission. Use synthetic inputs for tests.

## Explicit local configuration

`configure --cwd ...` accepts bounded stdin JSON with exactly:

- `version` (1 or 2), `expected_revision`, `expected_org_revision`;
- `binding`: `organization`, `project`, `credential_ref`. Version 1 accepts a
  simulation-only environment-variable name. Version 2 also requires
  `storage_kind: macos_keychain` and a reference of the form `vcw_` followed by
  32 lowercase hexadecimal digits. Configuration and status use metadata only.
- `policy`: `cycle`, `start`, `end`, `expiry`, `stop_at`, `ceiling`, `amount`,
  `grant_amount`, `pilot_limit`, `task_limit`;
- `profile` as above; `class_name`; `mode` (`manual` or `smart`).

All money values are exact integer USD micro-units. Ceiling is `none` (No ceiling),
`subscription_benefit` (Monthly subscription benefit only), or `custom` (Specify
it). Amount is positive for custom and null otherwise. Benefit-only requires
actual authorized grant coverage before live activation; a numerical setting is
not proof. Stop time precedes cycle end/expiry. No ceiling still respects credits,
request/task/pilot bounds and retained uncertainty.

Configuration requires the supported enrolled Codex scope. It explicitly creates
owner-only feature state under `~/.local/state/vibe-coding-workflow/usage/` and
pins the one canonical database identity in checkout binding files. It saves a
requested mode while leaving the feature OFF and acquires no account connection. A missing
or replaced pinned database requires recovery, not a new allowance. This feature
state is separate from optional managed task runtime activation.

`disable` takes `expected_revision`. `enable` takes `expected_revision` and an
optional `mode` (`manual` or `smart`). Omit `mode` to keep the saved choice. Disable
blocks new admissions. Enable saves local consent and returns the funding warning.
The public `run` path remains unavailable.
Live evidence belongs to the trusted host. `reconcile` takes `{}` and reports
`manual_recovery_required`, not guessed settlement or cleared deductions.

## Qualification and observations

The coordinator's local `Controller.observe` validates organization/project,
USD, selected pool, expiry and source/age before retaining a conservative balance.
`record_qualification` binds class/profile, quality, capacity, sample count and
native savings versus uncertainty. Qualification fields are exactly `class_name`, `profile_digest`, `samples`,
`quality_passed`, `net_native_saved`, `uncertainty`, `unit`, `native_calibrated`,
`observed_at`, `valid_until`. Only attributable `allowance_pp` savings qualify
shadow automatic selection; tokens remain proxies. Native evidence contains
`account`, `task`, `windows`; each window has `id`, `remaining_pp`, `resolution_pp`,
`allowance_pp`, `observed_at`, `reset_at`. Values are integer percentage points;
unknown precision or rounding remains unqualified.

Smart Balance live admission also requires `native_allowance_pp` from the
measured qualification. A legacy shadow record can still inform a shadow
decision. Live requests reserve the measured allowance through independent review.

Both store **non-authoritative shadow data**;
source labels or booleans cannot establish verified funding or activate execution.
The internal gate requires an exact host-issued `Admission` object.
The host verifies the selected grant row, price bounds including counting,
explicit task approval and distinct native reviewer. The gate pins those facts
to the current checkout, credential binding, profile, policy and exact task
through both calls. Manual requires explicit API task selection. Smart Balance
also pins the trusted qualification revision and record through both calls and
stops at its expiry. The host must verify provenance before creating the object.

Actual grant, price and Codex host source qualification remain live dependencies.
Provider-side grant isolation is a residual risk, not an enablement condition.

A shadow task contains exactly `task_id`, `run_id`, `class_name`, `packet`,
`provider` (`auto`, `openai-api`, or explicit other provider), `local_preferred`,
`api_only`, `reviewer_available`, `native`, `snapshots`. Native quota uses the
existing account/task and complete window/reset records. Missing evidence pauses
selection. Snapshots contain `path`/`sha256` and must be unchanged files within the
selected checkout. Other-provider/local choices retain priority.

Smart Balance requires a matching qualified profile/class, positive measured
native allowance savings beyond uncertainty, calibrated native capacity, current
credits/prices/expiry and an available independent reviewer. Account for unrelated
Codex activity when judging whether pilot allowance measurements are attributable.
Proxy token counts alone cannot qualify savings. Unqualified work stays
Manual/shadow. Do not add exploratory inference or stronger reasoning to spend
credits. Expiry can break ties
among equally important ready work, not manufacture tasks.

## Tests and live boundary

```sh
python3 -B -m unittest tests.test_usage_budget tests.test_usage_routing tests.test_usage_settings tests.test_smart_balance tests.test_openai_api tests.test_usage_admission tests.test_usage_live
```

These checks use disposable SQLite and fake connections. The default public
transport cannot connect. Usable grant, price and capacity evidence and a bounded
live pilot still require qualification and explicit request authorization.
Auto-reload OFF or a
provider-enforced grant-only guarantee is not required.

## Native handoff

If evaluate returns `handoff_recommended:true`, use `handoff --cwd ...` with
`{"task": <the bounded task>, "reason": <the decision reason>}`. The result includes
one stable handoff ID, state, native brief, pending API accounting and mandatory
review flags. Request again with fresh native evidence if capacity changes;
unclaimed handoffs respect the latest API-only/provider/reviewer choices. No source
text is persisted in the handoff ledger.

Before existing native agent tools, call `claim_handoff --cwd ...` with
`{"task_id": "...", "attempt_id": "<native dispatch attempt marker>"}`.
Only `new_claim:true` permits that dispatch attempt under existing task authority.
A replay returns `new_claim:false`; observe/reconcile the existing native attempt,
never create another child. The claim is not proof of agent execution or review.
Explicit API-only/provider choices require resolution; unavailable native capacity
waits rather than switching to another paid API. The existing native workflow owns
actual child identity, permissions, completion and fresh independent review.

Keep all pending API reservations and unknown slots while native work proceeds.
Tool-free API output cannot modify the source; the native agent must reread source
and avoid applying late output without new checks/review. Handoff never asserts
that the provider request stopped, settled, was free or consumed only the grant.
