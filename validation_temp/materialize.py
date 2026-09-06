from pathlib import Path
import shutil
import subprocess

BASE = 'ef7ee281b770758a318329501d85061fc563b496'
root = Path('cpu/ver_5')
if root.exists():
    shutil.rmtree(root)
root.mkdir(parents=True)
for name in ('solver.h', 'solver.cpp', 'main.cpp', 'Makefile', 'tests/regression.py'):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(subprocess.check_output(['git', 'show', f'{BASE}:cpu/ver_4/{name}']))
for name in ('heuristics.h', 'heuristics.cpp'):
    shutil.copyfile(Path('validation_temp') / name, root / name)


def replace(text, old, new):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'expected one patch point, found {count}: {old[:100]!r}')
    return text.replace(old, new, 1)


p = root / 'solver.h'
s = p.read_text()
s = '#ifndef UATU_VER5_SOLVER_H\n#define UATU_VER5_SOLVER_H\n#include "heuristics.h"\n' + s + '\n#endif\n'
s = replace(s, '\tuint32_t useCount;', '\tuint32_t useCount;\n\tbool protectOnce = false;')
s = replace(s, '\tSolver() = default;', '\tHeuristicState heuristics;\n\tSolver() = default;')
p.write_text(s)

p = root / 'solver.cpp'
s = p.read_text()
s = replace(s, '                vsids.insert(i);\n        }\n}', '                vsids.insert(i);\n        }\n\tconfigureHeuristics(*this);\n}')
s = replace(s, '                for ( int i = 0; i < numClauses; ) {', '''                for ( int i = 0; i < numClauses; ) {
                        if ( heuristics.probing && heuristics.propagationWork >= heuristics.probeEnd ) {
                                while ( i < numClauses ) ws[out ++] = ws[i ++];
                                ws.resize(out);
                                return -2;
                        }
                        heuristics.propagationWork ++;''')
s = replace(s, '                        while ( k < size && Value(c[k]) == -1 ) ++k;', '''                        while ( k < size && Value(c[k]) == -1 ) {
                                if ( heuristics.probing && heuristics.propagationWork >= heuristics.probeEnd ) {
                                        ws[out ++] = watcher;
                                        while ( i < numClauses ) ws[out ++] = ws[i ++];
                                        ws.resize(out);
                                        return -2;
                                }
                                heuristics.propagationWork ++;
                                k ++;
                        }''')
s = replace(s, '                clause.lbd = currentLBD;\n                dynamicLBDUpdates ++;', '''                if ( heuristics.lbdReduction && clause.lbd <= 30 && currentLBD + 1 < clause.lbd ) {
                        clause.protectOnce = true;
                }
                clause.lbd = currentLBD;
                dynamicLBDUpdates ++;''')
s = replace(s, '                        update_score(variable, 0.5);', '                        update_score(variable, heuristics.adaptiveEVSIDS ? 1.0 : 0.5);')
s = replace(s, '''        // Non-recursive, one-step reason minimization.
        if ( learnt.size() > 1 ) {''', '''        // Select a CPU-side minimization policy without replacing BCP.
        if ( heuristics.recursiveMinimization ) {
                minimizeLearnedClauseRecursive(*this);
        } else if ( learnt.size() > 1 ) {''')
s = replace(s, '        slow_lbd_sum += lbd > 50 ? 50 : lbd;', '        slow_lbd_sum += heuristics.blockedRestart ? lbd : (lbd > 50 ? 50 : lbd);')
s = replace(s, '''        // Original second-stage bump retained after the ablation trial.
        for ( int variable : bump ) {
                if ( level[variable] >= backtrackLevel - 1 ) update_score(variable, 1.0);
        }''', '''        // Glucose-style additional reward for useful current-level reasons.
        for ( int variable : bump ) {
                if ( heuristics.adaptiveEVSIDS ) {
                        const int cref = reason[variable];
                        if ( level[variable] == conflictLevel && cref >= origin_clauses &&
                             cref >= 0 && cref < static_cast<int>(clauseDB.size()) &&
                             clauseDB[cref].lbd < lbd ) update_score(variable, 1.0);
                } else if ( level[variable] >= backtrackLevel - 1 ) {
                        update_score(variable, 1.0);
                }
        }''')
s = replace(s, '''        for ( int i = origin_clauses; i < oldSize; i ++ ) {
                if ( !locked[i] && clauseDB[i].lbd >= 5 ) candidates.push_back(i);
        }''', '''        for ( int i = origin_clauses; i < oldSize; i ++ ) {
                Clause &clause = clauseDB[i];
                const bool protectedNow = clause.protectOnce;
                clause.protectOnce = false;
                if ( locked[i] ) continue;
                if ( heuristics.lbdReduction ) {
                        if ( protectedNow ) { heuristics.protectedClauses ++; continue; }
                        if ( clause.literals.size() > 2 && clause.lbd > 2 ) candidates.push_back(i);
                } else if ( clause.lbd >= 5 ) candidates.push_back(i);
        }''')
