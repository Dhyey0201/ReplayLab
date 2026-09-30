# ReplayLab Detailed Implementation Specification

Version 1.0 • Prepared for Dhyey Patel • September 29 2026

## Purpose and instructions for the implementing agent

Build ReplayLab, a deterministic exchange simulation and correctness-testing workbench. Its central purpose is to let an engineer change a matching engine, replay exactly the same commands, detect behavioral differences, reproduce failures across crashes, and reduce a large failing workload to a small, understandable reproduction.

This is an implementation contract, not a request for a visual prototype or a trading bot. Deliver working OCaml and Python code, reproducible tests, documented semantics, crash experiments, benchmark tooling, and a useful command-line interface. The finished project should be understandable to someone evaluating systems engineering, algorithms, reliability, and experimental rigor.

The required deliverable is an open-source-ready local repository. Do not connect to a broker, place real trades, use private employer information, or imply Jane Street uses or endorses this project. The connection to Jane Street is intellectual relevance: exchange infrastructure, ordering, correctness, functional programming, and careful performance work. This document specifies an original educational design; it does not reproduce JX or any proprietary system.

### Ready to use Codex starting prompt

```text
Read ReplayLab_Codex_Implementation_Specification.md completely before editing.
Implement the project described by it in this repository.

First inspect the repository and any applicable AGENTS.md instructions. Preserve
unrelated existing work. Treat this specification as the behavioral contract.
Create a milestone checklist and an implementation decision log. Resolve routine
implementation choices yourself, recording the reason and relevant tradeoff.

Work through milestones M0 through M9 in dependency order. Build the command-line
system first. Do not substitute a dashboard, mocked output, or a different language
for the OCaml engine. Implement the independent Python reference before optimizing
the OCaml engine. Do not skip persistence, failure shrinking, or crash experiments.

Run meaningful validation at every milestone. Store reproducible seeds, fixtures,
failure artifacts, and raw benchmark results. If a dependency or environment blocks
a test, explicitly record what could not be executed and continue with independent
work; never invent passing results or benchmark numbers.

Before finishing, run the release acceptance commands, review the requirements
matrix, and produce a concise report with completed milestones, verification
results, actual measurements, remaining limitations, and commands to reproduce
the main demos. Keep PROGRESS.md current so a later session can resume accurately.

Use the specification's required behavior when resolving ambiguities. Ask me only
when a consequential product decision cannot be resolved from this document or
when an external action requires authorization. Repository implementation and
local tests are authorized; public publishing and external account changes are not
part of this request.
```

### How to use this document

Place this file at the repository root, then give the prompt above to Codex. The document is deliberately self-contained. Sections on semantics, persistence, canonical encoding, and testing are normative. Library choices and module organization are recommended defaults that can change with a recorded reason. Optional extensions must not delay the required release.

Use MUST for a required release behavior, SHOULD for a preferred implementation with a documented alternative, and MAY for an optional extension. If two requirements seem inconsistent, record the conflict and resolve it before coding the affected behavior. Do not silently weaken the contract to make a test pass.

## 1 Product definition

### 1.1 The problem

An exchange matching engine is a stateful program. A seemingly harmless change to a queue, cancellation path, or retry handler can alter execution order, create duplicate trades, or break recovery. A normal example-based test may miss a failure that requires thousands of preceding commands and a crash at one exact boundary.

ReplayLab must make those failures easy to generate, detect, preserve, understand, and reproduce. A user should be able to submit a workload, compare two engines, replay an execution, crash and recover a durable session, and shrink a mismatch without manually reconstructing the incident.

### 1.2 The defining demonstration

The flagship demo is a complete debugging story:

1. Run a correct OCaml engine and the independent Python reference on a seeded workload.
2. Show identical responses, trades, and final semantic state.
3. Enable one deliberately faulty implementation in an isolated test build.
4. Detect a mismatch and save the first divergent prefix with full provenance.
5. Shrink that failure while preserving its semantic failure signature.
6. Print a short explanation of the remaining commands and the differing outputs.
7. Run the corrected engine on the minimized reproduction and show agreement.
8. Demonstrate a separate persistence scenario: interrupt an acknowledged workload, recover, retry uncertain requests, and compare with the corresponding uninterrupted logical execution.

This demo matters more than a complicated UI, a simulated profit chart, or an unsupported throughput headline.

### 1.3 Users and concrete workflows

| User | Goal | Successful outcome |
|---|---|---|
| Matching-engine developer | Verify a data structure change | Same canonical outcomes under saved workloads |
| Reliability engineer | Investigate crash behavior | Recovered durable history and deduplication are correct |
| Performance engineer | Compare implementations | Repeated measurements with an honest scope and provenance |
| Learner or interviewer | Inspect engineering decisions | Small fixtures, clear invariants, documented tradeoffs |

### 1.4 Required release scope

One instrument named `SIM`; one sequencer; one owner of mutable matching state; buy and sell limit orders; whole-order cancellation; partial fills; price-time priority; integer ticks and units; good-till-cancelled behavior; session-scoped order identities; request idempotency; independent Python reference; OCaml optimized engine; deterministic outputs; append-only command journal; replay; snapshots; crash injection; differential tests; shrinking; benchmark reports; CI; documentation; three runnable demos.

### 1.5 Explicit exclusions

Do not implement market orders, replace/amend commands, auctions, iceberg orders, pegged orders, stop orders, fees, margin, settlement, matching across instruments, real market data feeds, FIX, brokerage connectivity, distributed consensus, production authentication, Kubernetes deployment, GPU processing, ML predictions, LLM agents, or trading strategies in the required release. These increase scope without proving the core claims.

Do not describe results as production exchange performance, profitable trading, regulatory compliance, universal exactly-once delivery, formal proof, or a complete power-loss guarantee.

## 2 Architecture and dependency boundaries

### 2.1 System components

The OCaml executable owns parsing, session execution, order matching, canonical outputs, durable storage, and recovery. Python owns an independently implemented reference engine, workload generation, differential orchestration, process-crash orchestration, shrinking, and benchmark analysis. Both languages read the same documented wire formats and frozen fixtures.

The CLI is the product interface. A browser dashboard is optional and must consume exported artifacts instead of defining a second matching implementation.

| Component | Responsibility | Must not depend on |
|---|---|---|
| Domain | Typed commands, outcomes, error codes, safe numeric operations | Filesystem, clocks, randomness |
| Book | Levels, FIFO queues, matching, cancellation | JSON, networking, storage |
| Session | Sequencing, deduplication, order history, response construction | Wall-clock time |
| Canonical encoding | Stable semantic bytes and hashes | Hash-table iteration order |
| Journal | Framed durable normalized commands | Order-matching internals |
| Recovery | Validated journal replay and snapshot restore | Client retry timing |
| Driver | CLI, streams, exit codes, diagnostics | Hidden nondeterministic defaults |
| Reference | Independent simple semantics in Python | OCaml matching or queue code |
| Test controller | Comparison, fault schedules, shrinking | Assumptions that unacknowledged means uncommitted |
| Benchmark runner | Workload selection, timing, raw measurements | Differential checking in measured core loops |

### 2.2 Execution ownership

The required engine is single-threaded. A complete command finishes before the next command starts. No reader observes a partially updated book. Matching may mutate internal data structures, but externally each transition has one defined before-state and after-state.

Expose this conceptual operation:

```text
transition(state, sequenced_unique_command) -> outcome, emitted_events, new_state
```

An optimized implementation may mutate `state` in place. It must have exactly the same semantics as the simple reference operation. No clock, random number generator, environment variable, filesystem read, or thread race may influence the transition.

### 2.3 Execution modes

| Mode | Storage | Intended use | Durability claim |
|---|---|---|---|
| `memory` | None | Differential checks and core benchmarks | None |
| `durable` | Command journal and optional snapshots | Recovery experiments | Acknowledged unique decisions survive supported recovery |
| `replay` | Read existing journal or workload | Reconstruction and comparison | Does not modify input artifacts |

Do not label memory-mode responses durable. Persisted session metadata records the mode, wire version, semantics version, journal version, and configuration hash. Recovery refuses an incompatible semantics version rather than quietly replaying under changed rules.

### 2.4 Repository layout

```text
replaylab/
  README.md
  LICENSE
  AGENTS.md
  PROGRESS.md
  CHANGELOG.md
  dune-project
  replaylab.opam
  Makefile
  .ocamlformat
  .gitignore
  .github/workflows/ci.yml
  bin/main.ml
  lib/domain/             # validated types, commands, outcomes
  lib/book/               # levels, intrusive queues, matching
  lib/session/            # sequence, dedupe, order lifecycle
  lib/codec/              # strict parsing and canonical forms
  lib/storage/            # frame I/O, locking, snapshots, recovery
  lib/driver/             # stream execution and CLI wiring
  test/unit/
  test/properties/
  test/integration/
  python/pyproject.toml
  python/replaylab_ref/
  python/replaylab_tools/
  schemas/
  fixtures/golden/
  fixtures/regressions/
  workloads/configs/
  demos/
  scripts/
  docs/semantics.md
  docs/protocol.md
  docs/architecture.md
  docs/storage.md
  docs/testing.md
  docs/benchmarking.md
  docs/limitations.md
  docs/decisions/
  benchmarks/results/README.md
```

Small modules with clear `.mli` boundaries are preferable to a single large implementation file. This layout may be simplified if the separation of responsibilities remains visible.

## 3 Toolchain and setup policy

Use a stable OCaml 5.x compiler supported by the selected libraries, Dune, opam, and Python 3.11 or newer. Choose exact compatible versions during M0 and record them in the repository; this document does not assume whichever version is newest will work unchanged. Use native OCaml builds for performance results.

Recommended library roles: Yojson for JSON, Cmdliner for CLI parsing, Alcotest for example tests, QCheck for OCaml properties, a maintained SHA-256 library for canonical hashes and journal checksums, Unix for low-level I/O, pytest for Python tests, and Hypothesis for Python properties. Standard-library OCaml maps and hash tables are sufficient. Jane Street Core/Base may be used with an explicit benefit, but their use is not a project requirement.

