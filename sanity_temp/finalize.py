import json
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path

COMMIT = '60e2f03e533d6d1c16995f119a876bae140bbdc5'
manifest = json.loads(Path('prepared/manifest.json').read_text())
selection = json.loads(Path('prepared/selection.json').read_text())
paired = [json.loads(path.read_text()) for path in Path('paired').rglob('result.json')]
rechecks = [json.loads(path.read_text()) for path in Path('rechecks').rglob('sanitizer_result.json')]
for name, rows in [('paired', paired), ('sanitizer', rechecks)]:
    assert len(rows) == 100, (name, len(rows))
    assert {row['index'] for row in rows} == set(range(100)), name
    assert all(row['completed'] for row in rows), (name, [row['index'] for row in rows if not row['completed']])
    assert all(row['commit'] == COMMIT for row in rows), name
paired.sort(key=lambda row: row['index'])
rechecks.sort(key=lambda row: row['index'])
for release, sanitizer, selected in zip(paired, rechecks, manifest):
    assert release['index'] == sanitizer['index'] == selected['index']
    assert release['hash'] == sanitizer['hash'] == selected['hash']
    assert release['cnf_sha256'] == sanitizer['cnf_sha256']
    assert sorted(row['solver'] for row in release['results']) == ['minisat', 'ver4']
    assert release['timeout_sec'] == 1000 and sanitizer['timeout_sec'] == 30
    assert release['memory_limit_bytes'] == 12 * 1024**3

summary = {'commit': COMMIT, 'selection': selection, 'benchmarks': 100,
           'release_timeout_sec': 1000, 'penalty_sec': 2000,
           'release_address_space_limit_GiB': 12,
           'minisat_reused': False, 'paired_on_same_runner': True,
           'pair_order': 'alternating by sample index',
           'sanitizer_timeout_sec': 30, 'sanitizer_virtual_limit': 'unlimited',
           'sanitizer_rss_limit_GiB': 12, 'leak_sanitizer_enabled': False,
           'sanitizer_initial_harness_error': 'set_limits() executed in parent; corrected isolated recheck used',
           'runtime_errors': [], 'sanitizer_errors': [], 'disagreements': []}
score = {}
for name in ['ver4', 'minisat']:
    rows = []
    for case in paired:
        row = next(row for row in case['results'] if row['solver'] == name)
        rows.append(row)
        if row['status'] not in ('sat', 'unsat', 'timeout'):
            summary['runtime_errors'].append({'solver': name, 'index': case['index'],
                'hash': case['hash'], 'filename': case['filename'], 'status': row['status'],
                'exit_code': row['exit_code'], 'diagnostic': row['diagnostic'], 'rss_kb': row['rss_kb']})
    solved = [row for row in rows if row['status'] in ('sat', 'unsat')]
    assert all(0 <= row['wall_sec'] <= 1000 for row in solved)
    assert all(row['model_valid'] is True for row in solved if row['status'] == 'sat')
    solved_time = sum((Decimal(str(row['wall_sec'])) for row in solved), Decimal(0))
    score[name] = (solved_time + Decimal(2000) * (100 - len(solved))) / 100
    summary[name] = {'solved': len(solved), 'sat_solved': sum(row['status'] == 'sat' for row in rows),
                     'unsat_solved': sum(row['status'] == 'unsat' for row in rows),
                     'timeouts': sum(row['status'] == 'timeout' for row in rows),
                     'status_counts': dict(Counter(row['status'] for row in rows)),
                     'par2_sec': str(score[name]), 'solved_time_sum_sec': str(solved_time),
                     'unconfirmed_unsat': [case['index'] for case in paired
                         for row in case['results'] if row['solver'] == name and row.get('validation') == 'not_independently_confirmed']}
summary['par2_ver4_div_minisat'] = str(score['ver4'] / score['minisat'])
summary['par2_minisat_div_ver4'] = str(score['minisat'] / score['ver4'])
summary['par2_difference_sec'] = str(score['ver4'] - score['minisat'])
summary['ver4_par2_higher_percent'] = str((score['ver4'] / score['minisat'] - 1) * 100)
summary['sanitizer_status_counts'] = dict(Counter(case['result']['status'] for case in rechecks))
for case in rechecks:
    row = case['result']
    if row['status'] not in ('sat', 'unsat', 'timeout'):
        summary['sanitizer_errors'].append({'index': case['index'], 'hash': case['hash'],
            'filename': case['filename'], 'status': row['status'], 'exit_code': row['exit_code'],
            'diagnostic': row['diagnostic']})
summary['disagreements'] = [case['index'] for case in paired if case.get('disagreement')]
summary['has_observed_correctness_failure'] = any(row['status'].startswith('wrong') for row in summary['runtime_errors'] + summary['sanitizer_errors'])
summary['ver4_lower_par2'] = score['ver4'] < score['minisat']
summary['minisat_packages'] = sorted({case['runner']['minisat_package'] for case in paired})
cpus = set()
for case in paired:
    match = re.search(r'^Model name:\s*(.+)$', case['runner']['cpu'], re.M)
    if match:
        cpus.add(match.group(1).strip())
summary['cpu_models'] = sorted(cpus)
for root, filename, key in [('paired', 'result.json', 'initial_sanitizer_shadow_failures'),
                            ('rechecks', 'sanitizer_result.json', 'recheck_sanitizer_shadow_failures')]:
    count = 0
    for path in Path(root).rglob(filename):
        log = path.parent / 'sanitizer.log'
        if log.exists() and 'ReserveShadowMemoryRange failed' in log.read_text(errors='replace'):
            count += 1
    summary[key] = count
Path('final').mkdir(exist_ok=True)
Path('final/decision.json').write_text(json.dumps(summary, indent=2) + '\n')
print('VERIFIED_FINAL_SUMMARY_BEGIN')
print(json.dumps(summary, indent=2))
print('VERIFIED_FINAL_SUMMARY_END')
for root, filename in [('paired', 'result.json'), ('rechecks', 'sanitizer_result.json')]:
    for path in Path(root).rglob(filename):
        case = json.loads(path.read_text())
        rows = case['results'] if root == 'paired' else [case['result']]
        for row in rows:
            if row['status'] not in ('sat', 'unsat', 'timeout'):
                logname = row['solver'] + '.log'
                print('DIAGNOSTIC', case['index'], case['hash'], row['solver'], row['status'])
                print((path.parent / logname).read_text(errors='replace')[:12000])
