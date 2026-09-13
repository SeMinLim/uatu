#!/usr/bin/env python3
"""Validate one frozen SAT Competition 2025 sample, preserving process evidence."""
import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path
import platform
import resource
import signal
import subprocess
import sys
import time
import urllib.request

HERE = Path(__file__).resolve().parent
TIMEOUT_SECONDS = 1000.0
MEMORY_BYTES = 12 * 1024**3
SAMPLE_COUNT = 50
SOLVER_BASE_COMMIT = '362ceb9ed729c220c7233bd595528248aaddf90a'
GLUCOSE_COMMIT = '084d7375975408a06a1397cc4bc645a73b97fa65'


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def source_manifest(directory):
    files = sorted(path for path in directory.rglob('*')
                   if path.is_file() and (path.name == 'Makefile' or path.suffix in ('.cpp', '.h')))
    return {str(path.relative_to(directory)): sha256(path) for path in files}


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def capture(command):
    run = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=True)
    return run.stdout.strip()


def utc_now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def download_input(item, work):
    archive = work / 'input.cnf.xz'
    temporary = work / 'input.download'
    for attempt in range(4):
        try:
            request = urllib.request.Request(item['url'], headers={'User-Agent': 'Mozilla/5.0 Uatu-validation/2.0'})
            with urllib.request.urlopen(request, timeout=120) as src, temporary.open('wb') as dst:
                headers = dict(src.headers)
                length = src.headers.get('Content-Length')
                while True:
                    block = src.read(1024 * 1024)
                    if not block:
                        break
                    dst.write(block)
            with temporary.open('rb') as stream:
                if stream.read(6) != b'\xfd7zXZ\x00':
                    raise RuntimeError('download is not an xz archive')
            if length is not None and temporary.stat().st_size != int(length):
                raise RuntimeError('incomplete HTTP response')
            temporary.replace(archive)
            break
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    cnf = work / 'input.cnf'
    with lzma.open(archive, 'rb') as src, cnf.open('wb') as dst:
        while True:
            block = src.read(1024 * 1024)
            if not block:
                break
            dst.write(block)
    metadata = {
        'url': item['url'], 'gbd_hash': item['hash'], 'response_headers': headers,
        'compressed_bytes': archive.stat().st_size, 'compressed_sha256': sha256(archive),
        'cnf_bytes': cnf.stat().st_size, 'cnf_sha256': sha256(cnf),
        'identity_basis': 'Frozen GBD download URL; archive and decompressed bytes SHA-256 recorded. GBD normalized hash is not recomputed.'
    }
    archive.unlink()
    return cnf, metadata


def inspect_log(output, kind):
    statuses = set()
    counters = {}
    resource_lines = []
    with output.open(errors='replace') as stream:
        for raw_line in stream:
            line = raw_line.rstrip('\r\n')
            if line in ('SATISFIABLE', 'UNSATISFIABLE', 's SATISFIABLE', 's UNSATISFIABLE'):
                statuses.add(line)
            if line.startswith(('c OUT OF MEMORY during ', 'c RESOURCE LIMIT: container size exceeded during ')):
                resource_lines.append(line)
            if kind == 'reference' and line == 'INDETERMINATE':
                resource_lines.append(line)
            if kind == 'uatu' and ':' in line:
                key, value = line.rsplit(':', 1)
                try:
                    counters[key.strip()] = float(value.strip()) if '.' in value else int(value.strip())
                except ValueError:
                    pass
    return statuses, counters, resource_lines


def run_solver(command, output, kind):
    env = {key: value for key, value in os.environ.items() if not key.startswith('UATU_')}
    env.update(UATU_TIMEOUT_SEC='1000000000', UATU_PRINT_MODEL='1', OMP_NUM_THREADS='1')
    cpu = min(os.sched_getaffinity(0))

    def child_limits():
        os.sched_setaffinity(0, {cpu})
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    started = utc_now()
    with output.open('wb') as log:
        begin = time.monotonic()
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env,
                                   preexec_fn=child_limits, start_new_session=True)
        timed_out = False
        try:
            while True:
                pid, wait_status, usage = os.wait4(process.pid, os.WNOHANG)
                elapsed = time.monotonic() - begin
                if pid:
                    break
                if elapsed >= TIMEOUT_SECONDS:
                    timed_out = True
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    _, wait_status, usage = os.wait4(process.pid, 0)
                    elapsed = time.monotonic() - begin
                    break
                time.sleep(0.005)
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            raise
        process.returncode = os.waitstatus_to_exitcode(wait_status)
    code = process.returncode
    statuses, counters, resource_lines = inspect_log(output, kind)
    expected_sat = {'SATISFIABLE'} if kind == 'uatu' else {'s SATISFIABLE'}
    expected_unsat = {'UNSATISFIABLE'} if kind == 'uatu' else {'s UNSATISFIABLE'}
    outcome, resource_reason = 'execution_error', None
    if timed_out or elapsed > TIMEOUT_SECONDS:
        outcome = 'timeout'
    elif code == 10 and statuses == expected_sat:
        outcome = 'sat'
    elif code == 20 and statuses == expected_unsat:
        outcome = 'unsat'
    elif code == 0 and not statuses and resource_lines:
        outcome = 'resource_limit'
        resource_reason = ('Uatu allocation/container limit diagnostic' if kind == 'uatu' else
                           'Pinned Glucose OutOfMemoryException diagnostic, simp/Main.cc lines 301-304')
    return {
        'command': command, 'started_utc': started, 'completed_utc': utc_now(),
        'outcome': outcome, 'returncode': code, 'external_timeout': timed_out,
        'wall_seconds': elapsed, 'user_seconds': usage.ru_utime, 'system_seconds': usage.ru_stime,
        'max_rss_kib': usage.ru_maxrss, 'cpu_affinity': cpu,
        'timeout_seconds': TIMEOUT_SECONDS, 'memory_limit_bytes': MEMORY_BYTES,
        'resource_reason': resource_reason, 'resource_diagnostics': resource_lines,
        'log_sha256': sha256(output), 'counters': counters, 'validation': 'pending'
    }


