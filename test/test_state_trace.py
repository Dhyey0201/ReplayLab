from pathlib import Path
import subprocess
import tempfile
import unittest
from replaylab_ref.codec import canonical
from replaylab_ref.engine import Session
from replaylab_tools.generate import generate
from replaylab_tools.compare import evaluate


class StateTraceTests(unittest.TestCase):
    def test_every_attempt_in_tiny_workload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records, _ = generate("balanced", 313, 100)
            source = root / "in"
            source.write_bytes(b"".join(records))
            subprocess.run(
                [
                    "_build/default/bin/main.exe",
                    "run",
                    "--session-id",
                    "trace",
                    "--input",
                    str(source),
                    "--responses",
                    str(root / "responses"),
                    "--state-trace",
                    str(root / "states"),
                    "--validate",
                ],
                check=True,
                timeout=10,
            )
            model = Session("trace")
            for raw, state in zip(
                records, (root / "states").read_bytes().splitlines(), strict=True
            ):
                model.handle(raw)
                self.assertEqual(canonical(model.session_state()), state)

    def test_parser_syntax_precedes_duplicate_keys(self):
        records = [
            b'{"a":1,"a":2}garbage\n',
            b'{"a":1,"a":2,}\n',
            b'{"a":1,"a":2}\n',
            b'"\\ud800"\n',
            b'{"schema_version":1,"type":"new","client_id":"\\ud800"}\n',
            b"[" * 257 + b"0" + b"]" * 257 + b"\n",
            b"1e9999\n",
            b"Infinity\n",
        ]
        self.assertIsNone(
            evaluate("_build/default/bin/main.exe", records)["difference"]
        )
