# Uatu Ver. 4

Corrected Ver. 3 with preprocessing, reduction-epoch vivification, and LRB/EVSIDS branching.

## Architecture

- Maintains LRB and canonical EVSIDS scores concurrently and alternates the active heuristic by search-propagation budget without changing the current trail.
- Uses LRB conflict-participation and reason-side rewards with exponential recency updates and locality decay.
- Uses canonical EVSIDS with one bump per conflict participant and a decay factor of 0.95.
- Normalizes clauses and performs bounded unit propagation, subsumption, self-subsuming resolution, and variable elimination before CDCL search.
- Runs bounded clause vivification whenever the learned-clause database is reduced.
- Preserves Uatu's soft rephase and recent-LBD reset behavior; only clause reduction performs `backtrack(0)`.
