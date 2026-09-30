# Persistence and recovery

Each directory contains metadata.json, writer.lock, commands.wal and snapshots/.
Every operation, including inspect and verify-log, obtains the same exclusive OS
advisory lock for its entire scan. The OS releases the lock after process death;
the presence of writer.lock alone does not imply ownership.

Creation syncs metadata and the empty journal, then directory entries. Each
admitted unique request appends one frame, syncs the journal, applies the command,
caches the outcome, and only then emits a synced response. Business rejections
are journaled. Protocol errors, retries, conflicts and capacity errors are not.
Storage write/sync failure terminates the process. Short writes and EINTR are
handled; a zero write is an error. Journal bytes are the only authoritative log.

## Frames

| Bytes | Encoding |
|---|---|
| 0–3 | ASCII RPLB |
| 4–5 | unsigned big-endian frame version 1 |
| 6–9 | unsigned big-endian payload length, at most 65,536 |
| next N | canonical JSON payload |
| final 32 | raw SHA-256(header + payload) |

Payload fields are schema_version=1, semantics_version="replaylab-v1",
session_identity_hash (SHA256 of canonical metadata), seq, client_id, request_id,
and the complete normalized command. Scanner compares the exact field set and
canonical bytes, checks every checksum, requires contiguous sequences from 1,
rejects repeated request keys and enforces the recorded request capacity.

A partial final frame is an incomplete tail only when its known fixed header
bytes are valid. A full checksum mismatch, bad magic/version, excessive length,
or valid-checksum invalid payload is corruption. There is no search-ahead scan.
Read-only operations preserve bytes. Only `recover --repair-incomplete-tail`
truncates to the validated boundary and syncs before append. Complete corruption
is never automatically repaired.

## Snapshots

A snapshot has a body plus its SHA256 checksum. The body contains format and
semantic versions, session identity, configuration hash, last sequence, journal
boundary offset/checksum, full semantic state, and state digest. It is encoded as
canonical JSON bytes despite the .bin suffix. No runtime pointers are serialized.

Publication writes a unique same-directory temporary file, syncs, renames to
`snapshot-%020d.bin`, then syncs the snapshots directory. Repeating a snapshot at
the same sequence recognizes identical bytes; different bytes are rejected.
Temporary files are ignored. The entire journal is still scanned and validated
before snapshot selection. Newest valid compatible snapshot wins; rejected
snapshots emit a warning and fall back to older snapshots or full replay.

Restoration rebuilds queues by acceptance sequence, rebuilds request/order tables,
checks conservation and structure, and recomputes the event digest from original
cached events. Suffix commands are replayed after the restored sequence. There is
no journal rotation or compaction. Large histories remain deliberately retained.

## Failure evidence

The controller receives a notification on a dedicated pipe and kills its exact
child PID with SIGKILL while the child blocks on another pipe. Reports verify the
hook was reached, compare recovery against an independent valid-prefix oracle,
and separately verify acknowledged requests survived. An uncertain request may
be recovered or absent; retry resolves it without an extra logical execution.

The OCaml simulated I/O adapter uses separate volatile/durable bytes and exercises
production short-write/EINTR/fsync loops, dropped unsynced suffixes, disk-full,
zero writes and sync failure. This is distinct from process-kill evidence and
from physical power-loss testing. macOS uses fsync, not F_FULLFSYNC; Linux local
filesystem validation passed using Docker Desktop’s Linux overlay filesystem.
See `docs/validation/linux/` for executed checks; no remote CI run is claimed.
