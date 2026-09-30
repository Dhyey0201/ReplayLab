import argparse
from pathlib import Path
import sys
import tempfile
from replaylab_ref.codec import canonical
from .generate import save, PROFILES
from .compare import save_comparison, ExperimentTimeout


def main():
    p = argparse.ArgumentParser(description="ReplayLab reproducible experiments")
    sub = p.add_subparsers(dest="command", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--profile", choices=PROFILES, default="balanced")
    g.add_argument("--seed", type=int, required=True)
    g.add_argument("--count", type=int, required=True)
    g.add_argument("--out", required=True)
    c = sub.add_parser("compare")
    c.add_argument("--candidate", required=True)
    c.add_argument("--workload", required=True)
    c.add_argument("--session-id", default="comparison")
    c.add_argument("--candidate-arg", action="append", default=[])
    c.add_argument("--out", required=True)
    d = sub.add_parser("demo")
    d.add_argument("--candidate", default="_build/default/bin/main.exe")
    c = sub.add_parser("crash-check")
    c.add_argument("--candidate", required=True)
    c.add_argument("--workload", required=True)
    c.add_argument("--schedule", required=True)
    c.add_argument("--out", required=True)
    q = sub.add_parser("disturbance-check")
    for flag in ("candidate", "workload", "schedule", "out"):
        q.add_argument("--" + flag, required=True)
    s = sub.add_parser("shrink")
    s.add_argument("--failure", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--max-evaluations", type=int, default=2000)
    s.add_argument("--timeout-seconds", type=float, default=300)
    b = sub.add_parser("benchmark")
    b.add_argument("--config", required=True)
    b.add_argument("--out", required=True)
    sub.add_parser("demo-crash")
    sub.add_parser("demo-shrink")
    args = p.parse_args()
    if args.command == "generate":
        result = save(args.profile, args.seed, args.count, args.out)
    elif args.command == "compare":
        result = save_comparison(
            args.candidate, args.workload, args.session_id, args.out, args.candidate_arg
        )
    elif args.command == "crash-check":
        from .crash import crash_check

        result = crash_check(args.candidate, args.workload, args.schedule, args.out)
    elif args.command == "disturbance-check":
        from .disturbance import disturbance_check

        result = disturbance_check(
            args.candidate, args.workload, args.schedule, args.out
        )
    elif args.command == "shrink":
        from .shrink import shrink

        result = shrink(
            args.failure, args.out, args.max_evaluations, args.timeout_seconds
        )
    elif args.command == "benchmark":
        from .benchmark import benchmark

        result = {"measurements": benchmark(args.config, args.out)}
    elif args.command == "demo-crash":
        from .crash import crash_check

        Path("artifacts").mkdir(exist_ok=True)
        root = Path(tempfile.mkdtemp(prefix="crash-", dir="artifacts")) / "experiment"
        result = crash_check(
            "_build/default/test/engine/test_engine.exe",
            "fixtures/golden/recovery.jsonl",
            "demos/crash-plan.json",
            root,
        )
        print(
            f"Actual SIGKILL at {result['hook']}; acknowledged {result['acknowledged_responses']}, recovered prefix {result['durable_prefix']}; final equality {result['final_equal']}. Artifacts: {root}",
            file=sys.stderr,
        )
    elif args.command == "demo-shrink":
        from .shrink import shrink

        Path("artifacts").mkdir(exist_ok=True)
        root = Path(tempfile.mkdtemp(prefix="shrink-", dir="artifacts"))
        save("balanced", 42, 500, root / "generated.jsonl")
        save_comparison(
            "_build/default/test/engine/test_engine.exe",
            root / "generated.jsonl",
            "shrink",
            root / "failure",
            ["--mutant", "lifo"],
        )
        result = shrink(root / "failure", root / "reduced")
        corrected = save_comparison(
            "_build/default/bin/main.exe",
            root / "reduced/workload.jsonl",
            "shrink",
            root / "corrected",
        )
        result["corrected_status"] = corrected["status"]
        result["cached_artifacts_used"] = False
        print(
            f"Reduced {result['original_commands']} to {result['final_commands']} commands; {result['minimality']}; corrected engine: {corrected['status']}. Artifacts: {root}",
            file=sys.stderr,
        )
    else:
        Path("artifacts").mkdir(exist_ok=True)
        root = (
            Path(tempfile.mkdtemp(prefix="matching-", dir="artifacts")) / "comparison"
        )
        result = save_comparison(
            args.candidate, "fixtures/golden/walkthrough.jsonl", "golden", root
        )
        print(
            f"Golden walkthrough: {result['status']}; two distinct trades (10 + 2), one cancellation (5).",
            file=sys.stderr,
        )
        print(
            f"Retries repeat event IDs without executing trades. Artifacts: {root}",
            file=sys.stderr,
        )
    print(canonical(result).decode())
    if result.get("status") == "timeout" or result.get("validation_passed") is False:
        return 4
    return (
        1
        if result.get("status")
        in {"mismatch", "candidate_crash", "invalid_candidate_output"}
        else 0
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ExperimentTimeout as e:
        print(str(e), file=sys.stderr)
        sys.exit(4)
    except (ValueError, FileExistsError) as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)
    except OSError as e:
        print(str(e), file=sys.stderr)
        sys.exit(3)
