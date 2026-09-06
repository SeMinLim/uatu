# Uatu Ver. 5

Based on `cpu/ver_4` at commit `ef7ee281b770758a318329501d85061fc563b496`, with only the first planned heuristic extension: recursive learnt-clause minimization followed by binary-resolution minimization. `cpu/ver_4` is unchanged.

- Recursive minimization replaces the one-step reason check. It follows reason chains using reusable explicit-stack storage, caches successful traversals within one analysis, and rolls back temporary marks after a failed traversal. The asserting literal is retained.
- Binary-resolution minimization then processes clauses with at most 30 literals and LBD at most 6. It resolves against existing binary clauses containing the asserting literal, using read-only access to the existing watcher lists. Both original and learned binary clauses are eligible.
- Final LBD and the backtrack level are calculated after both passes. The existing `Minimized Literals` counter includes literals removed by either pass.

BCP, VSIDS, clause activity and deletion, dynamic LBD updates, restart and rephase policies, parsing, CLI output, build targets, and inherited regression scripts are otherwise unchanged. Neither minimization pass performs additional BCP calls. No preprocessing or vivification is added.

```bash
make
make run CNF=/path/to/instance.cnf TIMEOUT=1000
```

## SAT Competition 2025: 100-instance comparison

1. **Did Uatu ver_5 outperform MiniSAT? No.** On this sample with a 1000-second timeout, Uatu's PAR-2 score was **11.98% higher (worse)** than MiniSAT's.
2. **PAR-2 improvement factor: none.** The ratio `PAR-2(MiniSAT) / PAR-2(Uatu)` was **0.893006**, below the 1.0 threshold for an improvement.

| Solver | Solved / 100 | Timeouts | Other unsolved | PAR-2 total (s) | Mean PAR-2 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Uatu ver_5 | 31 | 67 | 2 | 148171.598362 | 1481.715984 |
| MiniSAT | 38 | 60 | 2 | 132318.134196 | 1323.181342 |

PAR-2 assigns the measured runtime to each solved instance and **2000 seconds** to every unsolved instance, including memory limits and unknown results. Mean PAR-2 is the total divided by 100; lower is better. Uatu's two other unsolved runs reached the memory limit; MiniSAT's two returned no solution.

### Measurement conditions

- **Sample:** 100 instances selected uniformly without replacement from the 400-instance [official 2025 Main Track manifest](https://benchmark-database.de/getinstances?context=cnf&query=track%3Dmain_2025), using Python `random.Random(20260906).sample(population_sorted_by_GBD_hash, 100)`. No filtering by size, difficulty, or result.
- **Uatu source:** [`c22c2c350f63468b1608eb7283806ebef2393831`](https://github.com/SeMinLim/uatu/commit/c22c2c350f63468b1608eb7283806ebef2393831), with source and Makefile identical to `main` at `319ee6d95d6abc4df2880df2f7a17a47aeb55b82`. Built with `make -C cpu/ver_5 release`, GCC 11.4.0, `-O3 -DNDEBUG`, and BCP profiling disabled.
- **Baseline:** Ubuntu MiniSAT package `1:2.2.1-5build2`, default preprocessing, `-verb=0`.
- **Execution:** 1000-second external wall-clock timeout and 12 GiB address-space limit per solver. Each pair ran sequentially on the same pinned logical CPU, with alternating solver order. Different pairs used heterogeneous GitHub-hosted Ubuntu 22.04 runners. Timing includes parsing and model output; downloads, decompression, and model checking are excluded.
- **Answer checks:** SAT models were checked against the CNF. UNSAT answers were checked against known answers or agreement between solvers, without proof checking. All 100 pairs were present, with no detected answer errors.

Completed on **2026-09-06 (UTC)**. The [evaluation run](https://github.com/SeMinLim/uatu/actions/runs/34039208713) contains the sample manifest, build identity, per-instance measurements, and final summary (`c22-paired-final` artifact).
