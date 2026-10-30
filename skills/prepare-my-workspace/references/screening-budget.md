# Screening budget controls

Load for an explicit allowance inspection, admission or settlement request. These controls precede the full onboarding screen; they do not discover or assess source files.

Use the installed package:

```sh
python3 -B <plugin-root>/scripts/workflow.py storage screening status
python3 -B <plugin-root>/scripts/workflow.py storage screening reserve
python3 -B <plugin-root>/scripts/workflow.py storage screening settle
```

Pass bounded JSON on standard input:

| Action | Exact fields |
| --- | --- |
| status | selection |
| reserve | selection, expected_revision |
| settle | selection, ticket |

Selection is exactly `{"target":"/absolute/path"}` or `{"project_scope":...}` using the local [Project scope grammar](../../../runtime/onboarding.py). Controls require an existing authenticated anchor; status and admission do not create one or prepare storage.

Only a fresh real temporary-owner publication creates the 300000 ms allowance. Existing owners with missing state, uncertain history and enrolled authorities remain protected. Preserve their references and ages. Do not delete an anchor, reparent history or choose another store to obtain time.

Check `admitted:true` before work. Only the first successful reservation returns `deadline_monotonic`, measured from reserve entry. Status, retries, stale requests and settlement never renew permission or a deadline. Respect existing task and tool permissions separately; a ticket grants neither.

Retain the exact returned ticket. An interrupted reservation keeps its full ceiling unavailable. Settle that ticket to record `charged-full`; exact settlement replay is idempotent. This version charges the entire ceiling and accepts no duration or refund claim. The charge is accounting, not measured execution, successful assessment, usage or cost.

Missing or protected screening does not waive mandatory baselines or itself block otherwise qualified enrollment. Report unavailable or partial coverage honestly. Both D3 pre-work callers, coverage persistence, total acquisition accounting and coordinator analysis/reporting timing still need integration and qualification.
