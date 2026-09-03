# Uatu Ver. 4

Corrected Ver. 3 with initial lightweight preprocessing and reduction-epoch vivification.

## Architecture

- Retains Ver. 3 BCP, First-UIP learning, VSIDS branching, soft rephasing, and usage-aware learned-clause management.
- Normalizes clauses and performs root-level unit propagation before CDCL search.
- Applies bounded backward subsumption, self-subsuming resolution, and bounded variable elimination with reverse model reconstruction.
- Runs bounded clause vivification whenever the learned-clause database is reduced.
- Detaches each vivification candidate from the watched-literal structure, negates its literals incrementally, and uses BCP to prove safe literal removal or a shorter RUP clause.
- Restores temporary assignments without modifying phase-saving state and installs vivification-derived unit clauses at decision level 0.
