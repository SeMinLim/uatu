# Uatu Ver. 1

Original compact CDCL reference implementation.

## Architecture

- DIMACS CNF loader and vector-based clause database.
- Two-watched-literal BCP with blocker checks.
- First-UIP learning, non-chronological backtracking, and VSIDS-style branching.
- Phase saving, local-best soft rephasing, recent-LBD window reset, and randomized LBD-based clause reduction.
