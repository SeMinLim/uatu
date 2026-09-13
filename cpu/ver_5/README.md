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

## MiniSAT Comparison (SAT Competition 2025)

The current four-stage Ver. 5 **did not outperform MiniSAT** on this 100-instance sample. The mean PAR-2 ratio (MiniSAT / Uatu) was **0.9644×**.

| Solver | Solved / 100 | Mean PAR-2 (s) |
|---|---:|---:|
| Uatu Ver. 5 | 38 | 1311.523 |
| MiniSAT 2.2.0 | 40 | 1264.827 |

Uatu had 61 timeouts and 1 memory limit; MiniSAT had 59 timeouts and 1 memory limit.

100 of 400 Main Track instances were sampled uniformly without replacement, seed `20260913`. Uatu source: [`a4dc75b`](https://github.com/SeMinLim/uatu/commit/a4dc75bc104c84762193446fc2ae15c58fb97908), stages 1–4. MiniSAT: `2.2.0 simp`, commit `eb01ad68b75bb3b34ff8657c37ad6a31faae0fc3`, default preprocessing.

Limits were **1000 seconds wall clock** and **12 GiB virtual address space** per solver, one thread. Each pair ran sequentially on the same GitHub-hosted Ubuntu 22.04 runner and pinned CPU core, with alternating solver order. Both used release builds (`-O3 -DNDEBUG`). CPU models, compiler versions, commands, and source hashes are recorded per instance.

Timing includes process launch, parsing, preprocessing, search, and model output. Download, decompression, cache warming, and model checking are excluded. Mean PAR-2 is the sum of validated solve wall times and a **2000-second penalty** per timeout or memory limit, divided by 100. **Lower is better.** A MiniSAT/Uatu ratio above 1 favors Uatu.

SAT models were checked against every original clause; UNSAT answers were compared with known answers or the other solver, without formal proof checking. All 100 pairs completed with no detected wrong answers, invalid models, or execution errors.

[Per-instance results and scores](benchmark_results/sat2025_stage4_vs_minisat_100.json) · [Measurement run](https://github.com/SeMinLim/uatu/actions/runs/34732981706)

## Earlier Results

The [100-instance MiniSAT comparison](benchmark_results/sat2025_stage3_vs_minisat_100.json) measured the earlier three-stage implementation, source [`68844e5`](https://github.com/SeMinLim/uatu/commit/68844e51f0d1f3b1ba5d812e78f18e7e0053ad73). It does not measure this replacement.
