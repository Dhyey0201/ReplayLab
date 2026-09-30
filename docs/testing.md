# Validation and reproduction

Run `make test` for native foundation/I/O tests plus Python semantic,
differential, persistence, crash, state-trace and shrinker tests. `make check` also
checks OCaml formatting. `make test-deep` adds 100 saved seeds × 1,000 attempts,
rotating through all ten profiles. Seed values 0–99 and generator version 1 are
fixed; replay uses saved bytes, not future PRNG regeneration.

The ordinary differential suite uses seeds 0–19 with 1,000 balanced attempts each,
compares every response and final full state, and asks the candidate to check
invariants after each attempt. A separate tiny workload compares full semantic
state after every attempt through `--state-trace`. Golden expectations are hand
calculated, not generated solely from candidate output.

Persistence tests mutate fresh copied/test sessions, exercise every byte cut of a
two-frame WAL, test corrupt complete/middle frames and recomputed-checksum invalid
payloads, verify no read-only mutation, and check locks and snapshot fallback.
All nine required crash hooks are tested; snapshot hooks use the completed
snapshot sequence. Child processes have timeouts and are killed/reaped in finally
blocks. An unreachable hook is an incomplete experiment, never a pass.

Test-only mutants reverse FIFO, use incoming execution price, mishandle middle
cancellation, and bypass deduplication. Each has a targeted witness. The generated
FIFO demo records the original, divergent prefix and reduced workload, difference
path, build/workload hashes, response streams, state projections and stderr.

The shrink predicate preserves mismatch class, command type, normalized semantic
path and numeric direction. It ignores shifting attempt/sequence indices.
Reduction performs earliest-prefix retention, contiguous chunk removal, grouped
request-family numeric changes, injective identity renaming, and a final deletion
fixed point. Final validation reruns three fresh engines. Budgets preserve the
best known workload. “1-minimal under deletion” is only reported after every
single deletion has been checked; global minimality is never claimed.

Crash shrinking additionally preserves hook and failure phase, retargets the
stable request key after each deletion, and uses a new session directory per
trial. It does not rename crash-target identities. Removing the target or making
a hook unreachable fails the predicate. `test_crash_shrinking_retargets_request_key`
reduces a real externally killed mutant experiment from four commands to two.

Local artifacts are under ignored `artifacts/` directories. CI uploads them on
failure as well as success. No remote service is required to replay a saved case.
