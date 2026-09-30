# Engineering notes

- The requested Digestif 1.2.0 pin did not exist in the configured opam repository;
  corrected it to available 1.3.0 before claiming a successful build.
- A local opam switch initially auto-pinned the entire project, including its
  opam root. The setup script now uses --no-install and explicit dependencies to
  avoid source copying. No global shell configuration is changed.
- The first shrinker run exposed a controller race: terminating a divergent child
  could leave an incomplete state output file. The checker now ignores that
  interrupted export and reruns the exact failing prefix for a complete artifact.
- Parser review found that Python's duplicate-key hook could run before detecting
  trailing garbage, unlike the candidate. Both now validate full JSON syntax
  before rejecting duplicate keys; a dedicated cross-language regression covers it.
- SIGKILL after sync/before apply recovered the uncertain third request. Its retry
  was deduplicated and final state matched the uninterrupted history.
- Generated FIFO failure: 500 attempts reduced to three. Preserving a semantic
  signature makes the reduced witness explain the same bug rather than a parser
  error or unrelated crash.
- Installing the formatter separately let opam upgrade Dune to 3.24.2. The first
  benchmark's metadata was corrected to that observed version, then Dune was
  restored to 3.17.2. The benchmark collector now reads actual tool versions and
  records unknown build scope unless the Make target supplies it explicitly.

## Final release audit

Added deterministic scheduled admission/delivery disturbances and regression
coverage for changed admission order, response drops and exact duplicates.
Comparison now preserves partial artifacts for candidate exits, malformed
output and timeouts, carries test arguments in reproduction commands, and
bounds an evaluation with an overall deadline. Hardened malformed-field
shrinker simplification and validation-error reporting. Snapshot benchmark
warm-up now runs separately; summaries include accepted-order and trade rates.

Fresh Linux setup succeeded in Docker, but image export exhausted host disk
space. The resulting macOS test errors were storage errors, so those runs are
not acceptance evidence. Compressed older deep-run response streams losslessly
(`*.jsonl.gz`), preserving workloads/manifests and all response content.

Final outcome: fresh Linux setup, 32 tests, all nine hooks, the 100,000-attempt
corpus, demos, clean-source build and benchmarks passed. A further Linux check
covered artifact schemas, embedded divergent commands and timeout-predicate
rejection; all 32 tests and demos passed. Benchmarks and charts were checked
against schemas, sample counts and workload hashes. Version is 0.1.0. All
required milestones are closed with evidence; remote CI/publication was not run.
