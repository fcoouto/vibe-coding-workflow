"""Bounded D7 fixture decisions and read-only GitHub metadata, without merge authority.

Policy must eventually come from a protected configuration and observations from
qualified sources. Neither requirement is established by passing Python/JSON data.
This module intentionally has no publishing or production authorization path.
"""

from datetime import datetime, timezone
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time
from urllib.parse import quote

from runtime.doctor import NativeProcess, ObservationError
from runtime.startup import StartupError, json_object


MAX_INPUT = 512 * 1024
MAX_ITEMS = 128
COVERAGE = {'general', 'security', 'behavior'}
COMMON = ('id', 'run_id', 'source', 'binding', 'observed_at', 'conclusion')
GITHUB_SECONDS = 15
GITHUB_API_VERSION = '2026-03-10'


class GateError(ValueError):
    """Sanitized invalid-envelope error; never includes submitted values."""


def _require(condition):
    if not condition:
        raise GateError('Invalid repository gate input')


def _fields(value, names):
    _require(type(value) is dict and set(value) == set(names))


def _text(value):
    _require(type(value) is str and 0 < len(value) <= 512 and value.isprintable() and bool(value.strip()))


def _integer(value, minimum=0, maximum=2**53):
    _require(type(value) is int and minimum <= value <= maximum)


def _items(value):
    _require(type(value) is list and len(value) <= MAX_ITEMS)
    return value


def _strings(value):
    for item in _items(value):
        _text(item)
    _require(len(set(value)) == len(value))


def _digest(value, commit=False):
    _require(type(value) is str and re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}' if commit else r'[0-9a-f]{64}', value) is not None)


def _source(value):
    _fields(value, ('issuer', 'workflow_ref', 'revision'))
    _text(value['issuer'])
    _text(value['workflow_ref'])
    _digest(value['revision'], commit=True)


def _pins(value, version=1):
    if version == 1:
        _fields(value, ('schema_version', 'policy_digest', 'runtime_digest'))
        _require(type(value['schema_version']) is int and value['schema_version'] == 2)
    else:
        _require(version == 2)
        _fields(value, ('schema_version', 'policy_digest', 'runtime_digest', 'accepted_scope_digest'))
        _require(type(value['schema_version']) is int and value['schema_version'] == 3)
        _digest(value['accepted_scope_digest'])
    _digest(value['policy_digest'])
    _digest(value['runtime_digest'])


def _target_ref(value):
    _text(value)
    _require(value.startswith('refs/heads/') and len(value) > len('refs/heads/'))
    _require(not any(char.isspace() or char in '~^:?*[\\' for char in value) and
             '..' not in value and '@{' not in value and not value.endswith('.') and
             all(part and not part.startswith('.') and not part.endswith('.lock') for part in value.split('/')))


