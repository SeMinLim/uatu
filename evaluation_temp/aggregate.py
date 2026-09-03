import csv
import json
from pathlib import Path

TIMEOUT_SEC = 1000.0
PAR2_PENALTY_SEC = 2000.0
VER4_COMMIT = 'e311f9f88c30753865465c9a9545707354ef8625'

rows = []
for path in Path('collected').rglob('result.csv'):
    with path.open(newline='') as source:
        rows.extend(csv.DictReader(source))
rows.sort(key=lambda row: int(row['index']))

if len(rows) != 100:
    raise SystemExit(f'expected 100 Ver4 results, found {len(rows)}')
if {int(row['index']) for row in rows} != set(range(100)):
    raise SystemExit('duplicate or missing Ver4 indices')

prior = list(csv.DictReader(Path('inputs/prior-raw.csv').open(newline='')))
minisat_rows = [row for row in prior if row['solver'] == 'minisat']
if len(minisat_rows) != 100:
    raise SystemExit(f'expected 100 MiniSAT rows, found {len(minisat_rows)}')


def summarize(data, solver):
    solved = [row for row in data if row['correct'] == '1']
    par2 = sum(
        min(float(row['wall_sec']), TIMEOUT_SEC)
        if row['correct'] == '1' else PAR2_PENALTY_SEC
        for row in data
    ) / len(data)
    return {
        'solver': solver,
        'benchmarks': len(data),
        'solved': len(solved),
        'sat_solved': sum(
            row['expected'] == 'sat' and row['correct'] == '1'
            for row in data
        ),
        'unsat_solved': sum(
            row['expected'] == 'unsat' and row['correct'] == '1'
            for row in data
        ),
        'timeouts': sum(row['result'] == 'timeout' for row in data),
        'wrong_answers': sum(
            row['result'] in ('sat', 'unsat') and row['correct'] != '1'
            for row in data
        ),
        'errors': sum(row['result'] == 'error' for row in data),
        'par2_sec': par2,
    }


minisat = summarize(minisat_rows, 'minisat')
ver4 = summarize(rows, 'ver4')

if minisat['solved'] != 46 or abs(minisat['par2_sec'] - 1173.1182) > 1e-6:
    raise SystemExit(f'unexpected MiniSAT baseline: {minisat}')
if ver4['errors'] != 0:
    error_rows = [row for row in rows if row['result'] == 'error']
    raise SystemExit('Ver4 still has execution errors: ' + json.dumps(error_rows))
if ver4['wrong_answers'] != 0:
    wrong_rows = [
        row for row in rows
        if row['result'] in ('sat', 'unsat') and row['correct'] != '1'
    ]
    raise SystemExit('Ver4 has wrong answers: ' + json.dumps(wrong_rows))

ver4['commit'] = VER4_COMMIT
ver4['vivification_runs'] = sum(int(row['vivification_runs']) for row in rows)
ver4['vivified_clauses'] = sum(int(row['vivified_clauses']) for row in rows)
ver4['vivified_literals'] = sum(int(row['vivified_literals']) for row in rows)

beats_minisat = ver4['par2_sec'] < minisat['par2_sec']
speedup = minisat['par2_sec'] / ver4['par2_sec']
relative = ver4['par2_sec'] / minisat['par2_sec']
difference = ver4['par2_sec'] - minisat['par2_sec']

summary = {
    'dataset': 'fixed-random 100 SAT Competition 2025 Main Track instances',
    'composition': {'sat': 50, 'unsat': 50},
    'timeout_sec': int(TIMEOUT_SEC),
    'par2_penalty_sec': int(PAR2_PENALTY_SEC),
    'minisat_baseline_reused': True,
    'beats_minisat': beats_minisat,
    'par2_speedup_over_minisat': speedup,
    'ver4_par2_relative_to_minisat': relative,
    'par2_difference_sec': difference,
    'minisat': minisat,
    'ver4': ver4,
}

Path('summary/decision.json').write_text(
    json.dumps(summary, indent=2) + '\n',
    encoding='utf-8',
)
with Path('summary/ver4_raw.csv').open('w', newline='') as output:
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)

report = [
    '# Uatu Ver4 Final vs MiniSAT',
    '',
    '- Dataset: fixed-random 100 SAT Competition 2025 Main Track instances',
    '- Composition: 50 SAT and 50 UNSAT',
    '- Timeout: 1,000 seconds per solver and benchmark',
    '- PAR-2 penalty: 2,000 seconds for timeout, error, or wrong answer',
    f'- Ver4 commit: `{VER4_COMMIT}`',
    '- MiniSAT baseline: reused from the identical 100-instance evaluation',
    '',
    '| Solver | Solved | SAT | UNSAT | Timeout | Wrong | Errors | PAR-2 (s) |',
    '|---|---:|---:|---:|---:|---:|---:|---:|',
    f"| MiniSAT | {minisat['solved']} | {minisat['sat_solved']} | {minisat['unsat_solved']} | {minisat['timeouts']} | {minisat['wrong_answers']} | {minisat['errors']} | {minisat['par2_sec']:.6f} |",
    f"| Uatu Ver4 | {ver4['solved']} | {ver4['sat_solved']} | {ver4['unsat_solved']} | {ver4['timeouts']} | {ver4['wrong_answers']} | {ver4['errors']} | {ver4['par2_sec']:.6f} |",
    '',
    f"MiniSAT exceeded: **{'YES' if beats_minisat else 'NO'}**",
    f"PAR-2 speedup over MiniSAT: **{speedup:.6f}x**",
    f"Ver4 PAR-2 relative to MiniSAT: **{relative:.6f}x**",
    f"PAR-2 difference, Ver4 minus MiniSAT: **{difference:.6f} seconds**",
]
Path('summary/report.md').write_text('\n'.join(report) + '\n', encoding='utf-8')
print('\n'.join(report))
