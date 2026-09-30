import io
import json
from pathlib import Path
import random
import unittest

from replaylab_ref.codec import canonical, digest, lines, parse, MAX_INT
from replaylab_ref.engine import Config, Session


def new(i, side="sell", price=100, quantity=10, client="a", **extra):
    return dict(
        schema_version=1,
        type="new",
        client_id=client,
        request_id=f"r{i}",
        instrument="SIM",
        order_id=f"o{i}",
        side=side,
        price_ticks=str(price),
        quantity=str(quantity),
        **extra,
    )


def cancel(i, order, client="a"):
    return dict(
        schema_version=1,
        type="cancel",
        client_id=client,
        request_id=f"r{i}",
        instrument="SIM",
        order_id=order,
    )


class ReferenceTests(unittest.TestCase):
    def send(self, s, c):
        r = s.handle(canonical(c))
        s.assert_invariants()
        return r

    def test_golden_hand_calculated(self):
        s = Session("golden")
        responses = [
            s.handle(line)
            for line in Path("fixtures/golden/walkthrough.jsonl")
            .read_bytes()
            .splitlines()
        ]
        self.assertEqual(
            [r["seq"] for r in responses],
            ["1", "2", "3", "4", "3", "4", "5", "6", None],
        )
        self.assertEqual([e["quantity"] for e in responses[2]["events"]], ["10", "2"])
        self.assertEqual(
            [e["price_ticks"] for e in responses[2]["events"]], ["100", "100"]
        )
        self.assertEqual(
            [e["resting"]["order_id"] for e in responses[2]["events"]], ["A1", "B1"]
        )
        self.assertEqual(responses[3]["events"][0]["cancelled_quantity"], "5")
        self.assertEqual(responses[4]["events"], responses[2]["events"])
        self.assertEqual(responses[5]["result"], responses[3]["result"])
        self.assertEqual(
            [r["result"]["code"] for r in responses[6:]],
            ["ORDER_NOT_ACTIVE", "ORDER_ID_REUSED", "IDEMPOTENCY_CONFLICT"],
        )
        self.assertEqual(s.book_state(), {"asks": [], "bids": []})
        self.assertEqual(
            (s.next_seq, s.event_count, len(s.requests), len(s.orders)), (7, 3, 6, 3)
        )
        s.assert_invariants()

    def test_sweeps_both_sides_residual_and_price_priority(self):
        for side, opposite in [("sell", "buy"), ("buy", "sell")]:
            s = Session("s")
            for i, p in enumerate([100, 102, 101]):
                self.send(s, new(i, side, p, 2))
            r = self.send(s, new(3, opposite, 103 if opposite == "buy" else 99, 8))
            self.assertEqual(
                [int(e["price_ticks"]) for e in r["events"]],
                [100, 101, 102] if opposite == "buy" else [102, 101, 100],
            )
            self.assertEqual(r["result"]["remaining_quantity"], "2")

    def test_cancellation_positions_and_fifo_partial(self):
        for target in range(3):
            s = Session("s")
            for i in range(3):
                self.send(s, new(i))
            self.send(s, cancel(5, f"o{target}"))
            r = self.send(s, new(6, "buy", quantity=11))
            self.assertEqual(
                [e["resting"]["order_id"] for e in r["events"]],
                [f"o{i}" for i in range(3) if i != target],
            )
            r = self.send(s, new(7, "buy", quantity=1))
            self.assertEqual(
                r["events"][0]["resting"]["order_id"],
                f"o{max(i for i in range(3) if i != target)}",
            )
        s = Session("s")
        self.send(s, new(0))
        self.send(s, cancel(1, "o0"))
        self.assertEqual(s.book_state()["asks"], [])

    def test_scope_rejected_retry_and_original_response(self):
        s = Session("s")
        rejected = cancel(9, "o0")
        first = self.send(s, rejected)
        original = self.send(s, new(0))
        self.send(s, new(0, client="b"))
        before = s.session_state()
        self.assertEqual(self.send(s, rejected)["result"], first["result"])
        self.assertEqual(s.session_state(), before)
        self.send(s, new(1, "buy", quantity=20))
        self.assertEqual(self.send(s, new(0))["result"], original["result"])

    def test_limits_precedence_and_sequence_exhaustion(self):
        s = Session("s", Config(1, 3))
        self.send(s, new(0))
        c = new(1)
        c["instrument"] = "OTHER"
        self.assertEqual(self.send(s, c)["result"]["code"], "UNKNOWN_INSTRUMENT")
        self.assertEqual(self.send(s, new(2))["result"]["code"], "SESSION_ORDER_LIMIT")
        self.assertEqual(
            self.send(s, new(3))["result"]["code"], "SESSION_REQUEST_LIMIT"
        )
        self.assertTrue(self.send(s, new(0))["duplicate"])
        c = new(0)
        c["quantity"] = "11"
        self.assertEqual(self.send(s, c)["result"]["code"], "IDEMPOTENCY_CONFLICT")
        s = Session("s")
        s.next_seq = MAX_INT
        self.assertEqual(self.send(s, new(0))["seq"], str(MAX_INT))
        self.assertEqual(self.send(s, new(1))["result"]["code"], "SEQUENCE_EXHAUSTED")
        self.assertTrue(self.send(s, new(0))["duplicate"])

    def test_protocol_and_no_mutation(self):
        cases = [
            (b"\xff", "INVALID_UTF8"),
            (b"", "INVALID_JSON"),
            (b'{"a":1,"a":2}', "DUPLICATE_OBJECT_KEY"),
            (b"[]", "WRONG_FIELD_TYPE"),
            (b'{"schema_version":true}', "WRONG_FIELD_TYPE"),
        ]
        for field, value, code in [
            ("price_ticks", "01", "INVALID_NUMERIC_ENCODING"),
            ("quantity", "0", "INVALID_NUMERIC_ENCODING"),
            ("quantity", "1000000001", "NUMERIC_OUT_OF_RANGE"),
            ("side", "BUY", "INVALID_SIDE"),
            ("client_id", "a b", "INVALID_ID"),
            ("quantity", 10, "WRONG_FIELD_TYPE"),
            ("schema_version", 2, "UNSUPPORTED_SCHEMA_VERSION"),
        ]:
            c = new(0)
            c[field] = value
            cases.append((json.dumps(c).encode(), code))
        c = new(0)
        c["extra"] = 1
        cases.append((json.dumps(c).encode(), "UNKNOWN_FIELD"))
        c = new(0)
        del c["side"]
        cases.append((json.dumps(c).encode(), "MISSING_FIELD"))
        s = Session("s")
        for raw, code in cases:
            before = s.session_state()
            self.assertEqual(s.handle(raw)["result"]["subcode"], code)
            self.assertEqual(s.session_state(), before)
        self.assertEqual(
            parse(canonical(new(0, price=10**9, quantity=10**9)))["quantity"],
            "1000000000",
        )
        raw = b"x" * 20000 + b"\n" + canonical(new(0))
        records = list(lines(io.BytesIO(raw)))
        self.assertEqual(len(records), 2)
        self.assertEqual(s.handle(records[0])["result"]["subcode"], "OVERSIZED_LINE")
        self.assertEqual(s.handle(records[1])["seq"], "1")

    def test_canonical_control_bytes_and_hash(self):
        self.assertEqual(
            canonical({"z": [], "a": '\n\t\x00"\\', "b": None}),
            b'{"a":"\\u000a\\u0009\\u0000\\"\\\\","b":null,"z":[]}',
        )
        self.assertEqual(
            digest({}),
            "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
        )

    def test_seeded_conservation_retry_metamorphism(self):
        for seed in range(20):
            rng = random.Random(seed)
            s = Session("s")
            baseline = Session("s")
            for i in range(100):
                c = new(
                    i,
                    rng.choice(["buy", "sell"]),
                    rng.randrange(98, 103),
                    rng.randrange(1, 20),
                )
                self.send(s, c)
                self.send(baseline, c)
                if rng.randrange(3) == 0:
                    before = s.session_state()
                    self.send(s, c)
                    self.assertEqual(s.session_state(), before)
            self.assertEqual(s.session_state(), baseline.session_state())
