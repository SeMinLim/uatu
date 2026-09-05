import hashlib
import json
import os
import resource
import subprocess
import sys
from pathlib import Path

# Fix the evaluation harness, not the frozen solver or its measured release results.
path = Path('sanity_temp/run_case.py')
source = path.read_text()
old = 'preexec_fn=None if sanitizer else set_limits())'
new = 'preexec_fn=None if sanitizer else set_limits)'
if old in source:
    if source.count(old) != 1:
        raise RuntimeError('Ambiguous evaluation harness patch')
    path.write_text(source.replace(old, new))
from run_case import measure, verify_model

limits = resource.getrlimit(resource.RLIMIT_AS)
if limits[1] != resource.RLIM_INFINITY:
    raise RuntimeError(f'Sanitizer requires unlimited virtual address space, inherited {limits}')
resource.setrlimit(resource.RLIMIT_AS, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
folder = Path('sanitizer-result')
folder.mkdir(exist_ok=True)
Path('work').mkdir(exist_ok=True)
index_arg = sys.argv[1]
if index_arg == 'probe':
    cnf = Path('work/tiny.cnf')
    cnf.write_text('p cnf 1 1\n1 0\n')
    result = measure('sanitizer', ['./bin/ver4-sanitize', str(cnf)], folder, 10.0, True)
    print('SANITIZER_PROBE=' + json.dumps(result, sort_keys=True))
    print((folder / 'sanitizer.log').read_text(errors='replace'))
    if result['status'] != 'sat':
        raise RuntimeError('Clean sanitizer startup probe failed')
    verify_model(cnf, folder / 'sanitizer.log', True)
    raise SystemExit(0)

index = int(index_arg)
manifest = json.loads(Path('prepared/manifest.json').read_text())
row = manifest[index]
if row['index'] != index:
    raise RuntimeError('Manifest mismatch')
case = {'index': index, 'hash': row['hash'], 'filename': row['filename'], 'expected': row['expected'],
        'commit': '60e2f03e533d6d1c16995f119a876bae140bbdc5',
        'timeout_sec': 30, 'rss_limit_bytes': 12 * 1024**3, 'virtual_limit': 'unlimited',
        'sanitizer_binary_sha256': hashlib.sha256(Path('bin/ver4-sanitize').read_bytes()).hexdigest(),
        'completed': False}
try:
    archive = Path('work/input.cnf.xz')
    cnf = Path('work/input.cnf')
    subprocess.run(['curl', '-fL', '--retry', '5', '--retry-delay', '3', '--connect-timeout', '30',
                    '--max-time', '600', row['url'], '-o', str(archive)], check=True, timeout=1000)
    with cnf.open('wb') as output:
        subprocess.run(['xz', '-dc', str(archive)], stdout=output, check=True, timeout=600)
    archive.unlink()
    digest = hashlib.sha256()
    with cnf.open('rb') as source:
        for chunk in iter(lambda: source.read(4 * 1024**2), b''):
            digest.update(chunk)
    case['cnf_sha256'] = digest.hexdigest()
    result = measure('sanitizer', ['./bin/ver4-sanitize', str(cnf)], folder, 30.0, True)
    if result['status'] == 'sat':
        try:
            result['model_details'] = verify_model(cnf, folder / 'sanitizer.log', True)
            result['model_valid'] = True
        except ValueError as error:
            result['status'] = 'wrong_model'
            result['validation_error'] = str(error)
    if result['status'] in ('sat', 'unsat') and row['expected'] in ('sat', 'unsat') and result['status'] != row['expected']:
        result['claimed_result'] = result['status']
        result['status'] = 'wrong_label'
    case['result'] = result
    case['completed'] = True
    if result['status'] not in ('sat', 'unsat', 'timeout'):
        print('SANITIZER_DIAGNOSTIC_BEGIN')
        print((folder / 'sanitizer.log').read_text(errors='replace'))
        print('SANITIZER_DIAGNOSTIC_END')
except Exception as error:
    case['infrastructure_error'] = repr(error)
(folder / 'sanitizer_result.json').write_text(json.dumps(case, indent=2) + '\n')
print('SANITIZER_CASE=' + json.dumps(case, sort_keys=True))
if not case['completed']:
    raise SystemExit(2)
