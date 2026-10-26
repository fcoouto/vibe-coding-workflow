"""Bounded persisted-history receipts never trust caller claims or execute review."""

from contextlib import contextmanager
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from runtime import doctor
from runtime.adapters import codex
from runtime.startup import ProjectScope, StartupError


class NativeReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.scope = ProjectScope("fixture", self.root, self.root / ".git", "policy")
        self.binding = dict(parent_session_id="parent", assignment="VCW review attempt attempt digest " + "a" * 64,
                            assignment_digest="a" * 64, candidate_digest="b" * 64,
                            requested_coverage=["general"], task_name="review_attempt")
        self.report = dict(version=1, attempt_id="attempt", assignment_digest="a" * 64,
                           candidate_digest="b" * 64, coverage=["general"], findings=[], limitations=[])
        self.text = json.dumps(self.report)
        self.responses = {
            "parent": dict(thread=dict(id="parent", cwd=str(self.root), cliVersion="0.163.0")),
            "spawn": dict(data=[dict(turnId="parent-turn", item=dict(
                id="spawn", type="subAgentActivity", kind="started", agentThreadId="child",
                agentPath="/root/review_attempt", model="gpt-6-luna", reasoningEffort="medium"))]),
            "child": dict(thread=dict(id="child", parentThreadId="parent", cwd=str(self.root),
                                       cliVersion="0.163.0", source={"subAgent": {"thread_spawn": {
                                           "parent_thread_id": "parent", "agent_path": "/root/review_attempt"}}})),
            "turns": dict(data=[dict(id="child-turn", status="completed", error=None)], nextCursor=None),
            "items": dict(data=[dict(turnId="child-turn", item=dict(id="final", type="agentMessage",
                                        phase="final_answer", text=self.text))], nextCursor=None),
        }
        self.log = self.root / "rpc.jsonl"

    def executable(self, responses=None, mode="normal", version="0.163.0"):
        path = self.root / "native"
        path.write_text(f'''#!{sys.executable}
import json, os, sys, time
if sys.argv[1:] == ["--version"]:
    print("codex-cli {version}")
    raise SystemExit
responses = {responses or self.responses!r}
mode = {mode!r}
turn_reads = 0
for line in sys.stdin:
    request = json.loads(line)
    with open({str(self.log)!r}, "a") as log:
        log.write(json.dumps(request) + "\\n")
    if "id" not in request:
        continue
    method = request["method"]
    params = request["params"]
    if mode == "slow":
        time.sleep(30)
    if method == "initialize": result = {{}}
    elif method == "thread/read": result = responses[params["threadId"]]
    elif method == "thread/items/read": result = responses["spawn"]
    elif method == "model/list": result = responses.get("catalog_second", responses["catalog"]) if params.get("cursor") else responses["catalog"]
    elif method == "thread/turns/list":
        turn_reads += 1
        result = responses.get("turns_second", responses["turns"]) if turn_reads > 1 else responses["turns"]
    elif method == "thread/items/list":
        result = responses.get("items_second", responses["items"]) if params.get("cursor") else responses["items"]
    else: raise RuntimeError("Unexpected RPC")
    if mode == "oversized": result = {{"data": "x" * (600 * 1024)}}
    print(json.dumps({{"id": request["id"], "result": result}}), flush=True)
''')
        path.chmod(0o700)
        return str(path)

    @contextmanager
    def prepared(self, binding=None, failure=False):
        module = types.ModuleType("runtime.evidence")
        calls = []
        def prepared_native_review(scope, attempt_id):
            calls.append((scope, attempt_id))
            if failure:
                raise StartupError("candidate changed")
            return copy.deepcopy(binding or self.binding)
        module.prepared_native_review = prepared_native_review
        with patch.dict(sys.modules, {"runtime.evidence": module}):
            yield calls

    def collect(self, responses=None, mode="normal", version="0.163.0", binding=None):
        with self.prepared(binding) as calls, patch.object(codex.shutil, "which", return_value=self.executable(responses, mode, version)):
            result = codex.collect_native_review(self.scope, "attempt", "parent-turn", "spawn")
        self.assertEqual(len(calls), 2)
        return result

    def test_receipt_fetches_actual_report_and_only_read_only_methods(self):
        for version in ("0.163.0", "0.164.0-alpha.11.1"):
            with self.subTest(version=version):
                responses = copy.deepcopy(self.responses)
                for identity in ("parent", "child"):
                    responses[identity]["thread"]["cliVersion"] = version
                observed = self.collect(responses, version=version)
                self.assertEqual(observed["report"], self.report)
                receipt = observed["receipt"]
                self.assertEqual(receipt["reviewer_id"], "child")
                self.assertEqual(receipt["report_digest"], hashlib.sha256(self.text.encode()).hexdigest())
                self.assertEqual(receipt["mechanism"], "codex-native-agent-path")
                self.assertEqual(receipt["native_version"], version)
                self.assertEqual(self.collect(responses, version=version), observed)
        methods = [json.loads(line)["method"] for line in self.log.read_text().splitlines()]
        self.assertEqual(set(methods), {"initialize", "initialized", "thread/read", "thread/items/read",
                                       "thread/turns/list", "thread/items/list"})

    def test_thread_versions_must_match_selected_executable(self):
        for version, other in (("0.163.0", "0.164.0-alpha.11.1"),
                               ("0.164.0-alpha.11.1", "0.163.0")):
            for identity in ("parent", "child"):
                responses = copy.deepcopy(self.responses)
                for matched in ("parent", "child"):
                    responses[matched]["thread"]["cliVersion"] = version
                responses[identity]["thread"]["cliVersion"] = other
                with self.subTest(version=version, identity=identity), self.assertRaises(StartupError):
                    self.collect(responses, version=version)

    def test_invalid_native_chains_fail_closed(self):
        cases = []
        def changed(label, mutate):
            responses = copy.deepcopy(self.responses)
            mutate(responses)
            cases.append((label, responses))
        changed("other turn", lambda r: r["spawn"]["data"][0].update(turnId="other"))
        changed("other item", lambda r: r["spawn"]["data"][0]["item"].update(id="other"))
        changed("missing native marker", lambda r: r["spawn"]["data"][0]["item"].pop("agentPath"))
        changed("changed native marker", lambda r: r["spawn"]["data"][0]["item"].update(agentPath="/root/review_other"))
        changed("unobservable spawn", lambda r: r["spawn"]["data"][0]["item"].update(type="collabAgentToolCall"))
        changed("self review", lambda r: r["spawn"]["data"][0]["item"].update(agentThreadId="parent"))
        changed("incomplete spawn", lambda r: r["spawn"]["data"][0]["item"].update(kind="completed"))
        changed("other child", lambda r: r["child"]["thread"].update(id="other"))
        changed("other child parent", lambda r: r["child"]["thread"].update(parentThreadId="other"))
        changed("missing native origin", lambda r: r["child"]["thread"].pop("source"))
        changed("other native origin", lambda r: r["child"]["thread"]["source"]["subAgent"]["thread_spawn"].update(parent_thread_id="other"))
        changed("other native path", lambda r: r["child"]["thread"]["source"]["subAgent"]["thread_spawn"].update(agent_path="/root/review_other"))
        changed("other checkout", lambda r: r["child"]["thread"].update(cwd="/other"))
        changed("incomplete turn", lambda r: r["turns"]["data"][0].update(status="inProgress"))
        changed("missing phase", lambda r: r["items"]["data"][0]["item"].pop("phase"))
        changed("other final turn", lambda r: r["items"]["data"][0].update(turnId="other"))
        changed("changed report", lambda r: r["items"]["data"][0]["item"].update(text=self.text.replace("b" * 64, "c" * 64)))
        changed("duplicate final", lambda r: r["items"]["data"].append(copy.deepcopy(r["items"]["data"][0])))
        changed("endless page", lambda r: r["items"].update(nextCursor="repeated"))
        for label, responses in cases:
            with self.subTest(label=label), self.assertRaises(StartupError):
                self.collect(responses)

    def test_malformed_envelopes_and_unknown_versions_are_not_provenance(self):
        for text in ("not JSON", '{"version":1,"version":1}', "{}", self.text.replace('"findings": []', '"findings": true')):
            responses = copy.deepcopy(self.responses)
            responses["items"]["data"][0]["item"]["text"] = text
            with self.subTest(text=text), self.assertRaises(StartupError):
                self.collect(responses)
        with self.assertRaises(StartupError):
            self.collect(version="9.999.0")

    def test_candidate_rechecked_after_fetch_and_errors_are_sanitized(self):
        module = types.ModuleType("runtime.evidence")
        module.prepared_native_review = unittest.mock.Mock(side_effect=[self.binding, StartupError("candidate changed")])
        with patch.dict(sys.modules, {"runtime.evidence": module}), patch.object(codex.shutil, "which", return_value=self.executable()):
            with self.assertRaises(StartupError):
                codex.collect_native_review(self.scope, "attempt", "parent-turn", "spawn")
        with self.assertRaisesRegex(StartupError, "Native review observation unavailable"):
            self.collect(mode="oversized")

    def test_pagination_is_bounded_and_latest_turn_is_rechecked(self):
        responses = copy.deepcopy(self.responses)
        responses["items_second"] = responses["items"]
        responses["items"] = dict(data=[], nextCursor="next-page")
        self.assertEqual(self.collect(responses)["report"], self.report)
        responses["turns_second"] = dict(data=[dict(id="later-turn", status="completed", error=None)])
        with self.assertRaises(StartupError):
            self.collect(responses)
        with patch.object(doctor, "RPC_TIMEOUT", 0.05), self.assertRaisesRegex(StartupError, "Native review observation unavailable"):
            self.collect(mode="slow")

    def test_invalid_identifiers_do_not_launch_native_process(self):
        with self.prepared(), patch.object(codex, "NativeProcess") as process:
            for value in (None, "", "x" * 257, "line\nbreak"):
                with self.subTest(value=value), self.assertRaises(StartupError):
                    codex.collect_native_review(self.scope, "attempt", value, "spawn")
            process.assert_not_called()


    def worker_fixture(self):
        responses = copy.deepcopy(self.responses)
        responses["parent"]["thread"].update(originator="codex_exec", source="exec")
        responses["child"]["thread"].update(model="configured-model", reasoningEffort="high")
        responses["spawn"]["data"][0]["item"]["agentPath"] = "/root/worker_attempt"
        responses["child"]["thread"]["source"]["subAgent"]["thread_spawn"]["agent_path"] = "/root/worker_attempt"
        binding = dict(attempt_id="attempt", parent_session_id="parent", task_name="worker_attempt",
                       assignment_digest="a" * 64, candidate_digest="b" * 64,
                       requested_model="requested-model", requested_effort="low",
                       client_surface="codex-cli", native_version="0.163.0")
        return responses, binding

    @contextmanager
    def prepared_worker(self, binding, changed=None):
        module = types.ModuleType("runtime.delegation")
        module.prepared_native_assignment = unittest.mock.Mock(
            side_effect=[copy.deepcopy(binding), copy.deepcopy(changed or binding)])
        with patch.dict(sys.modules, {"runtime.delegation": module}):
            yield

    def observe_worker(self, responses=None, binding=None, changed=None, mode="normal", version="0.163.0"):
        defaults, prepared = self.worker_fixture()
        executable = self.executable(responses or defaults, mode, version)
        with self.prepared_worker(binding or prepared, changed), patch.object(codex.shutil, "which", return_value=executable):
            return codex.observe_native_worker(self.scope, "attempt", "parent-turn", "spawn")

    def review_assignment_fixture(self):
        responses, binding = self.worker_fixture()
        binding.update(task_name="review_attempt", assignment_digest="d" * 64)
        responses["spawn"]["data"][0]["item"]["agentPath"] = "/root/review_attempt"
        responses["child"]["thread"]["source"]["subAgent"]["thread_spawn"]["agent_path"] = "/root/review_attempt"
        return responses, binding

    @contextmanager
    def prepared_review_assignment(self, binding, changed=None):
        module = types.ModuleType("runtime.delegation")
        module.prepared_native_review_assignment = unittest.mock.Mock(
            side_effect=[copy.deepcopy(binding), copy.deepcopy(changed or binding)])
        with patch.dict(sys.modules, {"runtime.delegation": module}):
            yield

    def observe_review_assignment(self, responses=None, binding=None, changed=None):
        defaults, prepared = self.review_assignment_fixture()
        executable = self.executable(responses or defaults)
        with self.prepared_review_assignment(binding or prepared, changed), patch.object(codex.shutil, "which", return_value=executable):
            return codex.observe_native_review_assignment(self.scope, attempt_id="attempt", parent_turn_id="parent-turn", spawn_item_id="spawn")

    def test_review_assignment_observation_preserves_unknown_and_incomplete_lifecycle(self):
        self.assertTrue(callable(getattr(codex, "observe_native_review_assignment", None)), "Review assignment lifecycle observation is unavailable")
        for status in (None, "inProgress", "interrupted", "failed"):
            responses, binding = self.review_assignment_fixture()
            if status is None:
                responses["turns"]["data"] = []
            else:
                responses["turns"]["data"][0]["status"] = status
            observed = self.observe_review_assignment(responses, binding)
            receipt = observed["receipt"]
            self.assertEqual(receipt["version"], 2)
            self.assertEqual(receipt["task_name"], "review_attempt")
            self.assertEqual(receipt["assignment_digest"], "d" * 64)
            self.assertEqual(receipt["turn_status"], status or "unknown")
            self.assertEqual(receipt["worker_turn_id"], "child-turn" if status else None)
            self.assertIsNone(receipt["result_item_id"])
            self.assertIsNone(receipt["result_digest"])
            self.assertIsNone(observed["result"])
            self.assertFalse(receipt["descendants_stopped"])
            self.assertEqual(receipt["prompt_delivery"], "unverified")
        methods = {json.loads(line)["method"] for line in self.log.read_text().splitlines()}
        self.assertLessEqual(methods, {"initialize", "initialized", "thread/read", "thread/items/read", "thread/turns/list"})

    def test_completed_review_assignment_returns_raw_result_and_d6_binding_without_d5_acceptance(self):
        self.assertTrue(callable(getattr(codex, "observe_native_review_assignment", None)), "Review assignment lifecycle observation is unavailable")
        responses, binding = self.review_assignment_fixture()
        responses["parent"]["thread"]["modelProvider"] = "parent-provider"
        responses["child"]["thread"]["modelProvider"] = "review-provider"
        for text in (self.text, "plain review output without a D5 report envelope"):
            responses["items"]["data"][0]["item"]["text"] = text
            observed = self.observe_review_assignment(responses, binding)
            receipt = observed["receipt"]
            self.assertEqual(observed["result"], text)
            self.assertEqual(receipt["result_digest"], hashlib.sha256(text.encode()).hexdigest())
            self.assertEqual(receipt["assignment_digest"], "d" * 64)
            self.assertEqual(receipt["candidate_digest"], "b" * 64)
            self.assertEqual(receipt["worker_id"], "child")
            self.assertEqual(receipt["worker_turn_id"], "child-turn")
            self.assertEqual(receipt["result_item_id"], "final")
            self.assertEqual(receipt["agent_path"], "/root/review_attempt")
            self.assertEqual(receipt["parent_model_provider"], "parent-provider")
            self.assertEqual(receipt["worker_model_provider"], "review-provider")
            self.assertEqual(receipt["requested_model"], "requested-model")
            self.assertEqual(receipt["configured_model"], "configured-model")
            self.assertEqual(receipt["spawn_observed_model"], "gpt-6-luna")
            self.assertIsNone(receipt["execution_model"])
            self.assertEqual(self.observe_review_assignment(responses, binding), observed)

    def test_review_assignment_rejects_wrong_marker_binding_and_child(self):
        self.assertTrue(callable(getattr(codex, "observe_native_review_assignment", None)), "Review assignment lifecycle observation is unavailable")
        for label in ("worker marker", "wrong native marker", "wrong binding", "changed binding", "wrong child", "changed turn", "oversized result"):
            responses, binding = self.review_assignment_fixture()
            changed = None
            if label == "worker marker": binding["task_name"] = "worker_attempt"
            elif label == "wrong native marker": responses["spawn"]["data"][0]["item"]["agentPath"] = "/root/worker_attempt"
            elif label == "wrong binding": binding["attempt_id"] = "other"
            elif label == "changed binding": changed = dict(binding, candidate_digest="c" * 64)
            elif label == "wrong child": responses["child"]["thread"]["parentThreadId"] = "other"
            elif label == "changed turn": responses["turns_second"] = dict(data=[dict(id="other", status="completed", error=None)])
            else: responses["items"]["data"][0]["item"]["text"] = "x" * (64 * 1024 + 1)
            with self.subTest(label=label), self.assertRaises(StartupError):
                self.observe_review_assignment(responses, binding, changed)
        responses, binding = self.review_assignment_fixture()
        with self.assertRaises(StartupError):
            self.observe_worker(responses, binding)

    def test_worker_observation_separates_settings_and_never_proves_stopped_writers(self):
        self.assertTrue(callable(getattr(codex, "observe_native_worker", None)), "Worker observation is unavailable")
        observed = self.observe_worker()
        receipt = observed["receipt"]
        self.assertEqual(receipt["version"], 2)
        self.assertEqual(receipt["worker_id"], "child")
        self.assertEqual(receipt["task_name"], "worker_attempt")
        self.assertEqual(receipt["requested_model"], "requested-model")
        self.assertEqual(receipt["requested_effort"], "low")
        self.assertEqual(receipt["configured_model"], "configured-model")
        self.assertEqual(receipt["configured_effort"], "high")
        self.assertEqual(receipt["spawn_observed_model"], "gpt-6-luna")
        self.assertEqual(receipt["spawn_observed_effort"], "medium")
        self.assertIsNone(receipt["execution_model"])
        self.assertIsNone(receipt["execution_effort"])
        self.assertFalse(receipt["descendants_stopped"])
        self.assertEqual(receipt["prompt_delivery"], "unverified")
        self.assertEqual(observed["result"], self.text)
        self.assertEqual(self.observe_worker(), observed)
        methods = {json.loads(line)["method"] for line in self.log.read_text().splitlines()}
        self.assertLessEqual(methods, codex.REVIEW_METHODS | {"initialized"})

    def test_worker_unknown_settings_and_incomplete_lifecycle_remain_unknown(self):
        responses, binding = self.worker_fixture()
        responses["child"]["thread"].pop("model")
        responses["child"]["thread"].pop("reasoningEffort")
        responses["spawn"]["data"][0]["item"].pop("model")
        responses["spawn"]["data"][0]["item"].pop("reasoningEffort")
        for status in ("inProgress", "interrupted", "failed"):
            responses["turns"]["data"][0]["status"] = status
            observed = self.observe_worker(responses, binding)
            self.assertEqual(observed["receipt"]["turn_status"], status)
            self.assertIsNone(observed["result"])
            for field in ("configured_model", "configured_effort", "spawn_observed_model", "spawn_observed_effort"):
                self.assertIsNone(observed["receipt"][field])
        responses["turns"]["data"] = []
        observed = self.observe_worker(responses, binding)
        self.assertEqual(observed["receipt"]["turn_status"], "unknown")
        self.assertIsNone(observed["receipt"]["worker_turn_id"])
        self.assertIsNone(observed["result"])

    def test_worker_observation_accepts_observed_desktop_surface_tuple(self):
        responses, binding = self.worker_fixture()
        binding.update(client_surface="codex-desktop", native_version="0.164.0-alpha.11.1")
        for identity in ("parent", "child"):
            responses[identity]["thread"]["cliVersion"] = "0.164.0-alpha.11.1"
        responses["parent"]["thread"].update(originator="Codex Desktop", source="vscode")
        try:
            observed = self.observe_worker(responses, binding, version="0.164.0-alpha.11.1")
        except StartupError as error:
            self.fail("Observed Desktop worker surface was rejected: " + str(error))
        self.assertEqual(observed["receipt"]["client_surface"], "codex-desktop")
        self.assertEqual(observed["receipt"]["originator"], "Codex Desktop")
        for source in ("appServer", "cli", "exec", "unknown"):
            responses["parent"]["thread"]["source"] = source
            with self.subTest(source=source), self.assertRaises(StartupError):
                self.observe_worker(responses, binding, version="0.164.0-alpha.11.1")
        responses["parent"]["thread"].update(source="vscode", originator="unknown")
        with self.assertRaises(StartupError):
            self.observe_worker(responses, binding, version="0.164.0-alpha.11.1")

    def test_worker_rejects_unbound_identity_surface_and_changed_assignment(self):
        responses, binding = self.worker_fixture()
        cases = []
        for field, value in (("task_name", "worker_other"), ("attempt_id", "other"),
                             ("native_version", "other"), ("client_surface", "codex-desktop"),
                             ("assignment_digest", "bad"), ("candidate_digest", "bad")):
            other = dict(binding, **{field: value})
            cases.append((responses, other, None))
        for field, value in (("originator", "Codex Desktop"), ("cwd", "/other")):
            other = copy.deepcopy(responses)
            other["parent"]["thread"][field] = value
            cases.append((other, binding, None))
        changed = dict(binding, candidate_digest="c" * 64)
        cases.append((responses, binding, changed))
        for observed, prepared, changed in cases:
            with self.subTest(binding=prepared, changed=changed), self.assertRaises(StartupError):
                self.observe_worker(observed, prepared, changed)

    def test_worker_bounds_results_history_and_turn_changes(self):
        for label in ("too large", "duplicate final", "changed turn", "endless page", "wrong child"):
            responses, binding = self.worker_fixture()
            if label == "too large":
                responses["items"]["data"][0]["item"]["text"] = "x" * (64 * 1024 + 1)
            elif label == "duplicate final":
                responses["items"]["data"].append(copy.deepcopy(responses["items"]["data"][0]))
            elif label == "changed turn":
                responses["turns_second"] = dict(data=[dict(id="other", status="completed", error=None)])
            elif label == "endless page":
                responses["items"]["nextCursor"] = "repeat"
            else:
                responses["child"]["thread"]["parentThreadId"] = "other"
            with self.subTest(label=label), self.assertRaises(StartupError):
                self.observe_worker(responses, binding)
        with patch.object(doctor, "RPC_TIMEOUT", 0.05), self.assertRaises(StartupError):
            self.observe_worker(mode="slow")

    def control_fixture(self):
        responses, _ = self.worker_fixture()
        responses["catalog"] = dict(data=[dict(model="new-native-model", defaultReasoningEffort="low",
            supportedReasoningEfforts=[dict(reasoningEffort="low"), dict(reasoningEffort="high")])], nextCursor=None)
        controls = dict(version=1, client_surface="codex-cli", native_version="0.163.0", parent_session_id="parent",
                        dispatch_controls=dict(spawn=True, explicit_model=True, explicit_effort=True, fork_turns_none=True))
        return responses, controls

    def discover_workers(self, responses=None, controls=None, version="0.163.0"):
        defaults, control = self.control_fixture()
        executable = self.executable(responses or defaults, version=version)
        with patch.object(codex.shutil, "which", return_value=executable):
            return codex.discover_native_workers(self.scope, controls or control)

    def test_discovery_binds_catalog_controls_surface_and_version_without_dispatch(self):
        self.assertTrue(callable(getattr(codex, "discover_native_workers", None)), "Worker discovery is unavailable")
        observed = self.discover_workers()
        self.assertEqual(observed["catalog"], [dict(model="new-native-model", supported_efforts=["low", "high"], default_effort="low")])
        self.assertEqual(observed["client_surface"], "codex-cli")
        self.assertEqual(observed["native_version"], "0.163.0")
        self.assertEqual(len(observed["capability_digest"]), 64)
        self.assertEqual(self.discover_workers(), observed)
        responses, controls = self.control_fixture()
        controls["dispatch_controls"]["explicit_effort"] = False
        self.assertNotEqual(self.discover_workers(responses, controls)["capability_digest"], observed["capability_digest"])
        methods = {json.loads(line)["method"] for line in self.log.read_text().splitlines()}
        self.assertEqual(methods, {"initialize", "initialized", "thread/read", "model/list"})

    def test_discovery_rejects_unqualified_surface_and_malformed_or_unbounded_catalog(self):
        for label in ("desktop", "version", "originator", "control type", "duplicate", "effort", "page loop"):
            responses, controls = self.control_fixture()
            if label == "desktop": controls["client_surface"] = "codex-desktop"
            elif label == "version": controls["native_version"] = "other"
            elif label == "originator": responses["parent"]["thread"]["originator"] = "Codex Desktop"
            elif label == "control type": controls["dispatch_controls"]["spawn"] = "true"
            elif label == "duplicate": responses["catalog"]["data"] *= 2
            elif label == "effort": responses["catalog"]["data"][0]["defaultReasoningEffort"] = "unsupported"
            else: responses["catalog"]["nextCursor"] = "repeat"
            with self.subTest(label=label), self.assertRaises(StartupError):
                self.discover_workers(responses, controls)
        responses, controls = self.control_fixture()
        responses["catalog_second"] = responses["catalog"]
        responses["catalog"] = dict(data=[], nextCursor="next-page")
        self.assertEqual(len(self.discover_workers(responses, controls)["catalog"]), 1)

    def test_desktop_catalog_requires_matching_observer_and_exact_surface_binding(self):
        responses, controls = self.control_fixture()
        controls.update(client_surface="codex-desktop", native_version="0.164.0-alpha.11.1")
        responses["parent"]["thread"].update(cliVersion="0.164.0-alpha.11.1", source="vscode", originator="Codex Desktop")
        executable = self.executable(responses, version="0.164.0-alpha.11.1")
        with patch.object(codex.shutil, "which", return_value=executable):
            try:
                observed = codex.discover_native_workers(self.scope, controls)
            except StartupError as error:
                self.fail("Observed Desktop catalog was rejected: " + str(error))
        self.assertEqual(observed["client_surface"], "codex-desktop")
        self.assertEqual(observed["native_version"], "0.164.0-alpha.11.1")
        self.assertEqual(observed["originator"], "Codex Desktop")
        self.assertEqual(observed["catalog"], [dict(model="new-native-model", supported_efforts=["low", "high"], default_effort="low")])
        for source in ("appServer", "cli", "exec", "unknown"):
            responses["parent"]["thread"]["source"] = source
            with self.subTest(source=source), self.assertRaises(StartupError):
                self.discover_workers(responses, controls, version="0.164.0-alpha.11.1")
        responses["parent"]["thread"]["source"] = "vscode"
        for version in ("0.163.0", "9.999.0"):
            with self.subTest(version=version), self.assertRaises(StartupError):
                self.discover_workers(responses, controls, version=version)
        controls["client_surface"] = "codex-cli"
        with self.assertRaises(StartupError):
            self.discover_workers(responses, controls, version="0.164.0-alpha.11.1")
        controls.update(client_surface="codex-desktop", native_version="0.163.0")
        responses["parent"]["thread"]["cliVersion"] = "0.163.0"
        with self.assertRaises(StartupError):
            self.discover_workers(responses, controls, version="0.163.0")

    def test_cli_surface_requires_exact_observed_standalone_exec_tuple(self):
        responses, controls = self.control_fixture()
        responses["parent"]["thread"].update(cliVersion="0.163.0", source="exec", originator="codex_exec", modelProvider="openai")
        try:
            observed = self.discover_workers(responses, controls)
        except StartupError as error:
            self.fail("Observed standalone CLI exec surface was rejected: " + str(error))
        self.assertEqual(observed["native_version"], "0.163.0")
        self.assertEqual(observed["originator"], "codex_exec")
        self.assertEqual(observed["parent_model_provider"], "openai")
        for source in ("cli", "vscode", "appServer", "unknown"):
            responses["parent"]["thread"]["source"] = source
            with self.subTest(source=source), self.assertRaises(StartupError):
                self.discover_workers(responses, controls)
        responses["parent"]["thread"]["source"] = "exec"
        for originator in ("codex_cli_rs", "Codex Desktop", "other", None):
            responses["parent"]["thread"]["originator"] = originator
            with self.subTest(originator=originator), self.assertRaises(StartupError):
                self.discover_workers(responses, controls)
        responses["parent"]["thread"]["originator"] = "codex_exec"
        for version in ("0.164.0-alpha.11.1", "9.999.0"):
            controls["native_version"] = version
            responses["parent"]["thread"]["cliVersion"] = version
            with self.subTest(version=version), self.assertRaises(StartupError):
                self.discover_workers(responses, controls, version=version)

    def test_provider_metadata_preserves_unknown_and_differing_native_values(self):
        discovered = self.discover_workers()
        self.assertIn("parent_model_provider", discovered)
        self.assertIsNone(discovered["parent_model_provider"])
        receipt = self.observe_worker()["receipt"]
        self.assertIn("parent_model_provider", receipt)
        self.assertIn("worker_model_provider", receipt)
        self.assertIsNone(receipt["parent_model_provider"])
        self.assertIsNone(receipt["worker_model_provider"])
        responses, controls = self.control_fixture()
        responses["parent"]["thread"]["modelProvider"] = "parent-provider"
        changed = self.discover_workers(responses, controls)
        self.assertEqual(changed["parent_model_provider"], "parent-provider")
        self.assertNotEqual(changed["capability_digest"], discovered["capability_digest"])
        responses, binding = self.worker_fixture()
        responses["parent"]["thread"]["modelProvider"] = "parent-provider"
        responses["child"]["thread"]["modelProvider"] = "worker-provider"
        receipt = self.observe_worker(responses, binding)["receipt"]
        self.assertEqual(receipt["parent_model_provider"], "parent-provider")
        self.assertEqual(receipt["worker_model_provider"], "worker-provider")
        responses["parent"]["thread"]["modelProvider"] = None
        responses["child"]["thread"]["modelProvider"] = None
        receipt = self.observe_worker(responses, binding)["receipt"]
        self.assertIsNone(receipt["parent_model_provider"])
        self.assertIsNone(receipt["worker_model_provider"])

    def test_present_provider_metadata_requires_bounded_printable_strings(self):
        for value in ("", "x" * 257, "provider\nname", True, {}):
            responses, controls = self.control_fixture()
            responses["parent"]["thread"]["modelProvider"] = value
            with self.subTest(value=value, source="catalog"), self.assertRaises(StartupError):
                self.discover_workers(responses, controls)
            for identity in ("parent", "child"):
                responses, binding = self.worker_fixture()
                responses[identity]["thread"]["modelProvider"] = value
                with self.subTest(value=value, source=identity), self.assertRaises(StartupError):
                    self.observe_worker(responses, binding)


if __name__ == "__main__":
    unittest.main()
