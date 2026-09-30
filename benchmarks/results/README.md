# Local benchmark evidence

The accepted local baseline is [local-cl7rg4h4/measurements](local-cl7rg4h4/measurements/).
It used native release builds, OCaml 5.2.1 / Dune 3.17.2, macOS arm64, balanced
seed 42 and 1,000 saved attempts. One warm-up precedes five measured runs per mode.
There are 945 schema-valid attempts and 793 unique sequenced commands. Parsing
and invalid records are outside the typed session modes. JSON batch includes all
1,000 attempts. Different scopes are not implementation speedups.

| Native mode | Median elapsed | Measured repetitions |
|---|---:|---:|
| Memory session | 5.487 ms | 5 |
| JSON batch | 14.403 ms | 5 |
| Durable session | 37.826 ms | 5 |
| Full recovery | 24.372 ms | 5 |
| Snapshot recovery plus full journal scan | 81.280 ms | 5 |

Snapshots were slower at this size. No acceleration claim is made. These are
small local observations; no production throughput or physical power-loss claim.
The native per-command raw samples, timer overhead, percentile method, retained
history, RSS/GC data, workload bytes/hash, binary hash and environment metadata
are saved alongside the summary.

- [Throughput by scope](local-cl7rg4h4/measurements/throughput.svg)
- [Raw latency distributions](local-cl7rg4h4/measurements/latency.svg)
- [Recovery versus journal size](local-cl7rg4h4/measurements/recovery.svg): 30 additional measurements, three sizes × two modes × five runs.
- [Failure reduction](local-cl7rg4h4/measurements/shrinking.svg)
- [Machine-readable summary](local-cl7rg4h4/measurements/summary.json)
- [Environment](local-cl7rg4h4/measurements/environment.json)

`make bench` creates a new directory and regenerates measurements/plots. Existing
results are preserved. The earlier `local-01fybtzs` baseline used Dune 3.24.2 after
formatter installation upgraded it; its metadata was corrected using installed
package evidence. It is retained as an exploratory run. Any workload-only
incomplete directory is not a benchmark result.

The Linux aarch64 release run is saved in [linux-release/measurements](linux-release/measurements/).
It ran inside Docker Desktop on Linux overlay storage, with the same workload
and five repetitions. Median elapsed times: memory 5.910 ms, JSON 16.057 ms,
durable 354.146 ms, full recovery 27.944 ms, snapshot recovery 112.008 ms.
The VM and filesystem differ from the macOS run; these are separate environments,
not a controlled platform speed comparison. Both datasets include raw samples,
accepted-order/trade rates, 30 recovery scaling results, and generated charts.
