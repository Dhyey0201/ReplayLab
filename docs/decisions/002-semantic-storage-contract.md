# 002: Semantic and storage contract

Context: Two equal visible books may respond differently to retries and reused IDs.
The durable log must define one recoverable ordering even when replies are lost.

| Decision | Alternative and reason | Consequence / verification |
|---|---|---|
| int64 internally, decimal strings on wire | floats lose integer precision | Bounds and maximum sequence tests |
| price maps plus linked queues | scanning is simpler but slow for cancellation | FIFO/unlink tests; Python independently scans |
| retain dedupe and terminal history | eviction changes later behavior | Finite configured sessions; full-state comparison |
| cache original semantic responses | reconstructing responses changes filled quantities | Retry-after-fill and snapshot tests |
| journal before apply | apply-first risks acknowledging absent decisions | Sync/apply/response crash hooks |
| fsync every unique request | group commit requires a different acknowledgement policy | Deliberate synchronous cost; separate benchmark mode |
| single journal, no compaction | segmentation creates more crash boundaries | Full scan retained; storage grows with session |
| full semantic snapshot and atomic publication | active book alone loses future behavior | Restore cache/history and rebuild queues; two snapshot hooks |
| complete corruption fails; incomplete tail needs explicit repair | guessing salvage can conceal damage | Every byte truncation and complete corruption matrix |
| canonical session and book projections | book hashes cannot test dedupe | Original response/payload, history and digest in session hash |
| signature-based shrinking | any failure predicate can minimize a different bug | Class/path/direction; three repetitions and deletion check |
| native benchmark scope separation | controller timing confounds matching cost | Raw timer samples and per-mode counts |

All changes to these decisions need a semantics/storage version decision and a
corresponding regression fixture. The implementation intentionally chooses simple
single-writer reasoning over multicore or distributed coordination.
