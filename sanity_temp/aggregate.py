import json
from collections import Counter
from pathlib import Path

manifest = json.loads(Path('prepared/manifest.json').read_text())
selection = json.loads(Path('prepared/selection.json').read_text())
cases = []
for path in Path('collected').rglob('result.json'):
    cases.append(json.loads(path.read_text()))
cases.sort(key=lambda row: row['index'])
if len(cases) != 100 or {row['index'] for row in cases} != set(range(100)):
    present = {row['index'] for row in cases}
    raise RuntimeError(f'Incomplete evaluation: {len(cases)}/100, missing={sorted(set(range(100)) - present)}')
for case in cases:
    expected = manifest[case['index']]
    if case['hash'] != expected['hash'] or not case.get('completed'):
        raise RuntimeError(f'Incomplete or mismatched benchmark: {case["index"]}, {case.get("infrastructure_error")}')
    if case['commit'] != '60e2f03e533d6d1c16995f119a876bae140bbdc5':
        raise RuntimeError('Solver version changed during evaluation')
    if sorted(row['solver'] for row in case['results']) != ['minisat', 'ver4']:
        raise RuntimeError('Missing paired solver result')

summary = {'commit': cases[0]['commit'], 'selection': selection, 'benchmarks': 100,
           'timeout_sec': 1000, 'par2_penalty_sec': 2000,
           'memory_limit_bytes': cases[0]['memory_limit_bytes'],
           'minisat_baseline_reused': False, 'max_parallel_pairs': 20,
           'sanitizer_timeout_sec': 30, 'leak_sanitizer_enabled': False}
failures = []
for solver in ('ver4', 'minisat'):
    rows = []
    for case in cases:
        entry = next(row for row in case['results'] if row['solver'] == solver)
        rows.append(entry)
        if entry['status'] not in ('sat', 'unsat', 'timeout'):
            failures.append({'index': case['index'], 'hash': case['hash'], 'filename': case['filename'], **entry})
    solved = [row for row in rows if row['status'] in ('sat', 'unsat')]
    par2 = sum(row['wall_sec'] if row['status'] in ('sat', 'unsat') else 2000.0 for row in rows) / 100
    summary[solver] = {'solved': len(solved), 'sat_solved': sum(row['status'] == 'sat' for row in rows),
                       'unsat_solved': sum(row['status'] == 'unsat' for row in rows),
                       'status_counts': dict(Counter(row['status'] for row in rows)),
                       'par2_sec': par2, 'solved_time_sum_sec': sum(row['wall_sec'] for row in solved),
                       'validated_sat_models': sum(row['model_valid'] is True for row in rows),
                       'unconfirmed_unsat': sum(row.get('validation') == 'not_independently_confirmed' for row in rows)}
summary['sanitizer_status_counts'] = dict(Counter(case['sanitizer']['status'] for case in cases))
summary['sanitizer_failures'] = [
    {'index': case['index'], 'hash': case['hash'], **case['sanitizer']}
    for case in cases if case['sanitizer']['status'] not in ('sat', 'unsat', 'timeout')]
summary['runtime_failures'] = failures
summary['paired_disagreements'] = [case['index'] for case in cases if case['disagreement']]
summary['minisat_packages'] = sorted({case['runner']['minisat_package'] for case in cases})
summary['ver4_par2_div_minisat'] = summary['ver4']['par2_sec'] / summary['minisat']['par2_sec']
summary['minisat_par2_div_ver4'] = summary['minisat']['par2_sec'] / summary['ver4']['par2_sec']
summary['par2_difference_sec'] = summary['ver4']['par2_sec'] - summary['minisat']['par2_sec']
summary['has_correctness_failure'] = any(row['status'].startswith('wrong') for row in failures)
summary['beats_minisat'] = not summary['has_correctness_failure'] and summary['ver4']['par2_sec'] < summary['minisat']['par2_sec']
Path('summary').mkdir(exist_ok=True)
Path('summary/decision.json').write_text(json.dumps(summary, indent=2) + '\n')
Path('summary/all_cases.json').write_text(json.dumps(cases, indent=2) + '\n')
print('FINAL_SUMMARY_BEGIN')
print(json.dumps(summary, indent=2))
print('FINAL_SUMMARY_END')