def _binding(value, version=1):
    _fields(value, ('repository', 'target', 'head', 'base', 'candidate_digest', 'queue', 'pins', 'definitions_digest'))
    _text(value['repository'])
    _require(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', value['repository']) is not None)
    _target_ref(value['target'])
    for key in ('head', 'base'):
        _digest(value[key], commit=True)
    _digest(value['candidate_digest'])
    _digest(value['definitions_digest'])
    _pins(value['pins'], version)
    queue = value['queue']
    if queue is not None:
        _fields(queue, ('candidate', 'base', 'members'))
        _digest(queue['candidate'], commit=True)
        _digest(queue['base'], commit=True)
        _strings(queue['members'])
        _require(bool(queue['members']))
        for member in queue['members']:
            _digest(member, commit=True)


def _policy(value, version=1):
    _fields(value, ('version', 'binding', 'current_runs', 'max_age', 'merge_methods', 'queue_mode',
                    'bypass_actors', 'verifier', 'required_checks', 'required_reviews', 'writer_source', 'revoked_runs'))
    _require(type(value['version']) is int and value['version'] == version)
    _binding(value['binding'], version)
    _integer(value['max_age'], 1, 86400)
    _require(type(value['current_runs']) is dict and len(value['current_runs']) <= MAX_ITEMS)
    for record_id, run_id in value['current_runs'].items():
        _text(record_id)
        _text(run_id)
    _require(len(set(value['current_runs'].values())) == len(value['current_runs']))
    for name in ('merge_methods', 'bypass_actors', 'revoked_runs'):
        _strings(value[name])
    _require(bool(value['merge_methods']) and set(value['merge_methods']) <= {'merge', 'squash', 'rebase'})
    _require(value['queue_mode'] in ('disabled', 'required'))
    _require((value['binding']['queue'] is not None) == (value['queue_mode'] == 'required'))
    _source(value['verifier'])
    _source(value['writer_source'])
    ids = []
    for check in _items(value['required_checks']):
        _fields(check, ('id', 'source', 'definition_digest'))
        _text(check['id'])
        ids.append(check['id'])
        _source(check['source'])
        _digest(check['definition_digest'])
    _require(len(set(ids)) == len(ids))
    coverage = []
    for review in _items(value['required_reviews']):
        _fields(review, ('coverage', 'source', 'reviewers'))
        _require(review['coverage'] in COVERAGE)
        coverage.append(review['coverage'])
        _source(review['source'])
        _strings(review['reviewers'])
        _require(bool(review['reviewers']))
    _require('general' in coverage and len(set(coverage)) == len(coverage))


def _record(value, extra, version=1):
    _fields(value, (*COMMON, *extra))
    for name in ('id', 'run_id'):
        _text(value[name])
    _require(type(value['conclusion']) is str and len(value['conclusion']) <= 512)
    _source(value['source'])
    _binding(value['binding'], version)
    _integer(value['observed_at'])


def _review(value, version=1):
    _record(value, ('reviewer_id', 'author_id', 'coverage', 'findings', 'dispositions', 'decision_refs', 'rechecked_findings'), version)
    for key in ('reviewer_id', 'author_id'):
        _text(value[key])
    for name in ('coverage', 'decision_refs'):
        _strings(value[name])
    _require(set(value['coverage']) <= COVERAGE)
    ids = []
    for finding in _items(value['findings']):
        _fields(finding, ('id', 'severity', 'scope', 'status'))
        _text(finding['id'])
        ids.append(finding['id'])
        _require(finding['severity'] in ('critical', 'high', 'medium', 'low', 'info') and
                 finding['scope'] in COVERAGE and finding['status'] in ('confirmed', 'hypothesis', 'optional'))
    _require(len(set(ids)) == len(ids))
    dispositions = []
    for disposition in _items(value['dispositions']):
        _fields(disposition, ('finding_id', 'status', 'reason'))
        _text(disposition['finding_id'])
        _text(disposition['reason'])
        _require(disposition['status'] in ('open', 'accepted') and disposition['finding_id'] in ids)
        dispositions.append(disposition['finding_id'])
    _require(len(set(dispositions)) == len(dispositions))
    rechecks = []
    for recheck in _items(value['rechecked_findings']):
        _fields(recheck, ('attempt_id', 'finding_id', 'status', 'reference'))
        for key in ('attempt_id', 'finding_id', 'reference'):
            _text(recheck[key])
        _require(recheck['status'] in ('resolved', 'open'))
        rechecks.append((recheck['attempt_id'], recheck['finding_id']))
    _require(len(set(rechecks)) == len(rechecks))


def _observation(value, version=1):
    _fields(value, ('version', 'binding', 'observed_at', 'verifier', 'merge_method', 'bypass_actors', 'checks', 'reviews', 'writers'))
    _require(type(value['version']) is int and value['version'] == version)
    _binding(value['binding'], version)
    _integer(value['observed_at'])
    _source(value['verifier'])
    _text(value['merge_method'])
    _strings(value['bypass_actors'])
    for check in _items(value['checks']):
        _record(check, ('definition_digest',), version)
        _digest(check['definition_digest'])
    for review in _items(value['reviews']):
        _review(review, version)
    writers = value['writers']
    _record(writers, ('unresolved', 'reconciled'), version)
    _strings(writers['unresolved'])
    for writer in _items(writers['reconciled']):
        _fields(writer, ('identity', 'expected_revision', 'expected_pins', 'attempt_id', 'candidate_digest',
                         'plan_digest', 'stopped', 'descendants_stopped'))
        _fields(writer['identity'], ('client', 'session_id', 'task_id', 'scope_ref'))
        for field in writer['identity'].values():
            _text(field)
        _require(writer['identity']['client'] == 'codex')
        _integer(writer['expected_revision'], 1)
        _pins(writer['expected_pins'], version)
        _text(writer['attempt_id'])
        _digest(writer['candidate_digest'])
        _digest(writer['plan_digest'])
        _require(type(writer['stopped']) is bool and type(writer['descendants_stopped']) is bool)


def validate_envelope(value):
    """Validate the exact fixture schema; this does not authenticate any field."""
    try:
        _fields(value, ('version', 'policy', 'before', 'after', 'now'))
        _require(type(value['version']) is int and value['version'] in (1, 2))
        version = value['version']
        _integer(value['now'])
        _policy(value['policy'], version)
        _observation(value['before'], version)
        _observation(value['after'], version)
        _require(len(json.dumps(value, allow_nan=False).encode()) <= MAX_INPUT)
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
        raise GateError('Invalid repository gate input') from None
    return value


def _semantic(value, field=None):
    if type(value) is dict:
        return {key: _semantic(item, key) for key, item in value.items() if key != 'observed_at'}
    if type(value) is list:
        items = [_semantic(item) for item in value]
        return items if field == 'members' else sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    return value


def _blockers(policy, observed, now):
    blockers = set()
    binding = policy['binding']

    def fresh(value):
        if not 0 <= now - value['observed_at'] <= policy['max_age']:
            blockers.add('stale_evidence')

    def record(value, source):
        fresh(value)
        if value['observed_at'] > observed['observed_at']:
            blockers.add('record_after_capture')
        if value['binding'] != binding:
            blockers.add('record_binding_mismatch')
        if value['source'] != source:
            blockers.add('source_mismatch')
        if policy['current_runs'].get(value['id']) != value['run_id']:
            blockers.add('replayed_evidence')
        if value['run_id'] in policy['revoked_runs']:
            blockers.add('revoked_evidence')

    fresh(observed)
    if observed['binding'] != binding:
        blockers.add('binding_mismatch')
    if observed['verifier'] != policy['verifier']:
        blockers.add('verifier_mismatch')
    if observed['merge_method'] not in policy['merge_methods']:
        blockers.add('unsupported_merge_method')
    if set(observed['bypass_actors']) != set(policy['bypass_actors']):
        blockers.add('bypass_mismatch')
    records = [*observed['checks'], *observed['reviews'], observed['writers']]
    for field in ('id', 'run_id'):
        if len({r[field] for r in records}) != len(records):
            blockers.add('duplicate_record')
    definitions = {check['id']: check for check in policy['required_checks']}
    for check in observed['checks']:
        definition = definitions.get(check['id'])
        if definition is None:
            blockers.add('unexpected_check')
            continue
        record(check, definition['source'])
        if check['definition_digest'] != definition['definition_digest']:
            blockers.add('check_definition_mismatch')
        if check['conclusion'] != 'success':
            blockers.add('check_not_success')
    if set(definitions) - {check['id'] for check in observed['checks']}:
        blockers.add('missing_check')
    covered = set()
    trusted_reviews = []
    for review in observed['reviews']:
        rules = [r for r in policy['required_reviews'] if r['coverage'] in review['coverage']]
        if set(review['coverage']) - {r['coverage'] for r in rules}:
            blockers.add('review_coverage_mismatch')
        if not rules:
            blockers.add('missing_review')
        valid = True
        for rule in rules:
            record(review, rule['source'])
            if review['reviewer_id'] not in rule['reviewers']:
                blockers.add('untrusted_reviewer')
                valid = False
        if review['conclusion'] != 'success':
            blockers.add('review_not_success')
            valid = False
        if review['reviewer_id'] == review['author_id']:
            blockers.add('review_not_independent')
            valid = False
        if valid and rules:
            covered.update(r['coverage'] for r in rules)
            trusted_reviews.append(review)
    if {r['coverage'] for r in policy['required_reviews']} - covered:
        blockers.add('missing_review')
    for review in observed['reviews']:
        dispositions = {d['finding_id']: d for d in review['dispositions']}
        for finding in review['findings']:
            if finding['scope'] not in review['coverage']:
                blockers.add('finding_coverage_mismatch')
            if finding['status'] == 'optional':
                continue
            rechecks = [item for fresh_review in trusted_reviews
                        if fresh_review['id'] != review['id'] and fresh_review['reviewer_id'] != review['reviewer_id']
                        and fresh_review['observed_at'] >= review['observed_at'] and finding['scope'] in fresh_review['coverage']
                        for item in fresh_review['rechecked_findings']
                        if item['attempt_id'] == review['id'] and item['finding_id'] == finding['id']]
            if rechecks and all(item['status'] == 'resolved' for item in rechecks):
                continue
            disposition = dispositions.get(finding['id'], {})
            high_security = finding['scope'] == 'security' and finding['status'] == 'confirmed' and finding['severity'] in ('high', 'critical')
            if high_security or disposition.get('status') != 'accepted' or not review['decision_refs']:
                blockers.add('unresolved_finding')
    writers = observed['writers']
    record(writers, policy['writer_source'])
    if writers['conclusion'] != 'success' or writers['unresolved']:
        blockers.add('unresolved_writers')
    attempts = set()
    for writer in writers['reconciled']:
        key = (*(writer['identity'][name] for name in ('client', 'session_id', 'task_id', 'scope_ref')), writer['attempt_id'])
        if key in attempts:
            blockers.add('duplicate_record')
        attempts.add(key)
        if not writer['stopped'] or not writer['descendants_stopped']:
            blockers.add('unresolved_writers')
        if (writer['expected_pins'] != binding['pins'] or writer['candidate_digest'] != binding['candidate_digest']
                or writer['plan_digest'] != binding['definitions_digest']):
            blockers.add('writer_binding_mismatch')
    return blockers


def evaluate(policy, before, after, *, now):
    """Evaluate supplied fixture decisions; no supplied object grants trust.

    Separate protected policy and independently acquired source observations are
    prerequisites for future integration. The execution boundary remains closed
    even when every modeled requirement passes. This function writes no state.
    """
    result = dict(evidence_valid=False, blockers=[], execution_blockers=['unqualified_publisher', 'unqualified_evidence_source'],
                  source_authentication='unverified', merge_authorized=False, published=False)
    try:
        version = policy.get('version') if type(policy) is dict else None
        validate_envelope(dict(version=version, policy=policy, before=before, after=after, now=now))
    except GateError:
        result['blockers'] = ['invalid_input']
        return result
    blockers = _blockers(policy, before, now) | _blockers(policy, after, now)
    if _semantic(before) != _semantic(after) or after['observed_at'] < before['observed_at']:
        blockers.add('inputs_changed')
    result.update(evidence_valid=not blockers, blockers=sorted(blockers))
    return result


def read_envelope(raw):
    """Parse bounded UTF-8 JSON and reject ambiguous duplicate keys/constants."""
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result)
            result[key] = value
        return result

    def invalid_constant(value):
        raise GateError('Invalid repository gate input')

    try:
        _require(type(raw) is bytes and len(raw) <= MAX_INPUT)
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=object_pairs, parse_constant=invalid_constant)
        return validate_envelope(value)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise GateError('Invalid repository gate input') from None


