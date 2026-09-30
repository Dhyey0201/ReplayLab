# ReplayLab progress — 2026-09-29

**Required implementation milestones M0–M9 are complete.** macOS and fresh Linux
validation passed. The final `0.1.0` source passed 32 tests and all demos on both
platforms. Full Linux logs: `docs/validation/linux-release/`; final reporting/schema
regressions: `docs/validation/linux-final-check/`.

The specification was read in three passes: semantics; architecture and failure
boundaries; acceptance and implementation order. The product is the specified
local OCaml/Python CLI workbench, with the specification’s explicit non-goals.

| Milestone | Status | Evidence |
|---|---|---|
| M0 Foundation | Complete | Pinned fresh Linux installation, native build, CLI, JSON/SHA vectors |
| M1 Contract/reference | Complete | Independent scan/sort reference, schemas, golden/edge/invariant tests |
| M2 OCaml engine | Complete | Price maps, linked FIFO, arbitrary cancellation, int64/lifecycle/dedupe |
| M3 Differential tooling | Complete | Streaming response/state comparison, ten profiles, 100 saved deep seeds, failure artifacts |
| M4 Journal | Complete | macOS/Linux framing, locking, corruption rejection, every-byte truncation checks |
| M5 Snapshots | Complete | Full semantic restore, suffix replay, fallback, original retry responses |
| M6 Crash experiments | Complete | All nine externally killed hooks, prefix oracle, simulated storage faults |
| M7 Shrinker | Complete | Four mutants; live FIFO 500 → 3; crash 4 → 2; three validations and deletion minimality |
| M8 Measurements | Complete | Five repetitions per native family, raw samples/RSS/GC, 30 recovery scaling runs and charts |
| M9 Release verification | Complete | Fresh Linux setup, checks, deep corpus, three demos, clean-source build and benchmarks |

## Executed validation

- `make check`: 32 Python tests, native Dune checks, Ruff format/lint and OCaml format pass on macOS. Log: `docs/validation/macos-release-check.log`.
- First Linux evidence run: 31 tests (before the final metamorphic test), native checks/format/lint, 100 × 1,000 attempts across ten profiles, all demos, clean-source tests and benchmark runs passed. Logs: `docs/validation/linux/`.
- Final Linux run: 32 tests, 100 × 1,000 attempts, all demos, clean-source build and benchmarks passed. Full artifacts: `artifacts/linux-release/artifacts.tar.gz`.
- Final controller/schema changes passed another full 32-test Linux check and all three demos; version output is `0.1.0`.
- Linux raw measurements: `benchmarks/results/linux-release/measurements`.
- macOS deep corpus: `artifacts/deep-u9jk6rkx`; older candidate/reference JSONL streams are losslessly compressed as `.jsonl.gz` to save disk space.
- Latest macOS native release measurements: `benchmarks/results/local-cl7rg4h4/measurements`; prior measurements are preserved.
- `replaylab --version` reports `0.1.0`.

## Environment and reproducibility

macOS 26.5.2 arm64 and Docker Desktop Linux 6.12.54 aarch64, overlay filesystem
inside the Linux VM. Linux tests used no macOS bind mount. Python 3.14.3,
opam 2.3.0, OCaml 5.2.1, Dune 3.17.2, Yojson 2.2.2 and Digestif 1.3.0.
Dependencies are project-local and pinned. Reproduce Linux evidence with:

```sh
docker build --target evidence --output type=local,dest=artifacts/linux-validation-new .
```

The initial image export exhausted host space. Those failed runs are not accepted
evidence. Docker recovered after space was reclaimed; the evidence target exports
only logs and a compressed archive, avoiding the large runnable image export.
No unrelated Docker images or user data were deleted.

The repository was initialized locally to isolate it from an ancestor repository.
Nothing was committed, pushed or published. Remote GitHub CI was not invoked.
There is no physical power-loss or production performance claim. Scope and
limitations are documented in `docs/limitations.md`; no required feature is
scheduled for a later release.
