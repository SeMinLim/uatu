#!/usr/bin/env python3
"""Focused correctness checks, not SAT Competition performance measurements."""
import itertools
import os
from pathlib import Path
import random
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
UNIT = r'''#include "solver.h"
#include <cassert>
#include <cmath>
#include <random>

static bool satisfies( const std::vector<std::vector<int>> &clauses, unsigned bits ) {
	for ( const std::vector<int> &clause : clauses ) {
		bool sat = false;
		for ( int literal : clause ) {
			const bool value = (bits >> (abs(literal) - 1)) & 1;
			if ( value == (literal > 0) ) sat = true;
		}
		if ( !sat ) return false;
	}
	return true;
}

int main() {
	{
		Solver s{}; s.vars = 4; s.initialize();
		s.conflicts = 4999;
		updateAdaptiveDecay(s);
		assert(std::abs(s.var_decay - 0.81) < 1e-12);
		std::vector<int> a{-1, 2}, b{-2, 3};
		s.add_clause(a); s.add_clause(b); s.origin_clauses = 2;
		s.decVarInTrail.push_back(0); s.assign(1, 1, -1);
		assert(s.propagate() == -1);
		s.decVarInTrail.push_back(s.trail.size()); s.assign(4, 2, -1);
		s.learnt = {-4, -3, -1};
		minimizeLearnedClauseRecursive(s);
		assert(s.learnt.size() == 2 && s.learnt[0] == -4 && s.learnt[1] == -1);
		assert(s.minimizedLiterals == 1);
		for ( unsigned char entry : s.heuristics.minKnown ) assert(entry == 0);
	}
	{
		Solver s{}; s.vars = 128; s.initialize();
		s.conflicts = 10000; s.lbd_queue_size = 50; s.fast_lbd_sum = 250;
		s.heuristics.trailQueueSize = 5000; s.heuristics.trailSum = 50000;
		for ( int &item : s.heuristics.trailQueue ) item = 10;
		s.decVarInTrail.push_back(0);
		for ( int i = 1; i <= 100; i ++ ) s.assign(i, 1, -1);
		observeConflictTrail(s);
		assert(s.heuristics.blockedRestarts == 1 && s.lbd_queue_size == 0);
		assert(s.trail.size() == 100 && s.decVarInTrail.size() == 1);
	}
	{
		Solver s{}; s.vars = 3; s.initialize();
		std::vector<int> a{-1, 2}, c{-1, 2, 3};
		s.add_clause(a); const int id = s.add_clause(c); s.origin_clauses = 1;
		s.clauseDB[id].lbd = 3; s.clauseDB[id].useCount = 1;
		s.heuristics.propagationWork = 100000;
		s.saved[1] = -1; s.saved[2] = 1; s.saved[3] = -1;
		assert(vivifyLearnedClauses(s));
		assert(s.clauseDB[id].literals.size() == 2);
		assert(s.heuristics.vivifiedClauses == 1);
		assert(s.trail.empty() && s.decVarInTrail.empty());
		assert(s.saved[1] == -1 && s.saved[2] == 1 && s.saved[3] == -1);
		assert(s.clauseDB[id].protectOnce);
	}
	{
		Solver s{}; s.vars = 4; s.initialize();
		std::vector<int> a{1, 2}, b{1, -2}, c{1, 3, 4};
		s.add_clause(a); s.add_clause(b); const int id = s.add_clause(c); s.origin_clauses = 2;
		s.clauseDB[id].lbd = 3; s.clauseDB[id].useCount = 1;
		s.heuristics.propagationWork = 100000;
		assert(vivifyLearnedClauses(s));
		assert(s.clauseDB[id].literals.size() == 1 && s.value[1] == 1);
		assert(s.reason[1] == id && s.level[1] == 0);
		assert(s.heuristics.vivificationUnits == 1);
		s.reduce();
		assert(s.value[1] == 1 && s.reason[1] >= 0);
	}
	// Compare every assignment before and after probing arbitrary small formulas.
	std::mt19937 rng(20260906);
	uint64_t totalShrunk = 0;
	for ( int trial = 0; trial < 500; trial ++ ) {
		Solver s{}; s.vars = 6; s.initialize();
		std::vector<std::vector<int>> before;
		const int count = 3 + rng() % 24;
		for ( int i = 0; i < count; i ++ ) {
			std::vector<int> clause;
			unsigned used = 0;
			const int width = 2 + rng() % 4;
			while ( static_cast<int>(clause.size()) < width ) {
				const int variable = 1 + rng() % 6;
				if ( used & (1U << variable) ) continue;
				used |= 1U << variable;
				clause.push_back(rng() % 2 ? variable : -variable);
			}
			before.push_back(clause);
			const int id = s.add_clause(clause);
			s.clauseDB[id].lbd = width;
			s.clauseDB[id].useCount = 1;
		}
		s.heuristics.propagationWork = 1000000;
		const bool consistent = vivifyLearnedClauses(s);
		std::vector<std::vector<int>> after;
		for ( const Clause &clause : s.clauseDB ) after.push_back(clause.literals);
		for ( unsigned bits = 0; bits < 64; bits ++ ) {
			if ( consistent ) assert(satisfies(before, bits) == satisfies(after, bits));
			else assert(!satisfies(before, bits));
		}
		assert(s.decVarInTrail.empty() && !s.heuristics.probing);
		totalShrunk += s.heuristics.vivifiedClauses;
	}
	assert(totalShrunk > 0);
	printf( "HEURISTIC_UNIT_AND_EXHAUSTIVE_VIVIFICATION_PASSED %llu\n", (unsigned long long)totalShrunk );
}
'''