def _github_output(executable, arguments, deadline, limit=512 * 1024):
    child = NativeProcess([str(executable), *arguments], deadline, stdin=subprocess.DEVNULL)
    try:
        raw = b''
        while True:
            chunk = child.read(deadline)
            if not chunk:
                break
            raw += chunk
            if len(raw) > limit:
                raise ObservationError('github_output_limit')
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ObservationError('timeout')
        return raw, child.process.wait(timeout=remaining)
    finally:
        child.close()


def _github_request(executable, endpoint, deadline):
    raw, code = _github_output(executable, ['api', '--hostname', 'github.com', '--method', 'GET', '--include',
        '-H', 'Accept: application/vnd.github+json', '-H', 'X-GitHub-Api-Version: ' + GITHUB_API_VERSION,
        '-H', 'Cache-Control: no-cache', endpoint], deadline)
    header, separator, body = raw.replace(b'\r\n', b'\n').partition(b'\n\n')
    lines = header.split(b'\n')
    _require(separator and re.fullmatch(rb'HTTP/(?:1\.[01]|2(?:\.0)?) [0-9]{3}(?: [\x20-\x7e]*)?', lines[0]))
    _require(all(re.fullmatch(rb'[A-Za-z0-9-]+:[\x20-\x7e]*', line) for line in lines[1:]))
    status = int(lines[0].split()[1])
    headers = BytesParser().parsebytes(b'\n'.join(lines[1:]) + b'\n\n')
    _require(not headers.defects and all(len(headers.get_all(key, [])) == 1
        for key in ('Content-Type', 'Date', 'X-GitHub-Request-Id')) and len(headers.get_all('ETag', [])) <= 1)
    _require(headers.get_content_type() == 'application/json')
    date, request_id, etag = (headers.get(key) for key in ('Date', 'X-GitHub-Request-Id', 'ETag'))
    for value in (date, request_id, etag):
        if value is not None:
            _text(value)
    _require(parsedate_to_datetime(date).tzinfo is not None)
    if status != 200:
        raise ObservationError('github_http_' + str(status))
    if code != 0:
        raise ObservationError('github_request_failed')
    return json_object(body), dict(endpoint=endpoint, status=status, server_date=date, etag=etag, request_id=request_id)


