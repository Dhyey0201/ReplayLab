"""Clean-source build/test with the existing pinned toolchain; no fresh-install claim."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile

source = Path.cwd()
artifacts = source / "artifacts"
artifacts.mkdir(exist_ok=True)
logs = Path(tempfile.mkdtemp(prefix="clean-check-", dir=artifacts))
with tempfile.TemporaryDirectory(prefix="replaylab-clean-source-") as tmp:
    clean = Path(tmp) / "source"
    shutil.copytree(
        source,
        clean,
        ignore=shutil.ignore_patterns(
            ".git",
            "_opam",
            "_build",
            ".opam-root",
            ".tools",
            ".venv",
            "artifacts",
            "__pycache__",
            ".ruff_cache",
        ),
    )
    env = dict(
        os.environ,
        OPAMROOT=str(source / ".opam-root"),
        PYTHONPATH=str(clean / "python"),
    )
    commands = [
        [
            str(source / ".tools/opam"),
            "exec",
            "--switch=" + str(source),
            "--",
            "dune",
            "build",
            "--root",
            str(clean),
        ],
        [
            str(source / ".tools/opam"),
            "exec",
            "--switch=" + str(source),
            "--",
            "dune",
            "runtest",
            "--root",
            str(clean),
        ],
        [
            str(source / ".venv/bin/python"),
            "-m",
            "unittest",
            "discover",
            "-s",
            "test",
            "-p",
            "test_*.py",
            "-v",
        ],
    ]
    for index, command in enumerate(commands):
        with (logs / f"{index}.log").open("wb") as output:
            subprocess.run(
                command,
                cwd=clean,
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=180,
            )
    (logs / "scope.txt").write_text(
        "Clean source copy, clean Dune build, existing pinned OCaml switch and Python virtual environment. No fresh dependency installation or Linux validation claimed.\n"
    )
print(f"Clean-source build and tests passed. Logs: {logs}")
