"""Runtime boundaries use disposable enrollments; no hooks, models or user state."""

import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from runtime.adapters import codex
from runtime import startup


PACKAGE = Path(__file__).resolve().parents[1]


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vibe runtime ")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.repo = self.base / "project"
        self.repo.mkdir()
        self.git(self.repo, "init", "-q")
        self.payload = {"hook_event_name": "PreToolUse", "session_id": "session-1",
                        "cwd": str(self.repo), "turn_id": "turn-1", "tool_use_id": "call-1",
                        "tool_name": "apply_patch", "tool_input": {"command": "PRIVATE_PATCH"}}

    def git(self, root, *args):
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        return subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull,
                               "-c", "commit.gpgsign=false", "-c", "init.templateDir=",
                               "-C", str(root), *args], check=True, env=env,
                              capture_output=True, text=True, timeout=5).stdout.strip()

    def enroll(self, root=None, **updates):
        root = root or self.repo
        identity = startup.checkout(root)
        record = {"schema_version": 1, "project_id": "fixture-project",
                  "repository_root": str(identity[0]), "git_common_dir": str(identity[1]),
                  "clients": ["codex"], "policy_digest": startup.policy_digest(PACKAGE)}
        record.update(updates)
        path = root / startup.PROJECT_FILE
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(record))
        return path

    def runtime(self, state_dir=None):
        return {"schema_version": 1, "state_dir": str(state_dir or self.base / "state")}

    def invoke(self, event="PreToolUse", payload=None, raw=None, client="codex"):
        payload = self.payload if payload is None else payload
        result = subprocess.run([sys.executable, "-I", "-B", str(PACKAGE / "scripts/workflow.py"),
                                 client, event], cwd=self.repo,
                                input=raw if raw is not None else json.dumps(payload).encode(),
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stderr, b"")
        return json.loads(result.stdout) if result.stdout else None

    def test_legacy_events_are_silent_without_runtime_opt_in(self):
        self.enroll()
        for kind in ("PreToolUse", "PostToolUse", "Stop", "Interrupt"):
            with self.subTest(kind=kind):
                output = self.invoke(kind, {**self.payload, "hook_event_name": kind})
                self.assertEqual(output, {} if kind == "Stop" else None)

    def test_runtime_scope_reuses_validated_checkout_and_never_initializes_state(self):
        self.enroll(runtime=self.runtime())
        self.assertTrue(hasattr(startup, "resolve_project"), "reusable scope resolver is missing")
        scope = startup.resolve_project(codex.normalize_runtime(self.payload), PACKAGE)
        self.assertEqual(scope.project_id, "fixture-project")
        self.assertEqual(scope.repository_root, self.repo)
        self.assertEqual(scope.git_common_dir, self.repo / ".git")
        self.assertEqual(scope.runtime.state_dir, self.base / "state")
        self.assertEqual(scope.runtime.schema_version, 1)
        self.assertFalse(scope.runtime.state_dir.exists())

    def test_legacy_resolver_has_no_runtime_settings(self):
        self.enroll()
        self.assertTrue(hasattr(startup, "resolve_project"), "reusable scope resolver is missing")
        event = codex.normalize({"hook_event_name": "SessionStart", "session_id": "session-1",
                                 "cwd": str(self.repo), "source": "startup"})
        scope = startup.resolve_project(event, PACKAGE)
        self.assertIsNone(scope.runtime)
        self.assertEqual(scope.policy_digest, startup.policy_digest(PACKAGE))

    def test_runtime_enabled_patch_is_denied_without_state_writes(self):
        self.enroll(runtime=self.runtime())
        output = self.invoke()
        self.assertIn("hookSpecificOutput", output)
        hook = output["hookSpecificOutput"]
        self.assertEqual(hook["hookEventName"], "PreToolUse")
        self.assertEqual(hook["permissionDecision"], "deny")
        self.assertIn("state", hook["permissionDecisionReason"])
        self.assertNotIn("updatedInput", hook)
        self.assertFalse((self.base / "state").exists())
        self.assertNotIn("PRIVATE_PATCH", str(output))

    def test_runtime_other_events_report_uncertainty_without_continuing_or_replacing_output(self):
        self.enroll(runtime=self.runtime())
        for kind in ("PreToolUse", "PostToolUse", "Stop", "Interrupt"):
            with self.subTest(kind=kind):
                output = self.invoke(kind, {**self.payload, "hook_event_name": kind,
                                            "tool_name": "Bash", "tool_response": "PRIVATE_RESULT"})
                self.assertNotIn("not implemented", str(output))
                self.assertNotIn("decision", output)
                self.assertNotIn("continue", output)
                self.assertNotIn("PRIVATE_RESULT", str(output))
                self.assertNotIn("SessionStart", str(output))
        self.assertFalse((self.base / "state").exists())

    def task_cli(self, action, request=None, *options):
        result = subprocess.run([sys.executable, "-I", "-B", str(PACKAGE / "scripts/workflow.py"),
                                 "task", action, "--cwd", str(self.repo), *options],
                                input=json.dumps(request).encode() if request is not None else b"",
                                capture_output=True, timeout=5)
        self.assertEqual(result.stderr, b"")
        return result.returncode, json.loads(result.stdout)

    def test_task_cli_start_update_status_and_validation(self):
        self.enroll(runtime=self.runtime())
        request = dict(client="codex", session_id="session-1", task_id="cli-task", scope_ref="user:task",
                       mode="editable", decision_ref="user:request")
        code, output = self.task_cli("start", request)
        self.assertEqual(code, 0, output)
        self.assertEqual(output["task"]["state"], "planned")
        self.assertTrue(output["ok"])
        update = {key: request[key] for key in ("client", "session_id", "task_id", "scope_ref")} | dict(
            expected_revision=1, state="active", reason="Implement request", reference="user:request")
        code, output = self.task_cli("update", update)
        self.assertEqual(code, 0, output)
        self.assertEqual(output["task"]["revision"], 2)
        self.assertIsNone(self.invoke())
        code, output = self.task_cli("status", None, "--client", "codex", "--session", "session-1")
        self.assertEqual(code, 0, output)
        self.assertEqual(output["task"]["task_id"], "cli-task")
        for invalid in (update, {**update, "state": "ready"}, {**update, "unexpected": True}):
            code, output = self.task_cli("update", invalid)
            self.assertEqual(code, 1, output)
            self.assertFalse(output["ok"])
            self.assertNotIn("Traceback", str(output))

    def test_task_cli_unconfigured_scope_does_not_initialize(self):
        self.enroll()
        code, output = self.task_cli("start", dict(client="codex", session_id="session", task_id="task",
            scope_ref="user:task", mode="editable", decision_ref="user:request"))
        self.assertEqual(code, 1, output)
        self.assertFalse((self.base / "state").exists())

    def test_doctor_cli_reports_missing_enrollment_without_initialization(self):
        result = subprocess.run([sys.executable, "-I", "-B", str(PACKAGE / "scripts/workflow.py"),
            "doctor", "--cwd", str(self.repo), "--client", "codex", "--executable", "/unavailable-native"],
            capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, b"")
        report = json.loads(result.stdout)
        self.assertEqual(report.get("enrollment", {}).get("status"), "missing")
        self.assertEqual(report.get("package", {}).get("status"), "passed")
        self.assertEqual(report.get("execution", {}).get("status"), "unverified")
        self.assertFalse((self.base / "state").exists())

    def incomplete_package(self):
        installed = self.base / "incomplete-package"
        shutil.copytree(PACKAGE, installed, ignore=shutil.ignore_patterns(".git", ".superpowers", "__pycache__"))
        (installed / "runtime/state.py").unlink()
        self.enroll(runtime=self.runtime())
        return installed

    def test_doctor_cli_missing_state_module_retains_independent_json_report(self):
        installed = self.incomplete_package()
        result = subprocess.run([sys.executable, "-I", "-B", str(installed / "scripts/workflow.py"),
            "doctor", "--cwd", str(self.repo), "--client", "codex", "--executable", "/unavailable-native"],
            capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, b"")
        report = json.loads(result.stdout)
        self.assertEqual(report["package"]["status"], "failed")
        self.assertEqual(report["state"]["status"], "unavailable")
        self.assertEqual(report["native"]["status"], "unavailable")
        self.assertEqual(report["execution"]["status"], "unverified")
        self.assertNotIn("Traceback", result.stdout.decode())
        self.assertFalse((self.base / "state").exists())

    def test_task_cli_missing_state_module_returns_sanitized_json_failure(self):
        installed = self.incomplete_package()
        result = subprocess.run([sys.executable, "-I", "-B", str(installed / "scripts/workflow.py"),
            "task", "status", "--cwd", str(self.repo), "--client", "codex", "--session", "session-1"],
            capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, b"")
        report = json.loads(result.stdout)
        self.assertFalse(report["ok"])
        self.assertIn("error", report)
        self.assertNotIn("runtime.state", report["error"])
        self.assertNotIn("Traceback", result.stdout.decode())
        self.assertFalse((self.base / "state").exists())

    def test_stale_policy_denies_only_accepted_runtime_patch_scope(self):
        self.enroll(policy_digest="stale", runtime=self.runtime())
        output = self.invoke()
        self.assertEqual(output.get("hookSpecificOutput", {}).get("permissionDecision"), "deny")
        self.assertFalse((self.base / "state").exists())
        self.enroll(policy_digest="stale")
        output = self.invoke()
        self.assertIn("differ", output.get("systemMessage", ""))
        self.assertNotIn("permissionDecision", str(output))
        self.enroll(policy_digest="stale", runtime=self.runtime(), clients=["claude-code"])
        self.assertIsNone(self.invoke())

    def test_unrelated_and_wrong_client_runtime_enrollment_are_silent(self):
        self.enroll(runtime=self.runtime(), clients=["claude-code"])
        self.assertIsNone(self.invoke())
        neighbor = self.base / "neighbor"
        neighbor.mkdir()
        self.git(neighbor, "init", "-q")
        self.enroll(runtime=self.runtime())
        self.assertIsNone(self.invoke(payload={**self.payload, "cwd": str(neighbor)}))

    def test_runtime_worktree_needs_its_own_enrollment(self):
        self.enroll(runtime=self.runtime())
        self.git(self.repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "--allow-empty", "-qm", "fixture")
        linked = self.base / "linked"
        self.git(self.repo, "worktree", "add", "--detach", str(linked))
        payload = {**self.payload, "cwd": str(linked)}
        self.assertIsNone(self.invoke(payload=payload))
        self.enroll(linked, runtime=self.runtime())
        output = self.invoke(payload=payload)
        self.assertEqual(output.get("hookSpecificOutput", {}).get("permissionDecision"), "deny")
        self.enroll(linked, repository_root=str(self.repo), runtime=self.runtime())
        output = self.invoke(payload=payload)
        self.assertIn("does not cover", output["systemMessage"])
        self.assertNotIn("permissionDecision", str(output))

    def test_missing_policy_or_client_sources_raise_scoped_runtime_error(self):
        self.enroll(runtime=self.runtime())
        event = codex.normalize_runtime(self.payload)
        with patch("runtime.startup.policy_digest", side_effect=startup.StartupError("Policy source unavailable")):
            with self.assertRaises(startup.RuntimeScopeError):
                startup.resolve_project(event, PACKAGE)
        original = Path.is_file
        with patch.object(Path, "is_file", lambda path: False if path == PACKAGE / "clients/codex.md" else original(path)):
            with self.assertRaises(startup.RuntimeScopeError):
                startup.resolve_project(event, PACKAGE)
        self.assertFalse((self.base / "state").exists())

    def test_malformed_runtime_config_is_error_without_fallback(self):
        for runtime in (None, [], {}, {"schema_version": True, "state_dir": str(self.base / "state")},
                        {"schema_version": 2, "state_dir": str(self.base / "state")},
                        {"schema_version": 1, "state_dir": 12}, self.runtime(Path("relative")),
                        self.runtime(self.repo / "state"), self.runtime(PACKAGE / "state"),
                        self.runtime(self.base / ".codex/plugins/cache/state")):
            with self.subTest(runtime=runtime):
                self.enroll(runtime=runtime)
                output = self.invoke()
                self.assertIn("runtime", output.get("systemMessage", "").lower())
                self.assertNotIn("permissionDecision", str(output))

    def test_state_directory_must_be_canonical_and_outside_any_repository(self):
        alias = self.base / "alias"
        alias.symlink_to(self.base, target_is_directory=True)
        other = self.base / "other-repo"
        other.mkdir()
        self.git(other, "init", "-q")
        for state_dir in (alias / "state", other / "state"):
            with self.subTest(state_dir=state_dir):
                self.enroll(runtime=self.runtime(state_dir))
                self.assertIn("runtime", self.invoke().get("systemMessage", "").lower())

    def test_state_directory_rejects_existing_and_missing_descendants_of_bare_repository(self):
        bare = self.base / "archive"
        bare.mkdir()
        self.git(bare, "init", "--bare", "-q")
        existing = bare / "runtime"
        existing.mkdir()
        event = codex.normalize_runtime(self.payload)
        for state_dir in (existing, bare / "missing/deeper/runtime"):
            with self.subTest(state_dir=state_dir):
                self.enroll(runtime=self.runtime(state_dir))
                with patch.dict(os.environ, {"GIT_DIR": str(self.repo / ".git"),
                                             "GIT_WORK_TREE": str(self.repo),
                                             "GIT_CEILING_DIRECTORIES": str(bare),
                                             "GIT_DISCOVERY_ACROSS_FILESYSTEM": "0"}):
                    with self.assertRaisesRegex(startup.StartupError, "outside repositories"):
                        startup.resolve_project(event, PACKAGE)
                self.assertFalse((state_dir / "runtime.sqlite3").exists())
        self.assertFalse((bare / "missing").exists())

    def test_state_directory_cannot_descend_from_a_regular_file(self):
        parent = self.base / "regular-file"
        parent.write_text("private fixture")
        self.enroll(runtime=self.runtime(parent / "state"))
        output = self.invoke()
        self.assertIn("directory", output.get("systemMessage", "").lower())
        self.assertNotIn("permissionDecision", str(output))

    def test_runtime_startup_never_emits_an_oversized_context(self):
        self.enroll(runtime=self.runtime())
        payload = {"hook_event_name": "SessionStart", "source": "startup", "cwd": str(self.repo),
                   "session_id": "word " * 160}
        output = self.invoke("SessionStart", payload)
        self.assertIn("context limit", output.get("systemMessage", ""))
        self.assertNotIn("applies to this enrolled checkout", str(output))

    def test_runtime_startup_adds_only_bounded_local_pointer_and_native_identity(self):
        self.enroll(runtime=self.runtime())
        payload = {"hook_event_name": "SessionStart", "source": "startup", "cwd": str(self.repo),
                   "session_id": "session-1"}
        output = self.invoke("SessionStart", payload)
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn(str(self.base / "state/runtime.sqlite3"), context)
        self.assertIn("session-1", context)
        self.assertLessEqual(len(context.split()), 150)
        self.assertFalse((self.base / "state").exists())

    def test_runtime_input_is_bounded_and_errors_are_event_specific(self):
        for kind in ("PreToolUse", "PostToolUse", "Stop", "Interrupt"):
            for raw in (b"[]", b'{"x":1,"x":2}', b'{"x":NaN}', b"\xff",
                        b"PRIVATE_SENTINEL", b"x" * (startup.MAX_INPUT + 1)):
                with self.subTest(kind=kind, raw=raw[:16]):
                    output = self.invoke(kind, raw=raw)
                    self.assertIn(kind, output.get("systemMessage", ""))
                    self.assertNotIn("SessionStart", str(output))
                    self.assertNotIn("PRIVATE_SENTINEL", str(output))
                    self.assertNotIn("decision", output)

    def test_cli_event_must_match_payload_and_claude_remains_startup_only(self):
        self.enroll(runtime=self.runtime())
        output = self.invoke("Stop")
        self.assertIn("Stop", output.get("systemMessage", ""))
        self.assertNotIn("decision", output)
        output = self.invoke(client="claude-code")
        self.assertIn("unsupported", output.get("systemMessage", "").lower())
        self.assertNotIn("permissionDecision", str(output))


