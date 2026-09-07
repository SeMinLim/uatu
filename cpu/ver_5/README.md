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

<!-- BEGIN SAT2025 VER5 MINISAT 100 -->
## MiniSAT Comparison (SAT Competition 2025)

On these 100 sampled instances, **Uatu Ver. 5 did not outperform MiniSAT**. The mean PAR-2 ratio (MiniSAT / Uatu) was **0.9523×**.

| Solver | Solved / 100 | Timeout | Memory limit | Mean PAR-2 (s) |
|---|---:|---:|---:|---:|
| Uatu Ver. 5 | 27 | 72 | 1 | 1507.454 |
| MiniSAT 2.2.0 | 31 | 68 | 1 | 1435.545 |

100 instances were sampled uniformly without replacement from the 400-instance [SAT Competition 2025 Main Track](https://satcompetition.github.io/2025/downloads.html), seed `20260908`. Each solver used a **1000-second wall-clock limit**, a **12 GiB address-space limit**, and one thread. Each pair ran sequentially on the same runner and pinned CPU core, with alternating solver order.

Measured Uatu source: [`68844e5`](https://github.com/SeMinLim/uatu/commit/68844e51f0d1f3b1ba5d812e78f18e7e0053ad73). MiniSAT: `2.2.0 simp` with default preprocessing ([source](https://github.com/niklasso/minisat/commit/eb01ad68b75bb3b34ff8657c37ad6a31faae0fc3)).

Measurements used GitHub Actions runners with six AMD EPYC or Intel Xeon CPU models and GCC 11.4.0. The results record each instance’s CPU; both release builds used `-O3` and `NDEBUG`.

Mean PAR-2 is the sum of validated solve wall times and 2000 seconds for each timeout or memory limit, divided by 100. **Lower is better.** The ratio compares aggregate PAR-2 on this sample.

Timing includes process launch, parsing, solving, and model output; it excludes download, decompression, cache warming, and model checking.

SAT models were checked against the original clauses. UNSAT answers matched known answers or the other solver, without formal proof checking. Detected wrong answers and unexpected solver failures: **0**.

MiniSAT’s allocation failure on one instance was identified from its exact source-defined log signature. The results preserve the original record and classification correction; measured times were unchanged.

[Per-instance results and scores](benchmark_results/sat2025_stage3_vs_minisat_100.json)
<!-- END SAT2025 VER5 MINISAT 100 -->
