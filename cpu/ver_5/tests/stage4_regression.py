#!/usr/bin/env python3
"""Correctness tests for preprocessing, reconstruction, and complete SAT solving."""
import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import random
import re
import subprocess
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SEED = 20260912
SANITIZERS = ['-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
              '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']


def write_cnf(path, variables, clauses):
    path.write_text(f'p cnf {variables} {len(clauses)}\n' + ''.join(
        ' '.join(map(str, clause)) + ' 0\n' for clause in clauses))


def truth_mask(variables, clauses):
    """Truth table using bitsets independent of solver propagation or elimination."""
    full = (1 << (1 << variables)) - 1
    literal_truth = {}
    for variable in range(1, variables + 1):
        value = sum(1 << mask for mask in range(1 << variables)
                    if mask & (1 << (variable - 1)))
        literal_truth[variable] = value
        literal_truth[-variable] = full ^ value
    result = full
    for clause in clauses:
        satisfied = 0
        for literal in clause:
            satisfied |= literal_truth[literal]
        result &= satisfied
    return result


def verify_model(text, variables, clauses, minisat=False):
    lines = text.splitlines()
    marker = 'SAT' if minisat else 'SATISFIABLE'
    assert marker in lines, text[-2000:]
    model = [int(value) for value in lines[lines.index(marker) + 1].split()]
    assert model and model[-1] == 0
    assignment = {}
    for literal in model[:-1]:
        assert 1 <= abs(literal) <= variables and abs(literal) not in assignment
        assignment[abs(literal)] = literal > 0
    assert len(assignment) == variables, (variables, assignment)
    for clause in clauses:
        assert any(assignment[abs(literal)] == (literal > 0) for literal in clause), clause


def small_cases():
    cases = [('empty_formula', 0, []), ('empty_clause', 0, [[]]),
             ('unused_variables', 8, []), ('empty_after_nonempty', 2, [[1, 2], []]),
             ('pure_variables', 5, [[1, 2], [-3, 4], [2, -3, 5]]),
             ('tautological_resolvents', 4, [[1, 2], [-1, -2], [1, 3], [-1, 4]]),
             ('resolvent_unit', 2, [[1, 2], [-1, 2]]),
             ('resolvent_conflict', 2, [[1, 2], [-1, 2], [1, -2], [-1, -2]]),
             ('SSR_positive', 4, [[1, 2], [-1, 2, 3], [-2, 4]]),
             ('SSR_negative', 4, [[-1, 2], [1, 2, 3], [-2, 4]]),
             ('duplicates_tautologies_units', 5, [[1, 1, 2], [1, -1, 3], [1, 2], [-2], [-3, 4], [4, 5]]),
             ('root_reconstruction', 6, [[1], [-1, 2], [-2, 3], [-3, 4, 5], [-4, 6], [-5, -6]]),
             ('subsumption_chain', 5, [[1, 2], [1, 2, 3], [1, 2, 3, 4], [-1, 5], [-2, -5]])]
    atoms = [[x for x in (a, b) if x] for a in (0, -1, 1) for b in (0, -2, 2) if a or b]
    for mask in range(1 << len(atoms)):
        cases.append((f'exhaustive_two_variable_{mask:03}', 2,
                      [row[:] for index, row in enumerate(atoms) if mask & (1 << index)]))
    rng = random.Random(SEED)
    for index in range(500):
        n = rng.randint(3, 10)
        clauses = []
        for _ in range(rng.randint(n, 6 * n)):
            count = rng.choices((1, 2, 3, 4), (1, 5, 7, 2))[0]
            clause = [rng.choice((-1, 1)) * rng.randint(1, n) for _ in range(count)]
            clauses.append(clause)
            if rng.randrange(12) == 0:
                clauses.append(clause[:])
        cases.append((f'random_small_{index:03}', n, clauses))
    for index in range(100):
        n = rng.randint(4, 10)
        permutation = rng.sample(range(1, n + 1), n)
        permutation = [x * rng.choice((-1, 1)) for x in permutation]
        clauses = []
        for i in range(n - 1):
            clauses.extend([[permutation[i], -permutation[i + 1]], [-permutation[i], permutation[i + 1]]])
        clauses.extend([[permutation[0], permutation[-1]]])
        if index % 3 == 0:
            clauses.append([-permutation[0], -permutation[-1]])
        rng.shuffle(clauses)
        cases.append((f'restoration_chain_{index:03}', n, clauses))
    return cases


def medium_cases():
    rng = random.Random(SEED + 1)
    cases = []
    for index in range(24):
        n = rng.randint(30, 70)
        clauses = []
        planted = rng.getrandbits(n) if index % 2 == 0 else None
        for _ in range(round(n * (4.27 if planted is None else 5.0))):
            selected = rng.sample(range(1, n + 1), 3)
            clause = [v * rng.choice((-1, 1)) for v in selected]
            if planted is not None and not any(bool(planted & (1 << (abs(v) - 1))) == (v > 0) for v in clause):
                clause[0] = -clause[0]
            clauses.append(clause)
        cases.append((f'medium_random_{index:02}', n, clauses))
    for pigeons, holes in ((5, 4), (6, 5), (7, 6), (9, 8)):
        clauses = [[p * holes + h + 1 for h in range(holes)] for p in range(pigeons)]
        for h in range(holes):
            for first in range(pigeons):
                for second in range(first + 1, pigeons):
                    clauses.append([-(first * holes + h + 1), -(second * holes + h + 1)])
        cases.append((f'pigeonhole_{pigeons}_{holes}', pigeons * holes, clauses))
    # XOR cycles have known parity, but the reference solver is still run.
    for parity in (0, 1):
        n = 30
        clauses = []
        for first in range(1, n + 1):
            second = first % n + 1
            rhs = parity if first == n else 0
            clauses.extend([[first, second], [-first, -second]] if rhs else [[first, -second], [-first, second]])
        cases.append((f'xor_cycle_{parity}', n, clauses))
    return cases


