"""Repeated native measurements. Python process startup is outside native timers."""

import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import tempfile
from replaylab_ref.codec import canonical
from .generate import save
from .compare import evaluate


def benchmark(config_file, out):
    config = json.loads(Path(config_file).read_bytes())
    root = Path(out)
    root.mkdir(parents=True, exist_ok=False)
    repetitions = int(config.get("repetitions", 5))
    if repetitions < 5:
        raise ValueError("main benchmark requires at least five repetitions")
    executable = str(
        Path(config.get("candidate", "_build/default/bin/bench.exe")).resolve()
    )
    workload = root / "workload.jsonl"
    manifest = save(
        config.get("profile", "balanced"),
        int(config.get("seed", 42)),
        int(config.get("count", 1000)),
        workload,
    )
    records = workload.read_bytes().splitlines(keepends=True)
    validation = evaluate("_build/default/bin/main.exe", records, "validation")
    if validation["difference"]:
        raise AssertionError("benchmark workload validation failed")
    environment = dict(
        schema_version=1,
        semantics_version="replaylab-v1",
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        platform=platform.platform(),
        machine=platform.machine(),
        cpu=platform.processor() or "unknown",
        logical_cores=str(os.cpu_count()),
        ram="unknown",
        filesystem="unknown",
        storage_device="unknown",
        python=platform.python_version(),
        build_identity="local working tree; source changes may be uncommitted",
        build_profile=os.environ.get("REPLAYLAB_BUILD_PROFILE", "unknown"),
        compiler=subprocess.check_output(
            ["_opam/bin/ocamlopt", "-version"], text=True
        ).strip(),
        dune=subprocess.check_output(
            ["_opam/bin/dune", "--version"], text=True
        ).strip(),
        dependencies={"yojson": "2.2.2", "digestif": "1.3.0"},
        executable_sha256=hashlib.sha256(Path(executable).read_bytes()).hexdigest(),
        workload=manifest,
        repetitions=str(repetitions),
        warmups="1",
        latency_percentile="nearest-rank; per-command native timer",
        timer="clock_gettime CLOCK_MONOTONIC; raw nanoseconds",
        rss="getrusage process high-water bytes, includes parsing and retained history",
    )
    (root / "environment.json").write_bytes(canonical(environment) + b"\n")
    results = []
    with tempfile.TemporaryDirectory(prefix="replaylab-bench-") as temp:
        for mode in config.get(
            "modes", ["memory-session", "json-batch", "durable-session", "recovery"]
        ):
            for repetition in range(-1, repetitions):
                session = Path(temp) / f"{mode}-{repetition}"
                if mode == "recovery":
                    subprocess.run(
                        [
                            "_build/default/bin/main.exe",
                            "run",
                            "--mode",
                            "durable",
                            "--session-id",
                            "benchmark",
                            "--session-dir",
                            str(session),
                            "--input",
                            str(workload),
                            "--responses",
                            str(Path(temp) / "responses"),
                        ],
                        check=True,
                        capture_output=True,
                        timeout=60,
                    )
                args = [
                    executable,
                    "--mode",
                    mode,
                    "--input",
                    str(workload),
                    "--session-dir",
                    str(session),
                ]
                sample = json.loads(
                    subprocess.run(
                        args, check=True, capture_output=True, timeout=60
                    ).stdout
                )
                if repetition < 0 and mode != "recovery":
                    continue
                sample["repetition"] = str(repetition)
                sample["workload_sha256"] = manifest["sha256"]
                if repetition >= 0:
                    results.append(sample)
                    (root / f"{mode}-{repetition}.json").write_bytes(
                        canonical(sample) + b"\n"
                    )
                if mode == "recovery":
                    subprocess.run(
                        [
                            "_build/default/bin/main.exe",
                            "snapshot",
                            "--session-dir",
                            str(session),
                        ],
                        check=True,
                        capture_output=True,
                        timeout=60,
                    )
                    snap = json.loads(
                        subprocess.run(
                            args, check=True, capture_output=True, timeout=60
                        ).stdout
                    )
                    if repetition < 0:
                        continue
                    snap["mode"] = "recovery-with-snapshot"
                    snap["repetition"] = str(repetition)
                    snap["workload_sha256"] = manifest["sha256"]
                    results.append(snap)
                    (root / f"recovery-with-snapshot-{repetition}.json").write_bytes(
                        canonical(snap) + b"\n"
                    )
    summaries = []
    for mode in sorted({r["mode"] for r in results}):
        group = [r for r in results if r["mode"] == mode]
        elapsed = [int(r["elapsed_ns"]) / 1e9 for r in group]
        summaries.append(
            dict(
                mode=mode,
                repetitions=str(len(group)),
                median_accepted_orders_per_second=f"{statistics.median(int(r['accepted_orders']) / (int(r['elapsed_ns']) / 1e9) for r in group):.3f}",
                median_trades_per_second=f"{statistics.median(int(r['trades']) / (int(r['elapsed_ns']) / 1e9) for r in group):.3f}",
                median_seconds=f"{statistics.median(elapsed):.9f}",
                median_attempts_per_second=f"{statistics.median(int(r['attempts']) / (int(r['elapsed_ns']) / 1e9) for r in group):.3f}",
                median_unique_commands_per_second=f"{statistics.median(int(r['unique_commands']) / (int(r['elapsed_ns']) / 1e9) for r in group):.3f}",
            )
        )
    (root / "summary.json").write_bytes(canonical(summaries) + b"\n")
    # Standalone SVG chart generated solely from saved results, no external plotting dependency.
    max_time = max(float(x["median_seconds"]) for x in summaries)
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="420" viewBox="0 0 900 420">',
        '<rect width="900" height="420" fill="white"/><text x="25" y="30" font-family="sans-serif" font-size="19">Native workload elapsed time — median of five repetitions</text>',
    ]
    for i, row in enumerate(summaries):
        y = 70 + i * 55
        width = 450 * float(row["median_seconds"]) / max_time
        svg.append(
            f'<text x="25" y="{y + 18}" font-family="sans-serif">{row["mode"]}</text><rect x="260" y="{y}" width="{width:.1f}" height="28" fill="#2463a5"/><text x="{270 + width:.1f}" y="{y + 18}" font-family="sans-serif">{row["median_seconds"]} s</text>'
        )
    svg.append(
        '<text x="25" y="390" font-family="sans-serif">Scopes differ; these bars are costs, not implementation speedups. See environment.json.</text></svg>'
    )
    (root / "elapsed.svg").write_text("\n".join(svg))
    return summaries