Prefer small dependency sets. Avoid introducing an asynchronous runtime until a measured need exists. If a library cannot be installed, record the blocker and consider an equivalent supported library; do not replace real persistence or cryptographic hashing with a stub.

M0 must verify the compiler, native build, Python import path, JSON round trip, SHA-256 cross-language fixture, a real temporary-file write and sync, and the test runner. Record exact setup commands that actually succeeded. Lock or otherwise reproducibly constrain OCaml and Python dependencies using supported toolchain mechanisms; commit the relevant metadata. Avoid an unqualified `latest` container tag.

Linux on a local filesystem is the authoritative environment for durability tests. macOS can support development, but any platform-specific syncing, directory persistence, locking, or process-signal differences must be documented and tested separately. Windows users should use a compatible Linux environment for the required crash suite.

## 4 Normative domain rules

### 4.1 Identities

Every fresh session has an explicit `session_id`, supplied by the caller and stored in metadata. A session begins with `next_seq = 1`. Clients have stable `client_id` strings. A request key is `(client_id, request_id)` within a session. An order key is `(client_id, order_id)` within a session; different clients may use the same local order ID.

IDs use ASCII `[A-Za-z0-9_-]`, length 1 through 64. They are case sensitive. No trimming or case folding is allowed. Session IDs follow the same rule. An order key may never be reused after a successfully accepted order, including after full fill or cancellation. A rejected new-order attempt does not reserve its order ID. The request key of a well-formed new request is reserved even if its business decision is a rejection.

Client identity is a simulation field, not verified authentication. The project must not claim that sending `client_id` establishes a secure identity.

### 4.2 Numeric representation

Prices, quantities, sequence numbers, per-command event indices, and counters use explicitly checked integer operations. Store prices, quantities, and sequences as OCaml `int64`, not platform-sized `int`. Python must enforce the same range instead of relying on unbounded integers.

Wire values for prices, quantities, sequences, and large counters are canonical decimal strings. This prevents precision loss when future JavaScript tools consume them. Schema versions remain ordinary JSON integers. Positive values use `[1-9][0-9]*`; zero is allowed only for fields whose domain permits it. Reject signs, leading zeros, spaces, exponent notation, floating-point numbers, and negative zero.

Initial domain limits are `1 <= price_ticks <= 1_000_000_000` and `1 <= quantity <= 1_000_000_000`. Sequence numbers range from 1 through signed 64-bit maximum. Per-level aggregate quantity and cumulative counters must use checked arithmetic. Do not compute `price * quantity` unless necessary; any added notional or position calculations must define their bounds and overflow behavior first.

After the maximum sequence has been used, the service rejects fresh requests with an unsequenced `SEQUENCE_EXHAUSTED` infrastructure error. It may still return cached results for existing request keys. Never wrap or restart the counter.

### 4.3 Instrument and order types

Only `SIM` is supported. Every command must name the instrument. New orders contain side `buy` or `sell`, positive integer limit price, and positive integer quantity. Orders remain active until fully filled or cancelled. There is no expiry or wall-clock scheduling.

Self-trading is allowed in version 1 and must be explicitly documented. A client may match with its own resting order. Self-trade prevention is a future semantics change, not an incidental filter.

### 4.4 Matching priority

A buy order crosses when its limit is greater than or equal to the best ask. A sell order crosses when its limit is less than or equal to the best bid. Select the best opposite price first: lowest ask for a buy, highest bid for a sell. Within that level select the oldest still-active order by its original acceptance sequence.

Trade quantity is `min(incoming_remaining, resting_remaining)`. Trade price is the resting order's limit price. Reduce both remainders exactly once. Remove a fully filled resting order from the active index and queue. Delete its price level if empty. Continue until the incoming order is exhausted or no opposite order crosses. Append any incoming residual to the tail of its own side and price level.

A partially filled resting order retains its original FIFO position. An incoming residual receives priority from the incoming command's acceptance sequence. A cancellation never changes other orders' priority. Timestamps and lexical order IDs never determine priority.

### 4.5 Cancellation

A cancellation specifies `client_id`, `request_id`, `instrument`, and the client's local `order_id`. It cancels the entire currently resting remainder for that exact order key. An unknown order, a filled order, or an already cancelled order produces `ORDER_NOT_ACTIVE`. Cancellation cannot target another client's order key; there is no separate arbitrary target-owner field.

Cancelling the middle, head, tail, or only node of a queue must work. A cancellation emits no trade. Retrying the same cancellation request returns its original successful response even though the order is no longer active. A new request ID for that same cancellation produces `ORDER_NOT_ACTIVE`.

### 4.6 New-order rejection

For a well-formed first-seen new-order request, enforce business checks in this order:

1. Instrument equals `SIM`; otherwise `UNKNOWN_INSTRUMENT`.
2. Order key has not previously been accepted; otherwise `ORDER_ID_REUSED`.
3. Session has room for one additional accepted order record; otherwise `SESSION_ORDER_LIMIT`.

Field shape, valid side, numeric range, and ID validity are schema validation, performed before sequencing. A failed business check reserves the request key and sequence, but does not reserve an order key, emit a trade, or mutate the book.

For a first-seen cancellation, check instrument before looking up its order key. This gives deterministic rejection precedence.

### 4.7 Limits

Default configurable limits are 100,000 accepted order records per session, 200,000 unique sequenced requests per session, and 16 KiB per inbound JSON line. Store limits in the semantic configuration. Tests may deliberately use smaller values. Reference and candidate must use identical limits.

The order-record limit counts accepted orders for the whole session, including terminal orders. This intentionally bounds retained lifecycle metadata. A syntactically valid first-seen request when the unique-request limit has been reached returns unsequenced `SESSION_REQUEST_LIMIT`; no key is reserved. Existing retries and request-key conflicts must still be classified using the retained table before applying this capacity check.

These limits make memory growth explicit. Do not evict dedupe or terminal-order entries in version 1. A session is finite; starting a new session is the supported reset.

### 4.8 Order lifecycle

An accepted order has original quantity, filled quantity, cancelled quantity, remaining quantity, original side and price, acceptance sequence, and status `active`, `filled`, or `cancelled`. Always maintain:

```text
original_quantity = filled_quantity + cancelled_quantity + remaining_quantity
```

Active orders have positive remainder and zero cancelled quantity. Filled orders have zero remainder and zero cancelled quantity. Cancelled orders have zero remainder and positive cancelled quantity; they may also have earlier fills. A successful new order can begin and end in `filled` during the same transition.

## 5 Protocol and request handling

### 5.1 Input format

Use UTF-8 JSON Lines for workloads and interactive stdin. One complete request occupies one line. No comments or trailing commas are accepted. A blank line is a malformed record rather than an implicit command. Workload metadata belongs in a sidecar manifest, not in the command stream.

Example new order:

```json
{"schema_version":1,"type":"new","client_id":"alice","request_id":"r1","instrument":"SIM","order_id":"a1","side":"sell","price_ticks":"100","quantity":"10"}
```

Example cancellation:

```json
{"schema_version":1,"type":"cancel","client_id":"alice","request_id":"r2","instrument":"SIM","order_id":"a1"}
```

Required fields must be present exactly once. Reject unknown fields, duplicate JSON object keys, nulls, wrong JSON types, invalid UTF-8, excessive input size, and unsupported schema versions. Do not let a permissive JSON decoder silently choose the last duplicated key. Document parser behavior for EOF without a newline: a complete final JSON value is allowed in a workload file, while live interactive clients should terminate each request with a newline.

`schema_version` must be JSON integer 1, not boolean, string, or float. `instrument` is an ASCII identifier using the same ID syntax; an unknown but well-formed instrument reaches business validation. Business values are compared after strict parsing and normalization.

### 5.2 Validation layers

The pipeline is: byte framing; JSON parsing; schema validation; normalized semantic command; request-key lookup; capacity/sequence check; sequence assignment; durable append if applicable; deterministic transition; response emission.

Malformed input yields `PROTOCOL_ERROR` with a stable machine-readable subcode, no sequence, no request-key reservation, no journal entry, and no state change. Human details may vary, but the normalized protocol-error class must match the reference. Memory and durable stream drivers continue after a recoverable complete bad line. A line that exceeds the size limit is drained to its newline with bounded buffering before processing the next line. Fatal storage errors terminate the durable stream.

### 5.3 Idempotency

For a normalized command, derive the request key and a canonical payload containing all business fields except `request_id`; the key already contains `client_id`. Include `type`, `instrument`, order ID, and all type-specific values in this payload. Comparing the full canonical bytes is authoritative; a digest can accelerate lookup but must not replace collision-safe equality.

If the request key exists and payload bytes match, return the original semantic response and original sequence with `duplicate: true`. Do not allocate a new sequence, append another journal record, change state, or create new events. If the key exists and the payload differs, return unsequenced `IDEMPOTENCY_CONFLICT`; preserve the first payload and original result.

JSON key ordering and insignificant JSON whitespace do not create different payloads. Schema-invalid inputs do not qualify as retries, even when they contain an existing request ID. An identical business-rejected request must return the same rejection on retry, even if current state would now permit it.

### 5.4 Response envelope

Every input attempt produces one response line unless the process terminates or output transport fails. In memory mode an envelope looks like:

```json
{
  "schema_version": 1,
  "session_id": "demo",
  "client_id": "alice",
  "request_id": "r1",
  "seq": "1",
  "duplicate": false,
  "durability": "none",
  "result": {
    "status": "accepted",
    "command_type": "new",
    "order_id": "a1",
    "order_status": "active",
    "original_quantity": "10",
    "filled_quantity": "0",
    "remaining_quantity": "10",
    "cancelled_quantity": "0"
  },
  "events": []
}
```

Durable-mode envelopes use `durability: "synced"` only after the journal record has been synced and the transition completed. Business rejections use `result.status: "rejected"` and a stable `code`. Unsequenced protocol, conflict, or capacity errors use `seq: null`, `durability: "none"`, and `result.status: "error"`. Include client and request identity only when they were safely parsed; otherwise use null. Define schemas for every variant rather than optional fields with unclear meaning.

