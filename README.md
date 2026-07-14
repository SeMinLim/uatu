# Uatu

A compact CDCL SAT solver built with a small set of effective heuristics.

## Solver Features

- First-UIP conflict-driven clause learning
- Non-chronological backtracking
- Two-watched-literal Boolean Constraint Propagation with blockers
- VSIDS-style branching with a max heap
- Phase saving
- Local-best-based soft rephasing
- LBD-based learned-clause management
- Recent-LBD window reset with deep-search preservation

## Versions

| Version | Description |
|---|---|
| `cpu/ver_1` | Original compact CDCL solver and reference implementation |
| `cpu/ver_2` | Improved solver preserving the original search policy, with lower profiling overhead, one-step learned-clause minimization, and deterministic clause reduction |

## Build and Run

```bash
cd cpu/ver_1   # or cpu/ver_2
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

---

## Mandatory Papers

- **[CDCL]** J. Marques-Silva, L. Inês, and M. Sharad, "Conflict-driven clause learning SAT solvers," Handbook of satisfiability, IOS press, 2021, 133-182.
- **[Chaff]** MW. Moskewicz et al, "Chaff: Engineering an efficient SAT solver," Proceedings of the 38th annual Design Automation Conference, 2001.
- **[MiniSAT]** N. Eén and S. Niklas, "An extensible SAT-solver," Lecture notes in computer science 2919.2004 (2004): 502-518.
- **[Phase Saving Technique]** K. Pipatsrisawat and D. Adnan, "A lightweight component caching scheme for satisfiability solvers," Theory and Applications of Satisfiability Testing–SAT 2007: 10th International Conference, Lisbon, Portugal, May 28-31, 2007.
- **[Glucose]** G. Audemard and S. Laurent, "Predicting learnt clauses quality in modern SAT solvers," Twenty-first international joint conference on artificial intelligence, 2009.
- **[Glucose]** G. Audemard and S. Laurent, "GLUCOSE: a solver that predicts learnt clauses quality," SAT Competition, 2009.
- **[CaDiCaL]** A. Biere, "Cadical, lingeling, plingeling, treengeling and yalsat entering the sat competition 2017," Proceedings of SAT Competition 14 (2017): 316-336.
- **[Clause Minimization]** N. Sörensson and A. Biere, "Minimizing learned clauses," Theory and Applications of Satisfiability Testing–SAT 2009, 2009.
