"""Disposable checkout tests; no client, model, network or real enrollment."""

import copy
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from runtime.adapters import claude_code, codex
from runtime.startup import MAX_INPUT, PROJECT_FILE, checkout, orient, policy_digest
from scripts.validate import validate


PACKAGE = Path(__file__).resolve().parents[1]


class JsonBoundaryTests(unittest.TestCase):
    def test_internal_json_bound_preserves_external_cap_and_strict_parser(self):
        import inspect
        from runtime.startup import json_object, StartupError
        from runtime.evidence import MAX_ARTIFACT
        self.assertIn('limit', inspect.signature(json_object).parameters)
        raw = b'{"value":"' + b'x' * MAX_INPUT + b'"}'
        with self.assertRaises(StartupError):
            json_object(raw)
        self.assertEqual(len(json_object(raw, limit=MAX_ARTIFACT)['value']), MAX_INPUT)
        unicode_raw = '{"value":"' + 'é' * (MAX_INPUT // 2) + '"}'
        with self.assertRaises(StartupError):
            json_object(unicode_raw)
        with self.assertRaises(StartupError):
            json_object(b'{"value":"' + b'x' * MAX_ARTIFACT + b'"}', limit=MAX_ARTIFACT)
        for invalid in (b'{"a":1,"a":2}', b'{"a":{"b":1,"b":2}}', b'{"a":NaN}', b'{"a":Infinity}', b'{"a":-Infinity}'):
            for bound in (MAX_INPUT, MAX_ARTIFACT):
                with self.subTest(invalid=invalid, bound=bound), self.assertRaises(StartupError):
                    json_object(invalid, limit=bound)


class StartupTests(unittest.TestCase):
    client = "codex"
    adapter = codex
    other_client = "claude-code"
    root_variable = "PLUGIN_ROOT"
    manifest_directory = ".codex-plugin"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vibe startup ")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.repo = self.base / "project"
        self.repo.mkdir()
        self.git(self.repo, "init", "-q")
        self.payload = {"hook_event_name": "SessionStart", "session_id": "fixture-session",
                        "source": "startup", "cwd": str(self.repo), "model": "unchanged-model",
                        "permission_mode": "default"}

    def git(self, root, *args):
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        return subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull,
                               "-c", "commit.gpgsign=false", "-c", "init.templateDir=",
                               "-C", str(root), *args], check=True, env=env,
                              capture_output=True, text=True, timeout=5).stdout.strip()

    def enroll(self, root=None, **updates):
        root = root or self.repo
        identity = checkout(root)
        record = {"schema_version": 1, "project_id": "fixture-project",
                  "repository_root": str(identity[0]), "git_common_dir": str(identity[1]),
                  "clients": [self.client], "policy_digest": policy_digest(PACKAGE)}
        record.update(updates)
        path = root / PROJECT_FILE
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(record))
        return path

    def invoke(self, raw=None, package=PACKAGE, payload=None, env=None):
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(package / "scripts/workflow.py"), self.client, "SessionStart"],
            input=raw if raw is not None else json.dumps(payload or self.payload).encode(),
            cwd=self.repo, capture_output=True, timeout=5, env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stderr, b"")
        return json.loads(result.stdout) if result.stdout else None

    def assert_diagnostic(self, output):
        self.assertIn("startup unavailable", output["systemMessage"])
        self.assertNotIn("continue", output)
        self.assertNotIn("permissionDecision", output.get("hookSpecificOutput", {}))
        self.assertNotIn("applies to this enrolled checkout", str(output))

    def test_unenrolled_is_silent_and_read_only(self):
        before = sorted(str(p.relative_to(self.repo)) for p in self.repo.rglob("*"))
        self.assertIsNone(self.invoke())
        self.assertEqual(before, sorted(str(p.relative_to(self.repo)) for p in self.repo.rglob("*")))

    def test_broken_git_is_silent_until_enrollment_exists(self):
        self.enroll()
        shutil.rmtree(self.repo / ".git")
        (self.repo / ".git").write_text("gitdir: /missing-vibe-fixture\n")
        self.assert_diagnostic(self.invoke())
        shutil.rmtree(self.repo / PROJECT_FILE.parent)
        self.assertIsNone(self.invoke())

    def test_fixture_git_ignores_inherited_hooks_and_selectors(self):
        hooks = self.base / "external hooks"
        hooks.mkdir()
        marker = self.base / "hook-ran"
        hook = hooks / "pre-commit"
        hook.write_text("#!/bin/sh\nprintf touched > " + shlex.quote(str(marker)) + "\n")
        hook.chmod(0o700)
        config = self.base / "external-config"
        config.write_text('[core]\n hooksPath = "' + str(hooks) + '"\n')
        with patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(config), "GIT_DIR": "/missing-vibe-fixture"}):
            self.git(self.repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                     "commit", "--allow-empty", "-qm", "isolated fixture")
        self.assertFalse(marker.exists())

    def test_enrolled_context_is_short_local_and_read_only(self):
        record = self.enroll()
        before = record.read_bytes()
        output = self.invoke()
        self.assertEqual(set(output), {"hookSpecificOutput"})
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertLessEqual(len(context.split()), 150)
        for path in (PACKAGE / "clients" / f"{self.client}.md", PACKAGE / "policies/00-index.md", record):
            self.assertIn(json.dumps(str(path)), context)
        self.assertNotIn("https://", context)
        self.assertEqual(record.read_bytes(), before)

    def test_nested_directory_and_symlink_resolve_same_checkout(self):
        self.enroll()
        nested = self.repo / "src/deep"
        nested.mkdir(parents=True)
        alias = self.base / "alias"
        alias.symlink_to(nested, target_is_directory=True)
        for cwd in (nested, alias):
            with self.subTest(cwd=cwd):
                self.assertIn("hookSpecificOutput", self.invoke(payload={**self.payload, "cwd": str(cwd)}))

    def test_neighbor_and_nested_repository_do_not_inherit_enrollment(self):
        self.enroll()
        for other in (self.base / "neighbor", self.repo / "nested-repo"):
            other.mkdir()
            self.git(other, "init", "-q")
            with self.subTest(cwd=other):
                self.assertIsNone(self.invoke(payload={**self.payload, "cwd": str(other)}))

    def test_parent_folder_does_not_select_an_enrolled_child(self):
        self.enroll()
        self.assertIsNone(self.invoke(payload={**self.payload, "cwd": str(self.base)}))

    def test_linked_worktree_requires_its_own_scope(self):
        self.enroll()
        self.git(self.repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "--allow-empty", "-qm", "fixture")
        worktree = self.base / "linked"
        self.git(self.repo, "worktree", "add", "--detach", str(worktree))
        payload = {**self.payload, "cwd": str(worktree)}
        self.assertIsNone(self.invoke(payload=payload))
        self.enroll(worktree)
        self.assertEqual(checkout(worktree)[1], checkout(self.repo)[1])
        self.assertIn("hookSpecificOutput", self.invoke(payload=payload))
        shutil.copyfile(self.repo / PROJECT_FILE, worktree / PROJECT_FILE)
        self.assert_diagnostic(self.invoke(payload=payload))

    def test_copied_record_does_not_enroll_separate_clone(self):
        self.enroll()
        clone = self.base / "separate"
        clone.mkdir()
        self.git(clone, "init", "-q")
        (clone / PROJECT_FILE.parent).mkdir()
        shutil.copyfile(self.repo / PROJECT_FILE, clone / PROJECT_FILE)
        self.assert_diagnostic(self.invoke(payload={**self.payload, "cwd": str(clone)}))

    def test_inherited_git_environment_cannot_redirect_scope(self):
        self.enroll()
        unrelated = self.base / "unrelated"
        unrelated.mkdir()
        self.git(unrelated, "init", "-q")
        env = {**os.environ, "GIT_DIR": str(self.repo / ".git"), "GIT_WORK_TREE": str(self.repo)}
        self.assertIsNone(self.invoke(payload={**self.payload, "cwd": str(unrelated)}, env=env))

    def test_other_selected_client_is_silent(self):
        self.enroll(clients=[self.other_client])
        self.assertIsNone(self.invoke())

    def test_superset_host_hints_cannot_extend_native_enrollment(self):
        self.enroll()
        other = self.base / "other"
        other.mkdir()
        self.git(other, "init", "-q")
        env = {**os.environ, "SUPERSET_WORKSPACE_ID": "fixture", "SUPERSET_WORKSPACE_PATH": str(self.repo),
               "SUPERSET_ROOT_PATH": str(self.repo), "SUPERSET_TERMINAL_ID": "fixture"}
        self.assertIsNone(self.invoke(payload={**self.payload, "cwd": str(other)}, env=env))
        self.assertIn("hookSpecificOutput", self.invoke(env=env))
        self.enroll(clients=["superset"])
        self.assertIsNone(self.invoke(env=env))

    def test_invalid_or_stale_enrollment_is_not_activation(self):
        for update in ({"schema_version": True}, {"schema_version": 2}, {"clients": "codex"},
                       {"project_id": "injected\ntext"}, {"git_common_dir": "/wrong"},
                       {"policy_digest": "0" * 64}):
            with self.subTest(update=update):
                self.enroll(**update)
                self.assert_diagnostic(self.invoke())

    def test_missing_broken_link_and_special_records_do_not_hang(self):
        path = self.enroll()
        path.unlink()
        self.assert_diagnostic(self.invoke())
        path.symlink_to(self.base / "missing")
        self.assert_diagnostic(self.invoke())
        path.unlink()
        os.mkfifo(path)
        self.assert_diagnostic(self.invoke())

    def test_record_symlink_and_directory_symlink_are_rejected(self):
        path = self.enroll()
        outside = self.base / "outside.json"
        path.rename(outside)
        path.symlink_to(outside)
        self.assert_diagnostic(self.invoke())
        path.unlink()
        path.parent.rmdir()
        path.parent.symlink_to(self.base, target_is_directory=True)
        self.assert_diagnostic(self.invoke())

    def test_invalid_json_is_bounded_and_does_not_echo_input(self):
        for raw in (b"[]", b"null", b'{"x":1,"x":2}', b'{"x":NaN}', b"\xff",
                    b"x" * (MAX_INPUT + 1), b"[" * 2000, b"PRIVATE_SENTINEL"):
            with self.subTest(raw=raw[:20]):
                output = self.invoke(raw=raw)
                self.assert_diagnostic(output)
                self.assertNotIn("PRIVATE_SENTINEL", str(output))

    def test_invalid_native_fields_are_diagnostics(self):
        for update in ({"source": "unknown"}, {"source": {}}, {"cwd": "relative"},
                       {"cwd": str(self.base / "missing")}, {"session_id": ""},
                       {"hook_event_name": "Stop"}, {"model": 12}):
            with self.subTest(update=update):
                self.assert_diagnostic(self.invoke(payload={**self.payload, **update}))

    def test_every_start_transition_orients_without_mutating_settings(self):
        self.enroll()
        for source in self.adapter.SOURCES:
            payload = {**self.payload, "source": source}
            before = copy.deepcopy(payload)
            event = self.adapter.normalize(payload)
            self.assertEqual(event.model, payload["model"])
            self.assertEqual(event.permission_mode, payload["permission_mode"])
            self.assertIn("hookSpecificOutput", self.invoke(payload=payload))
            self.assertEqual(payload, before)

    def test_absent_observations_remain_unknown(self):
        payload = {key: value for key, value in self.payload.items() if key not in ("model", "permission_mode")}
        event = self.adapter.normalize(payload)
        self.assertIsNone(event.model)
        self.assertIsNone(event.permission_mode)

    def test_git_timeout_has_no_activation(self):
        self.enroll()
        with patch("runtime.startup.subprocess.run", side_effect=subprocess.TimeoutExpired("git", 2)):
            with self.assertRaises(subprocess.TimeoutExpired):
                orient(self.adapter.normalize(self.payload), PACKAGE)

    def test_missing_installed_files_or_modified_policies_are_diagnostics(self):
        self.enroll()
        package = self.base / "installed plugin"
        shutil.copytree(PACKAGE, package, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        client = package / "clients" / f"{self.client}.md"
        client.unlink()
        self.assert_diagnostic(self.invoke(package=package))
        shutil.copyfile(PACKAGE / "clients" / f"{self.client}.md", client)
        policy = package / "policies/01-project-scope.md"
        policy.write_text(policy.read_text() + "\nChanged policy.\n")
        self.assert_diagnostic(self.invoke(package=package))

    def test_manifest_command_handles_spaces_and_hostile_python_environment(self):
        self.enroll()
        package = self.base / "plugin with spaces"
        shutil.copytree(PACKAGE, package, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        (self.repo / "json.py").write_text("raise RuntimeError('project import')\n")
        (self.repo / "sitecustomize.py").write_text("raise RuntimeError('environment import')\n")
        command = json.loads((package / "hooks" / f"{self.client}.json").read_text())["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        result = subprocess.run(["/bin/sh", "-c", command], cwd=self.repo,
                                input=json.dumps(self.payload), capture_output=True, text=True, timeout=5,
                                env={**os.environ, self.root_variable: str(package), "PYTHONPATH": str(self.repo)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("hookSpecificOutput", json.loads(result.stdout))

    def test_package_validator_rejects_missing_or_escaping_hook_path(self):
        package = self.base / "package"
        shutil.copytree(PACKAGE, package, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        self.assertEqual(validate(package)["validation"], "passed")
        path = package / self.manifest_directory / "plugin.json"
        manifest = json.loads(path.read_text())
        for value in ("./missing.json", "../hooks/codex.json", "./../outside.json"):
            manifest["hooks"] = value
            path.write_text(json.dumps(manifest))
            with self.subTest(value=value), self.assertRaises((ValueError, OSError)):
                validate(package)

    def test_package_validator_rejects_shadowing_root_manifest(self):
        package = self.base / "package"
        shutil.copytree(PACKAGE, package, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        (package / "plugin.json").write_text('{"name":"vibe-coding-workflow"}')
        with self.assertRaisesRegex(ValueError, "root manifest hides hooks"):
            validate(package)

    def test_package_validator_rejects_duplicate_claude_hooks(self):
        package = self.base / "package"
        shutil.copytree(PACKAGE, package, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        shutil.copyfile(package / "hooks/claude-code.json", package / "hooks/hooks.json")
        with self.assertRaisesRegex(ValueError, "duplicate Claude"):
            validate(package)

    def test_package_validator_rejects_different_client_versions(self):
        package = self.base / "package"
        shutil.copytree(PACKAGE, package, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        path = package / ".claude-plugin/plugin.json"
        manifest = json.loads(path.read_text())
        manifest["version"] = "999.0.0"
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "same package version"):
            validate(package)

    def test_stale_policy_diagnostic_identifies_the_remedy(self):
        self.enroll(policy_digest="stale")
        self.assertIn("Installed policies differ", self.invoke()["systemMessage"])


class ClaudeStartupTests(StartupTests):
    client = "claude-code"
    adapter = claude_code
    other_client = "codex"
    root_variable = "CLAUDE_PLUGIN_ROOT"
    manifest_directory = ".claude-plugin"


if __name__ == "__main__":
    unittest.main()
