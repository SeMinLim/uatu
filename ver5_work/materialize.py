from pathlib import Path
import hashlib
import json
import re
import shutil
import subprocess

BASE = 'ef7ee281b770758a318329501d85061fc563b496'
SOURCE = Path('cpu/ver_4')
TARGET = Path('cpu/ver_5')
STAGING = Path(__file__).resolve().parent


def replace(text, old, new, label):
    if text.count(old) != 1:
        raise RuntimeError(f'{label}: expected one patch point, got {text.count(old)}')
    return text.replace(old, new, 1)


for filename in ('solver.h', 'solver.cpp', 'main.cpp', 'Makefile'):
    expected = subprocess.check_output(['git', 'show', f'{BASE}:cpu/ver_4/{filename}'])
    if (SOURCE / filename).read_bytes() != expected:
        raise RuntimeError(f'base source mismatch: {filename}')
if TARGET.exists():
    shutil.rmtree(TARGET)
shutil.copytree(SOURCE, TARGET, ignore=shutil.ignore_patterns('obj'))
for filename in ('heuristics.h', 'heuristics.cpp', 'vivify.cpp'):
    shutil.copy2(STAGING / filename, TARGET / filename)
h = (TARGET / 'heuristics.h').read_text().replace('#include <stdint.h>', '#include <stdint.h>\n#include <stddef.h>')
(TARGET / 'heuristics.h').write_text(h)

h = (TARGET / 'solver.h').read_text()
h = '#ifndef UATU_VER5_SOLVER_H\n#define UATU_VER5_SOLVER_H\n\n#include "heuristics.h"\n' + h + '\n#endif\n'
h = replace(h, '\tuint32_t useCount;', '\tuint32_t useCount;\n\tbool protectOnce;\n\tbool vivifyEligible;', 'clause metadata')
h = replace(h, 'useCount(0) { literals.resize(sz); }', 'useCount(0), protectOnce(false), vivifyEligible(false) { literals.resize(sz); }', 'metadata defaults')
h = replace(h, '\tSolver() = default;', '\tSolver() = default;\n\tHeuristicOptions options;\n\tHeuristicState heuristics;', 'CPU heuristic state')
h, count = re.subn(r'int\s+propagate\(\s*\);', 'int propagate( uint64_t *budget = nullptr );', h)
assert count == 1
(TARGET / 'solver.h').write_text(h)

s = (TARGET / 'solver.cpp').read_text()
s = replace(s, '        learnt.reserve(64);', '        learnt.reserve(64);\n        configureHeuristics(*this);', 'heuristic configuration')
s = replace(s, 'int Solver::propagate( void ) {', 'int Solver::propagate( uint64_t *budget ) {', 'bounded BCP')
s = replace(s, '                        const int blocker = ws[i].blocker;', '''                        if ( !chargePropagation(heuristics, budget) ) {
                                while ( i < numClauses ) ws[out++] = ws[i++];
                                ws.resize(out);
#if UATU_PROFILE_BCP
                                finishBcpTiming();
#endif
                                return -2;
                        }
                        const int blocker = ws[i].blocker;''', 'watcher work bound')
s = replace(s, '                        while ( k < size && Value(c[k]) == -1 ) ++k;', '''                        while ( k < size ) {
                                if ( !chargePropagation(heuristics, budget) ) {
                                        ws[out++] = watcher;
                                        while ( i < numClauses ) ws[out++] = ws[i++];
                                        ws.resize(out);
#if UATU_PROFILE_BCP
                                        finishBcpTiming();
#endif
                                        return -2;
                                }
                                if ( Value(c[k]) != -1 ) break;
                                ++k;
                        }''', 'literal work bound')
s = replace(s, '''        Clause &clause = clauseDB[cref];
        const int currentLBD = calculateClauseLBD(clause);''', '''        Clause &clause = clauseDB[cref];
        clause.vivifyEligible = true;
        const int currentLBD = calculateClauseLBD(clause);''', 'recent-use vivification eligibility')
s = replace(s, '''                clause.lbd = currentLBD;
                dynamicLBDUpdates ++;''', '''                if ( options.lbdReduction && clause.lbd <= 30 &&
                     currentLBD + 1 < clause.lbd ) clause.protectOnce = true;
                clause.lbd = currentLBD;
                dynamicLBDUpdates ++;''', 'improved-clause grace period')
