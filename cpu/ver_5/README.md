# Uatu Ver. 5

Rebuilt from `cpu/ver_4` using the default policies of [Glucose 4.2.1 sequential `simp`](https://github.com/audemard/glucose/tree/084d7375975408a06a1397cc4bc645a73b97fa65).

- Recursive and binary-resolution learnt-clause minimization.
- Glucose variable/clause activity updates, adaptive VSIDS decay, dynamic LBD, and LBD/activity clause retention.
- LBD restarts, trail-based restart blocking, negative initial phase, full phase saving, and Force-UNSAT phases.
- Strategy adaptation at 100,000 conflicts, including reachable Luby, Chanseok Oh, and restart phase-randomization policies.
- Bounded variable elimination, backward subsumption, self-subsuming resolution, root simplification, and reverse model reconstruction.
- LCM learnt-clause vivification with Glucose target/revisit rules and search-entry scheduling after reduction.

Ver. 4's local-best rephasing and forced root backtrack inside clause reduction are removed. Heuristic control remains on the CPU; the existing two-watched-literal BCP structure is retained.

Default-disabled options such as random variable selection, random initial activity, asymmetric branching, and redundancy checking are omitted. LCM LBD rewriting and Chanseok permanent-clause vivification remain disabled. Restart randomization uses an actual 32-bit mask; upstream's cast of a `[0, 1)` random number accidentally produced zero.

```bash
make
make run CNF=/path/to/instance.cnf TIMEOUT=1000
UATU_PRINT_MODEL=1 ./obj/uatu_solver /path/to/instance.cnf
```

`make profile` enables BCP timing; `make debug` builds without optimization.

**Validation:** 309 CNFs, 1,236 executions with preprocessing enabled/skipped and release/ASan+UBSan builds. All verdicts matched Glucose; all returned SAT models satisfied the original CNF. 264 cases were also checked by exhaustive enumeration. Core, preprocessing, and LCM policy tests passed, as did release/profile/debug CLI checks. [Results and source hashes](tests/validation.json).

**Style-only update:** `solver.h` and `solver.cpp` now follow the project C-first style: tab indentation, K&R braces, explicit index loops, plain structs for public data, and a free BCP timing helper instead of a lambda. Heuristic logic, constants, state-update order, output, and exit codes are unchanged.

**Style-equivalence validation:** A deterministic regression subset of 10 solved SAT and 10 solved UNSAT instances across 12 families was drawn from the earlier uniformly sampled 100-instance set; it is not a performance sample. Under a 1,000-second wall-clock limit, 12 GiB, and one thread per run, baseline [`dbded78`](https://github.com/SeMinLim/uatu/commit/dbded78dc2a6e7588ecdb2bc635f0e39104168ca) and the restyled solver matched verdicts and all 17 integer counters on **20/20** instances. All 20 emitted SAT models (two solvers × 10 SAT instances) satisfied the original CNFs, and **10/10** UNSAT verdicts matched published GBD statuses. Timeout, invalid model, or execution errors: **0**. [Evidence](tests/sat2025_style_equivalence_20.json).

LeakSanitizer was unavailable under the test runtime's ptrace; leak detection was disabled. To rerun against a compiled Glucose 4.2.1 sequential binary:

```bash
python3 tests/regression.py --reference /path/to/glucose --build-dir /tmp/uatu-ver5-check
```

**SAT Competition 2025 validation:** 50/400 Main Track instances, sampled uniformly without replacement (seed `12803139359653862237`), source [`362ceb9`](https://github.com/SeMinLim/uatu/commit/362ceb9ed729c220c7233bd595528248aaddf90a). **1,000 seconds wall clock, 12 GiB, one thread:** **10 SAT, 8 UNSAT, 32 timeout; detected wrong answers or execution errors: 0**. SAT models passed original-CNF checks; 7 UNSAT answers matched GBD and 1 matched Glucose 4.2.1, without proof-certificate checking. Timeouts remain unresolved. [Evidence](tests/sat2025_validation_50.json) · [Run](https://github.com/SeMinLim/uatu/actions/runs/34751942376).

**MiniSAT comparison (SAT Competition 2025):** Ver. 5 **outperformed MiniSAT** on this sample. Mean PAR-2 ratio (MiniSAT / Ver. 5): **1.0560×**.

| Solver | Solved / 100 | Mean PAR-2 (s) |
|---|---:|---:|
| Uatu Ver. 5 | 32 | 1435.112 |
| MiniSAT 2.2.0 simp | 27 | 1515.483 |

100/400 Main Track instances, sampled uniformly without replacement (seed `2974165144`). **1,000 seconds wall clock, 12 GiB, one thread**, release builds with default preprocessing. Each pair ran sequentially on the same runner and pinned CPU core, with alternating order. Timing includes parsing, preprocessing, search and model output. Mean PAR-2 uses solved wall time or a **2,000-second penalty** for timeout/memory limit, divided by 100; lower is better. SAT models passed original-CNF checks; all UNSAT answers matched published GBD statuses, without proof-certificate checking. Detected wrong answers, invalid models and execution errors: **0**. [Source](https://github.com/SeMinLim/uatu/commit/11d2add23b8a2b722ad38e150478f029d8c9e6b4) · [Evidence](tests/sat2025_vs_minisat_100.json) · [Run](https://github.com/SeMinLim/uatu/actions/runs/34763218971).

Matching heuristic policies does not establish equal runtime. Glucose performance parity has not been measured for this replacement. Earlier SAT Competition scores apply to [the previous revision](https://github.com/SeMinLim/uatu/blob/66cf8f1a731c3189969ae4510d833b8b06fb73ea/cpu/ver_5/README.md).
