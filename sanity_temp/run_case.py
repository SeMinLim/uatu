import hashlib
import json
import os
import re
import resource
import signal
import subprocess
import sys
import time
from pathlib import Path

TIMEOUT = 1000.0
SANITIZER_TIMEOUT = 30.0
MEMORY_BYTES = 12 * 1024**3


def resident_bytes(pid):
    total = 0
    pending = [pid]
    seen = set()
    while pending:
        item = pending.pop()
        if item in seen:
            continue
        seen.add(item)
        try:
            fields = Path(f'/proc/{item}/statm').read_text().split()
            total += int(fields[1]) * os.sysconf('SC_PAGE_SIZE')
            children = Path(f'/proc/{item}/task/{item}/children').read_text().split()
            pending.extend(int(child) for child in children)
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
    return total


def set_limits():
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def measure(name, command, folder, timeout, sanitizer=False):
    log = folder / f'{name}.log'
    timing = folder / f'{name}.time'
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith('UATU_'):
            environment.pop(key)
    environment['UATU_PRINT_MODEL'] = '1'
    environment['UATU_TIMEOUT_SEC'] = str(timeout)
    if sanitizer:
        environment['ASAN_OPTIONS'] = 'detect_leaks=0:halt_on_error=1:abort_on_error=1'
        environment['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
    started = time.monotonic()
    termination = None
    peak = 0
    with log.open('wb') as output:
        process = subprocess.Popen(
            ['/usr/bin/time', '-q', '-f', '%e,%U,%S,%M,%x', '-o', str(timing)] + command,
            stdout=output, stderr=subprocess.STDOUT, env=environment,
            start_new_session=True, preexec_fn=None if sanitizer else set_limits())
        while True:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                if process.poll() is None:
                    termination = 'timeout'
                break
            if sanitizer:
                current = resident_bytes(process.pid)
                peak = max(peak, current)
                if current > MEMORY_BYTES:
                    termination = 'resource_limit'
                    break
            try:
                process.wait(timeout=min(0.25 if sanitizer else 0.5, remaining))
                break
            except subprocess.TimeoutExpired:
                pass
        if termination:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        code = process.wait()
    observed = time.monotonic() - started
    elapsed = observed
    user_seconds = None
    system_seconds = None
    rss_kb = peak // 1024 if peak else None
    if timing.exists():
        for line in reversed(timing.read_text(errors='replace').splitlines()):
            fields = line.split(',')
            if len(fields) == 5:
                try:
                    elapsed, user_seconds, system_seconds = map(float, fields[:3])
                    rss_kb = int(fields[3])
                    break
                except ValueError:
                    continue
    text = log.read_text(errors='replace')
    diagnostic = None
    if re.search(r'ERROR: AddressSanitizer|SUMMARY: AddressSanitizer|AddressSanitizer:DEADLYSIGNAL|runtime error:|UndefinedBehaviorSanitizer', text):
        diagnostic = 'sanitizer_error'
    elif re.search(r'internal error:|PARSE ERROR|failed to open|failed to seek', text, re.I):
        diagnostic = 'solver_error'
    elif re.search(r'bad_alloc|length_error|out of memory|cannot allocate memory|std::bad_array_new_length', text, re.I):
        diagnostic = 'resource_error'
    if diagnostic:
        status = diagnostic
    elif termination:
        status = termination
    elif code in (10, 20):
        answer = 'sat' if code == 10 else 'unsat'
        required = 'SATISFIABLE' if code == 10 else 'UNSATISFIABLE'
        if required not in {line.strip() for line in text.splitlines()}:
            status = 'malformed_output'
        elif elapsed > timeout:
            status = 'timeout'
        else:
            status = answer
    elif code == 0 and ('UNSOLVED' in text or 'INDETERMINATE' in text):
        status = 'timeout' if elapsed >= timeout * 0.99 else 'unexpected_unknown'
    else:
        status = 'abnormal_exit'
    counters = {}
    for key in ('Conflicts', 'Decisions', 'Unit Propagations', 'Restarts', 'Rephases', 'Clause Reductions'):
        match = re.search(r'^' + re.escape(key) + r'\s*:\s*(\d+)', text, re.M)
        if match:
            counters[key] = int(match.group(1))
    return {'solver': name, 'status': status, 'exit_code': code,
            'wall_sec': elapsed, 'observed_wall_sec': observed,
            'user_sec': user_seconds, 'sys_sec': system_seconds, 'rss_kb': rss_kb,
            'model_valid': None, 'validation': None, 'counters': counters,
            'diagnostic': diagnostic, 'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}


def verify_model(cnf, model_path, uatu):
    variable_count = None
    declared_clauses = None
    with cnf.open() as source:
        for line in source:
            fields = line.split()
            if fields and fields[0] == 'p':
                if len(fields) != 4 or fields[1] != 'cnf':
                    raise ValueError('Invalid DIMACS header')
                variable_count, declared_clauses = map(int, fields[2:])
                break
    if variable_count is None:
        raise ValueError('Missing DIMACS header')
    assignment = bytearray(variable_count + 1)
    started = not uatu
    terminated = False
    assigned = 0
    with model_path.open(errors='strict') as source:
        for line in source:
            stripped = line.strip()
            if uatu and not started:
                if stripped == 'SATISFIABLE':
                    started = True
                continue
            if not stripped or stripped in ('SAT', 'SATISFIABLE'):
                continue
            fields = stripped.split()
            if fields and fields[0] == 'v':
                fields = fields[1:]
            try:
                literals = [int(token) for token in fields]
            except ValueError:
                continue
            for literal in literals:
                if literal == 0:
                    terminated = True
                    break
                variable = abs(literal)
                if variable < 1 or variable > variable_count:
                    raise ValueError('Model variable out of range')
                value = 1 if literal > 0 else 2
                if assignment[variable] not in (0, value):
                    raise ValueError('Conflicting model assignments')
                if assignment[variable] == 0:
                    assigned += 1
                assignment[variable] = value
            if terminated:
                break
    if not terminated:
        raise ValueError('Model has no terminating zero')
    checked = 0
    satisfied = False
    pending = False
    with cnf.open() as source:
        for line in source:
            stripped = line.strip()
            if not stripped or stripped[0] in 'cp':
                continue
            if stripped[0] == '%':
                break
            for token in stripped.split():
                literal = int(token)
                if literal == 0:
                    checked += 1
                    if not satisfied:
                        raise ValueError(f'Model falsifies or fails to satisfy original clause {checked}')
                    satisfied = False
                    pending = False
                else:
                    variable = abs(literal)
                    if variable < 1 or variable > variable_count:
                        raise ValueError('CNF variable out of range')
                    pending = True
                    if assignment[variable] == (1 if literal > 0 else 2):
                        satisfied = True
    if pending or checked != declared_clauses:
        raise ValueError(f'CNF clause count mismatch: {checked} versus {declared_clauses}')
    return {'variables': variable_count, 'assigned': assigned, 'clauses_checked': checked}


def main():
    index = int(sys.argv[1])
    manifest = json.loads(Path('prepared/manifest.json').read_text())
    row = manifest[index]
    if row['index'] != index:
        raise RuntimeError('Manifest index mismatch')
    folder = Path('result')
    folder.mkdir(exist_ok=True)
    case = {'index': index, 'hash': row['hash'], 'filename': row['filename'],
            'expected': row['expected'], 'commit': '60e2f03e533d6d1c16995f119a876bae140bbdc5',
            'timeout_sec': TIMEOUT, 'memory_limit_bytes': MEMORY_BYTES,
            'runner': {'name': os.getenv('RUNNER_NAME'), 'arch': os.uname().machine,
                       'cpu': subprocess.check_output(['lscpu'], text=True),
                       'meminfo': Path('/proc/meminfo').read_text(),
                       'minisat_package': subprocess.check_output(['dpkg-query', '-W', 'minisat'], text=True).strip()},
            'results': []}
    Path('work').mkdir(exist_ok=True)
    archive = Path('work/instance.cnf.xz')
    cnf = Path('work/instance.cnf')
    try:
        subprocess.run(['curl', '-fL', '--retry', '5', '--retry-delay', '3',
                        '--connect-timeout', '30', '--max-time', '600',
                        row['url'], '-o', str(archive)], check=True, timeout=1000)
        with cnf.open('wb') as output:
            subprocess.run(['xz', '-dc', str(archive)], stdout=output, check=True, timeout=600)
        digest = hashlib.sha256()
        with cnf.open('rb') as source:
            for chunk in iter(lambda: source.read(4 * 1024**2), b''):
                digest.update(chunk)
        case['cnf_sha256'] = digest.hexdigest()
        case['cnf_bytes'] = cnf.stat().st_size
        archive.unlink()
        commands = {'ver4': ['./bin/ver4', str(cnf)],
                    'minisat': ['minisat', '-verb=0', str(cnf), 'work/minisat.model']}
        order = ['ver4', 'minisat'] if index % 2 == 0 else ['minisat', 'ver4']
        case['execution_order'] = order
        for name in order:
            measurement = measure(name, commands[name], folder, TIMEOUT)
            if measurement['status'] == 'sat':
                model_file = folder / 'ver4.log' if name == 'ver4' else Path('work/minisat.model')
                try:
                    measurement['model_details'] = verify_model(cnf, model_file, name == 'ver4')
                    measurement['model_valid'] = True
                    measurement['validation'] = 'original_cnf_model'
                except ValueError as error:
                    measurement['model_valid'] = False
                    measurement['status'] = 'wrong_model'
                    measurement['validation_error'] = str(error)
            if measurement['status'] in ('sat', 'unsat') and row['expected'] in ('sat', 'unsat'):
                if measurement['status'] != row['expected']:
                    measurement['claimed_result'] = measurement['status']
                    measurement['status'] = 'wrong_label'
                elif measurement['status'] == 'unsat':
                    measurement['validation'] = 'GBD_known_unsat_label'
            case['results'].append(measurement)
            (folder / 'result.json').write_text(json.dumps(case, indent=2) + '\n')
        answers = {r['solver']: r['status'] for r in case['results']}
        if set(answers.values()) == {'sat', 'unsat'}:
            case['disagreement'] = True
            for measurement in case['results']:
                if measurement['status'] == 'unsat':
                    measurement['status'] = 'wrong_unsat'
        else:
            case['disagreement'] = False
            for measurement in case['results']:
                if measurement['status'] == 'unsat' and measurement['validation'] is None:
                    measurement['validation'] = 'paired_unsat_agreement' if all(v == 'unsat' for v in answers.values()) else 'not_independently_confirmed'
        sanitizer = measure('sanitizer', ['./bin/ver4-sanitize', str(cnf)], folder, SANITIZER_TIMEOUT, True)
        if sanitizer['status'] == 'sat':
            try:
                verify_model(cnf, folder / 'sanitizer.log', True)
                sanitizer['model_valid'] = True
            except ValueError as error:
                sanitizer['status'] = 'wrong_model'
                sanitizer['validation_error'] = str(error)
        if sanitizer['status'] in ('sat', 'unsat') and row['expected'] in ('sat', 'unsat') and sanitizer['status'] != row['expected']:
            sanitizer['status'] = 'wrong_label'
        case['sanitizer'] = sanitizer
        case['completed'] = True
    except Exception as error:
        case['infrastructure_error'] = repr(error)
        case['completed'] = False
    (folder / 'result.json').write_text(json.dumps(case, indent=2) + '\n')
    summary = {key: value for key, value in case.items() if key != 'runner'}
    print('CASE_RESULT=' + json.dumps(summary, sort_keys=True))
    if not case['completed']:
        raise SystemExit(2)

if __name__ == '__main__':
    main()
