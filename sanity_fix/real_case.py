import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

index = int(sys.argv[1])
row = json.loads(Path('prepared/manifest.json').read_text())[index]
assert row['index'] == index and index in (33, 34, 36, 39, 70)
expected_sha = {33: '163084ee7120c0c97d488dedebb79f29e7e7aea4da758a068b12cd055a755fcc',
                34: '7aada02dc300ce6db773dbab34f115969174896a161b6d28ce37f5743e8fff4f',
                36: '01afee17b6fe1a16199f2632694e66bea2630db2a8298e1fda89dabb1a6d75ea',
                39: '4a92ea0f399a291eb8fcbd2cdd6a0e2aadbdc5a7e14bdabf73f21af6dc4d42ab'}
Path('work').mkdir(exist_ok=True)
Path('evidence').mkdir(exist_ok=True)
archive = Path('work/input.xz')
cnf = Path('work/input.cnf')
subprocess.run(['curl', '-fL', '--retry', '3', '--connect-timeout', '30', '--max-time', '400', row['url'], '-o', str(archive)], check=True)
with cnf.open('wb') as output:
    subprocess.run(['xz', '-dc', str(archive)], stdout=output, check=True)
archive.unlink()
digest = hashlib.sha256()
with cnf.open('rb') as source:
    for chunk in iter(lambda: source.read(4 * 1024**2), b''):
        digest.update(chunk)
if index in expected_sha:
    assert digest.hexdigest() == expected_sha[index]

env = {key: value for key, value in os.environ.items() if not key.startswith('UATU_')}
env.update(UATU_TIMEOUT_SEC='90', UATU_PRINT_MODEL='1', UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
flags = ['-std=c++17', '-O2', '-g', '-Wall', '-Wextra', '-Wpedantic', '-Werror']
sources = ['cpu/ver_4/solver.cpp', 'cpu/ver_4/main.cpp']
subprocess.run(['g++', *flags, '-fsanitize=undefined', '-fno-sanitize-recover=all', *sources, '-o', 'work/ubsan'], check=True)
subprocess.run(['g++', *flags, *sources, '-o', 'work/release'], check=True)


def execute(name, binary, timeout, memory=True):
    command = [binary, str(cnf)]
    if memory:
        command = ['prlimit', '--as=12884901888:12884901888', '--', *command]
    started = time.monotonic()
    path = Path('evidence') / (name + '.log')
    expired = False
    with path.open('wb') as output:
        process = subprocess.Popen(command, env=env, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            expired = True
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    text = path.read_text(errors='replace')
    assert not re.search(r'runtime error:|AddressSanitizer|internal error:|PARSE ERROR|terminate called|std::bad_alloc', text), text[-8000:]
    if not expired:
        assert process.returncode in (0, 10, 20), (process.returncode, text[-8000:])
        if process.returncode == 0:
            assert 'UNSOLVED' in text
        if process.returncode == 20:
            assert row['expected'] != 'sat'
        if process.returncode == 10:
            assert row['expected'] != 'unsat'
            lines = text.splitlines()
            literals = [int(x) for x in lines[lines.index('SATISFIABLE') + 1].split()]
            assert literals[-1] == 0
            model = {abs(lit): lit > 0 for lit in literals[:-1]}
            satisfied = False
            with cnf.open() as source:
                for line in source:
                    if not line.strip() or line.lstrip().startswith(('c', 'p')):
                        continue
                    for token in line.split():
                        literal = int(token)
                        if literal:
                            satisfied |= model.get(abs(literal)) == (literal > 0)
                        else:
                            assert satisfied, 'invalid SAT model'
                            satisfied = False
    counters = {name.strip(): int(value) for name, value in re.findall(r'^([A-Za-z ]+)\s*:\s*(-?\d+)\s*$', text, re.M)}
    assert all(value >= 0 for value in counters.values()), counters
    return {'name': name, 'wall_sec': time.monotonic() - started, 'exit': process.returncode,
            'external_timeout': expired, 'out_of_memory': 'OUT OF MEMORY' in text,
            'counters': counters, 'log_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

results = []
if index in (33, 36):
    # Actual large input, same 12 GiB address-space cap; never inject allocations.
    results.append(execute('original-input-release', 'work/release', 150))
else:
    # Diagnostic smoke run, not a new 1000-second performance measurement.
    results.append(execute('original-input-ubsan', 'work/ubsan', 100))
    driver = r'''#include "solver.h"
#include <inttypes.h>
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    Solver s{};
    int result = s.parse(argv[1]);
    if (result != 0) return 3;
    s.unitPropagations = INT_MAX - 1;
    result = s.solve();
    printf("BOUNDARY_COUNTER=%" PRIu64 "\n", s.unitPropagations);
    if (s.unitPropagations <= uint64_t(INT_MAX)) return 4;
    printf("UNSOLVED\n");
    return result == 30 || result == 10 || result == 20 ? 0 : 5;
}
'''
    Path('work/boundary.cpp').write_text(driver)
    subprocess.run(['g++', *flags, '-fsanitize=undefined', '-fno-sanitize-recover=all', '-Icpu/ver_4',
                    'cpu/ver_4/solver.cpp', 'work/boundary.cpp', '-o', 'work/boundary'], check=True)
    env['UATU_TIMEOUT_SEC'] = '5'
    results.append(execute('injected-boundary-ubsan', 'work/boundary', 30))
    assert not results[-1]['external_timeout']

summary = {'index': index, 'hash': row['hash'], 'filename': row['filename'],
           'cnf_sha256': digest.hexdigest(), 'cnf_bytes': cnf.stat().st_size,
           'results': results, 'all_checks_passed': True,
           'scope': 'targeted regression, not a 100-case or PAR-2 rerun'}
Path('evidence/result.json').write_text(json.dumps(summary, indent=2) + '\n')
print('ORIGINAL_CASE_RECHECK=' + json.dumps(summary, sort_keys=True), flush=True)