class RuntimeAdapterTests(unittest.TestCase):
    def normalize(self, **updates):
        self.assertTrue(hasattr(codex, "normalize_runtime"), "runtime normalizer is missing")
        payload = {"hook_event_name": "PreToolUse", "session_id": "session-1", "cwd": "/tmp",
                   "tool_name": "apply_patch", **updates}
        return codex.normalize_runtime(payload)

    def result(self, kind, action, reason="safe reason"):
        self.assertTrue(hasattr(codex, "render_runtime"), "runtime renderer is missing")
        from runtime.engine import HookResult
        return codex.render_runtime(HookResult(kind, action, reason))

    def test_normalizer_preserves_only_event_identity_and_needed_observations(self):
        event = self.normalize(turn_id="turn-1", tool_use_id="call-1", transcript_path="PRIVATE_PATH",
                               tool_input={"command": "PRIVATE_INPUT"}, tool_response="PRIVATE_RESULT")
        self.assertEqual((event.kind, event.client, event.session_id), ("PreToolUse", "codex", "session-1"))
        self.assertEqual(event.cwd, Path("/tmp"))
        self.assertEqual((event.turn_id, event.tool_call_id, event.tool_name),
                         ("turn-1", "call-1", "apply_patch"))
        self.assertNotIn("PRIVATE", repr(event))
        self.assertIsNone(self.normalize().turn_id)
        self.assertIsNone(self.normalize().tool_call_id)

    def test_receipt_fingerprint_requires_stable_identity_and_detects_changed_observations(self):
        first = self.normalize(turn_id="turn-1", tool_use_id="call-1", tool_input={"b": 2, "a": 1})
        reordered = self.normalize(turn_id="turn-1", tool_use_id="call-1", tool_input={"a": 1, "b": 2},
                                   transcript_path="ignored")
        changed = self.normalize(turn_id="turn-1", tool_use_id="call-1", tool_input={"a": 3, "b": 2})
        self.assertEqual(first.receipt_fingerprint, reordered.receipt_fingerprint)
        self.assertNotEqual(first.receipt_fingerprint, changed.receipt_fingerprint)
        self.assertEqual(len(first.receipt_fingerprint), 64)
        self.assertIsNone(self.normalize(tool_use_id="call-1").receipt_fingerprint)
        self.assertIsNone(self.normalize(turn_id="turn-1").receipt_fingerprint)
        post = self.normalize(hook_event_name="PostToolUse", turn_id="turn-1", tool_use_id="call-1",
                              tool_response={"exit_code": 0})
        failed = self.normalize(hook_event_name="PostToolUse", turn_id="turn-1", tool_use_id="call-1",
                                tool_response={"exit_code": 1})
        self.assertNotEqual(post.receipt_fingerprint, failed.receipt_fingerprint)

    def test_normalizer_rejects_malformed_required_and_optional_identity(self):
        for field in ("session_id", "cwd", "turn_id", "tool_use_id", "tool_name"):
            for value in (True, [], 1, "", " ", "bad\0id", "bad\nid", "x" * 4097):
                with self.subTest(field=field, value=repr(value)[:20]):
                    with self.assertRaises(startup.StartupError):
                        self.normalize(**{field: value})
        for updates in ({"cwd": "relative"}, {"hook_event_name": "SessionStart"},
                        {"hook_event_name": []}, {"tool_name": None}):
            with self.subTest(updates=updates), self.assertRaises(startup.StartupError):
                self.normalize(**updates)

    def test_stop_active_requires_boolean_and_absence_is_unknown(self):
        event = self.normalize(hook_event_name="Stop", stop_hook_active=True)
        self.assertTrue(event.stop_hook_active)
        self.assertIsNone(self.normalize(hook_event_name="Stop").stop_hook_active)
        for value in (None, 0, 1, "false", []):
            with self.subTest(value=value), self.assertRaises(startup.StartupError):
                self.normalize(hook_event_name="Stop", stop_hook_active=value)

    def test_non_tool_events_ignore_unused_tool_fields(self):
        for kind in ("Stop", "Interrupt"):
            with self.subTest(kind=kind):
                event = self.normalize(hook_event_name=kind, tool_name=[], tool_use_id={},
                                       last_assistant_message={"private": "PRIVATE"})
                self.assertIsNone(event.tool_name)
                self.assertIsNone(event.tool_call_id)
                self.assertNotIn("PRIVATE", repr(event))

    def test_pass_never_grants_permission_and_stop_always_returns_json(self):
        for kind in ("PreToolUse", "PostToolUse", "Stop", "Interrupt"):
            with self.subTest(kind=kind):
                self.assertEqual(self.result(kind, "pass"), {} if kind == "Stop" else None)

    def test_render_uses_only_supported_event_output_schemas(self):
        self.assertEqual(self.result("PreToolUse", "deny"), {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": "safe reason"}})
        self.assertEqual(self.result("PostToolUse", "context"), {"hookSpecificOutput": {
            "hookEventName": "PostToolUse", "additionalContext": "safe reason"}})
        self.assertEqual(self.result("Stop", "continue"), {"decision": "block", "reason": "safe reason"})
        for kind in ("Stop", "Interrupt"):
            self.assertEqual(self.result(kind, "context"), {"systemMessage": "safe reason"})

    def test_renderer_sanitizes_controls_and_bounds_reason(self):
        output = self.result("PreToolUse", "deny", "safe\nreason\0\x1b" + "x" * 2000)
        reason = output["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertNotIn("\n", reason)
        self.assertNotIn("\0", reason)
        self.assertNotIn("\x1b", reason)
        self.assertLessEqual(len(reason), 1024)

    def test_renderer_rejects_invalid_action_event_combinations(self):
        for kind, action in (("Interrupt", "continue"), ("PostToolUse", "deny"),
                             ("PreToolUse", "continue"), ("Stop", "deny"),
                             ("SessionStart", "context"), ("Stop", "unknown"),
                             ([], "pass"), ("Stop", [])):
            with self.subTest(kind=kind, action=action), self.assertRaises(startup.StartupError):
                self.result(kind, action)
        for reason in (None, [], "", "\0"):
            with self.subTest(reason=reason), self.assertRaises(startup.StartupError):
                self.result("PreToolUse", "deny", reason)


class OnboardingDispatcherTests(unittest.TestCase):
    def test_onboarding_routes_before_enrollment_and_returns_bounded_json_errors(self):
        for args, raw in ((["onboard", "inspect", "--cwd", "/", "--plan-dir", "/uncreated"], b"{}"),
                          (["onboard", "plan", "--plan-dir", "/uncreated"], b"{}"),
                          (["onboard", "inspect"], b"{}"),
                          (["onboard", "plan", "--plan-dir", "/uncreated"], b'{"x":NaN}')):
            with self.subTest(args=args):
                result = subprocess.run([sys.executable, "-I", "-B", str(PACKAGE / "scripts/workflow.py"),
                    *args], input=raw, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stderr, b"")
                report = json.loads(result.stdout)
                self.assertFalse(report["ok"])
                self.assertNotIn("enrolled", report["error"])

    def test_inspect_and_plan_work_without_enrollment_and_never_activate_runtime(self):
        from test_onboarding import OnboardingTests
        fixture = OnboardingTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        def invoke(action, request):
            args = ["onboard", action, "--plan-dir", str(fixture.directory)]
            if action == "inspect":
                args.extend(["--cwd", str(fixture.repo)])
            result = subprocess.run([sys.executable, "-I", "-B", str(PACKAGE / "scripts/workflow.py"),
                *args], input=json.dumps(request).encode(), capture_output=True, timeout=5)
            self.assertEqual(result.stderr, b"")
            return result.returncode, json.loads(result.stdout)
        code, report = invoke("inspect", fixture.record)
        self.assertEqual(code, 2)
        self.assertEqual(report["status"], "draft")
        code, report = invoke("plan", fixture.proposal(1))
        self.assertEqual(code, 0, report)
        self.assertEqual(report["status"], "ready_for_review")
        for field, value in (("dependencies", [{}]), ("id", [])):
            malformed = fixture.proposal(report["revision"])
            malformed["actions" if field == "dependencies" else "decisions"] = ([{
                **malformed["actions"][0], field: value}] if field == "dependencies" else [{"id": value}])
            code, failure = invoke("plan", malformed)
            self.assertEqual(code, 1, failure)
            self.assertFalse(failure["ok"])
        (fixture.directory / "plan.json").write_text('{"schema_version":1,"revision":2}')
        code, failure = invoke("inspect", fixture.record)
        self.assertEqual(code, 1, failure)
        self.assertFalse(failure["ok"])
        self.assertFalse((fixture.repo / startup.PROJECT_FILE).exists())
        self.assertFalse(any(fixture.base.rglob("*.sqlite3")))


if __name__ == "__main__":
    unittest.main()
