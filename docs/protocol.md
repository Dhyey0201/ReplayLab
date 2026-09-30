# Wire and canonical contract

Use UTF-8 JSON Lines, one attempt per line. A complete final JSON value without LF
is accepted. Live clients should terminate requests with LF. Blank lines are
errors. Oversized lines are drained with bounded buffering before the next line.
Stdout contains only response/result JSON; diagnostics use stderr.

The frozen draft-2020-12 schemas live in `schemas/v1.json`, under `$defs`.
`request`, `response`, `event`, `session_state`, `book_state`, `run_manifest`,
`difference`, `shrink_report`, and `benchmark_sample` are separate entry points.
JSON Schema cannot detect duplicate keys or enforce all cross-field arithmetic;
the strict parsers and invariant tests provide those additional checks.

## Validation order

1. Line size, then strict UTF-8.
2. RFC JSON grammar (maximum nesting depth 256), then duplicate object keys.
3. Object shape; schema_version presence, integer type (not bool/float), value 1.
4. Command type presence/type/value; unknown fields, then missing fields.
5. Fixed field order: client_id, request_id, instrument, order_id; then side,
   price_ticks, quantity for new orders. Type precedes syntax and numeric range.

The schema lists all stable protocol subcodes. Safely parsed valid client/request
IDs are echoed on schema errors; framing/JSON errors have null correlation IDs.
The Python parser validates the whole JSON grammar before duplicate-key checking,
so a duplicate key followed by trailing garbage is `INVALID_JSON` in both engines.

## Examples

New command:

```json
{"schema_version":1,"type":"new","client_id":"a","request_id":"r1","instrument":"SIM","order_id":"o1","side":"sell","price_ticks":"100","quantity":"10"}
```

Sequenced `result` variants (the envelope also carries schema_version, session_id,
client_id, request_id, seq, duplicate, durability and events):

```json
{"status":"accepted","command_type":"new","order_id":"o1","order_status":"active","original_quantity":"10","filled_quantity":"0","remaining_quantity":"10","cancelled_quantity":"0"}
{"status":"accepted","command_type":"cancel","order_id":"o1","order_status":"cancelled","cancelled_quantity":"10"}
{"status":"rejected","command_type":"cancel","order_id":"o1","code":"ORDER_NOT_ACTIVE"}
```

Unsequenced results use `seq:null`, `duplicate:false`, `durability:"none"`, and an
empty events array:

```json
{"status":"error","code":"PROTOCOL_ERROR","subcode":"INVALID_NUMERIC_ENCODING"}
{"status":"error","code":"IDEMPOTENCY_CONFLICT"}
```

Trade events use `resting`, `incoming`, `buyer`, and `seller`, each an object with
client_id and order_id. They also carry type, instrument, price_ticks, quantity,
session_id, seq, event_index. A cancelled event replaces the four role keys with
`order` and replaces quantity with `cancelled_quantity`. Index starts at "0".

## Canonical bytes and hashes

Object keys are ASCII-sorted; arrays retain order. No whitespace appears. Domain
numbers are canonical decimal strings, versions are JSON integers, and boolean
and null literals use JSON spelling. Quote and backslash are escaped; every
control character uses lowercase `\u00xx`, including newline and tab. Other ASCII
bytes are literal. The semantic subset has no Unicode strings or float values.
The shared byte fixture is `fixtures/golden/canonical.json`.

The deduplication payload excludes schema_version, client_id and request_id. The
request table key already contains the latter two IDs. Full canonical payload
bytes, not hash equality, determine retries.

The event digest starts at SHA256(`replaylab-events-v1`) and updates once per new
event with SHA256(previous **raw 32 bytes** || event length as unsigned 64-bit
big-endian || canonical event bytes). Displayed hashes are lowercase hex.

Book state contains price levels and FIFO active orders. Session state contains
configuration, versions, full sorted lifecycle ledger, sorted request cache with
original responses, sequence state, event count and digest. Apparently identical
books can therefore have different session hashes and different future behavior.
