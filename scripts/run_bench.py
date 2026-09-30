import os
import subprocess
import sys
from pathlib import Path
import tempfile
from replaylab_tools.benchmark import benchmark

root = (
    Path(tempfile.mkdtemp(prefix="local-", dir="benchmarks/results")) / "measurements"
)
print(benchmark("workloads/configs/benchmark.json", root))
print(f"Raw measurements: {root}")


subprocess.run([sys.executable, "scripts/recovery_scaling.py", str(root)], check=True)
subprocess.run(
    [
        sys.executable,
        "scripts/plot_results.py",
        str(root),
        "fixtures/regressions/fifo/report.json",
    ],
    check=True,
    env=os.environ
    | {
        "MPLCONFIGDIR": str(Path(".tools/matplotlib").resolve()),
        "XDG_CACHE_HOME": str(Path(".tools/cache").resolve()),
    },
)
