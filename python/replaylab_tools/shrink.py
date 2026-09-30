"""Deterministic semantic delta debugging; no global-minimality claim."""

import hashlib
import json
from pathlib import Path
import time
import tempfile
import subprocess
from replaylab_ref.codec import canonical
from .compare import evaluate, save_comparison, ExperimentTimeout


class BudgetExhausted(Exception):
    pass


def shrink(failure, out, max_evaluations=2000, timeout_seconds=300):
    if max_evaluations < 1 or timeout_seconds <= 0:
        raise ValueError("positive shrink budgets required")
    source = Path(failure)
    root = Path(out)
    root.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((source / "manifest.json").read_bytes())
    original_diff = json.loads((source / "difference.json").read_bytes())
    if not original_diff:
        raise ValueError("failure directory contains no semantic mismatch")
    if original_diff["signature"].startswith("timeout:"):
        raise ValueError("timeouts are not semantic shrink predicates")
    candidate = manifest["candidate"]
    args = manifest.get("candidate_args", [])
    sid = manifest["session_id"]
    signature = original_diff["signature"]
    raw = (source / "workload.jsonl").read_bytes()
    records = raw.split(b"\n")
    records = [r + b"\n" for r in records[:-1]] + ([records[-1]] if records[-1] else [])
    (root / "original.jsonl").write_bytes(raw)
    current = records[: int(original_diff["attempt"])]
    crash_mode = manifest.get("mode") == "crash"
    plan = json.loads((source / "schedule.json").read_bytes()) if crash_mode else None
    if crash_mode and "target_request" not in plan:
        raise ValueError(
            "crash shrinking requires a stable target_request, not an absolute sequence"
        )

    def run_trial(trial, timeout):
        if not crash_mode:
            return evaluate(candidate, trial, sid, timeout, args)
        from .crash import crash_check, CrashMismatch

        with tempfile.TemporaryDirectory(prefix="replaylab-crash-shrink-") as temporary:
            trial_root = Path(temporary)
            workload = trial_root / "workload.jsonl"
            workload.write_bytes(b"".join(trial))
            try:
                crash_check(
                    candidate, workload, plan, trial_root / "experiment", timeout
                )
            except CrashMismatch as mismatch:
                return {"difference": mismatch.report}
            except (ValueError, ExperimentTimeout):
                return {"difference": None}
            return {"difference": None}

    started = time.monotonic()
    evaluations = 0
    cache_hits = 0
    cache = {}
    exhausted = False
    minimal = False

    def predicate(trial):
        nonlocal evaluations, cache_hits
        key = hashlib.sha256(b"".join(trial)).hexdigest()
        if key in cache:
            cache_hits += 1
            return cache[key]
        remaining = timeout_seconds - (time.monotonic() - started)
        if evaluations >= max_evaluations or remaining <= 0:
            raise BudgetExhausted()
        evaluations += 1
        try:
            result = run_trial(trial, min(10, remaining))
        except (ExperimentTimeout, RuntimeError, json.JSONDecodeError):
            cache[key] = False
            return False
        diff = result["difference"]
        cache[key] = bool(diff and diff["signature"] == signature)
        return cache[key]

    try:
        if not predicate(current):
            raise ValueError("saved signature does not reproduce")
        granularity = 2
        while current:
            chunk = max(1, (len(current) + granularity - 1) // granularity)
            for start in range(0, len(current), chunk):
                trial = current[:start] + current[start + chunk :]
                if predicate(trial):
                    current = trial
                    granularity = max(2, granularity - 1)
                    break
            else:
                if granularity >= len(current):
                    break
                granularity = min(len(current), granularity * 2)
                continue
            continue
        # Numeric changes apply to complete same-key/value request families, preserving identical retries.
        changed = True
        while changed:
            changed = False
            parsed = []
            for line in current:
                try:
                    parsed.append(json.loads(line))
                except (ValueError, UnicodeError):
                    parsed.append(None)
            for index, command in enumerate(parsed):
                if not isinstance(command, dict):
                    continue
                for field in ("quantity", "price_ticks"):
                    value = command.get(field)
                    if (
                        not isinstance(value, str)
                        or not value.isascii()
                        or not value.isdecimal()
                        or int(value) < 2
                    ):
                        continue
                    number = int(value)
                    options = {1, number // 2, number - 1}
                    if field == "price_ticks":
                        for other in parsed:
                            if (
                                isinstance(other, dict)
                                and str(other.get(field, "")).isascii()
                                and str(other.get(field, "")).isdecimal()
                            ):
                                p = int(other[field])
                                options.update([p - 1, p, p + 1])
                    for smaller in sorted(x for x in options if 0 < x < number):
                        trial = []
                        for raw_line, c in zip(current, parsed):
                            if isinstance(c, dict) and (
                                c.get("client_id"),
                                c.get("request_id"),
                                c.get(field),
                            ) == (
                                command.get("client_id"),
                                command.get("request_id"),
                                value,
                            ):
                                trial.append(
                                    canonical(dict(c, **{field: str(smaller)})) + b"\n"
                                )
                            else:
                                trial.append(raw_line)
                        if predicate(trial):
                            current = trial
                            changed = True
                            break
                    if changed:
                        break
                if changed:
                    break
        # Injective short renaming of complete identity classes.
        for field, prefix in (
            []
            if crash_mode
            else [("client_id", "c"), ("order_id", "o"), ("request_id", "r")]
        ):
            objects = []
            for line in current:
                try:
                    objects.append(json.loads(line))
                except (ValueError, UnicodeError):
                    objects.append(None)
            values = sorted(
                {
                    c[field]
                    for c in objects
                    if isinstance(c, dict) and isinstance(c.get(field), str)
                }
            )
            mapping = {value: f"{prefix}{i}" for i, value in enumerate(values)}
            trial = [
                canonical(dict(c, **{field: mapping[c[field]]})) + b"\n"
                if isinstance(c, dict)
                and isinstance(c.get(field), str)
                and c.get(field) in mapping
                else line
                for c, line in zip(objects, current)
            ]
            if predicate(trial):
                current = trial
        while True:
            for index in range(len(current)):
                trial = current[:index] + current[index + 1 :]
                if predicate(trial):
                    current = trial
                    break
            else:
                minimal = True
                break
    except BudgetExhausted:
        exhausted = True
    finally:
        (root / "workload.jsonl").write_bytes(b"".join(current))
    validations = []
    for _ in range(3):
        remaining = timeout_seconds - (time.monotonic() - started)
        if remaining <= 0:
            exhausted = True
            break
        try:
            result = run_trial(current, min(10, remaining))
        except (ExperimentTimeout, RuntimeError, ValueError):
            result = {"difference": None}
        validations.append(
            bool(
                result["difference"] and result["difference"]["signature"] == signature
            )
        )
    report = dict(
        schema_version=1,
        predicate=signature,
        max_evaluations=str(max_evaluations),
        evaluation_budget_scope="reduction predicates; validation repetitions reported separately",
        timeout_seconds=str(timeout_seconds),
        evaluations=str(evaluations),
        cache_hits=str(cache_hits),
        duration_seconds=f"{time.monotonic() - started:.6f}",
        original_commands=str(len(records)),
        final_commands=str(len(current)),
        original_bytes=str(len(raw)),
        final_bytes=str(sum(map(len, current))),
        budget_exhausted=exhausted,
        validation_repetitions=str(len(validations)),
        validation_passed=len(validations) == 3 and all(validations),
        minimality="1-minimal under deletion"
        if minimal and len(validations) == 3 and all(validations)
        else "reduced reproduction; minimality not verified",
    )
    (root / "report.json").write_bytes(canonical(report) + b"\n")
    remaining = timeout_seconds - (time.monotonic() - started)
    report["reproduction_saved"] = False
    if report["validation_passed"] and remaining > 0:
        try:
            if crash_mode:
                from .crash import crash_check, CrashMismatch

                (root / "schedule.json").write_bytes(canonical(plan) + b"\n")
                try:
                    crash_check(
                        candidate,
                        root / "workload.jsonl",
                        plan,
                        root / "reproduction",
                        remaining,
                    )
                except CrashMismatch:
                    pass
            else:
                save_comparison(
                    candidate,
                    root / "workload.jsonl",
                    sid,
                    root / "reproduction",
                    args,
                    remaining,
                )
            report["reproduction_saved"] = True
        except (ExperimentTimeout, TimeoutError, subprocess.TimeoutExpired):
            report["budget_exhausted"] = True
    elif remaining <= 0:
        report["budget_exhausted"] = True
    report["duration_seconds"] = f"{time.monotonic() - started:.6f}"
    (root / "report.json").write_bytes(canonical(report) + b"\n")
    return report
