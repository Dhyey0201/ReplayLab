from pathlib import Path
import unittest
from replaylab_tools.compare import evaluate
from replaylab_tools.generate import generate

CANDIDATE = "_build/default/bin/main.exe"


class DifferentialTests(unittest.TestCase):
    def test_golden(self):
        self.assertIsNone(
            evaluate(
                CANDIDATE,
                Path("fixtures/golden/walkthrough.jsonl")
                .read_bytes()
                .splitlines(keepends=True),
                "golden",
            )["difference"]
        )

    def test_twenty_seeds(self):
        for seed in range(20):
            records, _ = generate("balanced", seed, 1000)
            result = evaluate(CANDIDATE, records, candidate_args=["--validate"])
            self.assertIsNone(result["difference"], (seed, result["difference"]))

    def test_protocol_corpus(self):
        from test_reference import new
        import json

        records = [
            b"\xff\n",
            b"\n",
            b"NaN\n",
            b'{"a":1,"a":2}\n',
            b"[]\n",
            b"x" * 20000 + b"\n",
        ]
        for field, values in {
            "schema_version": [True, 1.0, 2, None],
            "quantity": ["0", "01", "-1", "1e2", "1000000001", 1, None],
            "side": ["BUY", "", False],
            "client_id": ["a b", "é", "", None],
        }.items():
            for value in values:
                c = new(1)
                c[field] = value
                records.append(json.dumps(c).encode() + b"\n")
        records.append(json.dumps(new(1)).encode())
        self.assertIsNone(evaluate(CANDIDATE, records)["difference"])

    def test_hand_worked_variant_corpus(self):
        from test_reference import new, cancel
        from replaylab_ref.codec import canonical

        cases = []
        for side, opposite, limit in [("sell", "buy", 103), ("buy", "sell", 99)]:
            cases.append(
                [new(i, side, p, 2) for i, p in enumerate([100, 102, 101])]
                + [new(4, opposite, limit, 8)]
            )
        for target in range(3):
            cases.append(
                [new(i) for i in range(3)]
                + [
                    cancel(5, f"o{target}"),
                    new(6, "buy", 100, 11),
                    new(7, "buy", 100, 1),
                ]
            )
        cases.append(
            [
                cancel(9, "o0"),
                new(0),
                new(0, client="b"),
                cancel(9, "o0"),
                new(1, "buy", 100, 20),
                new(0),
            ]
        )
        for commands in cases:
            self.assertIsNone(
                evaluate(
                    CANDIDATE,
                    [canonical(c) + b"\n" for c in commands],
                    candidate_args=["--validate"],
                )["difference"]
            )
