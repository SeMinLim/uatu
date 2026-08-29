# Uatu Ver. 4

CHB-based CDCL solver built on Ver. 3.

## Architecture

- Retains the Ver. 3 BCP, First-UIP learning, one-step minimization, and learned-clause management.
- Replaces VSIDS decision selection with CHB conflict-history scoring.
- Clears assignment metadata during backtracking and validates implication-graph reason references.
- Uses current-level First-UIP traversal and a portable default release build.
