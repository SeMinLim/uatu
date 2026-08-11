# Uatu Ver4 Evaluation

- Dataset: fixed 50-instance SAT Competition 2025 subset
- Composition: 25 SAT and 25 UNSAT
- Timeout: 1,000 seconds per solver and instance
- Ver4 configuration: VSIDS, negative default phase, recursive-minimization budget 64, dynamic LBD, learned-clause activity, tiered search-preserving reduction

| Solver | Solved | SAT | UNSAT | Wrong | PAR-2 (s) | Solved time (s) | Peak RSS (KB) |
|---|---:|---:|---:|---:|---:|---:|---:|
| `minisat` | 20 | 14 | 6 | 0 | 1268.552 | 3427.580 | 8262280 |
| `ver3` | 12 | 7 | 5 | 0 | 1572.219 | 2610.930 | 10005740 |
| `ver4` | 13 | 7 | 6 | 0 | 1533.930 | 2696.500 | 11053852 |

MiniSAT exceeded: **NO**
