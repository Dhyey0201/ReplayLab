import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from jsonschema import Draft202012Validator
from replaylab_ref.codec import canonical
from test_reference import new, cancel


class BenchmarkTests(unittest.TestCase):
    def test_native_scopes_counts_and_samples(self):
        schema = json.loads(Path("schemas/v1.json").read_bytes())
        validator = Draft202012Validator(
            dict(schema, **{"$ref": "#/$defs/benchmark_sample"})
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workload = root / "workload.jsonl"
            workload.write_bytes(
                b"".join(
                    canonical(c) + b"\n"
                    for c in [new(0), new(1, "buy", 100, 1), cancel(2, "o0")]
                )
            )
            for mode in [
                "book-kernel",
                "memory-session",
                "json-batch",
                "durable-session",
            ]:
                result = json.loads(
                    subprocess.run(
                        [
                            "_build/default/bin/bench.exe",
                            "--mode",
                            mode,
                            "--input",
                            str(workload),
                            "--session-dir",
                            str(root / "session"),
                        ],
                        check=True,
                        capture_output=True,
                        timeout=10,
                    ).stdout
                )
                validator.validate(result)
                self.assertEqual(result["sample_count"], "3")
                self.assertEqual(result["unique_commands"], "3")
                self.assertEqual(result["accepted_orders"], "2")
                self.assertEqual(result["trades"], "1")
                self.assertEqual(result["active_orders"], "0")
                self.assertLessEqual(
                    sum(map(int, result["samples_ns"])), int(result["elapsed_ns"])
                )
