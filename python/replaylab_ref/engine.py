"""Independent scan/sort model: lifecycle dictionary, no price queues or index."""

from copy import deepcopy
from dataclasses import dataclass
import hashlib

from .codec import ID, MAX_INT, canonical, checked_add, parse, payload, ProtocolError


@dataclass(frozen=True)
class Config:
    max_accepted_orders: int = 100000
    max_unique_requests: int = 200000
    max_line_bytes: int = 16384

    def __post_init__(self):
        if not (
            type(self.max_accepted_orders) is int
            and type(self.max_unique_requests) is int
            and type(self.max_line_bytes) is int
            and 1 <= self.max_accepted_orders <= min(1000000, self.max_unique_requests)
            and 1 <= self.max_unique_requests <= 2000000
            and 1 <= self.max_line_bytes <= 16384
        ):
            raise ValueError("invalid semantic limits")

    def wire(self):
        return {k: str(v) for k, v in vars(self).items()}


@dataclass
class Order:
    client_id: str
    order_id: str
    side: str
    price: int
    original: int
    acceptance_seq: int
    remaining: int
    filled: int = 0
    cancelled: int = 0
    status: str = "active"

    def key(self):
        return {"client_id": self.client_id, "order_id": self.order_id}

    def wire(self):
        return dict(
            self.key(),
            side=self.side,
            price_ticks=str(self.price),
            original_quantity=str(self.original),
            acceptance_seq=str(self.acceptance_seq),
            remaining_quantity=str(self.remaining),
            filled_quantity=str(self.filled),
            cancelled_quantity=str(self.cancelled),
            status=self.status,
        )


