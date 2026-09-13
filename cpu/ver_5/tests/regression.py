#!/usr/bin/env python3
"""Check SAT semantics against exhaustive enumeration and an external solver.

The second driver skips preprocessing to exercise conflict analysis directly.
No performance score is inferred from this correctness suite.
"""
import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import random
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FLAGS = ['-std=c++17', '-Wall', '-Wextra', '-Wpedantic', '-Werror']
SAN = ['-O1', '-g', '-fsanitize=address,undefined',
       '-fno-sanitize-recover=all', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
DRIVER = '''#include "solver.h"
#include <cstdlib>
int main( int argc, char **argv ) {
    if ( argc != 3 ) return 1;
    Solver solver{};
    int result = solver.parse(argv[1]);
    if ( result == 0 ) {
        if ( atoi(argv[2]) != 0 ) solver.preprocessingDone = true;
        result = solver.solve();
    }
    if ( result == 10 ) {
        printf( "SATISFIABLE\\n" );
        solver.printModel();
    } else if ( result == 20 ) printf( "UNSATISFIABLE\\n" );
    printf( "TEST_COUNTERS %llu %llu %llu\\n",
        (unsigned long long)solver.conflicts,
        (unsigned long long)solver.reductionRuns,
        (unsigned long long)solver.restarts );
    return result;
}
'''


def compile_binary(output, source, sanitize):
    flags = SAN if sanitize else ['-O3', '-DNDEBUG']
    sources = ['solver.cpp', 'preprocess.cpp', 'lcm.cpp']
    # This fixture includes the preprocessing translation unit to check its bounds.
    if source.name == 'preprocess_policy.cpp':
        sources.remove('preprocess.cpp')
    subprocess.run(['g++', *FLAGS, *flags, '-I', str(ROOT),
                    *[str(ROOT / p) for p in sources],
                    str(source), '-o', str(output)], check=True)


def write_cnf(path, n, clauses):
    path.write_text(f'p cnf {n} {len(clauses)}\n' + ''.join(
        ' '.join(map(str, c)) + ' 0\n' for c in clauses))


def brute(n, clauses):
    return any(all(any(values[abs(lit) - 1] == (lit > 0) for lit in c)
                   for c in clauses)
               for values in itertools.product((False, True), repeat=n))


def verify_model(output, n, clauses):
    lines = output.splitlines()
    model = list(map(int, lines[lines.index('SATISFIABLE') + 1].split()))
    assert len(model) == n + 1 and model[-1] == 0, model
    values = {abs(lit): lit > 0 for lit in model[:-1]}
    assert set(values) == set(range(1, n + 1)), model
    assert all(any(values[abs(lit)] == (lit > 0) for lit in c) for c in clauses), output


def run(binary, cnf, env, args=()):
    result = subprocess.run([str(binary), str(cnf), *args], env=env,
                            text=True, capture_output=True, timeout=45)
    output = result.stdout + result.stderr
    assert result.returncode in (10, 20), (binary, result.returncode, output[-4000:])
    assert not re.search(r'AddressSanitizer|LeakSanitizer|runtime error:', output), output
    return result


def pigeonhole(pigeons, holes):
    rows = [[p * holes + h + 1 for h in range(holes)] for p in range(pigeons)]
    for h in range(holes):
        for a in range(pigeons):
            for b in range(a):
                rows.append([-(a * holes + h + 1), -(b * holes + h + 1)])
    return pigeons * holes, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--build-dir', type=Path, required=True)
    args = parser.parse_args()
    work = args.build_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    (work / 'driver.cpp').write_text(DRIVER)
    env = dict(os.environ, UATU_PRINT_MODEL='1', UATU_TIMEOUT_SEC='40',
               ASAN_OPTIONS=os.environ.get('ASAN_OPTIONS', 'detect_leaks=1:halt_on_error=1:abort_on_error=1'),
               UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
    binaries = []
    for name, sanitize in [('release', False), ('sanitized', True)]:
        binary = work / name
        compile_binary(binary, work / 'driver.cpp', sanitize)
        binaries.append(binary)
    for source in sorted((ROOT / 'tests').glob('*_policy.cpp')):
        binary = work / source.stem
        compile_binary(binary, source, True)
        subprocess.run([str(binary)], env=env, check=True, timeout=45)
    cases = [(0, []), (0, [[]]), (1, [[1]]), (1, [[1], [-1]]),
             (2, [[1, 1], [-1, 2]]), (2, [[1, -1], [-2, -2]]),
             (3, [[1, 2], [-1, 2, 3], [-2, 3], [-3, 1]]),
             (2, [[1, 2], [1, -2], [-1, 2], [-1, -2]])]
    rng = random.Random(4212026)
    for _ in range(256):
        n = rng.randint(3, 10)
        clauses = []
        for _ in range(rng.randint(n, 6 * n)):
            width = rng.choice((1, 2, 3, 3, 4))
            row = [rng.choice((-1, 1)) * rng.randint(1, n) for _ in range(width)]
            clauses.append(row)
        cases.append((n, clauses))
    small_count = len(cases)
    for _ in range(40):
        n = rng.randint(70, 150)
        clauses = [[v * rng.choice((-1, 1)) for v in rng.sample(range(1, n + 1), 3)]
                   for _ in range(int(n * rng.uniform(3.9, 4.5)))]
        cases.append((n, clauses))
    for holes in (4, 5, 6, 7, 8):
        cases.append(pigeonhole(holes + 1, holes))
    cnf = work / 'case.cnf'
    counters = [0, 0, 0]
    executions = 0
    for index, (n, clauses) in enumerate(cases):
        write_cnf(cnf, n, clauses)
        expected = brute(n, clauses) if index < small_count else None
        reference = run(args.reference.resolve(), cnf, env)
        if expected is not None:
            assert (reference.returncode == 10) == expected
        for binary in binaries:
            for mode in ('0', '1'):
                result = run(binary, cnf, env, (mode,))
                assert result.returncode == reference.returncode, (index, mode, result.stdout)
                if result.returncode == 10:
                    verify_model(result.stdout, n, clauses)
                matched = re.search(r'TEST_COUNTERS (\d+) (\d+) (\d+)', result.stdout)
                for j, value in enumerate(matched.groups()):
                    counters[j] += int(value)
                executions += 1
        if index % 50 == 0:
            print(f'Checked {index + 1}/{len(cases)} formulas', flush=True)
    assert counters[1] > 0 and counters[2] > 0, counters
    summary = dict(all_passed=True, seed=4212026, formulas=len(cases),
                   exhaustive_oracle_formulas=small_count, solver_executions=executions,
                   builds=['release', 'ASan+UBSan'], preprocessing=['enabled', 'skipped by test driver'],
                   leak_checking='detect_leaks=0' not in env['ASAN_OPTIONS'],
                   total_conflicts=counters[0], total_reductions=counters[1], total_restarts=counters[2],
                   reference_commit='084d7375975408a06a1397cc4bc645a73b97fa65',
                   policy_tests=[p.name for p in sorted((ROOT / 'tests').glob('*_policy.cpp'))])
    files = ['solver.h', 'solver.cpp', 'preprocess.cpp', 'lcm.cpp', 'main.cpp',
             'tests/regression.py', *['tests/' + name for name in summary['policy_tests']]]
    summary['source_sha256'] = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files}
    (work / 'regression.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    main()
