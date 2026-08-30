# Uatu Ver. 5

Tiered learned-clause management built directly on Ver. 3.

## Architecture

- Retains the Ver. 3 BCP, First-UIP learning, VSIDS branching, one-step minimization, and search-control pipeline.
- Keeps learned clauses with LBD at most 3 permanently in the CORE tier.
- Places learned clauses with LBD from 4 through 6 in TIER2 and protects them while they are used recently.
- Demotes TIER2 clauses that are unused for 30,000 conflicts to LOCAL.
- Deletes the lower-activity half of unlocked LOCAL clauses at each reduction.
- Promotes clauses when dynamic LBD improvement crosses a tier boundary.
- Does not enable CHB branching or recursive minimization.
