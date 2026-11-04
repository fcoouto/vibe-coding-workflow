# Usage Routing local management

Manual and Smart Balance share one runner and budget. Saving settings leaves
routing Off. A Keychain connection and explicit activation make either mode
available for the first eligible task. Other Codex work can continue. The public
CLI records and shows consent. Only the trusted Codex host can send requests
after live admission.

Warn at enablement/status that the provider may consume other credits or trigger
auto-reload despite local controls. Routine decisions use a compact warning code.
Reserve the next request's full maximum against the selected grant and limits;
stop earlier when coverage or expiry is doubtful and hand remaining work to native
when permitted. Never initiate a purchase or silently switch to a paid API pool.

## Set up and select a mode

1. Read `status` in the selected enrolled Codex checkout. Show the configured
   mode and whether live consent is saved.
2. For a requested connection, use [Keychain setup](keychain-setup.md). Confirm
   the selected organization, project and key, approved profile, task and data
   scope, expiry, billing cycle and spending limit. Reuse accepted settings and
   the existing connection when applicable. Save configuration with `configure`
   if needed.
3. On the user's explicit enable request, pass the current `revision` as
   `expected_revision` and select `mode: manual` or `mode: smart`. This
   records live consent for the approved configuration. Use the existing
   spending cap and expiry. Use `live_enabled` to verify saved live consent.
4. In Manual, route only tasks explicitly selected by the user. In Smart
   Balance, use the standing consent for eligible tasks within the approved
   scope and budget. Load [delegation](delegation.md) for either mode. Previews,
   comparisons and canaries are optional.
5. Use `disable` on an explicit stop request. Recheck status and report Off.
   On a stale revision, show current status before applying a changed selection.

## Read-only status, quoting and selection

From the package root:

```sh
python3 -I -B scripts/usage_routing.py status --cwd /absolute/project/path
python3 -I -B scripts/usage_routing.py quote < synthetic-quote.json
python3 -I -B scripts/usage_routing.py evaluate --cwd /absolute/project/path < task.json
```

Status creates no state or credentials. It distinguishes enrollment and saved
live consent (`live_enabled`). `live_dispatch:false` describes the public CLI
boundary. If the source package is unavailable or untrusted, resolve that
through the accepted workflow and preserve enrollment. Evaluate is an optional
read-only preview. `eligible` plus
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
actual authorized grant coverage before a live request; a numerical setting is
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
blocks new admissions. Explicit enable on a Keychain configuration sets
`live_consent` and returns the funding warning.
The public `run` path remains unavailable.
Live evidence belongs to the trusted host. `reconcile` takes `{}` and reports
`manual_recovery_required`, not guessed settlement or cleared deductions.

## Optional preview and evaluation

The coordinator's local `Controller.observe` retains a conservative balance
after checking organization/project, USD, selected pool, expiry and source/age.
For a comparative evaluation, `record_qualification` accepts `class_name`,
`profile_digest`, `samples`, `quality_passed`, `net_native_saved`,
`uncertainty`, `unit`, `native_calibrated`, `observed_at`, and
`valid_until`. Use attributable `allowance_pp` deltas to report measured
allowance savings. Mark unknown rounding or unrelated account
activity that prevents attribution. Neither preview records nor their inputs
authorize transmission.

A preview task contains exactly `task_id`, `run_id`, `class_name`, `packet`,
`provider` (`auto`, `openai-api`, or explicit other provider),
`local_preferred`, `api_only`, `reviewer_available`, `native`, and
`snapshots`. Native evidence contains `account`, `task`, and `windows`;
each window has `id`, `remaining_pp`, `resolution_pp`, `allowance_pp`,
`observed_at`, and `reset_at`. Capacity values are integer percentage
points. Snapshots contain `path` and `sha256` for unchanged files within
the selected checkout. Other-provider/local choices retain priority.

## Optional local checks

```sh
python3 -B -m unittest tests.test_usage_budget tests.test_usage_routing tests.test_usage_settings tests.test_smart_balance tests.test_openai_api tests.test_usage_admission tests.test_usage_live
```

These checks use disposable SQLite and fake connections. Use the
[Codex host](codex-host.md) for live admission.

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
