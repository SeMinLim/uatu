import sys
from pathlib import Path

output_path, cnf_path = sys.argv[1:]
lines = Path(output_path).read_text(errors='ignore').splitlines()
try:
    status_index = lines.index('SATISFIABLE')
except ValueError:
    raise SystemExit(1)

model = None
for line in lines[status_index + 1:]:
    fields = line.split()
    try:
        values = [int(field) for field in fields]
    except ValueError:
        continue
    if len(values) > 1 and values[-1] == 0:
        model = values[:-1]
        break
if model is None:
    raise SystemExit(1)

assignment = {abs(literal): literal > 0 for literal in model if literal}
if not assignment:
    raise SystemExit(1)

clause = []
with open(cnf_path, errors='ignore') as source:
    for line in source:
        stripped = line.strip()
        if not stripped or stripped[0] in 'cp%':
            continue
        for token in stripped.split():
            literal = int(token)
            if literal == 0:
                if not clause:
                    raise SystemExit(1)
                if not any(
                    assignment.get(abs(item), False) == (item > 0)
                    for item in clause
                ):
                    raise SystemExit(1)
                clause.clear()
            else:
                clause.append(literal)
if clause:
    raise SystemExit(1)
