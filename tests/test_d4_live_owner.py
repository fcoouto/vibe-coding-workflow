"""Prove live editable owners block D4 before any publication or effects."""

import unittest

from pathlib import Path

from runtime.startup import PROJECT_FILE
from tests import test_changes


class D4LiveOwnerTests(unittest.TestCase):
    def test_live_editable_task_blocks_host_issued_apply_before_publication(self):
        from runtime import evidence, state

        scenario = test_changes.ScopedChangesTests(methodName="runTest")
        scenario.setUp()
        self.addCleanup(scenario.doCleanups)
        request, contexts = scenario.d4_bookkeeping_request()
        context = contexts[0]
        scope = scenario.d4_bookkeeping_scopes[0]
        project_file = scenario.repo / PROJECT_FILE
        self.assertFalse(project_file.exists())

        effects_before = [
            (action, effect, scenario.changes._fingerprint(
                Path(action["owner"]["root"]), effect["path"]
            ))
            for action in request["manifest"]["actions"]
            for effect in action["effects"]
        ]
        baseline_before, sources_before = scenario.changes._recovery_sources(context)
        self.assertEqual(sources_before, [])

        identity = dict(client="codex", session_id="live-session", task_id="live-task",
                        scope_ref="fixture:live-owner")
        live = state.start_task(scope, identity | dict(
            mode="editable", decision_ref="fixture:live-editable"
        ))["task"]
        self.assertEqual(live["mode"], "editable")
        self.assertNotIn("retirement", live)

        issued = []

        class Host:
            def acquire_d4_bookkeeping(owner, facts, issue):
                grant = issue(facts)
                issued.append(grant)
                return grant

        markers = scenario.changes._authority_locations([context.directory])
        owners_before = [scenario.changes._authority_owner(marker) for marker in markers]
        with scenario.changes._bootstrap_d4_host(
            Host(), issuer=scenario.changes._D4_HOST_BOOTSTRAP_ISSUER
        ) as host:
            result = scenario.changes._run_scoped(
                scenario.directory, request, "apply", host=host
            )

        self.assertEqual(result["exit_code"], 2, result)
        self.assertEqual(
            [row["reason"] for row in result["blocked"]],
            ["Affected editable task lacks exact stopped-writer retirement proof"],
        )
        self.assertEqual(issued, [])
        self.assertFalse(project_file.exists())
        for action, effect, before in effects_before:
            self.assertEqual(
                scenario.changes._fingerprint(Path(action["owner"]["root"]), effect["path"]),
                before,
            )
        live_after = state.task_status(scope, "codex", identity["session_id"])["task"]
        self.assertEqual(live_after, live)
        self.assertEqual(live_after["pins"], live["pins"])
        self.assertNotIn("retirement", live_after)
        self.assertEqual(
            [scenario.changes._authority_owner(marker) for marker in markers], owners_before
        )
        baseline_after, sources_after = scenario.changes._recovery_sources(context)
        self.assertEqual(evidence._canonical_plain(baseline_after),
                         evidence._canonical_plain(baseline_before))
        self.assertEqual(sources_after, [])
