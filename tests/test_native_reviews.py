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


if __name__ == "__main__":
    unittest.main()
