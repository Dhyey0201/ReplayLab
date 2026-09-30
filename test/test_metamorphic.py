import json
from pathlib import Path
import unittest
from replaylab_ref.codec import canonical
from replaylab_tools.compare import evaluate


class MetamorphicTests(unittest.TestCase):
    def test_price_translation_and_identity_renaming(self):
        records = (
            Path("fixtures/golden/walkthrough.jsonl")
            .read_bytes()
            .splitlines(keepends=True)
        )
        base = evaluate("_build/default/bin/main.exe", records)
        self.assertIsNone(base["difference"])

        def transform(value, kind):
            if isinstance(value, list):
                return [transform(x, kind) for x in value]
            if isinstance(value, dict):
                return {
                    k: str(int(v) + 50)
                    if kind == "prices" and k == "price_ticks"
                    else "renamed-" + v
                    if kind == "identities" and k in {"client_id", "order_id"}
                    else transform(v, kind)
                    for k, v in value.items()
                }
            return value

        for kind in ("prices", "identities"):
            with self.subTest(kind=kind):
                changed = [
                    canonical(transform(json.loads(r), kind)) + b"\n" for r in records
                ]
                result = evaluate("_build/default/bin/main.exe", changed)
                self.assertIsNone(result["difference"])
                self.assertEqual(
                    result["candidate"], transform(base["candidate"], kind)
                )
