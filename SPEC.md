# atms: my first thing to build (not review)

acceptance criterion from Lynn (2026-11-01):
> "bring me something that believes two incompatible things for documented reasons"

i.e. an assumption-based truth maintenance system (de Kleer 1986): every derived
datum carries a label, the minimal sets of assumptions (environments) under
which it holds. contradictory data can coexist in different environments; a
nogood (an environment that derives ⊥) removes every environment containing it.
"documented reasons" = every belief can explain itself: which justifications,
and which assumptions.

open design questions to settle before coding (read de kleer first; don't
reinvent from memory):
- language and packaging (nix flake, tests in checks, not in the runtime build)
- label minimality and consistency: keep both invariants, and property-test them
- an explain() that returns the justification tree for a datum in an environment
- the boundary Lynn drew: this is justification tracking, not staleness detection.
  say so in the README.
- reviewer: Lynn. author: me.
