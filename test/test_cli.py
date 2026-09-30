import json
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from replaylab_ref.codec import canonical
from replaylab_tools.compare import Reader
from test_reference import new

ENGINE = "_build/default/bin/main.exe"


class CLITests(unittest.TestCase):
    def test_usage_and_protocol_exit_codes(self):
        for args in [
            ["run", "--max-orders", "nope"],
            ["run", "--mode", "bad"],
            ["unknown"],
        ]:
            result = subprocess.run([ENGINE, *args], capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, b"")
        result = subprocess.run(
            [ENGINE, "run", "--session-id", "s", "--fail-on-protocol-error"],
            input=b"\n",
            capture_output=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["result"]["code"], "PROTOCOL_ERROR")

    def test_sigint_closes_durable_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session"
            child = subprocess.Popen(
                [
                    ENGINE,
                    "stream",
                    "--mode",
                    "durable",
                    "--session-id",
                    "s",
                    "--session-dir",
                    str(path),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            reader = Reader(child.stdout, 5)
            try:
                child.stdin.write(canonical(new(0)) + b"\n")
                child.stdin.flush()
                self.assertEqual(json.loads(reader.line())["durability"], "synced")
                child.send_signal(signal.SIGINT)
                child.wait(timeout=5)
                self.assertEqual(child.returncode, 0)
            finally:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=5)
                reader.close()
            result = subprocess.run(
                [ENGINE, "verify-log", "--session-dir", str(path)],
                check=True,
                capture_output=True,
                timeout=5,
            )
            self.assertEqual(json.loads(result.stdout)["valid_frames"], "1")
