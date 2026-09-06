import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

TIMEOUT = 1000.0
MEMORY = 12 * 1024**3
index = int(sys.argv[1])
manifest = json.loads(Path('prepared/manifest.json').read_text())
assert len(manifest) == 100
row = manifest[index]
assert row['index'] == index
Path('work').mkdir(exist_ok=True)
Path('result').mkdir(exist_ok=True)
subprocess.run(['curl', '-fL', '--retry', '4', '--connect-timeout', '30', '--max-time', '450', row['url'], '-o', 'work/input.cnf.xz'], check=True)
with open('work/input.cnf', 'wb') as output:
    subprocess.run(['xz', '-dc', 'work/input.cnf.xz'], stdout=output, check=True)
Path('work/input.cnf.xz').unlink()
cnf = Path('work/input.cnf')
digest = hashlib.sha256()
with cnf.open('rb') as source:
    for chunk in iter(lambda: source.read(4*1024**2), b''):
        digest.update(chunk)


def integers(source):
    pending = b''
    while True:
        chunk = source.read(65536)
        if not chunk:
            if pending: yield int(pending)
            return
        data = pending + chunk
        fields = data.split()
        if data[-1:] not in b' \t\r\n\v\f':
            pending = fields.pop() if fields else data
        else:
            pending = b''
        for field in fields:
            yield int(field)


def verify_model(model_path, solver):
    variables = None
    with cnf.open('rb') as source:
        for line in source:
            if line.lstrip().startswith(b'p '):
                fields = line.split()
                assert fields[:2] == [b'p', b'cnf']
                variables = int(fields[2])
                break
    assert variables is not None
    assignment = bytearray(variables+1)
    with model_path.open('rb') as source:
        for line in source:
            if line.strip() == (b'SAT' if solver == 'minisat' else b'SATISFIABLE'):
                break
        else:
            raise RuntimeError('missing model status')
        ended = False
        for literal in integers(source):
            if literal == 0:
                ended = True
                break
            variable = abs(literal)
            assert 1 <= variable <= variables, 'model variable out of range'
            value = 1 if literal > 0 else 2
            assert assignment[variable] in (0, value), 'contradictory model'
            assignment[variable] = value
        assert ended, 'unterminated model'
    satisfied = False
    terminated = True
    clause_count = 0
    with cnf.open('rb') as source:
        for line in source:
            stripped = line.lstrip()
            if not stripped or stripped[:1] in (b'c', b'p', b'%'): continue
            for token in stripped.split():
                literal = int(token)
                if literal == 0:
                    assert satisfied, 'SAT model falsifies original clause'
                    satisfied = False
                    terminated = True
                    clause_count += 1
                else:
                    assert 1 <= abs(literal) <= variables
                    satisfied |= assignment[abs(literal)] == (1 if literal > 0 else 2)
                    terminated = False
    assert terminated
    return {'valid': True, 'checked_clauses': clause_count}


def short_lines(path):
    # Skip huge model lines while preserving diagnostics and statistics.
    lines = []
    with path.open('rb') as source:
        oversized = False
        while True:
            fragment = source.readline(8192)
            if not fragment: break
            if oversized:
                if fragment.endswith(b'\n'): oversized = False
                continue
            if not fragment.endswith(b'\n') and len(fragment) == 8192:
                oversized = True
                continue
            text = fragment.decode('utf-8', 'replace').strip()
            if len(text) < 4096 and not re.match(r'^-?\d+(?: +-?\d+)+ *0$', text): lines.append(text)
    return lines


