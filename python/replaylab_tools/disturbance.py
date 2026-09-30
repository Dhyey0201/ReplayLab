"""Deterministic logical-time request admission and response delivery experiments."""

import hashlib
import json
from pathlib import Path
from replaylab_ref.codec import canonical
from .compare import save_comparison


def disturbance_check(candidate, workload, schedule, out):
    raw = Path(workload).read_bytes()
    records = raw.split(b"\n")
    records = [r + b"\n" for r in records[:-1]] + ([records[-1]] if records[-1] else [])
    plan = json.loads(Path(schedule).read_bytes())
    if not isinstance(plan, dict) or set(plan) != {"disturbances"}:
        raise ValueError("schedule must contain disturbances")
    changes = {}
    for item in plan["disturbances"]:
        if not isinstance(item, dict) or set(item) - {
            "attempt",
            "request_delay_ticks",
            "response_delay_ticks",
            "drop_response",
            "duplicates",
        }:
            raise ValueError("invalid disturbance")
        attempt = item.get("attempt")
        if (
            type(attempt) is not int
            or not 1 <= attempt <= len(records)
            or attempt in changes
        ):
            raise ValueError("disturbance attempt must be unique and in range")
        for name in ("request_delay_ticks", "response_delay_ticks", "duplicates"):
            value = item.get(name, 0)
            if type(value) is not int or not 0 <= value <= 10000:
                raise ValueError("disturbance counts must be integers in 0..10000")
        if type(item.get("drop_response", False)) is not bool:
            raise ValueError("drop_response must be boolean")
        changes[attempt] = item
    admissions = []
    for index, record in enumerate(records, 1):
        change = changes.get(index, {})
        for copy in range(1 + change.get("duplicates", 0)):
            admissions.append(
                (index + change.get("request_delay_ticks", 0), index, copy, record)
            )
    if len(admissions) > 2000000:
        raise ValueError("expanded workload exceeds limit")
    admissions.sort(key=lambda a: a[:3])
    root = Path(out)
    root.mkdir(parents=True, exist_ok=False)
    (root / "original.jsonl").write_bytes(raw)
    (root / "schedule.json").write_bytes(canonical(plan) + b"\n")
    admitted = root / "admitted.jsonl"
    admitted.write_bytes(b"".join(a[3] for a in admissions))
    manifest = dict(
        schema_version=1,
        mode="logical-time-disturbance",
        semantics_version="replaylab-v1",
        workload_sha256=hashlib.sha256(raw).hexdigest(),
        status="incomplete",
        disturbances=plan["disturbances"],
    )
    (root / "manifest.json").write_bytes(canonical(manifest) + b"\n")
    comparison = save_comparison(
        candidate, admitted, "disturbance", root / "comparison"
    )
    responses = [
        json.loads(line)
        for line in (root / "comparison/candidate.jsonl").read_bytes().splitlines()
    ]
    executions, deliveries = [], []
    for ordinal, (admission, response) in enumerate(zip(admissions, responses), 1):
        tick, original, copy, _ = admission
        change = changes.get(original, {})
        execution = dict(
            admission=str(ordinal),
            original_attempt=str(original),
            copy=str(copy),
            admission_tick=str(tick),
            seq=response.get("seq"),
            response=response,
        )
        executions.append(execution)
        # A drop affects delivery only: execution and subsequent exact retries remain intact.
        if not (change.get("drop_response", False) and copy == 0):
            deliveries.append(
                dict(
                    execution,
                    delivery_tick=str(tick + change.get("response_delay_ticks", 0)),
                )
            )
    deliveries.sort(key=lambda e: (int(e["delivery_tick"]), int(e["admission"])))
    for name, entries in (("executions", executions), ("deliveries", deliveries)):
        (root / f"{name}.jsonl").write_bytes(
            b"".join(canonical(e) + b"\n" for e in entries)
        )
    manifest.update(
        status=comparison["status"],
        admissions=str(len(admissions)),
        delivered=str(len(deliveries)),
        admission_order=[str(a[1]) for a in admissions],
        session_hash=comparison["session_hash"],
        timing="logical ticks; no wall-clock or network latency claim",
    )
    (root / "manifest.json").write_bytes(canonical(manifest) + b"\n")
    return manifest
