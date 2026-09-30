# Measurement boundaries

`make bench` builds native code with Dune's release profile, generates and saves a
seeded workload, validates it against the reference outside timing, performs one
warm-up and five fresh measured repetitions, and writes every native sample.
The executable SHA-256, dependency versions, platform, workload hash and dirty-tree
label accompany results. Unknown hardware/storage details remain marked unknown.

The native timer uses clock_gettime(CLOCK_MONOTONIC). Samples contain integer
nanoseconds as decimal strings. Each command has start/end clock reads; empty
clock-pair median is recorded. Percentiles use nearest rank. Total elapsed time
also includes counter/timer bookkeeping. Python orchestration and process startup
are outside the native timer. Per-command samples are service costs under a
serial loop, not open-loop network latency. Do not infer p99 from aggregate time.

| Mode | Measured work |
|---|---|
| book-kernel | Prevalidated unique-order matching/cancellation only |
| memory-session | Typed admission, dedupe, matching, events and event digest |
| json-batch | Parsing, validation, session processing and JSON serialization |
| durable-session | Typed processing plus journal serialization/write/fsync; no response JSON output |
| recovery | Lock/open, full journal scan, state rebuild/restore, suffix replay and validation |

Snapshots still require complete journal scanning. Their measured effect includes
restoring retained request history and validating the restored state; they are not
assumed to improve all workloads. Kernel workloads must use unique order identities
and contain no retry/adversarial business cases; the default balanced benchmark
therefore excludes kernel mode. `bench.exe --mode book-kernel` is available for
appropriate saved workloads.

Raw JSON contains sample arrays, operation counts, GC allocation/collection data,
active levels/orders, retained records, dedupe count and process peak RSS. RSS
includes process setup/parsing/history and is not just OCaml heap size.

Saved results are local observations, not exchange production performance. Bar
charts compare distinct costs and label modes; no cross-mode implementation
speedup is claimed. Shared CI timing is smoke evidence only. See the local-run
README for actual values and measurement boundaries.
