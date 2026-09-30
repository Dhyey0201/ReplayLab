import json
from pathlib import Path
import tempfile
import unittest
from jsonschema import Draft202012Validator
from replaylab_tools.shrink import shrink
from replaylab_tools.compare import save_comparison
from replaylab_tools.disturbance import disturbance_check


class ControllerTests(unittest.TestCase):
    def test_crash_timeout_and_invalid_output_keep_artifacts(self):
        for script, status in [
            ("exit 7", "candidate_crash"),
            ("exec sleep 3", "timeout"),
            ("echo invalid", "invalid_candidate_output"),
        ]:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                candidate = root / "candidate"
                candidate.write_text("#!/bin/sh\n" + script + "\n")
                candidate.chmod(0o755)
                workload = root / "input"
                workload.write_bytes(b"{}\n")
                report = save_comparison(
                    candidate, workload, "errors", root / "result", timeout=1
                )
                self.assertEqual(report["status"], status)
                schema = json.loads(Path("schemas/v1.json").read_bytes())
                Draft202012Validator(
                    dict(schema, **{"$ref": "#/$defs/run_manifest"})
                ).validate(report)
                diff = json.loads((root / "result/difference.json").read_bytes())
                Draft202012Validator(
                    dict(schema, **{"$ref": "#/$defs/difference"})
                ).validate(diff)
                if status == "timeout":
                    with self.assertRaisesRegex(ValueError, "not semantic"):
                        shrink(root / "result", root / "reduced")
                for name in (
                    "workload.jsonl",
                    "reference.jsonl",
                    "candidate.jsonl",
                    "candidate.stderr",
                    "difference.json",
                    "manifest.json",
                ):
                    self.assertTrue((root / "result" / name).exists())

    def test_delays_drop_and_duplicate_preserve_executed_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schedule = root / "schedule.json"
            schedule.write_text(
                json.dumps(
                    {
                        "disturbances": [
                            {
                                "attempt": 1,
                                "request_delay_ticks": 3,
                                "response_delay_ticks": 5,
                            },
                            {"attempt": 2, "drop_response": True, "duplicates": 1},
                        ]
                    }
                )
            )
            report = disturbance_check(
                "_build/default/bin/main.exe",
                "fixtures/golden/walkthrough.jsonl",
                schedule,
                root / "result",
            )
            self.assertEqual(report["status"], "agreement")
            self.assertEqual(report["admission_order"][:2], ["2", "2"])
            executions = [
                json.loads(x)
                for x in (root / "result/executions.jsonl").read_text().splitlines()
            ]
            self.assertEqual(
                executions[0]["response"]["events"], executions[1]["response"]["events"]
            )
            self.assertEqual(int(report["admissions"]) - 1, int(report["delivered"]))
