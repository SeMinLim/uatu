# Ver4 root-restart sanity check, 2026-09-05

## Evidence and method

This report transcribes measured outputs, not estimates. Solver source was frozen at `60e2f03e533d6d1c16995f119a876bae140bbdc5`. Main and solver source were not changed by this evaluation.

- Primary paired execution: https://github.com/SeMinLim/uatu/actions/runs/33957925983
- Independent complete-artifact audit: https://github.com/SeMinLim/uatu/actions/runs/33968654742 ; job 101313145949.
- Audit artifact ID: 9970235374; ZIP SHA256: `3d8ef9aecbead6f8705508dd4d02344950b13aaa26490e417160fcc72ddd4bf2`.
- Audit explicitly paginated and downloaded all 100 paired artifacts and all 100 isolated sanitizer artifacts; it checked indices, source commit, input hash and CNF SHA256 before recomputing PAR-2 with Decimal.
- Sample: 100 unique inputs uniformly sampled without replacement from the official SAT Competition 2025 Main Track 400, seed 20260905. No size, label, or solver-runtime filtering. Retrieved metadata labels: SAT 45, UNSAT 33, unknown 22.
- Manifest SHA256: `3373a928e37a915368f533a6fffbc9672c9a26aef2741d0076c9abe6364ad9bf`.
- Release limit: 1000 seconds wall time including input reading; 12 GiB virtual address space per process. Every unsolved result contributes 2000 seconds. No cases excluded.
- MiniSAT 2.2.1 package `1:2.2.1-8build1` was rerun on every input, not reused. Each pair ran sequentially on the same Ubuntu 24.04 runner, with order alternated by index. Up to 20 pairs in parallel; CPU models varied across hosted runners.

## Measured release results

| Solver | SAT | UNSAT | Solved | Timeout | Other unsolved | Sum of solved seconds | PAR-2 seconds |
|---|---:|---:|---:|---:|---:|---:|---:|
| Ver4 | 14 | 9 | 23 | 75 | 2 allocation-error aborts | 5929.93 | 1599.2993 |
| MiniSAT | 18 | 13 | 31 | 67 | 2 early INDETERMINATE returns | 6982.38 | 1449.8238 |

Ver4 minus MiniSAT PAR-2: 149.4755 seconds. Ver4 / MiniSAT: 1.103099080039933128425674899. MiniSAT / Ver4: 0.9065368814955399530281792783. Ver4's score is 10.30990800399331284256748990 percent higher (worse).

No observed wrong SAT model or contradictory SAT/UNSAT answer. All SAT models were checked against every original CNF clause. Returned UNSAT answers had a known label or independent paired confirmation; these were not UNSAT-proof certifications.

## Sanity failures

Two release aborts threw uncaught `std::bad_alloc`, exit 134, under the 12 GiB address-space limit:

| Index | Input | Hash | GDB allocation site |
|---|---|---|---|
| 33 | 9.normalised.cnf.xz | 1c21a43aa1ad437e4a7e4eb5b9cd45a1 | Solver::initialize(), solver.cpp:81, clauseDB.reserve() |
| 36 | pj2002_k500.cnf.xz | 0dd928240a9559ab7e50d088e3f168ac | Heap::insert(), solver.h:69, position-vector resize during Solver::initialize() |

Allocation diagnostic run: https://github.com/SeMinLim/uatu/actions/runs/33964216748 ; jobs 101301305403 and 101301305226. Both used unchanged source. MiniSAT returned INDETERMINATE (exit 0) on those same two cases; the PAR-2 penalty was the same for both solvers.

Three release output summaries contained negative Unit Propagations counts:

| Index | Input | Hash | Observed counter |
|---|---|---|---:|
| 34 | bv_ILA_Piccolo_BEQ_sanity_transition.cnf.xz | 7bdf3e5401cc263951003b569bcd689c | -1825834135 |
| 39 | SC25_Timetable_C_481_E_49_Cl_32_D_7_T_58.normalised.cnf.xz | 24bde22f729a988fb2394b644cb60d39 | -1741468820 |
| 70 | sudoku-N30-12.cnf.xz | 0aa22564d00e9716519918d84b25c4a7 | -840413766 |

Long UBSan rechecks on original inputs 34 and 39, without injected counters or source changes, confirmed `solver.cpp:216:33: runtime error: signed integer overflow: 2147483647 + 1 cannot be represented in type 'int'` inside Solver::propagate(). Detection occurred after approximately 524.54 and 538.21 seconds respectively. Diagnostic run: https://github.com/SeMinLim/uatu/actions/runs/33964552167 ; jobs 101302240210 and 101302240091. Diagnostic runs do not replace release PAR-2 measurements.

The initial sanitizer harness incorrectly imposed an address-space cap on its own parent process, preventing ASan shadow-memory initialization. Those failures were discarded as harness failures, not solver failures. All 100 inputs were rechecked in isolated ASan/UBSan executions with no virtual-address cap and a 12 GiB RSS guard, 30 seconds each, leak checking disabled. That short recheck found 1 SAT, 3 UNSAT and 96 timeouts, with no sanitizer diagnostic. Its short duration did not cover the later integer overflow. Isolated recheck run: https://github.com/SeMinLim/uatu/actions/runs/33959442043.

Conclusion: Ver4 did not pass the requested sanity check. The PAR-2 values are observed measurements of the current faulty implementation, not performance validation of an error-free solver. No source fixes were applied in this test task.
