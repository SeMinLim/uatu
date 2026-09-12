# Uatu Ver. 5

CPU SAT solver rebuilt from `cpu/ver_4` with all four heuristic extensions.

## Heuristics

1. **Clause minimization:** recursive reason-graph minimization and binary resolution.
2. **LBD-centered management:** protect binary/glue clauses, current reasons, recently improved clauses, and the most active 10%.
3. **Search control:** restart blocking and adaptive VSIDS decay from 0.80 to 0.95.
4. **Preprocessing and vivification:** bounded variable elimination (BVE), backward subsumption, self-subsuming resolution, and selective learnt-clause vivification. SAT models restore eliminated variables in reverse order.

Preprocessing allows no clause/literal growth per accepted BVE. Optional simplification has a 40M-work budget and a 128 MiB occurrence-index cap; root normalization and model-reconstruction storage are separate.

Vivification runs at the next root opportunity after each 8192-conflict interval. Each pass selects at most 64 learnt clauses with length at most 30 and LBD at most 6, with a 200,000-work probe budget. It uses the existing BCP path and restores temporary assignments after each probe.

## Build and Run

```bash
make
make run CNF=/path/to/instance.cnf TIMEOUT=1000
```

`TIMEOUT` sets a periodically checked user-CPU time budget after parsing. Validation below uses an external wall-clock limit.

`make profile` measures BCP time. Set `UATU_PRINT_MODEL=1` to print the reconstructed model.

## Validation

50 instances sampled uniformly without replacement from the 400-instance [SAT Competition 2025 Main Track](https://satcompetition.github.io/2025/downloads.html), seed `20260912`. Limits: **1000 seconds wall clock** and **12 GiB virtual address space** per solver.

| Result | Instances |
|---|---:|
| SAT, original model validated | 10 |
| UNSAT, answer matched | 8 |
| Timeout | 32 |
| Memory limit | 0 |
| Wrong answer / execution error | 0 |

SAT models were checked against every original clause. UNSAT answers matched known benchmark answers or pinned MiniSAT 2.2.0, without formal proof checking. Timeouts and memory limits remain unsolved.

[Instance results and source hashes](benchmark_results/sat2025_stage4_validation_50.json) · [Validation run](https://github.com/SeMinLim/uatu/actions/runs/34692894604)

Release and ASan/UBSan checks passed on 899 stage-4 formulas and the existing 506-formula suite. Tests cover exhaustive small formulas, original-model reconstruction, malformed input, allocation failure, clause reduction, and interrupted vivification. LeakSanitizer was unavailable in the local test environment.

[Stage-4 regressions](benchmark_results/stage4_regression.json) · [Core regressions](benchmark_results/stage4_core_regression.json)

## Earlier Results

The [100-instance MiniSAT comparison](benchmark_results/sat2025_stage3_vs_minisat_100.json) measured the earlier three-stage implementation, source [`68844e5`](https://github.com/SeMinLim/uatu/commit/68844e51f0d1f3b1ba5d812e78f18e7e0053ad73). It does not measure this replacement.
