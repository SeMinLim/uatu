import itertools
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile

ROOT = Path('cpu/ver_5').resolve()
UNIT = r'''#include "solver.h"
#include <cassert>
#include <cmath>
#include <cstdio>

static void initialize( Solver &s, int variables ) {
	s.vars = variables;
	s.clauses = 0;
	s.initialize();
}

static bool valueOf( int literal, unsigned mask ) {
	const bool value = (mask >> (abs(literal) - 1)) & 1U;
	return value == (literal > 0);
}

static bool formulaValue( const std::vector<Clause> &formula, unsigned mask ) {
	for ( const Clause &clause : formula ) {
		bool satisfied = false;
		for ( int literal : clause.literals ) satisfied |= valueOf(literal, mask);
		if ( !satisfied ) return false;
	}
	return true;
}

static void checkVivification( bool unit, uint64_t credits ) {
	Solver s{};
	initialize(s, 5);
	std::vector<int> a{1, 2};
	std::vector<int> b = unit ? std::vector<int>{1, -2} : std::vector<int>{-3, 4};
	s.add_clause(a);
	s.add_clause(b);
	s.origin_clauses = 2;
	std::vector<int> target = unit ? std::vector<int>{1, 3, 4, 5} : std::vector<int>{1, 2, 3, 4};
	const int reference = s.add_clause(target);
	s.clauseDB[reference].lbd = 4;
	s.clauseDB[reference].vivifyEligible = true;
	const std::vector<Clause> before = s.clauseDB;
	s.heuristics.searchWork = credits * 50;
	assert(vivifyAtRoot(s) == 0);
	assert(s.decVarInTrail.empty());
	for ( int v = 1; v <= 5; v ++ ) {
		assert(s.saved[v] == 0 && s.local_best[v] == 0);
		if ( s.value[v] == 0 ) assert(s.reason[v] == -1 && s.level[v] == 0);
	}
	for ( unsigned mask = 0; mask < 32; mask ++ ) {
		assert(formulaValue(before, mask) == formulaValue(s.clauseDB, mask));
	}
	if ( credits >= 100 ) {
		assert(s.clauseDB[reference].literals.size() == (unit ? 1U : 2U));
		assert(s.heuristics.vivifiedClauses == 1);
		if ( unit ) {
			assert(s.value[1] == 1 && s.level[1] == 0 && s.reason[1] == reference);
			s.reduce();
			assert(s.reason[1] >= s.origin_clauses);
		}
	} else {
		assert(s.clauseDB[reference].literals == target);
	}
	int watches = 0;
	for ( int p = -s.vars; p <= s.vars; p ++ ) {
		for ( const WL &watcher : s.watched_literals[s.vars + p] ) {
			assert(watcher.clauseIdx >= 0 && watcher.clauseIdx < int(s.clauseDB.size()));
			if ( watcher.clauseIdx == reference ) watches ++;
		}
	}
	assert(watches == (s.clauseDB[reference].literals.size() == 1 ? 0 : 2));
}

int main() {
	{
		Solver s{};
		initialize(s, 6);
		s.conflicts = 4999;
		recordSearchConflict(s);
		assert(std::abs(s.var_decay - 0.81) < 1e-9);
		s.conflicts = 79999;
		s.var_decay = 0.95;
		recordSearchConflict(s);
		assert(s.var_decay == 0.95);
		for ( int i = 0; i < UATU_TRAIL_WINDOW; i ++ ) s.heuristics.trailHistory[i] = 1;
		s.heuristics.trailCount = UATU_TRAIL_WINDOW;
		s.heuristics.trailSum = UATU_TRAIL_WINDOW;
		s.lbd_queue_size = 50;
		s.fast_lbd_sum = 500;
		for ( int v = 1; v <= 6; v ++ ) s.assign(v, 0, -1);
		recordSearchConflict(s);
		assert(s.lbd_queue_size == 0 && s.fast_lbd_sum == 0);
		assert(s.heuristics.blockedRestarts == 1);
		assert(s.trail.size() == 6);
	}
	{
		Solver s{};
		initialize(s, 4);
		std::vector<int> a{-1, 2};
		std::vector<int> b{-2, 3};
		int ar = s.add_clause(a), br = s.add_clause(b);
		s.assign(1, 1, -1);
		s.assign(2, 1, ar);
		s.assign(3, 1, br);
		s.assign(4, 2, -1);
		s.learnt = {-4, -1, -3};
		assert(minimizeLearntRecursive(s));
		assert((s.learnt == std::vector<int>{-4, -1}));
		assert(s.heuristics.recursiveRemoved == 1);
		s.time_stamp = UINT32_MAX;
		s.learnt = {-4, -1, -3};
		assert(minimizeLearntRecursive(s));
		assert((s.learnt == std::vector<int>{-4, -1}));
	}
	{
		Solver s{};
		initialize(s, 6);
		std::vector<int> c{1, 2, 3, 4};
		const int id = s.add_clause(c);
		s.clauseDB[id].lbd = 10;
		for ( int v = 1; v <= 4; v ++ ) s.assign(v, 1, -1);
		s.updateClauseQuality(id);
		assert(s.clauseDB[id].lbd == 1 && s.clauseDB[id].protectOnce);
		s.clauseDB[id].lbd = 5;
		s.reduce();
		assert(s.clauseDB.size() == 1 && !s.clauseDB[id].protectOnce);
		assert(s.heuristics.protectedClauses == 1);
	}
	checkVivification(false, 1000);
	checkVivification(true, 1000);
	checkVivification(false, 0);
	checkVivification(false, 1);
	printf("FIVE_HEURISTIC_UNIT_CHECKS_PASSED\n");
}
'''

