# Uatu Ver. 5

CPU SAT solver rebuilt from `cpu/ver_4` with three heuristic extensions.

## Heuristics

1. **Clause minimization:** recursive reason-graph minimization, followed by binary resolution on learnt clauses with at most 30 literals and LBD at most 6.
2. **LBD-centered clause management:** protect binary/glue clauses, current reasons, recently improved clauses, and the most active 10%. Reduction preserves the current trail.
3. **Restart blocking and adaptive VSIDS:** block LBD restarts when the conflict trail exceeds 1.4 times its 5000-conflict average, after 10000 conflicts. Increase VSIDS decay from 0.80 to 0.95 by 0.01 every 5000 conflicts.

## Build and Run

```bash
make
make run CNF=/path/to/instance.cnf TIMEOUT=1000
```

## Validation

50 instances sampled uniformly without replacement from the 400-instance [SAT Competition 2025 Main Track](https://satcompetition.github.io/2025/downloads.html), using seed `20260907`. Each run used a 1000-second wall-clock timeout and a 12 GiB address-space limit.

| Result | Instances |
|---|---:|
| SAT, model validated | 10 |
| UNSAT, answer matched | 9 |
| Timeout | 31 |
| Memory limit | 0 |
| Wrong answer / execution error | 0 |

SAT models were checked against every original clause. UNSAT answers were matched to known benchmark answers or MiniSAT, without proof checking. Timeouts and memory limits remain unsolved.

Release and ASan/UBSan checks passed on 506 formulas. Focused heuristic tests, malformed-input checks, allocation-failure tests, and leak checking also passed.

[Instance results](benchmark_results/sat2025_stage3_50.json) · [Regression results](benchmark_results/regression.json)
