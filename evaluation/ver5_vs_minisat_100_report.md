# Uatu Ver5 vs MiniSAT Evaluation

- Dataset: 100 SAT Competition 2025 Main Track instances
- Composition: 50 SAT and 50 UNSAT
- Selection: 50 historical Ver4-evaluation instances plus 50 fixed-seed new instances
- New-instance selection seed: 20250830
- Timeout: 1,000 seconds per solver and instance
- Scoring: solved count first, then PAR-2 with a 2,000-second unsolved penalty
- Index 69 recovery: each solver ran on a separate runner with 2 GiB reserved from total memory
- Historical MiniSAT source: Ver4 evaluation commit `1b367b9c8ddbc3fb432d54fb618f5663cf5ac711`

| Solver | Solved | SAT | UNSAT | Wrong | PAR-2 (s) | Solved time (s) | Peak RSS (KB) |
|---|---:|---:|---:|---:|---:|---:|---:|
| `minisat` | 45 | 25 | 20 | 0 | 1180.609 | 8060.930 | 11883340 |
| `ver5` | 45 | 25 | 20 | 0 | 1210.187 | 11018.680 | 10005196 |

MiniSAT exceeded: **NO**
PAR-2 speedup over MiniSAT: **0.975560x**
Ver5-only solves: **11**
MiniSAT-only solves: **11**
Both solved: **34**
Both-solved geometric-mean speedup: **0.766971x**

## Split by measurement source

| Solver | Source | Instances | Solved | SAT | UNSAT | Wrong | PAR-2 (s) |
|---|---|---:|---:|---:|---:|---:|---:|
| `minisat` | historical | 50 | 20 | 14 | 6 | 0 | 1268.552 |
| `ver5` | historical | 50 | 21 | 12 | 9 | 0 | 1284.201 |
| `minisat` | new | 50 | 25 | 11 | 14 | 0 | 1092.667 |
| `ver5` | new | 50 | 24 | 13 | 11 | 0 | 1136.173 |
