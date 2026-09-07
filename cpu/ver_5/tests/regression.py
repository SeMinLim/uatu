#!/usr/bin/env python3
"""Run Ver5 solver regressions. Requires g++, Linux prlimit, and Python 3.

No competition performance score is computed here. Counter probes deliberately
start near integer boundaries; production solver initialization remains zero.
"""
import argparse
import itertools
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FLAGS = ['-std=c++17', '-Wall', '-Wextra', '-Wpedantic', '-Werror']
SAN = ['-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']

UNIT = r'''#include "solver.h"
#include <cassert>
#include <inttypes.h>

int main() {
	{
		Solver s{};
		s.vars = 3;
		s.clauses = 2;
		s.initialize();
		std::vector<int> first{-1, 2};
		std::vector<int> second{-2, 3};
		s.add_clause(first);
		s.add_clause(second);
		s.unitPropagations = INT_MAX;
		s.bcpFunctionCalls = INT_MAX;
		s.assign(1, 0, -1);
		assert(s.propagate() == -1);
		assert(s.unitPropagations == uint64_t(INT_MAX) + 2);
		assert(s.bcpFunctionCalls == uint64_t(INT_MAX) + 1);
		assert(s.value[2] == 1 && s.value[3] == 1);
		s.time_stamp = UINT32_MAX;
		for ( int i = 0; i <= s.vars; i ++ ) s.mark[i] = UINT32_MAX;
		s.nextAnalysisStamp();
		assert(s.time_stamp == 1);
		for ( int i = 0; i <= s.vars; i ++ ) assert(s.mark[i] == 0);
	}
	{
		Solver s{};
		s.vars = 2;
		s.clauses = 4;
		s.initialize();
		for ( int a = -1; a <= 1; a += 2 ) {
			for ( int b = -1; b <= 1; b += 2 ) {
				std::vector<int> clause{a, 2 * b};
				s.add_clause(clause);
			}
		}
		s.origin_clauses = 4;
		s.conflicts = INT_MAX;
		s.decides = INT_MAX;
		s.time_stamp = UINT32_MAX - 1;
		assert(s.solve() == 20);
		assert(s.conflicts > uint64_t(INT_MAX));
		assert(s.decides > uint64_t(INT_MAX));
	}
	{
		Solver s{};
		s.initialize();
		s.restarts = INT_MAX;
		s.restart();
		assert(s.restarts == uint64_t(INT_MAX) + 1);
		s.rephases = INT_MAX;
		s.conflicts = 5;
		s.rephase_inc = UINT64_MAX / 2 + 1;
		s.rephase();
		assert(s.rephases == uint64_t(INT_MAX) + 1);
		assert(s.rephase_inc == UINT64_MAX && s.rephase_limit == UINT64_MAX);
		s.reduce_limit = INT_MAX;
		s.reductionRuns = INT_MAX;
		s.reduce();
		assert(s.reduce_limit == uint64_t(INT_MAX) + 512);
		assert(s.reductionRuns == uint64_t(INT_MAX) + 1);
		s.reduce_limit = UINT64_MAX - 10;
		s.reduce();
		assert(s.reduce_limit == UINT64_MAX);
	}
	{
		Solver s{};
		s.vars = 3;
		s.initialize();
		std::vector<int> a{1, 2, 3};
		std::vector<int> b{-1, 2, 3};
		s.clauseDB[s.add_clause(a)].lbd = 10;
		s.clauseDB[s.add_clause(b)].lbd = 9;
		s.deletedClauses = INT_MAX;
		s.reduce();
		assert(s.deletedClauses == uint64_t(INT_MAX) + 1);
		assert(s.clauseDB.size() == 1);
	}
	printf( "COUNTER_AND_STAMP_REGRESSIONS_PASSED\n" );
}
'''

