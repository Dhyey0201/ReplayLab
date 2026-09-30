import json
from pathlib import Path
import tempfile
import unittest
from jsonschema import Draft202012Validator
from replaylab_ref.codec import canonical
from replaylab_tools.compare import evaluate, save_comparison
from replaylab_tools.shrink import shrink
from replaylab_tools.generate import generate
from test_reference import new, cancel

MUTANT = "_build/default/test/engine/test_engine.exe"
CORRECT = "_build/default/bin/main.exe"


class ShrinkTests(unittest.TestCase):
    def test_all_mutants_detected(self):
        cases = {
            "lifo": [new(0), new(1), new(2, "buy", quantity=1)],
            "incoming-price": [new(0), new(1, "buy", 101, 1)],
            "middle-cancel": [new(0), new(1), new(2), cancel(3, "o1")],
            "missing-dedupe": [new(0), new(0)],
        }
        for mutant, commands in cases.items():
            records = [canonical(c) + b"\n" for c in commands]
            self.assertIsNotNone(
                evaluate(MUTANT, records, candidate_args=["--mutant", mutant])[
                    "difference"
                ],
                mutant,
            )
            self.assertIsNone(evaluate(CORRECT, records)["difference"])

    def test_generated_failure_reduced_and_validated(self):
        with tempfile.TemporaryDirectory(prefix="replaylab-shrink-") as tmp:
            root = Path(tmp)
            records, _ = generate("balanced", 42, 500)
            # Guaranteed FIFO witness follows generated noise; the first failure may be earlier.
            records += [
                canonical(new(900 + i, "sell", 100, quantity=i + 2, client="witness"))
                + b"\n"
                for i in range(2)
            ]
            records += [
                canonical(new(902, "buy", 100, quantity=1, client="witness")) + b"\n"
            ]
            workload = root / "source.jsonl"
            workload.write_bytes(b"".join(records))
            manifest = save_comparison(
                MUTANT, workload, "shrink", root / "failure", ["--mutant", "lifo"]
            )
            self.assertEqual(manifest["status"], "mismatch")
            report = shrink(root / "failure", root / "reduced", 300, 60)
            schema = json.loads(Path("schemas/v1.json").read_bytes())
            Draft202012Validator(
                dict(schema, **{"$ref": "#/$defs/shrink_report"})
            ).validate(report)
            self.assertTrue(report["validation_passed"])
            self.assertLess(int(report["final_commands"]), len(records))
            self.assertEqual(report["minimality"], "1-minimal under deletion")
            reduced = (
                (root / "reduced/workload.jsonl").read_bytes().splitlines(keepends=True)
            )
            self.assertIsNone(evaluate(CORRECT, reduced, "shrink")["difference"])

    def test_crash_shrinking_retargets_request_key(self):
        from replaylab_tools.crash import crash_check, CrashMismatch

        with tempfile.TemporaryDirectory(prefix="replaylab-crash-reduction-") as tmp:
            root = Path(tmp)
            commands = [
                new(90, "buy", 1),
                new(0, "sell", 100),
                new(1, "buy", 101, 1),
                new(99, "sell", 200),
            ]
            workload = root / "input.jsonl"
            workload.write_bytes(b"".join(canonical(c) + b"\n" for c in commands))
            plan = {
                "hook": "after_sync_before_apply",
                "target_request": {"client_id": "a", "request_id": "r1"},
                "candidate_args": ["--mutant", "incoming-price"],
            }
            with self.assertRaises(CrashMismatch):
                crash_check(MUTANT, workload, plan, root / "failure")
            report = shrink(root / "failure", root / "reduced", 100, 30)
            schema = json.loads(Path("schemas/v1.json").read_bytes())
            Draft202012Validator(
                dict(schema, **{"$ref": "#/$defs/shrink_report"})
            ).validate(report)
            self.assertTrue(report["validation_passed"])
            self.assertEqual(report["final_commands"], "2")
            self.assertEqual(
                json.loads((root / "reduced/reproduction/schedule.json").read_bytes())[
                    "target_request"
                ],
                plan["target_request"],
            )
