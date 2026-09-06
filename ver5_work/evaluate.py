import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

TIMEOUT = 1000
MEMORY = 12 * 1024**3


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4*1024**2), b''):
            h.update(block)
    return h.hexdigest()


def load_manifest():
    paths = list(Path('prepared').rglob('manifest.json'))
    assert len(paths) == 1, paths
    rows = json.loads(paths[0].read_text())
    assert isinstance(rows, list) and len(rows) == 100
    assert {int(row['index']) for row in rows} == set(range(100))
    assert len({row['hash'] for row in rows}) == 100
    assert all(re.fullmatch('[0-9a-f]{32}', row['hash']) for row in rows)
    return sorted(rows, key=lambda row: int(row['index']))


def tokens(stream):
    pending = b''
    while True:
        block = stream.read(65536)
        if not block:
            if pending:
                yield pending
            break
        data = pending + block
        parts = data.split()
        if data[-1:].isspace():
            pending = b''
        elif parts:
            pending = parts.pop()
        else:
            pending = data
        yield from parts


def verify_model(cnf, output, solver):
    with Path(cnf).open('rb') as source:
        for line in source:
            if line.lstrip().startswith(b'p '):
                fields = line.split()
                assert fields[:2] == [b'p', b'cnf']
                variables = int(fields[2])
                count = int(fields[3])
                break
        else:
            raise AssertionError('missing CNF header')
    assignment = bytearray(variables + 1)
    with Path(output).open('rb') as source:
        for line in source:
            if line.strip() in (b'SAT', b'SATISFIABLE'):
                break
        else:
            raise AssertionError('missing model status')
        found_end = False
        for token in tokens(source):
            literal = int(token)
            if literal == 0:
                found_end = True
                break
            variable = abs(literal)
            assert 1 <= variable <= variables and assignment[variable] == 0, 'invalid or duplicate model variable'
            assignment[variable] = 2 if literal > 0 else 1
        assert found_end and assignment[1:].count(0) == 0, 'incomplete model'
    checked = 0
    satisfied = False
    unfinished = False
    with Path(cnf).open('rb') as source:
        for line in source:
            stripped = line.lstrip()
            if not stripped or stripped.startswith((b'c', b'p', b'%')):
                continue
            for token in line.split():
                literal = int(token)
                if literal == 0:
                    assert satisfied, f'model falsifies clause {checked}'
                    checked += 1
                    satisfied = False
                    unfinished = False
                else:
                    assert 1 <= abs(literal) <= variables
                    satisfied |= assignment[abs(literal)] == (2 if literal > 0 else 1)
                    unfinished = True
    assert not unfinished and checked == count, 'incomplete original CNF verification'
    return checked


