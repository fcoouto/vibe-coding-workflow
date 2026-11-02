"""Native ownership is supplied by a trusted host, then checked against real Git."""
import importlib.util
import unittest

from runtime import evidence, state
from tests import test_delivery


class DeliveryWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_delivery.DeliveryPlanTests('runTest')
        self.fixture.linked = True
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.scope = self.fixture.scope
        from runtime import delivery
        delivery.operate(self.scope, 'plan', self.fixture.request(plan=self.fixture.plan()))

    def owner(self, request, observation):
        self.assertIsNotNone(importlib.util.find_spec('scripts.delivery_coordinator'), 'Delivery owner is missing')
        from scripts.delivery_coordinator import DeliveryOperationOwner

        class Native:
            def observe_worktree(native, root):
                return observation() if callable(observation) else observation

        decision = dict(action='bind-worktree', request_digest=evidence._digest(request),
                        accepted_scope_digest=self.scope.accepted_scope_digest, reference='fixture:host-observation')
        return DeliveryOperationOwner(decision, native=Native(), repository=None, gate=None)

    def observation(self):
        return dict(root=str(self.scope.repository_root), owner='codex',
                    attachment='fixture:native-managed-worktree', reference='fixture:observed-attachment')

    def test_binds_actual_admitted_destination_without_rebinding_task(self):
        request = self.fixture.request(operation_id='workspace-1')
        result = self.owner(request, self.observation()).run(self.scope, 'bind-worktree', request)
        self.assertEqual(result['plan']['workspace']['root'], str(self.scope.repository_root))
        self.assertNotEqual(self.scope.git_dir, self.scope.git_common_dir)
        self.assertEqual(result['task']['accepted_identity']['checkout_id'], self.scope.checkout_id)
        self.assertEqual(result['plan']['workspace']['cleanup_owner'], 'client')

    def test_uncertain_or_foreign_native_attachment_does_not_bind(self):
        from runtime import delivery
        for observation in (None, self.observation() | dict(root=str(self.scope.primary_root))):
            request = self.fixture.request(operation_id='workspace-1')
            with self.assertRaises(ValueError):
                self.owner(request, observation).run(self.scope, 'bind-worktree', request)
            status = delivery.operate(self.scope, 'status', dict(client='codex', session_id='delivery'))
            self.assertIsNone(status['plan']['workspace'])

    def test_untrusted_request_or_changed_owner_binding_cannot_authorize(self):
        from runtime import delivery
        request = self.fixture.request(operation_id='workspace-1')
        with self.assertRaises(ValueError):
            delivery.operate(self.scope, 'bind-worktree', request)
        owner = self.owner(request, self.observation())
        with self.assertRaises(ValueError):
            owner.run(self.scope, 'bind-worktree', request | dict(operation_id='different'))

    def test_replay_reuses_completed_binding_without_another_native_observation(self):
        request = self.fixture.request(operation_id='workspace-1')
        owner = self.owner(request, self.observation())
        first = owner.run(self.scope, 'bind-worktree', request)
        second = owner.run(self.scope, 'bind-worktree', request)
        self.assertEqual(first['task']['revision'], second['task']['revision'])
        self.assertEqual(first['plan'], second['plan'])

    def test_replaced_checkout_cannot_bind_before_or_during_native_observation(self):
        import shutil
        request = self.fixture.request(operation_id='workspace-1')
        root = self.scope.repository_root
        original = root.with_name(root.name + '-original')
        database = state._path(self.scope)
        before = database.read_bytes()

        def replace():
            root.rename(original)
            shutil.copytree(original, root)
            return self.observation()

        with self.assertRaises(ValueError):
            self.owner(request, replace).run(self.scope, 'bind-worktree', request)
        self.assertEqual(database.read_bytes(), before)
        with self.assertRaises(ValueError):
            self.owner(request, self.observation()).run(self.scope, 'bind-worktree', request)
        self.assertEqual(database.read_bytes(), before)


class DeliveryOwnerPinTests(unittest.TestCase):
    def test_coordinator_code_changes_invalidate_runtime_pin(self):
        import shutil
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            for source in [*state._runtime_sources(), state.PACKAGE / 'scripts/delivery_coordinator.py']:
                target = package / source.relative_to(state.PACKAGE)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            with patch.object(state, 'PACKAGE', package):
                before = state.runtime_fingerprint()
                with (package / 'scripts/delivery_coordinator.py').open('a') as stream:
                    stream.write('\n# changed owner implementation\n')
                self.assertNotEqual(before, state.runtime_fingerprint())