LBD_UNIT = r'''#include "solver.h"
#include <cassert>

// Verify that compaction retains both watches and every assigned reason.
static void checkClauseReferences( Solver &s ) {
	std::vector<int> watchCount(s.clauseDB.size(), 0);
	for ( int literal = -s.vars; literal <= s.vars; literal ++ ) {
		if ( literal == 0 ) continue;
		for ( const WL &watch : s.watched_literals[s.vars + literal] ) {
			assert(watch.clauseIdx >= 0);
			assert(watch.clauseIdx < static_cast<int>(s.clauseDB.size()));
			const Clause &clause = s.clauseDB[watch.clauseIdx];
			assert(clause.literals[0] == -literal || clause.literals[1] == -literal);
			bool blockerFound = false;
			for ( int member : clause.literals ) {
				if ( member == watch.blocker ) blockerFound = true;
			}
			assert(blockerFound);
			watchCount[watch.clauseIdx] ++;
		}
	}
	for ( int count : watchCount ) assert(count == 2);
	for ( int literal : s.trail ) {
		const int reason = s.reason[abs(literal)];
		if ( reason == -1 ) continue;
		assert(reason >= 0 && reason < static_cast<int>(s.clauseDB.size()));
		bool literalFound = false;
		for ( int member : s.clauseDB[reason].literals ) {
			if ( member == literal ) literalFound = true;
		}
		assert(literalFound);
	}
}

// All assignments are forbidden, except the all-false assignment in SAT mode.
static void solveWithEarlyReduction( bool satisfiable ) {
	Solver s{};
	s.vars = 5;
	s.initialize();
	std::vector<std::vector<int>> formula;
	for ( int mask = 0; mask < 32; mask ++ ) {
		if ( satisfiable && mask == 0 ) continue;
		std::vector<int> clause;
		for ( int variable = 1; variable <= s.vars; variable ++ ) {
			clause.push_back((mask & (1 << (variable - 1))) ? -variable : variable);
		}
		formula.push_back(clause);
		s.add_clause(clause);
	}
	s.origin_clauses = static_cast<int>(s.clauseDB.size());
	// Duplicate originals are sound learnt clauses for the deletion exercise.
	for ( int i = 0; i < 8; i ++ ) {
		s.clauseDB[s.add_clause(formula[i])].lbd = 5;
	}
	s.reduce_limit = 1;
	assert(s.solve() == (satisfiable ? 10 : 20));
	assert(s.conflicts > 0 && s.reductionRuns > 0 && s.deletedClauses > 0);
	if ( satisfiable ) {
		for ( const std::vector<int> &clause : formula ) {
			bool satisfied = false;
			for ( int literal : clause ) {
				if ( s.value[abs(literal)] == (literal > 0 ? 1 : -1) ) satisfied = true;
			}
			assert(satisfied);
		}
	}
	checkClauseReferences(s);
}

int main() {
	{
		// LBD outranks activity; equal-LBD ties use activity, then clause ID.
		Solver s{};
		s.vars = 8;
		s.initialize();
		const int lbds[] = {8, 7, 6, 6, 6, 4};
		const double activities[] = {1000.0, 0.0, 1.0, 1.0, 3.0, 0.0};
		for ( int i = 0; i < 6; i ++ ) {
			std::vector<int> clause{1, 2, 3};
			if ( i == 3 ) clause.push_back(4);
			const int id = s.add_clause(clause);
			s.clauseDB[id].lbd = lbds[i];
			s.clauseDB[id].activity = activities[i];
			assert(s.clauseDB[id].canBeDeleted);
		}
		s.reduce();
		assert(s.deletedClauses == 3 && s.clauseDB.size() == 3);
		for ( int i = 0; i < 3; i ++ ) assert(s.reduceMap[i] == -1);
		for ( int i = 3; i < 6; i ++ ) assert(s.reduceMap[i] == i - 3);
		checkClauseReferences(s);
	}
	{
		// LBD 3 and 4 are eligible; glue clauses contribute to the half-DB window.
		Solver s{};
		s.vars = 4;
		s.initialize();
		const int lbds[] = {4, 3, 2, 2};
		for ( int i = 0; i < 4; i ++ ) {
			std::vector<int> clause{1, 2, 3, 4};
			s.clauseDB[s.add_clause(clause)].lbd = lbds[i];
		}
		s.reduce();
		assert(s.deletedClauses == 2 && s.clauseDB.size() == 2);
		assert(s.reduceMap[0] == -1 && s.reduceMap[1] == -1);
		assert(s.reduceMap[2] == 0 && s.reduceMap[3] == 1);
		checkClauseReferences(s);
	}
	for ( int binary = 0; binary <= 1; binary ++ ) {
		// Unlocked binary and glue clauses remain protected inside the window.
		Solver s{};
		s.vars = 3;
		s.initialize();
		for ( int i = 0; i < 2; i ++ ) {
			std::vector<int> clause{1, 2};
			if ( !binary ) clause.push_back(3);
			s.clauseDB[s.add_clause(clause)].lbd = binary ? 99 : 2;
		}
		s.reduce();
		assert(s.deletedClauses == 0 && s.clauseDB.size() == 2);
		assert(s.reduceMap[0] == 0 && s.reduceMap[1] == 1);
		checkClauseReferences(s);
	}
	{
		// Preserve originals, glue, binary clauses and root reasons while remapping.
		Solver s{};
		s.vars = 7;
		s.initialize();
		std::vector<std::vector<int>> clauses{
			{-1, 2}, {-3, 4, 5}, {3, -4, 5}, {3, -1, -2},
			{2, 4, 5}, {-3, 6}, {-6, 7}
		};
		const int lbds[] = {100, 9, 8, 7, 2, 99, 99};
		for ( int i = 0; i < 7; i ++ ) {
			s.clauseDB[s.add_clause(clauses[i])].lbd = lbds[i];
		}
		s.origin_clauses = 1;
		s.assign(1, 0, -1);
		assert(s.propagate() == -1);
		assert(s.reason[2] == 0 && s.reason[3] == 3);
		assert(s.reason[6] == 5 && s.reason[7] == 6);
		s.decVarInTrail.push_back(static_cast<int>(s.trail.size()));
		s.assign(-4, 1, -1);
		assert(s.propagate() == -1 && s.reason[5] == 1);
		s.reduce();
		assert(s.deletedClauses == 2 && s.clauseDB.size() == 5);
		assert(s.reduceMap[0] == 0 && s.reduceMap[1] == -1 && s.reduceMap[2] == -1);
		assert(s.decVarInTrail.empty() && s.value[4] == 0 && s.value[5] == 0);
		assert(s.reason[4] == -1 && s.reason[5] == -1);
		assert(s.reason[2] == 0 && s.reason[3] == 1);
		assert(s.reason[6] == 3 && s.reason[7] == 4);
		checkClauseReferences(s);
		s.assign(-4, 0, -1);
		assert(s.propagate() == -1 && s.value[5] == 0);
		checkClauseReferences(s);
	}
	{
		// Improved clauses survive one reduction; protection extends the window.
		Solver s{};
		s.vars = 6;
		s.initialize();
		for ( int i = 0; i < 4; i ++ ) {
			std::vector<int> clause{1, 2, 3, 4, 5, 6};
			const int id = s.add_clause(clause);
			s.clauseDB[id].lbd = i == 0 ? 6 : 3;
			s.clauseDB[id].activity = 10.0 * i;
		}
		for ( int variable = 1; variable <= 6; variable ++ ) {
			s.level[variable] = (variable - 1) % 3 + 1;
		}
		s.updateClauseQuality(0);
		assert(s.clauseDB[0].lbd == 3 && !s.clauseDB[0].canBeDeleted);
		assert(s.clauseDB[0].activity == 1.0 && s.clauseDB[0].useCount == 1);
		assert(s.dynamicLBDUpdates == 1 && s.clauseActivityBumps == 1);
		// Also reset protection on a survivor outside the deletion window.
		s.clauseDB[3].canBeDeleted = false;
		for ( int variable = 1; variable <= 6; variable ++ ) s.level[variable] = 0;
		s.reduce();
		assert(s.deletedClauses == 2 && s.clauseDB.size() == 2);
		assert(s.reduceMap[0] == 0 && s.reduceMap[1] == -1 && s.reduceMap[2] == -1);
		assert(s.reduceMap[3] == 1);
		assert(s.clauseDB[0].canBeDeleted && s.clauseDB[1].canBeDeleted);
		s.reduce();
		assert(s.deletedClauses == 3 && s.clauseDB.size() == 1);
		assert(s.reduceMap[0] == -1 && s.reduceMap[1] == 0);
		checkClauseReferences(s);
	}
	{
		// Protection uses pre-improvement LBD; one-level changes do not update.
		Solver s{};
		s.vars = 31;
		s.initialize();
		const int lbds[] = {30, 31, 4, 2, 0, 7};
		for ( int i = 0; i < 6; i ++ ) {
			std::vector<int> clause;
			for ( int variable = 1; variable <= 31; variable ++ ) clause.push_back(variable);
			s.clauseDB[s.add_clause(clause)].lbd = lbds[i];
		}
		s.origin_clauses = 1;
		for ( int variable = 1; variable <= 31; variable ++ ) s.level[variable] = (variable - 1) % 3 + 1;
		s.updateClauseQuality(-1);
		s.updateClauseQuality(0);
		s.updateClauseQuality(6);
		assert(s.clauseActivityBumps == 0 && s.dynamicLBDUpdates == 0);
		s.origin_clauses = 0;
		for ( int i = 0; i < 5; i ++ ) s.updateClauseQuality(i);
		assert(s.clauseDB[0].lbd == 3 && !s.clauseDB[0].canBeDeleted);
		assert(s.clauseDB[1].lbd == 3 && s.clauseDB[1].canBeDeleted);
		assert(s.clauseDB[2].lbd == 4 && s.clauseDB[2].canBeDeleted);
		assert(s.clauseDB[3].lbd == 2 && s.clauseDB[3].canBeDeleted);
		assert(s.clauseDB[4].lbd == 0 && s.clauseDB[4].canBeDeleted);
		assert(s.dynamicLBDUpdates == 2 && s.clauseActivityBumps == 5);
		for ( int variable = 1; variable <= 31; variable ++ ) s.level[variable] = 0;
		s.updateClauseQuality(5);
		assert(s.clauseDB[5].lbd == 7 && s.clauseDB[5].canBeDeleted);
		for ( int variable = 1; variable <= 31; variable ++ ) s.level[variable] = 1;
		s.updateClauseQuality(1);
		s.updateClauseQuality(3);
		assert(s.clauseDB[1].lbd == 1 && !s.clauseDB[1].canBeDeleted);
		assert(s.clauseDB[3].lbd == 2);
		assert(s.dynamicLBDUpdates == 3 && s.clauseActivityBumps == 8);
	}
	solveWithEarlyReduction(false);
	solveWithEarlyReduction(true);
	printf( "LBD_REDUCTION_REGRESSIONS_PASSED\n" );
}
'''

