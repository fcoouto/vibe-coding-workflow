"""Disposable accepted scopes for managed OpenRouter tests; no live account state."""
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

from runtime import startup, state

PACKAGE = Path(__file__).resolve().parents[1]


def enroll(repo, private):
    repo.mkdir(exist_ok=True)
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
    subprocess.run(['git', 'init', '-q', '--template=', str(repo)], env=env, check=True, capture_output=True)
    root, common = startup.checkout(repo)
    record = dict(schema_version=1, project_id='openrouter-fixture', repository_root=str(root),
                  git_common_dir=str(common), clients=['codex'], policy_digest=startup.policy_digest(PACKAGE),
                  runtime=dict(schema_version=2, state_dir=str(private)))
    path = repo / startup.PROJECT_FILE
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(record))
    scope = startup.resolve_project(SimpleNamespace(client='codex', cwd=repo), PACKAGE)
    state.start_task(scope, dict(client='codex', session_id='fixture-session', task_id='fixture-task',
        scope_ref='test:scope', mode='read-only', decision_ref='test:scope'))
    return scope


def configure(repo, *, executable=None, auth=None, routes=('proposals', 'workers')):
    from runtime import openrouter_settings as settings
    report = settings.configure(repo, dict(expected_revision=0, routes=list(routes),
        opencode=str(executable) if executable else None, auth_data=str(auth) if auth else None))
    request = dict(expected_revision=report['revision'])
    if 'workers' in routes: request['consent_version'] = 2
    return settings.enable(repo, request)