class Session:
    def __init__(self, session_id, config=None):
        if not isinstance(session_id, str) or not ID.fullmatch(session_id):
            raise ValueError("invalid session ID")
        self.session_id = session_id
        self.config = config or Config()
        self.orders = {}
        self.requests = {}
        self.next_seq = 1
        self.last_seq = 0
        self.event_count = 0
        self.event_digest = hashlib.sha256(b"replaylab-events-v1").digest()

    def _envelope(self, command, semantic, duplicate=False):
        return dict(
            schema_version=1,
            session_id=self.session_id,
            client_id=command.get("client_id"),
            request_id=command.get("request_id"),
            duplicate=duplicate,
            durability="none",
            **deepcopy(semantic),
        )

    def _error(self, command, code, subcode=None):
        result = {"status": "error", "code": code}
        if subcode:
            result["subcode"] = subcode
        return self._envelope(command, {"seq": None, "result": result, "events": []})

    def handle(self, raw):
        try:
            command = parse(raw, self.config.max_line_bytes)
        except ProtocolError as exc:
            return self._error(exc.correlation, "PROTOCOL_ERROR", exc.subcode)
        return self.submit(command)

    def submit(self, command):
        key = command["client_id"], command["request_id"]
        business = payload(command)
        encoded = canonical(business)
        if key in self.requests:
            old_payload, old_response = self.requests[key]
            if encoded != canonical(old_payload):
                return self._error(command, "IDEMPOTENCY_CONFLICT")
            return self._envelope(command, old_response, True)
        if len(self.requests) >= self.config.max_unique_requests:
            return self._error(command, "SESSION_REQUEST_LIMIT")
        if self.next_seq is None:
            return self._error(command, "SEQUENCE_EXHAUSTED")
        seq = self.next_seq
        result, events = self._execute(seq, command)
        semantic = {"seq": str(seq), "result": result, "events": events}
        self.requests[key] = deepcopy(business), deepcopy(semantic)
        self.last_seq = seq
        self.next_seq = seq + 1 if seq < MAX_INT else None
        for event in events:
            data = canonical(event)
            self.event_digest = hashlib.sha256(
                self.event_digest + len(data).to_bytes(8, "big") + data
            ).digest()
            self.event_count = checked_add(self.event_count, 1)
        return self._envelope(command, semantic)

    def _execute(self, seq, c):
        kind = c["type"]
        key = c["client_id"], c["order_id"]
        base = {"command_type": kind, "order_id": c["order_id"]}

        def rejected(code):
            return dict(base, status="rejected", code=code), []

        def event(index, kind, **fields):
            return dict(
                session_id=self.session_id,
                seq=str(seq),
                event_index=str(index),
                type=kind,
                instrument="SIM",
                **fields,
            )

        if c["instrument"] != "SIM":
            return rejected("UNKNOWN_INSTRUMENT")
        if kind == "cancel":
            order = self.orders.get(key)
            if order is None or order.status != "active":
                return rejected("ORDER_NOT_ACTIVE")
            amount = order.remaining
            order.remaining = 0
            order.cancelled = amount
            order.status = "cancelled"
            return dict(
                base,
                status="accepted",
                order_status="cancelled",
                cancelled_quantity=str(amount),
            ), [
                event(0, "cancelled", order=order.key(), cancelled_quantity=str(amount))
            ]
        if key in self.orders:
            return rejected("ORDER_ID_REUSED")
        if len(self.orders) >= self.config.max_accepted_orders:
            return rejected("SESSION_ORDER_LIMIT")
        incoming = Order(
            c["client_id"],
            c["order_id"],
            c["side"],
            int(c["price_ticks"]),
            int(c["quantity"]),
            seq,
            int(c["quantity"]),
        )
        eligible = [
            o
            for o in self.orders.values()
            if o.status == "active"
            and o.side != incoming.side
            and (
                o.price <= incoming.price
                if incoming.side == "buy"
                else o.price >= incoming.price
            )
        ]
        eligible.sort(
            key=lambda o: (
                o.price if incoming.side == "buy" else -o.price,
                o.acceptance_seq,
            )
        )
        self.orders[key] = incoming
        events = []
        for resting in eligible:
            if incoming.remaining == 0:
                break
            quantity = min(incoming.remaining, resting.remaining)
            for order in (incoming, resting):
                order.remaining -= quantity
                order.filled = checked_add(order.filled, quantity)
                if order.remaining == 0:
                    order.status = "filled"
            buyer, seller = (
                (incoming, resting) if incoming.side == "buy" else (resting, incoming)
            )
            events.append(
                event(
                    len(events),
                    "trade",
                    resting=resting.key(),
                    incoming=incoming.key(),
                    buyer=buyer.key(),
                    seller=seller.key(),
                    price_ticks=str(resting.price),
                    quantity=str(quantity),
                )
            )
        return dict(
            base,
            status="accepted",
            order_status=incoming.status,
            original_quantity=str(incoming.original),
            filled_quantity=str(incoming.filled),
            remaining_quantity=str(incoming.remaining),
            cancelled_quantity="0",
        ), events

    def book_state(self):
        result = {}
        for side, name in [("buy", "bids"), ("sell", "asks")]:
            active = [
                o
                for o in self.orders.values()
                if o.status == "active" and o.side == side
            ]
            active.sort(
                key=lambda o: (
                    o.price if side == "sell" else -o.price,
                    o.acceptance_seq,
                )
            )
            levels = []
            for order in active:
                if not levels or levels[-1]["price_ticks"] != str(order.price):
                    levels.append(
                        {"price_ticks": str(order.price), "orders": [], "quantity": "0"}
                    )
                levels[-1]["orders"].append(
                    dict(
                        order.key(),
                        acceptance_seq=str(order.acceptance_seq),
                        remaining_quantity=str(order.remaining),
                    )
                )
                levels[-1]["quantity"] = str(
                    checked_add(int(levels[-1]["quantity"]), order.remaining)
                )
            result[name] = levels
        return result

    def session_state(self):
        return dict(
            schema_version=1,
            semantics_version="replaylab-v1",
            session_id=self.session_id,
            configuration=self.config.wire(),
            last_applied_seq=str(self.last_seq),
            next_seq=None if self.next_seq is None else str(self.next_seq),
            orders=[self.orders[k].wire() for k in sorted(self.orders)],
            requests=[
                {
                    "client_id": k[0],
                    "request_id": k[1],
                    "payload": deepcopy(self.requests[k][0]),
                    "response": deepcopy(self.requests[k][1]),
                }
                for k in sorted(self.requests)
            ],
            event_count=str(self.event_count),
            event_digest=self.event_digest.hex(),
        )

    def assert_invariants(self):
        active = [o for o in self.orders.values() if o.status == "active"]
        bids = [o.price for o in active if o.side == "buy"]
        asks = [o.price for o in active if o.side == "sell"]
        assert not bids or not asks or max(bids) < min(asks), "UNCROSSED_BOOK"
        for order in self.orders.values():
            assert order.original == order.filled + order.cancelled + order.remaining, (
                "CONSERVATION"
            )
            assert all(
                0 <= x <= 10**9
                for x in (
                    order.original,
                    order.filled,
                    order.cancelled,
                    order.remaining,
                )
            )
            assert (order.status == "active") == (order.remaining > 0)
            assert (order.status == "cancelled") == (order.cancelled > 0)
        events = [
            e for _, response in self.requests.values() for e in response["events"]
        ]
        trades = [e for e in events if e["type"] == "trade"]
        traded = sum(int(e["quantity"]) for e in trades)
        assert sum(o.filled for o in self.orders.values()) == 2 * traded, (
            "TRADE_CONSERVATION"
        )
        assert self.event_count == len(events)
        for e in trades:
            resting = self.orders[e["resting"]["client_id"], e["resting"]["order_id"]]
            buyer = self.orders[e["buyer"]["client_id"], e["buyer"]["order_id"]]
            seller = self.orders[e["seller"]["client_id"], e["seller"]["order_id"]]
            assert int(e["quantity"]) > 0
            assert seller.price <= int(e["price_ticks"]) == resting.price <= buyer.price