def run(solver):
    env = {key: value for key, value in os.environ.items() if not key.startswith('UATU_')}
    env.update(UATU_TIMEOUT_SEC='1000', UATU_PRINT_MODEL='1')
    cpu = min(os.sched_getaffinity(0))
    model_path = Path('work/minisat.model')
    binary = Path('cpu/ver_5/obj/uatu_solver') if solver == 'ver5' else Path('/usr/bin/minisat')
    executable_sha = hashlib.sha256(binary.read_bytes()).hexdigest()
    args = [str(binary), str(cnf)]
    if solver == 'minisat': args += [str(model_path)]
    args = ['prlimit', f'--as={MEMORY}:{MEMORY}', '--', 'taskset', '-c', str(cpu), *args]
    timing = Path('work') / (solver+'.time')
    args = ['/usr/bin/time', '-q', '-f', '%e,%U,%S,%M', '-o', str(timing), *args]
    output_path = Path('work')/(solver+'.log')
    expired = False
    started = time.monotonic()
    with output_path.open('wb') as output:
        process = subprocess.Popen(args, env=env, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            process.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            expired = True
            try: os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError: pass
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                process.wait()
    elapsed = time.monotonic() - started
    lines = short_lines(output_path)
    diagnostic = '\n'.join(lines)
    status = 'unknown'
    invalid = False
    if expired or elapsed > TIMEOUT:
        status = 'timeout'
    elif process.returncode not in (0, 10, 20):
        status = 'error'
        invalid = True
    elif re.search(r'internal error|configuration error|parse error|sanitizer|runtime error:|terminate called', diagnostic, re.I):
        status = 'error'
        invalid = True
    elif 'SATISFIABLE' in lines and process.returncode == 10:
        status = 'sat'
    elif 'UNSATISFIABLE' in lines and process.returncode == 20:
        status = 'unsat'
    elif re.search(r'out of memory|resource limit|indeterminate.*memory', diagnostic, re.I):
        status = 'memory_limit'
    elif 'UNSOLVED' in lines or 'INDETERMINATE' in lines:
        status = 'unknown'
    else:
        status = 'error'
        invalid = True
    model_check = None
    if status == 'sat':
        try:
            model_check = verify_model(model_path if solver == 'minisat' else output_path, solver)
        except Exception as error:
            status = 'wrong_model'
            invalid = True
            model_check = {'valid': False, 'error': str(error)}
    if status in ('sat', 'unsat') and row['expected'] in ('sat', 'unsat') and status != row['expected']:
        status = 'wrong_answer'
        invalid = True
    counters = {}
    if solver == 'ver5':
        for line in lines:
            match = re.match(r'^([A-Za-z -]+)\s*:\s*(-?\d+)\s*$', line)
            if match: counters[match.group(1).strip()] = int(match.group(2))
        if any(value < 0 for value in counters.values()):
            invalid = True
            status = 'error'
    (Path('result')/(solver+'.log')).write_text(diagnostic+'\n')
    measurement = {'solver': solver, 'status': status, 'wall_sec': elapsed,
                   'exit_code': process.returncode, 'external_timeout': expired,
                   'invalid': invalid, 'model_check': model_check, 'counters': counters,
                   'binary_sha256': executable_sha,
                   'time_statistics': timing.read_text() if timing.exists() else None}
    print('MEASUREMENT='+json.dumps(measurement), flush=True)
    return measurement

order = ['ver5', 'minisat'] if index % 2 == 0 else ['minisat', 'ver5']
measurements = [run(solver) for solver in order]
answers = {m['status'] for m in measurements if m['status'] in ('sat', 'unsat')}
if answers == {'sat', 'unsat'}:
    for m in measurements: m['invalid'] = True
unverified_unsat = row['expected'] == 'unknown' and any(m['solver']=='ver5' and m['status']=='unsat' for m in measurements) and not any(m['solver']=='minisat' and m['status']=='unsat' for m in measurements)
result = {'index': index, 'hash': row['hash'], 'filename': row['filename'], 'expected': row['expected'],
          'cnf_sha256': digest.hexdigest(), 'cnf_bytes': cnf.stat().st_size,
          'timeout_sec': TIMEOUT, 'memory_bytes': MEMORY, 'execution_order': order,
          'source_sha256': Path('source.sha256').read_text(), 'cpu': Path('/proc/cpuinfo').read_text().split('\n\n')[0],
          'minisat_version': subprocess.check_output(['dpkg-query', '-W', '-f=${Version}', 'minisat'], text=True),
          'measurements': measurements, 'unverified_unsat': unverified_unsat,
          'all_checks_passed': not unverified_unsat and not any(m['invalid'] for m in measurements)}
Path('result/result.json').write_text(json.dumps(result, indent=2)+'\n')
print('CASE_COMPLETE='+json.dumps({'index': index, 'hash': row['hash'], 'passed': result['all_checks_passed']}), flush=True)
cnf.unlink()
