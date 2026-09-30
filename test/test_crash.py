from pathlib import Path
import tempfile
import unittest
from replaylab_tools.crash import crash_check, HOOKS


class CrashTests(unittest.TestCase):
    def test_all_nine_hooks(self):
        with tempfile.TemporaryDirectory(prefix="replaylab-crash-suite-") as tmp:
            for hook in HOOKS:
                result = crash_check(
                    "_build/default/test/engine/test_engine.exe",
                    "fixtures/golden/recovery.jsonl",
                    {"hook": hook, "seq": "3"},
                    Path(tmp) / hook,
                )
                self.assertTrue(result["hook_reached"])
                self.assertTrue(result["final_equal"])

    def test_release_rejects_test_flags(self):
        import subprocess

        result = subprocess.run(
            [
                "_build/default/bin/main.exe",
                "run",
                "--session-id",
                "s",
                "--mutant",
                "lifo",
            ],
            capture_output=True,
        )
        self.assertEqual(result.returncode, 2)
