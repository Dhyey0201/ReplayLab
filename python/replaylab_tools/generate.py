"""Seeded generator; saved bytes, not future PRNG behavior, define replay."""

import hashlib
import random
from pathlib import Path
from replaylab_ref.codec import canonical
from replaylab_ref.engine import Session

PROFILES = (
    "balanced",
    "deep-level",
    "many-levels",
    "sweep",
    "cancellation",
    "retries",
    "sparse-cross",
    "hot-cross",
    "malformed",
    "recovery",
)


def generate(profile, seed, count):
    if profile not in PROFILES or not 0 <= count <= 2000000:
        raise ValueError("invalid profile/count")
    rng = random.Random(seed)
    model = Session("generator")
    previous = []
    records = []
    categories = {}
    for i in range(count):
        draw = rng.randrange(100)
        active = [o for o in model.orders.values() if o.status == "active"]
        category = (
            "new"
            if draw < 60
            else "cancel"
            if draw < 80
            else "retry"
            if draw < 90
            else "conflict"
            if draw < 95
            else "malformed"
        )
        if profile == "cancellation":
            category = "cancel" if draw < 70 else "new"
        if profile == "retries":
            category = "retry" if draw < 40 else "conflict" if draw < 65 else "new"
        if profile == "malformed":
            category = "malformed" if draw < 70 else "new"
        if profile in (
            "deep-level",
            "many-levels",
            "sparse-cross",
            "hot-cross",
            "sweep",
            "recovery",
        ):
            category = "new"
        if category in ("retry", "conflict") and not previous:
            category = "new"
        client = rng.choice(["alice", "bob", "carol"])
        if category in ("retry", "conflict"):
            c = dict(rng.choice(previous))
            if category == "conflict":
                c["instrument"] = "OTHER" if c["instrument"] == "SIM" else "SIM"
            raw = canonical(c)
        elif category == "cancel":
            target = rng.choice(active) if active and draw % 5 else None
            c = dict(
                schema_version=1,
                type="cancel",
                client_id=target.client_id if target else client,
                request_id=f"r{i}",
                instrument="SIM",
                order_id=target.order_id if target else "missing",
            )
            raw = canonical(c)
            previous.append(c)
        elif category == "malformed":
            raw = rng.choice(
                [
                    b"",
                    b"{",
                    b"[]",
                    b'{"schema_version":true}',
                    b'{"schema_version":1,"schema_version":1}',
                    b"\xff",
                ]
            )
        else:
            side = rng.choice(["buy", "sell"])
            price = rng.randrange(95, 106)
            quantity = rng.randrange(1, 21)
            if profile == "deep-level":
                side = "sell"
                price = 100
            if profile == "many-levels":
                side = "sell"
                price = i + 1
            if profile == "sparse-cross":
                price = 90 if side == "buy" else 110
            if profile in ("hot-cross", "recovery"):
                side = "sell" if i % 2 == 0 else "buy"
                price = 100
            if profile == "sweep":
                side = "buy" if i % 8 == 7 else "sell"
                price = 110 if side == "buy" else 100 + i % 7
                quantity = 100 if side == "buy" else 5
            c = dict(
                schema_version=1,
                type="new",
                client_id=client,
                request_id=f"r{i}",
                instrument="SIM",
                order_id=f"o{i}",
                side=side,
                price_ticks=str(price),
                quantity=str(quantity),
            )
            raw = canonical(c)
            previous.append(c)
        model.handle(raw)
        records.append(raw + b"\n")
        categories[category] = categories.get(category, 0) + 1
    return records, categories


def save(profile, seed, count, out):
    path = Path(out)
    if path.exists() or path.with_suffix(".manifest.json").exists():
        raise FileExistsError(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    records, categories = generate(profile, seed, count)
    data = b"".join(records)
    path.write_bytes(data)
    manifest = dict(
        schema_version=1,
        generator_version="1",
        semantics_version="replaylab-v1",
        seed=str(seed),
        profile=profile,
        attempts=str(count),
        sha256=hashlib.sha256(data).hexdigest(),
        realized_categories={k: str(v) for k, v in categories.items()},
        configuration=Session("generator").config.wire(),
        python_prng="random.Random; replay saved bytes",
    )
    path.with_suffix(".manifest.json").write_bytes(canonical(manifest) + b"\n")
    return manifest
