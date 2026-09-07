#!/usr/bin/env python3
"""Validate one frozen SAT Competition 2025 sample on the current ver_5."""
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

TIMEOUT = 1000.0
MEMORY_BYTES = 12 * 1024**3
HERE = Path(__file__).resolve().parent
REPO = Path.cwd()
SOURCES = ['Makefile', 'solver.h', 'solver.cpp', 'main.cpp']


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as src:
        for block in iter(lambda: src.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def capture(command):
    run = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return run.stdout.strip()


def download_input(item, work):
    archive = work / 'input.cnf.xz'
    compressed = work / 'input.download'
    error = None
    for attempt in range(4):
        try:
            request = urllib.request.Request(item['url'], headers={'User-Agent':'Uatu-validation/1.0'})
            with urllib.request.urlopen(request, timeout=120) as src, compressed.open('wb') as dst:
                headers = dict(src.headers)
                while True:
                    data = src.read(1024 * 1024)
                    if not data:
                        break
                    dst.write(data)
            with compressed.open('rb') as stream:
                magic = stream.read(6)
            if magic != b'\xfd7zXZ\x00':
                raise RuntimeError('download is not an xz archive')
            if 'Content-Length' in headers and compressed.stat().st_size != int(headers['Content-Length']):
                raise RuntimeError('incomplete HTTP response')
            compressed.replace(archive)
            error = None
            break
        except Exception as exc:
            error = exc
            time.sleep(2 ** attempt)
    if error is not None:
        raise RuntimeError('input download failed: ' + repr(error))
    cnf = work / 'input.cnf'
    with lzma.open(archive, 'rb') as src, cnf.open('wb') as dst:
        while True:
            data = src.read(1024 * 1024)
            if not data:
                break
            dst.write(data)
    metadata = {
        'url':item['url'], 'response_headers':headers,
        'compressed_bytes':archive.stat().st_size, 'compressed_sha256':sha256(archive),
        'cnf_bytes':cnf.stat().st_size, 'cnf_sha256':sha256(cnf)
    }
    archive.unlink()
    return cnf, metadata


def run_solver(command, output, uatu):
    env = {key:value for key,value in os.environ.items() if not key.startswith('UATU_')}
    env.update(UATU_TIMEOUT_SEC='1000', UATU_PRINT_MODEL='1', OMP_NUM_THREADS='1')
    cpu = min(os.sched_getaffinity(0))
    def child_limits():
        os.sched_setaffinity(0, {cpu})
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    started = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    with output.open('wb') as log:
        begin = time.monotonic()
        proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                env=env, preexec_fn=child_limits, start_new_session=True)
        timed_out = False
        while True:
            pid, wait_status, usage = os.wait4(proc.pid, os.WNOHANG)
            elapsed = time.monotonic() - begin
            if pid:
                break
            if elapsed >= TIMEOUT:
                timed_out = True
                os.killpg(proc.pid, signal.SIGKILL)
                _, wait_status, usage = os.wait4(proc.pid, 0)
                elapsed = time.monotonic() - begin
                break
            time.sleep(0.02)
        proc.returncode = os.waitstatus_to_exitcode(wait_status)
    code = proc.returncode
    text = output.read_text(errors='replace')
    lines = set(text.splitlines())
    if timed_out or elapsed > TIMEOUT:
        outcome = 'timeout'
    elif code == 10 and 'SATISFIABLE' in lines:
        outcome = 'sat'
    elif code == 20 and 'UNSATISFIABLE' in lines:
        outcome = 'unsat'
    elif 'OUT OF MEMORY' in text or 'RESOURCE LIMIT' in text:
        outcome = 'resource_limit'
    elif code == 0 and 'UNSOLVED' in lines and usage.ru_utime >= TIMEOUT - 1:
        outcome = 'timeout'
    else:
        outcome = 'execution_error'
    counters = {}
    if uatu:
        for line in text.splitlines():
            if ':' not in line:
                continue
            key, value = line.rsplit(':', 1)
            try:
                counters[key.strip()] = float(value.strip()) if '.' in value else int(value.strip())
            except ValueError:
                pass
    return {
        'command':command, 'started_utc':started, 'outcome':outcome, 'returncode':code,
        'external_timeout':timed_out, 'wall_seconds':elapsed,
        'user_seconds':usage.ru_utime, 'system_seconds':usage.ru_stime,
        'max_rss_kib':usage.ru_maxrss, 'cpu_affinity':cpu,
        'timeout_seconds':TIMEOUT, 'memory_limit_bytes':MEMORY_BYTES,
        'log_sha256':sha256(output), 'counters':counters
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--index', type=int, required=True)
    parser.add_argument('--output', type=Path, default=Path('validation-output'))
    parser.add_argument('--solver-dir', type=Path, default=HERE/'candidate')
    args = parser.parse_args()
    sample = json.loads((HERE / 'sample.json').read_text())
    sampling = json.loads((HERE / 'sampling.json').read_text())
    assert len(sample) == 50 and 0 <= args.index < len(sample)
    assert sha256(HERE / 'sample.json') == sampling['sample_sha256']
    item = sample[args.index]
    assert item['index'] == args.index
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = out / 'work'
    work.mkdir(exist_ok=True)
    solver_dir = args.solver_dir.resolve()
    manifest = {name:sha256(solver_dir / name) for name in SOURCES}
    manifest_hash = hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    binary = solver_dir / 'obj/uatu_solver'
    checker = work / 'validate_model'
    subprocess.run(['g++','-O2','-std=c++17','-Wall','-Wextra','-Wpedantic',
                    str(HERE/'validate_model.cpp'),'-o',str(checker)], check=True)
    result = {
        'index':args.index, 'benchmark':item, 'sampling':sampling,
        'source_commit':capture(['git','rev-parse','HEAD']),
        'source_manifest':manifest, 'source_manifest_sha256':manifest_hash,
        'binary_sha256':sha256(binary), 'checker_sha256':sha256(HERE/'validate_model.cpp'),
        'evaluator_sha256':sha256(Path(__file__)),
        'github_run_id':os.environ.get('GITHUB_RUN_ID'),
        'github_run_attempt':os.environ.get('GITHUB_RUN_ATTEMPT'),
        'environment':{'platform':platform.platform(), 'cpu':capture(['lscpu']),
                       'compiler':capture(['g++','--version']),
                       'minisat_package':capture(['dpkg-query','-W','minisat'])},
        'validation':'pending'
    }
    write_json(out/'result.json',result)
    try:
        cnf, result['input'] = download_input(item, work)
        record = run_solver([str(binary),str(cnf)], out/'uatu.log', True)
        result['uatu'] = record
        outcome = record['outcome']
        expected = item['expected']
        if outcome in ('timeout','resource_limit'):
            result['validation'] = 'unresolved'
        elif outcome == 'execution_error':
            result['validation'] = 'execution_error'
        elif expected in ('sat','unsat') and outcome != expected:
            result['validation'] = 'wrong_result'
        elif outcome == 'sat':
            checked = subprocess.run([str(checker),str(cnf),str(out/'uatu.log'),'uatu'],
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,text=True)
            result['model_check'] = {'returncode':checked.returncode, 'output':checked.stdout}
            result['validation'] = 'validated_sat_model' if checked.returncode == 0 else 'invalid_model'
        elif expected == 'unsat':
            result['validation'] = 'matches_known_unsat'
        else:
            model = out/'minisat.model'
            oracle = run_solver(['minisat','-verb=0',str(cnf),str(model)],out/'minisat.log',False)
            result['unsat_oracle'] = oracle
            if oracle['outcome'] == 'unsat':
                result['validation'] = 'matches_minisat_unsat'
            elif oracle['outcome'] == 'sat':
                checked = subprocess.run([str(checker),str(cnf),str(model),'minisat'],
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,text=True)
                result['oracle_model_check'] = {'returncode':checked.returncode,'output':checked.stdout}
                result['validation'] = 'wrong_result' if checked.returncode == 0 else 'oracle_error'
            else:
                result['validation'] = 'unverified_unsat'
        result['completed_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
        cnf.unlink()
        checker.unlink()
        work.rmdir()
    except Exception as exc:
        result['validation'] = 'infrastructure_error'
        result['error'] = repr(exc)
    write_json(out/'result.json', result)
    print(json.dumps({'index':args.index, 'hash':item['hash'],
                      'outcome':result.get('uatu',{}).get('outcome'),
                      'validation':result['validation']}),flush=True)
    good = ('validated_sat_model','matches_known_unsat','matches_minisat_unsat','unresolved')
    return 0 if result['validation'] in good else 1


if __name__ == '__main__':
    sys.exit(main())
