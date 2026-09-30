import json
from pathlib import Path
import unittest
from jsonschema import Draft202012Validator
from replaylab_ref.engine import Session
from replaylab_ref.codec import canonical, digest


class SchemaTests(unittest.TestCase):
    def test_schema_and_golden_variants(self):
        schema = json.loads(Path("schemas/v1.json").read_bytes())
        Draft202012Validator.check_schema(schema)

        def validate(name, value):
            Draft202012Validator(dict(schema, **{"$ref": f"#/$defs/{name}"})).validate(
                value
            )

        session = Session("golden")
        for raw in Path("fixtures/golden/walkthrough.jsonl").read_bytes().splitlines():
            validate("request", json.loads(raw))
            response = session.handle(raw)
            validate("response", response)
            for event in response["events"]:
                validate("event", event)
        validate("response", session.handle(b""))
        validate("session_state", session.session_state())
        validate("book_state", session.book_state())
        vector = json.loads(Path("fixtures/golden/canonical.json").read_bytes())
        self.assertEqual(canonical(vector["value"]).decode(), vector["canonical_ascii"])
        self.assertEqual(digest(vector["value"]), vector["sha256"])

    def test_selected_failure_reports_and_benchmark_samples(self):
        schema = json.loads(Path("schemas/v1.json").read_bytes())
        for path in Path("fixtures/regressions/fifo").glob("*.json"):
            entry = {
                "difference.json": "difference",
                "report.json": "shrink_report",
            }.get(path.name)
            if entry:
                Draft202012Validator(
                    dict(schema, **{"$ref": f"#/$defs/{entry}"})
                ).validate(json.loads(path.read_bytes()))
