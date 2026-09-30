from pathlib import Path
import tempfile
from replaylab_tools.generate import save, PROFILES
from replaylab_tools.compare import save_comparison

Path("artifacts").mkdir(exist_ok=True)
root = Path(tempfile.mkdtemp(prefix="deep-", dir="artifacts"))
for seed in range(100):
    profile = PROFILES[seed % len(PROFILES)]
    workload = root / f"{seed}-{profile}.jsonl"
    save(profile, seed, 1000, workload)
    result = save_comparison(
        "_build/default/bin/main.exe", workload, "deep", root / f"comparison-{seed}"
    )
    if result["status"] != "agreement":
        raise SystemExit(f"Difference: {root}/comparison-{seed}")
    if seed % 10 == 9:
        print(f"{seed + 1}/100 seeds passed", flush=True)
print(f"100 seeds × 1000 attempts saved at {root}")
