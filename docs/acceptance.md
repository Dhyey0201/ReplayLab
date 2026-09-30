# Release acceptance matrix

All required acceptance gates passed on macOS arm64 and Linux aarch64.
Linux used Docker Desktop’s Linux overlay filesystem, not a macOS bind mount.
Logs: `docs/validation/linux-release/` and `docs/validation/linux-final-check/`;
full artifacts: `artifacts/linux-release/artifacts.tar.gz`.

| ID | Local evidence | Status |
|---|---|---|
| R01 price/time matching | Hand-worked sweeps/FIFO; 20 regular seeds; 100 deep seeds | Passed locally |
| R02 arbitrary cancellation | Head/middle/tail/only-node examples, linked-structure invariants | Passed locally |
| R03 partial fills/resting price | Both-direction sweeps, residuals, conservation, incoming-price mutant | Passed locally |
| R04 exact retries | Full state equality, cached original responses, state traces, scheduled drop/delay/duplicate checks | Passed locally |
| R05 conflicts/rejected retries | Golden and limits cases; retries after target activation and recovery | Passed locally |
| R06 canonical determinism | Byte/hash fixture in both languages; full state comparison | Passed locally |
| R07 independent reference | Scan/sort dataclass ledger vs OCaml maps/linked queues | Implemented and tested |
| R08 differential diagnosis | Saved FIFO difference path, command, prefix, outputs, states, provenance; crash/timeout artifact regressions | Passed locally |
| R09 durable ordering | All command hooks, actual sync, simulated short writes/sync failures | Passed on macOS and Linux |
| R10 strict journal | Every byte cut of two frames, complete/middle corruption, invalid checksummed payloads | Passed on macOS and Linux |
| R11 full recovery | Prefix oracle, acknowledged-result checks, uncertain retries and terminal IDs | Passed on macOS and Linux |
| R12 snapshot equivalence/fallback | Empty/suffix restore, repeated snapshot, damaged fallback, original responses | Passed on macOS and Linux |
| R13 real process crash | Nine notification-handshaked external SIGKILL hooks | Passed on macOS and Linux |
| R14 failure reduction | Generated FIFO 500 -> 3; crash mutant 4 -> 2 | Passed locally |
| R15 honest minimality | Final deletion fixed point and three fresh reproductions | Passed locally |
| R16 measured evidence | Five repetitions per native mode, raw latency/RSS/GC, recovery size series | Passed locally |
| R17 benchmark scope | Separate modes, native clocks, labelled plots, no inferred tail latency | Implemented |
| R18 setup/CLI demos | Project-local setup; three executable demos; clean-source validation | Fresh Linux setup and demos passed |
| R19 bounded policy | Bounded line drain, numeric/sequence/capacity edges, bounded WAL frames | Passed locally |
| R20 honest limitations | README, limitations, benchmark notes and completion report | Documented |

The supplied Docker evidence target reproduced setup, checks, the deep corpus,
all demos, a clean-source build and benchmarks on Linux. Remote GitHub CI has
not been invoked. No public publishing has occurred.
