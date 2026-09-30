import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import tempfile
import time
from replaylab_ref.codec import canonical, digest
from replaylab_ref.engine import Session


class ExperimentTimeout(RuntimeError):
    pass


def difference(expected, actual, path=""):
    if type(expected) is not type(actual):
        return path, expected, actual
    if isinstance(expected, dict):
        for k in sorted(set(expected) | set(actual)):
            p = f"{path}.{k}" if path else k
            if k not in expected or k not in actual:
                return p, expected.get(k), actual.get(k)
            diff = difference(expected[k], actual[k], p)
            if diff:
                return diff
    elif isinstance(expected, list):
        for i, (a, b) in enumerate(zip(expected, actual)):
            diff = difference(a, b, f"{path}[{i}]")
            if diff:
                return diff
        if len(expected) != len(actual):
            return path + ".length", len(expected), len(actual)
    elif expected != actual:
        return path, expected, actual
    return None


class Reader:
    def __init__(self, stream, timeout, deadline=None):
        self.deadline = deadline
        self.stream = stream
        self.timeout = timeout
        self.buffer = b""
        self.selector = selectors.SelectSelector()
        self.selector.register(stream, selectors.EVENT_READ)

    def line(self):
        deadline = min(time.monotonic() + self.timeout, self.deadline or float("inf"))
        if time.monotonic() >= deadline:
            raise ExperimentTimeout("experiment deadline exceeded")
        while b"\n" not in self.buffer:
            if not self.selector.select(max(0, deadline - time.monotonic())):
                raise ExperimentTimeout("response timeout")
            chunk = os.read(self.stream.fileno(), 65536)
            if not chunk:
                if self.buffer:
                    raise RuntimeError("incomplete response")
                return None
            self.buffer += chunk
            if len(self.buffer) > 128 * 1024 * 1024:
                raise RuntimeError("response exceeds bounded controller limit")
        line, self.buffer = self.buffer.split(b"\n", 1)
        return line

    def close(self):
        self.selector.close()


def classify(path, expected, actual, command):
    if path.startswith("events"):
        category = "event_mismatch"
    elif path.startswith("state"):
        category = "state_mismatch"
    elif "subcode" in path:
        category = "protocol_mismatch"
    else:
        category = "business_decision_mismatch"
    import re

    normalized = re.sub(r"\[\d+\]", "[]", path)
    direction = "different"
    if (
        isinstance(expected, str)
        and isinstance(actual, str)
        and expected.isdecimal()
        and actual.isdecimal()
    ):
        direction = "less" if int(actual) < int(expected) else "greater"
    try:
        kind = json.loads(command).get("type", "unknown")
    except (ValueError, UnicodeError, AttributeError):
        kind = "malformed"
    return f"{category}:{kind}:{normalized}:{direction}"


def evaluate(
    candidate,
    records,
    session_id="comparison",
    timeout=10,
    candidate_args=(),
    checkpoint_every=None,
):
    """One child, streamed response comparison; bounded stderr goes directly to disk."""
    deadline = time.monotonic() + timeout
    reference = Session(session_id)
    expected = []
    actual = []
    report = None
    before = None
    failure_kind = None
    with tempfile.TemporaryDirectory(prefix="replaylab-compare-") as directory:
        root = Path(directory)
        workload = root / "workload.jsonl"
        state = root / "state.json"
        workload.write_bytes(b"".join(records))
        interval = checkpoint_every or (1 if len(records) <= 100 else 250)
        trace_path = root / "state-trace.fifo"
        os.mkfifo(trace_path)
        trace_fd = os.open(trace_path, os.O_RDWR | os.O_NONBLOCK)
        trace_file = os.fdopen(trace_fd, "rb", buffering=0)
        trace_reader = Reader(trace_file, timeout, deadline)
        args = [
            str(Path(candidate).resolve()),
            "run",
            "--mode",
            "memory",
            "--session-id",
            session_id,
            "--input",
            str(workload),
            "--state-out",
            str(state),
            "--state-trace",
            str(trace_path),
            "--state-checkpoint",
            str(interval),
            *candidate_args,
        ]
        with (root / "stderr").open("wb") as err:
            child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=err)
            reader = Reader(child.stdout, timeout, deadline)
            try:
                for index, raw in enumerate(records):
                    before = reference.book_state()
                    exp = reference.handle(raw)
                    reference.assert_invariants()
                    expected.append(exp)
                    line = reader.line()
                    if line is None:
                        raise RuntimeError(f"candidate stopped at attempt {index + 1}")
                    got = json.loads(line)
                    actual.append(got)
                    diff = difference(exp, got)
                    if not diff and (index + 1) % interval == 0:
                        trace_line = trace_reader.line()
                        if trace_line is None:
                            raise RuntimeError("missing state checkpoint")
                        diff = difference(
                            reference.session_state(), json.loads(trace_line), "state"
                        )
                    if diff:
                        path, want, observed = diff
                        report = dict(
                            attempt=str(index + 1),
                            seq=exp["seq"],
                            path=path,
                            expected=want,
                            actual=observed,
                            signature=classify(path, want, observed, raw),
                            book_before=before,
                            book_after=reference.book_state(),
                        )
                        break
                if report:
                    child.terminate()
                else:
                    if reader.line() is not None:
                        raise RuntimeError("extra candidate response")
                child.wait(timeout=max(0.001, deadline - time.monotonic()))
                if not report and child.returncode:
                    raise RuntimeError(f"candidate exit {child.returncode}")
            except (
                ExperimentTimeout,
                subprocess.TimeoutExpired,
                RuntimeError,
                ValueError,
            ) as error:
                failure_kind = (
                    "timeout"
                    if isinstance(error, (ExperimentTimeout, subprocess.TimeoutExpired))
                    else "candidate_crash"
                    if child.poll() not in (None, 0) or "stopped" in str(error)
                    else "invalid_candidate_output"
                )
                report = dict(
                    attempt=str(len(expected)),
                    seq=str(reference.last_seq),
                    path="execution",
                    expected="valid response and successful exit",
                    actual=str(error),
                    signature=f"{failure_kind}:execution",
                    book_before=before,
                    book_after=reference.book_state(),
                )
            finally:
                if child.poll() is None:
                    child.kill()
                child.wait()
                reader.close()
                child.stdout.close()
                trace_reader.close()
                trace_file.close()
        stderr = (root / "stderr").read_text(errors="replace")
        ref_state = reference.session_state()
        candidate_state = (
            json.loads(state.read_bytes()) if state.exists() and not report else None
        )
        if not report:
            diff = difference(ref_state, candidate_state, "state")
            if diff:
                path, want, observed = diff
                report = dict(
                    attempt=str(len(records)),
                    seq=str(reference.last_seq),
                    path=path,
                    expected=want,
                    actual=observed,
                    signature=classify(
                        path, want, observed, records[-1] if records else b"{}"
                    ),
                    book_before=before,
                    book_after=reference.book_state(),
                )
        if report:
            attempt = int(report["attempt"])
            report["command_raw"] = (
                records[attempt - 1].decode("utf-8", errors="backslashreplace")
                if attempt
                else ""
            )
        return dict(
            failure_kind=failure_kind,
            difference=report,
            reference=expected,
            candidate=actual,
            reference_state=ref_state,
            candidate_state=candidate_state,
            stderr=stderr,
        )