The cached semantic response includes original seq, result, and events. The transport wrapper supplies the mode and duplicate marker. A retry may repeat previously returned trade events in its cached response; those repeated events retain the same IDs and are not newly executed trades. Downstream analysis must count unique event IDs, not every delivery of an event.

### 5.5 Events

Only two event kinds are required: `trade` and `cancelled`. A resting new order with no fills emits an empty list. Its acceptance is already represented by the response and order ledger. A successful cancellation emits one cancellation event. A rejected command emits no events.

Events have an ID composed of `(session_id, seq, event_index)`, represented as separate fields. `event_index` starts at decimal string `"0"` for each command. Trades occur in exact matching order. Trade fields include instrument, resting order key, incoming order key, buyer order key, seller order key, resting price, and executed quantity. A cancellation event contains the order key and cancelled remainder. Do not use random UUIDs or wall-clock timestamps for semantic event identities.

### 5.6 Stream behavior

Stdout is reserved for machine-readable response or result JSON. Diagnostics, progress bars, and human logs go to stderr. Flush each live response line. Read-only commands emit a single JSON document or explicitly documented JSONL. Exit codes are stable and tested. Ctrl-C triggers orderly shutdown when possible; SIGKILL correctness must not depend on shutdown handlers.

## 6 Golden semantic walkthrough

Start a fresh session `golden` with no orders. Each row is a unique valid request unless marked retry. Prices are ticks and quantities are units.

| Attempt | Command | Sequence | Expected effect |
|---|---|---|---|
| 1 | Alice sells A1 at 100 for 10, request a1 | 1 | Ask A1 rests with 10 |
| 2 | Bob sells B1 at 100 for 7, request b1 | 2 | Ask B1 rests behind A1 |
| 3 | Carol buys C1 at 101 for 12, request c1 | 3 | Trade 10 with A1, then 2 with B1, both at 100 |
| 4 | Bob cancels B1, request b2 | 4 | Cancel the remaining 5; ask side empty |
| 5 | Retry Carol request c1 unchanged | Original 3 | Cached two trades; no new trade execution |
| 6 | Retry Bob request b2 unchanged | Original 4 | Cached successful cancellation |
| 7 | Bob cancels B1 with new request b3 | 5 | Rejected ORDER_NOT_ACTIVE |
| 8 | Bob submits new B1 with request b4 | 6 | Rejected ORDER_ID_REUSED |
| 9 | Reuse Carol request c1 with quantity 13 | null | IDEMPOTENCY_CONFLICT; no state change |

The next fresh sequence is 7. There are exactly two distinct trade events, IDs `(golden,3,0)` and `(golden,3,1)`, with total traded quantity 12. There is one cancellation event `(golden,4,0)` with quantity 5. Final book is empty. A1 and C1 are filled, B1 is cancelled, six request keys have sequenced cached results, and three order keys were accepted. Persist this fixture in both languages' tests.

Additional mandatory walkthroughs: a buy sweeping several ask prices; a sell sweeping several bid prices; a non-crossing bid and ask; an incoming partially filled residual; cancelling the middle of three equal-price orders; two clients using the same local order ID; and a rejected cancellation retried after an order with that target ID is later accepted. The retry must preserve the earlier rejection.

## 7 Data structures and complexity

### 7.1 Independent reference

The Python engine should be deliberately simple. Store order lifecycle records in a dictionary. To match, scan active opposite-side orders and sort eligible candidates by best price and acceptance sequence. Avoid sharing candidate queue, selection, or mutation helpers with OCaml. Its slowness is acceptable; clarity and independence are the point.

Use Python dataclasses or equivalent explicit records. Implement request handling and business validation independently. Sharing protocol fixtures and declarative schema documentation is allowed. Sharing a generated algorithm or copying the same data-structure implementation is not.

### 7.2 Optimized OCaml book

Use an ordered price map per side. Each price maps to a doubly linked FIFO queue of live order nodes. Maintain a hash index from order key to node for cancellation. Retain a separate order ledger for terminal state and reused-ID checks. Maintain queue head, tail, size, and aggregate remaining quantity. A node references its level and previous/next node, with all mutations confined to the book implementation.

Standard OCaml immutable maps can store mutable level records. The map structure changes only when levels are created or removed. If a different structure is chosen, explain the expected complexity and demonstrate equivalent FIFO and cancellation behavior.

### 7.3 Complexity expectations

Let L be active price levels, N active orders, and F resting orders filled by one incoming command. Inserting a new level or deleting an empty level is typically O(log L). Hash-index lookup is expected O(1), not a worst-case guarantee. Removing a node from a nonempty level is O(1). Cancellation is expected O(1) plus O(log L) if its level is deleted. A straightforward matching loop can cost O(F log L) plus residual insertion; do not advertise O(F + log L) without showing how best-level access and level removal achieve it.

Full state export, invariants, canonical hashing, and JSON output are not constant-time. Keep them out of core benchmark loops. Report serialization and durability separately.

### 7.4 Pointer and index invariants

Every active order appears in exactly one live queue and exactly one active index entry. Head has no predecessor; tail has no successor. Walking forward and backward yields consistent order membership and terminates. Empty queues have no head or tail and must not remain in the price map. Queue length and aggregate quantity equal a fresh traversal. Nodes in one level share side and price. FIFO acceptance sequences strictly increase within a level. Terminal orders have no active index entry or queue node.

### 7.5 Memory lifecycle

Clear removed nodes' neighbor links so old nodes do not keep entire queues reachable unnecessarily. The retained terminal-order ledger and request cache are intentionally session-sized. Benchmark reports must include these retained entries, not just the active book. Do not describe memory as O(N active orders) when dedupe and lifecycle history are retained.

## 8 Determinism and canonical state

### 8.1 Deterministic inputs

Determinism is defined for the same semantics version, semantic configuration, session ID, and ordered stream of normalized commands. An observed execution with different admission order is a different input history. Client delays may change the arrival order; the sequencer's actual order is authoritative.

No semantic output includes elapsed time, PID, machine hostname, compiler version, random hash-table seed, memory address, or wall-clock timestamp. Keep such provenance in a separate run manifest.

### 8.2 Canonical JSON subset

Specify a restricted canonical encoder shared by contract, not necessarily by code: UTF-8; no whitespace; object keys sorted lexicographically by ASCII bytes; array order preserved; strings use JSON escaping with lowercase `\u00xx` for control bytes; no escaping of ordinary ASCII; no Unicode identifiers; integers permitted only for schema-version fields; domain numerics encoded as validated decimal strings; literal `true`, `false`, and `null` as needed.

Do not call an arbitrary JSON serializer output canonical without cross-language byte fixtures. Explicitly test escaping, key order, null, and empty arrays. Semantic canonical objects contain only defined fields. Operational diagnostic messages are not canonical data.

### 8.3 State exports

Provide two projections:

1. `book_state`: active bids descending by price, active asks ascending, each level's orders in FIFO order, order key, acceptance sequence, and remaining quantity.
2. `session_state`: session ID, versions, semantic configuration, last applied sequence, next sequence or exhausted marker, full sorted order ledger, sorted request cache with canonical payload and semantic response, event count, and a rolling semantic event digest.

Sort order ledger entries by `(client_id, order_id)` and request entries by `(client_id, request_id)`. Include sufficient data to distinguish apparently identical books that differ in future behavior. Book-only equality cannot verify idempotency or reused-ID rules.

Persist cached responses as they were originally generated. Do not reconstruct their quantities from the current order ledger; a resting order may have filled since its original acceptance response.

### 8.4 Hash definitions

Compute SHA-256 over canonical encoded projection bytes and expose hex digests. Initialize the event-history digest as SHA-256 of an explicitly specified domain string such as `replaylab-events-v1`. Update once per newly emitted semantic event as SHA-256 of `previous_digest_raw || length_u64_be || canonical_event_bytes`. Retries do not update it. Specify raw digest bytes versus displayed hexadecimal unambiguously and include cross-language test vectors.

Hashes are comparison aids. On mismatch, compare full canonical fields and explain the first difference. Tests must not treat equality of hashes as a substitute for useful diagnostics. Routine production-mode matching must not rehash the full session state after every command.

## 9 Journal and durability design

### 9.1 Durable decision point

For each first-seen schema-valid request admitted under session limits, assign the next sequence, serialize its normalized command, append one complete frame, and successfully sync the journal. Then apply the transition, cache its outcome, and emit the response. Business-rejected commands are journaled because their sequence and cached rejection affect future behavior. Protocol errors, retries, conflicts, and unsequenced infrastructure errors are not journaled.

The successful journal sync is the durable decision point. A frame may become durable before a response is delivered. Therefore unacknowledged does not mean absent. Recovery may apply an unacknowledged complete command; a client resolves uncertainty by retrying the same request key and payload.

An acknowledgement means the complete response line was observed by the client or test controller. Internally, emitting it is permitted only after successful sync and application. Stdout flushing is not a durability mechanism for the journal.

### 9.2 Failure during transition

All expected business rejection paths are defined results, not exceptions. If an unexpected exception occurs after a frame is durable, terminate the session with a diagnostic and do not process another command. Do not skip the frame or roll the sequence back. Recovery will retry the deterministic transition and may expose the same bug; preserve the journal for debugging.

A process crash in the middle of a mutable transition cannot expose partial state on recovery because the in-memory state is discarded and the full command is replayed from the last complete state. Never write a snapshot midway through a command.

### 9.3 Session directory

```text
session/
  metadata.json
  writer.lock
  commands.wal
  snapshots/
    snapshot-00000000000000000100.bin
  diagnostics/             # optional operational records
```

The journal is authoritative. Derived output files and diagnostics are not transaction participants. If an exported event file is lost or incomplete, regenerate it from the journal. Do not create a separate authoritative trade log requiring an undeclared multi-file transaction.

