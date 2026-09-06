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
