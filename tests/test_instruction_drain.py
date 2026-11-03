"""Execute the actual documented native loader, with real reader subprocesses."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


class InstructionDrainTests(unittest.TestCase):
    def test_helper_bytes_participate_in_existing_runtime_pins(self):
        from runtime import state
        package = state.PACKAGE
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = set(state._runtime_sources()) | {package / "scripts/drain_instructions.js"}
            for source in sources:
                target = root / source.relative_to(package)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            with patch.object(state, "PACKAGE", root):
                before = state.runtime_fingerprint()
                (root / "scripts/drain_instructions.js").write_text("async function drainInstructions() { return {complete:true}; }\n")
                self.assertNotEqual(before, state.runtime_fingerprint())

    def test_native_bootstrap_delivery_and_failure_boundaries(self):
        self.assertIsNotNone(shutil.which("node"), "Native loader verification requires Node")
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(["node", str(root / "tests/instruction_drain.cjs")],
                                cwd=root, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("native drain cases passed", result.stdout)
