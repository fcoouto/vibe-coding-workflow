"""Prepared delivery must preserve exact instructions, scope and revisions."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PACKAGE = Path(__file__).resolve().parents[1]
SCRIPT = PACKAGE / "scripts/read_instructions.py"


class PreparedInstructionsTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "Prepared instruction reader is missing")
        spec = importlib.util.spec_from_file_location("prepared_reader", SCRIPT)
        self.reader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.reader)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "clients").mkdir()
        (self.root / "policies").mkdir()
        (self.root / "clients/codex.md").write_text("# Client\nRead applicable contracts.\n")
        self.source = "# Rules\n" + "Preserve Straße and 漢字 exactly.\n" * 900
        (self.root / "policies/rules.md").write_text(self.source)
        (self.root / "policies/unrelated.md").write_text("Do not load this unused procedure.\n")
        self.prepare()

    def prepare(self):
        manifest = self.reader.build_manifest(self.root)
        (self.root / "clients/instruction-map.json").write_text(json.dumps(manifest))

    def test_pages_reconstruct_sources_once_with_complete_utf8_and_bounded_output(self):
        paths = ["clients/codex.md", "policies/rules.md", "policies/rules.md"]
        first = self.reader.load_page(self.root, paths)
        recovered = {path: "" for path in paths}
        for number in range(1, first["pages"] + 1):
            page = self.reader.load_page(self.root, paths, number, first["revision"] if number > 1 else None)
            self.assertLessEqual(len(self.reader.render_page(page).encode()), 9500)
            for section in page["sections"]:
                recovered[section["path"]] += section["text"]
            self.assertNotIn("unused procedure", self.reader.render_page(page))
        self.assertGreater(first["pages"], 1)
        self.assertEqual(recovered["policies/rules.md"], self.source)
        self.assertEqual(recovered["clients/codex.md"], "# Client\nRead applicable contracts.\n")

    def test_source_changes_reject_stale_map_and_prepared_continuation(self):
        paths = ["policies/rules.md"]
        first = self.reader.load_page(self.root, paths)
        (self.root / paths[0]).write_text(self.source + "New mandatory rule.\n")
        with self.assertRaises(ValueError):
            self.reader.load_page(self.root, paths)
        self.prepare()
        with self.assertRaises(ValueError):
            self.reader.load_page(self.root, paths, 2, first["revision"])
        with self.assertRaises(ValueError):
            self.reader.load_page(self.root, paths, 2)

    def test_invalid_selection_and_external_symlink_do_not_read_other_files(self):
        for paths in [[], ["../secret.md"], ["policies/missing.md"], [str(self.root.parent / "secret.md")]]:
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                self.reader.load_page(self.root, paths)
        outside = self.root.parent / (self.root.name + "-secret.md")
        outside.write_text("Private external text")
        self.addCleanup(outside.unlink)
        (self.root / "policies/rules.md").unlink()
        (self.root / "policies/rules.md").symlink_to(outside)
        with self.assertRaises(ValueError):
            self.reader.load_page(self.root, ["policies/rules.md"])

    def test_incomplete_and_overlapping_prepared_ranges_fail_before_delivery(self):
        path = self.root / "clients/instruction-map.json"
        original = json.loads(path.read_text())
        for ranges in [[[1, 2]], [[1, 4], [4, 901]], [[2, 901]], [[1, 9999]]]:
            manifest = json.loads(json.dumps(original))
            manifest["files"]["policies/rules.md"]["ranges"] = ranges
            path.write_text(json.dumps(manifest))
            with self.subTest(ranges=ranges), self.assertRaises(ValueError):
                self.reader.load_page(self.root, ["policies/rules.md"])

    def test_unselected_changed_file_does_not_trigger_read_or_reprepare(self):
        (self.root / "policies/unrelated.md").unlink()
        page = self.reader.load_page(self.root, ["clients/codex.md"])
        self.assertEqual(len(page["sections"]), 1)
        self.assertEqual(page["sections"][0]["text"], "# Client\nRead applicable contracts.\n")

    def test_preparation_rejects_unsplittable_line_instead_of_clipping_it(self):
        (self.root / "policies/rules.md").write_text("漢" * 8000)
        with self.assertRaises(ValueError):
            self.reader.build_manifest(self.root)

    def test_forged_map_cannot_select_non_instruction_package_files(self):
        import hashlib
        private = self.root / "private.txt"
        private.write_text("Private package data\n")
        path = self.root / "clients/instruction-map.json"
        manifest = json.loads(path.read_text())
        manifest["files"]["private.txt"] = dict(sha256=hashlib.sha256(private.read_bytes()).hexdigest(), ranges=[[1, 1]])
        path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            self.reader.load_page(self.root, ["private.txt"])

    def test_internal_symlink_cannot_reclassify_non_instruction_package_data(self):
        private = self.root / "private.txt"
        private.write_text("Private package data\n")
        alias = self.root / "policies/alias.md"
        alias.symlink_to("../private.txt")
        with self.assertRaises(ValueError):
            self.reader.build_manifest(self.root)
        alias.unlink()
        original = self.root / "policies/rules.md"
        original.unlink()
        original.symlink_to("../private.txt")
        with self.assertRaises(ValueError):
            self.reader.load_page(self.root, ["policies/rules.md"])

    def test_malformed_map_has_a_controlled_failure(self):
        for value in [[], None, {"version": 1, "files": []}]:
            (self.root / "clients/instruction-map.json").write_text(json.dumps(value))
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.reader.load_page(self.root, ["clients/codex.md"])

    def test_real_bootstrap_cli_is_bounded_and_package_manifest_is_current(self):
        self.assertEqual(json.loads((PACKAGE / "clients/instruction-map.json").read_text()),
                         self.reader.build_manifest(PACKAGE))
        result = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "bootstrap"],
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLessEqual(len(result.stdout), 9500)
        self.assertIn(b"clients/codex.md", result.stdout)
        self.assertNotIn(b"runtime.sqlite3", result.stdout)


if __name__ == "__main__":
    unittest.main()
