"""Reconstructed persisted v1 inputs, not captured execution or current issuance.

The pinned 397648a producer defines the format. No old code runs and no host,
qualification, source-completeness or current publication authority is issued.
The installer owns only its newly allocated disposable stores.
"""

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from runtime import changes, state


HISTORICAL_RUNTIME_DIGEST = '02922a4dd3bc14ba70e158f61a73ea7cd46fe033e18421305fb2a69d5c6ca8c3'


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def _binding(path):
    info = path.lstat()
    return dict(device=info.st_dev, inode=info.st_ino)


class ReconstructedV1History:
    AUTHORITY_CREATED_AT = 1700000000
    SOURCE_CREATED_AT = 1700000100

    def __init__(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='vcw-reconstructed-v1-')
        self.root = Path(self.temporary.name).resolve()
        self.owner = dict(kind='project', project_id='reconstructed_history', task=None)
        try:
            self._install()
        except BaseException:
            self.cleanup()
            raise

    def cleanup(self):
        self.temporary.cleanup()

    def _install(self):
        self.directories = [self.root / 'first', self.root / 'second']
        for directory in self.directories:
            directory.mkdir(mode=0o700)
            (directory / 'evidence').mkdir(mode=0o700)
            database = directory / 'runtime.sqlite3'
            descriptor = os.open(database, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            with closing(sqlite3.connect(database)) as db, db:
                for declaration in (*state.CANONICAL_TABLE_SQL.values(), *state.CANONICAL_INDEX_SQL.values()):
                    db.execute(declaration)
                db.execute('pragma application_id=' + str(state.APPLICATION_ID))
                db.execute('pragma user_version=3')
        self.authorities = [state._authority_identity(path / 'runtime.sqlite3') for path in self.directories]
        project = self.root / 'project'
        project.mkdir(mode=0o700)
        plan_dir = self.root / 'plan'
        plan_dir.mkdir(mode=0o700)
        # These policy/catalog pins are reconstructed constants, not captured provenance.
        pins = dict(policy_digest='1' * 64, runtime_digest=HISTORICAL_RUNTIME_DIGEST)
        plan = dict(package_pins=pins, identity=dict(project_id=self.owner['project_id'],
            project_root=str(project), binding=_binding(project)))
        manifest = dict(schema_version=2, transaction_id='reconstructed-v1-history',
            plan=dict(plan_id='reconstructed-plan', revision=1, review_digest='2' * 64, current_input_digest='3' * 64),
            pins=dict(package_pins=pins, toolkit_commit='4' * 40, sources_digest='5' * 64),
            authorization_reference='fixture:reconstructed-history', approved_scope=['enrollment'],
            owners=[], actions=[], enrollment=dict(record=dict(project_root=str(project)),
                before=dict(revision=None, raw_sha256=None, target=None), affected=[], requires=[], qualification=[]))
        self.journal = dict(schema_version=2, transaction_id=manifest['transaction_id'],
            manifest_digest=state._digest(manifest), manifest=manifest,
            approval=dict(reference=manifest['authorization_reference'], evidence=[], manifest_digest=state._digest(manifest)),
            plan=plan, state='prepared', receipts={}, enrollment=None, blocked=[], directories={}, observations=[])
        changes._scoped_journal_shape(self.journal)
        journal_raw = json.dumps(self.journal, sort_keys=True, ensure_ascii=True).encode() + b'\n'
        descriptor = os.open(plan_dir / 'transaction.json', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(journal_raw)
        self.identity = dict(plan_dir=str(plan_dir), transaction_id=manifest['transaction_id'],
            manifest_digest=self.journal['manifest_digest'])
        prior = dict(version=1, kind='d4-recovery-source', identity=self.identity,
            journal=dict(sha256=hashlib.sha256(journal_raw).hexdigest(), observed_at=self.SOURCE_CREATED_AT,
                state=self.journal['state']), authorities=sorted(self.authorities, key=state._digest),
            tasks=[], assignments=[], artifacts=[], previous=None)
        self.prior = self._artifact(0, 'a' * 32 + '.json', prior, self.SOURCE_CREATED_AT, [])
        self.second_source = self._artifact(1, 'b' * 32 + '.json', prior, self.SOURCE_CREATED_AT, [])
        head = dict(prior, authorities=[self.authorities[0]], previous=self.prior,
            journal=dict(prior['journal'], observed_at=self.SOURCE_CREATED_AT + 1))
        edge = dict(kind='recovery', reference=dict(authority=self.authorities[0], artifact=self.prior))
        self.head = self._artifact(0, 'c' * 32 + '.json', head, self.SOURCE_CREATED_AT, [edge])
        self.baselines = []
        for index, authority in enumerate(self.authorities):
            baseline = dict(version=1, kind='authority-source-baseline', source_contract=2,
                authority=authority, project_id=self.owner['project_id'], created_at=self.AUTHORITY_CREATED_AT,
                runtime_digest=HISTORICAL_RUNTIME_DIGEST)
            edge = dict(kind='recovery', reference=dict(identity=self.identity,
                artifact=self.head if index == 0 else self.second_source))
            self.baselines.append(self._artifact(index, state._source_baseline_name(authority),
                baseline, self.AUTHORITY_CREATED_AT, [edge]))
        self.contexts = tuple(changes._recovery_context(authority) for authority in self.authorities)

    def _artifact(self, index, name, content, created_at, dependencies):
        directory = self.directories[index]
        path = directory / 'evidence' / name
        raw = _raw(content)
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o400)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
        digest = hashlib.sha256(raw).hexdigest()
        metadata = dict(version=1, owner=self.owner, created_at=created_at,
            **{'class': 'compact'}, bytes=len(raw), status='live', closed_at=None,
            dependencies=dependencies, targets=[], export=None,
            managed=dict(path=str(path), binding=_binding(path),
                parents={str(directory): _binding(directory), str(path.parent): _binding(path.parent)},
                sha256=digest, mode=path.stat().st_mode & 0o777, bytes=path.stat().st_size))
        row = (name, digest, 'project:' + self.owner['project_id'], 'compact', created_at,
            None, 'live', len(raw), _raw(metadata).decode())
        state._metadata_record(row)
        with closing(sqlite3.connect(directory / 'runtime.sqlite3')) as db, db:
            db.execute('insert into evidence_metadata values(?,?,?,?,?,?,?,?,?)', row)
        return dict(name=name, digest=digest)

    def snapshot(self):
        """Read exact fixture files; inspection lock files live outside these stores."""
        return {str(path.relative_to(self.root)): (path.read_bytes(), path.stat().st_mode, _binding(path))
            for path in self.root.rglob('*') if path.is_file()}
