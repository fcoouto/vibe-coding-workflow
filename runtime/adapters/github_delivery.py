"""Bounded GitHub facts through a host-selected executable and executor.

The host executor must enforce the supplied deadline/output limits and retain its
actual execution provenance. JSON observations alone establish no check or merge
authority. No credential lookup or executable discovery occurs in this adapter.
"""
from pathlib import Path
import re
import subprocess

from runtime import delivery, evidence, state
from runtime.startup import json_object


def _require(condition):
    if not condition:
        raise state.StateError('GitHub delivery observation is unavailable or inconsistent')


def _commit(value):
    _require(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', value))
    return value


class GitHubDelivery:
    def __init__(self, *, executable, host, run):
        _require(isinstance(executable, str) and Path(executable).is_absolute()
                 and Path(executable).is_file() and callable(run))
        _require(isinstance(host, str) and re.fullmatch(r'[a-z0-9]+(?:[.-][a-z0-9]+)*', host))
        self.executable, self.host, self.run = executable, host, run

    def _read(self, endpoint):
        try:
            # The supported 2022 API retains merge_commit_sha; 2026 removes it.
            code, raw = self.run([self.executable, 'api', '--hostname', self.host,
                                 '-H', 'X-GitHub-Api-Version: 2022-11-28', endpoint],
                                 timeout=10, limit=128 * 1024)
            _require(type(code) is int and code == 0 and isinstance(raw, bytes)
                     and len(raw) <= 128 * 1024)
            return json_object(raw)
        except (OSError, ValueError, TypeError, subprocess.SubprocessError):
            # Provider diagnostics may contain credentials or private response text.
            raise state.StateError('GitHub delivery observation is unavailable or inconsistent') from None

    def observe(self, publication: dict) -> dict:
        evidence._bounded(publication)
        state._fields(publication, ('host', 'repository', 'target', 'branch', 'pull_request'),
                      ('id', 'provider', 'candidate', 'dependencies', 'required'))
        _require(publication['host'] == self.host)
        delivery._branch(publication['target'])
        delivery._branch(publication['branch'])
        repository = publication['repository']
        _require(isinstance(repository, str)
                 and re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+', repository)
                 and repository.split('/')[1] not in ('.', '..'))
        number = publication['pull_request']
        _require(type(number) is int and 0 < number <= 2 ** 53)
        repo = self._read('repos/' + repository)
        repo_id = repo.get('id')
        _require(type(repo_id) is int and repo_id > 0
                 and isinstance(repo.get('full_name'), str)
                 and repo['full_name'].casefold() == repository.casefold())
        pr = self._read(f'repos/{repository}/pulls/{number}')
        _require(type(pr.get('number')) is int and pr['number'] == number
                 and pr.get('state') in ('open', 'closed') and type(pr.get('draft')) is bool
                 and type(pr.get('merged')) is bool)
        for side, expected in (('base', publication['target']), ('head', publication['branch'])):
            row = pr.get(side)
            _require(isinstance(row, dict) and row.get('ref') == expected
                     and isinstance(row.get('repo'), dict)
                     and type(row['repo'].get('id')) is int and row['repo']['id'] == repo_id)
            _commit(row.get('sha'))
        if pr['merged']:
            _require(pr['state'] == 'closed' and isinstance(pr.get('merged_at'), str)
                     and bool(pr['merged_at'].strip()))
            _commit(pr.get('merge_commit_sha'))
        else:
            _require(pr.get('merged_at') is None)
        mergeability = pr.get('mergeable')
        _require(mergeability is None or type(mergeability) is bool)
        return dict(host=self.host, repository=repo['full_name'], repository_id=repo_id,
                    pull_request=number, state=pr['state'], draft=pr['draft'], merged=pr['merged'],
                    head=pr['head']['sha'], base=pr['base']['sha'], target=pr['base']['ref'],
                    branch=pr['head']['ref'], merge_commit=pr.get('merge_commit_sha') if pr['merged'] else None,
                    merged_at=pr.get('merged_at'), mergeability=mergeability,
                    checks='unobserved', reviews='unobserved')
