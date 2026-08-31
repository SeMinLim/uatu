# Uatu Ver. 5

CHB branching, recursive learned-clause minimization, and tiered clause management built directly on Ver. 3.

## Architecture

- Retains the Ver. 3 BCP, First-UIP learning, usage-aware clause activity, dynamic LBD updates, and search-control pipeline.
- Replaces VSIDS decision selection with CHB while retaining phase saving.
- Replaces one-step minimization with iterative recursive traversal of the implication-graph reason closure.
- Removes a learned literal only when every non-root antecedent is already represented by the learned clause or is recursively redundant.
- Keeps learned clauses with LBD at most 3 permanently in the CORE tier.
- Protects recently used clauses with LBD from 4 through 6 in TIER2 and demotes stale clauses to LOCAL.
- Deletes the lower-activity half of unlocked LOCAL clauses at each reduction.
