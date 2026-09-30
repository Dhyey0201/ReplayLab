"""Native recovery timings versus saved journal size, with five repetitions."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from replaylab_ref.codec import canonical

root = Path(sys.argv[1])
executable = str(Path("_build/default/bin/bench.exe").resolve())
records = (root / "workload.jsonl").read_bytes().splitlines(keepends=True)
results = []
with tempfile.TemporaryDirectory(prefix="replaylab-recovery-scaling-") as temp:
    for count in [100, 500, 1000]:
        source = Path(temp) / f"{count}.jsonl"
        source.write_bytes(b"".join(records[:count]))
        session = Path(temp) / f"session-{count}"
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
                str(source),
                "--responses",
                str(Path(temp) / "responses"),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        journal_size = (session / "commands.wal").stat().st_size
        for snap in [False, True]:
            if snap:
                subprocess.run(
                    [
                        "_build/default/bin/main.exe",
                        "snapshot",
                        "--session-dir",
                        str(session),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=30,
                )
            for repetition in range(-1, 5):
                result = json.loads(
                    subprocess.run(
                        [
                            executable,
                            "--mode",
                            "recovery",
                            "--session-dir",
                            str(session),
                        ],
                        check=True,
                        capture_output=True,
                        timeout=30,
                    ).stdout
                )
                if repetition < 0:
                    continue
                result.update(
                    attempted_workload_size=str(count),
                    journal_bytes=str(journal_size),
                    snapshot=snap,
                    repetition=str(repetition),
                    workload_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                    candidate_sha256=hashlib.sha256(
                        Path(executable).read_bytes()
                    ).hexdigest(),
                )
                results.append(result)
(root / "recovery-scaling.json").write_bytes(canonical(results) + b"\n")
print(f"{len(results)} recovery measurements written to {root}")
