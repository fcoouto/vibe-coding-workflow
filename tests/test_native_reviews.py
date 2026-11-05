"""Bounded persisted-history receipts never trust caller claims or execute review."""

from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time
import types
import unittest
from unittest.mock import patch

from runtime import doctor, evidence
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
            "parent": dict(thread=dict(id="parent", cwd=str(self.root), cliVersion="0.163.0",
                                       source="exec", originator="codex_exec")),
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
    if method == "initialize": result = responses.get("initialize", {{"codexHome": "/private/native", "platformFamily": "unix", "platformOs": "macos", "userAgent": "fixture"}})
    elif method == "thread/read": result = responses[params["threadId"]]
    elif method == "thread/items/read": result = responses["spawn"]
    elif method == "model/list": result = responses.get("catalog_second", responses["catalog"]) if params.get("cursor") else responses["catalog"]
    elif method == "thread/turns/list":
        turn_reads += 1
        if mode == "changed-rollout" and turn_reads == 2:
            with open(responses["child"]["thread"]["path"], "ab") as source:
                source.write(b"\\n")
        result = responses.get("turns_second", responses["turns"]) if turn_reads > 1 else responses["turns"]
    elif method == "thread/items/list":
        if "history" in responses:
            start = int(params.get("cursor", "0"))
            stop = start + params["limit"]
            result = {{"data": responses["history"][start:stop], "nextCursor": str(stop) if stop < len(responses["history"]) else None}}
        else:
            result = responses.get("items_second", responses["items"]) if params.get("cursor") else responses["items"]
    else: raise RuntimeError("Unexpected RPC")
    if mode == "oversized": result = {{"data": "x" * (600 * 1024)}}
    if mode == "oversized-notification" and method == "thread/items/read":
        print(json.dumps({{"method": "fixture/notification", "params": {{"data": "x" * (128 * 1024)}}}}), flush=True)
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
        module._digest = evidence._digest
        with patch.dict(sys.modules, {"runtime.evidence": module}):
            yield calls

    def collect(self, responses=None, mode="normal", version="0.163.0", binding=None):
        with self.prepared(binding) as calls, patch.object(codex.shutil, "which", return_value=self.executable(responses, mode, version)):
            result = codex.collect_native_review(self.scope, "attempt", "parent-turn", "spawn")
        self.assertEqual(len(calls), 2)
        return result

    def v1_fixture(self, review=False):
        responses, binding = self.review_assignment_fixture() if review else self.worker_fixture()
        body = dict(binding=dict(task_name=binding["task_name"]), request=dict(assignment="Prepared fixture"),
                    report_contract={}, review=dict(coverage=["general"]))
        digest = evidence._digest(body)
        binding["assignment_digest"] = digest
        envelope = (dict(ledger_assignment_digest=digest, ownership=body, assignment="Prepared fixture",
                         report_contract=dict(attempt_id="attempt", candidate_digest=binding["candidate_digest"],
                                              coverage=["general"])) if review else dict(assignment_digest=digest, assignment=body))
        responses["spawn"]["data"][0]["item"] = dict(id="spawn", type="collabAgentToolCall",
            tool="spawnAgent", status="completed", senderThreadId="parent", receiverThreadIds=["child"],
            prompt=json.dumps(envelope), model="gpt-6-luna", reasoningEffort="medium")
        responses["child"]["thread"]["source"]["subAgent"]["thread_spawn"].pop("agent_path")
        return responses, binding

    def test_v1_collab_call_correlates_prepared_assignment_without_inventing_agent_path(self):
        for review in (False, True):
            responses, binding = self.v1_fixture(review)
            observed = (self.observe_review_assignment(responses, binding) if review else
                        self.observe_worker(responses, binding))
            receipt = observed["receipt"]
            self.assertEqual(receipt["mechanism"], "codex-native-collab-call")
            self.assertIsNone(receipt["agent_path"])
            self.assertEqual((receipt["parent_session_id"], receipt["parent_turn_id"], receipt["spawn_item_id"],
                              receipt["worker_id"], receipt["worker_turn_id"], receipt["result_item_id"]),
                             ("parent", "parent-turn", "spawn", "child", "child-turn", "final"))
            self.assertEqual(receipt["assignment_digest"], binding["assignment_digest"])
            self.assertEqual(receipt["requested_model"], "requested-model")
            self.assertEqual(receipt["configured_model"], "configured-model")
            self.assertEqual(receipt["spawn_observed_model"], "gpt-6-luna")
            self.assertEqual(receipt["native_version"], "0.163.0")
            self.assertEqual(receipt["current_observer_version"], "0.163.0")
            self.assertEqual(observed["result"], self.text)
            self.assertIsNone(receipt["execution_model"])
            self.assertIsNone(receipt["execution_effort"])
            self.assertFalse(receipt["descendants_stopped"])
            self.assertEqual(receipt["prompt_delivery"], "unverified")
        responses, lifecycle_binding = self.v1_fixture(review=True)
        binding = self.binding | dict(ledger_assignment_digest=lifecycle_binding["assignment_digest"])
        receipt = self.collect(responses, binding=binding)["receipt"]
        self.assertEqual(receipt["mechanism"], "codex-native-collab-call")
        self.assertIsNone(receipt["agent_path"])
        self.assertEqual(receipt["assignment_digest"], self.binding["assignment_digest"])
        self.assertNotEqual(receipt["assignment_digest"], binding["ledger_assignment_digest"])
        responses["child"]["thread"]["source"]["subAgent"]["thread_spawn"]["agent_path"] = "/actual/native/path"
        self.assertEqual(self.collect(responses, binding=binding)["receipt"]["agent_path"], "/actual/native/path")
        self.assertEqual(self.collect()["receipt"]["mechanism"], "codex-native-agent-path")

    def test_v1_large_prepared_review_uses_bounded_real_subprocess_transport(self):
        responses, lifecycle_binding = self.v1_fixture(review=True)
        assignment = "x" * 65536
        plaintext_digest = hashlib.sha256(assignment.encode()).hexdigest()
        spawn = responses["spawn"]["data"][0]["item"]
        envelope = json.loads(spawn["prompt"])
        envelope["assignment"] = envelope["ownership"]["request"]["assignment"] = assignment
        ledger_digest = evidence._digest(envelope["ownership"])
        envelope["ledger_assignment_digest"] = ledger_digest
        spawn["prompt"] = json.dumps(envelope)
        report = self.report | dict(assignment_digest=plaintext_digest)
        text = json.dumps(report)
        responses["items"]["data"][0]["item"]["text"] = text
        binding = self.binding | dict(assignment=assignment, assignment_digest=plaintext_digest,
                                      ledger_assignment_digest=ledger_digest)
        initialization = dict(codexHome="/private/native", platformFamily="unix", platformOs="macos", userAgent="fixture")
        results = [initialization, responses["parent"], responses["spawn"], responses["child"],
                   responses["turns"], responses["items"], responses["turns"]]
        frames = [json.dumps(dict(id=number, result=result)).encode() + b"\n"
                  for number, result in enumerate(results, 1)]
        self.assertGreater(len(spawn["prompt"].encode()), doctor.MAX_INPUT)
        self.assertGreater(len(frames[2]), doctor.MAX_INPUT)
        self.assertLess(sum(map(len, frames)), doctor.MAX_OUTPUT)
        self.assertNotEqual(plaintext_digest, ledger_digest)
        collected = self.collect(responses, binding=binding)
        self.assertEqual(collected["report"], report)
        self.assertEqual(collected["receipt"]["assignment_digest"], plaintext_digest)
        self.assertEqual(collected["receipt"]["mechanism"], "codex-native-collab-call")
        self.assertIsNone(collected["receipt"]["agent_path"])
        lifecycle_binding["assignment_digest"] = ledger_digest
        observed = self.observe_review_assignment(responses, lifecycle_binding)
        self.assertEqual(observed["receipt"]["assignment_digest"], ledger_digest)
        self.assertEqual(observed["result"], text)
        self.assertFalse(observed["receipt"]["descendants_stopped"])

    def test_native_selected_response_limit_preserves_default_notification_and_total_bounds(self):
        params = dict(threadId="parent", turnId="parent-turn", itemIds=["spawn"])
        cases = (("default128", 128 * 1024, None, "normal"),
                 ("selected-over512", 512 * 1024, doctor.MAX_OUTPUT, "normal"),
                 ("notification-over128", 1, doctor.MAX_OUTPUT, "oversized-notification"))
        for label, size, limit, mode in cases:
            responses = copy.deepcopy(self.responses)
            responses["spawn"] = dict(data="x" * size)
            notifications = []
            process = doctor.NativeProcess([self.executable(responses, mode)], time.monotonic() + 5,
                                           on_notification=notifications.append)
            try:
                kwargs = {} if limit is None else dict(response_limit=limit)
                with self.subTest(case=label), self.assertRaises(doctor.ObservationError):
                    process.request(1, "thread/items/read", params, **kwargs)
                self.assertEqual(notifications, [])
            finally:
                process.close()
        responses = copy.deepcopy(self.responses)
        responses["spawn"] = dict(data="x" * (270 * 1024))
        frame = json.dumps(dict(id=1, result=responses["spawn"])).encode() + b"\n"
        self.assertLess(len(frame), doctor.MAX_OUTPUT)
        self.assertGreater(2 * len(frame), doctor.MAX_OUTPUT)
        process = doctor.NativeProcess([self.executable(responses)], time.monotonic() + 5)
        try:
            self.assertEqual(process.request(1, "thread/items/read", params, response_limit=doctor.MAX_OUTPUT), responses["spawn"])
            self.assertGreater(process.bytes_read, doctor.MAX_INPUT)
            with self.assertRaisesRegex(doctor.ObservationError, "output_limit"):
                process.request(2, "thread/items/read", params, response_limit=doctor.MAX_OUTPUT)
            self.assertGreater(process.bytes_read, doctor.MAX_OUTPUT)
        finally:
            process.close()
        process = doctor.NativeProcess([self.executable()], time.monotonic() + 5)
        try:
            with self.assertRaises(doctor.ObservationError):
                process.request(1, "thread/items/read", params, response_limit=doctor.MAX_OUTPUT + 1)
        finally:
            process.close()
        responses = copy.deepcopy(self.responses)
        responses["parent"]["padding"] = "x" * (128 * 1024)
        with patch.object(codex.shutil, "which", return_value=self.executable(responses)):
            with codex._native_reader(codex.REVIEW_METHODS) as (_, request):
                with self.assertRaises(doctor.ObservationError):
                    request("thread/read", dict(threadId="parent", includeTurns=False))

    def test_v1_collab_call_mismatch_fails_closed(self):
        for review in (False, True):
            baseline, binding = self.v1_fixture(review)
            cases = []
            def changed(label, mutate):
                responses = copy.deepcopy(baseline)
                mutate(responses)
                cases.append((label, responses))
            changed("parent turn", lambda r: r["spawn"]["data"][0].update(turnId="other"))
            changed("call", lambda r: r["spawn"]["data"][0]["item"].update(id="other"))
            for field, values in (("senderThreadId", (None, "other")), ("tool", (None, "sendInput")),
                                  ("status", ("failed", "inProgress", None)),
                                  ("receiverThreadIds", ([], ["child", "other"], ["parent"], "child", [None])),
                                  ("prompt", (None, "not JSON", "{}", '{"assignment":{},"assignment":{}}'))):
                for value in values:
                    changed(field + repr(value), lambda r, field=field, value=value:
                            r["spawn"]["data"][0]["item"].update({field: value}))
            for field, value in (("id", "other"), ("parentThreadId", "other"), ("cwd", "/other"),
                                  ("source", None)):
                changed("child " + field, lambda r, field=field, value=value: r["child"]["thread"].update({field: value}))
            changed("independent origin", lambda r:
                    r["child"]["thread"]["source"]["subAgent"]["thread_spawn"].update(parent_thread_id="other"))
            changed("caller origin only", lambda r: (r["child"]["thread"].pop("source"),
                    r["spawn"]["data"][0]["item"].update(threadSource={"parent_thread_id": "parent"}, parentTurnId="parent-turn")))
            for value in (False, "", "relative/path", "x" * 4097, "line\nbreak"):
                changed("bad actual path", lambda r, value=value:
                        r["child"]["thread"]["source"]["subAgent"]["thread_spawn"].update(agent_path=value))
            for mutation in ("digest", "body", "name", "extra", "outer"):
                responses = copy.deepcopy(baseline)
                spawn = responses["spawn"]["data"][0]["item"]
                envelope = json.loads(spawn["prompt"])
                body = envelope["ownership" if review else "assignment"]
                if mutation == "digest":
                    envelope["ledger_assignment_digest" if review else "assignment_digest"] = "f" * 64
                elif mutation == "body":
                    body["request"]["assignment"] = "Changed immutable request"
                elif mutation == "name":
                    body["binding"]["task_name"] = "other"
                elif mutation == "extra":
                    envelope["unprepared"] = True
                elif review:
                    envelope["assignment"] = "Changed outer assignment"
                else:
                    envelope["assignment_digest"] = None
                spawn["prompt"] = json.dumps(envelope)
                cases.append((mutation, responses))
            if review:
                responses = copy.deepcopy(baseline)
                spawn = responses["spawn"]["data"][0]["item"]
                envelope = json.loads(spawn["prompt"])
                envelope["report_contract"]["coverage"] = ["other"]
                spawn["prompt"] = json.dumps(envelope)
                cases.append(("altered outer report contract", responses))
            # Even a matching digest cannot replace the generated immutable task name.
            responses = copy.deepcopy(baseline)
            envelope = json.loads(responses["spawn"]["data"][0]["item"]["prompt"])
            body = envelope["ownership" if review else "assignment"]
            body["binding"]["task_name"] = "other"
            digest = evidence._digest(body)
            envelope["ledger_assignment_digest" if review else "assignment_digest"] = digest
            responses["spawn"]["data"][0]["item"]["prompt"] = json.dumps(envelope)
            observer = self.observe_review_assignment if review else self.observe_worker
            with self.subTest(review=review, case="matching digest wrong name"), self.assertRaises(StartupError):
                observer(responses, binding | dict(assignment_digest=digest))
            for label, responses in cases:
                with self.subTest(review=review, case=label), self.assertRaises(StartupError):
                    observer(responses, binding)
        malformed_v2, binding = self.worker_fixture()
        malformed_v2["spawn"]["data"][0]["item"]["type"] = "collabAgentToolCall"
        with self.assertRaises(StartupError):
            self.observe_worker(malformed_v2, binding)

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

    def test_thread_creation_versions_do_not_replace_current_reader_provenance(self):
        for version, other in (("0.163.0", "0.164.0-alpha.11.1"),
                               ("0.164.0-alpha.11.1", "0.163.0")):
            for identity in ("parent", "child"):
                responses = copy.deepcopy(self.responses)
                for matched in ("parent", "child"):
                    responses[matched]["thread"]["cliVersion"] = version
                responses[identity]["thread"]["cliVersion"] = other
                with self.subTest(version=version, identity=identity):
                    receipt = self.collect(responses, version=version)["receipt"]
                    self.assertIn("current_observer_version", receipt)
                    self.assertEqual(receipt["current_observer_version"], version)
                    self.assertEqual(receipt["parent_creation_version"], responses["parent"]["thread"]["cliVersion"])
                    self.assertEqual(receipt["worker_creation_version"], responses["child"]["thread"]["cliVersion"])

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

    def test_malformed_envelopes_are_not_provenance(self):
        for text in ("not JSON", '{"version":1,"version":1}', "{}", self.text.replace('"findings": []', '"findings": true')):
            responses = copy.deepcopy(self.responses)
            responses["items"]["data"][0]["item"]["text"] = text
            with self.subTest(text=text), self.assertRaises(StartupError):
                self.collect(responses)

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

    def test_large_tool_history_does_not_overflow_a_report_collection_frame(self):
        responses = copy.deepcopy(self.responses)
        responses['history'] = [dict(turnId='child-turn', item=dict(id='tool-' + str(i),
            type='commandExecution', aggregatedOutput='x' * 1536)) for i in range(120)]
        responses['history'].extend(responses['items']['data'])
        try:
            observed = self.collect(responses)
        except StartupError:
            self.fail('Bounded collection must retrieve the small report through large tool history')
        self.assertEqual(observed['report'], self.report)

    def test_large_individual_tool_items_preserve_transport_bounds(self):
        responses = copy.deepcopy(self.responses)
        responses['history'] = [dict(turnId='child-turn', item=dict(id='tool-' + str(i),
            type='commandExecution', aggregatedOutput='x' * (20 * 1024))) for i in range(16)]
        responses['history'].extend(responses['items']['data'])
        self.assertEqual(self.collect(responses)['report'], self.report)

    def test_paginated_report_collection_keeps_uniqueness_and_total_item_bound(self):
        for count, duplicate in ((120, True), (400, False)):
            responses = copy.deepcopy(self.responses)
            responses['history'] = [dict(turnId='child-turn', item=dict(id='tool-' + str(i),
                type='commandExecution', aggregatedOutput='ok')) for i in range(count)]
            responses['history'].extend(responses['items']['data'])
            if duplicate:
                responses['history'].insert(0, copy.deepcopy(responses['items']['data'][0]))
            with self.subTest(count=count, duplicate=duplicate), self.assertRaises(StartupError):
                self.collect(responses)

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

    def observe_worker(self, responses=None, binding=None, changed=None, mode="normal", version="0.163.0", **options):
        defaults, prepared = self.worker_fixture()
        executable = self.executable(responses or defaults, mode, version)
        with self.prepared_worker(binding or prepared, changed), patch.object(codex.shutil, "which", return_value=executable), \
                patch.dict(os.environ, {"CODEX_HOME": str(self.root)}):
            return codex.observe_native_worker(self.scope, "attempt", "parent-turn", "spawn", **options)

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

    def observe_review_assignment(self, responses=None, binding=None, changed=None, **options):
        defaults, prepared = self.review_assignment_fixture()
        executable = self.executable(responses or defaults)
        with self.prepared_review_assignment(binding or prepared, changed), patch.object(codex.shutil, "which", return_value=executable), \
                patch.dict(os.environ, {"CODEX_HOME": str(self.root)}):
            return codex.observe_native_review_assignment(self.scope, attempt_id="attempt", parent_turn_id="parent-turn", spawn_item_id="spawn", **options)

    def cooperative_rollout(self, responses, activity, *, terminal=True):
        path = self.root / 'rollout.jsonl'
        responses['child']['thread']['path'] = str(path)
        responses['initialize'] = dict(codexHome=str(self.root), platformFamily='unix', platformOs='macos', userAgent='fixture')
        result = responses['items']['data'][0]['item']['text']
        rows = [('session_meta', dict(id='child')), ('event_msg', dict(type='task_started', turn_id='child-turn'))]
        rows.extend(('event_msg' if item['type'] in {'item_completed', 'thread_settings_applied'} else 'response_item',
                     item) for item in activity)
        if terminal:
            rows.append(('event_msg', dict(type='task_complete', turn_id='child-turn', last_agent_message=result)))
        raw = ''.join(json.dumps(dict(timestamp='fixture', type=kind, payload=payload)) + '\n' for kind, payload in rows).encode()
        path.write_bytes(raw)
        return raw

    def test_guarded_child_lineage_uses_only_the_current_child_rollout(self):
        parent = "01a1a8b7-cf58-7421-8784-50419f70173e"
        child = "01a1a8bb-e785-79d0-b2a1-be3d32d3ce57"
        parent_turn = "01a1a8ba-7c00-7131-b423-b5827ded1768"
        child_turn = "01a1a8bb-e7a7-7720-a018-8fbeb4439e39"
        task_name = "worker_" + "a" * 32
        agent_path = "/root/" + task_name
        home = self.root / "native-home"
        sessions = home / "sessions"
        sessions.mkdir(parents=True, mode=0o700)
        child_path = sessions / f"rollout-{child}.jsonl"
        event = types.SimpleNamespace(client="codex", kind="PreToolUse", tool_name="apply_patch",
            session_id=child, turn_id=child_turn, cwd=self.root, transcript_path=child_path)

        def row(kind, **payload):
            return dict(timestamp="2026-11-04T22:44:09.000Z", type=kind, payload=payload)

        meta = dict(cwd=str(self.root), originator="codex_exec", cli_version="0.165.0")
        child_meta = row("session_meta", id=child, **meta, agent_path=agent_path,
            source=dict(subagent=dict(thread_spawn=dict(parent_thread_id=parent, depth=1, agent_path=agent_path))))
        child_start = row("event_msg", type="task_started", turn_id=child_turn, turn_attribution=dict(
            turn_id=child_turn, turn_trigger="exec", parent_turn_id=parent_turn,
            root_turn_id=parent_turn, initiating_agent_path="/root"))
        context = row("turn_context", turn_id=child_turn, cwd=str(self.root),
                      multi_agent_version="v2", model="gpt-6-luna", effort="high")

        def write(path, rows):
            path.write_text("".join(json.dumps(item) + "\n" for item in rows))
            path.chmod(0o600)

        child_rows = [child_meta, child_start, context]
        write(child_path, child_rows)
        with patch.dict(os.environ, CODEX_HOME=str(home)), patch.object(codex, "_native_reader",
                side_effect=AssertionError("The child hook must not launch another Codex process")):
            observe = lambda: codex.guarded_child_lineage(event, deadline=time.monotonic() + 2)
            self.assertEqual(observe(), dict(parent_session_id=parent, task_name=task_name,
                native_version="0.165.0", model="gpt-6-luna", effort="high"))
            wrong_turn = copy.deepcopy(context)
            wrong_turn["payload"]["turn_id"] = parent_turn
            for name, child_records in (
                ("aborted", child_rows + [row("event_msg", type="turn_aborted")]),
                ("wrong turn", [child_meta, child_start, wrong_turn]),
                ("duplicate metadata", child_rows + [child_meta]),
            ):
                with self.subTest(name=name):
                    write(child_path, child_records)
                    with self.assertRaises(StartupError):
                        observe()
            write(child_path, child_rows)
            alias = sessions / "linked" / child_path.name
            alias.parent.symlink_to(sessions, target_is_directory=True)
            event.transcript_path = alias
            with self.assertRaises(StartupError):
                observe()

    def test_cooperative_observation_accounts_for_the_exact_patch_and_read_only_reviewer(self):
        responses, binding = self.worker_fixture()
        command = '*** Begin Patch\n*** Update File: canary.py\n@@\n-return 0\n+return 42\n*** End Patch'
        raw = self.cooperative_rollout(responses, [dict(type='custom_tool_call', call_id='patch', name='apply_patch', input=command),
            dict(type='custom_tool_call_output', call_id='patch', output='Success')])
        observed = self.observe_worker(responses, binding, cooperative=True)
        self.assertEqual(observed['activity'], dict(source_digest=hashlib.sha256(raw).hexdigest(),
            calls=[dict(id='patch', tool='apply_patch', input_digest=codex.patch_input_fingerprint(command))]))
        self.assertFalse(observed['receipt']['descendants_stopped'])
        self.assertNotIn('activity', self.observe_worker(responses, binding))
        responses, binding = self.review_assignment_fixture()
        self.cooperative_rollout(responses, [])
        self.assertEqual(self.observe_review_assignment(responses, binding, cooperative=True)['activity']['calls'], [])

    def test_cooperative_observation_binds_wrapped_wait_and_patch_to_nested_ids(self):
        responses, binding = self.worker_fixture()
        wait = dict(marker=str(self.root / 'ready'), python=str(Path(sys.executable).resolve()), seconds=5)
        binding['foreground_wait'] = wait
        args = codex.foreground_wait_args(wait, self.scope.repository_root)
        command = '*** Begin Patch\n*** Update File: canary.py\n@@\n-return 0\n+return 42\n*** End Patch'

        def wrapped(outer, tool, value, item, result):
            return [dict(type='custom_tool_call', name='exec', call_id=outer,
                input=f'text(await tools.{tool}({json.dumps(value)}));\n'),
                dict(type='item_completed', thread_id='child', turn_id='child-turn', item=item),
                dict(type='custom_tool_call_output', call_id=outer, output=[
                    dict(type='input_text', text='Script completed\nWall time 0.3 seconds\nOutput:\n'),
                    dict(type='input_text', text=json.dumps(result)),
                ])]

        wait_result = dict(chunk_id='1234ab', wall_time_seconds=0.05, exit_code=0, original_token_count=3,
            output='D6_READY\n')
        wait_item = dict(type='CommandExecution', id='inner-wait', status='completed', exit_code=0,
            source='unified_exec_startup', aggregated_output='D6_READY\n', cwd=Path(args['workdir']).as_uri(),
            command=[args['shell'], '-c', args['cmd']])
        patch_item = dict(type='FileChange', id='inner-patch', status='completed', changes={'canary.py': {'type': 'update'}},
            stdout='Success. Updated the following files:\nM canary.py\n', stderr='')
        wait_rows = wrapped('outer-wait', 'exec_command', args, wait_item, wait_result)
        patch_rows = wrapped('outer-patch', 'apply_patch', command, patch_item, {})
        patch_rows[0]['input'] = patch_rows[0]['input'].replace('));\n', '))\n')
        rows = [dict(type='additional_tools', role='developer', tools=[]),
                dict(type='thread_settings_applied', thread_id='child', thread_settings={}), *wait_rows, *patch_rows]
        projection = dict(type='commandExecution', id='inner-wait', status='completed', exitCode=0,
                          source='unifiedExecStartup', aggregatedOutput='D6_READY\n', cwd=args['workdir'])
        patch_projection = dict(type='fileChange', id='inner-patch', status='completed')
        responses['history'] = [dict(turnId='child-turn', item=item) for item in (projection, patch_projection)] + responses['items']['data']
        raw = self.cooperative_rollout(responses, rows)
        observed = self.observe_worker(responses, binding, cooperative=True)
        self.assertEqual(observed['activity'], dict(source_digest=hashlib.sha256(raw).hexdigest(), calls=[
            dict(id='inner-wait', tool='exec_command', input_digest=evidence._digest(dict(tool_name='exec_command', tool_input=args))),
            dict(id='inner-patch', tool='apply_patch', input_digest=codex.patch_input_fingerprint(command))]))

        for name, activity in (
            ('extra JS', [*wait_rows, dict(patch_rows[0], input=patch_rows[0]['input'] + 'text(1);'), *patch_rows[1:]]),
            ('wrong wait args', [*wrapped('outer-wait', 'exec_command', dict(args, tty=True), wait_item, wait_result), *patch_rows]),
            ('resumable', [*wrapped('outer-wait', 'exec_command', args, wait_item, dict(wait_result, session_id=42)), *patch_rows]),
            ('extra nested item', [*wait_rows[:2], dict(wait_rows[1], item=dict(wait_item, id='another')), wait_rows[2], *patch_rows]),
            ('early patch', [*wait_rows[:2], *patch_rows, wait_rows[2]]),
            ('missing nested patch', [*wait_rows, patch_rows[0], patch_rows[2]]),
        ):
            self.cooperative_rollout(responses, activity)
            with self.subTest(name=name), self.assertRaises(StartupError):
                self.observe_worker(responses, binding, cooperative=True)
        self.cooperative_rollout(responses, rows)
        projection['id'] = 'outer-wait'
        with self.assertRaises(StartupError):
            self.observe_worker(responses, binding, cooperative=True)

    def test_cooperative_activity_allows_only_the_initial_v2_trigger_metadata(self):
        def row(kind, **payload):
            return dict(timestamp='fixture', type=kind, payload=payload)

        start = [row('session_meta', id='child'), row('event_msg', type='task_started', turn_id='child-turn'),
                 row('turn_context', turn_id='child-turn', multi_agent_version='v2'),
                 row('event_msg', type='thread_settings_applied', thread_id='child', thread_settings={})]
        trigger = row('inter_agent_communication_metadata', trigger_turn=True)
        call = row('response_item', type='custom_tool_call', call_id='patch', name='apply_patch', input='patch')
        output = row('response_item', type='custom_tool_call_output', call_id='patch', output='Success')
        completed = row('event_msg', type='task_complete', turn_id='child-turn', last_agent_message='report')

        def observe(rows, *, review=False):
            raw = b''.join(json.dumps(item).encode() + b'\n' for item in rows)
            return codex._cooperative_activity(raw, path=self.root / 'rollout.jsonl', child='child',
                turn='child-turn', result='report', review=review)['calls']

        self.assertEqual(observe([*start, trigger, call, output, completed]), [
            dict(id='patch', tool='apply_patch', input_digest=codex.patch_input_fingerprint('patch'))])
        self.assertEqual(observe([*start, trigger, completed], review=True), [])
        for rows in (
            [*start[:-1], trigger, start[-1], call, output, completed],
            [*start, trigger, trigger, call, output, completed],
            [*start, row('inter_agent_communication_metadata', trigger_turn=1), call, output, completed],
            [*start, row('inter_agent_communication_metadata', trigger_turn=True, extra=True), call, output, completed],
            [*start, row('inter_agent_communication', trigger_turn=True), call, output, completed],
            [*start, call, trigger, output, completed],
            [*start, call, output, completed, trigger],
        ):
            with self.subTest(rows=rows), self.assertRaises(doctor.ObservationError):
                observe(rows)

    def test_cooperative_observation_rejects_unknown_or_unfinished_activity(self):
        call = dict(type='custom_tool_call', call_id='patch', name='apply_patch', input='patch')
        output = dict(type='custom_tool_call_output', call_id='patch', output='Success')
        cases = [([call], True), ([output, call], True), ([call, output, output], True),
                 ([call, output], False), ([dict(call, name='exec'), output], True),
                 ([dict(type='function_call', call_id='shell', name='exec_command', arguments='{}')], True)]
        for activity, terminal in cases:
            responses, binding = self.worker_fixture()
            self.cooperative_rollout(responses, activity, terminal=terminal)
            with self.subTest(activity=activity, terminal=terminal), self.assertRaises(StartupError):
                self.observe_worker(responses, binding, cooperative=True)

    def test_cooperative_observation_accounts_for_the_pinned_wait_before_patching(self):
        responses, binding = self.worker_fixture()
        wait = dict(marker=str(self.root / 'ready'), python=str(Path(sys.executable).resolve()), seconds=5)
        binding['foreground_wait'] = wait
        args = codex.foreground_wait_args(wait, self.scope.repository_root)
        self.assertEqual(args['yield_time_ms'], 10000)
        self.assertIs(args['login'], False)
        self.assertIs(args['tty'], False)
        call = dict(type='function_call', call_id='wait', name='exec_command', arguments=json.dumps(args))
        result = dict(type='function_call_output', call_id='wait', output=(
            'Chunk ID: 1234ab\nWall time: 0.0500 seconds\nProcess exited with code 0\n'
            'Original token count: 3\nOutput:\nD6_READY\n'))
        terminal = dict(type='CommandExecution', id='wait', status='completed', exit_code=0,
                        source='unified_exec_startup', aggregated_output='D6_READY\n',
                        command=['/bin/sh', '-c', args['cmd']], cwd=Path(args['workdir']).as_uri())
        projection = dict(type='commandExecution', id='wait', status='completed', exitCode=0,
                          source='unifiedExecStartup', aggregatedOutput='D6_READY\n', cwd=args['workdir'])
        responses['history'] = [dict(turnId='child-turn', item=projection), *responses['items']['data']]
        command = '*** Begin Patch\n*** Update File: canary.py\n@@\n-return 0\n+return 42\n*** End Patch'
        patch_call = dict(type='custom_tool_call', call_id='patch', name='apply_patch', input=command)
        patch_result = dict(type='custom_tool_call_output', call_id='patch', output='Success')
        completed = dict(type='item_completed', thread_id='child', turn_id='child-turn', item=terminal)
        for wait_records in ([call, completed, result], [call, result, completed]):
            self.cooperative_rollout(responses, [*wait_records, patch_call, patch_result])
            observed = self.observe_worker(responses, binding, cooperative=True)
            self.assertEqual([(item['id'], item['tool']) for item in observed['activity']['calls']],
                             [('wait', 'exec_command'), ('patch', 'apply_patch')])
            self.assertEqual(observed['activity']['calls'][0]['input_digest'],
                             evidence._digest(dict(tool_name='exec_command', tool_input=args)))
        cases = {
            'changed arguments': ([dict(call, arguments=json.dumps(dict(args, login=True))), completed, result], projection),
            'resumable result': ([call, completed, dict(result, output=result['output'].replace(
                'Original token count:', 'Process running with session ID 42\nOriginal token count:'))], projection),
            'missing terminal event': ([call, result], projection),
            'terminal before call': ([completed, call, result], projection),
            'terminal after patch': ([call, result, patch_call, patch_result, completed], projection),
            'early patch': ([call, completed, patch_call, patch_result, result], projection),
            'inconsistent raw command': ([call, dict(completed, item=dict(terminal, command=['/bin/sh', '-c', 'true'])), result],
                                         projection),
            'prefixed shell command': ([call, dict(completed, item=dict(terminal,
                command=['/bin/sh', '-c', 'true', '-c', args['cmd']])), result], projection),
            'changed shell': ([call, dict(completed, item=dict(terminal,
                command=['/bin/zsh', '-c', args['cmd']])), result], projection),
            'changed raw cwd': ([call, dict(completed, item=dict(terminal, cwd='file:///other')), result], projection),
            'duplicate wait': ([call, completed, result, dict(call, call_id='other')], projection),
            'missing projection': ([call, completed, result], None),
            'failed projection': ([call, completed, result], dict(projection, status='failed', exitCode=1)),
        }
        for name, (activity, projected) in cases.items():
            with self.subTest(name=name), self.assertRaises(StartupError):
                responses['history'] = list(responses['items']['data'])
                if projected is not None:
                    responses['history'].insert(0, dict(turnId='child-turn', item=projected))
                self.cooperative_rollout(responses, activity)
                self.observe_worker(responses, binding, cooperative=True)

    def test_foreground_wait_command_requires_a_regular_marker(self):
        marker = self.root / "private ' marker"
        wait = dict(marker=str(marker), python=str(Path(sys.executable).resolve()), seconds=1)
        args = codex.foreground_wait_args(wait, self.scope.repository_root)

        def run_wait():
            return subprocess.run([args['shell'], '-c', args['cmd']], cwd=args['workdir'],
                                  capture_output=True, text=True, timeout=3)

        absent = run_wait()
        self.assertEqual((absent.returncode, absent.stdout), (1, ''))
        marker.touch()
        ready = run_wait()
        self.assertEqual((ready.returncode, ready.stdout), (0, 'D6_READY\n'))
        marker.rename(self.root / 'old')
        marker.symlink_to(self.root / 'old')
        linked = run_wait()
        self.assertEqual((linked.returncode, linked.stdout), (1, ''))

    def test_cooperative_observation_rejects_retry_and_replaced_turn(self):
        for retry, changed in ((True, False), (False, True), ('unknown', False)):
            responses, binding = self.worker_fixture()
            self.cooperative_rollout(responses, [])
            responses['turns']['data'][0]['willRetry'] = retry
            if changed:
                responses['turns_second'] = dict(data=[dict(id='later', status='completed', error=None)])
            with self.subTest(retry=retry, changed=changed), self.assertRaises(StartupError):
                self.observe_worker(responses, binding, cooperative=True)

    def test_cooperative_observation_rejects_projected_activity_missing_from_rollout(self):
        for item in (dict(type='commandExecution', status='completed', exitCode=0),
                     dict(type='fileChange', status='completed')):
            responses, binding = self.worker_fixture()
            self.cooperative_rollout(responses, [])
            responses['history'] = [dict(turnId='child-turn', item=dict(id='unaccounted', **item)),
                                    *responses['items']['data']]
            with self.subTest(item=item), self.assertRaises(StartupError):
                self.observe_worker(responses, binding, cooperative=True)

    def test_cooperative_observation_rechecks_the_same_raw_source(self):
        responses, binding = self.worker_fixture()
        self.cooperative_rollout(responses, [])
        with self.assertRaises(StartupError):
            self.observe_worker(responses, binding, mode='changed-rollout', cooperative=True)

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

    def test_workstream_creation_names_preserve_family_role_and_exact_native_lineage(self):
        cases = [(self.worker_fixture, self.observe_worker, "WS42.01", "worker_ws42_01_build_attempt"),
                 (self.review_assignment_fixture, self.observe_review_assignment,
                  "WS42.03", "review_ws42_03_review_attempt")]
        for fixture, observe, context, marker in cases:
            responses, binding = fixture()
            binding.update(workstream_context_id=context, task_name=marker)
            responses["spawn"]["data"][0]["item"]["agentPath"] = "/root/" + marker
            responses["child"]["thread"]["source"]["subAgent"]["thread_spawn"]["agent_path"] = "/root/" + marker
            with self.subTest(marker=marker):
                try:
                    receipt = observe(responses, binding)["receipt"]
                except StartupError:
                    self.fail("Exact prepared Workstreams creation marker was rejected")
                self.assertEqual(receipt["task_name"], marker)
                self.assertEqual(receipt["agent_path"], "/root/" + marker)
                self.assertEqual(receipt["worker_id"], "child")
                self.assertNotIn("workstream_context_id", receipt)
        responses = copy.deepcopy(self.responses)
        marker = "review_ws42_03_review_attempt"
        responses["spawn"]["data"][0]["item"]["agentPath"] = "/root/" + marker
        responses["child"]["thread"]["source"]["subAgent"]["thread_spawn"]["agent_path"] = "/root/" + marker
        binding = dict(self.binding, workstream_context_id="WS42.03", task_name=marker)
        try:
            receipt = self.collect(responses, binding=binding)["receipt"]
        except StartupError:
            self.fail("Exact prepared Workstreams D5 review marker was rejected")
        self.assertEqual(receipt["task_name"], marker)

    def test_workstream_creation_names_reject_other_attempt_family_role_or_unbound_context(self):
        for change in ("attempt", "family", "role", "context", "missing context", "legacy marker", "origin path"):
            responses, binding = self.worker_fixture()
            marker = "worker_ws42_01_build_attempt"
            binding.update(workstream_context_id="WS42.01", task_name=marker)
            if change == "attempt": marker = "worker_ws42_01_build_other"
            elif change == "family": marker = "worker_ws99_01_build_attempt"
            elif change == "role": marker = "worker_ws42_01_review_attempt"
            elif change == "context": binding["workstream_context_id"] = "WS42.02"
            elif change == "missing context": binding.pop("workstream_context_id")
            elif change == "legacy marker": marker = "worker_attempt"
            binding["task_name"] = marker
            responses["spawn"]["data"][0]["item"]["agentPath"] = "/root/" + marker
            responses["child"]["thread"]["source"]["subAgent"]["thread_spawn"]["agent_path"] = "/root/" + marker
            if change == "origin path":
                responses["child"]["thread"]["source"]["subAgent"]["thread_spawn"]["agent_path"] = "/root/worker_ws99_01_build_attempt"
            with self.subTest(change=change), self.assertRaises(StartupError):
                self.observe_worker(responses, binding)

    def test_native_task_names_normalize_without_truncating_or_losing_attempt_identity(self):
        self.assertTrue(callable(getattr(codex, "native_task_name", None)), "Shared native marker derivation is unavailable")
        self.assertEqual(codex.native_task_name("attempt", "worker"), "worker_attempt")
        self.assertEqual(codex.native_task_name("attempt", "review"), "review_attempt")
        self.assertEqual(codex.native_task_name("attempt", "worker", "WSAb42.01"), "worker_wsab42_01_build_attempt")
        self.assertEqual(codex.native_task_name("a" * 32, "review", "WS42.03"), "review_ws42_03_review_" + "a" * 32)
        for context in ("C12", "WS42.0", "WS42.00", "WS42.01.BUILD", "WS42/01", "WS42.01\n", "WS.01", "WS" + "a" * 17 + ".01", "WS42." + "1" * 17, 42, {}):
            with self.subTest(context=context), self.assertRaises(StartupError):
                codex.native_task_name("attempt", "worker", context)
        for attempt, role, context in (("a" * 64, "worker", "WS42.01"),
                                       ("other/path", "worker", "WS42.01"),
                                       ("UPPER", "worker", "WS42.01"),
                                       ("attempt", "coord", "WS42.01")):
            with self.subTest(attempt=attempt, role=role), self.assertRaises(StartupError):
                codex.native_task_name(attempt, role, context)

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

    def test_assignment_failure_preserves_only_recognized_codes_and_explicit_retry_intent(self):
        cases = [
            ("serverOverloaded", True, "serverOverloaded"),
            ("rateLimitExceeded", False, "rateLimitExceeded"),
            ("usageLimitExceeded", None, "usageLimitExceeded"),
            ("internalServerError", False, "internalServerError"),
            ({"httpConnectionFailed": {"httpStatusCode": 503}}, None, "httpConnectionFailed"),
            ({"responseStreamConnectionFailed": {}}, None, "responseStreamConnectionFailed"),
            ({"responseStreamDisconnected": {}}, None, "responseStreamDisconnected"),
            ({"responseTooManyFailedAttempts": {}}, False, "responseTooManyFailedAttempts"),
            ({"activeTurnNotSteerable": {"turnKind": "review"}}, None, "activeTurnNotSteerable"),
        ]
        for info, retry, expected in cases:
            responses, binding = self.worker_fixture()
            turn = responses["turns"]["data"][0]
            turn.update(status="failed", error=dict(codexErrorInfo=info,
                message="secret-token", additionalDetails="secret-details"))
            if retry is not None:
                turn["willRetry"] = retry
            with self.subTest(info=info, retry=retry):
                observed = self.observe_worker(responses, binding)
                self.assertIn("failure_code", observed["receipt"])
                self.assertEqual(observed["receipt"]["failure_code"], expected)
                self.assertIs(observed["receipt"]["will_retry"], retry)
                self.assertNotIn("secret", json.dumps(observed))
                self.assertNotIn("httpStatusCode", json.dumps(observed))
                self.assertIsNone(observed["result"])

    def test_assignment_unknown_failure_and_retry_intent_are_never_inferred(self):
        cases = [None, {}, "serverOverloaded", {"message": "rateLimitExceeded"},
                 {"codexErrorInfo": "unknown-secret"}, {"codexErrorInfo": "x" * 4097},
                 {"codexErrorInfo": ["serverOverloaded"]},
                 {"codexErrorInfo": {"serverOverloaded": {}}},
                 {"codexErrorInfo": {"httpConnectionFailed": "secret"}},
                 {"codexErrorInfo": {"httpConnectionFailed": {}, "other": {}}}]
        for error in cases:
            responses, binding = self.review_assignment_fixture()
            responses["turns"]["data"][0].update(status="failed", error=error, willRetry="false")
            with self.subTest(error=error):
                receipt = self.observe_review_assignment(responses, binding)["receipt"]
                self.assertIn("failure_code", receipt)
                self.assertIsNone(receipt["failure_code"])
                self.assertIsNone(receipt["will_retry"])
        for status in (None, "inProgress", "interrupted", "failed", "completed"):
            responses, binding = self.worker_fixture()
            if status is None:
                responses["turns"]["data"] = []
            else:
                responses["turns"]["data"][0]["status"] = status
            with self.subTest(status=status):
                receipt = self.observe_worker(responses, binding)["receipt"]
                self.assertIn("failure_code", receipt)
                self.assertIsNone(receipt["failure_code"])
                self.assertIsNone(receipt["will_retry"])

    def test_assignment_rechecks_normalized_failure_and_host_retry_intent(self):
        for changed in ({"error": {"codexErrorInfo": "rateLimitExceeded"}}, {"willRetry": False}):
            responses, binding = self.worker_fixture()
            responses["turns"]["data"][0].update(status="failed",
                error={"codexErrorInfo": "serverOverloaded"}, willRetry=True)
            responses["turns_second"] = copy.deepcopy(responses["turns"])
            responses["turns_second"]["data"][0].update(changed)
            with self.subTest(changed=changed), self.assertRaises(StartupError):
                self.observe_worker(responses, binding)

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
                             ("native_version", None), ("client_surface", "codex-desktop"),
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

    def test_reader_update_keeps_capability_digest_but_catalog_or_controls_changes_do_not(self):
        responses, controls = self.control_fixture()
        original = self.discover_workers(responses, controls)
        updated_controls = dict(controls)
        updated = self.discover_workers(responses, updated_controls, version="9.999.0")
        self.assertEqual(original["native_version"], "0.163.0")
        self.assertEqual(updated["native_version"], "9.999.0")
        self.assertEqual(updated["capability_digest"], original["capability_digest"])
        changed = copy.deepcopy(responses)
        changed["catalog"]["data"][0]["supportedReasoningEfforts"].append(dict(reasoningEffort="xhigh"))
        self.assertNotEqual(self.discover_workers(changed, updated_controls, version="9.999.0")["capability_digest"],
                            updated["capability_digest"])
        changed_controls = copy.deepcopy(updated_controls)
        changed_controls["dispatch_controls"]["explicit_effort"] = False
        self.assertNotEqual(self.discover_workers(responses, changed_controls, version="9.999.0")["capability_digest"],
                            updated["capability_digest"])
        self.assertEqual(controls["native_version"], "0.163.0")

    def test_discovery_rejects_unqualified_surface_and_malformed_or_unbounded_catalog(self):
        for label in ("desktop", "version metadata", "originator", "control type", "duplicate", "effort", "page loop"):
            responses, controls = self.control_fixture()
            if label == "desktop": controls["client_surface"] = "codex-desktop"
            elif label == "version metadata": controls["native_version"] = None
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

    def test_desktop_catalog_preserves_surface_binding_across_reader_updates(self):
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
            with self.subTest(version=version):
                updated = self.discover_workers(responses, controls, version=version)
                self.assertEqual(updated["native_version"], version)
                self.assertEqual(updated["capability_digest"], observed["capability_digest"])
        controls["client_surface"] = "codex-cli"
        with self.assertRaises(StartupError):
            self.discover_workers(responses, controls, version="0.164.0-alpha.11.1")
        controls.update(client_surface="codex-desktop", native_version="0.163.0")
        responses["parent"]["thread"]["cliVersion"] = "0.163.0"
        self.assertEqual(self.discover_workers(responses, controls, version="0.163.0")["client_surface"], "codex-desktop")

    def test_work_desktop_originator_preserves_live_surface_and_identity_checks(self):
        responses, controls = self.current_desktop_fixture(self.control_fixture)
        responses['parent']['thread']['originator']='codex_work_desktop'
        observed=self.discover_workers(responses,controls,version='0.165.0')
        self.assertEqual(observed['originator'],'codex_work_desktop')
        for source in ('exec','unknown',None):
            changed=copy.deepcopy(responses)
            changed['parent']['thread']['source']=source
            with self.assertRaises(StartupError):
                self.discover_workers(changed,controls,version='0.165.0')

    def current_desktop_fixture(self, fixture):
        responses, binding = fixture()
        binding.update(client_surface="codex-desktop", native_version="0.165.0")
        for identity in ("parent", "child"):
            responses[identity]["thread"]["cliVersion"] = "0.165.0-alpha.1.2"
        responses["parent"]["thread"].update(source="vscode", originator="Codex Desktop")
        return responses, binding

    def test_current_desktop_discovery_distinguishes_observer_from_creation_version(self):
        responses, controls = self.current_desktop_fixture(self.control_fixture)
        try:
            observed = self.discover_workers(responses, controls, version="0.165.0")
        except StartupError:
            self.fail("Proven observer/creation version pair was rejected")
        self.assertEqual(observed["native_version"], "0.165.0")
        self.assertEqual(observed["client_surface"], "codex-desktop")
        self.assertEqual(observed["originator"], "Codex Desktop")
        for field, value in (("cliVersion", None), ("cliVersion", ""),
                             ("cliVersion", {}), ("source", "exec"),
                             ("originator", "codex_exec"), ("originator", "Codex desktop"),
                             ("cwd", "/other")):
            changed = copy.deepcopy(responses)
            changed["parent"]["thread"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(StartupError):
                self.discover_workers(changed, controls, version="0.165.0")
        for reader in ("0.163.0", "0.164.0-alpha.11.1", "0.165.0-alpha.1.2", "9.999.0"):
            changed = dict(controls, native_version=reader)
            with self.subTest(reader=reader):
                self.assertEqual(self.discover_workers(responses, changed, version=reader)["native_version"], reader)
        controls["client_surface"] = "codex-cli"
        with self.assertRaises(StartupError):
            self.discover_workers(responses, controls, version="0.165.0")

    def test_current_desktop_native_chain_requires_exact_identity_with_independent_creation_versions(self):
        responses, binding = self.current_desktop_fixture(self.worker_fixture)
        try:
            receipt = self.observe_worker(responses, binding, version="0.165.0")["receipt"]
        except StartupError:
            self.fail("Proven native chain observer/creation version pair was rejected")
        self.assertEqual(receipt["native_version"], "0.165.0")
        self.assertEqual(receipt["worker_id"], "child")
        self.assertEqual(receipt["turn_status"], "completed")
        for creation in ("0.165.0", "0.163.0", "9.999.0-alpha.42"):
            changed = copy.deepcopy(responses)
            changed["child"]["thread"]["cliVersion"] = creation
            with self.subTest(creation=creation):
                receipt = self.observe_worker(changed, binding, version="0.165.0")["receipt"]
                self.assertEqual(receipt["worker_creation_version"], creation)
        for field, value in (("cliVersion", None), ("cliVersion", ""),
                             ("cliVersion", "line\nbreak"), ("cwd", "/other"),
                             ("parentThreadId", "other")):
            changed = copy.deepcopy(responses)
            changed["child"]["thread"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(StartupError):
                self.observe_worker(changed, binding, version="0.165.0")
        changed = copy.deepcopy(responses)
        changed["spawn"]["data"][0]["item"]["agentPath"] = "/root/worker_other"
        with self.assertRaises(StartupError):
            self.observe_worker(changed, binding, version="0.165.0")
        changed = copy.deepcopy(responses)
        changed["turns_second"] = dict(data=[dict(id="other", status="completed", error=None)])
        with self.assertRaises(StartupError):
            self.observe_worker(changed, binding, version="0.165.0")

    def test_current_desktop_d5_review_uses_proven_creation_pair_and_exact_surface(self):
        responses, _ = self.current_desktop_fixture(lambda: (copy.deepcopy(self.responses), {}))
        try:
            observed = self.collect(responses, version="0.165.0")
        except StartupError:
            self.fail("Proven D5 observer/creation version pair was rejected")
        self.assertEqual(observed["report"], self.report)
        self.assertEqual(observed["receipt"]["native_version"], "0.165.0")
        for field, value in (("source", "exec"), ("originator", "codex_exec"), ("cliVersion", None)):
            changed = copy.deepcopy(responses)
            changed["parent"]["thread"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(StartupError):
                self.collect(changed, version="0.165.0")

    def test_d5_review_rejects_consistent_surface_switch_from_admitted_binding(self):
        responses, _ = self.current_desktop_fixture(lambda: (copy.deepcopy(self.responses), {}))
        binding = dict(self.binding, native_version="0.165.0", client_surface="codex-desktop")
        self.assertEqual(self.collect(responses, binding=binding, version="9.999.0")["report"], self.report)
        responses["parent"]["thread"].update(source="exec", originator="codex_exec")
        with self.assertRaises(StartupError):
            self.collect(responses, binding=binding, version="9.999.0")

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
            with self.subTest(version=version):
                self.assertEqual(self.discover_workers(responses, controls, version=version)["native_version"], version)

    def test_updated_reader_keeps_admitted_worker_and_review_versions_without_rebinding(self):
        responses, binding = self.current_desktop_fixture(self.worker_fixture)
        responses["child"]["thread"]["cliVersion"] = "0.166.0-alpha.1"
        try:
            receipt = self.observe_worker(responses, binding, version="9.999.0")["receipt"]
        except StartupError:
            self.fail("Reader update rejected the unchanged admitted assignment")
        self.assertEqual(receipt["native_version"], "0.165.0")
        self.assertEqual(receipt["current_observer_version"], "9.999.0")
        self.assertEqual(receipt["parent_creation_version"], "0.165.0-alpha.1.2")
        self.assertEqual(receipt["worker_creation_version"], "0.166.0-alpha.1")
        self.assertEqual(receipt["assignment_digest"], binding["assignment_digest"])
        self.assertEqual(receipt["worker_id"], "child")
        responses, _ = self.current_desktop_fixture(lambda: (copy.deepcopy(self.responses), {}))
        binding = dict(self.binding, native_version="0.165.0")
        receipt = self.collect(responses, binding=binding, version="9.999.0")["receipt"]
        self.assertEqual(receipt["native_version"], "0.165.0")
        self.assertEqual(receipt["current_observer_version"], "9.999.0")

    def test_live_initialization_contract_rejects_missing_malformed_or_changed_shapes(self):
        for initialized in ({}, {"codexHome": "/private/native"},
                dict(codexHome=True, platformFamily="unix", platformOs="macos", userAgent="fixture"),
                dict(codexHome="/private/native", platformFamily="unix", platformOs="macos", userAgent="")):
            responses, binding = self.worker_fixture()
            responses["initialize"] = initialized
            with self.subTest(initialized=initialized), self.assertRaises(StartupError):
                self.observe_worker(responses, binding)

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