Create and sync metadata and initial journal safely before serving requests. Sync their parent directory as needed for durable file creation on the supported platform. Acquire an exclusive OS-level advisory lock for the session writer. A stale lock filename must not block recovery after process death; the lock is held by the OS, not inferred solely from file existence. A second writer must fail before modifying anything.

Version 1 uses a single journal file without rotation or compaction. This substantially simplifies correctness. Retaining all journal entries is intentional. Document storage growth and leave segmented logs to a later version.

### 9.4 Frame format

Freeze a simple binary framing format and provide a written byte-level specification:

| Field | Encoding | Meaning |
|---|---|---|
| Magic | 4 literal ASCII bytes `RPLB` | Frame start |
| Frame version | unsigned 16-bit big endian | 1 |
| Payload length | unsigned 32-bit big endian | Canonical JSON payload byte length |
| Payload | exactly stated number of bytes | Sequence plus normalized command |
| Checksum | 32 raw bytes | SHA-256 of header and payload |

Frame payload includes journal schema version, semantic version identifier, sequence, request key, and normalized command. Session identity/configuration are fixed in metadata and validated by a session identity hash in each payload or a mandatory journal header. Choose the per-payload identity hash for version 1 to avoid an additional header format.

Maximum frame payload is 64 KiB. Check the bound before allocating. A syntactically complete frame whose declared length, checksum, sequence, identity, or payload schema is invalid is corruption. The checksum detects accidental damage, not malicious tampering. No security claim is implied by using SHA-256.

### 9.5 Writing frames

Use low-level writes or a rigorously flushed buffer. Handle short writes and interrupted system calls. A zero-byte write before completion is an error. Retry `EINTR` where appropriate; do not retry indefinitely after disk-full, permission, or I/O failures. After an append or sync failure, stop accepting commands and do not return a successful response for the affected request.

The normal durability mode syncs every new journal frame. Group commit is optional future work. Do not implement a misleading `durable=true` mode that syncs only at shutdown. Any experimental no-sync mode must have a different label and must never satisfy durable acceptance tests.

### 9.6 Journal scanning and truncated tails

Replay frames from byte zero, validate checksums, and require contiguous sequences beginning at 1. Reject gaps, duplicates, wrong session identity, unsupported versions, and invalid normalized commands. No search-ahead resynchronization is allowed: do not skip damaged bytes to find another magic header.

An EOF in an otherwise well-formed final frame is an incomplete tail. Read-only verification reports its byte offset and does not mutate the file. Recovery for continued writing may explicitly repair only this incomplete tail by truncating to the last validated frame boundary and syncing the truncation before further append. Expose this behavior through a clear `--repair-incomplete-tail` option.

A checksum mismatch in a complete final frame is corruption, not a safely repairable incomplete tail. Fail closed and preserve the file. This distinction deliberately favors explicit corruption detection over guessing which bytes were safe. Every truncated-tail test operates on a copied session artifact.

### 9.7 Recovery contract

Recovered logical state equals deterministic replay of the valid authoritative journal prefix, optionally accelerated by a compatible validated snapshot. Every observed acknowledged unique request must exist in that prefix with the same cached outcome. Additional complete unacknowledged frames may exist. Recovery rebuilds request caches, order history, FIFO priority, sequences, and event digests, not only active book levels.

Do not claim process-kill tests prove behavior under physical power loss. A process crash leaves OS caches alive. Test a separate simulated-storage model that permits dropping unsynced suffix bytes while preserving synced prefixes. Document the filesystem and hardware assumptions behind real fsync behavior.

## 10 Snapshots

### 10.1 Purpose and scope

A snapshot saves full semantic session state at a completed command boundary. It accelerates rebuilding queues, order records, and request cache. Version 1 retains the full journal and validates journal framing/checksums even when a snapshot is used; benchmark reports must acknowledge this remaining scan cost.

### 10.2 Snapshot contents

Include format version, semantics version, session ID, configuration hash, last applied sequence, journal byte offset just after that sequence, checksum of the boundary frame or an explicit empty-prefix marker, complete canonical session state, canonical state digest, and a checksum over the snapshot envelope. The state must preserve cached original responses and full deduplication payloads.

Do not serialize raw pointers, object addresses, OCaml closures, or a language-specific opaque runtime heap. Serialize semantic records. Rebuild mutable queue links and hash indexes on load and then validate all invariants.

### 10.3 Atomic publication

Pause command admission at a completed transition. Write a uniquely named temporary snapshot in the same directory, flush it, sync the file, close it, rename to its final sequence-based filename, and sync the snapshots directory. Temporary files are ignored by recovery. Do not replace an existing snapshot with different bytes at the same sequence without treating that as an error.

A snapshot error can be reported while the command journal remains usable, provided the journal itself is healthy. An explicit snapshot CLI operation returns a nonzero exit on failure. Do not silently announce that a snapshot was saved.

### 10.4 Choosing and validating snapshots

Examine published snapshots from newest sequence downward. Validate checksum, versions, configuration, boundary frame identity, journal coverage, and state invariants. A snapshot may not be ahead of the validated journal prefix. If the newest snapshot is damaged, warn and try an older valid snapshot or full replay. Journal corruption remains fatal even if a snapshot seems usable; do not let snapshot fallback hide an authoritative-log error.

Replay only commands after the selected snapshot sequence. Verify the restored state against full replay in tests. An empty snapshot at sequence 0 is valid. Snapshotting twice with no new commands must either reproduce identical bytes or recognize the identical existing artifact.

## 11 Crash injection and failure experiments

### 11.1 Deterministic hooks

Expose named test-only crash hooks selected by unique command sequence and hook name. Hooks must not alter normal command semantics. Required locations:

| Hook | Crash location | Expected recovery |
|---|---|---|
| `before_append` | Before writing a new frame | Current request absent |
| `after_partial_append` | After a chosen strict prefix of frame bytes | Incomplete tail repair needed |
| `after_append_before_sync` | Full frame written, sync not complete | Complete request may be recovered; no acknowledgement guaranteed |
| `after_sync_before_apply` | Journal synced, transition not run | Request must be recovered |
| `during_match_after_first_fill` | First fill applied, command not finished | Replay reconstructs whole command exactly once |
| `after_apply_before_response` | State updated, response not emitted | Retry returns cached recovered outcome |
| `after_response` | Complete response flushed | Acknowledged outcome preserved |
| `snapshot_after_file_sync` | Temp snapshot synced, rename not done | Temp ignored; journal recovers |
| `snapshot_after_rename` | Rename done, directory sync pending | Valid visible snapshot or journal fallback |

Not every hook is reachable for every command. The harness must report “hook not reached” as an invalid experiment, not a successful crash test. Snapshot hooks use a snapshot sequence rather than pretending a snapshot is a trading command.

### 11.2 Process controller

The Python harness starts a child process in a fresh test directory, sends commands, collects fully observed response lines, and reads hook notifications on a separate test control pipe. At the requested hook, the child blocks on the control pipe and the parent sends SIGKILL. This handshake makes the kill location reproducible. A simplified child `_exit` hook may be added, but at least one required suite must use a real externally killed process.

Never identify the victim by a broad process-name match. Kill only the exact child PID owned by the test. Apply subprocess timeouts and preserve stderr. Save all input, output, hook, and recovery artifacts.

### 11.3 Correct crash oracle

After the crash, scan the journal and identify its valid command prefix. Compare recovered state and semantic events against reference replay of that prefix. Check separately that all acknowledged request keys are in it. Then resume with retries of uncertain submitted requests followed by the remaining workload and compare with an uninterrupted run under the same defined logical admission order.

The baseline must not assume every sent request was committed. Use a single outstanding client request for the first crash suite so order is unambiguous. Later multi-client schedules must record actual admission order and compare that order, not the originally intended schedule.

A retry at the crash boundary may be either a fresh admission if its frame was absent or a duplicate if its complete frame survived. Both are legal if the final logical effect occurs once and acknowledged results are preserved.

### 11.4 Simulated storage model

Create a storage adapter for unit tests with separate volatile appended bytes and a durable prefix. Successful sync advances the durable prefix. Simulated power loss discards any unsynced suffix; optionally generate allowed prefixes of unsynced bytes. Model short writes, interrupted writes, sync failure, and disk-full. Keep this adapter out of performance measurements and distinguish its evidence from physical hardware testing.

### 11.5 Other scheduled disturbances

Duplicate requests by exact request key and payload, drop a response, delay a request before admission, or delay a response after execution. The workload manifest records each disturbance. A response drop must not roll back an executed command. Do not reorder already sequenced commands. Request-delay experiments should make changed admission order visible in their report.

## 12 Differential checking

### 12.1 Comparison levels

Run the reference and candidate on the same byte-level workload and configuration. Compare normalized protocol errors for malformed lines. For valid attempts compare sequence/null, duplicate marker, semantic result, and event arrays. Normalize only explicitly nonsemantic transport fields such as memory versus durable label. Never sort trade events or ignore quantities to obtain agreement.

In small property runs compare full session state after every attempt. In larger runs compare outputs at every attempt and full state at configurable checkpoints plus the end. When a discrepancy occurs, rerun the failing prefix with per-attempt state export to locate the earliest state divergence.

### 12.2 Failure artifacts

Each saved failure directory contains `workload.jsonl`, `manifest.json`, `reference.jsonl`, `candidate.jsonl`, `difference.json`, `reference-state.json`, `candidate-state.json`, stderr files, relevant configuration, seed, generator version, candidate commit/build identifier, and an exact reproduction command. If persistence is involved include copied session data and fault schedule. Do not require a live network service to reproduce the failure.

### 12.3 Difference report

Report the first differing attempt, logical sequence if any, command, semantic path such as `events[0].quantity`, expected value, observed value, and a stable failure signature. Include a short book excerpt before and after the divergence. A report that says only “hash mismatch” is incomplete.

Classify failures as protocol mismatch, business-decision mismatch, event mismatch, state mismatch, invariant violation, candidate crash, or timeout. A timeout is not automatically evidence of semantic incorrectness and should not be shrunk using a semantic mismatch predicate.

