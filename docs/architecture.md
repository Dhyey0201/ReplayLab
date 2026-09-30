# Architecture

`lib/domain.ml` defines int64 quantities, identities, commands and lifecycle
records. `lib/book.ml` owns mutable doubly linked nodes, aggregate quantities,
active-order indexing and the two ordered price maps. Its interface exposes
private structural records for inspection without exposing mutation helpers.
`lib/book_view.ml` exports read-only JSON projections so the matching data structure has no JSON dependency.
`lib/session.ml` owns admission, deduplication, sequencing, original response
caching, and semantic event history. `lib/codec.ml` handles strict parsing and
canonical encoding. `lib/storage.ml` and `lib/snapshot.ml` implement durable
framing, validation and restore. `lib/driver.ml` owns streams and exit codes.

Python's `replaylab_ref` is deliberately different: one lifecycle dictionary and
an eligible-order scan sorted by price then original sequence. It imports no
candidate matching code. `replaylab_tools` generates workloads, compares streamed
responses, controls child processes, reduces failures, and analyzes native timing
samples. Frozen schemas/fixtures are the only shared semantic representation.

The candidate has expected O(1) index lookup and unlink for a nonempty level;
creating/deleting levels is O(log L). Matching is O(F log L) in this implementation.
Canonical export, full invariants, and full session hashing are linear or worse
in retained history and remain outside measured kernel loops.

The matching implementation updates level aggregate quantity before unlink;
unlink only changes links, size and membership. Removed neighbor links are cleared.
The terminal ledger and request cache intentionally retain history for the session.

Test-only faults and control pipes are configured only by
`test/engine/test_engine.exe`. The release CLI rejects those switches, reads no
mutant environment variable, and defaults to correct behavior. The code is shared
with test instrumentation, but ordinary users cannot select it through main.exe.
