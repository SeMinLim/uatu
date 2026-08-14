# Uatu Ver. 3

Usage-aware learned-clause management built on Ver. 2.

## Architecture

- Retains the Ver. 2 BCP, First-UIP learning, VSIDS branching, and search-control pipeline.
- Tracks learned-clause activity and conflict-analysis usage.
- Recomputes LBD when a learned clause is reused and keeps only improved values.
- Reduces unlocked clauses using activity, LBD, and clause length.