def oracle(n, clauses):
    return any(all(any(values[abs(lit)-1] == (lit > 0) for lit in c) for c in clauses)
               for values in itertools.product((False, True), repeat=n))


def main():
    flags = ['-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Wpedantic', '-Werror',
             '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
    env = {k: v for k, v in os.environ.items() if not k.startswith('UATU_')}
    env.update(UATU_TIMEOUT_SEC='5', UATU_PRINT_MODEL='1',
               ASAN_OPTIONS='detect_leaks=1:halt_on_error=1:abort_on_error=1',
               UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        (tmp / 'unit.cpp').write_text(UNIT)
        sources = [str(ROOT / 'solver.cpp'), str(ROOT / 'heuristics.cpp')]
        subprocess.run(['g++', *flags, '-I', str(ROOT), *sources, str(tmp/'unit.cpp'), '-o', str(tmp/'unit')], check=True)
        subprocess.run([str(tmp/'unit')], env=env, check=True, timeout=120)
        subprocess.run(['g++', *flags, *sources, str(ROOT/'main.cpp'), '-o', str(tmp/'solver')], check=True)
        names = ['ADAPTIVE_EVSIDS', 'BLOCKED_RESTART', 'LBD_REDUCTION', 'RECURSIVE_MIN', 'VIVIFICATION']
        rng = random.Random(20260906)
        for combination in range(32):
            current = dict(env)
            current['UATU_REDUCE_INITIAL'] = '1'
            for i, name in enumerate(names):
                current['UATU_H_' + name] = str((combination >> i) & 1)
            for case in range(30):
                n = 7
                clauses = []
                for _ in range(rng.randint(18, 45)):
                    variables = rng.sample(range(1, n+1), rng.choice([2, 3, 3]))
                    clauses.append([v if rng.getrandbits(1) else -v for v in variables])
                cnf = tmp/'case.cnf'
                cnf.write_text(f'p cnf {n} {len(clauses)}\n' + ''.join(' '.join(map(str,c)) + ' 0\n' for c in clauses))
                expected = oracle(n, clauses)
                run = subprocess.run([str(tmp/'solver'), str(cnf)], env=current, text=True, capture_output=True, timeout=15)
                assert run.returncode == (10 if expected else 20), (combination, case, run.stdout, run.stderr)
                assert not any(word in run.stderr.lower() for word in ['sanitizer', 'runtime error', 'internal error']), run.stderr
                if expected:
                    lines = run.stdout.splitlines()
                    model = [int(v) for v in lines[lines.index('SATISFIABLE')+1].split()]
                    assert model[-1] == 0 and len(model) == n+1
                    assignment = {abs(v): v > 0 for v in model[:-1]}
                    assert len(assignment) == n
                    assert all(any(assignment[abs(v)] == (v > 0) for v in c) for c in clauses)
            print('POLICY_COMBINATION_PASSED', combination, flush=True)
    print('ALL_32_POLICY_COMBINATIONS_PASSED', flush=True)

if __name__ == '__main__':
    main()