def _github_branch(value):
    _target_ref('refs/heads/' + value['ref'])
    _digest(value['sha'], commit=True)
    repository = value['repo']
    _integer(repository['id'], 1)
    _integer(repository['owner']['id'], 1)
    return dict(repository_id=repository['id'], owner_id=repository['owner']['id'], ref=value['ref'], sha=value['sha'])


def observe_github(repository, target_ref, pull_number):
    """Read selected server metadata through existing gh authentication; never issue authority.

    Responses are sequential observations, not an atomic snapshot or native D5/D6
    evidence. Executable hashes and HTTP metadata establish no protected custody.
    """
    started = time.monotonic()
    deadline = started + GITHUB_SECONDS
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        _text(repository)
        _require(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository) is not None and
                 all(part not in ('.', '..') for part in repository.split('/')))
        _target_ref(target_ref)
        _integer(pull_number, 1)
        selected = shutil.which('gh')
        if selected is None:
            raise ObservationError('github_executable_unavailable')
        executable = Path(selected).resolve(strict=True)
        _require(stat.S_ISREG(executable.stat().st_mode))
        fingerprint = hashlib.sha256()
        with executable.open('rb') as stream:
            while True:
                if time.monotonic() >= deadline:
                    raise ObservationError('timeout')
                chunk = stream.read(64 * 1024)
                if not chunk:
                    break
                fingerprint.update(chunk)
        raw, code = _github_output(executable, ['--version'], deadline, limit=4096)
        version = raw.decode('ascii').splitlines()[0]
        _require(code == 0 and re.fullmatch(r'gh version [0-9]+\.[0-9]+\.[0-9]+[^\r\n]*', version) is not None)
        _text(version)
        prefix = '/repos/' + repository
        endpoints = ['/user', prefix, prefix + '/pulls/' + str(pull_number),
                     prefix + '/git/ref/' + quote(target_ref[len('refs/'):], safe='/')]
        values, requests = [], []
        for endpoint in endpoints:
            value, provenance = _github_request(executable, endpoint, deadline)
            values.append(value)
            requests.append(provenance)
        account, repo, pull, target = values
        _text(account['login'])
        _integer(account['id'], 1)
        _integer(repo['id'], 1)
        _integer(repo['owner']['id'], 1)
        _text(repo['node_id'])
        _text(repo['full_name'])
        _text(repo['owner']['login'])
        _require(repo['full_name'].casefold() == repository.casefold() and
                 repo['owner']['login'].casefold() == repository.split('/')[0].casefold())
        _integer(pull['id'], 1)
        _integer(pull['number'], 1)
        _require(pull['number'] == pull_number and pull['state'] in ('open', 'closed') and
                 type(pull['merged']) is bool and type(pull['draft']) is bool)
        base, head = _github_branch(pull['base']), _github_branch(pull['head'])
        _require(base['repository_id'] == repo['id'] and base['owner_id'] == repo['owner']['id'] and
                 base['ref'] == target_ref[len('refs/heads/'):])
        _require(target['ref'] == target_ref and target['object']['type'] == 'commit')
        _digest(target['object']['sha'], commit=True)
        if time.monotonic() >= deadline:
            raise ObservationError('timeout')
        return dict(account=dict(login=account['login'], id=account['id']),
            repository=dict(id=repo['id'], node_id=repo['node_id'], full_name=repo['full_name'], owner_id=repo['owner']['id']),
            target=dict(ref=target['ref'], sha=target['object']['sha']),
            pull_request=dict(id=pull['id'], number=pull['number'], state=pull['state'], merged=pull['merged'],
                              draft=pull['draft'], base=base, head=head),
            provenance=dict(mechanism='github-rest-via-gh', host='github.com', api_version=GITHUB_API_VERSION,
                resolved_path=str(executable), version=version, sha256=fingerprint.hexdigest(),
                started_at=started_at, finished_at=datetime.now(timezone.utc).isoformat(),
                duration=time.monotonic() - started, requests=requests), merge_authority=False)
    except ObservationError:
        raise
    except (GateError, StartupError, OSError, ValueError, TypeError, KeyError, IndexError,
            UnicodeError, RecursionError, OverflowError, subprocess.SubprocessError):
        raise ObservationError('github_observation_unavailable') from None
