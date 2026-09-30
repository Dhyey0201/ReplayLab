"""Generate declarative v1 schemas; matching logic is never generated."""

import json
from pathlib import Path


def object_(properties, required=None):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else required,
        "additionalProperties": False,
    }


def ref(name):
    return {"$ref": f"#/$defs/{name}"}


def enum(*values):
    return {"enum": list(values)}


ID = {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,64}$"}
UINT = {"type": "string", "pattern": "^(0|[1-9][0-9]*)$"}
POS = {"type": "string", "pattern": "^[1-9][0-9]*$"}
VALUE = {"type": "string", "pattern": "^([1-9][0-9]{0,8}|1000000000)$"}
HASH = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
STRING = {"type": "string"}
BOOL = {"type": "boolean"}
V = {"const": 1, "type": "integer"}
ANY = {}


def ARRAY(x):
    return {"type": "array", "items": x}


base = dict(
    schema_version=V,
    type=enum("new"),
    client_id=ID,
    request_id=ID,
    instrument=ID,
    order_id=ID,
)
defs = {}
defs["new"] = object_(
    dict(base, side=enum("buy", "sell"), price_ticks=VALUE, quantity=VALUE)
)
defs["cancel"] = object_(dict(base, type=enum("cancel")))
defs["request"] = {"oneOf": [ref("new"), ref("cancel")]}
defs["order_key"] = object_(dict(client_id=ID, order_id=ID))
event = dict(session_id=ID, seq=POS, event_index=UINT, instrument={"const": "SIM"})
defs["trade"] = object_(
    dict(
        event,
        type={"const": "trade"},
        resting=ref("order_key"),
        incoming=ref("order_key"),
        buyer=ref("order_key"),
        seller=ref("order_key"),
        price_ticks=VALUE,
        quantity=VALUE,
    )
)
defs["cancelled"] = object_(
    dict(
        event,
        type={"const": "cancelled"},
        order=ref("order_key"),
        cancelled_quantity=VALUE,
    )
)
defs["event"] = {"oneOf": [ref("trade"), ref("cancelled")]}
defs["new_accepted"] = object_(
    dict(
        status={"const": "accepted"},
        command_type={"const": "new"},
        order_id=ID,
        order_status=enum("active", "filled"),
        original_quantity=VALUE,
        filled_quantity=UINT,
        remaining_quantity=UINT,
        cancelled_quantity={"const": "0"},
    )
)
defs["cancel_accepted"] = object_(
    dict(
        status={"const": "accepted"},
        command_type={"const": "cancel"},
        order_id=ID,
        order_status={"const": "cancelled"},
        cancelled_quantity=VALUE,
    )
)
defs["rejected"] = object_(
    dict(
        status={"const": "rejected"},
        command_type=enum("new", "cancel"),
        order_id=ID,
        code=enum(
            "UNKNOWN_INSTRUMENT",
            "ORDER_ID_REUSED",
            "SESSION_ORDER_LIMIT",
            "ORDER_NOT_ACTIVE",
        ),
    )
)
defs["protocol_error"] = object_(
    dict(
        status={"const": "error"},
        code={"const": "PROTOCOL_ERROR"},
        subcode=enum(
            "INVALID_UTF8",
            "OVERSIZED_LINE",
            "INVALID_JSON",
            "DUPLICATE_OBJECT_KEY",
            "UNKNOWN_FIELD",
            "MISSING_FIELD",
            "UNSUPPORTED_SCHEMA_VERSION",
            "WRONG_FIELD_TYPE",
            "INVALID_ID",
            "INVALID_SIDE",
            "INVALID_COMMAND_TYPE",
            "INVALID_NUMERIC_ENCODING",
            "NUMERIC_OUT_OF_RANGE",
        ),
    )
)
defs["infrastructure_error"] = object_(
    dict(
        status={"const": "error"},
        code=enum(
            "IDEMPOTENCY_CONFLICT", "SESSION_REQUEST_LIMIT", "SEQUENCE_EXHAUSTED"
        ),
    )
)
defs["result"] = {
    "oneOf": [
        ref(k)
        for k in [
            "new_accepted",
            "cancel_accepted",
            "rejected",
            "protocol_error",
            "infrastructure_error",
        ]
    ]
}
defs["semantic_response"] = object_(
    dict(
        seq=POS,
        result={
            "oneOf": [ref("new_accepted"), ref("cancel_accepted"), ref("rejected")]
        },
        events=ARRAY(ref("event")),
    )
)
defs["response"] = object_(
    dict(
        schema_version=V,
        session_id=ID,
        client_id={"anyOf": [ID, {"type": "null"}]},
        request_id={"anyOf": [ID, {"type": "null"}]},
        seq={"anyOf": [POS, {"type": "null"}]},
        duplicate=BOOL,
        durability=enum("none", "synced"),
        result=ref("result"),
        events=ARRAY(ref("event")),
    )
)
defs["configuration"] = object_(
    dict(max_accepted_orders=POS, max_unique_requests=POS, max_line_bytes=POS)
)
defs["order"] = object_(
    dict(
        client_id=ID,
        order_id=ID,
        side=enum("buy", "sell"),
        price_ticks=VALUE,
        original_quantity=VALUE,
        acceptance_seq=POS,
        remaining_quantity=UINT,
        filled_quantity=UINT,
        cancelled_quantity=UINT,
        status=enum("active", "filled", "cancelled"),
    )
)
defs["new_payload"] = object_(
    dict(
        type={"const": "new"},
        instrument=ID,
        order_id=ID,
        side=enum("buy", "sell"),
        price_ticks=VALUE,
        quantity=VALUE,
    )
)
defs["cancel_payload"] = object_(
    dict(type={"const": "cancel"}, instrument=ID, order_id=ID)
)
defs["payload"] = {"oneOf": [ref("new_payload"), ref("cancel_payload")]}
defs["cached_request"] = object_(
    dict(
        client_id=ID,
        request_id=ID,
        payload=ref("payload"),
        response=ref("semantic_response"),
    )
)
defs["session_state"] = object_(
    dict(
        schema_version=V,
        semantics_version={"const": "replaylab-v1"},
        session_id=ID,
        configuration=ref("configuration"),
        last_applied_seq=UINT,
        next_seq={"anyOf": [POS, {"type": "null"}]},
        orders=ARRAY(ref("order")),
        requests=ARRAY(ref("cached_request")),
        event_count=UINT,
        event_digest=HASH,
    )
)
defs["book_order"] = object_(
    dict(client_id=ID, order_id=ID, acceptance_seq=POS, remaining_quantity=VALUE)
)
defs["level"] = object_(
    dict(price_ticks=VALUE, quantity=POS, orders=ARRAY(ref("book_order")))
)
defs["book_state"] = object_(dict(bids=ARRAY(ref("level")), asks=ARRAY(ref("level"))))
defs["run_manifest"] = object_(
    dict(
        schema_version=V,
        semantics_version=STRING,
        mode=STRING,
        session_id=ID,
        configuration=ref("configuration"),
        workload_sha256=HASH,
        candidate=STRING,
        candidate_sha256=HASH,
        candidate_args=ARRAY(STRING),
        build_identity=STRING,
        status=enum("incomplete", "mismatch", "agreement"),
        reproduction=ARRAY(STRING),
        attempts=UINT,
        session_hash=HASH,
    ),
    required=[
        "schema_version",
        "semantics_version",
        "mode",
        "session_id",
        "configuration",
        "workload_sha256",
        "candidate",
        "candidate_sha256",
        "candidate_args",
        "build_identity",
        "status",
        "reproduction",
    ],
)
defs["difference"] = object_(
    dict(
        attempt=UINT,
        seq={"anyOf": [UINT, {"type": "null"}]},
        path=STRING,
        expected=ANY,
        actual=ANY,
        signature=STRING,
        book_before={"anyOf": [ref("book_state"), {"type": "null"}]},
        book_after=ref("book_state"),
    )
)
defs["shrink_report"] = object_(
    dict(
        schema_version=V,
        predicate=STRING,
        max_evaluations=POS,
        timeout_seconds=STRING,
        evaluations=UINT,
        cache_hits=UINT,
        duration_seconds=STRING,
        original_commands=UINT,
        final_commands=UINT,
        original_bytes=UINT,
        final_bytes=UINT,
        budget_exhausted=BOOL,
        validation_repetitions=UINT,
        validation_passed=BOOL,
        minimality=STRING,
    )
)
bench = {
    k: UINT
    for k in [
        "elapsed_ns",
        "sample_count",
        "latency_median_ns",
        "latency_p95_ns",
        "latency_p99_ns",
        "latency_max_ns",
        "clock_pair_median_ns",
        "attempts",
        "unique_commands",
        "accepted_orders",
        "trades",
        "duplicates",
        "business_rejections",
        "unsequenced_or_invalid",
        "active_orders",
        "active_levels",
        "retained_orders",
        "dedupe_entries",
        "peak_rss_bytes",
        "allocated_words",
        "minor_collections",
    ]
}
defs["benchmark_sample"] = object_(
    dict(
        bench,
        schema_version=V,
        mode=enum(
            "book-kernel",
            "memory-session",
            "json-batch",
            "durable-session",
            "recovery",
            "recovery-with-snapshot",
        ),
        samples_ns=ARRAY(UINT),
        session_hash={"anyOf": [HASH, {"type": "null"}]},
        repetition=UINT,
        workload_sha256=HASH,
    ),
    required=["schema_version", "mode", *bench, "samples_ns", "session_hash"],
)
root = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://replaylab.local/schemas/v1.json",
    "$defs": defs,
}
Path("schemas/v1.json").write_text(json.dumps(root, indent=2) + "\n")
