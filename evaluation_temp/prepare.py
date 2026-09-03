import csv
import json
import os
from pathlib import Path

manifest = list(csv.DictReader(Path('prepared/manifest.csv').open(newline='')))
if len(manifest) != 100:
    raise SystemExit(f'expected 100 benchmarks, found {len(manifest)}')
if len({row['hash'] for row in manifest}) != 100:
    raise SystemExit('benchmark hashes are not unique')
if sum(row['expected'] == 'sat' for row in manifest) != 50:
    raise SystemExit('expected 50 SAT benchmarks')
if sum(row['expected'] == 'unsat' for row in manifest) != 50:
    raise SystemExit('expected 50 UNSAT benchmarks')

prior = list(csv.DictReader(Path('prepared/prior-raw.csv').open(newline='')))
minisat = [row for row in prior if row['solver'] == 'minisat']
if len(minisat) != 100:
    raise SystemExit(f'expected 100 MiniSAT rows, found {len(minisat)}')

solved = [row for row in minisat if row['correct'] == '1']
par2 = sum(
    min(float(row['wall_sec']), 1000.0) if row['correct'] == '1' else 2000.0
    for row in minisat
) / 100.0
if len(solved) != 46 or abs(par2 - 1173.1182) > 1e-6:
    raise SystemExit(f'unexpected MiniSAT baseline: solved={len(solved)}, par2={par2}')

matrix = [
    {
        'index': int(row['index']),
        'expected': row['expected'],
        'hash': row['hash'],
        'url': row['url'],
    }
    for row in manifest
]
with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
    output.write('matrix=' + json.dumps(matrix, separators=(',', ':')) + '\n')
