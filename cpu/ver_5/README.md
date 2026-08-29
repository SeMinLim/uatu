# Uatu Ver. 5

Recursive learned-clause minimization built on Ver. 3.

## Architecture

- Retains the Ver. 3 BCP, First-UIP learning, VSIDS branching, and learned-clause management.
- Replaces one-step minimization with recursive reason-graph traversal.
- Removes a learned literal when its complete reason closure is already implied by root-level or learned literals.
