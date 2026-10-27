# Claude startup and Superset host validation

25 October 2026 evidence record, with a 27 October 2026 status note below. Original scope: reuse the validated startup layer for another native client and establish Superset's actual integration boundary. That native observation applies to the historical startup-only candidate and listed versions; it does not qualify later hook definitions or runtime behavior.

## Candidate and automated proof

Claude runtime/manifest SHA-256: `c6224e1dad862fceb223d9e2da19b4b35fe7facaa294cd4ebb0f9dbbbb6ad79d`. The digest concatenates each ordered relative filename, NUL, exact bytes, NUL: `.claude-plugin/plugin.json`, `hooks/claude-code.json`, `scripts/workflow.py`, `runtime/startup.py`, `runtime/adapters/claude_code.py`, `runtime/adapters/session_start.py`, `runtime/adapters/codex.py`.

Historical policy digest for the 25 October 2026 candidate snapshot: `e955274b00b5dbf75f266677e99da138f0c3da835e8c23ed7fc1e34c03be429d`; the approved policies were unchanged at that snapshot.

- Package validation passed.
- 54 tests passed. Both native adapters run the shared acceptance cases, including checkout/worktree isolation, wrong-client enrollment, malformed records, settings preservation and hostile Python/Git environments.
- Superset environment hints cannot activate an unrelated checkout or replace native client enrollment.
- Package checks reject duplicate Claude default hooks, divergent manifest versions and paths escaping the package.
- `git diff --check` passed.
- Independent code/security review found no actionable issues in the adapters, shared parser, routing, manifests, validator or host guidance; the reviewer independently ran all 54 tests and package checks.

## Native execution

| Surface | Evidence |
| --- | --- |
| Claude Code CLI 2.1.304 | Strict plugin validation passed with zero errors/warnings. One enrolled startup hook supplied local context. Unrelated and Codex-only enrollment produced no context. Malformed enrollment produced a diagnostic. Disabled hooks did not execute. |
| Codex CLI 0.163.0 | Regression probe passed: one enrolled context injection, unrelated silence, malformed diagnostic, untrusted/modified definitions prevented execution. |
| Codex desktop-bundled app-server 0.164.0-alpha.11.1 | Same regression cases passed; modified content was rejected with an approval-required failure event. |

All probes used disposable homes/configuration and repositories, an environment allowlist without credentials, and denied network access. No real client settings, authentication or project enrollment changed. Processes were stopped afterward.

Claude used `--init-only --plugin-dir <copy> --setting-sources user`, which runs startup without starting a conversation. Native debug output confirmed one handler and accepted context. The final enrolled observation took 50 ms; this is one observation, not a performance distribution. Codex used the previously inspected separate stop hook. No probe generated a model response.

Adding license-holder author metadata resolved the initial strict-validation warning. Strict validation and one enrolled Claude startup were rerun against that final manifest. Other cases remain applicable because runtime, registration and enrollment behavior were unchanged. The validator's marketplace-install advice remains advisory; local `--plugin-dir` loading was qualified, not published marketplace distribution.

## Superset inspection

Installed Superset and its bundled CLI are version 1.40.0. The CLI rejects `plugins` as an unknown command. This release hosts native agents and has no independently qualified workflow startup protocol, so no placeholder `superset.py` was added.

Installed source in `app.asar` shows:

- `dist/main/templates/codex-wrapper-exec.template.sh`: adds project trust for a workspace config and adds `--dangerously-bypass-hook-trust` when absent.
- `dist/main/chunks/host-service-utils-CkZE9Cf4.js`: default agent launch commands contain permission bypasses.
- `dist/main/host-service.js`: supplies `SUPERSET_*` workspace/terminal environment hints.

The plugin does not copy these launch flags or treat the environment hints as authorization. Real Superset execution remains unqualified until the selected launch path, final arguments, permissions and hook behavior are reconciled and observed. Source inspection cannot establish actual launch behavior.

## Limits

Claude Desktop is not installed here. Desktop Code, Cowork, Superset launches, desktop UI behavior and model policy compliance remain untested. Native startup success does not qualify those surfaces or later enforcement features.

## Current package status (27 October 2026)

The historical Claude Code CLI 2.1.304 startup observation and source digest above remain evidence for that exact startup-only candidate. The prepared D8 checkpoint at `f166a21` had ordered runtime/manifest source digest `cfbe62d0f28fa325a0dbe45493406ca7fcffb161472749da820e56a12b95b4a5`, versus the historical `c6224e1dad862fceb223d9e2da19b4b35fe7facaa294cd4ebb0f9dbbbb6ad79d`. Later D4 startup integration changes alter source files, so the D8 checkpoint digest is not a hash of the current integrated package. The prepared D8 package adds a Claude `PreToolUse` definition for `Edit`, `Write` and `NotebookEdit`; the old full-source qualification cannot be reused. No current Claude runtime hook or task-control execution was observed.

The current package contains prepared canonical per-client Claude file-guard and task-state support. The [shared startup contract](../clients/startup.md#enrollment-input) documents the schema-1 Codex-only runtime and pending production canonical-resolver integration. Claude native runtime qualification remains pending. Claude D5 evidence, D6 delegation, retirement, turn correlation and continuation remain unsupported. Superset implementation remains suspended; do not infer its behavior from Claude Code. Desktop Code requires separate capability qualification; Cowork remains unqualified.

Sources: [Claude hooks](https://code.claude.com/docs/en/hooks), [Claude plugin manifest](https://code.claude.com/docs/en/plugins-reference), [Superset agent integration](https://docs.superset.sh/add-agent-support), [Superset environment controls](https://docs.superset.sh/cli/env-vars).