PROBE = r'''#include "solver.h"
#include <limits.h>
int main() {
	Solver s{};
	s.vars = 2;
	s.clauses = 1;
	s.initialize();
	std::vector<int> clause{-1, 2};
	s.add_clause(clause);
	s.unitPropagations = INT_MAX;
	s.assign(1, 0, -1);
	if ( s.propagate() != -1 ) return 2;
	printf( "COUNT=%llu\n", (unsigned long long)s.unitPropagations );
	return 0;
}
'''

FAULT = r'''#include <stddef.h>
#include <stdlib.h>
#include <new>

static long failAfter = -1;
extern "C" void *__real__Znwm(size_t);
extern "C" void *__real__Znam(size_t);
static void checkAllocation() {
	if ( failAfter == 0 ) {
		failAfter = -1;
		throw std::bad_alloc();
	}
	if ( failAfter > 0 ) failAfter --;
}
extern "C" void *__wrap__Znwm(size_t bytes) {
	checkAllocation();
	return __real__Znwm(bytes);
}
extern "C" void *__wrap__Znam(size_t bytes) {
	checkAllocation();
	return __real__Znam(bytes);
}
int uatuMain(int, char **);
int main(int argc, char **argv) {
	if ( argc != 3 ) return 2;
	failAfter = strtol(argv[1], nullptr, 10);
	return uatuMain(argc - 1, argv + 1);
}
'''