### 12.4 Avoiding shared bugs

Cross-language agreement is useful but insufficient. Both implementations could misunderstand the specification. Hand-worked golden fixtures, conservation properties, independently written parsing edge tests, crash-prefix oracles, and deliberate bug mutants provide independent evidence. Generated expected output from the candidate must never be the only oracle.

## 13 Workload generation

### 13.1 Deterministic generator

Implement workload generation in Python only. Record seed, generator version, full configuration, output SHA-256, and number of commands in a manifest. Replay uses the saved workload bytes; it does not assume that regenerating with a future Python version will yield identical bytes. If exact cross-version generator behavior is promised, specify and implement a fixed PRNG algorithm and add frozen vectors.

Maintain a lightweight model when generating valid cancellations or deliberate fills. Also support adversarial generation that deliberately references inactive orders or conflicts with existing request keys. The generator must not depend on the optimized OCaml candidate's state to choose the next test input.

### 13.2 Profiles

| Profile | Characteristics | What it stresses |
|---|---|---|
| balanced | Mix of resting orders, crossing orders, and cancellations | General behavior |
| deep-level | Many orders at the same price | FIFO and arbitrary unlinking |
| many-levels | Many small price levels | Ordered-map changes |
| sweep | Incoming orders consume several orders and prices | Matching loop and event ordering |
| cancellation | Frequent head, middle, tail, and stale cancellations | Active index and queue integrity |
| retries | Identical retries, conflicting keys, rejected retries | Idempotency |
| sparse-cross | Mostly non-crossing orders | Book growth and retained memory |
| hot-cross | High match rate with little resting depth | Trade-heavy path |
| malformed | Invalid lines mixed with recoverable valid requests | Parser isolation and bounded buffers |
| recovery | Commands selected to reach each crash hook | Persistence boundaries |

Default balanced configuration can begin at 60% new requests, 20% cancellations, 10% exact retries, 5% conflicts, and 5% deliberately malformed attempts. Treat these as generator operation categories; document how categories behave when there is no previous request or active order to select. Use deterministic fallback choices and record realized counts.

### 13.3 Scale bands

Use tiny runs of 0–100 attempts for exhaustive and shrinking tests, medium runs of 1,000–10,000 for regular differential checks, and larger runs of 100,000 or more only with session limits adjusted and recorded. A 100,000-command independent reference run may be expensive; batch/checkpoint it and measure its runtime. Benchmark workloads can be much larger than the reference suite, but must first be semantically validated at appropriate smaller scales.

## 14 Failure shrinking

### 14.1 Required behavior

Given a reproducibly failing workload and failure signature, produce a smaller workload that still triggers that same class of semantic failure. First retain the earliest failing prefix. Then delete chunks using delta debugging, reduce individual commands, and simplify numeric and identity values when valid. Save both the original and minimized artifacts.

Call the result “reduced reproduction” by default. Call it “1-minimal under deletion” only after checking that removing any single remaining command no longer preserves the failure. Do not call it globally minimal: deletion plus local simplification does not prove that.

### 14.2 Failure predicate

Run both engines fresh for every candidate. A candidate preserves the failure when it reaches the intended semantic mismatch class and signature. Normalize shifting sequence numbers, event IDs, and attempt indices out of the signature where appropriate. Preserve meaningful properties such as mismatch path category, invariant name, command type, and direction of numeric difference.

If the original bug is a FIFO mismatch, an unrelated parse error or generic process crash must not count as preservation. Record the predicate in `difference.json` so future users know what was minimized.

### 14.3 Dependencies

Removing a new order may cause a later cancellation to be rejected. Removing an original request may turn a retry into its first submission. Such candidates are allowed if they remain valid for the target failure predicate. Prefer dependency-aware deletion groups for request families and order lifecycles, but still evaluate outcomes rather than assuming syntactic dependencies imply semantic necessity.

For ID simplification, rename complete equivalence classes consistently across new orders, cancellations, and retry families. Keep different clients distinct unless merging them preserves the same signature. Do not change one duplicated request payload while leaving its alleged identical retry unchanged unless testing that change intentionally.

### 14.4 Numeric simplification

Try smaller positive quantities, quantities around fill boundaries, and prices around equality/crossing boundaries. Candidate values may include 1, one less than current, half, and adjacent relevant opposing prices. Preserve the allowed numeric range. Do not blindly set every price to 1; the target bug may require price ordering.

### 14.5 Crash shrinking

Represent fault placement by a stable target request key, hook name, and hook occurrence within the command, rather than an absolute sequence that changes after deletion. Translate it to the new sequence for each candidate run. A candidate whose crash hook is unreachable is not a preserved failure. Use separate process directories so repaired journals from one candidate cannot affect another.

### 14.6 Budget and reproducibility

Support `--max-evaluations`, `--timeout-seconds`, deterministic candidate ordering, candidate-hash memoization, and subprocess timeouts. Record evaluations attempted, cache hits, elapsed time, original/final command count and bytes, and whether 1-minimality was verified or the budget was exhausted. Re-run the final candidate at least three times to confirm the claimed deterministic semantic signature.

### 14.7 Deliberately faulty engines

Create isolated test-only mutants for at least: LIFO at equal price, incoming-price execution instead of resting price, incorrect middle-node cancellation, and missing duplicate suppression. Each mutant should be detected by a targeted fixture. At least one generated larger workload must be shrunk automatically into an understandable reproduction. The normal release binary must not silently enable a mutant through a generic environment variable; keep mutants in a test executable or explicit test-only build target.

## 15 Invariants and property tests

### 15.1 Book and lifecycle properties

- After every completed command, best bid is strictly less than best ask when both sides are nonempty.
- All active remainders are positive and all stored quantities are within checked bounds.
- Each accepted order satisfies original = filled + cancelled + remaining.
- A trade's price equals the resting limit and satisfies both buy and sell limits.
- Trade quantities are positive and never exceed either pre-trade remainder.
- Price priority precedes FIFO priority; FIFO uses original acceptance sequence.
- Cancellation reduces active remaining quantity by exactly its event quantity and creates no trade.
- The active index, price levels, queues, and lifecycle ledger agree.
- Sum of filled quantities across all accepted orders equals twice the sum of unique trade quantities.
- Sum of accepted original quantities equals twice unique traded quantity plus cancelled quantity plus current active remaining quantity.

### 15.2 Protocol and session properties

- Identical retry leaves complete session semantic state unchanged.
- Conflicting retry leaves complete session semantic state unchanged.
- Schema-invalid attempts leave complete session semantic state unchanged.
- Business rejection changes sequence/cache state but not book/order lifecycle state.
- An accepted order ID remains reserved after terminal state.
- Fresh admitted commands have contiguous sequences; retries report original sequences.
- Different JSON key orders produce the same normalized request payload.
- A retry after snapshot recovery produces the original result, not a result recomputed from current book state.

### 15.3 Persistence properties

- Fresh full replay equals uninterrupted execution.
- Snapshot plus suffix replay equals full replay.
- Every observed acknowledged request survives recovery under the stated failure model.
- A surviving unacknowledged frame has exactly one logical effect after retry.
- Repeated recovery without new input yields the same canonical session state.
- Incomplete-tail repair followed by append produces a valid contiguous journal.
- Corruption is reported without silently skipping or rewriting valid preceding records.
- A second writer cannot acquire the same session lock.

### 15.4 Metamorphic checks

Insert an exact retry anywhere after its original request: final semantic state must remain unchanged, though the response stream gains a delivery. Replace all client and order identities using an injective consistent renaming: matching quantities and prices remain the same, with identities renamed. Shift all prices by a positive offset within bounds: trade quantities/order priority remain the same and trade prices shift by that offset. Concatenate workload A then B in one session versus pause/recover after A then execute B: results must agree.

Do not claim arbitrary command permutation preserves results; order is the key semantic input.

## 16 Test suite and release gates

### 16.1 Named test categories

| Prefix | Required coverage |
|---|---|
| SEM | Price/time priority, partial fills, sweeps, residuals, cancellation lifecycle |
| PRO | Schema variants, duplicate JSON keys, numeric bounds, malformed lines |
| IDE | Exact retries, conflicts, rejected retries, retries after terminal state |
| STR | Queue links, empty level deletion, active index, retained history |
| DET | Byte-identical canonical state across runs and hash seeds |
| WAL | Partial writes, frame boundaries, checksums, contiguous sequences |
| SNP | Empty snapshot, mid-session snapshot, damaged snapshot fallback |
| CRS | Every reachable process-crash hook and simulated storage failure |
| DIF | Cross-language fixtures and seeded random comparisons |
| SHR | Mutant detection, signature preservation, reduction and minimality status |
| CLI | Exit codes, stderr/stdout separation, recovery arguments |
| BEN | Benchmark schema/provenance validation; no fabricated measurements |

At least one direct golden test must cover each normative rejection code and validation precedence. Include boundary tests at numeric maximum, zero, negative input, capacity limits, and sequence exhaustion through a test constructor rather than billions of requests.

### 16.2 Journal corruption matrix

Test truncation at each byte boundary of a small multi-frame journal. For complete preceding frames plus an incomplete final frame, recover the prefix only with the documented repair option. Test flipped magic, unsupported frame version, length above the bound, payload bit flip, checksum bit flip, valid-checksum wrong sequence, wrong session identity, and valid-checksum invalid semantic payload. Complete corrupted frames must fail verification. Include a middle-frame corruption with valid later frames to prove the scanner never resynchronizes by skipping damage.

### 16.3 CI tiers

Pull-request CI runs formatting, build, unit tests, golden comparisons, approximately 20 seeded medium-small differential runs, targeted process crashes, snapshot tests, and a shrinker smoke test. Tune exact lengths to a practical budget while keeping deterministic seeds committed.

A manually runnable deep suite runs at least 100 seeds across profiles, all crash hooks, byte-boundary truncation tests, and multiple mutants. If scheduled CI is configured, avoid dependencies on external credentials. Benchmarks may run in CI as smoke tests, but noisy shared-runner timings are not release performance claims.