def execute(args, env, timeout=30):
    result = subprocess.run([str(x) for x in args], env=env, capture_output=True, text=True, timeout=timeout)
    combined = result.stdout + result.stderr
    assert not re.search(r'AddressSanitizer|LeakSanitizer|runtime error:', combined), combined[-5000:]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--minisat', type=Path, required=True)
    parser.add_argument('--no-leak-check', action='store_true')
    args = parser.parse_args()
    out = args.work_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith('UATU_')}
    env.update(UATU_PRINT_MODEL='1', UATU_TIMEOUT_SEC='20',
               ASAN_OPTIONS=f'detect_leaks={int(not args.no_leak_check)}:halt_on_error=1:abort_on_error=1',
               UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
    sources = [ROOT / x for x in ('solver.cpp', 'preprocess.cpp', 'vivify.cpp')]
    provenance_sources = sources + [ROOT / 'solver.h', ROOT / 'main.cpp']
    source_sha256 = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in provenance_sources if p.exists()}
    builds = {'release': out / 'release', 'ASan_UBSan': out / 'sanitized'}
    flags = ['g++', '-std=c++17', '-Wall', '-Wextra', '-Wpedantic', '-Werror', '-I', ROOT]
    subprocess.run([str(x) for x in [*flags, '-O3', '-DNDEBUG', *sources, ROOT / 'main.cpp', '-o', builds['release']]], check=True)
    subprocess.run([str(x) for x in [*flags, *SANITIZERS, *sources, ROOT / 'main.cpp', '-o', builds['ASan_UBSan']]], check=True)
    subprocess.run([str(x) for x in [*flags, *SANITIZERS, *sources, HERE / 'preprocess_semantics.cpp', '-o', out / 'preprocess_semantics']], check=True)
    records = []
    path = out / 'current.cnf'
    small = small_cases()
    medium = medium_cases()
    counters = {key: 0 for key in ('extensions', 'eliminated', 'subsumed', 'strengthened', 'resolvents', 'work')}
    minisat = args.minisat.resolve()
    assert minisat.is_file(), minisat
    start = time.monotonic()
    for index, (name, n, clauses) in enumerate(small + medium):
        write_cnf(path, n, clauses)
        if index < len(small):
            expected = bool(truth_mask(n, clauses))
            oracle = 'exhaustive_truth_table'
        else:
            model = out / 'minisat.model'
            model.unlink(missing_ok=True)
            reference = execute([minisat, '-verb=0', path, model], env)
            assert reference.returncode in (10, 20), (name, reference.stdout, reference.stderr)
            expected = reference.returncode == 10
            if expected:
                verify_model(model.read_text(), n, clauses, minisat=True)
            oracle = 'MiniSAT_2.2.0_simp'
        record = {'name': name, 'variables': n, 'clauses': len(clauses), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                  'expected': 'SAT' if expected else 'UNSAT', 'oracle': oracle, 'builds': {}}
        for build, binary in builds.items():
            run = execute([binary, path], env)
            (out / f'{name}_{build}.log').write_text(run.stdout + run.stderr)
            assert run.returncode == (10 if expected else 20), (name, build, run.returncode, run.stdout, run.stderr)
            if expected:
                verify_model(run.stdout, n, clauses)
            stats = dict(re.findall(r'^([^:\n]+?)\s*:\s*(\d+)\s*$', run.stdout, re.M))
            record['builds'][build] = {'returncode': run.returncode, 'model_checked': expected, 'counters': stats}
        if index < len(small):
            probe = execute([out / 'preprocess_semantics', path], env)
            assert probe.returncode == 0, (name, probe.stdout, probe.stderr)
            check = json.loads(probe.stdout.splitlines()[-1])
            record['preprocess_semantics'] = check
            for key in counters:
                counters[key] += check[key]
        records.append(record)
        if index % 100 == 0:
            print(f'VALIDATED {index + 1}/{len(small) + len(medium)}', flush=True)
        (out / 'checkpoint.json').write_text(json.dumps({'all_passed_so_far': True, 'records': records}, indent=2) + '\n')
    for counter in ('extensions', 'eliminated', 'subsumed', 'strengthened', 'resolvents'):
        assert counters[counter] > 0, counters
    search_probe = next(record for record in records if record['name'] == 'pigeonhole_9_8')
    for build in builds:
        search_stats = search_probe['builds'][build]['counters']
        assert int(search_stats['Vivification Runs']) > 0
        assert int(search_stats['Vivified Clauses']) > 0
        assert int(search_stats['Clause Reductions']) > 0
    summary = {'all_passed': True, 'seed': SEED, 'small_formula_count': len(small), 'medium_formula_count': len(medium),
               'total_formula_count': len(records), 'builds': list(builds), 'timeout_is_not_success': True,
               'SAT_models_checked_against_all_original_clauses': True,
               'leak_checking': not args.no_leak_check,
               'preprocess_all_model_projection_and_extension_counters': counters,
               'source_sha256': source_sha256,
               'elapsed_seconds': time.monotonic() - start, 'records': records}
    (out / 'stage4_regression.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k != 'records'}, indent=2), flush=True)


if __name__ == '__main__':
    main()
