# Uatu

A compact CDCL SAT solver built with a small set of effective heuristics.

## Solver Features

- First-UIP conflict-driven clause learning
- Non-chronological backtracking
- Two-watched-literal Boolean Constraint Propagation with blockers
- VSIDS branching
- Phase saving
- Local-best-based rephasing with root backtracking in Ver. 4
- LBD-based learned-clause management
- LBD-triggered root-level restarts in Ver. 4

## Versions

| Version | Description |
|---|---|
| `cpu/ver_1` | Original compact CDCL solver and reference implementation |
| `cpu/ver_2` | Improved solver preserving the original search policy, with lower profiling overhead, one-step learned-clause minimization, and deterministic clause reduction |
| `cpu/ver_3` | Usage-aware learned-clause retention with activity and dynamic LBD updates |
| `cpu/ver_4` | Corrected Ver. 3 with root-level restarts and rephasing |
| `cpu/ver_5` | Ver. 4 with recursive/binary minimization, LBD management, restart blocking, adaptive VSIDS, bounded preprocessing, and selective vivification |

## Build and Run

```bash
cd cpu/ver_5   # or an earlier version
make
./obj/uatu_solver <instance.cnf>
```

Additional build targets:

```bash
make profile
make debug
make clean
```

## Benchmarks

| Directory | Purpose |
|---|---|
| `benchmark/sample` | Small smoke-test instances |
| `benchmark/satcomp2024` | Heuristic development and parameter tuning |
| `benchmark/satcomp2025` | Frozen final evaluation |

Sample benchmarks:

```bash
cd benchmark/sample
bash download.sh
```

SAT Competition benchmarks:

```bash
cd benchmark/satcomp2024   # or benchmark/satcomp2025
bash download.sh all
```

Use `bash download.sh download` and `bash download.sh extract` to perform the two steps separately. Benchmark archives are downloaded and decompressed before running the solver; Uatu reads plain DIMACS `.cnf` files.

SAT Competition 2024 is used for heuristic development and parameter tuning. SAT Competition 2025 is reserved as a frozen final-evaluation set to avoid benchmark overfitting.

## Ver. 5 Validation (Stages 1–4)

50 random SAT Competition 2025 instances, 1000-second limit: **10 SAT, 8 UNSAT, 32 timeout, 0 memory limit**. Detected wrong answers and execution errors: **0**.

[Features, validation details, and regression results](cpu/ver_5/README.md)

<!-- BEGIN SAT2025 VER5 MINISAT 100 -->
## Earlier Ver. 5 Comparison (Stages 1–3)

The earlier three-stage Ver. 5 ([`68844e5`](https://github.com/SeMinLim/uatu/commit/68844e51f0d1f3b1ba5d812e78f18e7e0053ad73)) **did not outperform MiniSAT** on these 100 instances. The mean PAR-2 ratio (MiniSAT / Uatu) was **0.9523×**.

| Solver | Solved / 100 | Mean PAR-2 (s) |
|---|---:|---:|
| Uatu Ver. 5 | 27 | 1507.454 |
| MiniSAT 2.2.0 | 31 | 1435.545 |

100 of 400 Main Track instances were sampled uniformly without replacement (seed `20260908`). Limits: **1000 seconds wall clock**, **12 GiB**, one thread. Each pair ran sequentially on the same runner and pinned CPU core, with alternating solver order. MiniSAT used `2.2.0 simp` with default preprocessing.

Mean PAR-2 averages validated solve wall times and a 2000-second penalty per timeout or memory limit. **Lower is better.**

[Per-instance results and scores](cpu/ver_5/benchmark_results/sat2025_stage3_vs_minisat_100.json) · [Measurement details at the evaluated revision](https://github.com/SeMinLim/uatu/blob/b66cd539c3101f1ef87ec13d88fffbc121aa5116/cpu/ver_5/README.md#minisat-comparison-sat-competition-2025)
These measurements apply to the earlier source above. Current Ver. 5 validation is recorded in [its README](cpu/ver_5/README.md).
<!-- END SAT2025 VER5 MINISAT 100 -->

---

## Mandatory Papers

- **[CDCL]** J. Marques-Silva, L. Inês, and M. Sharad, "Conflict-driven clause learning SAT solvers," Handbook of satisfiability, IOS press, 2021, 133-182.
- **[Chaff]** MW. Moskewicz et al, "Chaff: Engineering an efficient SAT solver," Proceedings of the 38th annual Design Automation Conference, 2001.
- **[MiniSAT]** N. Eén and S. Niklas, "An extensible SAT-solver," Lecture notes in computer science 2919.2004 (2004): 502-518.
- **[Phase Saving Technique]** K. Pipatsrisawat and D. Adnan, "A lightweight component caching scheme for satisfiability solvers," Theory and Applications of Satisfiability Testing–SAT 2007: 10th International Conference, Lisbon, Portugal, May 28-31, 2007.
- **[Glucose]** G. Audemard and S. Laurent, "Predicting learnt clauses quality in modern SAT solvers," Twenty-first international joint conference on artificial intelligence, 2009.
- **[Glucose]** G. Audemard and S. Laurent, "GLUCOSE: a solver that predicts learnt clauses quality," SAT Competition, 2009.
- **[CaDiCaL]** A. Biere, "Cadical, lingeling, plingeling, treengeling and yalsat entering the sat competition 2017," Proceedings of SAT Competition 14 (2017): 316-336.
- **[LRB]** J. H. Liang, V. Ganesh, P. Poupart, and K. Czarnecki, "Learning rate based branching heuristic for SAT solvers," Theory and Applications of Satisfiability Testing – SAT 2016, 2016.
- **[Clause Minimization]** N. Sörensson and A. Biere, "Minimizing learned clauses," Theory and Applications of Satisfiability Testing–SAT 2009, 2009.
