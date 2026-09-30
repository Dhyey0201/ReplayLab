# 001: Ownership, language split, and reproducible foundation

Context: The behavioral contract requires independently implemented matching and explicit evidence.
Decision: OCaml 5.2.1, Dune 3.17.2, Yojson 2.2.2, Digestif 1.3.0; opam 2.3.0 lives locally. Python uses the standard library and unittest initially, avoiding a mandatory package download for the oracle. Add property generation with deterministic seeds.
Alternatives: A shared matching implementation would weaken the oracle. Global package installation would alter the user's environment.
Consequences: Python scans and sorts lifecycle records; OCaml uses ordered price maps and linked queues. A single owner completes each command, simplifying sequence and crash boundaries. No multicore claim.
Verification: Native foundation test exercises JSON, SHA-256's standard abc vector and real fsync. Golden expectations are hand calculated from specification section 6.
