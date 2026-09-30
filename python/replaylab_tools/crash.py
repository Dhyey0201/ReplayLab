"""Owned-child SIGKILL experiments; independent journal-prefix oracle."""

import hashlib
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
from replaylab_ref.codec import canonical
from replaylab_ref.engine import Session
from .compare import Reader, difference, ExperimentTimeout


class CrashMismatch(AssertionError):
    def __init__(self, report):
        super().__init__(report["signature"])
        self.report = report


HOOKS = (
    "before_append",
    "after_partial_append",
    "after_append_before_sync",
    "after_sync_before_apply",
    "during_match_after_first_fill",
    "after_apply_before_response",
    "after_response",
    "snapshot_after_file_sync",
    "snapshot_after_rename",
)


def scan_prefix(path):
    raw = path.read_bytes()
    offset = 0
    commands = []
    while offset < len(raw):
        if len(raw) - offset < 10:
            break
        magic, version, length = struct.unpack(">4sHI", raw[offset : offset + 10])
        if magic != b"RPLB" or version != 1 or length > 65536:
            raise ValueError("corrupt journal header")
        end = offset + 42 + length
        if end > len(raw):
            break
        content = raw[offset : end - 32]
        if hashlib.sha256(content).digest() != raw[end - 32 : end]:
            raise ValueError("corrupt checksum")
        payload = json.loads(raw[offset + 10 : end - 32])
        if payload["seq"] != str(len(commands) + 1):
            raise ValueError("noncontiguous prefix")
        commands.append(payload["command"])
        offset = end
    return commands, offset, offset != len(raw)


