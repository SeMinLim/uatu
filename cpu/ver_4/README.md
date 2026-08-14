# Uatu Ver. 4

CHB-based branching architecture built on Ver. 3.

## Architecture

- Retains the Ver. 3 BCP, clause learning, minimization, and learned-clause management.
- Replaces VSIDS branching updates with Conflict History-Based (CHB) scores.
- Updates variable scores from recent conflict participation and propagation outcomes.
- Uses a bidirectional max heap because CHB scores can increase or decrease.