### 16.4 Test isolation

Every persistence test owns a fresh temporary directory. Fixtures are copied before mutation. Process tests reap children and close pipes on success, failure, and timeout. Tests must not delete arbitrary paths, reuse a real user session directory, or leave a background server running.

## 17 Command line interface

### 17.1 Required commands

Implement these stable behaviors; argument spelling may only change with matching documentation and demo updates:

```bash
replaylab run --mode memory --session-id demo --input workload.jsonl \
  --responses responses.jsonl --state-out state.json

replaylab run --mode durable --session-dir runs/demo --session-id demo \
  --input workload.jsonl --responses responses.jsonl

replaylab stream --mode durable --session-dir runs/live --session-id live

replaylab verify-log --session-dir runs/demo

replaylab replay --session-dir runs/demo --state-out replayed.json \
  --events-out events.jsonl

replaylab recover --session-dir runs/demo --repair-incomplete-tail \
  --input remaining.jsonl --responses recovered-responses.jsonl

replaylab snapshot --session-dir runs/demo

replaylab inspect --session-dir runs/demo --view book

replaylab inspect --session-dir runs/demo --view session

python -m replaylab_tools generate --profile balanced --seed 42 \
  --count 10000 --out workload.jsonl

python -m replaylab_tools compare --candidate ./_build/default/bin/main.exe \
  --workload workload.jsonl --session-id demo --out artifacts/comparison

python -m replaylab_tools shrink --failure artifacts/failure \
  --max-evaluations 2000 --timeout-seconds 300 --out artifacts/reduced

python -m replaylab_tools crash-check --candidate ./_build/default/bin/main.exe \
  --workload fixtures/golden/recovery.jsonl --schedule demos/crash-plan.json \
  --out artifacts/crash-demo

python -m replaylab_tools benchmark --config workloads/configs/benchmark.json \
  --out benchmarks/results/local-run
```

`run --mode durable` creates a new session and refuses an existing nonempty session path. `recover` is the explicit route for continuation. `replay`, `verify-log`, and `inspect` do not repair or mutate journals. `snapshot` obtains the writer lock and may reconstruct current state before publishing a snapshot. Paths are literal arguments, never shell-evaluated strings.

### 17.2 Exit codes

Use 0 for successful operation, 1 for an observed comparison/invariant failure, 2 for CLI/configuration misuse, 3 for storage corruption or I/O failure, and 4 for test timeout or incomplete experiment. Streamed business rejection is a normal processed result and does not by itself force process failure. A `run --fail-on-protocol-error` option may make malformed input fail the batch; default behavior continues and counts it in the run summary.

### 17.3 Convenience targets

Provide `make setup`, `make build`, `make test`, `make check`, `make test-deep`, `make demo`, `make demo-crash`, `make demo-shrink`, and `make bench`. `make setup` should explain or install project-local dependencies using the documented toolchain, not overwrite global user configuration. A developer must be able to run the demos after setup without inventing commands from internal source code.

## 18 Benchmarking methodology

### 18.1 Questions to answer

Measure how data-structure choices affect matching, what serialization costs, what synchronous journaling costs, how recovery scales, and how efficiently the shrinker reduces actual failures. The goal is credible comparisons, not a predetermined number of orders per second.

### 18.2 Separate benchmark families

| Benchmark | Included | Excluded |
|---|---|---|
| Book kernel | Prevalidated unique command matching and cancellation | Parsing, dedupe, full-state export, storage |
| Memory session | Typed session processing including dedupe and event creation | File durability and Python controller time |
| JSON batch | Parse, validate, execute, serialize | Sync durability |
| Durable session | New request journal append, sync, apply, response | External network |
| Recovery | Journal scan, snapshot validation/load, suffix replay | Workload generation |
| Shrinking | Predicate runs and reduction passes | Original failure generation unless separately reported |

Only compare like-for-like modes. Do not show a durable-mode result beside a kernel result and label the difference an implementation speedup.

### 18.3 Experimental procedure

Use pre-generated saved workloads. Record workload hash, configuration, semantics version, commit SHA or explicit dirty-tree marker, compiler/build flags, dependency versions, CPU, core count, RAM, OS, filesystem for durable runs, storage device information when available, and timestamp. Missing environment information should be marked unknown.

Build optimized native code. Separate warm-up from measured runs. Use at least five measured repetitions for the main comparison. Reset state between repetitions. Randomize or alternate candidate order when comparing two implementations to reduce drift. Avoid generating commands, computing full session hashes, printing each command, or running the reference in the measured kernel loop.

Measure total elapsed time with a monotonic clock. Report processed attempts/second, unique sequenced commands/second, accepted orders/second, trades/second, and rejection/duplicate counts so the workload mix is visible. If recording per-command latency, define exact start/end boundaries and account for timer overhead. A closed-loop stdin driver measures service/request-response latency under its own offered load, not a full open-loop load test.

### 18.4 Latency and memory

Report median, p95, p99, maximum, and sample count with the percentile calculation documented. Persist raw samples or a documented histogram. A batch elapsed time divided by command count is an average; it cannot yield p99 latency. Do not infer tail latency from aggregate throughput.

Report peak resident memory with platform caveats, OCaml allocation/GC statistics when available, active orders/levels, total accepted order records, and dedupe entry count. Do not confuse OCaml heap size with full process RSS. Do not assert a leak solely because retained session history increases memory.

### 18.5 Charts and conclusions

Generate static charts from saved numeric results: throughput by mode/profile; latency distribution or percentile comparison; recovery time versus journal size with and without snapshots; and shrinker command-count reduction with evaluations/time. Every chart includes units and benchmark scope. Use log axes only when labelled. Clearly distinguish measured results from unexecuted examples.

There is no hard performance threshold for the first release beyond completion on documented local resources. Correctness is a gate; performance is evidence. After a baseline exists, set a hardware-specific regression budget in an ADR if useful.

## 19 Observability and artifacts

Operational logs should include level, component, operation, sequence when known, and stable error code. Wall-clock timestamps are allowed in these logs because logs are outside deterministic semantics. Avoid logging entire large workloads by default.

Run summaries include input attempts, protocol errors, duplicates, conflicts, business rejections, unique sequenced commands, accepted orders, unique trades, cancellations, last applied sequence, and final book/session hashes. Operational attempt counters may differ after retries or recovery; do not include them in canonical session state unless they are defined as journal-derived logical counters.

The event count and rolling digest in semantic state count only newly emitted events from unique sequenced transitions. Comparison tools must distinguish unique execution from repeated response delivery.

Failure artifact writes should use clear directory names, refuse accidental overwrite by default, and record incomplete runs. Large generated artifacts belong in ignored output directories; commit only selected small golden and regression fixtures. Publish performance results only when the user explicitly chooses to publish the repository or results.

## 20 Security and operational boundaries

The required product is a local research tool, not a public server. Do not add a network listener by default. Validate file sizes and framing lengths before allocation. Pass subprocess arguments as arrays, not interpolated shell strings. Run untrusted benchmark workloads only within finite configured limits and subprocess timeouts.

Session metadata and workload files are untrusted inputs for parsing. Never use data from them to execute code, import arbitrary modules, or invoke shell commands. Reject path traversal if any future artifact format contains file paths. Do not place credentials in fixtures or commit environment files.

A local advisory lock prevents cooperating duplicate writers; it is not a distributed lock. Checksums detect corruption; they do not authenticate the data. A single local disk is a single failure domain. State these limitations plainly in `docs/limitations.md`.

## 21 Implementation milestones

### M0 Repository and executable foundation

Inspect existing files and instructions. Create project skeleton, reproducible toolchain metadata, CLI stub with real `--help`/version, a tiny OCaml unit test, Python package/test setup, formatting targets, CI skeleton, and progress log. Record supported environment and actual successful commands. Exit gate: clean build and tests from documented setup; no simulated compiler output.

### M1 Contract and independent reference

Write protocol schemas, semantic documentation, canonical encoding fixtures, the Python reference session engine, and hand-calculated golden tests. Implement validation, order lifecycle, idempotency, limits, deterministic events, state exports, and rejection precedence. Exit gate: golden walkthrough and invariant tests pass; all response variants are documented; request/order scope is unambiguous.

### M2 OCaml domain and correct engine

Implement typed validated values, book queues, index, session wrapper, checked arithmetic, canonical exports, and memory-mode CLI. Begin with correctness even if optimization is incomplete. Add tests for queue unlink cases, FIFO, fills, rejection, and retries. Exit gate: candidate matches the reference on all golden fixtures and a small seeded corpus.

### M3 Differential harness and workload generation

Implement saved manifests, profiles, comparison modes, first-divergence diagnostics, invariant instrumentation, and failure artifacts. Add cross-language canonical byte/hash vectors. Exit gate: at least 20 deterministic seeds pass at a documented size; a deliberate FIFO mutant fails with useful saved evidence.

### M4 Journal and replay

Implement session metadata, writer locking, binary frame codec, short-write-safe append, sync-before-response, strict scanner, read-only replay, incomplete-tail repair, and fatal storage error behavior. Exit gate: memory and replayed durable execution agree; corrupted complete frames are rejected; all tiny-journal truncation boundaries are classified; second writer fails safely.

### M5 Recovery and snapshots

Implement full semantic snapshot codec, atomic publication, compatibility validation, restore, and explicit continuation. Add rejected-request cache and post-fill retry snapshot cases. Exit gate: snapshot plus suffix equals full replay; damaged snapshot falls back; journal corruption stays fatal; original responses survive restore.

### M6 Crash and simulated storage experiments

Implement child-process handshake hooks, targeted SIGKILL, uncertain-request retries, valid-prefix oracle, and simulated volatile/durable storage. Exit gate: each applicable hook reached and verified; acknowledged outcomes preserved; partial-match crash does not duplicate trades; reports distinguish process crashes from power-loss simulation.

### M7 Shrinker and debugging demo