def save_comparison(
    candidate, workload, session_id, out, candidate_args=(), timeout=10
):
    root = Path(out)
    root.mkdir(parents=True, exist_ok=False)
    records = Path(workload).read_bytes().splitlines(keepends=True)
    # Split only LF, preserving CR and malformed raw bytes.
    raw = Path(workload).read_bytes()
    records = raw.split(b"\n")
    records = [line + b"\n" for line in records[:-1]] + (
        [records[-1]] if records[-1] else []
    )
    (root / "workload.jsonl").write_bytes(raw)
    manifest = dict(
        schema_version=1,
        semantics_version="replaylab-v1",
        mode="memory",
        session_id=session_id,
        configuration=Session(session_id).config.wire(),
        workload_sha256=hashlib.sha256(raw).hexdigest(),
        candidate=str(Path(candidate).resolve()),
        candidate_sha256=hashlib.sha256(Path(candidate).read_bytes()).hexdigest(),
        candidate_args=list(candidate_args),
        build_identity="local working tree",
        status="incomplete",
        reproduction=[
            "python",
            "-m",
            "replaylab_tools",
            "compare",
            "--candidate",
            str(Path(candidate).resolve()),
            "--workload",
            str((root / "workload.jsonl").resolve()),
            "--session-id",
            session_id,
            "--out",
            "NEW_DIRECTORY",
            *["--candidate-arg=" + arg for arg in candidate_args],
        ],
    )
    (root / "manifest.json").write_bytes(canonical(manifest) + b"\n")
    result = evaluate(candidate, records, session_id, timeout, candidate_args)
    if result["difference"] and result["difference"]["path"].startswith("state"):
        # State may diverge before outputs. Rerun only the failing prefix with a trace every attempt.
        result = evaluate(
            candidate,
            records[: int(result["difference"]["attempt"])],
            session_id,
            timeout,
            candidate_args,
            checkpoint_every=1,
        )
    if result["difference"] and not result["failure_kind"]:
        prefix = records[: int(result["difference"]["attempt"])]
        (root / "prefix.jsonl").write_bytes(b"".join(prefix))
        # Preserve candidate state at the divergent prefix with a fresh bounded run.
        subprocess.run(
            [
                str(Path(candidate).resolve()),
                "run",
                "--mode",
                "memory",
                "--session-id",
                session_id,
                "--input",
                str(root / "prefix.jsonl"),
                "--state-out",
                str(root / "candidate-state.json"),
                "--responses",
                str(root / "prefix-responses.jsonl"),
                *candidate_args,
            ],
            check=True,
            timeout=timeout,
            capture_output=True,
        )
    for name, key in [
        ("reference.jsonl", "reference"),
        ("candidate.jsonl", "candidate"),
    ]:
        (root / name).write_bytes(b"".join(canonical(r) + b"\n" for r in result[key]))
    (root / "reference-state.json").write_bytes(
        canonical(result["reference_state"]) + b"\n"
    )
    if result["candidate_state"] is not None:
        (root / "candidate-state.json").write_bytes(
            canonical(result["candidate_state"]) + b"\n"
        )
    (root / "candidate.stderr").write_text(result["stderr"])
    (root / "reference.stderr").write_text("")
    (root / "difference.json").write_bytes(canonical(result["difference"]) + b"\n")
    manifest["status"] = result["failure_kind"] or (
        "mismatch" if result["difference"] else "agreement"
    )
    manifest["attempts"] = str(len(records))
    manifest["session_hash"] = digest(result["reference_state"])
    (root / "manifest.json").write_bytes(canonical(manifest) + b"\n")
    return manifest
