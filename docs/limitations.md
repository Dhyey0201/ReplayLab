# Current limitations

- Linux local filesystems are the authoritative durability target. The executed
  validation covers macOS arm64 and Linux aarch64 using Docker Desktop’s overlay
  filesystem. Remote CI and physical power-loss testing are separate evidence.
- SIGKILL leaves the OS page cache alive. Separate simulated-storage tests do not
  prove behavior of every filesystem, controller cache, or physical power loss.
  macOS uses fsync rather than the stronger platform-specific F_FULLFSYNC.
- One instrument, one thread, finite session history; no journal rotation,
  compaction, or request eviction. Replay and snapshot validation scan the full
  journal. Snapshot loading has a 512 MiB bound and falls back to journal replay
  if a snapshot exceeds it. Very large allowed sessions have not been measured.
- IDs simulate client ownership; there is no authentication or malicious-tamper
  protection. Checksums detect damage, not authorship. Locks coordinate local
  cooperating processes only. One disk remains one failure domain.
- Differential agreement is evidence, not proof. Hand-worked fixtures, structural
  invariants, mutants and crash-prefix oracles address some shared-bug risks.
- Shrink results are local reductions; 1-minimality only concerns single-command
  deletion under the saved signature. Crash-target identities are preserved.
- Benchmark metadata can contain unknown CPU/storage details. Local observations
  are not production latency, throughput, or capacity claims.
- No browser UI, real orders, market data, strategies, FIX, broker integration,
  distributed consensus, or employer endorsement is included.