Implement earliest prefix extraction, chunk deletion, per-command simplification, dependency handling, signature predicates, memoization, budgets, and crash-hook retargeting. Exit gate: at least one large mutant failure is reduced automatically and reproduced three times; report accurately states minimality/budget status; corrected engine passes the reduced case.

### M8 Performance measurements

Add kernel/session/JSON/durable/recovery benchmarks, raw results, environment metadata, repeated-run summaries, and generated charts. Profile before optional optimization. Any algorithm change reruns semantic and crash gates relevant to it. Exit gate: actual results exist for at least memory-session, durable-session, and recovery on the documented machine; no invented headline figures.

### M9 Release documentation and clean setup verification

Finalize README, architecture, decisions, limitations, demos, setup scripts, CI, and regression fixtures. Perform a clean checkout or clean environment setup test where feasible. Review every requirement below. Exit gate: an unfamiliar developer can run the three demos using README commands, core release tests pass, optional work is separated from completed claims, and the final report is evidence-based.

### Progress reporting contract

Maintain `PROGRESS.md` with current milestone, completed acceptance checks, commands and outcomes, unresolved blockers, important decisions, and next actions. If a long task spans sessions, the next agent reads this file and the specification before changing code. Do not mark a milestone complete just because files exist; its exit gate must have evidence.

## 22 Architecture decisions to document

Write short ADRs with context, decision, alternatives, consequences, and verification. Required decisions include: single-thread ownership; OCaml/Python split; reference independence; integer/string wire representation; price map plus linked queues; session-scoped dedupe and history retention; journal-before-apply; fsync per command; single journal without compaction; snapshot contents and publication; corruption versus incomplete-tail policy; canonical state scope; shrinker signature and minimality claims; and benchmark measurement boundaries.

For each decision, explain why it serves the project. For example, the single writer makes admission order and recovery reasoning simpler, while deliberately leaving multicore scaling outside the first release. Avoid generic claims such as “microservices are scalable” that do not connect to this implementation.

## 23 Acceptance matrix

| ID | Required result | Evidence |
|---|---|---|
| R01 | Correct price-time limit matching | Golden fixtures, properties, differential tests |
| R02 | Correct arbitrary cancellation | Head/middle/tail/only-node tests and invariants |
| R03 | Correct partial fills and resting-price execution | Hand-worked sweeps and quantity conservation |
| R04 | Exact retries do not mutate state | Full session equality before/after retries |
| R05 | Conflicting and rejected retries handled consistently | Golden and recovery fixtures |
| R06 | Deterministic canonical outputs | Repeated byte comparison, cross-language vectors |
| R07 | Independent Python reference | Separate simple implementation and review notes |
| R08 | Useful differential diagnosis | Saved first-mismatch report from a mutant |
| R09 | Durable acknowledgement ordering | Hook and simulated I/O tests |
| R10 | Strict journal validation | Corruption and byte-boundary truncation matrix |
| R11 | Full recovery including dedupe history | Crash/retry and terminal-order tests |
| R12 | Snapshot equivalence and safe fallback | Full replay versus snapshot replay comparisons |
| R13 | Real process crash experiment | Owned child killed at named hook with artifacts |
| R14 | Automatic failure reduction | Original/reduced cases and signature report |
| R15 | Honest minimality claims | Single-deletion check or explicit budget status |
| R16 | Reproducible benchmark evidence | Raw results, repetitions, environment manifest |
| R17 | No benchmark mode confusion | Separate labels, scopes, and plots |
| R18 | Runnable CLI demos and setup | Clean setup log and three demo commands |
| R19 | Bounded parsing and session memory policy | Size, numeric, and capacity edge tests |
| R20 | Clear limitations and no invented claims | README and final review |

## 24 Demo scripts and reviewer experience

### 24.1 Deterministic matching demo

`make demo` runs the golden workload through both engines, prints a concise order/trade summary, and shows identical final session hashes. It should take seconds after compilation. The machine-readable full result remains available in an artifact directory. Explain why trade price is the resting price and why the retry response contains old event IDs without a new trade.

### 24.2 Crash recovery demo

`make demo-crash` runs a workload, kills the process after a journal sync but before response, recovers the session, retries the uncertain request, and compares with the uninterrupted logical run. Print the hook, observed acknowledged prefix, recovered durable prefix, duplicate status, distinct trade count, and equality outcome. The script must actually kill and recover a process; a narrated static transcript is insufficient.

### 24.3 Shrinking demo

`make demo-shrink` runs an isolated faulty FIFO implementation on a saved workload, detects the failure, reduces it, and prints the original and final command counts plus the remaining semantic difference. Then execute the corrected implementation on the reduced workload. A precomputed minimized fixture is useful for a fast fallback demo, but the primary command must invoke the shrinker and label whether cached artifacts were used.

### 24.4 README first screen

The README should immediately answer: what the tool does, why replay/shrinking are useful, how to run the first demo, and what has actually been tested. Include a short true demo transcript or animation after the core works. Do not begin with unsupported claims about institutional adoption, nanosecond latency, or millions of orders per second.

## 25 Optional extensions after the required release

Prioritize one extension only after M9 passes:

1. A read-only browser timeline that steps through commands, shows book changes, highlights the first divergence, and displays reduced reproductions.
2. A persistent-tree OCaml implementation behind the same engine interface for a measured comparison against mutable queues.
3. A bounded group-commit journal mode with an explicit acknowledgement policy and expanded crash tests.
4. Incremental simulated inventory/exposure views built from unique trade events, with precise units and overflow rules.
5. Model checking of a tiny bounded state machine to supplement randomized testing.
6. Multi-instrument independent shards, only after defining sequence and event identity per shard.

Do not bolt on an LLM solely to make the project sound agentic. Its strongest contribution is deterministic debugging with concrete correctness evidence.

## 26 Engineering pitfalls the agent must actively avoid

### 26.1 Semantic pitfalls

Using incoming instead of resting price; appending partially filled resting orders to the queue tail; comparing lexical IDs for priority; allowing reused terminal order IDs; recomputing a cached response from current state; counting repeated delivered events as new trades; using floating-point prices; ignoring rejection precedence; and treating a duplicate request as a new sequenced command.

### 26.2 Persistence pitfalls

Responding before sync; assuming buffered write equals durable write; ignoring short writes; swallowing fsync errors; treating every unacknowledged request as lost; serializing only the active book in snapshots; snapshotting half a transition; deleting journals before defining compaction safety; silently truncating checksum-corrupt complete frames; and using a snapshot to conceal a corrupt authoritative journal.

### 26.3 Testing pitfalls

Copying optimized matching code into the reference; comparing only final book hash; normalizing away trade order; regenerating an alleged reproduction without retaining original bytes; shrinking to a different bug; failing to verify the crash hook was reached; interpreting a process timeout as a passing result; and writing expected fixtures from candidate output without independent review.

### 26.4 Performance pitfalls

Timing Python orchestration while calling it engine latency; reporting percentiles from one aggregate duration; comparing different workload mixes; ignoring retained dedupe history in memory claims; measuring debug and release builds without labelling them; and reporting planned benchmark targets as achieved results.

## 27 Completion report required from Codex

The final implementation report must include:

- Completed milestones and any unfinished required requirement IDs.
- Exact build/test/demo commands and their observed outcomes.
- Toolchain and environment used for validation.
- Number and size of differential workloads actually executed.
- Crash hooks tested, acknowledged-prefix checks, and simulated-storage coverage.
- One original and reduced failure example, with the stable signature and minimality status.
- Measured benchmark numbers with mode, sample count, and reproducibility paths.
- Main design decisions, known limitations, and any deviations from this specification.
- A short list of the most useful files to read first.

Never claim all tests pass if a suite was unavailable, skipped, timed out, or not executed. Mark untested behavior explicitly. If only part of the project can be completed in a session, leave a working checkpoint and accurate progress log instead of a misleading finished README.

## 28 Portfolio and interview presentation

Once implemented and verified, the project story should emphasize the engineering questions you answered: how to define order priority precisely; how to compare independent implementations; how to preserve durable decisions across uncertain replies; how to distinguish logical execution from duplicate delivery; how to reduce a failure without changing its meaning; and how to measure performance without conflating modes.

A truthful description before measurements is: “Built an OCaml exchange simulation workbench with an independent Python reference, deterministic replay, crash-recovery tests, and automated reduction of failing workloads.” Add quantified scale, speed, or reduction only after the repository contains reproducible evidence.

Keep a personal engineering journal of bugs found, decisions reconsidered, and tradeoffs measured. This makes the project useful for learning and discussion rather than merely a collection of generated files. Be ready to explain the code and demonstrate a failure live.

## 29 Primary references and evidence boundaries

These sources motivate or support specific background points. All detailed ReplayLab behaviors above are project design decisions, not requirements published by Jane Street.