def check_model(checker, cnf, model, format_name):
    checked = subprocess.run([str(checker), str(cnf), str(model), format_name],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=300)
    return {
        'returncode': checked.returncode, 'output': checked.stdout,
        'model_sha256': sha256(model), 'input_sha256': sha256(cnf),
        'checker_sha256': sha256(HERE / 'validate_model.cpp'),
        'checker_binary_sha256': sha256(checker)
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=int, required=True)
    parser.add_argument('--output', type=Path, default=Path('benchmark-output'))
    parser.add_argument('--solver-dir', type=Path, default=Path.cwd() / 'cpu/ver_5')
    parser.add_argument('--glucose-dir', type=Path, default=Path.cwd() / 'glucose-source')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'result.json').exists():
        raise RuntimeError('result.json already exists; use a new output directory to preserve the original attempt')
    work = out / 'work'
    work.mkdir(exist_ok=True)
    result = {'index': args.index, 'validation': 'pending', 'started_utc': utc_now(),
              'solver_base_commit': SOLVER_BASE_COMMIT, 'github_run_id': os.environ.get('GITHUB_RUN_ID'),
              'github_run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT')}
    write_json(out / 'result.json', result)
    try:
        sample = json.loads((HERE / 'sample.json').read_text())
        sampling = json.loads((HERE / 'sampling.json').read_text())
        assert len(sample) == SAMPLE_COUNT and 0 <= args.index < SAMPLE_COUNT
        assert sha256(HERE / 'sample.json') == sampling['sample_sha256']
        assert len({item['hash'] for item in sample}) == SAMPLE_COUNT
        item = sample[args.index]
        assert item['index'] == args.index and item['expected'] in ('sat', 'unsat', 'unknown')
        assert item['url'] == 'https://benchmark-database.de/file/' + item['hash'] + '?context=cnf'
        solver_dir = args.solver_dir.resolve()
        manifest = source_manifest(solver_dir)
        assert manifest == json.loads((HERE / 'expected_source_manifest.json').read_text())
        binary = solver_dir / 'obj/uatu_solver'
        checker = work / 'validate_model'
        subprocess.run(['g++', '-O2', '-std=c++17', '-Wall', '-Wextra', '-Wpedantic',
                        str(HERE / 'validate_model.cpp'), '-o', str(checker)], check=True)
        result.update({
            'benchmark': item, 'sampling': sampling, 'source_directory': 'cpu/ver_5',
            'source_commit': capture(['git', '-C', str(solver_dir), 'rev-parse', 'HEAD']),
            'source_manifest': manifest, 'source_manifest_sha256': canonical_digest(manifest),
            'binary_sha256': {'uatu': sha256(binary)}, 'checker_sha256': sha256(HERE / 'validate_model.cpp'),
            'checker_binary_sha256': sha256(checker), 'evaluator_sha256': sha256(Path(__file__)),
            'build_command': 'make -C cpu/ver_5 release',
            'timeout_basis': '1000 wall-clock seconds from launch to exit, including parsing, preprocessing and model output; excludes download, decompression and model checking',
            'environment': {'platform': platform.platform(), 'cpu': capture(['lscpu']),
                            'compiler': capture(['g++', '--version']), 'memory': capture(['free', '-b']),
                            'runner_os': os.environ.get('RUNNER_OS'), 'image_version': os.environ.get('ImageVersion'),
                            'python': sys.version, 'memory_limit_kind': 'RLIMIT_AS',
                            'timing_poll_interval_seconds': 0.005},
            'validation_definition': 'SAT model checked against every original clause; UNSAT compared with known GBD status or pinned Glucose 4.2.1. No UNSAT proof checking. Timeout and memory limit are unresolved.'
        })
        write_json(out / 'result.json', result)
        cnf, result['input'] = download_input(item, work)
        command = [str(binary), str(cnf)]
        result['uatu'] = {'command': command, 'validation': 'pending', 'state': 'ready_to_run'}
        write_json(out / 'result.json', result)
        record = run_solver(command, out / 'uatu.log', 'uatu')
        result['uatu'] = record
        write_json(out / 'result.json', result)
        print(json.dumps({'index': args.index, 'outcome': record['outcome'],
                          'wall_seconds': record['wall_seconds']}), flush=True)
        outcome = record['outcome']
        if outcome in ('timeout', 'resource_limit'):
            record['validation'] = 'unresolved'
        elif outcome == 'execution_error':
            record['validation'] = 'execution_error'
        else:
            # Check returned SAT models even if their verdict contradicts metadata.
            if outcome == 'sat':
                record['model_check'] = check_model(checker, cnf, out / 'uatu.log', 'uatu')
                record['validation'] = ('validated_sat_model' if record['model_check']['returncode'] == 0 else 'invalid_model')
            elif item['expected'] == 'unsat':
                record['validation'] = 'matches_known_unsat'
            if item['expected'] in ('sat', 'unsat') and outcome != item['expected']:
                record['validation'] = 'wrong_result'
                record['contradiction'] = 'Returned verdict contradicts frozen GBD metadata'
            elif outcome == 'unsat' and item['expected'] == 'unknown':
                # The reference is evidence only for an otherwise unverified UNSAT answer.
                glucose_dir = args.glucose_dir.resolve()
                glucose = glucose_dir / 'simp/glucose'
                assert capture(['git', '-C', str(glucose_dir), 'rev-parse', 'HEAD']) == GLUCOSE_COMMIT
                assert not capture(['git', '-C', str(glucose_dir), 'diff', '--name-only'])
                reference_manifest = {str(path.relative_to(glucose_dir)): sha256(path)
                                      for path in sorted(glucose_dir.rglob('*'))
                                      if path.is_file() and (path.name == 'Makefile' or path.suffix in ('.cc', '.h'))}
                reference_command = [str(glucose), '-verb=0', str(cnf), str(out / 'glucose.model')]
                result['reference_commit'] = GLUCOSE_COMMIT
                result['reference_source_manifest'] = reference_manifest
                result['binary_sha256']['reference'] = sha256(glucose)
                result['reference'] = {'command': reference_command, 'validation': 'pending', 'state': 'ready_to_run'}
                write_json(out / 'result.json', result)
                reference = run_solver(reference_command, out / 'glucose.log', 'reference')
                result['reference'] = reference
                if reference['outcome'] == 'unsat':
                    reference['validation'] = 'corroborates_uatu_unsat'
                    record['validation'] = 'matches_reference_unsat'
                elif reference['outcome'] == 'sat':
                    # Upstream Glucose writes assignments without a SAT header to its result file.
                    normalized = out / 'glucose-check.model'
                    with normalized.open('wb') as dst, (out / 'glucose.model').open('rb') as src:
                        dst.write(b'SAT\n')
                        for block in iter(lambda: src.read(1024 * 1024), b''):
                            dst.write(block)
                    reference['model_check'] = check_model(checker, cnf, normalized, 'minisat')
                    reference['model_normalization'] = 'Prepended SAT header to unchanged Glucose result-file assignments'
                    reference['validation'] = ('validated_sat_model' if reference['model_check']['returncode'] == 0 else 'invalid_model')
                    if reference['model_check']['returncode'] == 0:
                        record['validation'] = 'wrong_result'
                        record['contradiction'] = 'Uatu UNSAT contradicts the validated SAT model returned by pinned Glucose'
                    else:
                        record['validation'] = 'unverified_unsat'
                        record['disagreement'] = 'Pinned Glucose returned SAT with an invalid model; Uatu UNSAT remains unverified'
                else:
                    reference['validation'] = ('execution_error' if reference['outcome'] == 'execution_error' else 'unresolved')
                    record['validation'] = 'unverified_unsat'
        good = {'validated_sat_model', 'matches_known_unsat', 'matches_reference_unsat', 'unresolved'}
        result['validation'] = ('complete' if record['validation'] in good else
                                'unverified' if record['validation'] == 'unverified_unsat' else 'invalid')
        write_json(out / 'result.json', result)
        cnf.unlink()
        checker.unlink()
        work.rmdir()
    except Exception as error:
        result['validation'] = 'infrastructure_error'
        result['error'] = repr(error)
    result['completed_utc'] = utc_now()
    result['artifact_sha256'] = {path.name: sha256(path) for path in sorted(out.iterdir())
                                if path.is_file() and path.suffix in ('.log', '.model')}
    write_json(out / 'result.json', result)
    print(json.dumps({'index': args.index, 'validation': result['validation']}), flush=True)
    return 0 if result['validation'] == 'complete' else 1


if __name__ == '__main__':
    sys.exit(main())
