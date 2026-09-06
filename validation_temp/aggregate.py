import json
import math
from pathlib import Path

manifest = json.loads(Path('prepared/manifest.json').read_text())
rows = [json.loads(path.read_text()) for path in Path('collected').rglob('result.json')]
rows.sort(key=lambda row: row['index'])
assert len(rows) == 100, ('incomplete evaluation', len(rows))
assert [row['index'] for row in rows] == list(range(100)), 'duplicate or missing cases'
assert len({row['hash'] for row in rows}) == 100
assert len({row['source_sha256'] for row in rows}) == 1, 'mixed candidate source revisions'
for expected, measured in zip(manifest, rows):
    assert expected['index'] == measured['index'] and expected['hash'] == measured['hash']
    assert expected['expected'] == measured['expected']
    assert measured['timeout_sec'] == 1000 and measured['memory_bytes'] == 12*1024**3
    assert {m['solver'] for m in measured['measurements']} == {'minisat', 'ver5'}

summaries = {}
for name in ('minisat', 'ver5'):
    data = [next(m for m in row['measurements'] if m['solver'] == name) for row in rows]
    solved = [m for m in data if m['status'] in ('sat', 'unsat') and not m['invalid'] and m['wall_sec'] <= 1000]
    scores = [m['wall_sec'] if m in solved else 2000.0 for m in data]
    statuses = {}
    for m in data: statuses[m['status']] = statuses.get(m['status'], 0)+1
    summaries[name] = {'solved': len(solved), 'sat': sum(m['status']=='sat' for m in solved),
                       'unsat': sum(m['status']=='unsat' for m in solved), 'statuses': statuses,
                       'invalid_runs': sum(m['invalid'] for m in data),
                       'par2_sum_sec': math.fsum(scores), 'par2_mean_sec': math.fsum(scores)/100}
passed = all(row['all_checks_passed'] for row in rows)
minisat_score = summaries['minisat']['par2_mean_sec']
ver5_score = summaries['ver5']['par2_mean_sec']
report = {'cases': 100, 'selection': json.loads(Path('prepared/selection.json').read_text()),
          'timeout_sec': 1000, 'memory_gib': 12, 'both_solvers_freshly_measured': True,
          'paired_sequential_runs': True, 'source_sha256': rows[0]['source_sha256'],
          'all_checks_passed': passed, 'failed_cases': [r['index'] for r in rows if not r['all_checks_passed']],
          'results': summaries, 'beats_minisat': passed and ver5_score < minisat_score,
          'par2_ratio_minisat_over_ver5': minisat_score/ver5_score,
          'par2_difference_ver5_minus_minisat_sec': ver5_score-minisat_score,
          'minisat_versions': sorted({r['minisat_version'] for r in rows})}
Path('summary').mkdir(exist_ok=True)
Path('summary/report.json').write_text(json.dumps(report, indent=2)+'\n')
Path('summary/all-results.json').write_text(json.dumps(rows, indent=2)+'\n')
print('VER5_COMPLETE_100_COMPARISON_BEGIN')
print(json.dumps(report, indent=2))
print('VER5_COMPLETE_100_COMPARISON_END')
if not passed: raise SystemExit('Correctness gate failed; these are not validated final scores')
