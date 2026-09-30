# ReplayLab

ReplayLab is a local exchange simulator for testing changes to a matching engine.
It runs an OCaml engine against an independent Python reference, saves the first
behavioral difference, and reduces a failing workload to a small reproduction.
Its journal and crash controller test what happens when a process dies between a
durable decision and its reply.

```sh
make setup
make demo
make demo-crash
make demo-shrink
```

The three demos actually execute both engines, kill a child process, and run the
shrinker. Observed on macOS arm64:

```text
Golden walkthrough: agreement; two distinct trades (10 + 2), one cancellation (5).
SIGKILL after_sync_before_apply: 2 acknowledged responses, 3 recovered commands.
FIFO mutant: 500 attempts -> 3 commands; 1-minimal under deletion.
Correct engine on reduced case: agreement.
```

Local validation includes 100 saved seeds × 1,000 attempts across ten profiles,
all nine crash hooks, every byte truncation of a two-frame journal, snapshot
fallback, and semantic/crash failure reduction. **Required release gates pass
on macOS and Linux**, including a fresh Linux toolchain installation.
See [PROGRESS.md](PROGRESS.md) and the [acceptance matrix](docs/acceptance.md)
for saved evidence. GitHub CI is also configured for Ubuntu 24.04.

## Setup

The tested toolchain is OCaml 5.2.1, Dune 3.17.2, opam 2.3.0 and Python 3.14.3.
You need Python, curl, a C compiler and standard build tools (Xcode command-line
tools on macOS; compiler/make on Linux). `make setup` downloads project-local
opam, creates `_opam` and `.venv`, and installs pinned dependencies. It does not
modify your global shell configuration. Network access is needed for setup.
The reference/runtime code requires Python 3.11+; the full development lock was
validated with 3.14.3. Other development Python versions are unverified.

```sh
make build       # native engine and isolated test executable
make check       # tests, native checks, formatting and lint
make test-deep   # ordinary suite plus 100 saved 1,000-attempt workloads
make clean-check # clean-source build using the existing pinned toolchain
make bench       # native release measurements, raw samples and static charts
```

## CLI

```sh
mkdir -p artifacts runs
./_build/default/bin/main.exe run --mode memory --session-id demo \
  --input fixtures/golden/walkthrough.jsonl \
  --responses artifacts/responses.jsonl --state-out artifacts/state.json

./_build/default/bin/main.exe run --mode durable --session-id demo \
  --session-dir runs/demo --input fixtures/golden/walkthrough.jsonl \
  --responses artifacts/durable-responses.jsonl

./_build/default/bin/main.exe verify-log --session-dir runs/demo
./_build/default/bin/main.exe snapshot --session-dir runs/demo
./_build/default/bin/main.exe replay --session-dir runs/demo \
  --state-out artifacts/replayed.json --events-out artifacts/events.jsonl
./_build/default/bin/main.exe inspect --session-dir runs/demo --view book
```

A durable `run` refuses a nonempty session directory. Use `recover` to continue;
only `recover --repair-incomplete-tail` may truncate an incomplete final frame.
Complete corruption fails closed. Every session operation takes the same lock.
`stream` reads stdin and flushes one JSON response per attempt. Full state traces
are available through `--state-trace FILE --state-checkpoint N`.

```sh
PYTHONPATH=python .venv/bin/python -m replaylab_tools generate \
  --profile balanced --seed 42 --count 1000 --out artifacts/workload.jsonl
PYTHONPATH=python .venv/bin/python -m replaylab_tools compare \
  --candidate ./_build/default/bin/main.exe --workload artifacts/workload.jsonl \
  --session-id comparison --out artifacts/comparison
```

Artifact directories refuse accidental overwrite. Exit codes are 0 success,
1 semantic/invariant difference, 2 usage/configuration, 3 storage/I/O failure,
and 4 timeout/incomplete experiment. A business rejection is a normal response.

## Evidence and reading order

Read [semantics](docs/semantics.md), [protocol](docs/protocol.md),
[architecture](docs/architecture.md), and [storage](docs/storage.md), then compare
[the independent reference](python/replaylab_ref/engine.py) with
[the OCaml book](lib/book.ml) and [session](lib/session.ml).
[Testing](docs/testing.md) explains the oracles and shrink predicate.
[Benchmark results](benchmarks/results/README.md) link raw samples and plots.

Scope is one instrument, integer limit orders, partial fills, FIFO priority,
whole-order cancellation, idempotency and finite retained history. This is an
educational systems project with no broker connectivity, trading strategy,
authentication, production-exchange claim, or employer endorsement.
See [limitations](docs/limitations.md) before interpreting durability or timing.

Scheduled duplicate, dropped-response, request-delay and response-delay
experiments are documented in [docs/disturbances.md](docs/disturbances.md).

To run the same release gates in a fresh Linux environment using Docker:

```sh
docker build --target evidence --output type=local,dest=artifacts/linux-validation .
```

This installs the pinned toolchain and runs checks, the 100-seed corpus, all three
demos, a clean-source build, and native benchmarks on the container filesystem.
It exports logs and a compressed artifact archive. Allow several GB of free disk
space. For an interactive development image, build with `--target development`.
