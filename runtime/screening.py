"""One-use accounting for authenticated fresh temporary owner publications."""

from copy import deepcopy
from pathlib import Path
import time
import uuid

from runtime import evidence, state
from runtime.startup import _check_observation_deadline


def _fresh():
    return dict(version=1, birth='temporary-owner-publication', limit_ms=300000,
                revision=0, charged_ms=0, settled_sequence=0, reservation=None, last_receipt=None)


def _check_birth(context, db, targets, budget):
    from runtime import review_storage as storage
    acquired = storage._MACHINE_ACQUISITION.get()
    storage._require(acquired is not None and any(context is selected for selected in acquired['contexts']))
    config = storage._configuration(acquired['path'], acquired['descriptor'])
    storage._require(config is not None)
    owners = storage._owners(config, context, db, budget=budget)
    storage._require(not storage._related_owners(owners, targets, budget))


def _protected(identity=None):
    return dict(identity or {}, ok=False, status='protected', admitted=False, screening=None, revision=None)


class _Control:
    def __init__(self, operation, argument, entered):
        self.operation, self.argument, self.entered = operation, argument, entered
        self.write = operation != 'status'
        self.identity = None

    def access(self, config, context, select, reobserve, budget):
        """Use the resolver's live guard and context, never its returned accounting mapping."""
        from runtime import review_storage as storage
        acquired = storage._MACHINE_ACQUISITION.get()
        storage._require(acquired is not None and any(context is selected for selected in acquired['contexts']))
        expected = None

        def validate(db):
            reobserve()
            storage._require(storage._owners(config, context, db, budget=budget) == owners)
            if expected is not None:
                storage._require(state._metadata(db, owner['reference']['name']) == expected)
            if budget is not None:
                _check_observation_deadline(budget)

        with evidence._context_database(context, write=self.write, durable=self.write,
                                        before_commit=validate if self.write else None) as db:
            owners = storage._owners(config, context, db, budget=budget)
            owner = select(owners)
            if owner is None:
                result = _protected()
            else:
                self.identity = {key: owner[key] for key in ('owner', 'reference', 'created_at')}
                metadata = state._metadata(db, owner['reference']['name'])
                result = self.transition(db, metadata)
                expected = state._metadata(db, owner['reference']['name'])
            validate(db)
        return result

    def transition(self, db, metadata):
        screening = metadata.get('screening')
        if screening is None:
            return _protected(self.identity)
        state._screening_record(screening)
        current = deepcopy(screening)
        admitted = False
        if self.operation == 'reserve' and current['revision'] == self.argument == 0:
            ticket = dict(sequence=1, nonce=uuid.uuid4().hex, ceiling_ms=300000)
            current.update(revision=1, reservation=ticket)
            admitted = True
        elif self.operation == 'settle':
            try:
                state._screening_ticket(self.argument)
            except state.StartupError:
                return _protected(self.identity)
            if current['revision'] == 1 and current['reservation'] == self.argument:
                current.update(revision=2, charged_ms=300000, settled_sequence=1,
                    reservation=None, last_receipt=dict(ticket=deepcopy(self.argument), disposition='charged-full'))
            elif current['revision'] != 2 or current['last_receipt']['ticket'] != self.argument:
                return _protected(self.identity)
        if current != screening:
            state._screening_record(current)
            changed = dict(metadata, screening=current)
            db.execute('update evidence_metadata set data=? where name=?',
                       (evidence._raw(changed).decode(), self.identity['reference']['name']))
        result = dict(self.identity, ok=True, status={0: 'available', 1: 'reserved', 2: 'settled'}[current['revision']],
                      admitted=admitted, screening=current, revision=current['revision'])
        if admitted:
            result['deadline_monotonic'] = self.entered + 300
        return result


def operate(selection, operation, argument=None):
    entered = time.monotonic()
    from runtime import review_storage as storage
    control = _Control(operation, argument, entered)
    try:
        evidence._bounded(selection)
        storage._require(isinstance(selection, dict) and set(selection) in ({'target'}, {'project_scope'}))
        if operation == 'reserve':
            state._integer(argument, 'expected screening revision')
        if 'target' in selection:
            target = selection['target']
            storage._require(isinstance(target, str) and Path(target).is_absolute() and len(target) <= 4096)
            enrolled = storage.acquire_enrolled_accounting(target)
            if enrolled['status'] != 'outside':
                return _protected(enrolled)
            result = storage._temporary_target_result(target, budget=storage._budget(), control=control)
        else:
            result = storage._project_owner_result(selection['project_scope'], control=control)
        if 'admitted' not in result:
            status = result.get('status')
            result = _protected(dict(control.identity or {}, **result))
            if status == 'storage_pending':
                result['status'] = status
        return result
    except storage._HistoryConflict as error:
        return _protected(storage._history_protected(error.owners))
    except (*storage._ERRORS, RuntimeError):
        return _protected(control.identity)


def screening_status(selection):
    return operate(selection, 'status')


def reserve_screening(selection, expected_revision):
    return operate(selection, 'reserve', expected_revision)


def settle_screening(selection, ticket):
    return operate(selection, 'settle', ticket)