s = replace(s, '                        update_score(variable, 0.5);', '                        update_score(variable, options.adaptiveEVSIDS ? 1.0 : 0.5);', 'EVSIDS bump')
s = replace(s, '''        // Non-recursive, one-step reason minimization.
        if ( learnt.size() > 1 ) {''', '''        if ( options.recursiveMinimization && !minimizeLearntRecursive(*this) ) return 30;

        // Retain the one-step policy for controlled heuristic replacement.
        if ( !options.recursiveMinimization && learnt.size() > 1 ) {''', 'recursive minimizer')
s = replace(s, '        slow_lbd_sum += lbd > 50 ? 50 : lbd;', '        slow_lbd_sum += options.blockedRestart ? lbd : (lbd > 50 ? 50 : lbd);', 'consistent LBD statistics')
s = replace(s, '''        // Original second-stage bump retained after the ablation trial.
        for ( int variable : bump ) {
                if ( level[variable] >= backtrackLevel - 1 ) update_score(variable, 1.0);
        }''', '''        // Glucose-style extra bump: a useful learned reason at the current level.
        for ( int variable : bump ) {
                if ( options.adaptiveEVSIDS ) {
                        const int reference = reason[variable];
                        if ( level[variable] == conflictLevel && reference >= origin_clauses &&
                             reference >= 0 && reference < static_cast<int>(clauseDB.size()) &&
                             clauseDB[reference].lbd < lbd ) update_score(variable, 1.0);
                } else if ( level[variable] >= backtrackLevel - 1 ) {
                        update_score(variable, 1.0);
                }
        }''', 'quality-limited extra bump')
s = replace(s, '''        for ( int i = origin_clauses; i < oldSize; i ++ ) {
                if ( !locked[i] && clauseDB[i].lbd >= 5 ) candidates.push_back(i);
        }''', '''        for ( int i = origin_clauses; i < oldSize; i ++ ) {
                Clause &clause = clauseDB[i];
                const bool protectedNow = clause.protectOnce;
                clause.protectOnce = false;
                if ( options.lbdReduction ) {
                        if ( protectedNow ) heuristics.protectedClauses ++;
                        if ( !locked[i] && !protectedNow && clause.lbd > 2 &&
                             clause.literals.size() > 2 ) candidates.push_back(i);
                } else if ( !locked[i] && clause.lbd >= 5 ) {
                        candidates.push_back(i);
                }
        }''', 'glue binary locked and temporary retention')
s = replace(s, '''        std::sort(candidates.begin(), candidates.end(), [&]( int a, int b ) {
                if ( clauseDB[a].activity != clauseDB[b].activity ) {''', '''        std::sort(candidates.begin(), candidates.end(), [&]( int a, int b ) {
                if ( options.lbdReduction && clauseDB[a].lbd != clauseDB[b].lbd ) {
                        return clauseDB[a].lbd > clauseDB[b].lbd;
                }
                if ( clauseDB[a].activity != clauseDB[b].activity ) {''', 'LBD-first ordering')
s = replace(s, '''                if ( conflictClause != -1 ) {
                        updateLocalBest();''', '''                if ( conflictClause != -1 ) {
                        recordSearchConflict(*this);
                        updateLocalBest();''', 'conflict observation hook')
s = replace(s, '''                } else if ( reduces >= reduce_limit ) {
                        reduce();''', '''                } else if ( reduces >= reduce_limit ) {
                        reduce();
                        result = vivifyAtRoot(*this);''', 'root-only inprocessing hook')
(TARGET / 'solver.cpp').write_text(s)

s = (TARGET / 'main.cpp').read_text()
point = '\tprintf( "Active Clauses       : %zu\\n", solver.clauseDB.size() );'
extra = '''
\tprintf( "Blocked Restarts     : %" PRIu64 "\\n", solver.heuristics.blockedRestarts );
\tprintf( "Decay Updates        : %" PRIu64 "\\n", solver.heuristics.decayUpdates );
\tprintf( "Recursive Calls      : %" PRIu64 "\\n", solver.heuristics.recursiveCalls );
\tprintf( "Recursive Removed    : %" PRIu64 "\\n", solver.heuristics.recursiveRemoved );
\tprintf( "Protected Clauses    : %" PRIu64 "\\n", solver.heuristics.protectedClauses );
\tprintf( "Vivification Runs    : %" PRIu64 "\\n", solver.heuristics.vivifyRuns );
\tprintf( "Vivified Clauses     : %" PRIu64 "\\n", solver.heuristics.vivifiedClauses );
\tprintf( "Vivified Literals    : %" PRIu64 "\\n", solver.heuristics.vivifiedLiterals );
\tprintf( "Vivification Work    : %" PRIu64 "\\n", solver.heuristics.vivifyWork );
\tprintf( "Vivify Budget Stops  : %" PRIu64 "\\n", solver.heuristics.vivifyBudgetStops );
'''
s = replace(s, point, point + extra, 'feature counters')
(TARGET / 'main.cpp').write_text(s)