def command(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def run(binary, cnf, env, limit=None, extra=()):
    args = [str(binary), *map(str, extra), str(cnf)]
    if limit is not None:
        args = ['prlimit', f'--as={limit}:{limit}', '--', *args]
    result = subprocess.run(args, env=env, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=20)
    text = result.stdout + result.stderr
    assert not re.search(r'AddressSanitizer|LeakSanitizer|runtime error:', text), text[-5000:]
    assert result.returncode in (0, 10, 20), (args, result.returncode, text[-5000:])
    return result


def verify(result, variables, clauses, expected):
    assert result.returncode == (10 if expected else 20), result.stdout + result.stderr
    if expected:
        lines = result.stdout.splitlines()
        model = [int(x) for x in lines[lines.index('SATISFIABLE') + 1].split()]
        assert model and model[-1] == 0
        assignment = {}
        for literal in model[:-1]:
            assert 1 <= abs(literal) <= variables and abs(literal) not in assignment
            assignment[abs(literal)] = literal > 0
        for clause in clauses:
            assert any(assignment.get(abs(lit)) == (lit > 0) for lit in clause), clause


def write_cnf(path, variables, clauses):
    path.write_text(f'p cnf {variables} {len(clauses)}\n' +
                    ''.join(' '.join(map(str, row)) + ' 0\n' for row in clauses))


def brute(variables, clauses):
    for values in itertools.product((False, True), repeat=variables):
        if all(any(values[abs(lit) - 1] == (lit > 0) for lit in row) for row in clauses):
            return True
    return False


def test(work, samples, baseline):
    env = {k: v for k, v in os.environ.items() if not k.startswith('UATU_')}
    env.update(UATU_PRINT_MODEL='1', UATU_TIMEOUT_SEC='5',
               ASAN_OPTIONS='detect_leaks=1:halt_on_error=1:abort_on_error=1',
               UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
    sources = [ROOT / 'solver.cpp', ROOT / 'main.cpp']
    release = work / 'release'
    sanitized = work / 'sanitized'
    command(['g++', *FLAGS, '-O3', '-DNDEBUG', *sources, '-o', release])
    command(['g++', *FLAGS, *SAN, *sources, '-o', sanitized])
    command(['g++', *FLAGS, '-O2', '-DUATU_PROFILE_BCP=1', *sources, '-o', work / 'profile'])
    for name, source in (('unit', UNIT), ('lbd_unit', LBD_UNIT)):
        (work / f'{name}.cpp').write_text(source)
        command(['g++', *FLAGS, *SAN, '-I', ROOT, ROOT / 'solver.cpp', work / f'{name}.cpp', '-o', work / name])
        unit = subprocess.run([str(work / name)], env=env, capture_output=True, text=True, timeout=20)
        assert unit.returncode == 0, unit.stdout + unit.stderr
        print(unit.stdout, flush=True)

    cases = [(0, []), (0, [[]]), (1, [[1]]), (1, [[1], [-1]]),
             (2, [[-1, 2], [1]]), (2, [[1, 2], [1, -2], [-1, 2], [-1, -2]])]
    rng = random.Random(20260905)
    for _ in range(samples):
        n = rng.randint(3, 10)
        clauses = []
        for _ in range(rng.randint(2 * n, 6 * n)):
            chosen = rng.sample(range(1, n + 1), rng.choice([2, 3, 3, 3]))
            clauses.append([v if rng.getrandbits(1) else -v for v in chosen])
        cases.append((n, clauses))
    cnf = work / 'test.cnf'
    for index, (n, clauses) in enumerate(cases):
        write_cnf(cnf, n, clauses)
        expected = brute(n, clauses)
        for binary in (release, sanitized):
            verify(run(binary, cnf, env), n, clauses, expected)
        if index % 100 == 0:
            print('CORRECTNESS_CASES', index, flush=True)

    invalid = ['', 'c no header', 'p', 'p c', 'p cn', '1 0\n',
               'p cnf -1 0\n', 'p cnf 2147483647 0\n',
               'p cnf 999999999999999999999999 0\n',
               'p cnf 1 -1\n', 'p cnf 1 1\n2 0\n',
               'p cnf 1 1\n-2147483648 0\n', 'p cnf 1 1\nx 0\n',
               'p cnf 1 1\n1', 'p cnf 1 2\n1 0\n',
               'p cnf 1 0\n1 0\n', 'p cnf 1 0\np cnf 1 0\n',
               'p cnf 1 1\n1x 0\n', 'p cnf 1 1\n+ 0\n']
    for text in invalid:
        cnf.write_text(text)
        for binary in (release, sanitized):
            result = run(binary, cnf, env)
            assert result.returncode == 0 and 'UNSOLVED' in result.stdout
            assert 'PARSE ERROR' in result.stderr
    cnf.write_text('c final comment without newline\np\tcnf\t1\t1\r\n1 0\nc EOF')
    verify(run(sanitized, cnf, env), 1, [[1]], True)
    # Exercise refills in a comment, the header, and an integer token.
    for padding in (65530, 65532, 65534, 65535, 65536):
        cnf.write_text('c' + ' ' * padding + '\np cnf 1 1\n1 0')
        verify(run(sanitized, cnf, env), 1, [[1]], True)

    large = work / 'large-comment.cnf'
    with large.open('wb') as stream:
        stream.write(b'c')
        for _ in range(80):
            stream.write(b' ' * 1024**2)
        stream.write(b'\np cnf 1 1\n1 0\n')
    verify(run(release, large, env, 64 * 1024**2), 1, [[1]], True)
    cnf.write_text('p cnf 1000000 1\n1 0\n')
    limited = run(release, cnf, env, 32 * 1024**2)
    assert limited.returncode == 0 and 'UNSOLVED' in limited.stdout
    assert 'OUT OF MEMORY during parsing' in limited.stderr
    print('STREAMING_AND_MEMORY_LIMIT_REGRESSIONS_PASSED', flush=True)

    (work / 'fault.cpp').write_text(FAULT)
    command(['g++', *FLAGS, *SAN, '-Dmain=uatuMain', '-c', ROOT / 'main.cpp', '-o', work / 'main.o'])
    command(['g++', *FLAGS, *SAN, '-I', ROOT, ROOT / 'solver.cpp', work / 'fault.cpp', work / 'main.o',
             '-Wl,--wrap=_Znwm,--wrap=_Znam', '-o', work / 'fault'])
    write_cnf(cnf, 2, [[1, 2], [1, -2], [-1, 2], [-1, -2]])
    failures = 0
    consecutive_solved = 0
    stages = set()
    for point in range(256):
        result = run(work / 'fault', cnf, env, extra=(point,))
        if 'OUT OF MEMORY' in result.stderr:
            failures += 1
            consecutive_solved = 0
            assert result.returncode == 0 and 'UNSOLVED' in result.stdout
            stages.add('solving' if 'during solving' in result.stderr else 'parsing')
        else:
            assert result.returncode == 20, result.stdout + result.stderr
            consecutive_solved += 1
            if consecutive_solved == 8:
                break
    assert stages == {'parsing', 'solving'} and consecutive_solved == 8, (stages, failures)
    print('ALLOCATION_FAULT_INJECTION_PASSED', failures, sorted(stages), flush=True)

    baseline_evidence = None
    if baseline:
        old = work / 'baseline'
        old.mkdir()
        for name in ('solver.h', 'solver.cpp', 'main.cpp'):
            content = subprocess.check_output(['git', 'show', f'{baseline}:cpu/ver_4/{name}'], text=True)
            (old / name).write_text(content)
        (old / 'probe.cpp').write_text(PROBE)
        command(['g++', *FLAGS, '-O2', '-g', '-fsanitize=undefined', '-fno-sanitize-recover=all',
                 old / 'solver.cpp', old / 'probe.cpp', '-o', old / 'probe'])
        probe = subprocess.run([str(old / 'probe')], env=env, capture_output=True, text=True, timeout=20)
        assert probe.returncode != 0 and 'signed integer overflow' in probe.stderr, probe.stderr
        command(['g++', *FLAGS, '-O2', old / 'solver.cpp', old / 'main.cpp', '-o', old / 'release'])
        old_oom = subprocess.run(['prlimit', '--as=67108864:67108864', '--', str(old / 'release'), str(large)],
                                 env=env, capture_output=True, text=True, timeout=20)
        assert old_oom.returncode not in (0, 10, 20) and 'bad_alloc' in old_oom.stderr
        baseline_evidence = {'commit': baseline, 'injected_INT_MAX_overflow_reproduced': True,
                             'large_input_allocation_abort_reproduced': True}
        print('BASELINE_FAILURES_REPRODUCED', flush=True)
    summary = {'correctness_formulas_per_build': len(cases), 'correctness_builds': ['release', 'ASan+UBSan'],
               'malformed_inputs_per_build': len(invalid), 'allocation_failure_points': failures,
               'allocation_failure_stages': sorted(stages), 'leak_checking': True,
               'counter_boundary_tests': 'passed; deliberately injected INT_MAX / UINT32_MAX / UINT64_MAX',
               'lbd_reduction_tests': 'passed; ranking, eligibility, protections, window, dynamic LBD, compaction',
               'early_reduction_formulas': ['exhaustive 5-variable UNSAT', 'all-false-only 5-variable SAT'],
               'bounded_streaming_under_64_MiB': 'passed', 'controlled_OOM_under_32_MiB': 'passed',
               'baseline': baseline_evidence, 'all_passed': True}
    print('REGRESSION_SUMMARY=' + json.dumps(summary, sort_keys=True), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=int, default=500)
    parser.add_argument('--build-dir', type=Path)
    parser.add_argument('--baseline')
    args = parser.parse_args()
    if args.samples < 0:
        parser.error('--samples must be nonnegative')
    if args.build_dir:
        args.build_dir.mkdir(parents=True, exist_ok=True)
        summary = test(args.build_dir.resolve(), args.samples, args.baseline)
        (args.build_dir / 'regression.json').write_text(json.dumps(summary, indent=2) + '\n')
    else:
        with tempfile.TemporaryDirectory(prefix='uatu-regression-') as directory:
            test(Path(directory), args.samples, args.baseline)


if __name__ == '__main__':
    main()
