import sys


if len(sys.argv) != 3:
	raise SystemExit(f"usage: {sys.argv[0]} <solver-output> <cnf>")

outputPath, cnfPath = sys.argv[1:]
model = []
for line in open(outputPath, errors="ignore"):
	fields = line.split()
	if not fields or fields[-1] != "0":
		continue
	try:
		values = [int(value) for value in fields]
	except ValueError:
		continue
	if len(values) > 1:
		model = values[:-1]

assignment = {abs(value): value > 0 for value in model if value}
if not assignment:
	raise SystemExit("missing SAT model")

clause = []
with open(cnfPath, errors="ignore") as source:
	for line in source:
		stripped = line.strip()
		if not stripped or stripped[0] in "cp%":
			continue
		for token in stripped.split():
			literal = int(token)
			if literal == 0:
				if not any(
					assignment.get(abs(item), False) == (item > 0)
					for item in clause
				):
					raise SystemExit("invalid SAT model")
				clause.clear()
			else:
				clause.append(literal)
if clause:
	raise SystemExit("unterminated DIMACS clause")
