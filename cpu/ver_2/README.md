# Uatu Ver. 2

Optimized implementation that preserves the Ver. 1 search policy.

## Architecture

- The same two-watched-literal BCP and First-UIP CDCL pipeline as Ver. 1.
- Reduced parser, timeout-checking, and profiling overhead outside the BCP hot path.
- Non-recursive one-step learned-clause minimization.
- Deterministic, locked-clause-aware reduction using LBD and clause length.
