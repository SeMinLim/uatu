# Uatu Ver5 Tiered Clause Management Validation

- Implementation: Ver. 3 plus CORE, TIER2, and LOCAL learned-clause management
- Isolation: VSIDS and one-step minimization retained; CHB and recursive minimization disabled
- Static validation: release, debug, and ASan/UBSan builds passed with warnings treated as errors
- Differential validation: 100 fixed-seed random CNFs matched MiniSAT; every SAT model was checked
- Tier-path validation: a fixed pigeonhole instance exercised learned-clause reduction under ASan/UBSan
- Benchmark validation: 10 SAT Competition 2025 Main Track instances, five SAT and five UNSAT
- Per-instance timeout: 300 seconds

| ID | Expected | Result | Model | Wall (s) | CORE | TIER2 | LOCAL | Reductions | Deleted |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|
| 18 | unsat | unsat | 1 | 1.450 | 10573 | 9657 | 9116 | 4 | 15183 |
| 21 | sat | sat | 1 | 0.000 | 0 | 1 | 0 | 0 | 0 |
| 29 | unsat | unsat | 1 | 151.640 | 21149 | 9377 | 25601 | 37 | 591029 |
| 54 | sat | sat | 1 | 10.180 | 40512 | 7744 | 15176 | 12 | 75368 |
| 70 | sat | sat | 1 | 24.140 | 37043 | 5300 | 23617 | 17 | 155066 |
| 72 | unsat | unsat | 1 | 3.780 | 17098 | 4046 | 1191 | 2 | 819 |
| 80 | sat | sat | 1 | 47.280 | 8302 | 1470 | 38848 | 33 | 507621 |
| 84 | unsat | unsat | 1 | 0.010 | 0 | 0 | 0 | 0 | 0 |
| 92 | sat | sat | 1 | 2.270 | 1 | 50 | 11071 | 3 | 18268 |
| 95 | unsat | unsat | 1 | 0.000 | 3 | 0 | 0 | 0 | 0 |

**Validation result: 10/10 correct.**
Aggregate solver wall time: **240.750 seconds**.
