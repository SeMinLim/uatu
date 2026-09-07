# Uatu Ver. 5

Based on `cpu/ver_4` at commit `ef7ee281b770758a318329501d85061fc563b496`, with two planned heuristic extensions: recursive and binary-resolution learnt-clause minimization, followed by Glucose-style LBD-centered learned-clause management. `cpu/ver_4` is unchanged.

- Recursive minimization replaces the one-step reason check. It follows reason chains using reusable explicit-stack storage, caches successful traversals within one analysis, and rolls back temporary marks after a failed traversal. The asserting literal is retained.
- Binary-resolution minimization then processes clauses with at most 30 literals and LBD at most 6. It resolves against existing binary clauses containing the asserting literal, using read-only access to the existing watcher lists. Both original and learned binary clauses are eligible.
- Final LBD and the backtrack level are calculated after both passes. The existing `Minimized Literals` counter includes literals removed by either pass.

The second extension adapts the learned-clause retention policy from [Glucose 3.0](https://github.com/audemard/glucose/blob/3.0/core/Solver.cc):

- Reduction ranks nonbinary learned clauses by decreasing LBD, using increasing clause activity only to break equal-LBD ties. Binary clauses sort last. The initial deletion window is half of **all learned clauses**, rather than half of a filtered candidate set.
- Original clauses, binary clauses, glue clauses with LBD at most 2, and clauses serving as current assignment reasons are protected. Learned clauses with LBD 3 or 4 can now be deleted when they fall inside the deletion window.
- During conflict analysis, an LBD decrease of at least two updates a learned clause's LBD. If its **previous** LBD was at most 30, the improvement also protects it for the next reduction. That protection extends the deletion window by one and is then cleared for surviving clauses.
- Uatu retains its existing reduction schedule: initially 8192 conflicts between reductions, increasing by 512 after each reduction. Root backtracking, database compaction, watcher updates, and reason-index remapping are retained. This is an adaptation of the Glucose retention policy, not its reduction scheduler.

BCP, variable VSIDS, clause activity bumping and decay, restart and rephase policies, parsing, CLI output, and build targets retain their preceding behavior. Neither extension adds BCP calls. Restart blocking, adaptive VSIDS, preprocessing, and vivification remain later steps.

```bash
make
make run CNF=/path/to/instance.cnf TIMEOUT=1000
```

## SAT Competition 2025: stage-2 comparison

These measurements used the **stage-2 source, including Glucose-style LBD-centered learned-clause management**, at commit `8eb756b7284053522bd2314f17a2a1cf8c567fe1`.

1. **Did Uatu ver_5 outperform MiniSAT? No.** On this 100-instance sample with a 1000-second timeout, Uatu's PAR-2 score was **14.15% higher (worse)** than MiniSAT's.
2. **PAR-2 improvement factor: none.** The ratio `PAR-2(MiniSAT) / PAR-2(Uatu)` was **0.876077**, below the 1.0 threshold for an improvement.

| Solver | Solved / 100 | Timeouts | Other unsolved | PAR-2 total (s) | Mean PAR-2 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Uatu ver_5 | 29 | 69 | 2 | 149094.052614 | 1490.940526 |
| MiniSAT | 40 | 58 | 2 | 130617.878262 | 1306.178783 |

[PAR-2](https://satcompetition.github.io/2025/tracks.html) assigns the measured runtime to each solved instance and **2000 seconds** to every unsolved instance. Mean PAR-2 is `(sum of solved runtimes + 2000 * unsolved count) / 100`; lower is better. Uatu's two other unsolved runs reached the memory limit; MiniSAT's two returned no solution (`unknown`), so these are not counted as timeouts.

### Measurement conditions

- **Sample:** 100 instances selected uniformly without replacement from the 400-instance [official 2025 Main Track manifest](https://benchmark-database.de/getinstances?context=cnf&query=track%3Dmain_2025), using Python `random.Random(20260906).sample(population_sorted_by_GBD_hash, 100)`. No filtering by size, difficulty, or result. This preserves the previously drawn random sample; **both solvers were measured again** for this comparison.
- **Uatu source:** [`8eb756b7284053522bd2314f17a2a1cf8c567fe1`](https://github.com/SeMinLim/uatu/commit/8eb756b7284053522bd2314f17a2a1cf8c567fe1). Built with `make -C cpu/ver_5 release`, GCC 11.4.0, `-O3 -DNDEBUG`, and BCP profiling disabled. Source and binary SHA-256 identities were checked.
- **Baseline:** Ubuntu MiniSAT package `1:2.2.1-5build2`, default preprocessing, `-verb=0`.
- **Execution:** 1000-second external wall-clock timeout and 12 GiB address-space limit per solver. Each pair ran sequentially on the same pinned logical CPU, with alternating solver order. Different pairs used heterogeneous GitHub-hosted Ubuntu 22.04 runners. Timing includes parsing and model output; downloads, decompression, and model checking are excluded.
- **Answer checks:** SAT models were checked against the original CNF. UNSAT answers were checked against known answers or agreement between solvers, without proof checking. All 100 unique pairs were present, with no detected runtime or answer errors in either solver.

Completed on **2026-09-07 (UTC)**. The [per-instance results and provenance](benchmark_results/sat2025_stage2_100.json) preserve all 200 solver measurements, the sample, build identity, source hashes, runner information, and final summary. The [evaluation run](https://github.com/SeMinLim/uatu/actions/runs/34083297444) also contains execution logs and the `lbd-paired-final` artifact.
