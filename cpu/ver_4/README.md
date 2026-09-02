# Uatu Ver. 4

Corrected Ver. 3 with initial lightweight preprocessing.

## Architecture

- Retains Ver. 3 BCP, First-UIP learning, VSIDS branching, soft rephasing, and usage-aware learned-clause management.
- Normalizes clauses and performs root-level unit propagation before CDCL search.
- Applies bounded backward subsumption and self-subsuming resolution.
- Applies bounded variable elimination with reverse model reconstruction.
