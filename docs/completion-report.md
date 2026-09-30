# ReplayLab 0.1.0 completion report

All required M0–M9 milestones and R01–R20 acceptance gates are complete.
The release is the specification’s local OCaml/Python command-line workbench.
No required feature is deferred to a later release.

## Implemented

- Independent Python scan/sort reference and native OCaml price-map/FIFO engine.
- Strict bounded JSONL, int64 checks, rejection precedence, exact retries,
  lifecycle/history retention, deterministic events, full state and hashes.
- Synchronous framed WAL, exclusive locking, strict corruption detection,
  incomplete-tail repair, full snapshots, fallback and explicit recovery.
- Streaming differential comparison, ten seeded profiles, first-divergence
  diagnostics, schema-validated artifacts and classified crash/timeout output.
- Scheduled duplicates, dropped responses, admission delays and delivery delays
  with explicit logical-time schedules and changed-admission-order reports.
- Nine externally controlled SIGKILL hooks, acknowledged-prefix checks,
  uncertain-request retries and separate simulated storage-fault tests.
- Four isolated mutants, semantic/crash shrinking, stable signatures, budgets,
  repeated validation and honest deletion-minimality claims.
- Native kernel/session/JSON/durable/recovery benchmark tools, raw samples,
  RSS/GC/counters, repeated measurements, charts, CI and three live demos.

## Executed evidence

| Gate | Outcome |
|---|---|
| Fresh Linux setup | Pinned dependencies installed successfully from scratch |
| macOS and Linux checks | 32 Python tests, native Dune tests, Ruff format/lint and OCaml formatting passed |
| Deep differential corpus | 100 saved seeds × 1,000 attempts across ten profiles passed on both platforms |
| Persistence | Every-byte tiny-journal truncation matrix, corrupt complete frames, locks, snapshot restore/fallback passed |
| Crash testing | All nine hooks reached; acknowledged outcomes and recovered prefixes preserved |
| Clean-source build | Native build and native/Python tests passed on both platforms |
| Matching demo | Equal state hashes; two unique trades and one cancellation |
| Crash demo | Actual SIGKILL; two observed responses, three recovered decisions; final retry/resume equality |
| Shrink demo | Live 500 → 3 reduction; three fresh reproductions; deletion 1-minimal; corrected engine agrees |
| Crash shrink | Stable request-key target retained; four commands reduced to two |
| Benchmarks | Five measured repetitions per main mode, 30 recovery scaling results, valid raw schemas and five charts per run |

Latest logs: `docs/validation/macos-release-check.log`,
`docs/validation/linux-release/`, and `docs/validation/linux-final-check/`.
The final Linux check includes the reporting/schema fixes and all demos.
Full Linux artifacts: `artifacts/linux-release/artifacts.tar.gz`.
Raw benchmarks: `benchmarks/results/local-cl7rg4h4/measurements` and
`benchmarks/results/linux-release/measurements`.
Selected FIFO regression: `fixtures/regressions/fifo/`.

The FIFO witness contains two one-unit bids at 105 followed by a one-unit sell
at 1. Correct FIFO fills the older bid at 105; the LIFO mutant fills the newer
bid. Reduction uses 48 predicate evaluations. Global minimality is not claimed.

## Environment and scope

macOS 26.5.2 arm64 and Linux 6.12.54 aarch64 in Docker Desktop. Linux durability
checks ran on the VM’s overlay filesystem, without a macOS bind mount. Python
3.14.3, opam 2.3.0, OCaml 5.2.1, Dune 3.17.2, Yojson 2.2.2 and Digestif 1.3.0.
The final executable reports `0.1.0`. Dependencies are project-local and pinned.

Initial image export ran out of host disk space; those interrupted checks are
excluded from acceptance evidence. The compact Docker evidence target succeeded.
Older deep response streams were losslessly compressed to preserve content.

One instrument/thread, finite retained history and full WAL scans are deliberate
scope boundaries. Snapshot restore is slower for the measured small workload.
SIGKILL and simulated faults do not prove physical power-loss behavior. No broker,
authentication, network service or production-performance claim is included.
See `docs/limitations.md` and `docs/acceptance.md`.

Nothing was committed, pushed or published. Remote GitHub CI was not invoked;
local Linux evidence is recorded independently of the configured CI workflow.
