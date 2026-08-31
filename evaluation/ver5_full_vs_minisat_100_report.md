# Uatu Ver5 Full vs MiniSAT

- Dataset: 100 fixed-random SAT Competition 2025 Main Track instances
- Composition: 50 SAT and 50 UNSAT
- Timeout: 1,000 seconds per solver and benchmark
- PAR-2 penalty: 2,000 seconds for timeout, error, or wrong answer
- Execution: both solvers ran sequentially on the same runner; order alternated by index

| Solver | Solved | SAT | UNSAT | Wrong | Errors | PAR-2 (s) |
|---|---:|---:|---:|---:|---:|---:|
| MiniSAT | 46 | 25 | 21 | 0 | 0 | 1173.118200 |
| Uatu Ver5 | 44 | 24 | 20 | 0 | 1 | 1214.507600 |

MiniSAT exceeded: **NO**
PAR-2 speedup over MiniSAT: **0.965921x**
Ver5 PAR-2 relative to MiniSAT: **1.035282x**
