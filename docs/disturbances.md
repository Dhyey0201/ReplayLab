# Scheduled disturbances

Run a saved logical-time experiment:

```sh
PYTHONPATH=python .venv/bin/python -m replaylab_tools disturbance-check \
  --candidate _build/default/bin/main.exe \
  --workload fixtures/golden/walkthrough.jsonl \
  --schedule demos/disturbance-plan.json --out artifacts/disturbance
```

Each input attempt starts at its one-based logical tick. A request delay changes
its admission tick; ties use original attempt and copy index. The controller
saves the resulting admission order before running the candidate and independent
reference. Exact duplicate copies retain the original bytes and request key.
Already sequenced commands are never reordered.

Response drops and response delays apply to delivery records after execution.
A drop suppresses the original delivery, while duplicate retries still deliver
the cached response. Execution records and final state retain every admitted
transition. Output contains original/admitted workloads, the schedule, execution
and delivery records, and the complete differential comparison. The manifest
makes admission-order changes explicit. These are deterministic logical-time
experiments, not wall-clock latency or network measurements.

Comparison failures also preserve partial outputs, stderr, reference state,
workload and a stable classification for timeout, candidate crash, or invalid
candidate output. Reproduction commands retain explicit candidate arguments.

Shrinking records its predicate-evaluation budget separately from the three fresh
validation repetitions. A time-limited run saves its best workload and report;
failed or incomplete validation returns a nonzero CLI status and does not earn
a verified minimality claim.
