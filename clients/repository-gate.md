# Repository merge assurance

Load this contract only when assessing repository merge assurance. It is a bounded offline fixture inspector; it does not replace [Merge Readiness](../policies/08-merge-readiness.md), [Code Review](../policies/06-code-review.md), [Security Review](../policies/04-security-review.md), or [Tests and Builds](../policies/05-tests-and-builds.md).

Supply a UTF-8 JSON envelope on standard input to the installed package's CLI:

```sh
python3 -I -B /path/to/package/scripts/repository_gate.py < envelope.json
```

The envelope is version 1 and contains `policy`, `before`, `after`, and integer `now`. The policy and observations each use their current version-1 schema; nested runtime pins require `schema_version: 2`. Input is limited to 512 KiB. The CLI rejects malformed or ambiguous JSON and prints a bounded decision object. It always exits 1: no production publisher or evidence source is qualified.

`evidence_valid: true` means only that the supplied before/after records satisfy modeled checks and remain consistent. `source_authentication` remains `unverified`; `merge_authorized` and `published` remain false, with execution blockers. Caller-supplied records, fixture success, and this CLI cannot prove provenance, authorize a merge, or qualify repository enforcement. Do not weaken required D5/D6 coverage to make a fixture pass. See the [D7 validation record](../docs/d7-validation.md) for current qualification limits.
