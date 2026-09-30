"""Strict wire validation and explicitly restricted canonical JSON."""

import hashlib
import json
import re

ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z", re.ASCII)
DECIMAL = re.compile(r"[1-9][0-9]*\Z", re.ASCII)
MAX_INT = 2**63 - 1
MAX_VALUE = 10**9
BASE = ("schema_version", "type", "client_id", "request_id", "instrument", "order_id")


class ProtocolError(ValueError):
    def __init__(self, subcode, correlation=None):
        super().__init__(subcode)
        self.subcode = subcode
        self.correlation = correlation or {}


def canonical(value):
    def encode(v):
        if v is None:
            return "null"
        if type(v) is bool:
            return "true" if v else "false"
        if type(v) is int:
            return str(v)
        if isinstance(v, str):
            if not v.isascii():
                raise ValueError("canonical strings must be ASCII")
            return (
                '"'
                + "".join(
                    '\\"'
                    if c == '"'
                    else "\\\\"
                    if c == "\\"
                    else f"\\u{ord(c):04x}"
                    if ord(c) < 32
                    else c
                    for c in v
                )
                + '"'
            )
        if isinstance(v, list):
            return "[" + ",".join(map(encode, v)) + "]"
        if isinstance(v, dict):
            return (
                "{" + ",".join(encode(k) + ":" + encode(v[k]) for k in sorted(v)) + "}"
            )
        raise TypeError(type(v))

    return encode(value).encode("ascii")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def checked_add(a, b):
    result = a + b
    if not 0 <= result <= MAX_INT:
        raise OverflowError("int64 counter overflow")
    return result


class _ObjectPairs(list):
    pass


def _validate_json_tree(value, depth=0):
    if depth > 256:
        raise ProtocolError("INVALID_JSON")
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ProtocolError("INVALID_JSON") from None
    elif isinstance(value, _ObjectPairs):
        for key, child in value:
            _validate_json_tree(key, depth + 1)
            _validate_json_tree(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _validate_json_tree(child, depth + 1)


def _convert_pairs(value):
    if isinstance(value, _ObjectPairs):
        result = {}
        for key, child in value:
            if key in result:
                raise ProtocolError("DUPLICATE_OBJECT_KEY")
            result[key] = _convert_pairs(child)
        return result
    if isinstance(value, list):
        return [_convert_pairs(child) for child in value]
    return value


def parse(raw, max_line_bytes=16384):
    if isinstance(raw, str):
        try:
            raw = raw.encode("utf-8")
        except UnicodeEncodeError:
            raise ProtocolError("INVALID_UTF8") from None
    if raw.endswith(b"\n"):
        raw = raw[:-1]
    if len(raw) > max_line_bytes:
        raise ProtocolError("OVERSIZED_LINE")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise ProtocolError("INVALID_UTF8") from None
    try:
        obj = json.loads(
            text,
            object_pairs_hook=_ObjectPairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except ProtocolError:
        raise
    except (ValueError, RecursionError):
        raise ProtocolError("INVALID_JSON") from None
    _validate_json_tree(obj)
    obj = _convert_pairs(obj)
    if not isinstance(obj, dict):
        raise ProtocolError("WRONG_FIELD_TYPE")
    correlation = {
        k: obj[k]
        for k in ("client_id", "request_id")
        if isinstance(obj.get(k), str) and ID.fullmatch(obj[k])
    }

    def fail(code):
        raise ProtocolError(code, correlation)

    if "schema_version" not in obj:
        fail("MISSING_FIELD")
    if type(obj["schema_version"]) is not int:
        fail("WRONG_FIELD_TYPE")
    if obj["schema_version"] != 1:
        fail("UNSUPPORTED_SCHEMA_VERSION")
    if "type" not in obj:
        fail("MISSING_FIELD")
    if not isinstance(obj["type"], str):
        fail("WRONG_FIELD_TYPE")
    if obj["type"] not in ("new", "cancel"):
        fail("INVALID_COMMAND_TYPE")
    fields = BASE + (
        ("side", "price_ticks", "quantity") if obj["type"] == "new" else ()
    )
    if set(obj) - set(fields):
        fail("UNKNOWN_FIELD")
    if set(fields) - set(obj):
        fail("MISSING_FIELD")
    for field in fields[2:]:
        value = obj[field]
        if not isinstance(value, str):
            fail("WRONG_FIELD_TYPE")
        if field in BASE and not ID.fullmatch(value):
            fail("INVALID_ID")
        if field == "side" and value not in ("buy", "sell"):
            fail("INVALID_SIDE")
        if field in ("price_ticks", "quantity"):
            if not DECIMAL.fullmatch(value):
                fail("INVALID_NUMERIC_ENCODING")
            if len(value) > 10 or int(value) > MAX_VALUE:
                fail("NUMERIC_OUT_OF_RANGE")
    return obj


def payload(command):
    return {
        k: v
        for k, v in command.items()
        if k not in ("schema_version", "request_id", "client_id")
    }


def lines(stream, limit=16384):
    """Bounded buffering, including draining an oversized record to its newline."""
    while True:
        line = stream.readline(limit + 2)
        if not line:
            return
        if not line.endswith(b"\n") and len(line) > limit:
            while True:
                chunk = stream.readline(limit + 2)
                if not chunk or chunk.endswith(b"\n"):
                    break
        yield line