s = replace(s, '''                if ( clauseDB[a].activity != clauseDB[b].activity ) {''', '''                if ( heuristics.lbdReduction && clauseDB[a].lbd != clauseDB[b].lbd ) {
                        return clauseDB[a].lbd > clauseDB[b].lbd;
                }
                if ( clauseDB[a].activity != clauseDB[b].activity ) {''')
s = replace(s, '''                        result = analyze(conflictClause, backtrackLevel, lbd);''', '''                        observeConflictTrail(*this);
                        result = analyze(conflictClause, backtrackLevel, lbd);''')
s = replace(s, '''                                clauseDB[learnedClause].lbd = lbd;''', '''                                clauseDB[learnedClause].lbd = lbd;
                                clauseDB[learnedClause].activity = clause_inc;''')
s = replace(s, '''                        var_inc *= 1.0 / var_decay;''', '''                        updateAdaptiveDecay(*this);
                        var_inc *= 1.0 / var_decay;''')
s = replace(s, '''                } else if ( reduces >= reduce_limit ) {
                        reduce();''', '''                } else if ( reduces >= reduce_limit ) {
                        reduce();
                        if ( !vivifyLearnedClauses(*this) ) { result = 20; break; }''')
s = replace(s, '''                } else if ( conflicts >= rephase_limit ) {''', '''                } else if ( heuristics.rephase && conflicts >= rephase_limit ) {''')
p.write_text(s)

p = root / 'main.cpp'
s = p.read_text()
s = replace(s, '''	printf( "Active Clauses       : %zu\\n", solver.clauseDB.size() );''', '''	printf( "Active Clauses       : %zu\\n", solver.clauseDB.size() );
	printHeuristicStatistics(solver);''')
s = replace(s, '''	} catch ( const std::length_error & ) {
		fprintf( stderr, "c RESOURCE LIMIT: container size exceeded during %s\\n", stage );
		result = 30;
	}''', '''	} catch ( const std::length_error & ) {
		fprintf( stderr, "c RESOURCE LIMIT: container size exceeded during %s\\n", stage );
		result = 30;
	} catch ( const std::invalid_argument &error ) {
		fprintf( stderr, "c CONFIGURATION ERROR: %s\\n", error.what() );
		result = 30;
	} catch ( const std::logic_error &error ) {
		fprintf( stderr, "c INTERNAL ERROR: %s\\n", error.what() );
		result = 30;
	}''')
p.write_text(s)

p = root / 'Makefile'
s = p.read_text().replace('SOURCES := solver.cpp main.cpp', 'SOURCES := solver.cpp heuristics.cpp main.cpp').replace('HEADERS := solver.h', 'HEADERS := solver.h heuristics.h')
p.write_text(s)
p = root / 'tests/regression.py'
s = p.read_text().replace("ROOT / 'solver.cpp',", "ROOT / 'solver.cpp', ROOT / 'heuristics.cpp',")
s = s.replace('Ver4 sanity-fix regressions', 'Ver5 inherited sanity-fix regressions')
p.write_text(s)
(root / 'README.md').write_text('''# Uatu Ver. 5

Based on corrected Ver. 4 (`ef7ee281`), with five independently selectable CPU policies:

- Adaptive EVSIDS: decay 0.8 to 0.95, plus reason-quality activity rewards.
- Blocked LBD restarts: retain root restarts, but protect unusually deep conflict trails.
- LBD-first reduction: protect binary, glue, locked and recently improved clauses.
- Iterative recursive learned-clause minimization with successful-reason reuse.
- Selective learned-clause vivification at reduction epochs, bounded by propagation work.

These are Glucose-inspired policies integrated with Uatu's existing CDCL, not a full Glucose port. The BCP implementation and Ver4's root rephase sequence remain available. Ver4 is unchanged.

```bash
make
make run CNF=/path/to/input.cnf TIMEOUT=1000
UATU_H_VIVIFICATION=0 obj/uatu_solver input.cnf
```

Each switch accepts `0` or `1` (default `1`): `UATU_H_ADAPTIVE_EVSIDS`, `UATU_H_BLOCKED_RESTART`, `UATU_H_LBD_REDUCTION`, `UATU_H_RECURSIVE_MIN`, `UATU_H_VIVIFICATION`. `UATU_H_REPHASE=0` disables the inherited phase-target policy without disabling phase saving or restarts.

`heuristics.h` / `heuristics.cpp` hold the policy state and CPU-side helpers. The propagation routine supplies implications, conflicts and bounded-probe work accounting; adding a CPU policy does not replace it. No FPGA implementation or accelerator performance is claimed by this software version.

References: Audemard and Simon, *Refining Restarts Strategies for SAT and UNSAT* (CP 2012); Sorensson and Biere, *Minimizing Learned Clauses* (SAT 2009); Li et al., *Clause Vivification by Unit Propagation in CDCL SAT Solvers* (Artificial Intelligence 2019); Glucose official source `audemard/glucose`, `core/Solver.cc` (blob `61cf6d8d`).

Run `python3 tests/regression.py --samples 500` and `python3 tests/heuristics_regression.py` for focused regression checks. SAT Competition performance is reported separately; a timeout or memory limit is not a solved instance.
''')
print('MATERIALIZED_VER5_FROM', BASE)
