# Uatu Ver. 4

Based on `cpu/ver_3`, with root-level restart and rephase semantics restored.

- First-UIP CDCL, non-chronological backjumping, two-watched-literal BCP, VSIDS, phase saving, and one-step clause minimization.
- Usage-aware learned-clause retention and dynamic LBD, unchanged from Ver. 3.
- The existing LBD trigger now calls `restart()`: backtrack to level 0, retain learned clauses and saved phases, and clear the recent-LBD window.
- `rephase()` backtracks to level 0 **before** installing phase targets, so ordinary phase saving cannot overwrite them. Ver. 3's phase-selection sequence and intervals are retained; this is not a full CaDiCaL port.
- Clause reduction still runs at level 0 and protects root reason clauses. Ordinary conflict backjumps retain their analyzed target level.

The previous Ver. 4 preprocessing, vivification, and LRB/EVSIDS implementation is removed. `cpu/ver_3` is unchanged.

```bash
make
make run CNF=/path/to/instance.cnf TIMEOUT=1000
```
