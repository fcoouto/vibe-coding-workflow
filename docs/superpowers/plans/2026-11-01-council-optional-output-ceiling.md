# Council optional output ceiling

The user approved omitting `max_tokens` by default after a controlled Dots
comparison: the advertised 460800 ceiling failed twice, while 8192 and omission
completed with reasoning enabled. This change targets direct text requests only.

## Implementation

- Add a regression that sends a direct request without an output ceiling. Retain
  integer validation for explicit ceilings and all existing transport boundaries.
- Update direct payload construction to omit the default ceiling. Preserve an
  explicit source-backed `output_capacity` correction and repository behavior.
- Keep token targets advisory and maximum reasoning, deadlines, consent, scope,
  technical completion and Free-disable guards intact. Align the local procedure,
  transport contract and source coverage with the resulting behavior.
- Observe focused regression failure before implementation. Run affected Council
  checks and `python3 -B scripts/validate.py`; obtain one independent diff review.
- Merge only this change into the user-confirmed plugin integration branch,
  `codex/project-repository-adjustments`. Preserve unrelated edits. Do not merge
  the isolated Free qualification branch, push, or change installed settings.