def run_solver(name, row):
    environment = {k: v for k, v in os.environ.items() if not k.startswith('UATU_')}
    environment.update(UATU_TIMEOUT_SEC='1000', UATU_PRINT_MODEL='1')
    binary = Path('tools') / name
    command = [str(binary.resolve())]
    model_file = Path('result/minisat.model')
    if name == 'minisat':
        command.extend(['-verb=0', 'input.cnf', str(model_file)])
    else:
        command.append('input.cnf')
    available = sorted(os.sched_getaffinity(0))
    command = ['prlimit', f'--as={MEMORY}:{MEMORY}', '--', 'taskset', '-c', str(available[0]), *command]
    path = Path('result') / (name + '.log')
    started = time.monotonic()
    expired = False
    with path.open('wb') as output:
        process = subprocess.Popen(command, env=environment, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            process.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            expired = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
    elapsed = time.monotonic() - started
    with path.open('rb') as source:
        text = source.read(4*1024**2).decode(errors='replace')
    # Counters are at the end even when the SAT model is very large.
    with path.open('rb') as source:
        source.seek(max(0, path.stat().st_size - 65536))
        tail = source.read().decode(errors='replace')
    combined = text + '\n' + tail
    counters = {key.strip(): int(value) for key, value in re.findall(r'^([A-Za-z ]+)\s*:\s*(-?\d+)\s*$', tail, re.M)}
    status = 'unknown'
    answer = None
    if expired or elapsed > TIMEOUT:
        status = 'timeout'
    elif process.returncode < 0:
        status = 'crash'
    elif re.search(r'internal error:|PARSE ERROR|runtime error:|AddressSanitizer|terminate called', combined):
        status = 'internal_error'
    elif 'OUT OF MEMORY' in combined or 'RESOURCE LIMIT' in combined or 'Out of memory' in combined:
        status = 'memory_limit'
    elif process.returncode in (10, 20):
        answer = 'sat' if process.returncode == 10 else 'unsat'
        wanted = 'SATISFIABLE' if answer == 'sat' else 'UNSATISFIABLE'
        if wanted not in text.splitlines():
            status = 'bad_output'
        elif row.get('expected') in ('sat', 'unsat') and answer != row['expected']:
            status = 'wrong_answer'
        elif answer == 'sat':
            try:
                verified_clauses = verify_model('input.cnf', model_file if name == 'minisat' else path, name)
                status = 'solved'
            except (AssertionError, ValueError, OSError) as error:
                status = 'invalid_model'
                (Path('result') / (name + '-model-error.txt')).write_text(str(error))
        elif row.get('expected') == 'unsat':
            status = 'solved'
        else:
            status = 'unsat_unverified'
    elif process.returncode != 0:
        status = 'error'
    elif elapsed >= TIMEOUT - 1:
        status = 'timeout'
    if any(value < 0 for value in counters.values()):
        status = 'negative_counter'
    return {'solver': name, 'index': int(row['index']), 'hash': row['hash'], 'expected': row.get('expected'),
            'status': status, 'answer': answer, 'wall_sec': elapsed, 'exit_code': process.returncode,
            'external_timeout': expired, 'memory_limit_bytes': MEMORY, 'affinity_cpu': available[0],
            'counters': counters, 'log_sha256': digest(path), 'binary_sha256': digest(binary),
            'model_checked': status == 'solved' and answer == 'sat'}


def pair(index):
    manifest = load_manifest()
    row = manifest[index]
    Path('result').mkdir(exist_ok=True)
    build = json.loads(Path('tools/build.json').read_text())
    for solver in ('ver5', 'minisat'):
        assert digest(Path('tools') / solver) == build['binaries'][solver]
        (Path('tools') / solver).chmod(0o755)
    url = row['url'].replace('http://', 'https://', 1)
    subprocess.run(['curl', '-fL', '--retry', '3', '--connect-timeout', '30', '--max-time', '600', url, '-o', 'input.xz'], check=True)
    with Path('input.cnf').open('wb') as output:
        subprocess.run(['xz', '-dc', 'input.xz'], stdout=output, check=True)
    Path('input.xz').unlink()
    cnf_hash = digest('input.cnf')
    order = ('minisat', 'ver5') if index % 2 == 0 else ('ver5', 'minisat')
    rows = []
    for solver in order:
        rows.append(run_solver(solver, row))
        Path('result/partial.json').write_text(json.dumps(rows, indent=2) + '\n')
    answers = {r['answer'] for r in rows if r['answer'] is not None and r['status'] in ('solved', 'unsat_unverified')}
    if len(answers) > 1:
        for record in rows:
            record['status'] = 'answer_disagreement'
    if len(answers) == 1 and all(r['answer'] == 'unsat' for r in rows):
        for record in rows:
            if record['status'] == 'unsat_unverified':
                record['status'] = 'solved'
                record['verification'] = 'independent-solver agreement'
    cpu = subprocess.check_output(['lscpu'], text=True)
    result = {'index': index, 'benchmark': row, 'cnf_sha256': cnf_hash,
              'source_manifest_sha256': build['source_manifest_sha256'], 'cpu': cpu, 'rows': rows}
    Path('result/result.json').write_text(json.dumps(result, indent=2) + '\n')
    print('PAIR_RESULT=' + json.dumps(result), flush=True)


def aggregate():
    paths = sorted(Path('collected').rglob('result.json'))
    results = [json.loads(p.read_text()) for p in paths]
    assert len(results) == 100, f'expected exactly 100 pairs, found {len(results)}'
    assert {r['index'] for r in results} == set(range(100))
    assert len({r['benchmark']['hash'] for r in results}) == 100
    sources = {r['source_manifest_sha256'] for r in results}
    assert len(sources) == 1, 'mixed candidate versions'
    manifest = load_manifest()
    for result in results:
        assert result['benchmark']['hash'] == manifest[result['index']]['hash']
        assert {r['solver'] for r in result['rows']} == {'ver5', 'minisat'}
    summary = {}
    bugs = {'crash', 'internal_error', 'bad_output', 'wrong_answer', 'invalid_model', 'error', 'negative_counter', 'answer_disagreement'}
    for solver in ('minisat', 'ver5'):
        rows = [r for pair in results for r in pair['rows'] if r['solver'] == solver]
        solved = [r for r in rows if r['status'] == 'solved']
        summary[solver] = {'benchmarks': len(rows), 'solved': len(solved),
            'sat': sum(r['answer'] == 'sat' for r in solved), 'unsat': sum(r['answer'] == 'unsat' for r in solved),
            'par2': sum(r['wall_sec'] if r['status'] == 'solved' else 2*TIMEOUT for r in rows)/len(rows),
            'timeouts': sum(r['status'] == 'timeout' for r in rows),
            'memory_limits': sum(r['status'] == 'memory_limit' for r in rows),
            'other_unsolved': sum(r['status'] in ('unknown', 'unsat_unverified') for r in rows),
            'bugs': [r for r in rows if r['status'] in bugs]}
    verified = not summary['ver5']['bugs']
    summary.update(timeout_sec=TIMEOUT, penalty_sec=2*TIMEOUT, source_manifest_sha256=next(iter(sources)),
                   all_100_present=True, code_validation_passed=verified,
                   par2_ratio_minisat_over_ver5=summary['minisat']['par2']/summary['ver5']['par2'],
                   beats_minisat=verified and summary['ver5']['par2'] < summary['minisat']['par2'])
    Path('summary').mkdir(exist_ok=True)
    Path('summary/summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    Path('summary/raw.json').write_text(json.dumps(results, indent=2) + '\n')
    print('FINAL_PAR2_BEGIN\n' + json.dumps(summary, indent=2) + '\nFINAL_PAR2_END', flush=True)
    if not verified:
        raise RuntimeError('Ver5 failed code validation; source publication is blocked')


if __name__ == '__main__':
    if sys.argv[1] == 'prepare':
        rows = load_manifest()
        print('REUSED_UNFILTERED_RANDOM_SAMPLE', len(rows), 'unique benchmarks')
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            stream.write('indices=' + json.dumps(list(range(100))) + '\n')
    elif sys.argv[1] == 'pair':
        pair(int(sys.argv[2]))
    elif sys.argv[1] == 'aggregate':
        aggregate()
    else:
        raise SystemExit('unknown mode')