1. Jane Street, [How to Build an Exchange](https://www.janestreet.com/tech-talks/building-an-exchange/). The talk discusses exchange design through JX, including fairness, reliability, and performance. It establishes the relevance of exchange infrastructure as a technical topic; it does not establish an employer preference for this project.
2. OCaml documentation, [Mutability and Imperative Control Flow](https://ocaml.org/docs/mutability-imperative-control-flow). Relevant to the chosen design's combination of typed functional boundaries with confined mutable queues. Consult official documentation for the exact compiler version chosen during implementation.
3. Linux man-pages, [fsync](https://man7.org/linux/man-pages/man2/fsync.2.html). Relevant to the distinction between syncing file contents and persisting containing-directory entries. The concrete supported platform and storage assumptions still require tests and documentation.
4. Linux man-pages, [rename](https://man7.org/linux/man-pages/man2/rename.2.html). Relevant to same-filesystem snapshot publication. Rename visibility and persistence after failure are separate concerns; directory synchronization remains part of this design.

The scope of this document is an implementable research and portfolio project. It makes no claim that a local prototype replaces production exchange controls, that process-kill tests simulate every hardware failure, or that a project guarantees a hiring outcome.

## 30 Final execution checklist

Before declaring ReplayLab complete, answer yes with evidence to each question:

1. Can a fresh developer build the OCaml engine and run the Python reference?
2. Are trading, rejection, retry, and sequence semantics written and executable?
3. Does the golden walkthrough produce exactly two distinct trades and one cancellation?
4. Do equal-price orders retain FIFO priority after partial fills and arbitrary cancellation?
5. Can a retry after a crash recover its original response without executing another trade?
6. Does recovery preserve request cache and terminal-order identity rules?
7. Does the journal scanner detect complete corruption and distinguish incomplete tails?
8. Do snapshots preserve full semantic state and safely fall back when damaged?
9. Does the process-crash suite prove its hooks were actually reached?
10. Can a saved failure be reproduced without regenerating its workload?
11. Does the shrinker preserve the intended failure and label its minimality honestly?
12. Do reported measurements have raw data, units, scope, and environment metadata?
13. Do the normal release binary and demos avoid accidental test-mutant activation?
14. Are optional extensions separated from the required completed feature list?
15. Can the owner explain the implementation, limitations, and one real debugging story?

A release that satisfies these checks is a substantive engineering project. Build toward those demonstrated behaviors, and use every extra feature only when it strengthens them.

## Appendix A Critical algorithm outlines

These outlines explain operation ordering. They are not a substitute for typed implementations, complete error handling, or the normative rules above.

### A1 Request admission and durable execution

```text
handle_attempt(raw_line):
    parsed = strict_parse_and_validate(raw_line)
    if parsed is protocol_error:
        return unsequenced_error(parsed.code)

    key = (parsed.client_id, parsed.request_id)
    payload = canonical_business_payload(parsed)
    previous = request_cache.find(key)
    if previous exists:
        if previous.payload_bytes != payload:
            return unsequenced_error(IDEMPOTENCY_CONFLICT)
        return wrap(previous.semantic_response, duplicate=true)

    if request_cache.size >= configuration.max_unique_requests:
        return unsequenced_error(SESSION_REQUEST_LIMIT)
    if next_sequence is exhausted:
        return unsequenced_error(SEQUENCE_EXHAUSTED)

    seq = next_sequence
    command = normalize(parsed)
    if mode == durable:
        append_complete_frame(seq, command)
        sync_journal_or_terminate()

    # This operation includes expected business rejection outcomes.
    # Unexpected failure terminates the process; it does not skip the record.
    semantic_response = apply_unique_sequenced_command(seq, command)
    request_cache.insert(key, payload, semantic_response)
    last_applied_sequence = seq
    next_sequence = checked_successor_or_exhausted(seq)
    assert_invariants_if_debug_enabled()
    return wrap(semantic_response, duplicate=false)
```

Replay invokes the unique-sequenced transition and cache update from verified frames, bypassing live admission and journal writing. It MUST assert that every journaled key is first-seen, that the sequence is the expected successor, and that admission would have been possible under the recorded session limits. A duplicated key in a journal is corruption even if the payload matches. Replay must not silently treat an invalid duplicate frame as an ordinary client retry.

Assign the sequence as a local candidate before writing; commit its in-memory advancement only after transition completion. An append failure terminates the durable process so no later request can accidentally reuse that sequence within a partially written journal. Recovery decides how to handle the tail.

### A2 Incoming order matching

```text
execute_new(seq, command):
    rejection = validate_business_rules(command)
    if rejection exists:
        return rejected_result(rejection), []

    incoming = create_order_record(command, acceptance_sequence=seq)
    ledger.insert(incoming.key, incoming)
    events = []

    while incoming.remaining > 0:
        level = best_opposite_level(incoming.side)
        if no level or not crosses(incoming.limit_price, level.price):
            break

        resting = level.head
        executed = min(incoming.remaining, resting.remaining)
        decrement both remaining quantities by executed
        increment both filled quantities by executed
        decrement level aggregate quantity by executed
        append trade event at resting.limit_price

        if resting.remaining == 0:
            resting.status = filled
            unlink resting node and remove active index entry
            remove level if empty

    if incoming.remaining > 0:
        incoming.status = active
        append incoming node to its own price-level tail
        add incoming to active index
    else:
        incoming.status = filled

    update event digest once for each new event in list order
    return acceptance_response_from_current_incoming_record(), events
```

A level's aggregate quantity is adjusted exactly once per fill. Ensure the unlink helper does not subtract a filled order's already-zero remaining quantity incorrectly or double-subtract a cancellation amount. State precisely whether aggregate maintenance belongs to mutation helpers or their callers and test that convention.

### A3 Cancellation

```text
execute_cancel(seq, command):
    reject UNKNOWN_INSTRUMENT if needed
    node = active_index.find((command.client_id, command.order_id))
    if node absent:
        return rejected_result(ORDER_NOT_ACTIVE), []

    cancelled = node.order.remaining
    subtract cancelled from its level aggregate
    unlink node and remove active index entry
    remove its level if empty
    node.order.remaining = 0
    node.order.cancelled_quantity = cancelled
    node.order.status = cancelled
    emit one cancellation event
    update event digest
    return accepted_cancellation_result(), [event]
```

### A4 Differential loop

```text
for attempt_index, line in saved_workload:
    reference_response = reference.handle(line)
    candidate_response = candidate.handle(line)
    compare(normalized(reference_response), normalized(candidate_response))
    if comparison differs:
        save prefix and complete failure artifact
        stop with failure
    if checkpoint_due:
        compare(reference.session_state(), candidate.session_state())
        if different:
            rerun this prefix with per-attempt state exports
            save earliest divergence
            stop with failure
compare full final state
```

Do not pipe all candidate output into an unbounded buffer before comparing a large workload. Use streaming readers with backpressure and timeouts. For throughput benchmarks, use a separate execution path to avoid counting the overhead of this checker.

### A5 Delta debugging

```text
candidate = earliest_failing_prefix(original)
granularity = 2
while candidate has at least two commands and budget remains:
    divide candidate into granularity contiguous chunks
    for chunk in deterministic order:
        trial = candidate without chunk
        if preserves_signature(trial):
            candidate = trial
            granularity = max(2, granularity - 1)
            restart this loop
    if no reduction:
        if granularity >= number_of_commands(candidate):
            break
        granularity = min(2 * granularity, number_of_commands(candidate))

repeat numeric and identity simplifications until no progress or budget exhaustion
if budget remains:
    repeat individual-deletion checks to a fixed point
reproduce final candidate three times and save report
```

A time-budget exit must still save the best known reproducer. Preserve the original failure if no accepted reduction is found. Empty workloads are legitimate trial candidates; evaluate them rather than assuming a failing input must be nonempty.

## Appendix B Contract details that must be frozen in M1

The specification fixes behavior, but the repository must freeze exact field spelling for every machine-readable variant before more components depend on it. Publish complete schemas and golden examples for these records:

| Record | Minimum mandatory contents |
|---|---|
| New accepted response | Command type, local order ID, original quantity, current-at-acceptance filled/remaining/cancelled quantities, order status |
| Cancel accepted response | Command type, local order ID, cancelled quantity, resulting order status |
| Business rejected response | Command type, order ID, rejection code |
| Unsequenced error | Stable error code, protocol subcode where applicable, parsed correlation IDs or null |
| Trade event | Event identity, instrument, all four role-specific order keys, price, quantity |
| Cancel event | Event identity, instrument, order key, cancelled quantity |
| Run manifest | Versions, mode, session/configuration, seed if generated, workload hash, executable/build identity |
| Difference report | Signature, first differing attempt, semantic path, expected/actual values, artifact paths |
| Shrink report | Predicate, budgets, evaluations, sizes, duration, validation repetitions, minimality status |
| Benchmark result | Mode/scope, profile/hash, counts, durations, samples, environment, repetitions |

The accepted-new response example in section 5 is the baseline for this variant; expand the other variants with equally concrete examples in repository documentation.

Add protocol subcodes at minimum for invalid UTF-8, oversized line, invalid JSON, duplicate object key, unknown field, missing field, unsupported schema version, wrong field type, invalid ID, invalid side, and invalid numeric encoding/range. When several schema problems coexist, use a documented deterministic validation order. A robust default is framing/encoding first, JSON/duplicate-key errors second, schema-version validation third, field set fourth, then field checks in a fixed command-specific order. The reference and candidate must implement the same order.

Set a hard configuration ceiling of 1,000,000 accepted order records and 2,000,000 unique sequenced requests for version 1; values must be positive and max accepted orders must not exceed max unique requests. This bounds total order quantity at 10^15 and keeps basic quantity aggregates safely within signed 64-bit range under the specified numeric limits. Checked arithmetic remains required. Larger experiments require an explicit versioned configuration-policy change and validation of all aggregate bounds.

Read-only commands must obtain a lock that excludes an active writer while scanning a session, or open an explicitly stable copied session. The simple required implementation uses the same exclusive lock for all session operations. A reader must not report transient append bytes as persistent corruption while the writer is still updating the file. Snapshot and recovery also hold that lock for their entire operation. This is a local consistency choice, not a scalability feature.

## Appendix C Suggested review questions for the finished project

Use these to check understanding, not as memorized interview scripts:

1. Why can two books look identical while their sessions behave differently on the next request?
2. Why is a retry response allowed to contain trade events without creating new trades?
3. Why is the log appended before the state mutation, and what happens if application then fails?
4. What can be concluded about a sent request whose response was never observed?
5. Which failures does SIGKILL test, and which storage failures require a different model?
6. Why does snapshot publication sync both a file and a directory?
7. Why must an order ID remain reserved after its order is filled?
8. How does cancellation remove the middle of a price-level queue efficiently?
9. Why does differential testing need hand-worked fixtures and invariants too?
10. What does the shrinker's minimality claim prove, and what does it leave unproven?
11. Why can a benchmark's throughput rise when its workload becomes less representative?
12. What information would be needed before extending this design to multiple matching shards?
13. Which exact test would fail if FIFO were accidentally reversed?
14. Which measured bottleneck justifies the next optimization?
15. What is the smallest recovered failure you can explain command by command?