def crash_check(candidate, workload, schedule, out, timeout=10):
    root = Path(out)
    root.mkdir(parents=True, exist_ok=False)
    executable = str(Path(candidate).resolve())
    records = Path(workload).read_bytes().split(b"\n")
    records = records[:-1] if records[-1] == b"" else records
    (root / "workload.jsonl").write_bytes(b"\n".join(records) + b"\n")
    plan = (
        json.loads(Path(schedule).read_bytes())
        if isinstance(schedule, (str, Path))
        else schedule
    )
    (root / "schedule.json").write_bytes(canonical(plan) + b"\n")
    hook = plan["hook"]
    seq = int(plan.get("seq", "3"))
    sid = plan.get("session_id", "crash")
    if hook not in HOOKS:
        raise ValueError("unknown hook")
    if "target_request" in plan:
        model = Session(sid)
        seq = None
        for raw in records:
            response = model.handle(raw)
            if {
                "client_id": response["client_id"],
                "request_id": response["request_id"],
            } == plan["target_request"]:
                seq = int(response["seq"])
                break
        if seq is None:
            raise ValueError("target request unreachable")
    candidate_args = plan.get("candidate_args", [])
    if not isinstance(candidate_args, list) or not all(
        isinstance(x, str) for x in candidate_args
    ):
        raise ValueError("invalid candidate argument list")
    manifest = dict(
        schema_version=1,
        semantics_version="replaylab-v1",
        mode="crash",
        session_id=sid,
        configuration=Session(sid).config.wire(),
        workload_sha256=hashlib.sha256(
            (root / "workload.jsonl").read_bytes()
        ).hexdigest(),
        candidate=executable,
        candidate_sha256=hashlib.sha256(Path(executable).read_bytes()).hexdigest(),
        candidate_args=candidate_args,
        build_identity="local working tree",
        status="incomplete",
        reproduction=[
            "python",
            "-m",
            "replaylab_tools",
            "crash-check",
            "--candidate",
            executable,
            "--workload",
            str((root / "workload.jsonl").resolve()),
            "--schedule",
            str((root / "schedule.json").resolve()),
            "--out",
            "NEW_DIRECTORY",
        ],
    )
    (root / "manifest.json").write_bytes(canonical(manifest) + b"\n")

    def check_state(expected, actual, phase):
        delta = difference(expected, actual, "state")
        if delta:
            from .compare import classify

            path, want, got = delta
            report = dict(
                attempt=str(len(records)),
                seq=str(seq),
                path=path,
                expected=want,
                actual=got,
                signature=f"crash:{hook}:{phase}:" + classify(path, want, got, b"{}"),
                book_before=None,
                book_after=Session(sid).book_state(),
            )
            (root / "difference.json").write_bytes(canonical(report) + b"\n")
            (root / "reference-state.json").write_bytes(canonical(expected) + b"\n")
            (root / "candidate-state.json").write_bytes(canonical(actual) + b"\n")
            manifest["status"] = "mismatch"
            (root / "manifest.json").write_bytes(canonical(manifest) + b"\n")
            raise CrashMismatch(report)

    session = root / "session"
    empty = root / "empty.jsonl"
    empty.write_bytes(b"")
    ack = []
    sent = []
    notify_r, notify_w = os.pipe()
    control_r, control_w = os.pipe()
    args = [
        executable,
        "stream",
        "--mode",
        "durable",
        "--session-dir",
        str(session),
        "--session-id",
        sid,
    ]
    snapshot_hook = hook.startswith("snapshot_")
    if snapshot_hook:
        completed = root / "completed.jsonl"
        completed.write_bytes(b"\n".join(records) + b"\n")
        subprocess.run(
            [
                executable,
                "run",
                "--mode",
                "durable",
                "--session-dir",
                str(session),
                "--session-id",
                sid,
                "--input",
                str(completed),
                "--responses",
                str(root / "before.jsonl"),
                *candidate_args,
            ],
            check=True,
            capture_output=True,
            timeout=timeout,
        )
        ack = [json.loads(x) for x in (root / "before.jsonl").read_bytes().splitlines()]
        sent = list(records)
        seq = max(int(r["seq"]) for r in ack if r["seq"])
        args = [executable, "snapshot", "--session-dir", str(session)]
    args += candidate_args + [
        "--hook",
        hook,
        "--hook-seq",
        str(seq),
        "--notify-fd",
        str(notify_w),
        "--control-fd",
        str(control_r),
    ]
    with (root / "child.stderr").open("wb") as stderr:
        child = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            pass_fds=(notify_w, control_r),
        )
        os.close(notify_w)
        os.close(control_r)
        notification = os.fdopen(notify_r, "rb", buffering=0)
        hook_reader = Reader(notification, timeout)
        response_reader = Reader(child.stdout, timeout)
        try:
            if not snapshot_hook:
                model = Session(sid)
                for raw in records:
                    expected = model.handle(raw)
                    sent.append(raw)
                    child.stdin.write(raw + b"\n")
                    child.stdin.flush()
                    target = expected["seq"] == str(seq) and not expected["duplicate"]
                    if target and hook != "after_response":
                        break
                    response = response_reader.line()
                    if response is None:
                        raise RuntimeError("child exited before response")
                    ack.append(json.loads(response))
                    if target:
                        break
                else:
                    raise ExperimentTimeout("hook not reached: target request absent")
            reached = hook_reader.line()
            if reached != f"{hook} {seq}".encode():
                raise ExperimentTimeout("hook not reached or wrong hook notification")
            (root / "hook.txt").write_bytes(reached + b"\n")
            child.send_signal(signal.SIGKILL)
            child.wait(timeout=timeout)
            if child.returncode != -signal.SIGKILL:
                raise RuntimeError("child was not killed by SIGKILL")
        finally:
            if child.poll() is None:
                child.kill()
            child.wait()
            hook_reader.close()
            response_reader.close()
            notification.close()
            os.close(control_w)
            child.stdin.close()
            child.stdout.close()
    (root / "acknowledged.jsonl").write_bytes(
        b"".join(canonical(r) + b"\n" for r in ack)
    )
    commands, valid_bytes, incomplete = scan_prefix(session / "commands.wal")
    oracle = Session(sid)
    for command in commands:
        oracle.handle(canonical(command))
    for response in ack:
        if response["seq"] is None:
            continue
        key = response["client_id"], response["request_id"]
        if key not in oracle.requests:
            raise AssertionError("acknowledged request missing from prefix")
        cached = oracle.requests[key][1]
        if any(response[k] != cached[k] for k in ("seq", "result", "events")):
            raise AssertionError("acknowledged outcome changed")
    # Save the untouched crashed WAL before explicit repair.
    (root / "crashed.wal").write_bytes((session / "commands.wal").read_bytes())
    subprocess.run(
        [
            executable,
            "recover",
            "--session-dir",
            str(session),
            "--repair-incomplete-tail",
            "--input",
            str(empty),
            "--state-out",
            str(root / "prefix-state.json"),
            *candidate_args,
        ],
        check=True,
        capture_output=True,
        timeout=timeout,
    )
    recovered = json.loads((root / "prefix-state.json").read_bytes())
    check_state(oracle.session_state(), recovered, "prefix")
    # Retrying all submitted keys covers uncertain delivery; finish the unsubmitted suffix.
    resume = root / "resume.jsonl"
    resume.write_bytes(b"\n".join(sent + records[len(sent) :]) + b"\n")
    subprocess.run(
        [
            executable,
            "recover",
            "--session-dir",
            str(session),
            "--input",
            str(resume),
            "--responses",
            str(root / "resumed.jsonl"),
            "--state-out",
            str(root / "final-state.json"),
            *candidate_args,
        ],
        check=True,
        capture_output=True,
        timeout=timeout,
    )
    uninterrupted = Session(sid)
    for raw in records:
        uninterrupted.handle(raw)
    final = json.loads((root / "final-state.json").read_bytes())
    check_state(uninterrupted.session_state(), final, "final")
    report = dict(
        schema_version=1,
        hook=hook,
        hook_reached=True,
        kill="SIGKILL",
        hook_seq=str(seq),
        acknowledged_responses=str(len(ack)),
        durable_prefix=str(len(commands)),
        valid_bytes=str(valid_bytes),
        incomplete_tail=incomplete,
        prefix_equal=True,
        final_equal=True,
        candidate_sha256=hashlib.sha256(Path(executable).read_bytes()).hexdigest(),
        workload_sha256=hashlib.sha256(
            (root / "workload.jsonl").read_bytes()
        ).hexdigest(),
        evidence_scope="process crash; OS page cache survives",
        unique_trades=str(
            sum(
                e["type"] == "trade"
                for _, r in uninterrupted.requests.values()
                for e in r["events"]
            )
        ),
    )
    manifest["status"] = "agreement"
    (root / "manifest.json").write_bytes(canonical(manifest) + b"\n")
    (root / "report.json").write_bytes(canonical(report) + b"\n")
    return report
