"""Standalone matplotlib charts, generated only from saved raw measurements."""

import json
from pathlib import Path
import statistics
import sys
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

root = Path(sys.argv[1])
shrink = Path(sys.argv[2])
rows = [
    json.loads(p.read_bytes())
    for p in root.glob("*.json")
    if p.name.startswith(("memory-session-", "json-batch-", "durable-session-"))
]
modes = ["memory-session", "json-batch", "durable-session"]
plt.rcParams.update(
    {"font.size": 10, "axes.spines.top": False, "axes.spines.right": False}
)
fig, ax = plt.subplots(figsize=(8, 4))
values = [
    statistics.median(
        int(r["unique_commands"]) / (int(r["elapsed_ns"]) / 1e9)
        for r in rows
        if r["mode"] == mode
    )
    for mode in modes
]
ax.bar(modes, values, color=["#2463a5", "#278271", "#bf6339"])
ax.set_ylabel("Unique sequenced commands / second")
ax.set_title(
    "Balanced seed 42: median of five native runs\nDistinct scopes; not implementation speedups"
)
fig.tight_layout()
fig.savefig(root / "throughput.svg")
plt.close(fig)
fig, ax = plt.subplots(figsize=(8, 4))
for mode in modes:
    samples = sorted(
        int(n) / 1000 for r in rows if r["mode"] == mode for n in r["samples_ns"]
    )
    ax.step(samples, [(i + 1) / len(samples) for i in range(len(samples))], label=mode)
ax.set_xscale("log")
ax.set_xlabel("Native per-command time (microseconds, log scale)")
ax.set_ylabel("Cumulative fraction")
ax.set_title("Raw service-time samples, five repetitions; timer overhead included")
ax.legend()
fig.tight_layout()
fig.savefig(root / "latency.svg")
plt.close(fig)
scaling = json.loads((root / "recovery-scaling.json").read_bytes())
fig, ax = plt.subplots(figsize=(8, 4))
for snap in [False, True]:
    sizes = sorted({int(r["journal_bytes"]) for r in scaling})
    values = [
        statistics.median(
            int(r["elapsed_ns"]) / 1e6
            for r in scaling
            if int(r["journal_bytes"]) == size and r["snapshot"] == snap
        )
        for size in sizes
    ]
    ax.plot(
        [x / 1024 for x in sizes],
        values,
        marker="o",
        label="snapshot restore + scan" if snap else "full replay + scan",
    )
ax.set_xlabel("Authoritative journal size (KiB)")
ax.set_ylabel("Median native recovery time (ms)")
ax.set_title("Five measured repetitions per size and mode")
ax.legend()
fig.tight_layout()
fig.savefig(root / "recovery.svg")
plt.close(fig)
report = json.loads(shrink.read_bytes())
fig, ax = plt.subplots(figsize=(7, 4))
ax.bar(
    ["Original", "Reduced"],
    [int(report["original_commands"]), int(report["final_commands"])],
    color=["#999999", "#2463a5"],
)
ax.set_ylabel("Commands")
ax.set_title(
    f"FIFO witness: {report['evaluations']} evaluations, {report['duration_seconds']} seconds\n{report['minimality']}"
)
fig.tight_layout()
fig.savefig(root / "shrinking.svg")
plt.close(fig)
