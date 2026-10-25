# Claude startup and Superset host validation

25 October 2026. Scope: reuse the validated startup layer for another native client and establish Superset's actual integration boundary. Onboarding, enforcement, model routing and connector implementation remain later work.

## Candidate and automated proof

Claude runtime/manifest SHA-256: `c6224e1dad862fceb223d9e2da19b4b35fe7facaa294cd4ebb0f9dbbbb6ad79d`. The digest concatenates each ordered relative filename, NUL, exact bytes, NUL: `.claude-plugin/plugin.json`, `hooks/claude-code.json`, `scripts/workflow.py`, `runtime/startup.py`, `runtime/adapters/claude_code.py`, `runtime/adapters/session_start.py`, `runtime/adapters/codex.py`.

Policy digest: `e955274b00b5dbf75f266677e99da138f0c3da835e8c23ed7fc1e34c03be429d`; approved policies are unchanged.

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

Sources: [Claude hooks](https://code.claude.com/docs/en/hooks), [Claude plugin manifest](https://code.claude.com/docs/en/plugins-reference), [Superset agent integration](https://docs.superset.sh/add-agent-support), [Superset environment controls](https://docs.superset.sh/cli/env-vars).