s = (TARGET / 'Makefile').read_text()
s = replace(s, 'SOURCES := solver.cpp main.cpp', 'SOURCES := solver.cpp heuristics.cpp vivify.cpp main.cpp', 'build sources')
s = replace(s, 'HEADERS := solver.h', 'HEADERS := solver.h heuristics.h', 'build headers')
s = s.replace(' -march=native', '')
(TARGET / 'Makefile').write_text(s)

# Extend the inherited error-regression compiler commands to the new modules.
p = TARGET / 'tests/regression.py'
s = p.read_text()
s = replace(s, "sources = [ROOT / 'solver.cpp', ROOT / 'main.cpp']", "sources = [ROOT / 'solver.cpp', ROOT / 'heuristics.cpp', ROOT / 'vivify.cpp', ROOT / 'main.cpp']", 'regression sources')
s = s.replace("ROOT / 'solver.cpp', work /", "ROOT / 'solver.cpp', ROOT / 'heuristics.cpp', ROOT / 'vivify.cpp', work /")
s = replace(s, '\t\ts.deletedClauses = INT_MAX;', '\t\ts.options.lbdReduction = false;\n\t\ts.deletedClauses = INT_MAX;', 'legacy deletion-counter unit test')
p.write_text(s)

(TARGET / 'README.md').write_text('''# Uatu Ver. 5

Ver. 4 with selectable CPU-side CDCL heuristics. This is an integration of
Glucose-style policies, not a complete Glucose port or an FPGA implementation.

- Adaptive EVSIDS: decay 0.80 to 0.95; learned-reason-aware extra bump.
- Blocked LBD restart: 50 LBD samples, 5,000 trail samples, factor 1.4.
- LBD-first reduction: protect glue, binary and locked clauses; one-round grace after LBD improvement.
- Recursive learned-clause minimization: explicit stack and reusable successful reason closures.
- Selective vivification: root-level reduction epochs; at most 32 candidates and 2% of recent BCP inspection work, capped at 200,000 inspections.

Ver. 4 root restart, rephase, streaming input and resource-error handling remain.
Each policy has an explicit hook in `solver.cpp`; its implementation is in
`heuristics.cpp` or `vivify.cpp`. Runtime options are read once during initialization.

```sh
make
UATU_TIMEOUT_SEC=1000 obj/uatu_solver input.cnf
UATU_VIVIFICATION=0 obj/uatu_solver input.cnf
```

All five switches default to enabled. Set any to `0` for an ablation or replacement:
`UATU_ADAPTIVE_EVSIDS`, `UATU_BLOCKED_RESTART`, `UATU_LBD_REDUCTION`,
`UATU_RECURSIVE_MINIMIZATION`, `UATU_VIVIFICATION`.

Algorithm references: Audemard and Simon, *Predicting Learnt Clauses Quality in
Modern SAT Solvers* (IJCAI 2009); *Refining Restarts Strategies for SAT and UNSAT*
(CP 2012); Soerensson and Biere, *Minimizing Learned Clauses* (SAT 2009);
Li et al., *Clause Vivification by Unit Propagation in CDCL SAT Solvers* (2018).
''')

root = Path('README.md')
s = root.read_text()
lines = s.splitlines()
for i, line in enumerate(lines):
    if line.startswith('| `cpu/ver_4`'):
        lines.insert(i + 1, '| `cpu/ver_5` | Ver. 4 with selectable adaptive EVSIDS, blocked restarts, LBD-first retention, recursive minimization, and vivification |')
        break
else:
    raise RuntimeError('README version row missing')
root.write_text('\n'.join(lines) + '\n')

# Export only the implementation and documentation, never the temporary harness.
paths = [root] + sorted(p for p in TARGET.rglob('*') if p.is_file() and 'obj' not in p.parts)
manifest = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
Path('candidate-source.json').write_text(json.dumps({'base': BASE, 'files': manifest}, indent=2) + '\n')
print('MATERIALIZED_VER5', json.dumps(manifest, sort_keys=True), flush=True)
