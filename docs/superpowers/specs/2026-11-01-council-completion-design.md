# Council completion and delivery

Council should help the user make a decision. Recover failed attempts within the
approved session rather than advance with missing participants. Success requires
three investigations, three critiques over one coherent report set, and fresh
synthesis. Show recovery progress; keep detailed diagnostics private. Report an
inability to finish only when permitted recovery or an explicit spending limit is exhausted,
the user cancels, or an authorization or unresolved ownership blocker prevents work.

## Approach

The approved approach removes phase and overall session time caps. Each issued
request retains a finite timeout (1200 seconds by default), measured from its
issuance and never reset by resume. Recovery attempts get their own request timeout,
within existing attempt counts and any explicit spending limit. Maximum reasoning
remains unchanged. Unlimited individual requests would prevent a stalled provider
from yielding to recovery; rigid session caps would fail otherwise recoverable work.

Native text participants receive a short generated instruction naming one immutable
packet and its SHA-256. They may read and verify that packet only; no browsing,
repository inspection, writes, or delegation. Each phase still uses a fresh native
context. The coordinator checks observed access and packet integrity; this is not
an OS sandbox or proof supplied by the model's answer.

The phase allocations remain planning guidance for compatible request files, not
cancellation triggers. Preparation, checks and handoffs consume the issued attempt's
time. Each recovery investigation retains its 120-second bound. Early completion
advances immediately; recovery never duplicates an unresolved owner. Cancellation
and progress updates remain available throughout the session.

The runtime blocks phase advancement until the preceding phase has all three
accepted reports and stopped owners. Existing coherent-generation replacement rules
remain. Historical sessions retain their recorded scheduling and outcome semantics.
Free remains enabled for text only with zero-cost routing; Balanced stays recommended.

## Validation

Exercise packet integrity and narrow delivery, elapsed time beyond old phase targets,
nonrenewing attempt deadlines, recovery without losing accepted reports, missing-seat
barriers, and a full seven-answer session. Run Council regressions and package
validation. A paid live rerun is a separate follow-up.
