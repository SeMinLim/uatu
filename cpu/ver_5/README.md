# Uatu Ver. 5

CHB-based CDCL solver with recursive learned-clause minimization.

## Architecture

- Retains the corrected Ver. 4 BCP, First-UIP learning, CHB branching, and learned-clause management.
- Replaces one-step minimization with recursive traversal of the implication-graph reason closure.
- Removes a learned literal only when every non-root antecedent is already represented by the learned clause or is recursively redundant.