OPTIONS = ['UATU_ADAPTIVE_EVSIDS', 'UATU_BLOCKED_RESTART', 'UATU_LBD_REDUCTION',
           'UATU_RECURSIVE_MINIMIZATION', 'UATU_VIVIFICATION']


def oracle(n, clauses):
    return any(all(any(bits[abs(q)-1] == (q > 0) for q in c) for c in clauses)
               for bits in itertools.product((False, True), repeat=n))


def verify(process, n, clauses, expected):
    assert process.returncode == (10 if expected else 20), process.stdout + process.stderr
    assert 'internal error' not in process.stderr and 'runtime error:' not in process.stderr, process.stderr
    if expected:
        lines = process.stdout.splitlines()
        literals = [int(q) for q in lines[lines.index('SATISFIABLE') + 1].split()]
        assert literals[-1] == 0 and len(literals) == n+1
        model = {abs(q): q > 0 for q in literals[:-1]}
        assert set(model) == set(range(1, n+1))
        assert all(any(model[abs(q)] == (q > 0) for q in c) for c in clauses)


work = Path('feature-work')
work.mkdir(exist_ok=True)
(work / 'unit.cpp').write_text(UNIT)
sources = [str(ROOT / n) for n in ('solver.cpp', 'heuristics.cpp', 'vivify.cpp')]
subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Wpedantic', '-Werror', '-O1', '-g',
                '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-fno-omit-frame-pointer',
                '-fno-pie', '-no-pie', '-I', str(ROOT), *sources, str(work/'unit.cpp'), '-o', str(work/'unit')], check=True)
env = {k: v for k, v in os.environ.items() if not k.startswith('UATU_')}
env.update(ASAN_OPTIONS='detect_leaks=1:abort_on_error=1', UBSAN_OPTIONS='halt_on_error=1', UATU_PRINT_MODEL='1')
subprocess.run([str(work/'unit')], env=env, check=True)
rng = random.Random(20260906)
formulas = []
for _ in range(24):
    n = rng.randint(3, 8)
    clauses = []
    for _ in range(5*n):
        variables = rng.sample(range(1, n+1), min(n, 3))
        clauses.append([v if rng.getrandbits(1) else -v for v in variables])
    formulas.append((n, clauses, oracle(n, clauses)))
for mask in range(32):
    config = env.copy()
    config.update({name: str((mask >> i) & 1) for i, name in enumerate(OPTIONS)})
    for n, clauses, expected in formulas:
        cnf = work / 'case.cnf'
        cnf.write_text(f'p cnf {n} {len(clauses)}\n' + ''.join(' '.join(map(str, c))+' 0\n' for c in clauses))
        process = subprocess.run([str(ROOT/'obj/uatu_solver'), str(cnf)], env=config, capture_output=True, text=True, timeout=10)
        verify(process, n, clauses, expected)
summary = {'feature_units_passed': True, 'feature_combinations': 32, 'formulas_per_combination': len(formulas),
           'switch_checks': 32*len(formulas), 'five_default_features': OPTIONS}
(work/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
print('FEATURE_CHECKS=' + json.dumps(summary), flush=True)
